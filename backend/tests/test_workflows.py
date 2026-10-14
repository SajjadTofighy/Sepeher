import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from app.main import app
from app.routers import commands
from app.store import state
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset(track_database):
    with TestClient(app) as client:
        client.post("/api/v1/demo/reset")
        yield client


def test_bootstrap_contract(reset):
    data = reset.get("/api/v1/bootstrap").json()
    assert len(data["assets"]) == 12
    assert data["summary"]["online"] == 11
    assert data["meta"]["mode"] == "mock"


def test_incident_lifecycle_rejects_skipping_and_offline_dispatch(reset):
    path = "/api/v1/incidents/INC-824/transition"
    assert (
        reset.post(path, json={"status": "assigned", "asset_id": "AST-001"}).status_code
        == 409
    )
    assert reset.post(path, json={"status": "confirmed"}).status_code == 200
    assert (
        reset.post(path, json={"status": "assigned", "asset_id": "AST-006"}).status_code
        == 409
    )
    assert (
        reset.post(path, json={"status": "assigned", "asset_id": "AST-001"}).status_code
        == 200
    )
    assert reset.post(path, json={"status": "en_route"}).status_code == 200
    assert reset.post(path, json={"status": "on_scene"}).status_code == 200
    assert reset.post(path, json={"status": "closed"}).status_code == 422
    assert (
        reset.post(
            path, json={"status": "closed", "note": "بازرسی و رفع وضعیت نمونه"}
        ).status_code
        == 200
    )
    report = reset.get("/api/v1/incidents/INC-824/report").json()
    assert len(report["incident"]["timeline"]) == 6
    assert reset.get("/api/v1/audit/verify").json()["valid"]


def test_safe_commands_idempotency_and_ack_stages(reset, monkeypatch):
    payload = {
        "asset_id": "AST-001",
        "command": "position",
        "channel": "data",
        "request_id": "test-1",
    }
    first = reset.post("/api/v1/commands", json=payload).json()
    second = reset.post("/api/v1/commands", json=payload).json()
    assert first["id"] == second["id"]
    assert len(state["commands"]) == 1
    assert (
        reset.post("/api/v1/commands", json={**payload, "command": "ping"}).status_code
        == 409
    )
    assert (
        reset.post(
            "/api/v1/commands", json={**payload, "command": "engine_stop"}
        ).status_code
        == 422
    )
    epoch = first["epoch"]
    monkeypatch.setattr(commands.time, "time", lambda: epoch + 3)
    assert reset.get("/api/v1/commands").json()[0]["status"] == "delivered"
    monkeypatch.setattr(commands.time, "time", lambda: epoch + 7)
    assert reset.get("/api/v1/commands").json()[0]["status"] == "executed"


def test_offline_command_times_out(reset, monkeypatch):
    c = reset.post(
        "/api/v1/commands",
        json={
            "asset_id": "AST-006",
            "command": "ping",
            "channel": "sms",
            "request_id": "offline",
        },
    ).json()
    monkeypatch.setattr(commands.time, "time", lambda: c["epoch"] + 21)
    assert reset.get("/api/v1/commands").json()[0]["status"] == "timed_out"


def test_policy_gate_and_validation(reset):
    payload = {
        "name": "سیاست نمونه جدید",
        "zone": "Z1",
        "condition": "long_stop",
        "threshold": 15,
    }
    p = reset.post("/api/v1/policies", json=payload).json()
    route = "/api/v1/policies/" + p["id"]
    assert reset.patch(route + "/status", json={"status": "active"}).status_code == 409
    assert reset.post(route + "/test").status_code == 200
    assert reset.patch(route + "/status", json={"status": "shadow"}).status_code == 200
    r = reset.patch(route + "/status", json={"status": "active"})
    assert r.status_code == 200 and r.json()["approver"]
    assert (
        reset.post("/api/v1/policies", json={**payload, "zone": "missing"}).status_code
        == 404
    )


def test_audit_tamper_detection(reset):
    reset.get("/api/v1/assets/AST-009/track")
    assert reset.get("/api/v1/audit/verify").json()["valid"]
    state["audit"][0]["action"] = "tampered"
    assert not reset.get("/api/v1/audit/verify").json()["valid"]


def test_mission_and_assistant(reset):
    m = reset.post("/api/v1/missions/MSN-101/checkpoint").json()
    assert m["status"] == "completed" and m["progress"] == 100
    assert reset.post("/api/v1/missions/MSN-101/checkpoint").status_code == 409
    answer = reset.post(
        "/api/v1/assistant", json={"question": "وضعیت منطقه چیست؟"}
    ).json()
    assert answer["mock"] and not answer["can_execute"] and answer["sources"]
    ids = {i["id"] for i in state["incidents"]}
    assert set(answer["sources"]) <= ids


def test_nearby_sorted_straight_line_and_scenario(reset):
    rows = reset.get("/api/v1/incidents/INC-824/nearby").json()
    assert all(r["distance_type"] == "straight_line" for r in rows)
    assert [r["distance_km"] for r in rows] == sorted(r["distance_km"] for r in rows)
    assert all(r["asset_id"] != "AST-006" for r in rows)
    i = reset.post("/api/v1/demo/scenario").json()
    assert i["severity"] == "critical" and i["status"] == "detected"


def test_geography_settings_and_camera_integration(reset):
    zone = {
        "name": "محدوده آزمایشی",
        "risk": "high",
        "points": [[49.8, 30.7], [49.9, 30.7], [49.9, 30.8], [49.8, 30.8]],
    }
    z = reset.post("/api/v1/zones", json=zone)
    assert z.status_code == 201
    assert (
        reset.put(
            "/api/v1/zones/" + z.json()["id"], json={**zone, "name": "محدوده ویرایش‌شده"}
        ).status_code
        == 200
    )
    assert (
        reset.post(
            "/api/v1/zones", json={**zone, "points": [[1, 1], [1, 1], [1, 1]]}
        ).status_code
        == 422
    )
    config = reset.get("/api/v1/settings").json()
    assert (
        reset.put("/api/v1/settings", json={**config, "retention_days": 120}).json()[
            "retention_days"
        ]
        == 120
    )
    assert (
        reset.put(
            "/api/v1/settings",
            json={**config, "normal_coverage_timeout": 20, "weak_coverage_timeout": 5},
        ).status_code
        == 422
    )
    assert (
        reset.patch(
            "/api/v1/assets/AST-001/settings",
            json={
                "carrier": "ایرانسل",
                "sim": "DEMO-001",
                "report_interval": 60,
                "data_package": "expiring",
            },
        ).json()["report_interval"]
        == 60
    )
    event = reset.post("/api/v1/cameras/CAM-32/event", json={"event": "fire"})
    assert event.status_code == 409  # Groundwork accepts real plate input only; no fabricated IVA incident.
    assert (
        reset.post(
            "/api/v1/cameras/CAM-35/event", json={"event": "intrusion"}
        ).status_code
        == 409
    )


def test_gis_settings_validate_service_and_preserve_versions(reset):
    config = reset.get('/api/v1/settings').json()
    assert config['gis_mode'] == 'local'
    payload = {**config, 'gis_mode': 'wms', 'gis_url': 'https://gis.example.org/ows', 'gis_layers': 'example:roads', 'gis_wms_version': '1.1.1', 'gis_opacity': 0.5}
    result = reset.put('/api/v1/settings', json=payload)
    assert result.status_code == 200
    assert reset.get('/api/v1/settings').json()['gis_layers'] == 'example:roads'
    assert result.json()['gis_wms_version'] == '1.1.1'
    for change in ({'gis_url': 'file:///tmp/map'}, {'gis_url': 'https://user:secret@example.org/ows'}, {'gis_layers': '   '}, {'gis_opacity': 1.5}, {'gis_wms_version': '2.0.0'}):
        assert reset.put('/api/v1/settings', json={**payload, **change}).status_code == 422
    result = reset.put('/api/v1/settings', json={**payload, 'gis_mode': 'wfs', 'gis_wfs_version': '2.0.0'})
    assert result.status_code == 200
    assert result.json()['gis_wfs_version'] == '2.0.0'
