"""Real-input-only groundwork, disabled gates and shared engine/finding routing."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import engine, main, sim, store
from app.intel import coverage, geo, worker
from app.models import RuntimeSettings
from app.seed import seed


@pytest.fixture
def case(track_database, monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, 20, tzinfo=timezone.utc).timestamp())  # Tehran 23:30
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    monkeypatch.setattr(main, "now", store.now)
    store.state.clear()
    store.state.update(seed())
    store.state.update(incidents=[], policies=[], findings=[], alerts=[], audit=[])
    pipeline = dict(id="PIPE-TEST", name="خط آزمون شماتیک", field="آغاجاری", points=[[49.9, 30.75], [49.92, 30.75]])
    store.state["pipelines"] = [pipeline]
    store.state["segments"] = geo.derive_segments([pipeline])
    store.state["zones"] = [dict(id="Z1", name="محدوده آزمون", coverage="normal", points=[[49.8, 30.7], [50, 30.7], [50, 30.9], [49.8, 30.9]])]
    for index, camera in enumerate(store.state["cameras"]):
        camera.update(lon=49.905 + index * 0.001, lat=30.75, zone="محدوده آزمون")
    return SimpleNamespace(clock=clock, pipeline=pipeline, segments=store.state["segments"], client=TestClient(main.app))


def pressure(case, **updates):
    return dict(pipeline_id=case.pipeline["id"], chainage_m=750, time=store.now(), pressure_drop_pct=25, source="SCADA-READONLY-INPUT", **updates)


def read(case, camera_id="CAM-32", plate="۱۲الف ۳۴۵-۶۷", vehicle_class="heavy", **updates):
    return dict(camera_id=camera_id, plate=plate, time=store.now(), vehicle_class=vehicle_class, **updates)


def policy(condition, mode="active", **updates):
    row = {**seed()["policies"][0], "condition": condition, "status": mode, "schedule": "تمام شبانه‌روز", "zone": "Z1", **updates}
    store.state["policies"] = [row]
    store.state["settings"]["intel_anpr_enabled"] = True
    return row


def post_pressure(case, payload=None):
    return case.client.post("/api/v1/intel/ingest/pipeline-pressure", json=payload or pressure(case))


def post_read(case, payload=None, **updates):
    return case.client.post("/api/v1/intel/ingest/plate-read", json=payload or read(case, **updates))


def test_defaults_and_disabled_inputs_do_not_write(case):
    assert not RuntimeSettings().intel_pressure_enabled and not RuntimeSettings().intel_anpr_enabled
    assert not store.state["settings"]["intel_pressure_enabled"] and not store.state["settings"]["intel_anpr_enabled"]
    before = deepcopy(store.state)
    response = post_pressure(case)
    assert response.status_code == 409 and response.json()["detail"] == "نیازمند مجوز بهره‌برداری و اتصال یک‌طرفه"
    assert post_read(case).status_code == 409
    assert case.client.post("/api/v1/cameras/CAM-32/event", json={"event": "plate"}).status_code == 409
    assert store.state == before


def test_pressure_maps_chainage_to_segment_and_attaches_context(case):
    store.state["settings"].update(intel_pressure_enabled=True, intel_pressure_mode="active")
    target = case.segments[1]
    asset = store.state["assets"][0]
    last_time = sim.iso(case.clock.t - 300)
    point = geo.polyline_midpoint(target["points"])
    coverage._record_visit(target, dict(lon=point[0], lat=point[1], time=last_time), asset["id"], store.now())
    result = post_pressure(case)
    assert result.status_code == 201
    data = result.json()
    assert data["event"]["segment_id"] == target["id"]
    assert data["finding"]["kind"] == "pressure_drop" and data["finding"]["subject_ids"][0] == target["id"]
    assert data["finding"]["evidence"]["values"]["source"] == "SCADA-READONLY-INPUT"
    assert data["finding"]["can_execute"] is False
    i = data["incident"]
    assert i["asset_id"] == target["id"] and i["kind"] == "pressure_drop" and i["assigned_to"] is None
    assert i["lon"] == pytest.approx(data["event"]["lon"])
    assert i["pressure_context"]["last_visit"]["last_visit"] == last_time
    assert i["pressure_context"]["nearest_patrol"]
    assert len(i["backup_patrols"]) == 1 and store.state["commands"] == []
    assert post_pressure(case).json()["event"]["id"] == data["event"]["id"]
    assert len(store.state["findings"]) == 1 and len(store.state["incidents"]) == 1


def test_pressure_explicit_segment_boundary_and_invalid_location(case):
    store.state["settings"]["intel_pressure_enabled"] = True
    payload = pressure(case)
    payload.pop("chainage_m")
    payload["segment_id"] = case.segments[-1]["id"]
    data = post_pressure(case, payload).json()
    assert data["event"]["segment_id"] == payload["segment_id"] and data["incident"] is None
    for chainage, index in ((0, 0), (case.segments[0]["length_m"], 1), (sum(s["length_m"] for s in case.segments), len(case.segments) - 1)):
        p = pressure(case); p["chainage_m"] = chainage
        assert post_pressure(case, p).json()["event"]["segment_id"] == case.segments[index]["id"]
    before = deepcopy(store.state)
    for updates in ({"chainage_m": -1}, {"chainage_m": 100000}, {"segment_id": case.segments[0]["id"]},
                    {"source": "demo"}, {"source": "  "}, {"pressure_drop_pct": 0}, {"pressure_drop_pct": 101},
                    {"time": "2099-01-02T00:00:00Z"}, {"time": "2099-01-01T20:00:00"}):
        p = pressure(case); p.update(updates)
        assert post_pressure(case, p).status_code == 422
    assert store.state == before


@pytest.mark.parametrize("settings", [{}, {"intel_pressure_mode": "active", "shadow_mode": True}, {"intel_pressure_mode": "active", "maintenance_silence": True}])
def test_pressure_routing_controls_findings_only(case, settings):
    store.state["settings"].update(intel_pressure_enabled=True, **settings)
    result = post_pressure(case).json()
    assert result["finding"]["incident_id"] is None and result["incident"] is None
    assert store.state["incidents"] == [] and store.state["commands"] == []


def test_pressure_busy_patrols_and_conflicting_retry(case):
    store.state["settings"].update(intel_pressure_enabled=True, intel_pressure_mode="active")
    target = geo.point_at_chainage(case.pipeline["points"], 750)
    first, second = store.state["assets"][:2]
    first.update(lon=target[0], lat=target[1], status="online")
    second.update(lon=target[0] + 0.001, lat=target[1], status="online")
    store.state["incidents"] = [dict(id="INC-BUSY", assigned_to=first["id"], status="assigned")]
    result = post_pressure(case).json()
    assert result["incident"]["pressure_context"]["nearest_patrol"]["asset_id"] == second["id"]
    payload = pressure(case); payload["pressure_drop_pct"] = 30
    assert post_pressure(case, payload).status_code == 409
    assert len(store.state["pressure_events"]) == 1


def test_anpr_heavy_at_night_uses_engine_and_no_fake_tracker(case):
    row = policy("unknown_vehicle")
    assets = deepcopy(store.state["assets"])
    result = post_read(case)
    assert result.status_code == 201
    data = result.json()
    assert data["event"]["plate"] == "12الف34567"
    assert data["alerts"][0]["policy_id"] == row["id"] and data["alerts"][0]["finding_id"] == data["findings"][0]["id"]
    assert data["findings"][0]["kind"] == "unknown_vehicle" and data["incidents"][0]["policy_id"] == row["id"]
    assert data["incidents"][0]["kind"] == "anpr" and data["incidents"][0]["assigned_to"] is None
    assert store.state["assets"] == assets and store.state["commands"] == []
    assert post_read(case).json()["event"]["id"] == data["event"]["id"]
    assert len(store.state["findings"]) == 1
    engine.evaluate(store.state, store.state["assets"][0], store.now(), store.create_incident, store.audit)
    assert len(store.state["findings"]) == 1


@pytest.mark.parametrize("local_hour,vehicle_class,expected", [(23, "heavy", 1), (5, "heavy", 1), (6, "heavy", 0), (12, "heavy", 0), (23, "light", 0), (23, "unknown", 0)])
def test_anpr_night_schedule_and_class(case, local_hour, vehicle_class, expected):
    policy("unknown_vehicle")
    case.clock.t = datetime(2099, 1, 2, local_hour, tzinfo=engine.TEHRAN).timestamp()
    result = post_read(case, vehicle_class=vehicle_class).json()
    assert len(result["findings"]) == expected


def test_repeat_requires_two_distinct_sensitive_cameras_and_fires_once(case):
    policy("camera_event")
    store.state["settings"]["intel_anpr_sensitive_camera_ids"] = ["CAM-32", "CAM-33", "CAM-34"]
    assert post_read(case, vehicle_class="light").json()["findings"] == []
    case.clock.t += 10
    assert post_read(case, vehicle_class="light").json()["findings"] == []  # same camera twice
    case.clock.t += 10
    result = post_read(case, camera_id="CAM-33", vehicle_class="light").json()
    assert result["findings"][0]["kind"] == "camera_event"
    evidence = result["findings"][0]["evidence"]
    assert evidence["values"]["camera_ids"] == ["CAM-32", "CAM-33"]
    assert len(evidence["values"]["event_ids"]) == 3
    case.clock.t += 10
    assert post_read(case, camera_id="CAM-34", vehicle_class="light").json()["findings"] == []
    assert len(store.state["findings"]) == len(store.state["incidents"]) == 1


def test_repeat_window_plate_identity_and_non_sensitive_reads(case):
    policy("camera_event")
    store.state["settings"].update(intel_anpr_sensitive_camera_ids=["CAM-32", "CAM-33"], intel_anpr_repeat_window_minutes=10)
    assert post_read(case, camera_id="CAM-34").json()["findings"] == []
    assert post_read(case).json()["findings"] == []
    case.clock.t += 601
    assert post_read(case, camera_id="CAM-33").json()["findings"] == []
    case.clock.t += 1
    assert post_read(case, plate="88ب88888").json()["findings"] == []
    case.clock.t += 1
    assert len(post_read(case, plate="12الف34567").json()["findings"]) == 1


@pytest.mark.parametrize("condition", ["unknown_vehicle", "camera_event"])
def test_allowlisted_plate_ignored_by_both_rules(case, condition):
    policy(condition)
    settings = case.client.get("/api/v1/settings").json()
    settings.update(intel_vehicle_allowlist=["۱۲الف ۳۴۵-۶۷"], intel_anpr_sensitive_camera_ids=["CAM-32", "CAM-33"])
    saved = case.client.put("/api/v1/settings", json=settings)
    assert saved.status_code == 200 and saved.json()["intel_vehicle_allowlist"] == ["12الف34567"]
    assert post_read(case).json()["findings"] == []
    case.clock.t += 10
    assert post_read(case, camera_id="CAM-33", plate="12الف34567").json()["findings"] == []
    assert store.state["findings"] == store.state["incidents"] == []


@pytest.mark.parametrize("mode,settings", [("shadow", {}), ("active", {"shadow_mode": True}), ("active", {"maintenance_silence": True}), ("active", {})])
def test_anpr_routing_controls(case, mode, settings):
    row = policy("unknown_vehicle", mode)
    store.state["settings"].update(settings)
    if mode == "active" and not settings:
        row["action"] = "log_only"
    data = post_read(case).json()
    assert len(data["findings"]) == 1 and data["incidents"] == [] and not data["alerts"][0]["routed"]
    assert not data["findings"][0]["can_execute"]


def test_camera_adapter_requires_real_payload_and_reuses_canonical_ingest(case):
    policy("unknown_vehicle")
    for event in ("fire", "intrusion", "plate"):
        assert case.client.post("/api/v1/cameras/CAM-32/event", json={"event": event}).status_code == 409
    assert store.state["plate_reads"] == store.state["findings"] == store.state["incidents"] == []
    payload = read(case); payload.pop("camera_id"); payload["event"] = "plate"
    legacy = case.client.post("/api/v1/cameras/CAM-32/event", json=payload)
    assert legacy.status_code == 201
    assert post_read(case).json()["event"]["id"] == legacy.json()["event"]["id"]
    assert len(store.state["plate_reads"]) == len(store.state["findings"]) == 1
    assert case.client.post("/api/v1/cameras/CAM-32/event", json={**payload, "plate": "!"}).status_code == 422


def test_no_seed_or_worker_generated_sensor_findings_and_reset_disables(case):
    store.state["policies"] = [{**p, "zone": "Z1"} for p in seed()["policies"]]
    worker.tick(store.now())
    assert store.state["pressure_events"] == store.state["plate_reads"] == []
    assert not any(f["kind"] in {"pressure_drop", "unknown_vehicle", "camera_event"} for f in store.state["findings"])
    store.state["settings"].update(intel_anpr_enabled=True, intel_pressure_enabled=True)
    assert case.client.post("/api/v1/demo/reset").status_code == 200
    assert not store.state["settings"]["intel_anpr_enabled"] and not store.state["settings"]["intel_pressure_enabled"]
    assert store.state["pressure_events"] == store.state["plate_reads"] == []


def test_policy_backtest_only_replays_real_reads_without_live_findings(case):
    row = policy("camera_event", "draft")
    assert case.client.post(f"/api/v1/policies/{row['id']}/test").status_code == 422
    store.state["settings"]["intel_anpr_sensitive_camera_ids"] = ["CAM-32", "CAM-33"]
    post_read(case)
    case.clock.t += 10
    post_read(case, camera_id="CAM-33")
    before = deepcopy(store.state)
    tested = case.client.post(f"/api/v1/policies/{row['id']}/test")
    assert tested.status_code == 200 and tested.json()["matches"] == 1 and tested.json()["samples"] == 2
    assert not tested.json()["mock"]
    for key in ("plate_reads", "findings", "incidents", "alerts", "assets", "engine"):
        assert store.state[key] == before[key]
    assert case.client.patch(f"/api/v1/policies/{row['id']}/status", json={"status": "shadow"}).status_code == 200


def test_invalid_input_and_settings_are_rejected_without_events(case):
    policy("unknown_vehicle")
    before = deepcopy(store.state)
    for updates in ({"time": "2099-01-02T00:00:00Z"}, {"time": "2099-01-01T20:00:00"}, {"plate": "!"}, {"vehicle_class": "madeup"}):
        payload = read(case); payload.update(updates)
        assert post_read(case, payload).status_code == 422
    assert post_read(case, camera_id="NO-CAMERA").status_code == 404
    assert store.state == before
    config = case.client.get("/api/v1/settings").json()
    for updates in ({"intel_anpr_repeat_window_minutes": 0}, {"intel_anpr_night_hours": "25:00–06:00"}, {"intel_anpr_sensitive_camera_ids": ["NO-CAMERA"]}):
        assert case.client.put("/api/v1/settings", json={**config, **updates}).status_code == 422


def test_repeat_is_inclusive_and_rearms_after_real_quiet_window(case):
    policy("camera_event")
    store.state["settings"].update(intel_anpr_sensitive_camera_ids=["CAM-32", "CAM-33"], intel_anpr_repeat_window_minutes=10)
    assert post_read(case, vehicle_class="light").json()["findings"] == []
    case.clock.t += 600
    assert len(post_read(case, camera_id="CAM-33", vehicle_class="light").json()["findings"]) == 1
    case.clock.t += 601
    assert post_read(case, vehicle_class="light").json()["findings"] == []
    case.clock.t += 1
    assert len(post_read(case, camera_id="CAM-33", vehicle_class="light").json()["findings"]) == 1
    assert len(store.state["findings"]) == 2


def test_receipt_time_preserves_late_input_provenance(case):
    policy("unknown_vehicle")
    payload = read(case)
    payload["time"] = sim.iso(case.clock.t - 86400)
    data = post_read(case, payload).json()
    assert data["event"]["time"] == payload["time"]
    assert data["findings"][0]["created_at"] == data["event"]["received_at"] == store.now()
    assert data["alerts"][0]["time"] == store.now()
    assert datetime.fromisoformat(data["findings"][0]["evidence"]["window_to"]) == datetime.fromisoformat(payload["time"])


def test_plate_conflicting_retry_and_pressure_wrong_pipeline(case):
    policy("unknown_vehicle")
    post_read(case)
    assert post_read(case, vehicle_class="light").status_code == 409
    assert len(store.state["plate_reads"]) == len(store.state["findings"]) == 1
    store.state["settings"]["intel_pressure_enabled"] = True
    other = {**case.pipeline, "id": "PIPE-OTHER"}
    store.state["pipelines"].append(other)
    payload = pressure(case)
    payload.pop("chainage_m")
    payload.update(pipeline_id=other["id"], segment_id=case.segments[0]["id"])
    assert post_pressure(case, payload).status_code == 422
    payload["pipeline_id"] = "MISSING"
    assert post_pressure(case, payload).status_code == 404
    assert store.state["pressure_events"] == []
