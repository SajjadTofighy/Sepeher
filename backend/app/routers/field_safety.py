"""Authenticated field SOS, man-down reports, acknowledgement and musters."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from .. import authz, field_safety as safety, store
from ..models import (FieldSafetyAlert, FieldSafetyInput, FieldSafetyReceipt, Muster, MusterInput,
                      MusterNotice, MusterResponse, MusterResponseInput)
from .field import ERROR_RESPONSES, FieldRoute, device_for, new_id, record

router = APIRouter(route_class=FieldRoute, tags=['field-safety'], responses=ERROR_RESPONSES)


def security_principal():
    principal = authz.require('manage')
    if not set(principal.roles) & safety.SECURITY_ROLES:
        raise HTTPException(403, 'دسترسی به اعلام خطر برای نقش امنیتی است')
    return principal


def event_for(id):
    row = store.field.get('field_safety_events', id)
    if row is None:
        raise HTTPException(404, 'گزارش ایمنی پیدا نشد')
    return row


@router.post('/api/v1/tour/safety-events', response_model=FieldSafetyReceipt, status_code=201)
def report(payload: FieldSafetyInput, request: Request):
    principal = authz.require('read')
    tour = record('tour', payload.tour_id)
    if 'guard' not in principal.roles or tour['owner_sub'] != principal.sub or tour['status'] != 'active':
        raise HTTPException(403, 'گزارش ایمنی به گشت فعال خود نگهبان نیاز دارد')
    device = device_for(request, principal)
    return safety.receipt(safety.report(tour, device, payload, store.now()))


@router.get('/api/v1/tour/safety-events/{id}/receipt', response_model=FieldSafetyReceipt)
def receipt(id: str):
    principal = authz.require('read')
    row = event_for(id)
    if row['type'] == 'duress' or row['owner_sub'] != principal.sub:
        raise HTTPException(404, 'رسید پیدا نشد')
    return safety.receipt(row)


@router.get('/api/v1/tour/safety-alerts', response_model=list[FieldSafetyAlert])
def alerts():
    principal = security_principal()
    rows = [safety.view(row) for row in store.field.records('field_safety_events') if authz.visible(principal, row, own=False)]
    for row in rows:
        store.audit('مشاهده گزارش ایمنی نگهبان', row['id'])
    return rows


@router.post('/api/v1/tour/safety-alerts/{id}/ack', response_model=FieldSafetyAlert)
def acknowledge_alert(id: str):
    principal = security_principal()
    row = event_for(id)
    authz.check_scope(row, own=False)
    if row.get('incident_id'):
        raise HTTPException(409, 'رسید SOS فقط از مسیر پرونده حادثه ثبت می‌شود')
    return safety.view(safety.acknowledge_event(row, principal, store.now()))


@router.get('/api/v1/tour/safety-alerts/stream')
def alert_stream():
    principal = security_principal()
    async def generate():
        while True:
            with store.locked_state():
                rows = [safety.view(row) for row in store.field.records('field_safety_events')
                        if authz.visible(principal, row, own=False)]
                message = json.dumps([FieldSafetyAlert.model_validate(row).model_dump(mode='json') for row in rows], ensure_ascii=False)
            yield f'event: safety\ndata: {message}\n\n'
            await asyncio.sleep(3)
    return StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})


def muster_view(row):
    return {**row, 'unanswered_guard_ids': [p['guard_id'] for p in row['participants'] if p['response'] is None]}


@router.post('/api/v1/tour/musters', response_model=Muster, status_code=201)
def create_muster(payload: MusterInput):
    principal = security_principal()
    if not set(principal.roles) & {'security_officer', 'security_manager', 'admin'}:
        raise HTTPException(403, 'حضورشماری به مسئول حراست نیاز دارد')
    zone = store.field.get('field_zones', payload.zone_id)
    if not zone:
        raise HTTPException(404, 'محوطه پیدا نشد')
    contractor = payload.contractor_id or principal.contractor_id
    if not contractor:
        raise HTTPException(422, 'پیمانکار حضورشماری باید تعیین شود')
    authz.check_scope({'zone_id': payload.zone_id, 'contractor_id': contractor}, own=False)
    participants = []
    seen = set()
    for tour in store.field.records('tour'):
        if (tour['status'] == 'active' and tour['zone_id'] == payload.zone_id
                and tour['contractor_id'] == contractor and tour['owner_sub'] not in seen):
            seen.add(tour['owner_sub'])
            participants.append(dict(guard_id=tour['guard_id'], owner_sub=tour['owner_sub'],
                                     response=None, responded_at=None))
    row = dict(id=new_id('MUSTER'), zone_id=payload.zone_id, contractor_id=contractor,
               reason=payload.reason, created_at=store.now(), actor_sub=principal.sub, participants=participants)
    store.field.save('musters', row)
    store.audit('آغاز حضورشماری اضطراری', row['id'])
    return muster_view(row)


@router.get('/api/v1/tour/musters', response_model=list[Muster | MusterNotice])
def musters():
    principal = authz.require('read')
    rows = muster_rows(principal)
    if 'guard' not in principal.roles:
        for row in rows:
            store.audit('مشاهده فهرست حضورشماری', row['id'])
    return rows


def muster_rows(principal):
    rows = []
    for row in store.field.records('musters'):
        if 'guard' in principal.roles:
            participant = next((p for p in row['participants'] if p['owner_sub'] == principal.sub), None)
            if participant:
                rows.append(dict(id=row['id'], zone_id=row['zone_id'], reason=row['reason'],
                                 created_at=row['created_at'], response=participant['response']))
        elif authz.visible(principal, row, own=False):
            rows.append(muster_view(row))
    return rows


@router.get('/api/v1/tour/musters/stream')
def muster_stream():
    principal = authz.require('read')
    async def generate():
        while True:
            with store.locked_state():
                message = json.dumps(muster_rows(principal), ensure_ascii=False)
            yield f'event: muster\ndata: {message}\n\n'
            await asyncio.sleep(3)
    return StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})


@router.post('/api/v1/tour/musters/{id}/respond', response_model=MusterResponse)
def respond(id: str, payload: MusterResponseInput):
    principal = authz.require('read')
    if 'guard' not in principal.roles:
        raise HTTPException(403, 'پاسخ حضورشماری فقط برای نگهبان است')
    row = store.field.get('musters', id)
    if not row:
        raise HTTPException(404, 'حضورشماری پیدا نشد')
    participant = next((p for p in row['participants'] if p['owner_sub'] == principal.sub), None)
    if not participant:
        raise HTTPException(404, 'اعلان حضورشماری برای شما نیست')
    if participant['response'] is not None:
        if participant['response'] == payload.response:
            return dict(muster_id=id, response=participant['response'], responded_at=participant['responded_at'])
        raise HTTPException(409, 'پاسخ حضورشماری قبلاً ثبت شده است')
    participant.update(response=payload.response, responded_at=store.now())
    store.field.save('musters', row)
    store.audit('پاسخ حضورشماری نگهبان', id, payload.response)
    return dict(muster_id=id, response=participant['response'], responded_at=participant['responded_at'])
