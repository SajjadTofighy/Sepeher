"""Patrol check-ins and the single SOS event path, with an injected clock."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import engine, sim, store
from app.intel import safety, worker
from app.main import app
from app.routers.incidents import nearby_patrols
from app.core.seed import seed


@pytest.fixture
def case(track_database, monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, 9, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    import app.main as main
    monkeypatch.setattr(main, "now", store.now)
    store.state.clear()
    store.state.update(seed())
    store.state["policies"] = []
    asset = store.state["assets"][0]
    asset.update(speed=0, synthetic=True)
    set_stop(asset, clock)
    return clock, asset


def set_stop(asset, clock, minutes=3, lon=49.78, lat=30.76):
    asset.update(lon=lon, lat=lat, speed=0, last_seen=sim.iso(clock.t))
    asset["track"] = [dict(lon=lon, lat=lat, time=sim.iso(clock.t - s))
                      for s in range(minutes * 60, -1, -30)]


def episode(asset):
    return store.state["intel"]["safety"]["episodes"][asset["id"]]


def test_unmanned_stop_starts_timer_and_confirm_closes_it(case):
    clock, asset = case
    safety.tick(sim.iso(clock.t))
    row = episode(asset)
    assert row["state"] == "check_pending" and row["facility_id"] == "FAC-001"
    assert row["deadline"] == sim.iso(clock.t + 600)
    assert safety in worker.capabilities
    with TestClient(app) as client:
        data = client.get("/api/v1/intel/safety").json()
        assert any(e["state"] == "check_pending" for e in data["episodes"])
        response = client.post(f"/api/v1/intel/safety/{asset['id']}/confirm", json={"note": "سلامت گشت تأیید شد"})
        assert response.status_code == 200 and response.json()["state"] == "confirmed"
        assert store.state["audit"][-1]["action"] == "تأیید سلامت گشت"
    clock.t += 1000
    safety.tick(sim.iso(clock.t))
    assert not any(f["kind"] == "patrol_safety" for f in store.state["findings"])


def test_stop_threshold_must_be_observed_before_check_pending(case):
    clock, asset = case
    set_stop(asset, clock, minutes=2)
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "stopped" and episode(asset)["deadline"] is None
    clock.t += 60
    asset["track"].append(dict(lon=asset["lon"], lat=asset["lat"], time=sim.iso(clock.t)))
    asset["last_seen"] = sim.iso(clock.t)
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "check_pending"


def test_timeout_escalates_once_and_reuses_backup_suggestions(case):
    clock, asset = case
    store.state["settings"]["intel_safety_mode"] = "active"
    safety.tick(sim.iso(clock.t))
    for _ in range(10):
        clock.t += 60
        asset["track"].append(dict(lon=asset["lon"], lat=asset["lat"], time=sim.iso(clock.t)))
        asset["last_seen"] = sim.iso(clock.t)
        safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "escalated"
    finding = store.lookup("findings", episode(asset)["finding_id"])
    assert finding["severity"] == "high" and finding["incident_id"]
    incident = store.lookup("incidents", finding["incident_id"])
    assert incident["kind"] == "patrol_safety" and incident["assigned_to"] is None
    assert incident["emergency_contacts"] == store.state["settings"]["intel_emergency_contacts"]
    assert incident["backup_patrols"] == nearby_patrols(incident)
    count = len(store.state["incidents"])
    safety.tick(sim.iso(clock.t))
    assert len(store.state["findings"]) == 1 and len(store.state["incidents"]) == count
    assert store.state["commands"] == []


def test_moving_cancels_pending_episode_without_escalation(case):
    clock, asset = case
    safety.tick(sim.iso(clock.t))
    clock.t += 30
    asset.update(lon=49.79, speed=30, last_seen=sim.iso(clock.t))
    asset["track"].append(dict(lon=asset["lon"], lat=asset["lat"], time=sim.iso(clock.t)))
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "idle"
    assert store.state["findings"] == []


def test_silence_pending_escalates_critical_at_shared_zone_timeout(case):
    clock, asset = case
    store.state["zones"] = [dict(id="Z-TEST", name="پوشش ضعیف", coverage="weak",
                                points=[[49, 30], [50, 30], [50, 31], [49, 31]])]
    store.state["settings"].update(weak_coverage_timeout=2, intel_safety_mode="active")
    safety.tick(sim.iso(clock.t))
    clock.t += 119
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "check_pending"
    clock.t += 1
    safety.tick(sim.iso(clock.t))
    finding = store.lookup("findings", episode(asset)["finding_id"])
    assert finding["severity"] == "critical"
    assert finding["evidence"]["thresholds"]["silence_minutes"] == 2
    assert store.lookup("incidents", finding["incident_id"])["severity"] == "critical"


def test_connection_policy_threshold_applies_to_safety(case):
    clock, asset = case
    store.state["zones"] = [dict(id="Z1", name="آزمایش", coverage="normal",
                                points=[[49, 30], [50, 30], [50, 31], [49, 31]])]
    store.state["policies"] = [{**seed()["policies"][0], "condition": "connection_lost", "threshold": 7,
                                "status": "shadow", "schedule": "تمام شبانه‌روز"}]
    safety.tick(sim.iso(clock.t))
    clock.t += 6 * 60
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "check_pending"
    clock.t += 60
    safety.tick(sim.iso(clock.t))
    assert store.lookup("findings", episode(asset)["finding_id"])["severity"] == "critical"


def test_ordinary_stop_during_normal_hours_does_nothing(case):
    clock, asset = case
    set_stop(asset, clock, lon=49.5, lat=30.5)
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "idle"
    assert store.state["findings"] == []


def test_remote_pipeline_and_tehran_night_stops_are_sensitive(case):
    clock, asset = case
    store.state["facilities"] = []
    safety.tick(sim.iso(clock.t))
    assert "خط" in episode(asset)["reason"]
    store.state["intel"].pop("safety")
    clock.t = datetime(2099, 1, 1, 20, tzinfo=timezone.utc).timestamp()
    set_stop(asset, clock, lon=49.5, lat=30.5)
    safety.tick(sim.iso(clock.t))
    assert episode(asset)["state"] == "check_pending"
    assert episode(asset)["reason"] == "توقف خارج از ساعت عادی گشت"


@pytest.mark.parametrize("settings", [{"intel_safety_mode": "shadow"},
                                      {"intel_safety_mode": "active", "shadow_mode": True},
                                      {"intel_safety_mode": "active", "maintenance_silence": True}])
def test_routing_controls_create_finding_without_incident(case, settings):
    clock, asset = case
    store.state["settings"].update(settings)
    before = deepcopy(store.state["incidents"])
    safety.tick(sim.iso(clock.t))
    clock.t += 300
    safety.tick(sim.iso(clock.t))
    finding = store.lookup("findings", episode(asset)["finding_id"])
    assert finding["incident_id"] is None and finding["can_execute"] is False
    assert store.state["incidents"] == before


def test_sos_event_routes_through_engine_and_is_idempotent(case):
    clock, asset = case
    store.state["policies"] = [seed()["policies"][-1]]
    assert store.state["policies"][0]["condition"] == "sos"
    before = len(store.state["incidents"])
    with TestClient(app) as client:
        path = f"/api/v1/assets/{asset['id']}/events"
        payload = dict(type="sos", time=sim.iso(clock.t))
        result = client.post(path, json=payload)
        assert result.status_code == 201
        data = result.json()
        assert data["incidents"][0]["severity"] == "critical"
        assert data["incidents"][0]["kind"] == "sos"
        assert data["incidents"][0]["emergency_contacts"]
        assert data["alerts"][0]["policy_id"] == store.state["policies"][0]["id"]
        assert client.post(path, json=payload).json()["event"]["id"] == data["event"]["id"]
    assert len(store.state["incidents"]) == before + 1
    engine.evaluate(store.state, asset, sim.iso(clock.t), store.create_incident, store.audit)
    assert len(store.state["incidents"]) == before + 1


def test_sos_capability_is_required_and_global_shadow_is_respected(case):
    clock, asset = case
    store.state["policies"] = [seed()["policies"][-1]]
    with TestClient(app) as client:
        payload = dict(type="sos", time=sim.iso(clock.t))
        response = client.post("/api/v1/assets/AST-002/events", json=payload)
        assert response.status_code == 422 and "قابلیت" in response.json()["detail"]
        assert client.post(f"/api/v1/assets/{asset['id']}/events", json={**payload, "time": "2099-01-01T09:00:00"}).status_code == 422
        store.state["settings"]["shadow_mode"] = True
        result = client.post("/api/v1/demo/scenario").json()
        assert result["event"]["type"] == "sos" and result["incidents"] == []
        assert result["alerts"][0]["mode"] == "shadow"


def test_late_confirmation_cannot_hide_silence(case):
    clock, asset = case
    safety.tick(sim.iso(clock.t))
    clock.t += 300
    with TestClient(app) as client:
        assert client.post(f"/api/v1/intel/safety/{asset['id']}/confirm", json={}).status_code == 409
    assert episode(asset)["state"] == "escalated"
