"""Explicit guard safety reports and timed operator acknowledgement escalation."""
from fastapi import HTTPException

from .. import store
from ..tracks import parse_timestamp

SECURITY_ROLES = {'shift_supervisor', 'security_officer', 'security_manager', 'admin'}


def _finding(tour, event, stamp):
    from ..intel import findings
    return findings.raise_finding(
        rule_id='intel.field_' + event['type'], kind='patrol_safety',
        subject_ids=[tour['guard_id']], severity='critical',
        summary='گزارش ایمنی نگهبان نیازمند بررسی انسانی',
        mode='shadow', needs_incident=False, now_iso=stamp,
        evidence=dict(rule='گزارش صریح دستگاه میدانی؛ بدون تشخیص سمت سرور',
                      thresholds=dict(), window_from=stamp, window_to=stamp,
                      points=[], values=dict(event_id=event['id'], tour_id=tour['id'], type=event['type'])),
        sources=[event['id'], tour['id']],
    )


def _base(tour, device, kind, stamp, client_id=None):
    from ..routers.field import new_id
    return dict(id=new_id('SAFE'), tour_id=tour['id'], guard_id=tour['guard_id'], owner_sub=tour['owner_sub'],
                device_id=device['id'], zone_id=tour['zone_id'], contractor_id=tour['contractor_id'],
                type=kind, client_id=client_id, created_at=stamp, incident_id=None, operator_ack_at=None,
                operator_ack_sub=None, escalation='operator', finding_id=None, rate_flagged=rate_flagged())


def rate_flagged():
    from ..security.auth import current_scope
    scope = current_scope.get()
    return bool(scope and scope.get('state', {}).get('rate_flagged'))


def record_duress(tour, device, stamp, *, client_id=None, auth_expired=False, clock_regressed=False):
    if client_id:
        prior = next((e for e in store.field.records('field_safety_events') if e['owner_sub'] == tour['owner_sub']
                      and e.get('client_id') == client_id), None)
        if prior:
            if prior['tour_id'] != tour['id'] or prior['type'] != 'duress':
                raise HTTPException(409, 'شناسه رویداد قبلاً مصرف شده است')
            return prior
    row = _base(tour, device, 'duress', stamp, client_id)
    row['auth_expired'] = auth_expired
    row['clock_regressed'] = clock_regressed
    store.field.save('field_safety_events', row)
    store.audit('ثبت رویداد میدانی محرمانه', row['id'])
    return row


def report(tour, device, payload, stamp, *, auth_expired=False, clock_regressed=False):
    from ..tour.evidence import request_hash
    payload_hash = request_hash(payload)
    prior = next((e for e in store.field.records('field_safety_events') if e['owner_sub'] == tour['owner_sub']
                  and e.get('client_id') == payload.client_id), None)
    if prior:
        if (prior['tour_id'] != tour['id'] or prior['type'] != payload.type
                or prior.get('request_hash') != payload_hash):
            raise HTTPException(409, 'شناسه رویداد قبلاً مصرف شده است')
        return prior
    if payload.type == 'man_down' and not (payload.fall_detected or
            (payload.motionless_seconds or 0) >= store.state['settings']['field_man_down_idle_seconds']):
        raise HTTPException(422, 'رویداد عدم تحرک به آستانه تنظیم‌شده یا الگوی سقوط نیاز دارد')
    row = _base(tour, device, payload.type, stamp, payload.client_id)
    row['request_hash'] = payload_hash
    row['auth_expired'] = auth_expired
    row['clock_regressed'] = clock_regressed
    if payload.type == 'sos':
        zone = store.field.get('field_zones', tour['zone_id'])
        asset = store.lookup('assets', tour['guard_id'])
        last = next((s for s in reversed(store.field.scans()) if s['owner_sub'] == tour['owner_sub']
                     and s['lon'] is not None and s['lat'] is not None), None)
        point = {**asset, 'lon': last['lon'], 'lat': last['lat']} if last else asset
        incident = store.create_incident('اعلام خطر نگهبان', 'critical', zone['name'] if zone else tour['zone_id'],
            point, 'درخواست کمک صریح نگهبان؛ نیازمند رسید اپراتور', 'دریافت اعلام خطر از دستگاه ثبت‌شده',
            zone_id=tour['zone_id'], actor=tour['owner_sub'])
        store.attach_emergency_context(incident, 'sos')
        row['incident_id'] = incident['id']
    else:
        row['finding_id'] = _finding(tour, row, stamp)['id']
        row['motionless_seconds'] = payload.motionless_seconds
        row['fall_detected'] = payload.fall_detected
    store.field.save('field_safety_events', row)
    store.audit('دریافت اعلام خطر نگهبان' if payload.type == 'sos' else 'دریافت رویداد عدم تحرک', row['id'])
    return row


def escalation(row, now=None):
    return escalation_level(row['created_at'], bool(row.get('operator_ack_at')),
                            store.state['settings']['field_sos_escalation_seconds'], now)


def escalation_level(created_at, acknowledged, threshold, now=None):
    """Shared timed chain for unacknowledged SOS alerts and urgent messages."""
    if acknowledged:
        return 'operator'
    elapsed = (parse_timestamp(now or store.now()) - parse_timestamp(created_at)).total_seconds()
    if elapsed >= threshold * 2:
        return 'security_officer'
    if elapsed >= threshold:
        return 'shift_supervisor'
    return 'operator'


def view(row, now=None):
    return {**row, 'escalation': escalation(row, now)}


def receipt(row):
    return dict(id=row['id'], server_received_at=row['created_at'], incident_id=row.get('incident_id'),
                operator_ack_at=row.get('operator_ack_at'))


def acknowledge_incident(incident_id, principal, stamp):
    event = next((row for row in store.field.records('field_safety_events') if row.get('incident_id') == incident_id), None)
    if not event:
        raise HTTPException(404, 'اعلام خطر میدانی برای این پرونده پیدا نشد')
    return acknowledge_event(event, principal, stamp)


def acknowledge_event(event, principal, stamp):
    if event['operator_ack_at']:
        return event
    event['operator_ack_at'] = stamp
    event['operator_ack_sub'] = principal.sub
    store.field.save('field_safety_events', event)
    store.audit('رسید اپراتور برای اعلام خطر نگهبان', event['id'])
    return event


@store.state_locked
def tick(now):
    from ..intel import findings
    active_guard_ids = set()
    for tour in store.field.records('tour'):
        if tour['status'] != 'active':
            continue
        active_guard_ids.add(tour['guard_id'])
        checkins = [row for row in store.field.records('checkins') if row['tour_id'] == tour['id']]
        last = max((row['time'] for row in checkins), default=tour['started_at'])
        overdue = (parse_timestamp(now) - parse_timestamp(last)).total_seconds() >= \
            store.state['settings']['heat_profile']['checkin_minutes'] * 60
        existing = next((row for row in store.state['findings'] if row['rule_id'] == 'intel.field_checkin'
                         and row['subject_ids'] == [tour['guard_id']] and row['status'] != 'resolved'), None)
        if overdue and not existing:
            findings.raise_finding(rule_id='intel.field_checkin', kind='patrol_safety',
                subject_ids=[tour['guard_id']], severity='high', mode='shadow', needs_incident=False,
                summary='مهلت تأیید سلامت گشت پیاده سپری شد', now_iso=now,
                evidence=dict(rule='فاصله تأیید سلامت از پروفایل گرما',
                              thresholds=dict(checkin_minutes=store.state['settings']['heat_profile']['checkin_minutes']),
                              window_from=last, window_to=now, points=[], values=dict(tour_id=tour['id'])),
                sources=[tour['id'], tour['guard_id']])
        elif not overdue and existing:
            findings.resolve_finding(existing['id'], now_iso=now)
    for row in store.state['findings']:
        if (row['rule_id'] == 'intel.field_checkin' and row['status'] != 'resolved'
                and row['subject_ids'][0] not in active_guard_ids):
            findings.resolve_finding(row['id'], now_iso=now)
    for row in store.field.records('field_safety_events'):
        level = escalation(row, now)
        if row.get('escalation') != level:
            row['escalation'] = level
            store.field.save('field_safety_events', row)
            store.audit('تشدید اعلام خطر بی‌رسید', row['id'], level, actor='سامانه')
