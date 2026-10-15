import json

import pytest

from app.core import roads
from app.core.roads import RoadGraph, from_geojson, from_osm_xml
from test_intel_gis import client  # noqa: F401  (frozen-clock API client)


@pytest.fixture(autouse=True)
def schematic_network():
    roads.reset()
    yield
    roads.reset()


def ladder():
    """Two parallel roads joined at both ends: a slow direct road and a fast detour."""
    g = RoadGraph("test")
    g.add_way([[50.00, 30.00], [50.10, 30.00]], "track")  # 20 km/h direct
    g.add_way([[50.00, 30.00], [50.00, 30.01], [50.10, 30.01], [50.10, 30.00]], "motorway_link")
    return g


def test_fastest_path_prefers_time_over_distance():
    r = ladder().route([50.00, 30.00], [50.10, 30.00])
    assert [50.00, 30.01] in r["path"] and r["distance_km"] > 9.6
    assert r["eta_minutes"] < 9.6 / 20 * 60


def test_one_way_and_off_network_are_respected():
    g = RoadGraph("test")
    g.add_way([[50.0, 30.0], [50.0, 30.01]], "service", oneway="yes")
    assert g.route([50.0, 30.0], [50.0, 30.01]) and g.route([50.0, 30.01], [50.0, 30.0]) is None
    g.add_way([[50.1, 30.0], [50.1, 30.01]], "footway")  # not drivable
    assert g.edges == 1
    assert g.route([51.0, 31.0], [50.0, 30.01]) is None  # beyond MAX_SNAP_KM


def test_reverse_search_matches_point_to_point_routes():
    g = roads.network()
    target = [49.95, 30.85]
    origins = [[49.70, 30.70], [49.88, 30.801], [49.66, 30.90]]
    for origin, many in zip(origins, g.to_destination(origins, target)):
        one = g.route(origin, target)
        if one is None:  # the one-way spur's dead end cannot leave
            assert many is None and origin == [49.88, 30.801]
            continue
        assert many["eta_minutes"] == one["eta_minutes"] and many["distance_km"] == one["distance_km"]


def test_offline_osm_and_geojson_extracts(tmp_path):
    osm = tmp_path / "region.osm"
    osm.write_text("""<osm><node id="1" lat="30.0" lon="50.0"/><node id="2" lat="30.0" lon="50.01"/>
      <node id="3" lat="30.0" lon="50.02"/>
      <way id="9"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="primary"/><tag k="maxspeed" v="60"/></way>
      <way id="10"><nd ref="1"/><nd ref="3"/><tag k="highway" v="primary"/><tag k="access" v="private"/></way></osm>""")
    g = from_osm_xml(str(osm), "osm")
    r = g.route([50.0, 30.0], [50.02, 30.0])
    assert g.edges == 4 and r["eta_minutes"] == round(r["distance_km"] / 60 * 60, 1)
    path = tmp_path / "roads.geojson"
    path.write_text(json.dumps(dict(type="FeatureCollection", features=[dict(type="Feature",
        properties=dict(highway="residential", oneway="-1"), geometry=dict(type="LineString", coordinates=[[50, 30], [50, 30.01]]))])))
    g = roads.load(str(path))
    assert g.source == "geojson" and g.route([50, 30.01], [50, 30]) and not g.route([50, 30], [50, 30.01])
    assert from_geojson(dict(features=[]), "x").edges == 0


def test_routing_api_and_dispatch_use_road_eta(client):
    status = client.get("/api/v1/routing/network").json()
    assert status["source"] == "schematic" and status["nodes"] > 100
    r = client.get("/api/v1/routing/route", params=dict(from_lon=49.70, from_lat=30.70, to_lon=49.95, to_lat=30.85)).json()
    assert r["path"][0] == [49.70, 30.70] and r["path"][-1] == [49.95, 30.85]
    assert client.get("/api/v1/routing/route", params=dict(from_lon=49.88, from_lat=30.801, to_lon=49.88, to_lat=30.779)).status_code == 404
    from app.core import store
    incident = store.create_incident("آزمون مسیر", "high", "آزمایش", store.lookup("assets", "AST-012"), "نمونه", "ثبت")
    incident.update(lon=49.95, lat=30.85)
    options = client.get(f"/api/v1/incidents/{incident['id']}/dispatch-options").json()
    rows = options["suggestions"] + options["needs_confirmation"]
    assert rows and all(row["distance_type"] == "road" for row in rows if roads.network().nearest([row["lon"], row["lat"]]))
    assert "شبکه راه شماتیک" in options["eta_basis"]
    assert [x["eta_minutes"] for x in options["needs_confirmation"]] == sorted(x["eta_minutes"] for x in options["needs_confirmation"])


def test_alternatives_are_distinct_bounded_and_avoid_closed_areas():
    g = roads.network()
    origin, target = [49.70, 30.70], [49.95, 30.85]
    found = g.routes(origin, target, 3)
    assert [r["id"] for r in found] == ["R1", "R2", "R3"][:len(found)] and len(found) >= 2
    assert found[0]["label"] == "سریع‌ترین" and found[1]["label"] == "جایگزین ۱"
    assert all(r["eta_minutes"] >= found[0]["eta_minutes"] for r in found)
    assert all(r["eta_minutes"] <= found[0]["eta_minutes"] * roads.MAX_DETOUR for r in found)
    assert len({tuple(map(tuple, r["path"])) for r in found}) == len(found)
    closed = dict(type="circle", center=[49.82, 30.78], radius_m=3000)
    from app.core.sim import distance_km
    for r in g.routes(origin, target, 3, [closed]):
        assert all(distance_km(p, closed["center"]) * 1000 > closed["radius_m"] for p in r["path"])
    walled = dict(type="polygon", points=[[49.60, 30.60], [50.30, 30.60], [50.30, 30.95], [49.60, 30.95]])
    assert g.routes(origin, target, 3, [walled]) == []  # whole network closed: no road route, caller falls back
    assert g.routes(origin, [49.88, 30.79], 3)  # ...a one-way spur reached the legal way


def test_simulated_patrol_follows_the_road_path():
    from app.core import sim
    plan = dict(routes=[], radius=0.01, period=900, aspect=1, phase=0, direction=1, t0=0, center=[49.62, 30.78])
    path = [[49.70, 30.78], [49.70, 30.86]]
    sim.dispatch(plan, [49.78, 30.86], 100, now=1000, path=path)
    start = sim.position(plan, 1000)
    middle = sim.position(plan, 1050)
    corner_share = (sim.distance_km(start, path[0]) + sim.distance_km(*path)) / (
        sim.distance_km(start, path[0]) + sim.distance_km(*path) + sim.distance_km(path[1], [49.78, 30.86]))
    corner = sim.position(plan, 1000 + 100 * corner_share)
    assert abs(corner[0] - 49.70) < 1e-6 and abs(corner[1] - 30.86) < 1e-6
    assert sim.position(plan, 2000) == [49.78, 30.86]
    assert middle != [start[0] + (49.78 - start[0]) / 2, start[1] + (30.86 - start[1]) / 2]


def test_assignment_stores_chosen_route_and_routes_api(client):
    from app.core import store
    incident = store.create_incident("آزمون مسیر انتخابی", "high", "آزمایش", store.lookup("assets", "AST-012"), "نمونه", "ثبت")
    incident.update(lon=49.95, lat=30.85)
    assert client.post(f"/api/v1/incidents/{incident['id']}/transition", json=dict(status="confirmed")).status_code == 200
    patrol = client.get(f"/api/v1/incidents/{incident['id']}/dispatch-options").json()["suggestions"] or \
        client.get(f"/api/v1/incidents/{incident['id']}/dispatch-options").json()["needs_confirmation"]
    asset = patrol[0]["asset_id"]
    plan = client.get(f"/api/v1/incidents/{incident['id']}/routes", params=dict(asset_id=asset)).json()
    assert plan["source"] == "schematic" and plan["routes"]
    pick = plan["routes"][-1]
    body = dict(status="assigned", asset_id=asset, route_id="R9")
    assert client.post(f"/api/v1/incidents/{incident['id']}/transition", json=body).status_code == 422
    body["route_id"] = pick["id"]
    item = client.post(f"/api/v1/incidents/{incident['id']}/transition", json=body).json()
    assert item["route"]["id"] == pick["id"] and item["eta_minutes"] == item["route"]["eta_minutes"]
    assert {r["id"] for r in item["route_alternatives"]} == {r["id"] for r in plan["routes"]} - {pick["id"]}
    assert store.plan_for(store.lookup("assets", asset))["routes"][-1]["path"] == item["route"]["path"][1:-1]
    free = client.post("/api/v1/routing/routes", json=dict(origin=[49.70, 30.70], destination=[49.95, 30.85])).json()
    blocked = client.post("/api/v1/routing/routes", json=dict(origin=[49.70, 30.70], destination=[49.95, 30.85],
        avoid_areas=[dict(type="circle", center=[49.82, 30.78], radius_m=3000)])).json()
    assert blocked["avoided_areas"] == 1 and blocked["routes"][0]["eta_minutes"] > free["routes"][0]["eta_minutes"]
    assert client.post("/api/v1/routing/routes", json=dict(origin=[200, 30], destination=[49.9, 30.8])).status_code == 422


def test_trail_keeps_road_bends_of_a_short_dispatch():
    from app.core import sim
    plan = dict(routes=[], radius=0.01, period=900, aspect=1, phase=0, direction=1, t0=0, center=[49.62, 30.78])
    sim.dispatch(plan, [49.78, 30.86], 12, now=1000, path=[[49.70, 30.78], [49.70, 30.86]])
    asset = dict(id="X")
    sim.apply(asset, plan, now=1100)
    points = [[round(p["lon"], 6), round(p["lat"], 6)] for p in asset["track"]]
    assert [49.70, 30.78] in points and [49.70, 30.86] in points
