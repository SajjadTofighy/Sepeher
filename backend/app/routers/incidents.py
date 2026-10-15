from fastapi import APIRouter, HTTPException

from ..core.models import HazardArea, Incident, IncidentCreation, IncidentReport, NearbyPatrol, Transition
from ..core import sim, store
from ..security import authz
from ..field import safety as field_safety
from ..core.engine import point_in_polygon
from ..core.store import audit, lookup, now, plan_for, state, StateRoute

# No routable road network yet (design §15): ETA is an explicit estimate from straight-line
# distance, a road-winding factor and an average patrol speed.
ROAD_FACTOR = 1.3
PATROL_KMH = 45
# Demo playback compresses the drive so the dispatch is visible within a presentation.
DEMO_TIME_COMPRESSION = 5


def eta_minutes(km):
    return round(km * ROAD_FACTOR / PATROL_KMH * 60, 1)


def patrol_vehicle(a):
    return a["kind"] == "vehicle" and a.get("unit", "patrol") == "patrol"


def dispatchable(a, incident):
    return (
        patrol_vehicle(a)
        and a["status"] != "offline"
        and a["id"] != incident["asset_id"]
        and not any(i.get("assigned_to") == a["id"] and i["status"] != "closed" and i["id"] != incident["id"] for i in state["incidents"])
    )

router = APIRouter(route_class=StateRoute, tags=["incidents"])


@router.get("/api/v1/incidents", response_model=list[Incident])
def incidents():
    return state["incidents"]


@router.post("/api/v1/incidents", response_model=Incident, status_code=201)
def create_process_incident(payload: IncidentCreation):
    zone = next((z for z in state["zones"] if point_in_polygon(payload.lon, payload.lat, z["points"])), None)
    item = store.create_incident(
        title=payload.title, severity=payload.severity, zone=zone["name"] if zone else "حادثه فرایندی",
        zone_id=zone["id"] if zone else None,
        asset=dict(id="MANUAL-" + store.next_incident_id(), lon=payload.lon, lat=payload.lat),
        description=payload.description, first_action="ثبت دستی حادثه فرایندی", actor="اپراتور",
    )
    item["kind"] = "process"
    return item


def open_incident(id):
    item = lookup("incidents", id)
    if item["status"] == "closed":
        raise HTTPException(409, "محدوده خطر حادثه خاتمه‌یافته قابل تغییر نیست")
    return item


@router.put("/api/v1/incidents/{id}/hazard-area", response_model=Incident)
def set_hazard_area(id: str, payload: HazardArea):
    from ..intel import hazard

    item = open_incident(id)
    if item.get("hazard_area") == payload.model_dump():
        return item
    hazard.clear(id)
    item["hazard_area"] = payload.model_dump()
    item["timeline"].append(dict(time=store.now(), action="ثبت محدوده خطر", actor="اپراتور"))
    store.audit("ثبت محدوده خطر", id, payload.type, actor="اپراتور")
    hazard.tick(store.now())
    return item


@router.delete("/api/v1/incidents/{id}/hazard-area", response_model=Incident)
def clear_hazard_area(id: str):
    from ..intel import hazard

    item = open_incident(id)
    hazard.clear(id)
    item["hazard_area"] = None
    item["timeline"].append(dict(time=store.now(), action="حذف محدوده خطر", actor="اپراتور"))
    store.audit("حذف محدوده خطر", id, actor="اپراتور")
    return item


@router.get("/api/v1/incidents/{id}", response_model=Incident)
def incident(id: str):
    return lookup("incidents", id)


@router.post('/api/v1/incidents/{id}/ack', response_model=Incident)
def acknowledge_field_alert(id: str):
    principal = authz.require('manage')
    if not set(principal.roles) & field_safety.SECURITY_ROLES:
        raise HTTPException(403, 'رسید اعلام خطر به اپراتور امنیتی نیاز دارد')
    item = lookup('incidents', id)
    event = field_safety.acknowledge_incident(id, principal, store.now())
    if not item.get('operator_ack_at'):
        item['operator_ack_at'] = event['operator_ack_at']
        item['timeline'].append(dict(time=event['operator_ack_at'], action='رسید اپراتور اعلام خطر', actor=principal.username))
    return item


@router.post("/api/v1/incidents/{id}/transition", response_model=Incident)
def transition(id: str, p: Transition):
    item = lookup("incidents", id)
    flow = ["detected", "confirmed", "assigned", "en_route", "on_scene", "closed"]
    if flow.index(p.status) != flow.index(item["status"]) + 1:
        raise HTTPException(409, "ترتیب چرخه حادثه رعایت نشده است")
    if p.status == "assigned":
        if not p.asset_id:
            raise HTTPException(422, "انتخاب گشت لازم است")
        a = lookup("assets", p.asset_id)
        if not dispatchable(a, item):
            raise HTTPException(409, "گشت انتخابی آماده اعزام نیست")
        item["assigned_to"] = p.asset_id
        km = sim.distance_km([a["lon"], a["lat"]], [item["lon"], item["lat"]])
        item["eta_minutes"] = eta_minutes(km)
        sim.dispatch(
            plan_for(a),
            [item["lon"], item["lat"]],
            max(12, min(45, item["eta_minutes"] * 60 / DEMO_TIME_COMPRESSION)),
        )
    if p.status == "closed" and not p.note.strip():
        raise HTTPException(422, "گزارش خاتمه لازم است")
    item["status"] = p.status
    label = {
        "confirmed": "تأیید حادثه",
        "assigned": "ارجاع به گشت",
        "en_route": "گشت در مسیر",
        "on_scene": "حضور در محل",
        "closed": "خاتمه حادثه",
    }[p.status]
    item["timeline"].append(
        dict(
            time=now(),
            action=label + (" — " + p.note if p.note else ""),
            actor="اپراتور نمایشی",
        )
    )
    audit(label, id, p.asset_id or p.note)
    from ..intel import hazard
    hazard.tick(store.now())
    return item


@router.get("/api/v1/incidents/{id}/nearby", response_model=list[NearbyPatrol])
def nearby(id: str):
    return nearby_patrols(lookup("incidents", id))


def nearby_patrols(item):
    """Shared backup suggestions; eligibility and ETA stay identical to the API."""
    rows = []
    for a in state["assets"]:
        if not dispatchable(a, item):
            continue
        km = sim.distance_km([a["lon"], a["lat"]], [item["lon"], item["lat"]])
        rows.append(
            dict(
                asset_id=a["id"],
                name=a["name"],
                distance_km=round(km, 2),
                distance_type="straight_line",
                eta_minutes=eta_minutes(km),
                lon=a["lon"],
                lat=a["lat"],
            )
        )
    return sorted(rows, key=lambda x: x["distance_km"])


@router.get("/api/v1/incidents/{id}/report", response_model=IncidentReport)
def report(id: str):
    from ..intel import hazard
    audit("دریافت گزارش حادثه", id)
    return dict(incident=lookup("incidents", id), hazard=hazard.snapshot(id), generated_at=now(), mock=True)
