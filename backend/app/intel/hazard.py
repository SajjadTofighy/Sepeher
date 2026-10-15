"""Process-incident exposure and human-reviewed boundary closure suggestions."""

from datetime import timedelta

from ..core.tracks import parse_timestamp
from ..core import store
from ..core.engine import observation_gap_seconds
from ..routers.incidents import dispatchable, eta_minutes
from ..core.sim import distance_km
from .findings import raise_finding, resolve_finding
from .geo import closest_hazard_boundary, hazard_boundary_distance_m, hazard_contains

APPROACH_MIN_SPEED_KMH = 5
CLOSURE_PATROL_COUNT = 3

def _memory():
    return store.state["intel"].setdefault("hazard", {})


def _exposure(incident, stamp):
    area = incident.get("hazard_area")
    inside, approaching = [], []
    if not area or incident["status"] == "closed":
        return inside, approaching
    for asset in store.state["assets"]:
        point = [asset["lon"], asset["lat"]]
        distance = hazard_boundary_distance_m(point, area) / 1000
        row = dict(asset_id=asset["id"], name=asset["name"], distance_to_boundary_km=round(distance, 3), finding_id=None)
        if hazard_contains(point, area):
            inside.append(row)
            continue
        if asset["speed"] <= APPROACH_MIN_SPEED_KMH or incident.get("assigned_to") == asset["id"] or distance > store.state["settings"]["intel_hazard_approach_km"]:
            continue
        since = parse_timestamp(stamp) - timedelta(seconds=observation_gap_seconds(asset))
        points = store.observations_since(asset, since.isoformat())
        points = [p for p in points if parse_timestamp(p["time"]) <= parse_timestamp(stamp)]
        if len(points) < 2:
            continue
        previous, current = points[-2:]
        if (hazard_boundary_distance_m([current["lon"], current["lat"]], area)
                < hazard_boundary_distance_m([previous["lon"], previous["lat"]], area)):
            approaching.append((row, [previous, current]))
    return inside, approaching


@store.state_locked
def clear(incident_id, stamp=None):
    for finding_id in _memory().pop(incident_id, {}).values():
        resolve_finding(finding_id, stamp)


@store.state_locked
def tick(stamp):
    memory = _memory()
    active = {i["id"] for i in store.state["incidents"] if i["status"] != "closed" and i.get("hazard_area")}
    for id in list(memory):
        if id not in active:
            clear(id, stamp)
    for incident in store.state["incidents"]:
        if incident["id"] not in active:
            continue
        _, approaching = _exposure(incident, stamp)
        current = memory.setdefault(incident["id"], {})
        ids = {row["asset_id"] for row, _ in approaching}
        for asset_id in list(current):
            if asset_id not in ids:
                resolve_finding(current.pop(asset_id), stamp)
        for row, points in approaching:
            if row["asset_id"] in current:
                continue
            finding = raise_finding(
                rule_id="intel.hazard.approach", kind="hazard_approach", severity="high",
                subject_ids=[incident["id"], row["asset_id"]],
                summary=f"نزدیک‌شدن {row['name']} به محدوده خطر {incident['title']}",
                sources=[incident["id"], row["asset_id"]], now_iso=stamp,
                evidence=dict(rule="hazard_approach", thresholds=dict(approach_km=store.state["settings"]["intel_hazard_approach_km"], speed_kmh=APPROACH_MIN_SPEED_KMH),
                              window_from=points[0]["time"], window_to=points[-1]["time"],
                              points=[(p["lon"], p["lat"], p["time"]) for p in points],
                              values=dict(geometry=incident["hazard_area"], distance_to_boundary_km=row["distance_to_boundary_km"])),
            )
            finding["incident_id"] = incident["id"]
            current[row["asset_id"]] = finding["id"]
            incident["timeline"].append(dict(time=stamp, actor="موتور هوشمندی",
                                             action=f"هشدار نزدیک‌شدن {row['name']} به محدوده خطر · {finding['id']}"))


def _suggestions(incident):
    area = incident.get("hazard_area")
    if not area or incident["status"] == "closed":
        return []
    patrols = [a for a in store.state["assets"] if dispatchable(a, incident)]

    def suggestion(asset, target, distance, index=None):
        return dict(asset_id=asset["id"], name=asset["name"], lon=asset["lon"], lat=asset["lat"],
                    distance_km=round(distance, 3), distance_type="straight_line", eta_minutes=eta_minutes(distance),
                    eta_label="تخمینی", target=target, access_point_index=index)

    if area.get("access_points"):
        return [suggestion(asset, point, distance_km([asset["lon"], asset["lat"]], point), index)
                for index, point in enumerate(area["access_points"])
                if patrols
                for asset in [min(patrols, key=lambda a: distance_km([a["lon"], a["lat"]], point))]]
    nearest = sorted(patrols, key=lambda a: hazard_boundary_distance_m([a["lon"], a["lat"]], area))[:CLOSURE_PATROL_COUNT]
    return [suggestion(a, closest_hazard_boundary([a["lon"], a["lat"]], area),
                       hazard_boundary_distance_m([a["lon"], a["lat"]], area) / 1000) for a in nearest]


@store.state_locked
def snapshot(incident_id, stamp=None):
    incident = store.lookup("incidents", incident_id)
    inside, approaching = _exposure(incident, stamp or store.now())
    current = _memory().get(incident_id, {})
    return dict(inside=inside,
                approaching=[{**row, "finding_id": current.get(row["asset_id"])} for row, _ in approaching],
                closure_suggestions=_suggestions(incident))
