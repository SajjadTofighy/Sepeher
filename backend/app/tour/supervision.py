"""Exception-first supervision of walking patrols: deterministic, scoped, read-only.

Every outcome is derived from durable field records. Suspended (emergency or
excused) checks are reported separately and never counted as missed. Nothing
here creates incidents, dispatches or messages anyone.
"""
from datetime import timedelta

from ..security import authz
from .. import store
from ..field.safety import SECURITY_ROLES
from ..field.media import jalali_stamp, message_acknowledged
from ..tracks import parse_timestamp

VERIFIED_TRUST = ('high', 'medium')
INTEGRITY_PREFIX = 'intel.integrity.'
SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}


def lookback(now):
    return (parse_timestamp(now) - timedelta(hours=store.state['settings']['integrity_window_hours'])).isoformat()


def in_window(value, window_from, window_to):
    stamp = parse_timestamp(value)
    return parse_timestamp(window_from) <= stamp < parse_timestamp(window_to)


def emergency_zones():
    """Active emergencies by zone with their start time."""
    return {row['id']: row['changed_at'] for row in store.field.records('emergency_modes') if row.get('active')}


def suspended_by_emergency(scheduled, zones):
    # Only checks whose window was still open when the emergency began are suspended;
    # an emergency never retroactively erases an already missed station.
    started = zones.get(scheduled['zone_id'])
    return started is not None and parse_timestamp(started) < parse_timestamp(scheduled['ends_at'])


def scan_rows():
    from ..routers.stations import scan_view
    return [scan_view(row) for row in store.field.scans()]


def checks(principal, window_from, window_to, now):
    """One row per scheduled station check due in the window, with its outcome."""
    visits = {}
    for visit in store.field.records('station_visits'):
        if visit['status'] == 'completed':
            visits.setdefault((visit['tour_id'], visit['station_id']), visit)
    suspended_zones = emergency_zones()
    rows = []
    for scheduled in store.field.records('scheduled_tours'):
        if not authz.visible(principal, scheduled, own=False) or not in_window(scheduled['due_at'], window_from, window_to):
            continue
        for station_id in scheduled['station_ids']:
            visit = visits.get((scheduled.get('tour_id'), station_id)) if scheduled.get('tour_id') else None
            if visit:
                outcome = 'verified' if visit.get('trust_level') in VERIFIED_TRUST else 'visited_unverified'
            elif scheduled['status'] == 'excused' or suspended_by_emergency(scheduled, suspended_zones):
                outcome = 'suspended'
            elif parse_timestamp(now) >= parse_timestamp(scheduled['ends_at']):
                outcome = 'missed'
            else:
                outcome = 'pending'
            rows.append(dict(scheduled_tour_id=scheduled['id'], station_id=station_id, guard_id=scheduled['guard_id'],
                             zone_id=scheduled['zone_id'], contractor_id=scheduled['contractor_id'],
                             due_at=scheduled['due_at'], ends_at=scheduled['ends_at'], outcome=outcome,
                             visit_id=visit['id'] if visit else None,
                             trust_level=visit.get('trust_level') if visit else None,
                             suspension_reason=next(iter(scheduled.get('warnings', [])[-1:]), 'وضعیت اضطرار')))
    return rows


def totals(rows):
    count = lambda *outcomes: sum(r['outcome'] in outcomes for r in rows)
    planned = len(rows) - count('suspended')
    verified = count('verified')
    return dict(planned=planned, visited=count('verified', 'visited_unverified'), verified=verified,
                verified_percent=round(verified * 100 / planned, 1) if planned else None,
                missed=count('missed'), pending=count('pending'), suspended=count('suspended'))


def station_status(principal):
    latest = {}
    for scan in scan_rows():
        if scan['status'] != 'rejected':
            latest[scan['station_id']] = scan
    result = []
    for station in store.field.records('stations'):
        if not authz.visible(principal, station, own=False):
            continue
        scan = latest.get(station['id'])
        status = 'never' if scan is None else 'ok' if (
            scan['status'] == 'accepted' and scan['trust_level'] in VERIFIED_TRUST) else 'unverified'
        result.append(dict(station_id=station['id'], name=station.get('name', station['id']), status=status,
                           zone_id=station['zone_id'], contractor_id=station['contractor_id'],
                           last_scan_id=scan['id'] if scan else None,
                           last_trust=scan['trust_level'] if scan else None,
                           last_scan_at=scan['received_at'] if scan else None,
                           tag_mode=station.get('tag_mode', 'code')))
    return result


def _item(kind, severity, row, title, detail, since, sources, **extra):
    return dict(id=f'{kind}:{sources[0]}', kind=kind, severity=severity, zone_id=row['zone_id'],
                contractor_id=row['contractor_id'], title=title, detail=detail, since=since,
                source_ids=sources, guard_id=extra.get('guard_id'), station_id=extra.get('station_id'))


def exceptions(principal, now):
    """Live exception list for supervisors; duress only reaches security roles."""
    window_from = lookback(now)
    items = []
    for row in checks(principal, window_from, now, now):
        if row['outcome'] == 'missed':
            items.append(_item('station_missed', 'high', row, 'ایستگاه ازدست‌رفته',
                               f"ایستگاه {row['station_id']} تا پایان پنجره {jalali_stamp(row['ends_at'])} بازدید نشد",
                               row['ends_at'], [row['scheduled_tour_id'], row['station_id']],
                               guard_id=row['guard_id'], station_id=row['station_id']))
        elif row['outcome'] == 'pending' and parse_timestamp(now) >= parse_timestamp(row['due_at']):
            items.append(_item('station_overdue', 'medium', row, 'ایستگاه سررسیدگذشته',
                               f"موعد ایستگاه {row['station_id']} گذشته و پنجره تا {jalali_stamp(row['ends_at'])} باز است",
                               row['due_at'], [row['scheduled_tour_id'], row['station_id']],
                               guard_id=row['guard_id'], station_id=row['station_id']))
    tours = {t['id']: t for t in store.field.records('tour')}
    for scan in scan_rows():
        if not authz.visible(principal, scan, own=False) or not in_window(scan['received_at'], window_from, now):
            continue
        guard_id = tours.get(scan['tour_id'], {}).get('guard_id')
        if scan['status'] == 'pending_review':
            items.append(_item('scan_pending_review', 'medium', scan, 'اسکن در انتظار بازبینی',
                               f"اسکن {scan['evidence']['tag']} ایستگاه {scan['station_id']} تأیید سرپرست می‌خواهد",
                               scan['received_at'], [scan['id']], guard_id=guard_id, station_id=scan['station_id']))
        elif scan['status'] == 'accepted' and scan['trust_level'] == 'low':
            items.append(_item('scan_low_trust', 'medium', scan, 'اسکن کم‌اعتماد',
                               '، '.join(f'{k}={v}' for k, v in scan['evidence'].items()),
                               scan['received_at'], [scan['id']], guard_id=guard_id, station_id=scan['station_id']))
    security = bool(set(principal.roles) & SECURITY_ROLES) or principal.mode == 'demo'
    kinds = {'sos': ('alarm_unacked', 'اعلام خطر بی‌رسید'), 'man_down': ('man_down_unacked', 'عدم تحرک بی‌رسید'),
             'duress': ('duress_unacked', 'رمز اضطرار بی‌رسید')}
    for event in store.field.records('field_safety_events'):
        if event.get('operator_ack_at') or not authz.visible(principal, event, own=False):
            continue
        if event['type'] == 'duress' and not security:
            continue
        kind, title = kinds[event['type']]
        items.append(_item(kind, 'critical', event, title, f"گشت {event['tour_id']}؛ تشدید تا رسید اپراتور",
                           event['created_at'], [event['id']], guard_id=event['guard_id']))
    silence = timedelta(minutes=store.state['settings']['exception_device_silence_minutes'])
    devices = store.field.devices()
    for tour in tours.values():
        if tour['status'] != 'active' or not authz.visible(principal, tour, own=False):
            continue
        seen = max((d['last_seen'] for d in devices if d['owner_sub'] == tour['owner_sub']
                    and d['status'] == 'active' and d['last_seen']), default=tour['started_at'], key=parse_timestamp)
        if parse_timestamp(now) - parse_timestamp(seen) >= silence:
            items.append(_item('device_silent', 'high', tour, 'دستگاه بی‌ارتباط در شیفت',
                               f'آخرین ارتباط دستگاه {jalali_stamp(seen)}', seen, [tour['id']], guard_id=tour['guard_id']))
    for muster in store.field.records('musters'):
        unanswered = [p['guard_id'] for p in muster['participants'] if p['response'] is None]
        if unanswered and authz.visible(principal, muster, own=False):
            items.append(_item('muster_open', 'high', muster, 'حضورشماری باز',
                               'بی‌پاسخ: ' + '، '.join(unanswered), muster['created_at'], [muster['id']]))
    for message in store.field.records('messages'):
        if (message['priority'] == 'urgent' and message['direction'] != 'to_center'
                and not message_acknowledged(message) and authz.visible(principal, message, own=False)):
            items.append(_item('message_urgent_unacked', 'medium', message, 'پیام فوری بی‌رسید', message['text'][:120],
                               message['created_at'], [message['id']], guard_id=message.get('guard_id')))
    for finding in store.state['findings']:
        values = finding['evidence']['values']
        if (finding['rule_id'].startswith(INTEGRITY_PREFIX) and finding['status'] != 'resolved'
                and authz.visible(principal, values, own=False)):
            items.append(_item('integrity', finding['severity'], values, finding['summary'],
                               f"{finding['id']} · {finding['mode']} · {finding['evidence']['rule']}",
                               finding['created_at'], [finding['id'], *finding['sources']],
                               guard_id=values.get('guard_id'), station_id=values.get('station_id')))
    items.sort(key=lambda i: (SEVERITY_ORDER[i['severity']], i['since']))
    return items


def suspended(principal, now):
    zones = emergency_zones()
    rows = []
    for scheduled in store.field.records('scheduled_tours'):
        if (authz.visible(principal, scheduled, own=False) and in_window(scheduled['due_at'], lookback(now), now)
                and (scheduled['status'] == 'excused' or (scheduled['status'] == 'queued' and suspended_by_emergency(scheduled, zones)))):
            rows.append(dict(scheduled_tour_id=scheduled['id'], guard_id=scheduled['guard_id'],
                             zone_id=scheduled['zone_id'], contractor_id=scheduled['contractor_id'],
                             due_at=scheduled['due_at'], ends_at=scheduled['ends_at'],
                             station_count=len(scheduled['station_ids']), reason='وضعیت اضطرار'))
    return rows
