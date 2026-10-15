"""GPS ingestion for local device adapters; history survives server restarts."""
from datetime import timezone
from fastapi import APIRouter, HTTPException, Request
from .. import engine, store
from ..security import authz
from ..field import offline
from ..models import DeviceEventInput, DeviceEventResult, TrackPoint, PositionInput, PositionBatchInput, PositionBatchResult
from ..store import StateRoute
from ..tracks import TrackConflict
from ..tracks import parse_timestamp

router = APIRouter(route_class=StateRoute, tags=["positions"])


@router.post("/api/v1/assets/{id}/positions", response_model=TrackPoint, status_code=201)
def record_position(id: str, point: PositionInput):
    asset = store.lookup("assets", id)
    try:
        result = store.tracks.append(id, point.lon, point.lat, point.time, point.speed)
    except TrackConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    store.refresh_track(asset)
    if any(cp.get("target_id") for m in store.state["missions"] for cp in m["checkpoints"]):
        from ..intel import coverage
        coverage.tick(store.now())
    engine.evaluate(store.state, asset, store.now(), store.create_incident, store.audit)
    store.audit("ثبت موقعیت و مسیر", id)
    return result


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
        accepted.append(record_position(id, point))
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
