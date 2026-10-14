"""Phase six: exception board, station verification status and patrol reports."""
import csv
from datetime import timedelta
import io

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime
from starlette.responses import Response

from .. import authz, store, supervision
from ..field_media import jalali_stamp
from ..models import ExceptionBoard, GuardDetailReport, PatrolReport, StationStatus
from ..tracks import parse_timestamp
from .field import ERROR_RESPONSES, FieldRoute, record

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
