"""Phase-two walking shifts, schedule approval, queue and emergency controls."""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from ..core import engine, store
from ..security import authz
from ..tour import schedule as tour_schedule
from ..core.models import (DailyTourView, EmergencyMode, EmergencyModeInput, ScheduledTour,
    ShiftHandover, ShiftHandoverInput, ShiftPattern, ShiftPatternInput,
    TourSchedule, TourScheduleInput)
from .field import ERROR_RESPONSES, FieldRoute, new_id, record

router = APIRouter(route_class=FieldRoute, tags=['tour-schedules'], responses=ERROR_RESPONSES)


def visible(kind, *, own=False):
    principal = authz.require('read')
    return [row for row in store.field.records(kind) if authz.visible(principal, row, own=own)]


@router.get('/api/v1/tour/shift-patterns', response_model=list[ShiftPattern])
def patterns():
    authz.require('read')
    return [tour_schedule.default_pattern(), *store.field.records('shift_patterns')]


@router.post('/api/v1/tour/shift-patterns', response_model=ShiftPattern, status_code=201)
def create_pattern(payload: ShiftPatternInput):
    authz.require('manage')
    row = dict(**payload.model_dump(mode='json'), id=new_id('PATTERN'), created_at=store.now())
    store.field.save('shift_patterns', row)
    store.audit('تعریف الگوی شیفت گشت', row['id'])
    return row


@router.get('/api/v1/tour/schedules', response_model=list[TourSchedule])
def schedules():
    return visible('tour_schedules')


@router.post('/api/v1/tour/schedules', response_model=TourSchedule, status_code=201)
def create_schedule(payload: TourScheduleInput):
    authz.require('manage')
    route = record('routes', payload.route_id)
    if not route['station_ids']:
        raise HTTPException(409, 'مسیر برای زمان‌بندی باید ایستگاه داشته باشد')
    if not tour_schedule.pattern_record(payload.pattern_id):
        raise HTTPException(404, 'الگوی شیفت پیدا نشد')
    if payload.last_date < payload.first_date or (payload.last_date - payload.first_date).days + 1 > store.state['settings']['tour_schedule_max_days']:
        raise HTTPException(422, 'بازه برنامه از سقف تنظیم‌شده بیشتر است')
    row = dict(**payload.model_dump(mode='json'), id=new_id('SCHEDULE'), zone_id=route['zone_id'],
               contractor_id=route['contractor_id'], status='draft', created_at=store.now(), approved_at=None)
    store.field.save('tour_schedules', row)
    store.audit('پیش‌نویس برنامه گشت', row['id'])
    return row


@router.post('/api/v1/tour/schedules/{id}/approve', response_model=TourSchedule)
def approve(id: str):
    authz.require('manage')
    row = record('tour_schedules', id)
    if row['status'] != 'draft':
        raise HTTPException(409, 'برنامه پیش‌تر تأیید شده است')
    row.update(status='approved', approved_at=store.now())
    store.field.save('tour_schedules', row)
    for day in (tour_schedule.local_day(store.now()), tour_schedule.local_day(store.now()) + timedelta(days=1)):
        tour_schedule.materialize(row, day)
    store.audit('تأیید برنامه گشت بدون اعزام', id)
    return row


@router.get('/api/v1/tour/queue', response_model=list[ScheduledTour])
def queue(service_date: date | None = None, contractor_id: str | None = None):
    principal = authz.require('read')
    today = tour_schedule.local_day(store.now())
    day = service_date or today
    if day not in (today, today + timedelta(days=1)):
        raise HTTPException(422, 'صف فقط برای امروز و فردا قابل درخواست است')
    for schedule in visible('tour_schedules'):
        if schedule['status'] == 'approved':
            tour_schedule.materialize(schedule, day)
    rows = [row for row in visible('scheduled_tours', own=True) if row['service_date'] == day.isoformat()
            and (contractor_id is None or row['contractor_id'] == contractor_id)]
    return tour_schedule.queue_rows(principal, rows)


@router.get('/api/v1/tour/daily', response_model=DailyTourView)
def daily(service_date: date, contractor_id: str | None = None):
    principal = authz.require('manage')
    for schedule in visible('tour_schedules'):
        if schedule['status'] == 'approved':
            tour_schedule.materialize(schedule, service_date)
    walking = [r for r in visible('scheduled_tours') if r['service_date'] == service_date.isoformat()
               and (contractor_id is None or r['contractor_id'] == contractor_id)]
    # Existing vehicle plans retain their own model and scope; no synthetic merge.
    assets = {asset['id']: asset for asset in store.state['assets']}
    vehicles = [p for p in store.state.get('patrol_plans', [])
                if p['shift_start'][:10] <= service_date.isoformat() <= p['shift_end'][:10]
                and ('admin' in principal.roles or all(assets.get(patrol['asset_id'], {}).get('zone_id') in principal.zone_ids
                                                       for patrol in p['patrols']))
                and (contractor_id is None or any(assets.get(patrol['asset_id'], {}).get('contractor_id') == contractor_id
                                                   for patrol in p['patrols']))]
    return dict(date=service_date, walking=walking, vehicles=vehicles)


@router.get('/api/v1/tour/handovers', response_model=list[ShiftHandover])
def handovers():
    principal = authz.require('read')
    rows = visible('shift_handovers')
    if 'guard' in principal.roles:
        guard = authz.linked_guard(principal)
        rows = [row for row in rows if row['incoming_guard_id'] == guard['id']]
    return rows


@router.post('/api/v1/tour/handovers', response_model=ShiftHandover, status_code=201)
def create_handover(payload: ShiftHandoverInput):
    authz.require('manage')
    authz.check_scope(payload.model_dump(), own=False)
    outgoing, incoming = record('guards', payload.outgoing_guard_id), record('guards', payload.incoming_guard_id)
    if outgoing['id'] == incoming['id'] or any((g['zone_id'], g['contractor_id']) != (payload.zone_id, payload.contractor_id) for g in (outgoing, incoming)):
        raise HTTPException(422, 'نگهبانان تحویل باید متفاوت و در حوزه یکسان باشند')
    row = dict(**payload.model_dump(), id=new_id('HANDOVER'), acknowledged_at=None, acknowledged_by=None, created_at=store.now())
    store.field.save('shift_handovers', row)
    store.audit('ثبت تحویل شیفت', row['id'])
    return row


@router.post('/api/v1/tour/handovers/{id}/ack', response_model=ShiftHandover)
def acknowledge(id: str):
    principal = authz.require('read')
    row = store.field.get('shift_handovers', id)
    if not row:
        raise HTTPException(404, 'تحویل شیفت پیدا نشد')
    authz.check_scope(row, own=False)
    incoming = record('guards', row['incoming_guard_id'])
    if row['acknowledged_at'] or principal.sub != incoming['keycloak_sub']:
        raise HTTPException(403, 'فقط نگهبان ورودی می‌تواند تحویل را تأیید کند')
    row.update(acknowledged_at=store.now(), acknowledged_by=principal.sub)
    store.field.save('shift_handovers', row)
    store.audit('تأیید تحویل شیفت', id)
    return row


@router.get('/api/v1/tour/emergency/{zone_id}', response_model=EmergencyMode | None)
def emergency(zone_id: str):
    authz.require('read')
    if store.field.get('field_zones', zone_id) is None:
        raise HTTPException(404, 'محوطه پیدا نشد')
    authz.check_scope({'zone_id': zone_id, 'contractor_id': authz.require('read').contractor_id}, own=False)
    return store.field.get('emergency_modes', zone_id)


@router.put('/api/v1/tour/emergency/{zone_id}', response_model=EmergencyMode)
def set_emergency(zone_id: str, payload: EmergencyModeInput):
    principal = authz.require('manage')
    if not set(principal.roles) & {'security_officer', 'security_manager', 'admin'}:
        raise HTTPException(403, 'فعال‌سازی اضطرار به مسئول حراست نیاز دارد')
    if store.field.get('field_zones', zone_id) is None:
        raise HTTPException(404, 'محوطه پیدا نشد')
    authz.check_scope({'zone_id': zone_id, 'contractor_id': principal.contractor_id}, own=False)
    row = dict(zone_id=zone_id, active=payload.active, reason=payload.reason, changed_at=store.now(), actor_sub=principal.sub)
    store.field.save('emergency_modes', {'id': zone_id, **row})
    if payload.active:
        for scheduled in store.field.records('scheduled_tours'):
            if scheduled['zone_id'] == zone_id and scheduled['status'] == 'queued':
                scheduled.update(status='excused', warnings=[*scheduled['warnings'], 'وضعیت اضطرار'])
                store.field.save('scheduled_tours', scheduled)
        for mission in store.state.get('missions', []):
            if any(cp.get('target_id') and not cp.get('visited') and cp.get('lon') is not None and cp.get('lat') is not None
                   and engine.point_in_polygon(cp['lon'], cp['lat'], store.field.get('field_zones', zone_id)['points'])
                   for cp in mission['checkpoints']):
                for cp in mission['checkpoints']:
                    if (cp.get('target_id') and not cp.get('visited') and cp.get('lon') is not None and cp.get('lat') is not None
                            and engine.point_in_polygon(cp['lon'], cp['lat'], store.field.get('field_zones', zone_id)['points'])):
                        cp['excused_reason'] = 'وضعیت اضطرار'
    store.audit('فعال‌سازی وضعیت اضطرار' if payload.active else 'پایان وضعیت اضطرار', zone_id, payload.reason)
    return row
