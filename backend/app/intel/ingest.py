"""Explicit read-only sensor inputs. No generated events or outbound integrations."""

from datetime import timezone

from fastapi import HTTPException

from ..core.tracks import parse_timestamp
from ..core import engine, store
from ..routers.incidents import nearby_patrols
from . import coverage, findings, geo

PRESSURE_DISABLED = "نیازمند مجوز بهره‌برداری و اتصال یک‌طرفه"
ANPR_DISABLED = "پلاک‌خوان غیرفعال است؛ اتصال ورودی واقعی و فعال‌سازی لازم است"


def require_enabled(key):
    if not store.state["settings"].get(key, False):
        raise HTTPException(409, PRESSURE_DISABLED if key == "intel_pressure_enabled" else ANPR_DISABLED)


def event_time(value):
    stamp = value.astimezone(timezone.utc)
    if stamp > parse_timestamp(store.now()):
        raise HTTPException(422, "زمان رخداد نباید در آینده باشد")
    return stamp.isoformat()


def pressure_segment(payload):
    store.lookup("pipelines", payload.pipeline_id)
    segments = sorted((s for s in store.state["segments"] if s["pipeline_id"] == payload.pipeline_id), key=lambda s: s["index"])
    if payload.segment_id is not None:
        segment = store.lookup("segments", payload.segment_id)
        if segment["pipeline_id"] != payload.pipeline_id:
            raise HTTPException(422, "قطعه متعلق به خط لوله انتخاب‌شده نیست")
        return segment, geo.polyline_midpoint(segment["points"])
    total = sum(s["length_m"] for s in segments)
    if not segments or payload.chainage_m > total:
        raise HTTPException(422, "فاصله طولی خارج از خط لوله است")
    offset = 0
    for segment in segments:
        # Boundary belongs to the next segment, except at the pipeline endpoint.
        if payload.chainage_m < offset + segment["length_m"] or segment is segments[-1]:
            return segment, geo.point_at_chainage(segment["points"], payload.chainage_m - offset)
        offset += segment["length_m"]


@store.state_locked
def pipeline_pressure(payload):
    require_enabled("intel_pressure_enabled")
    stamp = event_time(payload.time)
    segment, point = pressure_segment(payload)
    events = store.state["pressure_events"]
    existing = next((e for e in events if (e["pipeline_id"], e["segment_id"], e["chainage_m"], e["time"], e["source"]) ==
                     (payload.pipeline_id, segment["id"], payload.chainage_m, stamp, payload.source)), None)
    if existing:
        if existing["pressure_drop_pct"] != payload.pressure_drop_pct:
            raise HTTPException(409, "برای این منبع، محل و زمان، افت فشار متفاوتی ثبت شده است")
        finding = store.lookup("findings", existing["finding_id"])
        return dict(event=existing, finding=finding, incident=store.lookup("incidents", finding["incident_id"]) if finding["incident_id"] else None)
    event = dict(id=f"PRS-{len(events) + 1:04}", pipeline_id=payload.pipeline_id, segment_id=segment["id"],
                 chainage_m=payload.chainage_m, time=stamp, received_at=store.now(), pressure_drop_pct=payload.pressure_drop_pct,
                 source=payload.source, lon=point[0], lat=point[1])
    last_visit = next(r for r in coverage.snapshot(store.now())["items"] if r["id"] == segment["id"])
    zone = next((z for z in store.state["zones"] if engine.point_in_polygon(*point, z["points"])), None)
    candidates = nearby_patrols(dict(id=None, asset_id=segment["id"], lon=point[0], lat=point[1]))
    nearest = candidates[0] if candidates else None
    context = dict(event_id=event["id"], pipeline_id=payload.pipeline_id, segment_id=segment["id"], last_visit=last_visit,
                   nearest_patrol=nearest, nearest_patrol_position_source=store.observation_source(store.lookup("assets", nearest["asset_id"])) if nearest else None)
    finding = findings.raise_finding(rule_id="intel.pressure", kind="pressure_drop", subject_ids=[segment["id"], event["id"]],
        summary=f"افت فشار گزارش‌شده {payload.pressure_drop_pct:g}٪ · قطعه {segment['id']}", severity="high",
        mode=store.state["settings"]["intel_pressure_mode"], needs_incident=True, zone_id=zone["id"] if zone else None,
        now_iso=event["received_at"], evidence=dict(rule="افت فشار اعلام‌شده از ورودی یک‌طرفه", thresholds=dict(pressure_drop_pct_gt=0),
            window_from=stamp, window_to=stamp, points=[[point[0], point[1], stamp]], values=dict(
                pressure_drop_pct=payload.pressure_drop_pct, source=payload.source, received_at=event["received_at"],
                chainage_m=payload.chainage_m, geometry=dict(type="Point", coordinates=point), **context)),
        sources=[event["id"], payload.pipeline_id, segment["id"], *([last_visit["last_asset_id"]] if last_visit["last_asset_id"] else []),
                 *([nearest["asset_id"]] if nearest else [])])
    event["finding_id"] = finding["id"]
    incident = store.lookup("incidents", finding["incident_id"]) if finding["incident_id"] else None
    if incident:
        incident.update(kind="pressure_drop", pressure_context=context, backup_patrols=[nearest] if nearest else [])
    events.append(event)
    store.audit("دریافت یک‌طرفه رخداد افت فشار", event["id"], f"{payload.source} · {segment['id']}")
    return dict(event=event, finding=finding, incident=incident)


@store.state_locked
def plate_read(payload):
    require_enabled("intel_anpr_enabled")
    camera = store.lookup("cameras", payload.camera_id)
    stamp = event_time(payload.time)
    reads = store.state["plate_reads"]
    existing = next((e for e in reads if (e["camera_id"], e["plate"], e["time"]) == (payload.camera_id, payload.plate, stamp)), None)
    if existing:
        if existing["vehicle_class"] != payload.vehicle_class:
            raise HTTPException(409, "برای این دوربین، پلاک و زمان، رده خودروی متفاوتی ثبت شده است")
        event = existing
    else:
        event = dict(id=f"ANPR-{len(reads) + 1:04}", type="plate_read", source="reported", camera_id=camera["id"],
                     plate=payload.plate, time=stamp, received_at=store.now(), vehicle_class=payload.vehicle_class,
                     lon=camera["lon"], lat=camera["lat"], sensitive=camera["id"] in store.state["settings"]["intel_anpr_sensitive_camera_ids"],
                     alert_ids=[], finding_ids=[], incident_ids=[])
        fired = engine.evaluate(store.state, engine.plate_subject(store.state, event), event["received_at"],
                                store.create_incident, store.audit, event=event, record_finding=findings.raise_finding)
        event["alert_ids"] = [a["id"] for a in fired]
        event["finding_ids"] = [a["finding_id"] for a in fired if a["finding_id"]]
        event["incident_ids"] = list(dict.fromkeys(a["incident_id"] for a in fired if a["incident_id"]))
        for id in event["incident_ids"]:
            store.lookup("incidents", id)["kind"] = "anpr"
        reads.append(event)
        store.audit("دریافت خوانش واقعی پلاک", event["id"], camera["id"])
    return dict(event=event, alerts=[store.lookup("alerts", id) for id in event["alert_ids"]],
                findings=[store.lookup("findings", id) for id in event["finding_ids"]],
                incidents=[store.lookup("incidents", id) for id in event["incident_ids"]])
