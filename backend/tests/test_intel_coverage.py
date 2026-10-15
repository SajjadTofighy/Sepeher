"""Coverage from continuous GPS legs, with no incident or dispatch authority."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import sim, store
from app.intel import coverage, geo, worker
from app.main import app
from app.routers.incidents import dispatchable, patrol_vehicle
from app.core.seed import seed


@pytest.fixture
def case(track_database, monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    import app.main as main
    monkeypatch.setattr(main, "now", store.now)
    store.state.clear()
    store.state.update(seed())
    store.state["policies"] = []
    asset = store.state["assets"][0]
    asset.update(synthetic=True, track=[], report_interval=30)
    store.state["assets"] = [asset]
    store.state["pipelines"] = [dict(id="PIPE-TEST", name="خط آزمایشی", field=asset["field"],
                                    points=[[49.7795, 30.76], [49.7805, 30.76]])]
    store.state["segments"] = geo.derive_segments(store.state["pipelines"])
    store.state["facilities"] = []
    store.state["settings"]["intel_coverage_buffer_m"] = 10
    return clock, asset


def point(clock, lon=49.78, lat=30.76, seconds=0):
    return dict(lon=lon, lat=lat, time=sim.iso(clock.t + seconds))


def statuses(clock):
    return coverage.snapshot(sim.iso(clock.t))["items"]


def test_crossing_leg_marks_segment_visited(case):
    clock, asset = case
    asset["track"] = [point(clock, lat=30.759, seconds=-30), point(clock, lat=30.761)]
    coverage.tick(sim.iso(clock.t))
    row = statuses(clock)[0]
    assert row["status"] == "ok" and row["last_asset_id"] == asset["id"]
    assert row["last_visit"] and row["age_minutes"] <= 1


def test_one_kilometre_leg_interpolates_crossing_between_observations(case):
    clock, asset = case
    asset["track"] = [point(clock, lat=30.7555, seconds=-60), point(clock, lat=30.7645)]
    segment = store.state["segments"][0]
    assert all(geo.point_polyline_distance_m([p["lon"], p["lat"]], segment["points"]) > 400 for p in asset["track"])
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"
    assert statuses(clock)[0]["last_visit"] != asset["track"][-1]["time"]


@pytest.mark.parametrize("interval,gap,expected", [(30, 120, "ok"), (30, 121, "never"), (60, 180, "ok"), (60, 181, "never")])
def test_gap_above_shared_threshold_is_not_interpolated(case, interval, gap, expected):
    clock, asset = case
    asset["report_interval"] = interval
    asset["track"] = [point(clock, lat=30.7555, seconds=-gap), point(clock, lat=30.7645)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == expected


def test_facility_uses_its_radius_independently_of_pipeline_buffer(case):
    clock, asset = case
    store.state["segments"] = []
    store.state["facilities"] = [dict(id="FAC-TEST", name="چاه آزمایشی", field=asset["field"],
                                     lon=49.78, lat=30.76, radius_m=100, kind="well", unmanned=True)]
    asset["track"] = [point(clock, lat=30.761, seconds=-30)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "never"
    finding = store.state["findings"][0]
    assert finding["severity"] == "medium" and finding["mode"] == "shadow"
    asset["track"].append(point(clock, lat=30.7608))
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"
    assert finding["status"] == "resolved"


def test_stale_transition_latches_once_and_next_visit_resolves(case):
    clock, asset = case
    asset["track"] = [point(clock)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"
    clock.t += 12 * 3600
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"
    clock.t += 1
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "stale"
    assert len(store.state["findings"]) == 1
    finding = store.state["findings"][0]
    assert finding["kind"] == "coverage_gap" and finding["severity"] == "low"
    assert finding["evidence"]["values"]["geometry"]["type"] == "LineString"
    assert finding["evidence"]["values"]["last_asset_id"] == asset["id"]
    for _ in range(3):
        coverage.tick(sim.iso(clock.t))
    assert len(store.state["findings"]) == 1
    asset["track"].append(point(clock))
    coverage.tick(sim.iso(clock.t))
    assert finding["status"] == "resolved" and statuses(clock)[0]["status"] == "ok"
    assert len(store.state["findings"]) == 1


@pytest.mark.parametrize("kind,unit", [("person", "patrol"), ("vehicle", "org"), ("vehicle", "field")])
def test_non_patrol_assets_are_ignored(case, kind, unit):
    clock, asset = case
    asset.update(kind=kind, unit=unit, track=[point(clock)])
    coverage.tick(sim.iso(clock.t))
    assert not patrol_vehicle(asset)
    assert statuses(clock)[0]["status"] == "never"
    assert store.state["intel"]["coverage"]["cursors"] == {}


def test_busy_patrol_still_counts_for_coverage(case):
    clock, asset = case
    store.state["incidents"][0].update(assigned_to=asset["id"])
    assert not dispatchable(asset, store.state["incidents"][1])
    asset["track"] = [point(clock)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"


def test_incremental_cursor_does_not_reprocess_and_keeps_previous_leg(case):
    clock, asset = case
    asset["track"] = [point(clock, lat=30.7555)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "never"
    before = deepcopy(store.state)
    coverage.tick(sim.iso(clock.t))
    assert store.state == before
    clock.t += 60
    asset["track"] = [point(clock, lat=30.7645)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"
    assert store.state["intel"]["coverage"]["cursors"][asset["id"]]["point"] == asset["track"][-1]


def test_unmanned_facility_has_shorter_stale_threshold(case):
    clock, asset = case
    store.state["facilities"] = [dict(id="FAC-TEST", name="چاه آزمایشی", field=asset["field"],
                                     lon=49.78, lat=30.76, radius_m=100, kind="well", unmanned=True)]
    asset["track"] = [point(clock)]
    coverage.tick(sim.iso(clock.t))
    clock.t += 8 * 3600 + 1
    coverage.tick(sim.iso(clock.t))
    assert [row["status"] for row in statuses(clock)] == ["ok", "stale"]
    assert store.state["findings"][0]["subject_ids"] == ["FAC-TEST"]


def test_summary_and_api_use_computed_coverage_and_keep_sample_metrics(case):
    clock, asset = case
    store.state["facilities"] = [dict(id="FAC-TEST", name="چاه آزمایشی", field="کرنج",
                                     lon=50.2, lat=30.6, radius_m=100, kind="well", unmanned=True)]
    asset["track"] = [point(clock)]
    coverage.tick(sim.iso(clock.t))
    totals = coverage.snapshot(sim.iso(clock.t))["totals"]
    summary = store.summary()
    assert summary["coverage"] == totals["percent_ok"] == 50
    assert {f["name"]: f["coverage"] for f in summary["fields"]} == {"آغاجاری": 100, "کرنج": 0, "پارسی": 0}
    assert [f["events"] for f in summary["fields"]] == [12, 8, 5]
    assert summary["availability"] == 99.4 and summary["mock"]
    with TestClient(app) as client:
        data = client.get("/api/v1/intel/coverage").json()
        assert data["totals"] == totals
        assert set(data) == {"items", "totals"}
        answer = client.post("/api/v1/assistant", json={"question": "کدام تأسیسات بازدید نشده و پوشش ضعیف دارند؟"}).json()
        assert "چاه آزمایشی" in answer["answer"]
        assert answer["sources"] == [store.state["findings"][0]["id"]]
        assert answer["can_execute"] is False


def test_gaps_never_create_incidents_even_in_active_mode(case):
    clock, _ = case
    store.state["settings"].update(intel_coverage_mode="active", shadow_mode=False)
    before = deepcopy(store.state["incidents"])
    coverage.tick(sim.iso(clock.t))
    assert store.state["findings"][0]["mode"] == "active"
    assert store.state["findings"][0]["incident_id"] is None
    assert store.state["incidents"] == before and store.state["commands"] == []


def test_backfill_window_ignores_old_and_future_observations(case):
    clock, asset = case
    asset["track"] = [point(clock, seconds=-73 * 3600), point(clock, seconds=1)]
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "never"
    assert store.state["intel"]["coverage"]["cursors"] == {}


def test_worker_registered_and_backfill_after_reset(case, track_database):
    clock, _ = case
    assert coverage in worker.capabilities
    stamp = datetime.fromtimestamp(clock.t, timezone.utc) - timedelta(hours=2)
    track_database.append("AST-001", 49.78, 30.76, stamp, 0)
    with TestClient(app) as client:
        assert client.post("/api/v1/demo/reset").status_code == 200
        first = client.get("/api/v1/intel/coverage").json()
        visited = [row for row in first["items"] if row["last_asset_id"] == "AST-001"]
        assert visited and all(row["last_visit"] for row in visited)
        assert any(row["status"] == "ok" for row in first["items"])
        assert client.post("/api/v1/demo/reset").status_code == 200
        second = client.get("/api/v1/intel/coverage").json()
        assert second == first


def test_reported_source_change_restarts_cursor(case, track_database):
    clock, asset = case
    asset["track"] = [point(clock, lat=30.8)]
    coverage.tick(sim.iso(clock.t))
    asset.pop("synthetic")
    track_database.append(asset["id"], 49.78, 30.76, sim.iso(clock.t - 60), 0)
    store.refresh_track(asset)
    coverage.tick(sim.iso(clock.t))
    assert statuses(clock)[0]["status"] == "ok"
    assert store.state["intel"]["coverage"]["cursors"][asset["id"]]["source"] == "reported"
