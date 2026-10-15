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
