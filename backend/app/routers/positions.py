"""GPS ingestion for local device adapters; history survives server restarts."""
from datetime import timezone
from fastapi import APIRouter, HTTPException, Request
from ..core import engine, store
from ..security import authz
from ..field import offline
from ..core.models import DeviceEventInput, DeviceEventResult, PositionInput, PositionBatchInput, PositionBatchResult, PositionReceipt
from ..core.sim import distance_km
from ..core.store import StateRoute
from ..core.tracks import TrackConflict
from ..core.tracks import parse_timestamp, utc_timestamp
from ..security.auth import current_principal

router = APIRouter(route_class=StateRoute, tags=["positions"])


def assess(asset_id, point, received_at):
    """Quality flags and live acceptance for one observation (rules are explainable, never 'spoofing').

    Rejects only what would corrupt the live picture: a timestamp beyond the allowed clock skew
    would otherwise stay "newest" forever. Everything else is stored; an implausible jump is kept
    as raw history but does not move the live position.
    """
    settings = store.state["settings"]
    observed, received = parse_timestamp(point.time), parse_timestamp(received_at)
    ahead = (observed - received).total_seconds()
    if ahead > settings["field_clock_skew_seconds"]:
        raise HTTPException(422, "زمان موقعیت بیش از انحراف مجاز ساعت در آینده است")
    flags = []
    if ahead > 0:
        flags.append("clock_ahead")
    if point.accuracy_m is None:
        flags.append("accuracy_unknown")
    elif point.accuracy_m > settings["field_location_max_accuracy_m"]:
        flags.append("low_accuracy")
    latest = store.latest_observation(store.lookup("assets", asset_id))
    if latest and latest["source"] == "reported" and parse_timestamp(latest["time"]) > observed:
        flags.append("late")
    # In-order reports (the common case) compare with the cached newest live report.
    in_order = latest and latest["source"] == "reported" and parse_timestamp(latest["time"]) < observed
    previous = latest if in_order else store.tracks.previous_reported(asset_id, point.time)
    live = True
    if previous:
        seconds = (observed - parse_timestamp(previous["time"])).total_seconds()
        kmh = distance_km([previous["lon"], previous["lat"]], [point.lon, point.lat]) / (seconds / 3600)
        if kmh > settings["field_location_max_speed_kmh"]:
            flags.append("implausible_speed")
            live = False
    return flags, live


def ingest_position(id, point, auth):
    asset = store.lookup("assets", id)
    received_at = utc_timestamp(store.now())
    flags, live = assess(id, point, received_at)
    try:
        result, created = store.tracks.append(id, point.lon, point.lat, point.time, point.speed, received_at=received_at,
                                              accuracy_m=point.accuracy_m, fix_source=point.fix_source,
                                              sequence=point.sequence, auth=auth, flags=flags, live=live)
    except TrackConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    store.refresh_track(asset)
    if any(cp.get("target_id") for m in store.state["missions"] for cp in m["checkpoints"]):
        from ..intel import coverage
        coverage.tick(store.now())
    # Telemetry is durable in the track store; the audit chain records operator and security actions.
    engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)
    return dict(result, received_at=received_at, created=created, live=live, flags=sorted(flags))


@router.post("/api/v1/assets/{id}/positions", response_model=PositionReceipt, status_code=201)
def record_position(id: str, point: PositionInput):
    principal = current_principal.get()
    return ingest_position(id, point, f"principal:{principal.username}" if principal else "unauthenticated")


@router.post('/api/v1/assets/{id}/positions:batch', response_model=PositionBatchResult, status_code=201)
def record_positions_batch(id: str, payload: PositionBatchInput, request: Request):
    from .field import device_for
    principal = authz.require('read')
    guard = authz.linked_guard(principal)
    if 'guard' not in principal.roles or not guard or guard['id'] != id:
        raise HTTPException(403, 'موقعیت دسته‌ای فقط برای تجهیز نگهبان ثبت‌شده است')
    device = device_for(request, principal)
    points = []
    for row in payload.records:
        if row.kind != 'position' or row.device_id != device['id']:
            raise HTTPException(422, 'رکورد موقعیت یا دستگاه صف نامعتبر است')
        offline.verify(row)
        point = offline.queued(PositionInput, row.payload)
        if parse_timestamp(point.time) != parse_timestamp(row.captured_at):
            raise HTTPException(422, 'زمان موقعیت با رکورد امضاشده یکسان نیست')
        points.append(point)
    accepted, regressed = [], []
    for row, point in zip(payload.records, points):
        accepted.append(ingest_position(id, point, f"device:{device['id']}"))
        if offline.clock_regressed(row):
            regressed.append(row.client_id)
    return dict(accepted=accepted, clock_regressed_client_ids=regressed)


@store.state_locked
def ingest_event(id: str, payload: DeviceEventInput):
    """Single SOS ingestion path for device adapters and the demo scenario."""
    asset = store.lookup("assets", id)
    if payload.type not in asset["capabilities"]:
        raise HTTPException(422, "این تجهیز قابلیت دکمه اضطراری (SOS) ندارد")
    stamp = payload.time.astimezone(timezone.utc).isoformat()
    events = store.state["device_events"]
    existing = next((e for e in events if e["asset_id"] == id and e["type"] == payload.type and e["time"] == stamp), None)
    if existing is None:
        existing = dict(id=f"EVT-{len(events) + 1:04}", asset_id=id, type=payload.type,
                        time=stamp, received_at=store.now(), alert_ids=[], incident_ids=[])
        fired = engine.evaluate(store.state, asset, stamp, store.create_incident, store.audit, event=existing)
        existing["alert_ids"] = [alert["id"] for alert in fired]
        existing["incident_ids"] = list(dict.fromkeys(alert["incident_id"] for alert in fired if alert["incident_id"]))
        events.append(existing)
        store.audit("ثبت رخداد اضطراری دستگاه", existing["id"], id)
    return dict(event=existing,
                alerts=[store.lookup("alerts", aid) for aid in existing["alert_ids"]],
                incidents=[store.lookup("incidents", iid) for iid in existing["incident_ids"]])


@router.post("/api/v1/assets/{id}/events", response_model=DeviceEventResult, status_code=201)
def record_event(id: str, payload: DeviceEventInput):
    return ingest_event(id, payload)
