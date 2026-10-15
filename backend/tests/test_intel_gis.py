"""Operational GIS picture: change journal with resume, bounded queries and history separate from live."""

from datetime import datetime, timedelta, timezone
import threading

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core import journal, sim, store
from app.main import app


@pytest.fixture
def client(monkeypatch):
    frozen = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
    clock = dict(now=frozen)
    monkeypatch.setattr(store, "now", lambda: clock["now"].isoformat())
    # Simulated beats are frozen too, so only real changes appear in the feed.
    monkeypatch.setattr(sim.time, "time", lambda: clock["now"].timestamp())
    monkeypatch.setattr(journal.Journal, "__init__", _instant(journal.Journal.__init__))
    with TestClient(app) as c:
        c.post("/api/v1/demo/reset")
        c.clock = clock
        yield c


def _instant(original):
    def init(self, capacity=20000, min_interval=0.5):
        original(self, capacity, 0)  # deterministic tests: every read syncs
    return init


def changes(client, cursor, **params):
    response = client.get("/api/v1/changes", params=dict(cursor=cursor, **params))
    assert response.status_code == 200, response.text
    return response.json()


def report(client, asset="AST-001", lon=49.71, lat=30.71, seconds=0):
    point = dict(lon=lon, lat=lat, time=(client.clock["now"] - timedelta(seconds=60 - seconds)).isoformat(), accuracy_m=6)
    assert client.post(f"/api/v1/assets/{asset}/positions", json=point).status_code == 201


def test_bootstrap_is_bounded_and_changes_resume_from_its_cursor(client):
    data = client.get("/api/v1/bootstrap").json()
    trail = store.state["settings"]["map_trail_points"]
    assert all(len(a["track"]) <= trail for a in data["assets"])
    cursor = data["meta"]["cursor"]
    idle = changes(client, cursor)
    assert idle["reset"] is False and idle["cursor"] == cursor and idle["assets"] == []
    report(client)
    delta = changes(client, cursor)
    assert [a["id"] for a in delta["assets"]] == ["AST-001"] and delta["assets"][0]["lon"] == 49.71
    assert delta["assets"][0]["position_state"] == "fresh"
    # Applying the same cursor again is idempotent; the new cursor has nothing pending.
    assert changes(client, cursor)["assets"][0]["id"] == "AST-001"
    assert changes(client, delta["cursor"])["assets"] == []


def test_restart_unknown_and_too_old_cursors_force_snapshot_reload(client, monkeypatch):
    cursor = client.get("/api/v1/bootstrap").json()["meta"]["cursor"]
    assert changes(client, "garbage")["reset"] is True
    assert changes(client, cursor.split(":")[0] + ":999999")["reset"] is True
    # A demo reset (like a restart or restore) starts a new epoch: old cursors reload.
    client.post("/api/v1/demo/reset")
    assert changes(client, cursor)["reset"] is True
    # A cursor older than the bounded buffer cannot be replayed: reload instead of a silent gap.
    feed = journal.reset()
    monkeypatch.setattr(feed, "capacity", 3)
    feed.entries = type(feed.entries)(maxlen=3)
    feed.sync(force=True)
    old = feed.cursor()
    for step in range(5):
        report(client, lon=49.71 + step / 1000, seconds=step)
        feed.sync(force=True)
    assert changes(client, old)["reset"] is True


def test_removed_entities_and_identity_projection(client, token_factory):
    cursor = client.get("/api/v1/bootstrap").json()["meta"]["cursor"]
    removed = store.state["missions"].pop()
    assert changes(client, cursor)["removed"] == {"missions": [removed["id"]]}
    store.lookup("assets", "AST-009")["keycloak_sub"] = "guard-sub"
    report(client, asset="AST-009")
    operator = {"Authorization": "Bearer " + token_factory(sub="op", roles=["shift_supervisor"])}
    seen = client.get("/api/v1/changes", params=dict(cursor=cursor), headers=operator).json()
    assert next(a for a in seen["assets"] if a["id"] == "AST-009")["keycloak_sub"] is None


def test_long_poll_returns_on_change_or_deadline_without_wall_clock(client, monkeypatch):
    cursor = client.get("/api/v1/bootstrap").json()["meta"]["cursor"]
    ticks = dict(t=0.0, sleeps=0)

    async def fake_sleep(seconds):
        ticks["t"] += seconds
        ticks["sleeps"] += 1
        if ticks["sleeps"] == 3:
            store.state["incidents"][0]["title"] = "تغییر در حین انتظار"  # a change arrives while waiting

    monkeypatch.setattr(main, "poll_clock", lambda: ticks["t"])
    monkeypatch.setattr(main, "poll_sleep", fake_sleep)
    body = changes(client, cursor, wait=20)
    assert body["incidents"][0]["title"] == "تغییر در حین انتظار" and ticks["sleeps"] == 3
    ticks.update(t=0.0, sleeps=-100)
    idle = changes(client, body["cursor"], wait=2)
    assert idle["assets"] == [] and ticks["t"] >= 2


def test_bbox_query_is_bounded_and_validated(client):
    everything = client.get("/api/v1/map/features", params=dict(bbox="-180,-90,180,90")).json()
    assert everything["total"] == len(everything["features"]) and not everything["truncated"]
    capped = client.get("/api/v1/map/features", params=dict(bbox="-180,-90,180,90", limit=2)).json()
    assert len(capped["features"]) == 2 and capped["truncated"] and capped["total"] == everything["total"]
    report(client, lon=48.0, lat=29.0)  # away from every schematic seed feature
    box = client.get("/api/v1/map/features", params=dict(bbox="47.99,28.99,48.01,29.01", layers="assets")).json()
    assert [f["id"] for f in box["features"]] == ["AST-001"] and box["features"][0]["position_state"] == "fresh"
    for bad in ("30.7,49.7,30.8,49.8x", "50,30,49,31", "-200,0,10,10"):
        assert client.get("/api/v1/map/features", params=dict(bbox=bad)).status_code == 422
    assert client.get("/api/v1/map/features", params=dict(bbox="0,0,1,1", layers="secrets")).status_code == 422


def test_history_batch_is_windowed_capped_and_separate_from_live(client):
    for step in range(5):
        report(client, lon=49.71 + step / 1000, seconds=step * 10)
    live_before = store.lookup("assets", "AST-001")["lon"]
    window = dict(since=(client.clock["now"] - timedelta(minutes=2)).isoformat(),
                  until=client.clock["now"].isoformat(), asset_id=["AST-001", "AST-002"])
    batch = client.get("/api/v1/tracks", params=window).json()
    assert [p["lon"] for p in batch["tracks"]["AST-001"]] == [49.71 + s / 1000 for s in range(5)]
    assert not batch["truncated"] and store.state["audit"][-1]["action"] == "مشاهده تاریخچه موقعیت برای بازپخش"
    capped = client.get("/api/v1/tracks", params={**window, "limit_per_asset": 2}).json()
    assert len(capped["tracks"]["AST-001"]) == 2 and capped["truncated"]
    assert capped["tracks"]["AST-001"][-1]["lon"] == 49.71 + 4 / 1000  # newest points kept
    assert store.lookup("assets", "AST-001")["lon"] == live_before
    assert client.get("/api/v1/tracks", params={**window, "since": window["until"], "until": window["since"]}).status_code == 422


def test_bootstrap_audit_is_recent_only_with_total(client):
    for step in range(main.BOOTSTRAP_AUDIT + 5):
        store.audit("آزمون حجم ممیزی", f"T-{step}")
    data = client.get("/api/v1/bootstrap").json()
    assert len(data["audit"]) == main.BOOTSTRAP_AUDIT and int(data["meta"]["audit_total"]) == len(store.state["audit"])
    assert data["audit"][0]["target"] == f"T-{main.BOOTSTRAP_AUDIT + 4}"


def test_requests_never_wait_on_the_state_lock_in_the_event_loop(client):
    # Middleware headers used to take the state lock on the event loop: one slow handler froze
    # every connection. Holding the lock must not block an unrelated request.
    done = threading.Event()

    def call():
        assert client.get("/api/v1/health").status_code == 200
        done.set()

    with store.locked_state():
        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(timeout=10)  # safety bound only; a regression would hang here
    assert done.is_set()


def test_basemap_is_internal_only(client):
    settings = client.get("/api/v1/settings").json()
    assert settings["basemap_style_url"] == ""  # default: schematic map, no network request
    for public in ("https://tiles.openfreemap.org/styles/liberty", "https://tile.openstreetmap.org/style.json",
                   "https://user:pw@gis.example.org/style.json", "ftp://gis.example.org/style.json"):
        assert client.put("/api/v1/settings", json={**settings, "basemap_style_url": public}).status_code == 422
    internal = {**settings, "basemap_style_url": "https://gis.example.org/styles/aghajari/style.json"}
    assert client.put("/api/v1/settings", json=internal).json()["basemap_style_url"] == internal["basemap_style_url"]
    # The approved origin is the one the browser's CSP admits.
    csp = client.get("/api/v1/health").headers["content-security-policy"]
    assert "https://gis.example.org" in csp and "openfreemap" not in csp and "openstreetmap" not in csp


def fresh_report(client, asset, lon, lat):
    point = dict(lon=lon, lat=lat, time=(client.clock["now"] - timedelta(seconds=5)).isoformat(), accuracy_m=5)
    assert client.post(f"/api/v1/assets/{asset}/positions", json=point).status_code == 201


def new_incident(client, lon=49.75, lat=30.75):
    incident = store.create_incident("رخداد آزمون اعزام", "high", "آزمایش", store.lookup("assets", "AST-012"), "نمونه", "ثبت")
    incident.update(lon=lon, lat=lat)
    assert client.post(f"/api/v1/incidents/{incident['id']}/transition", json=dict(status="confirmed")).status_code == 200
    return incident


def test_dispatch_options_rank_fresh_patrols_and_explain_exclusions(client):
    incident = new_incident(client)
    patrols = [a for a in store.state["assets"] if a["kind"] == "vehicle" and a.get("unit", "patrol") == "patrol"
               and a["status"] != "offline" and a["id"] != incident["asset_id"]]
    near, far = patrols[0]["id"], patrols[1]["id"]
    fresh_report(client, near, 49.76, 30.75)
    fresh_report(client, far, 49.90, 30.75)
    options = client.get(f"/api/v1/incidents/{incident['id']}/dispatch-options").json()
    assert [r["asset_id"] for r in options["suggestions"]][:2] == [near, far]
    assert all(r["position_state"] == "fresh" and not r["needs_confirmation"] for r in options["suggestions"])
    assert len(options["suggestions"]) <= 3
    # Simulated or stale positions are never ranked as live; they wait for operator confirmation.
    assert all(r["needs_confirmation"] for r in options["needs_confirmation"])
    assert {r["asset_id"] for r in options["needs_confirmation"]}.isdisjoint({near, far})
    assert "شبکه راه" in options["eta_basis"]
    offline = next((a for a in store.state["assets"] if a["kind"] == "vehicle" and a["status"] == "offline"), None)
    reasons = {x["asset_id"]: x["reason"] for x in options["excluded"]}
    if offline:
        assert reasons[offline["id"]] == "بدون ارتباط"
    assert client.post(f"/api/v1/incidents/{incident['id']}/transition", json=dict(status="assigned", asset_id=near)).status_code == 200
    other = new_incident(client)
    busy = {x["asset_id"]: x["reason"] for x in client.get(f"/api/v1/incidents/{other['id']}/dispatch-options").json()["excluded"]}
    assert busy[near] == f"مشغول حادثه {incident['id']}"


def test_two_operators_cannot_assign_the_same_patrol(client):
    first, second = new_incident(client), new_incident(client)
    patrol = next(a["id"] for a in store.state["assets"] if a["kind"] == "vehicle" and a.get("unit", "patrol") == "patrol"
                  and a["status"] != "offline" and a["id"] != first["asset_id"])
    results, barrier = [], threading.Barrier(2)

    def assign(incident):
        barrier.wait()
        results.append(client.post(f"/api/v1/incidents/{incident['id']}/transition",
                                   json=dict(status="assigned", asset_id=patrol)).status_code)

    workers = [threading.Thread(target=assign, args=(i,)) for i in (first, second)]
    [w.start() for w in workers]
    [w.join(timeout=30) for w in workers]
    assert sorted(results) == [200, 409]
    assert sum(i.get("assigned_to") == patrol and i["status"] == "assigned" for i in store.state["incidents"]) == 1


def test_communication_gap_layer_separates_offline_queue_from_silence(client):
    now = client.clock["now"]
    path = "/api/v1/assets/AST-001/positions"
    # Observed on time but received an hour later: queued offline, evidence of no network here.
    for step in range(4):
        point = dict(lon=49.80, lat=30.80, time=(now - timedelta(minutes=60) + timedelta(seconds=30 * step)).isoformat(), accuracy_m=5)
        assert client.post(path, json=point).status_code == 201
    # Then a 40-minute silence starting at a different place; its cause is unknown.
    for when, lon in ((now - timedelta(minutes=50), 49.90), (now - timedelta(minutes=10), 49.90)):
        assert client.post(path, json=dict(lon=lon, lat=30.80, time=when.isoformat(), accuracy_m=5)).status_code == 201
    layer = client.get("/api/v1/intel/communication-gaps", params=dict(hours=2, cell_m=500)).json()
    by_lon = {round(c["lon"], 2): c for c in layer["cells"]}
    queued, silent = by_lon[49.8], by_lon[49.9]
    assert queued["offline_samples"] == 4 and queued["silences"] == 1  # the gap after the queued burst starts here
    assert silent["silences"] == 1 and silent["silence_minutes"] == 40.0 and silent["offline_samples"] >= 1
    assert all(c["confidence"] == "low" for c in layer["cells"])  # few samples: never presented as certain
    finding = store.lookup("findings", queued["finding_id"])
    assert finding["kind"] == "communication_gap" and finding["mode"] == "shadow" and finding["can_execute"] is False
    events = silent["offline_samples"] + silent["silences"]
    assert (silent["finding_id"] is not None) == (events >= store.state["settings"]["intel_comm_gap_min_events"])
    for bad in (dict(hours=0), dict(hours=500), dict(cell_m=10)):
        assert client.get("/api/v1/intel/communication-gaps", params=bad).status_code == 422
