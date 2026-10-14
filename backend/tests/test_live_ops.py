import time

import pytest
from fastapi.testclient import TestClient

from app import engine, sim
from app.main import app
from app.store import state


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


@pytest.fixture
def client(track_database, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(sim.time, "time", clock)
    import app.main as main

    monkeypatch.setattr(main.time, "time", clock)
    with TestClient(app) as c:
        c.post("/api/v1/demo/reset")
        c.clock = clock
        yield c


def drive_story(client, seconds=20):
    story = client.post("/api/v1/demo/story")
    assert story.status_code == 201
    client.clock.t += seconds
    return story.json(), client.get("/api/v1/bootstrap").json()


def test_live_motion_is_deterministic_and_moves(client):
    first = {a["id"]: (a["lon"], a["lat"]) for a in client.get("/api/v1/assets").json()}
    assert first == {a["id"]: (a["lon"], a["lat"]) for a in client.get("/api/v1/assets").json()}
    client.clock.t += 60
    later = {a["id"]: a for a in client.get("/api/v1/assets").json()}
    assert later["AST-001"]["lon"] != first["AST-001"][0]
    assert later["AST-006"]["status"] == "offline"
    assert (later["AST-006"]["lon"], later["AST-006"]["lat"]) == first["AST-006"]
    assert 5 <= later["AST-001"]["speed"] <= 120
    assert len(later["AST-001"]["track"]) > 10


def test_reported_gps_overrides_simulation(client):
    point = dict(lon=49.75, lat=30.75, time="2099-01-01T00:00:00Z", speed=12)
    assert client.post("/api/v1/assets/AST-002/positions", json=point).status_code == 201
    client.clock.t += 120
    asset = next(a for a in client.get("/api/v1/assets").json() if a["id"] == "AST-002")
    assert (asset["lon"], asset["lat"], asset["speed"]) == (49.75, 30.75, 12)


def test_policy_engine_routes_active_entry_once(client):
    story, data = drive_story(client)
    incident = data["incidents"][0]
    assert incident["policy_id"] == story["policy_id"] and incident["asset_id"] == story["asset_id"]
    assert incident["zone_id"] == story["zone_id"] and incident["status"] == "detected"
    assert "23:10" in incident["description"]
    assert data["alerts"][0]["routed"] and data["alerts"][0]["incident_id"] == incident["id"]
    count = len(data["incidents"])
    client.clock.t += 30
    assert len(client.get("/api/v1/bootstrap").json()["incidents"]) == count
    # The story vehicle is never offered as a patrol.
    assert all(r["asset_id"] != story["asset_id"] for r in client.get(f"/api/v1/incidents/{incident['id']}/nearby").json())


def test_shadow_policy_logs_without_incident(client):
    next(p for p in state["policies"] if p["id"] == "POL-01")["status"] = "shadow"
    count = len(state["incidents"])
    _, data = drive_story(client)
    assert len(data["incidents"]) == count
    alert = data["alerts"][0]
    assert not alert["routed"] and alert["reason"] == "حالت سایه" and alert["incident_id"] is None
    assert len([a for a in data["alerts"] if a["policy_id"] == "POL-01"]) == 1
    assert data["summary"]["shadow_alerts"] == sum(a["mode"] == "shadow" for a in data["alerts"])


def test_silence_window_suppresses_routing(client):
    state["settings"]["maintenance_silence"] = True
    count = len(state["incidents"])
    _, data = drive_story(client)
    assert len(data["incidents"]) == count and not data["alerts"][0]["routed"]


def test_out_of_schedule_entry_does_not_fire(client, monkeypatch):
    monkeypatch.setattr(engine, "local_clock", lambda asset: "12:00")
    _, data = drive_story(client)
    assert not any(a["policy_id"] == "POL-01" for a in data["alerts"])


def test_duplicate_alert_merges_into_open_incident(client):
    _, data = drive_story(client)
    incident = data["incidents"][0]
    asset = next(a for a in state["assets"] if a["id"] == "AST-S73")
    state["engine"]["inside"]["AST-S73"] = []
    engine.evaluate(state, asset, incident["created_at"], None, lambda *a: None)
    assert len(state["incidents"]) == len(data["incidents"])
    assert "ادغام" in state["incidents"][0]["timeline"][-1]["action"]


def test_dispatch_eta_arrival_and_measured_cycle(client):
    _, data = drive_story(client)
    iid = data["incidents"][0]["id"]
    rows = client.get(f"/api/v1/incidents/{iid}/nearby").json()
    assert rows and all(r["eta_minutes"] > 0 for r in rows)
    path = f"/api/v1/incidents/{iid}/transition"
    assert client.post(path, json={"status": "confirmed"}).status_code == 200
    # Field teams and the subject vehicle cannot be dispatched.
    assert client.post(path, json={"status": "assigned", "asset_id": "AST-010"}).status_code == 409
    assigned = client.post(path, json={"status": "assigned", "asset_id": rows[0]["asset_id"]}).json()
    assert assigned["eta_minutes"] == rows[0]["eta_minutes"]
    client.clock.t += 60
    data = client.get("/api/v1/bootstrap").json()
    incident = next(i for i in data["incidents"] if i["id"] == iid)
    patrol = next(a for a in data["assets"] if a["id"] == rows[0]["asset_id"])
    assert incident["arrived_at"] and patrol["speed"] == 0
    assert sim.distance_km([patrol["lon"], patrol["lat"]], [incident["lon"], incident["lat"]]) < 0.01
    for status in ("en_route", "on_scene"):
        assert client.post(path, json={"status": status}).status_code == 200
    assert client.post(path, json={"status": "closed", "note": "بررسی شد"}).status_code == 200
    summary = client.get("/api/v1/analytics").json()
    assert all(summary["cycle_measured"]) and summary["closed_incidents"] == 1


def test_assistant_answers_design_questions_with_sources(client):
    _, data = drive_story(client)
    iid = data["incidents"][0]["id"]
    ask = lambda q: client.post("/api/v1/assistant", json={"question": q}).json()
    why = ask(f"چرا حادثه {iid[4:]} بحرانی شده است؟")
    assert why["sources"] == [iid] and "POL-01" in why["answer"] and not why["can_execute"]
    persian = ask("چرا حادثه " + iid[4:].translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) + " مهم است؟")
    assert persian["sources"] == [iid]
    route = ask("کدام گشت‌ها خارج از مسیر هستند؟")
    assert route["sources"] and all("مسیر" in next(i for i in state["incidents"] if i["id"] == s)["title"] for s in route["sources"])
    zone = ask("در ۲۴ ساعت گذشته کدام منطقه بیشترین هشدار را داشته است؟")
    assert "حریم تأسیسات شرقی" in zone["answer"]
    now = ask("الان چه اتفاق مهمی در منطقه افتاده است؟")
    ids = {i["id"] for i in state["incidents"]}
    assert now["sources"] and set(now["sources"]) <= ids
