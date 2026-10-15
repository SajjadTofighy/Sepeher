"""Phase six: exception board, station verification status and patrol reports."""
import csv
from datetime import timedelta
import io

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime
from starlette.responses import Response

from .. import authz, store, supervision
from ..field_media import jalali_stamp
from ..models import (DeviceCapabilityInput, DeviceCapabilityReport, ExceptionBoard, GuardDetailReport, PaperScanInput,
                      PatrolReport, PilotMetrics, ScanRecord, StationStatus)
from ..tracks import parse_timestamp
from .field import ERROR_RESPONSES, FieldRoute, device_for, new_id, record

router = APIRouter(route_class=FieldRoute, tags=['supervision'], responses=ERROR_RESPONSES)
CSV_RESPONSE = {200: {'content': {'text/csv': {'schema': {'type': 'string'}}}}}


def period(window_from, window_to):
    now = store.now()
    end = window_to.isoformat() if window_to else now
    start = window_from.isoformat() if window_from else (parse_timestamp(end) - timedelta(hours=24)).isoformat()
    if parse_timestamp(start) >= parse_timestamp(end):
        raise HTTPException(422, 'شروع بازه باید پیش از پایان آن باشد')
    if parse_timestamp(end) - parse_timestamp(start) > timedelta(days=93):
        raise HTTPException(422, 'بازه گزارش حداکثر ۹۳ روز است')
    return dict(window_from=start, window_to=end, from_jalali=jalali_stamp(start), to_jalali=jalali_stamp(end))


def counts(items):
    result = {}
    for item in items:
        result[item['kind']] = result.get(item['kind'], 0) + 1
    return result


@router.get('/api/v1/tour/exceptions', response_model=ExceptionBoard)
def exception_board():
    principal = authz.require('manage')
    now = store.now()
    items = supervision.exceptions(principal, now)
    store.audit('مشاهده تابلوی استثنای گشت', 'EXCEPTIONS', str(len(items)))
    return dict(classification_label=store.state['settings']['classification_label'], generated_at=now,
                generated_at_jalali=jalali_stamp(now), items=items, counts=counts(items),
                suspended=supervision.suspended(principal, now),
                emergency_zone_ids=sorted(z for z in supervision.emergency_zones()
                                          if authz.visible(principal, {'zone_id': z, 'contractor_id': principal.contractor_id}, own=False)),
                stations=supervision.station_status(principal))


@router.get('/api/v1/tour/station-status', response_model=list[StationStatus])
def station_status():
    return supervision.station_status(authz.require('manage'))


def build_report(principal, window, audit_detail):
    now = store.now()
    rows = supervision.checks(principal, window['window_from'], window['window_to'], now)
    groups = {}
    for row in rows:
        groups.setdefault((row['contractor_id'], row['zone_id']), []).append(row)
    trust = dict(high=0, medium=0, low=0, manual=0, pending_review=0, weak_tag=0, rejected_replay=0)
    for scan in supervision.scan_rows():
        if not authz.visible(principal, scan, own=False) or not supervision.in_window(
                scan['received_at'], window['window_from'], window['window_to']):
            continue
        if scan['status'] == 'rejected':
            trust['rejected_replay'] += scan.get('reason') == 'tag_replay'
            continue
        trust[scan['trust_level']] += 1
        trust['manual'] += scan['evidence']['tag'] == 'manual'
        trust['pending_review'] += scan['status'] == 'pending_review'
        trust['weak_tag'] += scan['evidence']['tag'] == 'counter_ok'
    integrity = {}
    for finding in store.state['findings']:
        if (finding['rule_id'].startswith(supervision.INTEGRITY_PREFIX)
                and supervision.in_window(finding['created_at'], window['window_from'], window['window_to'])
                and authz.visible(principal, finding['evidence']['values'], own=False)):
            integrity[finding['rule_id']] = integrity.get(finding['rule_id'], 0) + 1
    emergency = [dict(zone_id=row['id'], active=row['active'], reason=row['reason'], changed_at=row['changed_at'])
                 for row in store.field.records('emergency_modes')
                 if authz.visible(principal, {'zone_id': row['id'], 'contractor_id': principal.contractor_id}, own=False)]
    entry = store.audit('خروجی گزارش گشت نگهبانی', 'PATROL-REPORT', audit_detail)
    return dict(classification_label=store.state['settings']['classification_label'], generated_at=now,
                generated_at_jalali=jalali_stamp(now), viewer=principal.username, period=window,
                totals=supervision.totals(rows),
                trust=trust,
                # Contractor and post aggregates only: no individual ranking.
                contractors=[dict(contractor_id=c, zone_id=z, **supervision.totals(items))
                             for (c, z), items in sorted(groups.items())],
                emergency=emergency, integrity=integrity,
                exceptions=counts(supervision.exceptions(principal, now)),
                audit_chain=dict(valid=store.field.verify_audit(), count=len(store.field.audits()),
                                 scope='persistent SQLite chain; not WORM storage'),
                audit_id=entry['id'])


def csv_report(report):
    out = io.StringIO()
    writer = csv.writer(out)
    label = report['classification_label']
    writer.writerow(['طبقه‌بندی', label])
    writer.writerow(['گزارش', 'گزارش گشت نگهبانی'])
    writer.writerow(['بازه', report['period']['from_jalali'], report['period']['to_jalali']])
    writer.writerow(['تولید', report['generated_at_jalali'], 'بیننده', report['viewer'], 'ممیزی', report['audit_id']])
    writer.writerow([])
    writer.writerow(['بخش', 'شاخص', 'مقدار'])
    for key, value in report['totals'].items():
        writer.writerow(['پایبندی', key, '' if value is None else value])
    for key, value in report['trust'].items():
        writer.writerow(['اعتماد', key, value])
    for key, value in report['integrity'].items():
        writer.writerow(['یکپارچگی', key, value])
    for key, value in report['exceptions'].items():
        writer.writerow(['استثنا', key, value])
    writer.writerow(['زنجیره ممیزی', 'valid', report['audit_chain']['valid']])
    writer.writerow(['زنجیره ممیزی', 'count', report['audit_chain']['count']])
    writer.writerow([])
    writer.writerow(['پیمانکار', 'پست/محوطه', 'برنامه‌ریزی‌شده', 'انجام‌شده', 'تأییدشده', 'درصد تأیید', 'ازدست‌رفته', 'باز', 'تعلیق اضطرار'])
    for line in report['contractors']:
        writer.writerow([line['contractor_id'], line['zone_id'], line['planned'], line['visited'], line['verified'],
                         '' if line['verified_percent'] is None else line['verified_percent'],
                         line['missed'], line['pending'], line['suspended']])
    writer.writerow([])
    writer.writerow(['محوطه اضطرار', 'فعال', 'دلیل', 'زمان تغییر'])
    for line in report['emergency']:
        writer.writerow([line['zone_id'], line['active'], line['reason'], jalali_stamp(line['changed_at'])])
    writer.writerow([])
    writer.writerow(['طبقه‌بندی', label])
    return '﻿' + out.getvalue()


@router.get('/api/v1/reports/tour/summary', response_model=PatrolReport, responses=CSV_RESPONSE)
def patrol_report(window_from: AwareDatetime | None = None, window_to: AwareDatetime | None = None,
                  format: str = Query(default='json', pattern='^(json|csv)$')):
    principal = authz.require('export')
    if 'guard' in principal.roles:
        authz.fail('permission_denied', 403)
    report = build_report(principal, period(window_from, window_to), format)
    if format == 'json':
        return report
    return Response(csv_report(report), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="sepehr-patrol-report.csv"',
                             'Cache-Control': 'no-store'})


@router.get('/api/v1/reports/tour/guards/{guard_id}', response_model=GuardDetailReport)
def guard_detail(guard_id: str, window_from: AwareDatetime | None = None, window_to: AwareDatetime | None = None):
    principal = authz.require('read')
    if not set(principal.roles) & {'shift_supervisor', 'auditor'}:
        raise HTTPException(403, dict(code='individual_view_denied',
                                      message='نمای فردی فقط برای سرپرست شیفت همان محوطه و ممیز است'))
    guard = record('guards', guard_id)
    if not guard.get('zone_id') or not authz.visible(principal, guard, own=False):
        authz.fail('scope_denied', 403)
    window = period(window_from, window_to)
    rows = [r for r in supervision.checks(principal, window['window_from'], window['window_to'], store.now())
            if r['guard_id'] == guard_id]
    tours = {t['id'] for t in store.field.records('tour') if t['guard_id'] == guard_id}
    scans = [s for s in supervision.scan_rows() if s['tour_id'] in tours
             and supervision.in_window(s['received_at'], window['window_from'], window['window_to'])]
    entry = store.audit('مشاهده نمای فردی نگهبان', guard_id, f"{window['window_from']}–{window['window_to']}")
    return dict(classification_label=store.state['settings']['classification_label'], generated_at=store.now(),
                viewer=principal.username, guard_id=guard_id, guard_name=guard.get('name', guard_id),
                zone_id=guard.get('zone_id'), contractor_id=guard.get('contractor_id'), period=window,
                checks=rows, scans=scans, totals=supervision.totals(rows), audit_id=entry['id'])


@router.post('/api/v1/tour/paper-scans', response_model=ScanRecord, status_code=201)
def paper_scan(payload: PaperScanInput):
    """Later entry of the printed backup form used while the system or network was down."""
    principal = authz.require('manage')
    scheduled = authz.check_scope(record('scheduled_tours', payload.scheduled_tour_id), own=False)
    if payload.station_id not in scheduled['station_ids']:
        raise HTTPException(422, 'ایستگاه در برنامه این دور نیست')
    recorded = payload.recorded_at.isoformat()
    if parse_timestamp(recorded) > parse_timestamp(store.now()):
        raise HTTPException(422, 'زمان ثبت‌شده روی فرم نمی‌تواند در آینده باشد')
    guard = record('guards', scheduled['guard_id'])
    owner = guard.get('keycloak_sub') or 'paper:' + guard['id']
    client_id = f'paper:{payload.form_serial}:{payload.station_id}'
    previous = store.field.scan_by_client(owner, client_id)
    if previous:
        if previous['tour_id'] == scheduled.get('tour_id') and previous.get('paper_recorded_at') == recorded:
            return previous
        raise HTTPException(409, 'این ردیف فرم کاغذی قبلاً با مقدار دیگری ثبت شده است')
    stamp = store.now()
    if not scheduled.get('tour_id'):
        tour = dict(id=new_id('TOUR'), route_id=scheduled.get('route_id'),
                    guard_id=guard['id'], owner_sub=owner, zone_id=scheduled['zone_id'],
                    contractor_id=scheduled['contractor_id'], status='completed', started_at=recorded,
                    completed_at=recorded, scheduled_tour_id=scheduled['id'], method='paper')
        store.field.save('tour', tour)
        scheduled.update(tour_id=tour['id'], status='completed')
        store.field.save('scheduled_tours', scheduled)
    tour_id = scheduled['tour_id']
    if any(v['tour_id'] == tour_id and v['station_id'] == payload.station_id and v['status'] == 'completed'
           for v in store.field.records('station_visits')):
        raise HTTPException(409, 'برای این ایستگاه در این دور بازدید ثبت شده است')
    evidence = dict(tag='paper', location='unavailable', sequence='in_order', dwell='ok', clock='unknown')
    from ..tour import trust
    level = trust(evidence)
    visit = dict(id=new_id('VISIT'), station_id=payload.station_id, tour_id=tour_id, owner_sub=owner, device_id='PAPER',
                 zone_id=scheduled['zone_id'], contractor_id=scheduled['contractor_id'], arrived_at=recorded,
                 completed_at=recorded, status='completed', second_sub=None, assurance='دستی', task_ids=[], tasks=[],
                 min_dwell_seconds=0, two_person_required=False, media_capture_allowed=False, tag_revision=0,
                 scan_id=new_id('SCAN'), trust_level=level, hazard_flags=[], offline_flags=[], method='paper')
    store.field.save('station_visits', visit)
    row = dict(id=visit['scan_id'], method='paper', station_id=payload.station_id, tour_id=tour_id, visit_id=visit['id'],
               owner_sub=owner, device_id='PAPER', client_id=client_id, zone_id=scheduled['zone_id'],
               contractor_id=scheduled['contractor_id'], received_at=stamp, device_time=None, lon=None, lat=None,
               accuracy_m=None, evidence=evidence, trust_level=level, status='accepted', review_sub=principal.sub,
               reviewed_at=stamp, reason=f'فرم کاغذی {payload.form_serial}' + (f'؛ {payload.notes}' if payload.notes else ''),
               hazard_flags=[], offline_flags=[], paper_recorded_at=recorded)
    store.field.append_scan(row)
    store.audit('ورود فرم کاغذی پشتیبان گشت', row['id'], f'{payload.form_serial}:{payload.station_id}')
    return row


@router.post('/api/v1/devices/{id}/capabilities', response_model=DeviceCapabilityReport, status_code=201)
def capability_report(id: str, payload: DeviceCapabilityInput, request: Request):
    """Pilot evidence from the guard's own enrolled device: feature availability, battery, token refresh."""
    principal = authz.require('read')
    device = device_for(request, principal)
    if 'guard' not in principal.roles or device['id'] != id:
        authz.fail('device_owner_mismatch', 403)
    row = dict(**payload.model_dump(), id=new_id('CAP'), device_id=id, owner_sub=principal.sub, reported_at=store.now())
    store.field.save('device_reports', row)
    return row


def stats(values):
    ordered = sorted(values)
    if not ordered:
        return None, None
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    return median, ordered[min(len(ordered) - 1, max(0, -(-95 * len(ordered) // 100) - 1))]


def metric(key, label, value, unit, samples, method):
    return dict(key=key, label=label, value=None if value is None else round(float(value), 3), unit=unit,
                samples=samples, method=method)


@router.get('/api/v1/reports/pilot', response_model=PilotMetrics)
def pilot_metrics(window_from: AwareDatetime | None = None, window_to: AwareDatetime | None = None):
    """Pilot indicators computable from durable records; the rest are listed as manual measurements."""
    principal = authz.require('export')
    if 'guard' in principal.roles:
        authz.fail('permission_denied', 403)
    window = period(window_from, window_to)
    inside = lambda value: value and supervision.in_window(value, window['window_from'], window['window_to'])
    scans = [x for x in supervision.scan_rows() if authz.visible(principal, x, own=False) and inside(x['received_at'])]
    kept = [x for x in scans if x['status'] != 'rejected']
    rows = supervision.checks(principal, window['window_from'], window['window_to'], store.now())
    all_checks = len(rows)
    share = lambda outcome: (sum(r['outcome'] == outcome for r in rows) * 100 / all_checks) if all_checks else None
    events = [e for e in store.field.records('field_safety_events') if e['type'] in ('sos', 'man_down')
              and authz.visible(principal, e, own=False) and inside(e['created_at'])]
    latency = [(parse_timestamp(e['operator_ack_at']) - parse_timestamp(e['created_at'])).total_seconds()
               for e in events if e.get('operator_ack_at')]
    ack_median, ack_p95 = stats(latency)
    ages = [(parse_timestamp(x['received_at']) - parse_timestamp(x['device_time'])).total_seconds() / 60
            for x in scans if x.get('device_time')]
    owners = {x['owner_sub'] for x in scans} | {d['owner_sub'] for d in store.field.devices()}
    reports = [r for r in store.field.records('device_reports') if r['owner_sub'] in owners and inside(r['reported_at'])]
    latest = {}
    for r in reports:
        latest[r['device_id']] = r
    drops = []
    for device_id in latest:
        series = [r for r in reports if r['device_id'] == device_id and r['battery_level'] is not None and not r['charging']]
        if len(series) >= 2:
            hours = (parse_timestamp(series[-1]['reported_at']) - parse_timestamp(series[0]['reported_at'])).total_seconds() / 3600
            if hours > 0:
                drops.append((series[0]['battery_level'] - series[-1]['battery_level']) * 100 / hours)
    refresh_ok = sum(r['auth_refresh_ok'] for r in reports)
    refresh_failed = sum(r['auth_refresh_failed'] for r in reports)
    available = lambda key: (sum(r[key] for r in latest.values()) * 100 / len(latest)) if latest else None
    metrics = [
        metric('trust_high_ratio', 'نسبت اسکن‌های با اعتماد زیاد', (sum(x['trust_level'] == 'high' for x in kept) * 100 / len(kept)) if kept else None,
               '%', len(kept), 'اسکن‌های پذیرفته یا در انتظار بازبینی در بازه؛ اسکن ردشده شمرده نمی‌شود'),
        metric('missed_not_visited', 'ایستگاه ازدست‌رفته: بازدید نشد', share('missed'), '%', all_checks,
               'نسبت به همه بررسی‌های برنامه‌ریزی‌شده با موعد در بازه'),
        metric('missed_unverified', 'بازدید با اعتماد ناکافی', share('visited_unverified'), '%', all_checks,
               'بازدید تکمیل‌شده با trust کم، از جمله فرم کاغذی'),
        metric('suspended_emergency', 'تعلیق با وضعیت اضطرار', share('suspended'), '%', all_checks,
               'جزو ازدست‌رفته شمرده نمی‌شود'),
        metric('alarm_ack_median', 'فاصله اعلام خطر تا رسید اپراتور (میانه)', ack_median, 's', len(latency),
               'SOS و عدم تحرک با رسید اپراتور در بازه؛ رمز اضطرار جدا محرمانه است'),
        metric('alarm_ack_p95', 'فاصله اعلام خطر تا رسید اپراتور (صدک ۹۵)', ack_p95, 's', len(latency), 'همان نمونه'),
        metric('alarm_unacked', 'اعلام خطر بدون رسید', sum(not e.get('operator_ack_at') for e in events), 'count', len(events),
               'تا لحظه تولید گزارش'),
        metric('sync_success_rate', 'نرخ همگام‌سازی موفق اسکن', (len(kept) * 100 / len(scans)) if scans else None, '%', len(scans),
               'اسکن پذیرفته‌شده نسبت به همه اسکن‌های دریافتی؛ رد امضا پیش از ثبت در audit دیده می‌شود'),
        metric('queue_age_max', 'بیشترین عمر رکورد در صف', max(ages) if ages else None, 'min', len(ages),
               'اختلاف زمان دریافت سرور و زمان دستگاه'),
        metric('battery_drain', 'مصرف باتری (میانه درصد در ساعت)', stats(drops)[0], '%/h', len(drops),
               'گزارش‌های پیاپی دستگاه بدون شارژ؛ برای یک شیفت در طول شیفت ضرب شود'),
        metric('token_refresh_success', 'موفقیت تمدید توکن کیکلاک', (refresh_ok * 100 / (refresh_ok + refresh_failed)) if refresh_ok + refresh_failed else None,
               '%', refresh_ok + refresh_failed, 'شمارنده‌های گزارش‌شده توسط اپ میدانی'),
        metric('barcode_detector', 'دسترس‌پذیری BarcodeDetector', available('barcode_detector'), '%', len(latest), 'آخرین گزارش هر دستگاه'),
        metric('web_nfc', 'دسترس‌پذیری Web NFC', available('web_nfc'), '%', len(latest), 'آخرین گزارش هر دستگاه'),
        metric('wake_lock_motion', 'Wake Lock و حسگر حرکت', (sum(r['wake_lock'] and r['device_motion'] for r in latest.values()) * 100 / len(latest)) if latest else None,
               '%', len(latest), 'پیش‌نیاز تشخیص عدم تحرک؛ رفتار با صفحه قفل آزمون دستی است'),
    ]
    entry = store.audit('خروجی شاخص‌های پایلوت', 'PILOT-METRICS')
    return dict(classification_label=store.state['settings']['classification_label'], generated_at=store.now(),
                period=window, metrics=metrics, audit_id=entry['id'],
                manual_measurements=['موفقیت ورود کیکلاک روی شبکه میدان (نمونه‌برداری دستی در هر شیفت)',
                                     'رفتار تشخیص عدم تحرک با صفحه قفل روی هر مدل گوشی',
                                     'مصرف باتری یک شیفت کامل با گوشی شارژشده در آغاز شیفت',
                                     'معیار رد پایش پس‌زمینه طبق برنامه پایلوت در DESIGN-REVIEW.fa.md'])

