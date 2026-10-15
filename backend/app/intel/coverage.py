"""Incremental patrol coverage over schematic segments and facilities."""

from datetime import timedelta

from ..core.tracks import parse_timestamp as _stamp
from ..core import store
from ..core.engine import observation_gap_seconds
from ..routers.incidents import patrol_vehicle
from ..core.sim import distance_km
from . import findings, geo

RULE_ID = "intel.coverage"



def coverage_items():
    return [("segment", row) for row in store.state["segments"]] + [
        ("facility", row) for row in store.state["facilities"]
    ]


def stale_hours(kind, item):
    key = "intel_coverage_unmanned_stale_hours" if kind == "facility" and item["unmanned"] else "intel_coverage_stale_hours"
    return store.state["settings"][key]


def _memory():
    return store.state["intel"].setdefault("coverage", {"cursors": {}, "visits": {}})


def _clear_finding(id, stamp):
    for finding in store.state["findings"]:
        if finding["rule_id"] == RULE_ID and finding["subject_ids"] == [id] and finding["status"] != "resolved":
            findings.resolve_finding(finding["id"], now_iso=stamp)


def _record_visit(item, point, asset_id, now):
    # Compliance must see this asset's visit even if another patrol has a newer
    # last_visit in the aggregate coverage record.
    from .patrol import record_visit
    record_visit(item["id"], asset_id, point["time"])
    visits = _memory()["visits"]
    visit = dict(last_visit=point["time"], last_asset_id=asset_id,
                 point=[point["lon"], point["lat"], point["time"]])
    from .shift_report import record_coverage_visit
    record_coverage_visit(item["id"], visit)
    previous = visits.get(item["id"])
    if previous is None or _stamp(point["time"]) > _stamp(previous["last_visit"]):
        visits[item["id"]] = dict(last_visit=point["time"], last_asset_id=asset_id,
                                  point=[point["lon"], point["lat"], point["time"]])
        _clear_finding(item["id"], now)


def _process_leg(previous, current, asset, indexed, now):
    a, b = [previous["lon"], previous["lat"]], [current["lon"], current["lat"]]
    candidates = [(kind, item, bounds) for kind, item, bounds in indexed
                  if geo.bboxes_intersect(geo.bbox([a, b]), bounds)]
    if not candidates:
        return
    start, end = _stamp(previous["time"]), _stamp(current["time"])
    gap = (end - start).total_seconds()
    # Narrow configured buffers/radii need closer samples than the 50 m ceiling.
    radii = [store.state["settings"]["intel_coverage_buffer_m"] if kind == "segment" else item["radius_m"]
             for kind, item, _ in candidates]
    step = min(50, *(radius for radius in radii if radius > 0)) if any(radius > 0 for radius in radii) else 1
    points = geo.densify(a, b, step) if 0 < gap <= observation_gap_seconds(asset) else [b]
    for index, point in enumerate(points):
        fraction = index / (len(points) - 1) if len(points) > 1 else 1
        stamp = (start + (end - start) * fraction).isoformat()
        for kind, item, bounds in candidates:
            if not geo.bbox_contains(bounds, point):
                continue
            visited = (
                geo.point_polyline_distance_m(point, item["points"]) <= store.state["settings"]["intel_coverage_buffer_m"]
                if kind == "segment" else
                distance_km(point, [item["lon"], item["lat"]]) * 1000 <= item["radius_m"]
            )
            if visited:
                _record_visit(item, dict(lon=point[0], lat=point[1], time=stamp), asset["id"], now)


@store.state_locked
def snapshot(now, visits=None):
    """Read current statuses and percentages without advancing observation cursors."""
    if visits is None:
        visits = store.state["intel"].get("coverage", {}).get("visits", {})
    items, fields = [], {asset["field"]: [0, 0] for asset in store.state["assets"]}
    for kind, item in coverage_items():
        visit = visits.get(item["id"])
        age = max(0, (_stamp(now) - _stamp(visit["last_visit"])).total_seconds() / 60) if visit else None
        status = "never" if visit is None else "stale" if age > stale_hours(kind, item) * 60 else "ok"
        items.append(dict(id=item["id"], kind=kind, status=status,
                          last_visit=visit["last_visit"] if visit else None,
                          last_asset_id=visit["last_asset_id"] if visit else None,
                          age_minutes=round(age, 1) if age is not None else None))
        counts = fields.setdefault(item["field"], [0, 0])
        counts[0] += status == "ok"
        counts[1] += 1
    ok = sum(item["status"] == "ok" for item in items)
    return dict(items=items, totals=dict(
        percent_ok=round(ok / len(items) * 100, 1) if items else 0,
        by_field={field: round(ok / total * 100, 1) if total else 0 for field, (ok, total) in fields.items()},
    ))


@store.state_locked
def tick(now):
    memory = _memory()
    settings = store.state["settings"]
    indexed = []
    for kind, item in coverage_items():
        bounds = geo.bbox(item["points"] if kind == "segment" else [[item["lon"], item["lat"]]])
        indexed.append((kind, item, geo.expand_bbox(bounds, settings["intel_coverage_buffer_m"] if kind == "segment" else item["radius_m"])))
    backfill_from = (_stamp(now) - timedelta(hours=settings["intel_coverage_backfill_hours"])).isoformat()
    for asset in store.state["assets"]:
        if not patrol_vehicle(asset):
            continue
        source = store.observation_source(asset)
        cursor = memory["cursors"].get(asset["id"])
        if cursor is not None and cursor["source"] != source:
            cursor = None
        since = cursor["point"]["time"] if cursor else backfill_from
        previous = cursor["point"] if cursor else None
        for point in store.observations_since(asset, since):
            stamp = _stamp(point["time"])
            if stamp > _stamp(now) or (previous and stamp <= _stamp(previous["time"])):
                continue
            _process_leg(previous or point, point, asset, indexed, now)
            previous = point
        if previous is not None:
            memory["cursors"][asset["id"]] = dict(source=source, point=dict(previous))

    records = {item["id"]: (kind, item) for kind, item in coverage_items()}
    for row in snapshot(now)["items"]:
        if row["status"] == "ok":
            _clear_finding(row["id"], now)
            continue
        kind, item = records[row["id"]]
        visit = memory["visits"].get(item["id"])
        label = item.get("name") or f"قطعه {item['index'] + 1} از {item['pipeline_id']}"
        findings.raise_finding(
            rule_id=RULE_ID, kind="coverage_gap", subject_ids=[item["id"]],
            summary=f"{label} · {'بازدید ثبت نشده' if row['status'] == 'never' else 'بازدید گشت به تأخیر افتاده'}",
            severity="medium" if kind == "facility" and item["unmanned"] else "low",
            mode=settings["intel_coverage_mode"], needs_incident=False,
            evidence=dict(
                rule="فاصله از مسیر گشت و زمان آخرین بازدید", thresholds=dict(
                    stale_hours=stale_hours(kind, item), buffer_m=settings["intel_coverage_buffer_m"] if kind == "segment" else item["radius_m"],
                ), window_from=visit["last_visit"] if visit else backfill_from, window_to=now,
                points=[visit["point"]] if visit else [], values=dict(
                    last_visit=row["last_visit"], last_asset_id=row["last_asset_id"], age_minutes=row["age_minutes"],
                    geometry=dict(type="LineString", coordinates=item["points"]) if kind == "segment" else dict(type="Point", coordinates=[item["lon"], item["lat"]]),
                    field=item["field"], status=row["status"],
                ),
            ), sources=[item["id"], *([row["last_asset_id"]] if row["last_asset_id"] else [])], now_iso=now,
        )
