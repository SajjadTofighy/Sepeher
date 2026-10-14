"""Deterministic phase 0 contracts, geometry, routing, and worker regressions."""

import asyncio
import math
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import engine, sim, store
from app.intel import findings, geo, worker
from app.main import app
from app.models import Finding
from app.seed import seed


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    return clock


@pytest.fixture
def client(track_database, clock, monkeypatch):
    # Isolate phase 0 infrastructure from the capability registered in phase 1A.
    monkeypatch.setattr(worker, "capabilities", [])
    store.state.clear()
    store.state.update(seed())
    store.state["policies"] = []
    with TestClient(app) as client:
        assert app.state.intel_worker is None
        yield client


def evidence(clock):
    stamp = sim.iso(clock.t)
    return dict(rule="قاعدة آزمایشی مستند", thresholds={"distance_m": 100},
                window_from=stamp, window_to=stamp,
                points=[[49.78, 30.76, stamp]], values={"distance_m": 120})


def raise_example(clock, **overrides):
    payload = dict(rule_id="RULE-TEST", kind="foundation", subject_ids=["AST-001"],
                   summary="یافته آزمایشی برای بررسی", evidence=evidence(clock), sources=["AST-001"])
    return findings.raise_finding(**{**payload, **overrides})


def test_projection_distances_and_degenerate_geometry():
    assert geo.project_m([49.78, 30.76], 30.76, 49.78) == (0, 0)
    x, y = geo.project_m([0.001, 0.001], 0)
    assert x == pytest.approx(111.195, abs=0.001)
    assert y == x
    assert geo.project_m([0.001, 60], 60)[0] == pytest.approx(x / 2)
    assert geo.point_segment_distance_m([0.005, 0.001], [0, 0], [0.01, 0]) == pytest.approx(y)
    assert geo.point_segment_distance_m([-0.001, 0], [0, 0], [0.01, 0]) == pytest.approx(x)
    assert geo.point_segment_distance_m([0, 0], [0, 0], [0, 0]) == 0
    assert geo.point_polyline_distance_m([0.01, 0.005], [[0, 0], [0.01, 0], [0.01, 0.01]]) == 0
    assert geo.point_polyline_distance_m([0.001, 0], [[0, 0]]) == pytest.approx(x)
    assert math.isinf(geo.point_polyline_distance_m([0, 0], []))


def test_densify_keeps_endpoints_and_bounds_spacing():
    a, b = [49.78, 30.76], [49.79, 30.77]
    points = geo.densify(a, b, 100)
    assert points[0] == a and points[-1] == b
    assert all(sim.distance_km(p, q) * 1000 <= 100.01 for p, q in zip(points, points[1:]))
    assert geo.densify(a, a, 100) == [a, a]
    for step in (0, -1, math.inf, math.nan):
        with pytest.raises(ValueError):
            geo.densify(a, b, step)
        with pytest.raises(ValueError):
            geo.derive_segments([], step)


def test_bbox_helpers():
    bounds = geo.bbox([[49.78, 30.76], [49.79, 30.77], [49.785, 30.765]])
    assert bounds == (49.78, 30.76, 49.79, 30.77)
    assert geo.bbox_contains(bounds, [49.78, 30.76])
    assert not geo.bbox_contains(bounds, [49.80, 30.76])
    expanded = geo.expand_bbox(bounds, 100)
    assert expanded[0] < bounds[0] and expanded[3] > bounds[3]
    assert geo.bboxes_intersect(bounds, expanded)
    assert not geo.bboxes_intersect(bounds, (0, 0, 1, 1))
    with pytest.raises(ValueError):
        geo.bbox([])
    with pytest.raises(ValueError):
        geo.expand_bbox(bounds, -1)


def test_segments_keep_bends_length_and_stable_ids():
    pipeline = dict(id="PIPE-TEST", field="آغاجاری", points=[[0, 0], [0.003, 0], [0.003, 0.012]])
    segments = geo.derive_segments([pipeline])
    assert len(segments) == 4
    assert [s["index"] for s in segments] == list(range(4))
    assert len({s["id"] for s in segments}) == 4
    assert all(s["pipeline_id"] == "PIPE-TEST" and s["field"] == "آغاجاری" for s in segments)
    assert segments[0]["points"][1] == pipeline["points"][1]
    assert segments[0]["points"][0] == pipeline["points"][0]
    assert segments[-1]["points"][-1] == pipeline["points"][-1]
    assert all(a["points"][-1] == b["points"][0] for a, b in zip(segments, segments[1:]))
    expected = sum(sim.distance_km(a, b) * 1000 for a, b in zip(pipeline["points"], pipeline["points"][1:]))
    assert sum(s["length_m"] for s in segments) == pytest.approx(expected)
    assert all(0 < s["length_m"] <= 500.01 for s in segments)
    assert segments == geo.derive_segments([pipeline])


def test_schematic_layers_cross_some_beats_and_leave_remote_layers(clock):
    data = seed()
    assert data["segments"] == geo.derive_segments(data["pipelines"])
    assert all("شماتیک" in row["name"] for key in ("pipelines", "facilities") for row in data[key])
    fields = {a["field"] for a in data["assets"]}
    assert all(row["field"] in fields for key in ("pipelines", "facilities") for row in data[key])
    beat_points = []
    for asset in data["assets"]:
        if asset["kind"] != "vehicle" or asset["status"] == "offline":
            continue
        plan = sim.new_plan(asset, [asset["lon"], asset["lat"]], now=clock.t)
        beat_points.extend(sim.position(plan, clock.t + k * plan["period"] / 120) for k in range(120))
    distances = [min(geo.point_polyline_distance_m(p, row["points"]) for p in beat_points) for row in data["pipelines"]]
    assert min(distances) < 10 and max(distances) > 5000
    facility_distances = [min(sim.distance_km(p, [f["lon"], f["lat"]]) * 1000 for p in beat_points) for f in data["facilities"]]
    assert min(facility_distances) < 10 and max(facility_distances) > 5000


def layers():
    return dict(type="FeatureCollection", features=[
        dict(type="Feature", geometry=dict(type="LineString", coordinates=[[49.78, 30.76], [49.79, 30.77]]),
             properties=dict(name="خط آزمایشی", field="آغاجاری")),
        dict(type="Feature", geometry=dict(type="Point", coordinates=[49.78, 30.76]),
             properties=dict(name="چاه آزمایشی", field="کرنج", kind="well", radius_m=100, unmanned=True)),
    ])


def test_geojson_import_bootstrap_segments_and_audit(client):
    response = client.post("/api/v1/intel/layers/import", json=layers())
    assert response.status_code == 201
    data = response.json()
    assert data["pipelines"][0]["points"] == layers()["features"][0]["geometry"]["coordinates"]
    assert data["facilities"][0]["kind"] == "well"
    assert data["segments"] == geo.derive_segments(data["pipelines"])
    boot = client.get("/api/v1/bootstrap").json()
    assert data["pipelines"][0] in boot["pipelines"] and data["facilities"][0] in boot["facilities"]
    assert data["segments"][0] in client.get("/api/v1/intel/segments").json()
    assert store.state["audit"][-1]["action"] == "ورود لایه‌های هوشمندی"
    assert client.get("/api/v1/audit/verify").json()["valid"]


@pytest.mark.parametrize("mutation", [
    "longitude", "latitude", "extra_coordinate", "short_line", "zero_line",
    "bad_type", "bad_kind", "bad_radius", "missing_unmanned", "bad_field",
])
def test_invalid_import_is_atomic(client, mutation):
    payload = layers()
    line, point = payload["features"]
    if mutation == "longitude":
        point["geometry"]["coordinates"][0] = 181
    elif mutation == "latitude":
        point["geometry"]["coordinates"][1] = 86
    elif mutation == "extra_coordinate":
        point["geometry"]["coordinates"].append(0)
    elif mutation == "short_line":
        line["geometry"]["coordinates"].pop()
    elif mutation == "zero_line":
        line["geometry"]["coordinates"][1] = line["geometry"]["coordinates"][0]
    elif mutation == "bad_type":
        point["geometry"]["type"] = "Polygon"
    elif mutation == "bad_kind":
        point["properties"]["kind"] = "unknown"
    elif mutation == "bad_radius":
        point["properties"]["radius_m"] = -1
    elif mutation == "missing_unmanned":
        del point["properties"]["unmanned"]
    elif mutation == "bad_field":
        point["properties"]["field"] = "unknown"
    before = deepcopy(store.state)
    assert client.post("/api/v1/intel/layers/import", json=payload).status_code == 422
    assert store.state == before


def test_import_duplicate_ids_rejected_without_partial_write(client):
    payload = layers()
    payload["features"][1]["properties"]["id"] = "PIPE-001"
    before = deepcopy(store.state)
    assert client.post("/api/v1/intel/layers/import", json=payload).status_code == 409
    assert store.state == before


def test_import_derived_segment_ids_cannot_collide_with_facilities(client):
    payload = layers()
    payload["features"][0]["properties"]["id"] = "PIPE-COLLISION"
    payload["features"][1]["properties"]["id"] = "PIPE-COLLISION-SEG-0000"
    before = deepcopy(store.state)
    assert client.post("/api/v1/intel/layers/import", json=payload).status_code == 409
    assert store.state == before


def test_finding_latch_ack_resolve_and_recreate(client, clock):
    first = raise_example(clock)
    assert first["id"] == "FND-0001" and first["mode"] == "shadow" and not first["can_execute"]
    clock.t += 10
    assert raise_example(clock)["id"] == first["id"]
    assert len(store.state["findings"]) == 1
    response = client.post(f"/api/v1/intel/findings/{first['id']}/ack")
    assert response.json()["status"] == "acknowledged"
    assert response.json()["updated_at"] == sim.iso(clock.t)
    audit_count = len(store.state["audit"])
    client.post(f"/api/v1/intel/findings/{first['id']}/ack")
    assert len(store.state["audit"]) == audit_count
    assert raise_example(clock)["id"] == first["id"]
    clock.t += 10
    findings.resolve_finding(first["id"])
    assert client.post(f"/api/v1/intel/findings/{first['id']}/ack").status_code == 409
    findings.resolve_finding(first["id"])
    second = raise_example(clock)
    assert second["id"] == "FND-0002" and second["status"] == "open"
    assert len(client.get("/api/v1/intel/findings", params={"kind": "foundation", "status": "resolved"}).json()) == 1
    assert client.get("/api/v1/intel/findings", params={"kind": "absent"}).json() == []
    assert client.post("/api/v1/intel/findings/missing/ack").status_code == 404
    assert [row["action"] for row in store.state["audit"]] == [
        "ایجاد یافته هوشمندی", "تأیید دریافت یافته هوشمندی", "رفع یافته هوشمندی", "ایجاد یافته هوشمندی",
    ]
    assert client.get("/api/v1/audit/verify").json()["valid"]
    with pytest.raises(ValidationError):
        Finding.model_validate({**second, "can_execute": True})


@pytest.mark.parametrize("mode,global_shadow,action,silence", [
    ("active", False, "create_incident", False),
    ("shadow", False, "create_incident", False),
    ("active", True, "create_incident", False),
    ("active", False, "log_only", False),
    ("active", False, "create_incident", True),
    ("active", False, "log_only", True),
    ("shadow", True, "log_only", True),
])
def test_shared_routing_matches_engine_and_findings(client, clock, mode, global_shadow, action, silence):
    store.state["settings"].update(shadow_mode=global_shadow, maintenance_silence=silence)
    policy = {**seed()["policies"][0], "status": mode, "action": action, "schedule": "تمام شبانه‌روز"}
    store.state["policies"] = [policy]
    asset = store.lookup("assets", "AST-001")
    asset.update(lon=49.93, lat=30.75, authorized=False)
    alert = engine.evaluate(store.state, asset, sim.iso(clock.t), store.create_incident, store.audit)[0]
    decision = engine.routing_decision(store.state["settings"], mode, action)
    assert {k: alert[k] for k in decision} == decision
    finding = raise_example(clock, mode=mode, action=action, needs_incident=True)
    assert finding["mode"] == alert["mode"]
    assert bool(finding["incident_id"]) == decision["routed"]
    assert finding["can_execute"] is False and store.state["commands"] == []
    if finding["incident_id"]:
        incident = store.lookup("incidents", finding["incident_id"])
        assert incident["status"] == "detected" and incident["assigned_to"] is None
        assert incident["timeline"][0]["actor"] == "موتور هوشمندی"


def test_active_finding_uses_same_dedupe_window(client, clock):
    first = raise_example(clock, mode="active", needs_incident=True)
    count = len(store.state["incidents"])
    findings.resolve_finding(first["id"])
    clock.t += 30
    second = raise_example(clock, mode="active", needs_incident=True)
    assert second["incident_id"] == first["incident_id"]
    assert len(store.state["incidents"]) == count
    assert "ادغام" in store.lookup("incidents", first["incident_id"])["timeline"][-1]["action"]
    findings.resolve_finding(second["id"])
    clock.t += store.state["settings"]["dedupe_seconds"] + 1
    third = raise_example(clock, mode="active", needs_incident=True)
    assert third["incident_id"] != first["incident_id"]
    assert len(store.state["incidents"]) == count + 1


def test_observations_follow_simulated_reported_offline_and_synthetic_precedence(client, clock, track_database):
    since = sim.iso(clock.t - 120)
    store.refresh_tracks(now_iso=sim.iso(clock.t))
    asset = store.lookup("assets", "AST-001")
    expected = [p for p in asset["track"] if p["time"] >= since]
    assert store.observations_since(asset, since) == expected
    track_database.append(asset["id"], 49.7, 30.7, sim.iso(clock.t - 30))
    track_database.append(asset["id"], 49.71, 30.71, sim.iso(clock.t))
    store.refresh_track(asset)
    expected = track_database.read(asset["id"], since=since)
    assert store.observations_since(asset, since) == expected
    assert store.observations_since(asset, sim.iso(clock.t + 1)) == []
    asset["synthetic"] = True
    store.refresh_track(asset)
    expected = [p for p in asset["track"] if p["time"] >= since]
    assert store.observations_since(asset, since) == expected
    assert expected != track_database.read(asset["id"], since=since)
    asset["status"] = "offline"
    store.refresh_track(asset)
    assert store.observations_since(asset, since) == track_database.read(asset["id"], since=since)


def test_worker_tick_without_lifespan_refreshes_before_capabilities(track_database, clock, monkeypatch):
    store.state.clear()
    store.state.update(seed())
    store.state["policies"] = []
    assert all(hasattr(capability, "tick") for capability in worker.capabilities)
    seen = []

    def capability_tick(stamp):
        assert store.state_lock.locked()
        assert store.lookup("assets", "AST-001")["last_seen"] == stamp
        seen.append(stamp)

    monkeypatch.setattr(worker, "capabilities", [SimpleNamespace(tick=capability_tick)])
    worker.tick(sim.iso(clock.t))
    first = deepcopy(store.lookup("assets", "AST-001")["track"])
    worker.tick(sim.iso(clock.t))
    assert store.lookup("assets", "AST-001")["track"] == first
    clock.t += 60
    worker.tick(sim.iso(clock.t))
    assert store.lookup("assets", "AST-001")["track"] != first
    assert len(seen) == 3
    assert not store.state_lock.locked()


def test_lifespan_starts_and_cancels_worker(monkeypatch):
    monkeypatch.setenv("SEPEHR_WORKER", "1")
    cancelled = []

    async def check():
        started = asyncio.Event()

        async def run():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        monkeypatch.setattr(worker, "run", run)
        async with worker.lifespan(app):
            await started.wait()
            task = app.state.intel_worker
            assert task is not None and not task.done()
        assert task.cancelled()

    asyncio.run(check())
    assert cancelled == [True]


def test_worker_uses_runtime_interval_and_releases_lock(client, clock, monkeypatch):
    store.state["settings"]["intel_tick_seconds"] = 17
    intervals = []

    async def stop_after_tick(interval):
        intervals.append(interval)
        assert not store.state_lock.locked()
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", stop_after_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run())
    assert intervals == [17]


def test_settings_validation_and_demo_reset_clear_intel(client, clock):
    config = client.get("/api/v1/settings").json()
    assert config["intel_tick_seconds"] == 5
    assert client.put("/api/v1/settings", json={**config, "intel_tick_seconds": 12}).json()["intel_tick_seconds"] == 12
    for interval in (0, 3601):
        assert client.put("/api/v1/settings", json={**config, "intel_tick_seconds": interval}).status_code == 422
    raise_example(clock)
    client.post("/api/v1/intel/layers/import", json=layers())
    assert client.post("/api/v1/demo/reset").status_code == 200
    assert store.state["findings"] == [] and store.state["intel"] == {"latches": {}}
    assert store.state["pipelines"] == seed()["pipelines"]
    assert store.state["segments"] == geo.derive_segments(store.state["pipelines"])
    assert store.state["settings"]["intel_tick_seconds"] == 5


def test_policy_dedupe_preserves_asset_policy_window_and_closed_identity(client, clock):
    policy = {**seed()["policies"][0], "schedule": "تمام شبانه‌روز"}
    store.state["policies"] = [policy]
    assets = [store.lookup("assets", id) for id in ("AST-001", "AST-002")]

    def enter(asset):
        asset.update(lon=0, lat=0, authorized=False)
        engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)
        asset.update(lon=49.93, lat=30.75)
        alerts = engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)
        return alerts[0]["incident_id"]

    first = enter(assets[0])
    clock.t += 30
    assert enter(assets[0]) == first
    assert enter(assets[1]) != first
    store.lookup("incidents", first)["status"] = "closed"
    replacement = enter(assets[0])
    assert replacement != first
    policy["id"] = "POL-DIFFERENT"
    assert enter(assets[0]) != replacement
    policy["id"] = "POL-01"
    clock.t += store.state["settings"]["dedupe_seconds"] + 1
    assert enter(assets[0]) != replacement
    assert not store.state["commands"]
