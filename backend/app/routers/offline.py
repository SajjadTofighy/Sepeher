"""Signed offline field queue ingestion; emergency proof survives expired OIDC tokens."""
from fastapi import APIRouter, HTTPException, Request

from .. import store
from ..security import auth, authz
from ..field import media as media_logic, offline, safety as field_safety
from ..models import (FieldReport, FieldReportInput, FieldSafetyInput, FieldSafetyReceipt, SignedQueueRecord,
                      StationVisit, StationVisitInput)
from ..tracks import parse_timestamp
from . import field_comms, stations
from .field import ERROR_RESPONSES, device_for

router = APIRouter(route_class=store.StateRoute, tags=['offline'], responses=ERROR_RESPONSES)


def guard_device(record, request):
    principal = authz.require('read')
    if 'guard' not in principal.roles:
        raise HTTPException(403, 'صف میدانی به هویت نگهبان نیاز دارد')
    device = device_for(request, principal)
    if device['id'] != record.device_id:
        raise HTTPException(403, 'شناسه دستگاه صف با نشست سازگار نیست')
    offline.verify(record)
    return principal, device


@router.post('/api/v1/tour/offline/scans', response_model=StationVisit, status_code=201)
def submit_scan(record: SignedQueueRecord, request: Request):
    if record.kind != 'scan':
        raise HTTPException(422, 'نوع رکورد اسکن لازم است')
    guard_device(record, request)
    with store.field.transaction():
        payload = offline.queued(StationVisitInput, record.payload, exclude=('station_id',))
        if (payload.client_id != record.client_id or payload.device_time is None
                or parse_timestamp(payload.device_time) != parse_timestamp(record.captured_at)
                or (parse_timestamp(payload.previous_device_time) if payload.previous_device_time else None)
                   != (parse_timestamp(record.previous_device_time) if record.previous_device_time else None)):
            raise HTTPException(422, 'زمان و شناسه رکورد صف با اسکن سازگار نیست')
        station_id = record.payload.get('station_id')
        if not isinstance(station_id, str) or not station_id:
            raise HTTPException(422, 'شناسه ایستگاه صف لازم است')
        return stations.arrival(station_id, payload, request)


@router.post('/api/v1/tour/offline/reports', response_model=FieldReport, status_code=201)
def submit_report(record: SignedQueueRecord, request: Request):
    if record.kind != 'report':
        raise HTTPException(422, 'نوع رکورد گزارش لازم است')
    principal, device = guard_device(record, request)
    with store.field.transaction():
        payload = offline.queued(FieldReportInput, record.payload)
        if payload.client_id != record.client_id:
            raise HTTPException(422, 'شناسه رکورد صف با گزارش سازگار نیست')
        tour = store.field.get('tour', payload.tour_id)
        if not tour or tour['owner_sub'] != principal.sub:
            raise HTTPException(403, 'گشت به دستگاه ثبت‌شده تعلق ندارد')
        stamp = store.now()
        row = field_comms.create_report(tour, device, payload, stamp, clock_regressed=offline.clock_regressed(record),
                                        offline_too_long=offline.offline_too_long(record, stamp))
        return media_logic.report_view(row)


@router.post('/api/v1/tour/offline/emergency', response_model=FieldSafetyReceipt, status_code=201)
def submit_emergency(record: SignedQueueRecord, request: Request):
    if record.kind not in ('sos', 'duress', 'man_down'):
        raise HTTPException(422, 'نوع رکورد اضطراری نامعتبر است')
    device = offline.verify(record)
    with store.field.transaction():
        tour_id = record.payload.get('tour_id')
        tour = store.field.get('tour', tour_id) if isinstance(tour_id, str) else None
        if not tour or tour['owner_sub'] != device['owner_sub']:
            raise HTTPException(403, 'گشت به دستگاه ثبت‌شده تعلق ندارد')
        authorization = request.headers.get('Authorization', '')
        authenticated = False
        if authorization.lower().startswith('bearer '):
            try:
                principal = auth.authenticate(authorization)
                authenticated = principal.sub == device['owner_sub'] and 'guard' in principal.roles
            except HTTPException:
                pass
        stamp = store.now()
        regressed = offline.clock_regressed(record)
        if record.kind == 'duress':
            if set(record.payload) != {'tour_id'}:
                raise HTTPException(422, 'بدنه رمز اضطرار معتبر نیست')
            event = field_safety.record_duress(tour, device, stamp, client_id=record.client_id,
                                               auth_expired=not authenticated, clock_regressed=regressed)
            # A duress receipt must never expose that the silent report was created.
            return dict(id=record.client_id, server_received_at=stamp, incident_id=None, operator_ack_at=None)
        payload = offline.queued(FieldSafetyInput, record.payload)
        if payload.type != record.kind or payload.client_id != record.client_id:
            raise HTTPException(422, 'نوع و شناسه اعلام خطر با رکورد صف سازگار نیست')
        event = field_safety.report(tour, device, payload, stamp,
                                    auth_expired=not authenticated, clock_regressed=regressed)
        return field_safety.receipt(event)
