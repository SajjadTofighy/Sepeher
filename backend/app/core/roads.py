"""Offline road-graph routing: fastest path over a local road network, no external service.

The network is read once from SEPEHR_ROAD_NETWORK, an offline OpenStreetMap extract (.osm XML) or
GeoJSON LineStrings exported from the organisation's GIS (properties highway, maxspeed, oneway).
Without it the synthetic schematic network in seed.py is used and labelled as such."""

import heapq
import json
import math
import os
import threading
import xml.etree.ElementTree as ET

from .sim import distance_km

# Default speeds (km/h) by OSM highway class; ways of other classes (footway, etc.) are not drivable.
SPEEDS = dict(motorway=90, motorway_link=60, trunk=80, trunk_link=50, primary=70, primary_link=40,
              secondary=60, secondary_link=40, tertiary=50, tertiary_link=30, unclassified=40,
              residential=30, service=20, track=20, living_street=10, road=30)
ACCESS_KMH = 15  # leg between the true position and the nearest road node
MAX_SNAP_KM = 2.0  # farther than this from any road node: no road route, caller falls back
CELL_DEG = 0.01


def _speed(highway, maxspeed):
    try:
        text = str(maxspeed or "").strip().lower()
        value = float("".join(c for c in text.split(";")[0] if c.isdigit() or c == "."))
        return value * 1.609 if "mph" in text else value
    except ValueError:
        return SPEEDS.get(highway)


class RoadGraph:
    def __init__(self, source):
        self.source, self.coords, self.ids, self.out, self.inc, self.grid = source, [], {}, [], [], {}
        self.edges = 0

    def _node(self, lon, lat):
        key = (round(lon, 7), round(lat, 7))
        if key not in self.ids:
            self.ids[key] = len(self.coords)
            self.coords.append([lon, lat])
            self.out.append([])
            self.inc.append([])
            self.grid.setdefault((math.floor(lon / CELL_DEG), math.floor(lat / CELL_DEG)), []).append(self.ids[key])
        return self.ids[key]

    def add_way(self, points, highway, maxspeed=None, oneway=None):
        speed = _speed(highway, maxspeed) if highway in SPEEDS or maxspeed else None
        if not speed or len(points) < 2:
            return
        flag = str(oneway or "").lower()
        if flag == "-1":
            points = list(reversed(points))
        one = flag in ("yes", "true", "1", "-1") or highway in ("motorway",)
        nodes = [self._node(float(p[0]), float(p[1])) for p in points]
        for a, b in zip(nodes, nodes[1:]):
            if a == b:
                continue
            km = distance_km(self.coords[a], self.coords[b])
            edge = km / speed * 60
            self.out[a].append((b, km, edge))
            self.inc[b].append((a, km, edge))
            self.edges += 1
            if not one:
                self.out[b].append((a, km, edge))
                self.inc[a].append((b, km, edge))
                self.edges += 1

    def nearest(self, point):
        cx, cy = math.floor(point[0] / CELL_DEG), math.floor(point[1] / CELL_DEG)
        best, ring = None, 0
        reach = math.ceil(MAX_SNAP_KM / (CELL_DEG * 111 * math.cos(math.radians(point[1])))) + 1
        while ring <= reach:
            for x in range(cx - ring, cx + ring + 1):
                for y in range(cy - ring, cy + ring + 1):
                    if max(abs(x - cx), abs(y - cy)) != ring:
                        continue
                    for n in self.grid.get((x, y), ()):
                        km = distance_km(point, self.coords[n])
                        if km <= MAX_SNAP_KM and (best is None or km < best[1]):
                            best = (n, km)
            # A node one ring further can still be closer than one found in a corner cell.
            if best and ring * CELL_DEG * 111 * math.cos(math.radians(point[1])) > best[1]:
                break
            ring += 1
        return best

    def _search(self, start, edges, goal=None):
        minutes, km, prev, heap = {start: 0.0}, {start: 0.0}, {}, [(0.0, start)]
        while heap:
            t, n = heapq.heappop(heap)
            if t > minutes[n]:
                continue
            if n == goal:
                break
            for m, d, e in edges[n]:
                if t + e < minutes.get(m, math.inf):
                    minutes[m], km[m], prev[m] = t + e, km[n] + d, n
                    heapq.heappush(heap, (t + e, m))
        return minutes, km, prev

    def route(self, origin, destination):
        """Fastest path origin → destination, or None when either end is off the network or unreachable."""
        a, b = self.nearest(origin), self.nearest(destination)
        if not a or not b:
            return None
        minutes, km, prev = self._search(a[0], self.out, b[0])
        if b[0] not in minutes:
            return None
        path, n = [self.coords[b[0]]], b[0]
        while n != a[0]:
            n = prev[n]
            path.append(self.coords[n])
        path.reverse()
        return self._result(a[1] + b[1], km[b[0]], minutes[b[0]], [list(origin), *path, list(destination)])

    def to_destination(self, origins, destination):
        """One reverse search from the destination gives every origin's fastest drive to it."""
        b = self.nearest(destination)
        if not b:
            return [None] * len(origins)
        minutes, km, _ = self._search(b[0], self.inc)
        results = []
        for origin in origins:
            a = self.nearest(origin)
            ok = a and a[0] in minutes
            results.append(self._result(a[1] + b[1], km[a[0]], minutes[a[0]], None) if ok else None)
        return results

    def _result(self, access_km, road_km, road_minutes, path):
        return dict(distance_km=round(access_km + road_km, 2), eta_minutes=round(road_minutes + access_km / ACCESS_KMH * 60, 1),
                    access_km=round(access_km, 3), path=path, source=self.source)


def from_geojson(data, source):
    graph = RoadGraph(source)
    for f in data.get("features", []):
        g, p = f.get("geometry") or {}, f.get("properties") or {}
        lines = [g.get("coordinates", [])] if g.get("type") == "LineString" else g.get("coordinates", []) if g.get("type") == "MultiLineString" else []
        for line in lines:
            graph.add_way(line, p.get("highway"), p.get("maxspeed"), p.get("oneway"))
    return graph


def from_osm_xml(path, source):
    graph, nodes, way, tags = RoadGraph(source), {}, None, {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = (float(el.get("lon")), float(el.get("lat")))
            el.clear()
        elif el.tag == "way":
            refs = [nd.get("ref") for nd in el.findall("nd")]
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags.get("highway") and tags.get("access") not in ("no", "private"):
                graph.add_way([nodes[r] for r in refs if r in nodes], tags["highway"], tags.get("maxspeed"), tags.get("oneway"))
            el.clear()
    return graph


def load(path=None):
    path = path if path is not None else os.environ.get("SEPEHR_ROAD_NETWORK", "")
    if not path:
        from .seed import schematic_roads
        return from_geojson(schematic_roads(), "schematic")
    if path.endswith((".osm", ".xml")):
        return from_osm_xml(path, "osm")
    with open(path, encoding="utf-8") as f:
        return from_geojson(json.load(f), "geojson")


_lock, _graph = threading.Lock(), None


def network():
    global _graph
    with _lock:
        if _graph is None:
            _graph = load()
        return _graph


def reset(graph=None):
    """Replace the cached network (tests, or after the operator installs a new extract)."""
    global _graph
    with _lock:
        _graph = graph
