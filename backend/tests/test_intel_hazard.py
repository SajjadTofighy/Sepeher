"""Hazard geometry, approach latches and operator-controlled incident lifecycle."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import sim, store
from app.intel import hazard, worker
from app.main import app
from app.core.seed import seed


@pytest.fixture
def case(track_database, monkeypatch):
    clock = SimpleNamespace(t=datetime(2099, 1, 1, 9, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(store, "now", lambda: sim.iso(clock.t))
    monkeypatch.setattr(sim.time, "time", lambda: clock.t)
    store.state.clear()
    store.state.update(seed())
    store.state["policies"] = []
    incident = store.create_incident("نشت گاز نمونه", "critical", "نمونه", dict(id="MANUAL", lon=49.78, lat=30.76),
                                     "شرح نمونه", "ثبت دستی", actor="اپراتور")
    incident["hazard_area"] = dict(type="circle", center=[49.78, 30.76], radius_m=200, access_points=[])
    asset = store.state["assets"][0]
    asset.update(synthetic=True, speed=30, status="online")
    return clock, incident, asset


def move(asset, clock, before, after):
    asset.update(lon=after[0], lat=after[1], last_seen=sim.iso(clock.t))
    asset["track"] = [dict(lon=point[0], lat=point[1], time=sim.iso(clock.t - delta))
                      for point, delta in [(before, 30), (after, 0)]]


@pytest.mark.parametrize("area", [dict(type="circle", center=[49.78, 30.76], radius_m=200),
                                   dict(type="polygon", points=[[49.77, 30.75], [49.79, 30.75], [49.79, 30.77], [49.77, 30.77]])])
def test_circle_and_polygon_inside(case, area):
    clock, incident, asset = case
    incident["hazard_area"] = area
    move(asset, clock, [49.78, 30.76], [49.78, 30.76])
    result = hazard.snapshot(incident["id"])
    assert asset["id"] in [a["asset_id"] for a in result["inside"]]
    assert asset["id"] not in [a["asset_id"] for a in result["approaching"]]
    assert hazard in worker.capabilities


def test_approaching_is_latched_and_never_creates_an_incident(case):
    clock, incident, asset = case
    move(asset, clock, [49.80, 30.76], [49.79, 30.76])
    count = len(store.state["incidents"])
    hazard.tick(store.now())
    hazard.tick(store.now())
    found = [f for f in store.state["findings"] if f["kind"] == "hazard_approach" and asset["id"] in f["subject_ids"]]
    assert len(found) == 1 and found[0]["severity"] == "high"
    assert found[0]["incident_id"] == incident["id"] and found[0]["can_execute"] is False
    assert len(store.state["incidents"]) == count
    assert sum(found[0]["id"] in e["action"] for e in incident["timeline"]) == 1
    assert next(a for a in hazard.snapshot(incident["id"])["approaching"] if a["asset_id"] == asset["id"])["finding_id"] == found[0]["id"]
    with TestClient(app) as client:
        assert client.put(f"/api/v1/incidents/{incident['id']}/hazard-area", json=incident["hazard_area"]).status_code == 200
        report = client.get(f"/api/v1/incidents/{incident['id']}/report").json()
        assert report["incident"]["hazard_area"] and report["hazard"]["approaching"]
    assert sum(asset["id"] in f["subject_ids"] for f in store.state["findings"]) == 1


def test_moving_away_and_slow_assets_do_not_fire(case):
    clock, incident, asset = case
    move(asset, clock, [49.79, 30.76], [49.80, 30.76])
    hazard.tick(store.now())
    assert not any(asset["id"] in f["subject_ids"] for f in store.state["findings"])
    move(asset, clock, [49.80, 30.76], [49.79, 30.76])
    asset["speed"] = 5
    hazard.tick(store.now())
    assert not any(asset["id"] in f["subject_ids"] for f in store.state["findings"])


def test_assigned_patrol_is_excluded_and_approach_resolves(case):
    clock, incident, asset = case
    move(asset, clock, [49.80, 30.76], [49.79, 30.76])
    hazard.tick(store.now())
    finding = next(f for f in store.state["findings"] if asset["id"] in f["subject_ids"])
    incident["assigned_to"] = asset["id"]
    hazard.tick(store.now())
    assert finding["status"] == "resolved"
    assert asset["id"] not in [a["asset_id"] for a in hazard.snapshot(incident["id"])["approaching"]]


def test_suggestions_exclude_busy_patrols_and_use_boundary_or_access_point(case):
    clock, incident, asset = case
    move(asset, clock, [49.79, 30.76], [49.79, 30.76])
    store.state["incidents"][1].update(assigned_to=asset["id"], status="assigned")
    rows = hazard.snapshot(incident["id"])["closure_suggestions"]
    assert len(rows) == 3 and asset["id"] not in [r["asset_id"] for r in rows]
    assert all(r["eta_label"] == "تخمینی" for r in rows)
    assert [r["distance_km"] for r in rows] == sorted(r["distance_km"] for r in rows)
    incident["hazard_area"]["access_points"] = [[49.7, 30.7], [49.8, 30.8]]
    rows = hazard.snapshot(incident["id"])["closure_suggestions"]
    assert [r["target"] for r in rows] == incident["hazard_area"]["access_points"]
    eligible = [a for a in store.state["assets"] if a["kind"] == "vehicle" and a["unit"] == "patrol" and a["status"] != "offline" and a["id"] != asset["id"]]
    for row in rows:
        expected = min(eligible, key=lambda a: sim.distance_km([a["lon"], a["lat"]], row["target"]))
        assert row["asset_id"] == expected["id"]


def test_closed_incident_rejects_area_changes_and_clears_warning(case):
    clock, incident, asset = case
    move(asset, clock, [49.80, 30.76], [49.79, 30.76])
    hazard.tick(store.now())
    incident["status"] = "closed"
    hazard.tick(store.now())
    with TestClient(app) as client:
        path = f"/api/v1/incidents/{incident['id']}/hazard-area"
        assert client.put(path, json=incident["hazard_area"]).status_code == 409
        assert client.delete(path).status_code == 409
    assert not hazard.snapshot(incident["id"])["approaching"]
    assert all(f["status"] == "resolved" for f in store.state["findings"])


def test_manual_incident_uses_normal_lifecycle_and_shared_polygon_validation(case):
    clock, _, _ = case
    with TestClient(app) as client:
        payload = dict(title="آتش‌سوزی نمونه", severity="critical", lon=49.78, lat=30.76, description="گزارش اپراتور")
        response = client.post("/api/v1/incidents", json=payload)
        assert response.status_code == 201
        incident = response.json()
        assert incident["status"] == "detected" and incident["kind"] == "process"
        assert incident["timeline"][0]["actor"] == "اپراتور"
        id = incident["id"]
        area = dict(type="polygon", points=[[49.7, 30.7], [49.8, 30.7], [49.8, 30.8]])
        path = f"/api/v1/incidents/{id}/hazard-area"
        assert client.put(path, json=area).status_code == 200
        assert client.get(f"/api/v1/intel/hazard/{id}").status_code == 200
        assert client.put(path, json={**area, "points": [[49, 30], [49, 30], [49, 30]]}).status_code == 422
        assert client.put(path, json=dict(type="circle", center=[200, 30], radius_m=100)).status_code == 422
        assert client.delete(path).json()["hazard_area"] is None
        assert client.post(f"/api/v1/incidents/{id}/transition", json={"status": "assigned"}).status_code == 409
        assert client.post(f"/api/v1/incidents/{id}/transition", json={"status": "confirmed"}).status_code == 200
        patrol = client.get(f"/api/v1/incidents/{id}/nearby").json()[0]["asset_id"]
        for status in ["assigned", "en_route", "on_scene", "closed"]:
            result = client.post(f"/api/v1/incidents/{id}/transition", json=dict(status=status, asset_id=patrol, note="گزارش خاتمه"))
            assert result.status_code == 200
        assert result.json()["status"] == "closed"
        assert client.post("/api/v1/incidents", json={**payload, "lat": 90}).status_code == 422
