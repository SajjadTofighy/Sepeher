"""Phase-five field media custody, report routing and urgent message escalation.

Binary media is stored once, unmodified, outside SQLite; watermarks are drawn by
viewers at display/export time from the metadata returned here. Deletion happens
only in the retention tick, never for media under legal hold.
"""
from datetime import timedelta
import hashlib
import os
from pathlib import Path

from fastapi import HTTPException

from ..security import authz
from .. import engine, store
from .safety import escalation_level
from ..models import RESTRICTED_REPORT_CATEGORIES
from ..tracks import parse_timestamp

RESTRICTED_VIEWERS = {'security_manager', 'admin'}
SAFETY_INSTRUCTION = 'نزدیک نشو، از فاصله امن گزارش کن'
UPLOAD_ABANDON_HOURS = 24


def media_root():
    configured = os.environ.get('SEPEHR_MEDIA_DIR')
    root = Path(configured) if configured else store.field.path.parent / 'media'
    for name in ('uploads', 'objects'):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def upload_path(upload_id):
    return media_root() / 'uploads' / (upload_id + '.part')


def object_path(media_id):
    return media_root() / 'objects' / (media_id + '.bin')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def jalali(year, month, day):
    """Pure Gregorian to Solar Hijri conversion (33-year arithmetic cycle)."""
    offsets = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    leap_year = year + 1 if month > 2 else year
    days = (355666 + 365 * year + (leap_year + 3) // 4 - (leap_year + 99) // 100
            + (leap_year + 399) // 400 + day + offsets[month - 1])
    result = -1595 + 33 * (days // 12053)
    days %= 12053
    result += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        result += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return result, 1 + days // 31, 1 + days % 31
    return result, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def jalali_stamp(value):
    local = parse_timestamp(value).astimezone(engine.TEHRAN)
    year, month, day = jalali(local.year, local.month, local.day)
    return f'{year:04}/{month:02}/{day:02} {local.hour:02}:{local.minute:02}'


def restricted(item):
    return item.get('category') in RESTRICTED_REPORT_CATEGORIES


def may_view(principal, item):
    if not authz.visible(principal, item, own=True):
        return False
    return not restricted(item) or 'guard' in principal.roles or bool(set(principal.roles) & RESTRICTED_VIEWERS)


def may_read_content(principal, item):
    if item['status'] != 'stored' or not may_view(principal, item):
        return False
    # Restricted evidence leaves the guard's device after a successful upload.
    return not (restricted(item) and 'guard' in principal.roles)


def retention_until(item):
    if not item.get('server_received_at'):
        return None
    days = store.state['settings']['media_retention_days'][item.get('category') or 'other']
    return (parse_timestamp(item['server_received_at']) + timedelta(days=days)).isoformat()


def view(item, principal):
    stamp = store.now()
    watermark = dict(captured_at_jalali=jalali_stamp(item.get('server_received_at') or item['created_at']),
                     guard_code=item['guard_id'], station_code=item.get('station_id') or '—',
                     viewer=principal.username, viewed_at_jalali=jalali_stamp(stamp))
    return {**item, 'retention_until': retention_until(item), 'exportable': not restricted(item),
            'watermark': watermark}


def capture_station(tour, media_type, owner_sub):
    """Text and audio are always allowed; images and video follow zone and open-visit station policy."""
    station_id = None
    for visit in store.field.records('station_visits'):
        if visit['tour_id'] == tour['id'] and visit['owner_sub'] == owner_sub and not visit['completed_at']:
            station_id = visit['station_id']
            station = store.field.get('stations', station_id)
            if media_type != 'audio' and (not visit['media_capture_allowed'] or not station['media_capture_allowed']):
                deny_capture()
    zone = store.field.get('field_zones', tour['zone_id'])
    if media_type != 'audio' and zone is not None and not zone['media_capture_allowed']:
        deny_capture()
    return station_id


def deny_capture():
    raise HTTPException(403, dict(code='media_capture_denied',
                                  message='در این محوطه یا ایستگاه فقط متن و صوت مجاز است'))


def report_for(report_id, tour, owner_sub):
    if report_id is None:
        return None
    report = store.field.get('field_reports', report_id)
    if not report or report['owner_sub'] != owner_sub or report['tour_id'] != tour['id']:
        raise HTTPException(422, 'گزارش پیوست باید متعلق به همین نگهبان و گشت باشد')
    return report


def report_view(report):
    media_ids = [m['id'] for m in store.field.records('media') if m.get('report_id') == report['id']]
    return {**report, 'media_ids': media_ids}


def message_acknowledged(row):
    if row['recipients']:
        return all(r['acknowledged_at'] for r in row['recipients'])
    return bool(row.get('center_ack_at'))


def message_escalation(row, now=None):
    if row['priority'] != 'urgent':
        return 'operator'
    return escalation_level(row['created_at'], message_acknowledged(row),
                            store.state['settings']['message_urgent_escalation_seconds'], now)


@store.state_locked
def tick(now):
    """Retention purge, abandoned upload cleanup and urgent-message escalation audit."""
    current = parse_timestamp(now)
    for item in store.field.records('media'):
        until = retention_until(item)
        if item['status'] == 'stored' and not item.get('legal_hold') and until and parse_timestamp(until) <= current:
            object_path(item['id']).unlink(missing_ok=True)
            item.update(status='purged', purged_at=now)
            store.field.save('media', item)
            store.audit('حذف رسانه پس از پایان دوره نگهداری', item['id'], item.get('category') or 'other', actor='سامانه')
    for upload in store.field.records('media_uploads'):
        if upload['status'] == 'open' and current - parse_timestamp(upload['updated_at']) >= timedelta(hours=UPLOAD_ABANDON_HOURS):
            upload_path(upload['id']).unlink(missing_ok=True)
            upload.update(status='failed', updated_at=now)
            store.field.save('media_uploads', upload)
            store.audit('بستن آپلود رهاشده رسانه', upload['id'], actor='سامانه')
    for row in store.field.records('messages'):
        level = message_escalation(row, now)
        if row.get('escalation', 'operator') != level:
            row['escalation'] = level
            store.field.save('messages', row)
            store.audit('تشدید پیام فوری بی‌رسید', row['id'], level, actor='سامانه')
