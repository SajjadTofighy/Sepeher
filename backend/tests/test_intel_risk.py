"""Fixed risk, secure draft boundaries, mission compliance and policy latches."""

import json
import random
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import engine, sim, store
from app.intel import coverage, patrol, risk, worker
from app.main import app
from app.models import PatrolPlanInput
from app.seed import seed


@pytest.fixture
def case(track_database, monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, 9, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    store.state.clear()
    store.state.update(seed())
    store.state.update(policies=[], incidents=[], missions=[])
    store.state["segments"] = []
    facility = deepcopy(store.state["facilities"][0])
    for key in ("road_distance_m", "village_distance_m", "heavy_vehicle_access"):
        facility.pop(key, None)
    store.state["facilities"] = [facility]
    asset = store.state["assets"][0]
    asset.update(speed=0, synthetic=True, track=[], patrol_base=[facility["lon"], facility["lat"]])
    store.state["zones"] = [dict(id="Z1", name="محدوده آزمون", coverage="normal",
                                points=[[49, 30], [50, 30], [50, 31], [49, 31]])]
    return clock, asset, facility


def request(clock, **kwargs):
    return PatrolPlanInput(shift_start=sim.iso(clock.t + 3600), shift_end=sim.iso(clock.t + 9 * 3600),
                           asset_ids=kwargs.get("asset_ids", ["AST-001"]), stops_per_patrol=kwargs.get("stops_per_patrol", 1))


def planned_mission(clock, asset, facility, due_delta=0):
    mission = dict(id="MSN-TEST", asset_id=asset["id"], name="گشت زمان‌دار", zone="محدوده آزمون",
                   status="active", progress=0, plan_window_minutes=30, checkpoints=[dict(
                   name=facility["name"], target_id=facility["id"], lon=facility["lon"], lat=facility["lat"],
                   due_at=sim.iso(clock.t + due_delta), visited=False)])
    store.state["missions"] = [mission]
    return mission


def policy(mode="active"):
    row = {**seed()["policies"][0], "condition": "missed_checkpoint", "zone": "Z1", "status": mode,
           "schedule": "تمام شبانه‌روز", "action": "create_incident"}
    store.state["policies"] = [row]
    return row


def test_breakdown_arithmetic_and_incident_decay(case):
    clock, asset, facility = case
    incident = store.create_incident("رخداد تاریخی", "low", "آزمایش", asset, "نمونه", "ثبت")
    incident.update(created_at=sim.iso(clock.t - 30 * 86400), lon=facility["lon"], lat=facility["lat"], status="closed")
    future = deepcopy(incident)
    future.update(id="INC-FUTURE", created_at=sim.iso(clock.t + 100))
    distant = deepcopy(incident)
    distant.update(id="INC-DISTANT", lon=40, lat=20)
    store.state["incidents"].extend([future, distant])
    result = risk.snapshot()
    row = result["items"][0]
    factors = {f["factor"]: f for f in row["breakdown"]}
    assert factors["incidents"]["raw"] == pytest.approx(0.5)
    assert row["score"] == pytest.approx(0.7)
    assert all(f["contribution"] == pytest.approx(f["normalized"] * f["weight"]) for f in factors.values())
    assert row["score"] == pytest.approx(sum(f["contribution"] for f in factors.values()))
    assert all(0 <= f["normalized"] <= 1 for f in factors.values())
    clock.t += 30 * 86400
    store.state["incidents"].remove(future)
    assert risk.snapshot()["items"][0]["breakdown"][0]["raw"] == pytest.approx(0.25)
    finding = store.lookup("findings", row["finding_id"])
    assert finding["kind"] == "risk_assessment" and finding["can_execute"] is False and finding["incident_id"] is None


def test_missing_access_is_neutral_and_normalization_is_bounded(case):
    clock, _, facility = case
    row = risk.snapshot()["items"][0]
    factor = next(f for f in row["breakdown"] if f["factor"] == "access")
    assert factor["normalized"] == 0.5 and set(factor["raw"].values()) == {"داده ناموجود"}
    facility.update(road_distance_m=0, village_distance_m=2000, heavy_vehicle_access=True)
    factor = next(f for f in risk.snapshot()["items"][0]["breakdown"] if f["factor"] == "access")
    assert factor["normalized"] == pytest.approx(2 / 3)
    store.state["intel"]["coverage"] = dict(cursors={}, visits={facility["id"]: dict(last_visit=sim.iso(clock.t - 4 * 3600), last_asset_id="AST-001")})
    assert next(f for f in risk.snapshot()["items"][0]["breakdown"] if f["factor"] == "staleness")["normalized"] == 0.5


def test_sampling_bias_and_without_replacement_with_injected_rng():
    rows = [dict(id="high", score=0.9), dict(id="low", score=0.1)]
    rng = random.Random(51)
    sampled = [patrol.weighted_sample(rows, 1, 2, rng)[0]["id"] for _ in range(1000)]
    assert sampled.count("high") > 960
    assert {r["id"] for r in patrol.weighted_sample(rows, 2, 2, random.Random(2))} == {"high", "low"}
    assert len(patrol.weighted_sample([{**r, "score": 0} for r in rows], 2, 2, random.Random(2))) == 2


def test_most_overdue_item_is_mandatory_and_targets_unique(case):
    clock, _, facility = case
    other = deepcopy(facility)
    other.update(id="FAC-OTHER", lon=49.80, unmanned=False, name="ایستگاه دیگر")
    store.state["facilities"].append(other)
    store.state["intel"]["coverage"] = dict(cursors={}, visits={
        facility["id"]: dict(last_visit=sim.iso(clock.t - 20 * 3600), last_asset_id="AST-001"),
        other["id"]: dict(last_visit=sim.iso(clock.t - 21 * 3600), last_asset_id="AST-001")})
    # Unmanned: 12 h overdue; manned: 9 h overdue despite an older visit.
    plan = patrol.create(request(clock), random.Random(1))
    assert plan["patrols"][0]["stops"][0]["target_id"] == facility["id"]
    assert plan["patrols"][0]["stops"][0]["mandatory"]


def test_assignment_uses_bases_and_spacing_uses_shared_eta(case):
    clock, asset, facility = case
    other = deepcopy(facility)
    other.update(id="FAC-OTHER", lon=49.84, name="ایستگاه دیگر")
    store.state["facilities"].append(other)
    second = store.state["assets"][1]
    second["patrol_base"] = [other["lon"], other["lat"]]
    asset.update(lon=other["lon"], lat=other["lat"])
    plan = patrol.create(request(clock, asset_ids=[asset["id"], second["id"]], stops_per_patrol=1), random.Random(4))
    assert [p["stops"][0]["target_id"] for p in plan["patrols"]] == [facility["id"], other["id"]]
    asset["patrol_base"] = [facility["lon"], facility["lat"]]
    plan = patrol.create(request(clock, stops_per_patrol=2), random.Random(3))
    stops = plan["patrols"][0]["stops"]
    from app.routers.incidents import eta_minutes
    gap = (datetime.fromisoformat(stops[1]["due_at"]) - datetime.fromisoformat(stops[0]["due_at"])).total_seconds() / 60
    assert gap >= eta_minutes(sim.distance_km([stops[0]["lon"], stops[0]["lat"]], [stops[1]["lon"], stops[1]["lat"]])) + 10
    assert len({s["target_id"] for s in stops}) == 2


class SequenceRng:
    def __init__(self, values):
        self.values = iter(values)
        self.last = values[-1]

    def random(self):
        return next(self.values, self.last)


def test_jitter_resamples_and_handles_midnight_with_bounded_failure(case):
    clock, _, _ = case
    first = patrol.create(request(clock), SequenceRng([0.5]))
    patrol.approve(first["id"])
    clock.t += 86400
    second = patrol.create(request(clock), SequenceRng([0.5, 0.95]))
    old, new = first["patrols"][0]["stops"][0]["due_at"], second["patrols"][0]["stops"][0]["due_at"]
    assert not patrol.similar_local_time(old, new, 60)
    assert patrol.similar_local_time("2099-01-01T20:25:00Z", "2099-01-01T20:35:00Z", 15)
    # Constant repeated time exhausts bounded retries, without saving a conflicting draft.
    count = len(store.state["patrol_plans"])
    with pytest.raises(HTTPException) as exc:
        patrol.create(request(clock), SequenceRng([0.5]))
    assert exc.value.status_code == 422 and len(store.state["patrol_plans"]) == count
    assert "rng" not in json.dumps(second).lower()


def test_approve_creates_missions_idempotently_without_dispatch_and_discard_is_audited(case):
    clock, _, _ = case
    plan = patrol.create(request(clock), random.Random(5))
    stored_breakdown = deepcopy(plan["patrols"][0]["stops"][0]["breakdown"])
    store.state["settings"]["intel_risk_weights"]["access"] = 2
    before_sim, before_commands = deepcopy(store.state["sim"]), deepcopy(store.state["commands"])
    with TestClient(app) as client:
        path = f"/api/v1/intel/patrol-plans/{plan['id']}"
        response = client.post(path + "/approve")
        assert response.status_code == 200 and response.json()["status"] == "approved"
        assert len(store.state["missions"]) == 1
        assert client.post(path + "/approve").status_code == 200 and len(store.state["missions"]) == 1
        assert client.post(path + "/discard").status_code == 409
        assert client.get(path).json()["patrols"][0]["stops"][0]["breakdown"] == stored_breakdown
        assert client.get("/api/v1/intel/patrol-plans").json()
    assert store.state["missions"][0]["checkpoints"][0]["target_id"]
    assert store.state["sim"] == before_sim and store.state["commands"] == before_commands
    draft = patrol.create(request(clock), random.Random(1))
    patrol.discard(draft["id"])
    assert store.state["audit"][-1]["action"] == "کنارگذاشتن پیش‌نویس برنامه گشت"


def test_coverage_visit_marks_only_the_matching_patrol_within_inclusive_window(case):
    clock, asset, facility = case
    mission = planned_mission(clock, asset, facility)
    other = store.state["assets"][1]
    # Another patrol owns the newer aggregate visit; it must not hide this patrol's compliance.
    coverage._record_visit(facility, dict(lon=facility["lon"], lat=facility["lat"], time=store.now()), other["id"], store.now())
    assert not mission["checkpoints"][0]["visited"]
    coverage._record_visit(facility, dict(lon=facility["lon"], lat=facility["lat"], time=sim.iso(clock.t - 1801)), asset["id"], store.now())
    assert not mission["checkpoints"][0]["visited"]
    coverage._record_visit(facility, dict(lon=facility["lon"], lat=facility["lat"], time=sim.iso(clock.t - 1800)), asset["id"], store.now())
    assert mission["progress"] == 100 and mission["status"] == "completed"
    assert mission["checkpoints"][0]["visited_at"] == sim.iso(clock.t - 1800)


def test_coverage_tick_not_manual_marking_completes_planned_checkpoint(case):
    clock, asset, facility = case
    mission = planned_mission(clock, asset, facility)
    asset["track"] = [dict(lon=facility["lon"], lat=facility["lat"], time=store.now())]
    with TestClient(app) as client:
        assert client.post("/api/v1/missions/MSN-TEST/checkpoint").status_code == 409
    coverage.tick(store.now())
    assert mission["progress"] == 100 and mission["checkpoints"][0]["visited"]


@pytest.mark.parametrize("mode,global_settings,routed", [("active", {}, True), ("shadow", {}, False),
    ("active", {"shadow_mode": True}, False), ("active", {"maintenance_silence": True}, False)])
def test_missed_checkpoint_fires_once_per_checkpoint_through_engine(case, mode, global_settings, routed):
    clock, asset, facility = case
    mission = planned_mission(clock, asset, facility, due_delta=-1800)
    policy(mode)
    store.state["settings"].update(global_settings)
    asset.update(lon=40, lat=20)  # Missed target zone, not the tracker location, scopes this policy.
    assert engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit) == []
    clock.t += 1
    alerts = engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)
    assert len(alerts) == 1 and alerts[0]["target_id"] == facility["id"] and alerts[0]["routed"] is routed
    assert not engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)
    second = deepcopy(mission["checkpoints"][0])
    second.update(name="ایستگاه دوم", due_at=sim.iso(clock.t - 1800))
    mission["checkpoints"].append(second)
    clock.t += 1
    assert len(engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)) == 1
    assert store.state["commands"] == []


def test_arrival_is_processed_before_expired_deadline_on_worker_tick(case):
    clock, asset, facility = case
    mission = planned_mission(clock, asset, facility, due_delta=-1801)
    policy()
    asset["status"] = "online"
    asset["track"] = [dict(lon=facility["lon"], lat=facility["lat"], time=sim.iso(clock.t - 1))]
    # Preserve injected observations while refreshing other assets.
    from unittest.mock import patch
    original = store.refresh_track
    with patch.object(store, "refresh_track", side_effect=lambda a, at=None: None if a["id"] == asset["id"] else original(a, at)):
        worker.tick(store.now())
    assert mission["checkpoints"][0]["visited"] and not store.state["alerts"]


def test_old_checkpoints_still_work_and_new_policy_can_be_tested_and_activated(case):
    clock, asset, facility = case
    legacy = deepcopy(seed()["missions"][0])
    legacy["checkpoints"] = [dict(name="قدیمی", visited=False)]
    store.state["missions"] = [legacy]
    with TestClient(app) as client:
        assert client.post(f"/api/v1/missions/{legacy['id']}/checkpoint").json()["progress"] == 100
        mission = planned_mission(clock, asset, facility, due_delta=-1900)
        old = deepcopy(mission["checkpoints"][0])
        old["due_at"] = sim.iso(clock.t - 9 * 86400)
        mission["checkpoints"].append(old)
        result = client.post("/api/v1/policies", json=dict(name="کنترل ایستگاه", zone="Z1", condition="missed_checkpoint")).json()
        before = deepcopy(store.state["alerts"])
        tested = client.post(f"/api/v1/policies/{result['id']}/test").json()
        assert tested["samples"] == 1 and tested["matches"] == 1 and not tested["mock"]
        assert store.state["alerts"] == before and not mission["checkpoints"][0]["visited"]
        for status in ("shadow", "active"):
            assert client.patch(f"/api/v1/policies/{result['id']}/status", json=dict(status=status)).status_code == 200


def test_api_contract_import_access_and_invalid_plan_inputs(case):
    clock, _, _ = case
    with TestClient(app) as client:
        payload = request(clock).model_dump(mode="json")
        assert client.post("/api/v1/intel/patrol-plans", json={**payload, "rng": 1}).status_code == 422
        assert client.post("/api/v1/intel/patrol-plans", json={**payload, "asset_ids": ["AST-010"]}).status_code == 422
        assert client.post("/api/v1/intel/patrol-plans", json={**payload, "asset_ids": ["AST-001", "AST-001"]}).status_code == 422
        assert client.post("/api/v1/intel/patrol-plans", json={**payload, "shift_end": payload["shift_start"]}).status_code == 422
        response = client.post("/api/v1/intel/patrol-plans", json=payload)
        assert response.status_code == 201 and response.json()["status"] == "draft"
        layer = dict(type="FeatureCollection", features=[dict(type="Feature", geometry=dict(type="LineString", coordinates=[[49.78, 30.76], [49.79, 30.76]]),
            properties=dict(name="خط آزمون", field="آغاجاری", road_distance_m=25, village_distance_m=250, heavy_vehicle_access=True))])
        imported = client.post("/api/v1/intel/layers/import", json=layer)
        assert imported.status_code == 201
        assert all(s["road_distance_m"] == 25 and s["heavy_vehicle_access"] for s in imported.json()["segments"])
        assert client.get("/api/v1/intel/risk").json()["items"][0]["breakdown"]
