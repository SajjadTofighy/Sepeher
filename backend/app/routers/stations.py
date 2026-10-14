"""Phase-one station operations; transactions and identity reuse phase zero."""
import math
import os
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from .. import authz, engine, qr, store, tour as tour_evidence, tour_tags
from ..models import (FieldZone, FieldZoneInput, SealChange, SealReplacement, Station,
    ManualReviewInput, ManualScanInput, ScanRecord, StationInput, StationScan, StationTagSheet, StationTagStatusInput, StationTask,
    StationTaskAnswer, StationTaskInput, StationTaskResult, StationVisit, StationVisitCancel, StationVisitInput,
    SunProvisioning, TagVerification)
from ..tracks import parse_timestamp
from .field import ERROR_RESPONSES, FieldRoute, device_for, new_id, record

router = APIRouter(route_class=FieldRoute, tags=['stations'], responses=ERROR_RESPONSES)


def get_station(id):
    item = store.field.get('stations', id)
    if item is None:
        raise HTTPException(404, 'ایستگاه پیدا نشد')
    authz.require('station_read')
    return authz.check_scope(item, own=False)


def field_zone(id):
    zone = store.field.get('field_zones', id)
    if not zone:
        raise HTTPException(409, 'محوطه گشت باید ابتدا در مخزن پایدار ثبت شود')
    return zone


def position(station, payload):
    zone = field_zone(station['zone_id'])
    if payload.lon is None or payload.lat is None or not engine.point_in_polygon(payload.lon, payload.lat, zone['points']):
        tour_tags.denied('station_outside_zone', 'موقعیت اسکن خارج از محوطه ایستگاه است')


@router.get('/api/v1/tour/zones', response_model=list[FieldZone])
def zones():
    principal = authz.require('station_read')
    return [z for z in store.field.records('field_zones') if 'admin' in principal.roles or z['id'] in principal.zone_ids]


@router.put('/api/v1/tour/zones/{id}', response_model=FieldZone)
def save_zone(id: str, payload: FieldZoneInput):
    authz.require('admin')
    if not id or len(id) > 100:
        raise HTTPException(422, 'شناسه محوطه معتبر نیست')
    for station in store.field.records('stations'):
        if station['zone_id'] == id and not engine.point_in_polygon(station['lon'], station['lat'], payload.points):
            raise HTTPException(409, 'مرز تازه ایستگاه موجود را بیرون محوطه می‌برد')
    item = dict(id=id, **payload.model_dump())
    store.field.save('field_zones', item)
    store.audit('ثبت محوطه پایدار گشت', id)
    return item


@router.get('/api/v1/tour/stations', response_model=list[Station])
def stations():
    principal = authz.require('station_read')
    return [s for s in store.field.records('stations') if authz.visible(principal, s, own=False)]


def station_input(payload):
    authz.require('manage')
    item = payload.model_dump()
    authz.check_scope(item, own=False)
    if payload.sensitivity not in store.state['settings']['station_sensitivity_labels']:
        raise HTTPException(422, 'حساسیت باید از برچسب‌های پیکربندی‌شده انتخاب شود')
    zone = field_zone(payload.zone_id)
    if not engine.point_in_polygon(payload.lon, payload.lat, zone['points']):
        raise HTTPException(422, 'ایستگاه باید داخل محوطه باشد')
    if item['media_capture_allowed'] is None:
        item['media_capture_allowed'] = zone['media_capture_allowed']
    if item['tag_uid']:
        item['tag_uid'] = item['tag_uid'].upper()
    return item


@router.post('/api/v1/tour/stations', response_model=Station, status_code=201)
def create_station(payload: StationInput):
    item = station_input(payload)
    if item['tag_uid'] and any(s.get('tag_uid') == item['tag_uid'] for s in store.field.records('stations')):
        raise HTTPException(409, 'UID تگ قبلاً به ایستگاه دیگری اختصاص یافته است')
    item.update(id=new_id('STN'), tag_status='planned', tag_revision=1, created_at=store.now())
    store.field.save('stations', item)
    tour_tags.new_key(item['id'])
    store.audit('ایجاد ایستگاه گشت', item['id'])
    return item


@router.get('/api/v1/tour/stations/{id}', response_model=Station)
def station(id: str):
    return get_station(id)


@router.put('/api/v1/tour/stations/{id}', response_model=Station)
def update_station(id: str, payload: StationInput):
    previous = get_station(id)
    item = station_input(payload)
    if any(item[k] != previous[k] for k in ('tag_mode', 'tag_uid', 'zone_id', 'contractor_id')):
        raise HTTPException(409, 'حالت تگ، UID و حوزه ایستگاه قابل بازنویسی نیست؛ ایستگاه تازه بسازید')
    previous.update(item)
    store.field.save('stations', previous)
    store.audit('ویرایش ایستگاه گشت', id)
    return previous


@router.post('/api/v1/tour/stations/{id}/tag-status', response_model=Station)
def damaged(id: str, payload: StationTagStatusInput):
    authz.require('manage')
    item = get_station(id)
    if item['tag_status'] == 'revoked':
        raise HTTPException(409, 'تگ ابطال‌شده قابل تغییر نیست')
    item['tag_status'] = payload.tag_status
    store.field.save('stations', item)
    store.audit('ثبت آسیب تگ', id, payload.reason)
    return item


@router.get('/api/v1/tour/stations/{id}/tag-sheet', response_model=StationTagSheet)
def sheet(id: str):
    authz.require('export')
    item = get_station(id)
    if item['tag_status'] in ('damaged', 'revoked'):
        raise HTTPException(409, 'برچسب نامعتبر قابل چاپ نیست')
    code = tour_tags.tag_payload(item)
    audit = store.audit('صدور برگه خنثی برچسب', id)
    return dict(code=code, svg=qr.svg(code) if item['tag_mode'] == 'qr_hmac' else '',
                classification_label=store.state['settings']['classification_label'], audit_id=audit['id'])


@router.post('/api/v1/tour/stations/{id}/sun-provisioning', response_model=SunProvisioning)
def provisioning(id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    authz.require('admin')
    item = get_station(id)
    if item['tag_mode'] != 'nfc_sun' or item['tag_status'] != 'planned':
        raise HTTPException(409, 'آماده‌سازی فقط برای تگ SUN برنامه‌ریزی‌شده است')
    base = os.environ.get('SEPEHR_FIELD_TAG_BASE_URL', 'http://127.0.0.1:8000/nfc')
    url = urlsplit(base)
    if (url.query or url.fragment or url.username or url.password or not url.hostname
            or (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')))):
        raise HTTPException(503, 'مبدأ آماده‌سازی NFC باید HTTPS یا loopback دقیق باشد')
    template = base + '?tag=' + tour_tags.tag_payload(item) + '&picc=' + '0' * 32 + '&cmac=' + '0' * 16
    prefix = 'https://' if url.scheme == 'https' else 'http://'
    uri = bytes([4 if url.scheme == 'https' else 3]) + template[len(prefix):].encode('ascii')
    if len(uri) > 255:
        raise HTTPException(503, 'URL آماده‌سازی برای پروفایل NDEF کوتاه بیش از حد بلند است')
    ndef = bytes([0xD1, 1, len(uri), 0x55]) + uri
    file = len(ndef).to_bytes(2, 'big') + ndef
    key = tour_tags.active_key(id)
    offset = 7 - len(prefix)
    store.audit('صدور کلیدهای آماده‌سازی SUN برای نصاب', id)
    return dict(kid=key['kid'], uid=item['tag_uid'], meta_key=key['meta_key'], file_key=key['file_key'],
                url_template=template, ndef_hex=file.hex(), picc_data_offset=template.index('picc=') + 5 + offset,
                mac_input_offset=template.index('tag=') + offset, mac_offset=template.index('cmac=') + 5 + offset)


@router.post('/api/v1/tour/stations/{id}/install', response_model=Station)
def install(id: str, payload: StationScan):
    principal = authz.require('manage')
    item = get_station(id)
    if item['tag_status'] != 'planned':
        raise HTTPException(409, 'راه‌اندازی نیازمند تگ برنامه‌ریزی‌شده است')
    position(item, payload)
    proof = tour_tags.verify_tag(item, payload.payload)
    item['tag_status'] = 'installed'
    store.field.save('stations', item)
    store.field.save('tag_installations', dict(id=new_id('INSTALL'), station_id=id, lon=payload.lon, lat=payload.lat,
                     installer_sub=principal.sub, time=store.now(), **{k: v for k, v in proof.items() if k != 'station_id'}))
    store.audit('اولین اسکن نصاب و نصب تگ', id, proof['assurance'])
    return item


@router.post('/api/v1/tour/stations/{id}/verify-tag', response_model=TagVerification)
def verify(id: str, payload: StationScan):
    item = get_station(id)
    if item['tag_status'] != 'installed':
        raise HTTPException(409, 'تگ ایستگاه هنوز نصب نشده است')
    position(item, payload)
    proof = tour_tags.verify_tag(item, payload.payload)
    store.audit('اعتبارسنجی تگ ایستگاه', id, proof['assurance'])
    return proof


@router.get('/api/v1/tour/stations/{id}/tasks', response_model=list[StationTask])
def tasks(id: str):
    get_station(id)
    return [t for t in store.field.records('station_tasks') if t['station_id'] == id]


@router.post('/api/v1/tour/stations/{id}/tasks', response_model=StationTask, status_code=201)
def create_task(id: str, payload: StationTaskInput):
    authz.require('manage')
    station = get_station(id)
    if payload.kind == 'audio' and not station['media_capture_allowed']:
        raise HTTPException(409, 'ضبط رسانه در ایستگاه مجاز نیست')
    item = dict(**payload.model_dump(), id=new_id('TASK'), station_id=id, created_at=store.now())
    store.field.save('station_tasks', item)
    store.audit('تعریف وظیفه ایستگاه', item['id'])
    return item


@router.post('/api/v1/tour/stations/{id}/tasks/{task_id}/seal', response_model=SealChange, status_code=201)
def replace_seal(id: str, task_id: str, payload: SealReplacement):
    principal = authz.require('manage')
    get_station(id)
    task = store.field.get('station_tasks', task_id)
    if not task or task['station_id'] != id or task['kind'] != 'seal':
        raise HTTPException(404, 'وظیفه پلمب پیدا نشد')
    if task['expected_value'] == payload.expected_value:
        raise HTTPException(409, 'شماره پلمب تازه باید متفاوت باشد')
    item = dict(**payload.model_dump(), id=new_id('SEAL'), station_id=id, task_id=task_id,
                previous_value=task['expected_value'], actor_sub=principal.sub, time=store.now())
    task['expected_value'] = payload.expected_value
    store.field.save('station_tasks', task)
    store.field.save('seal_changes', item)
    store.audit('تعویض پلمب ایستگاه', task_id, f"{item['previous_value']} → {item['expected_value']}: {payload.reason}")
    return item


@router.post('/api/v1/tour/stations/{id}/visits', response_model=StationVisit, status_code=201)
def arrival(id: str, payload: StationVisitInput, request: Request):
    principal = authz.require('read')
    station = get_station(id)
    tour = record('tour', payload.tour_id)
    if 'guard' not in principal.roles or tour['owner_sub'] != principal.sub or tour['status'] != 'active':
        tour_tags.denied('visit_owner_required', 'گشت فعال متعلق به نگهبان لازم است')
    if (tour['zone_id'], tour['contractor_id']) != (station['zone_id'], station['contractor_id']):
        tour_tags.denied('scope_denied', 'ایستگاه متعلق به حوزه گشت نیست')
    device = device_for(request, principal)
    previous = store.field.scan_by_client(principal.sub, payload.client_id)
    if previous:
        if (previous['tour_id'] == tour['id'] and previous['station_id'] == id
                and previous.get('request_hash') == tour_evidence.request_hash(payload) and previous.get('visit_id')):
            return store.field.get('station_visits', previous['visit_id'])
        if previous.get('request_hash') == tour_evidence.request_hash(payload) and previous['status'] == 'rejected' and previous['reason'] == 'tag_replay':
            from starlette.responses import JSONResponse
            return JSONResponse({'detail': {'code': 'tag_replay', 'message': 'شمارنده تگ تکراری یا عقب‌رفته است'}}, status_code=403)
        raise HTTPException(409, 'شناسه درخواست اسکن قبلاً مصرف شده است')
    if tour.get('scheduled_tour_id'):
        scheduled = store.field.get('scheduled_tours', tour['scheduled_tour_id'])
        done = {v['station_id'] for v in store.field.records('station_visits')
                if v['tour_id'] == tour['id'] and v['status'] == 'completed'}
        remaining = [station_id for station_id in scheduled['station_ids'] if station_id not in done]
        if not remaining or id != remaining[0]:
            tour_tags.denied('station_order_required', 'فقط ایستگاه بعدی برنامه قابل بازدید است')
    if station['tag_status'] != 'installed':
        raise HTTPException(409, 'تگ نصب‌شده لازم است')
    if any(v['owner_sub'] == principal.sub and v['completed_at'] is None for v in store.field.records('station_visits')):
        raise HTTPException(409, 'بازدید باز دیگری وجود دارد')
    if any(h in station['hazards'] for h in ('h2s', 'flammable')) and not payload.gas_detector_confirmed:
        raise HTTPException(409, 'تأیید روشن بودن گازسنج پیش از ایستگاه لازم است')
    try:
        proof = tour_tags.verify_tag(station, payload.payload)
    except HTTPException as error:
        if isinstance(error.detail, dict) and error.detail.get('code') == 'tag_replay':
            evidence, level = tour_evidence.evaluate(station, tour, payload, tag='replay', received_at=store.now())
            scan = dict(id=new_id('SCAN'), station_id=id, tour_id=tour['id'], visit_id=None,
                        owner_sub=principal.sub, device_id=device['id'], client_id=payload.client_id,
                        request_hash=tour_evidence.request_hash(payload),
                        zone_id=station['zone_id'], contractor_id=station['contractor_id'], received_at=store.now(),
                        device_time=payload.device_time.isoformat() if payload.device_time else None,
                        lon=payload.lon, lat=payload.lat, accuracy_m=payload.accuracy_m,
                        evidence=evidence, trust_level=level, status='rejected', review_sub=None, reviewed_at=None,
                        reason='tag_replay', hazard_flags=[], offline_flags=tour_evidence.offline_flags(payload, store.now()))
            store.field.append_scan(scan)
            store.audit('رد اسکن تکراری تگ', scan['id'])
            from starlette.responses import JSONResponse
            return JSONResponse({'detail': error.detail}, status_code=error.status_code)
        raise
    stamp = store.now()
    evidence, level = tour_evidence.evaluate(station, tour, payload, tag=tour_evidence.tag_evidence(station, proof),
                                    received_at=stamp, dwell='ok' if station['min_dwell_seconds'] == 0 else 'too_short')
    offline_flags = tour_evidence.offline_flags(payload, stamp)
    level = tour_evidence.trust(evidence, offline_flags)
    flags = ['دستگاه فاقد گواهی Ex'] if any(h.startswith('ex_zone_') for h in station['hazards']) and not device['ex_certified'] else []
    selected = [t for t in store.field.records('station_tasks') if t['station_id'] == id]
    item = dict(id=new_id('VISIT'), station_id=id, tour_id=tour['id'], owner_sub=principal.sub, device_id=device['id'],
        zone_id=station['zone_id'], contractor_id=station['contractor_id'], arrived_at=stamp, completed_at=None,
        second_sub=None, assurance=proof['assurance'], task_ids=[t['id'] for t in selected],
        min_dwell_seconds=station['min_dwell_seconds'], two_person_required=station['two_person_required'],
        media_capture_allowed=station['media_capture_allowed'], tag_revision=station['tag_revision'],
        scan_id=new_id('SCAN'), trust_level=level, hazard_flags=flags, offline_flags=offline_flags)
    # Immutable task snapshots preserve bounds/seal evidence across later changes.
    item['tasks'] = selected
    item['lon'], item['lat'] = payload.lon, payload.lat
    store.field.save('station_visits', item)
    store.field.append_scan(dict(id=item['scan_id'], station_id=id, tour_id=tour['id'], visit_id=item['id'],
        owner_sub=principal.sub, device_id=device['id'], client_id=payload.client_id,
        request_hash=tour_evidence.request_hash(payload),
        zone_id=station['zone_id'], contractor_id=station['contractor_id'], received_at=stamp,
        device_time=payload.device_time.isoformat() if payload.device_time else None,
        lon=payload.lon, lat=payload.lat, accuracy_m=payload.accuracy_m, evidence=evidence, trust_level=level,
        status='accepted', review_sub=None, reviewed_at=None, reason='', hazard_flags=flags,
        offline_flags=offline_flags))
    store.audit('شروع بازدید ایستگاه', item['id'], proof['assurance'])
    return item


def scan_view(row):
    review = store.field.get('scan_reviews', row['id'])
    return {**row, 'status': 'accepted' if review and review['approved'] else 'rejected' if review else row['status'],
            'review_sub': review['review_sub'] if review else None,
            'reviewed_at': review['reviewed_at'] if review else None,
            'visit_id': review['visit_id'] if review and review['approved'] else row.get('visit_id')}


@router.get('/api/v1/tour/scans', response_model=list[ScanRecord])
def scans():
    principal = authz.require('read')
    rows = [scan_view(row) for row in store.field.scans() if authz.visible(principal, row)]
    if 'guard' not in principal.roles:
        for row in rows:
            store.audit('مشاهده شواهد اسکن', row['id'])
    return rows


@router.post('/api/v1/tour/stations/{id}/manual-scan', response_model=ScanRecord, status_code=201)
def manual_scan(id: str, payload: ManualScanInput, request: Request):
    principal = authz.require('read')
    station = get_station(id)
    current = record('tour', payload.tour_id)
    if 'guard' not in principal.roles or current['owner_sub'] != principal.sub or current['status'] != 'active':
        tour_tags.denied('visit_owner_required', 'گشت فعال متعلق به نگهبان لازم است')
    if (current['zone_id'], current['contractor_id']) != (station['zone_id'], station['contractor_id']):
        tour_tags.denied('scope_denied', 'ایستگاه متعلق به حوزه گشت نیست')
    device = device_for(request, principal)
    previous = store.field.scan_by_client(principal.sub, payload.client_id)
    if previous:
        if (previous['station_id'] == id and previous['tour_id'] == current['id']
                and previous.get('request_hash') == tour_evidence.request_hash(payload)):
            return scan_view(previous)
        raise HTTPException(409, 'شناسه درخواست اسکن قبلاً مصرف شده است')
    if any(h in station['hazards'] for h in ('h2s', 'flammable')) and not payload.gas_detector_confirmed:
        raise HTTPException(409, 'تأیید روشن بودن گازسنج پیش از ایستگاه لازم است')
    if payload.uid and payload.uid.upper() != station.get('tag_uid'):
        raise HTTPException(422, 'UID گزارش‌شده با تگ ایستگاه سازگار نیست')
    stamp = store.now()
    evidence, level = tour_evidence.evaluate(station, current, payload,
                                             tag='uid_only' if payload.uid else 'manual', received_at=stamp)
    offline_flags = tour_evidence.offline_flags(payload, stamp)
    flags = ['دستگاه فاقد گواهی Ex'] if any(h.startswith('ex_zone_') for h in station['hazards']) and not device['ex_certified'] else []
    row = dict(id=new_id('SCAN'), station_id=id, tour_id=current['id'], visit_id=None,
        owner_sub=principal.sub, device_id=device['id'], client_id=payload.client_id,
        request_hash=tour_evidence.request_hash(payload),
        zone_id=station['zone_id'], contractor_id=station['contractor_id'], received_at=stamp,
        device_time=payload.device_time.isoformat() if payload.device_time else None,
        lon=payload.lon, lat=payload.lat, accuracy_m=payload.accuracy_m,
        evidence=evidence, trust_level=level, status='pending_review', review_sub=None, reviewed_at=None,
        reason=payload.reason, hazard_flags=flags, offline_flags=offline_flags)
    store.field.append_scan(row)
    store.audit('ثبت اسکن دستی در انتظار تأیید', row['id'], payload.reason)
    return row


@router.post('/api/v1/tour/scans/{id}/review', response_model=ScanRecord)
def review_scan(id: str, payload: ManualReviewInput):
    principal = authz.require('manage')
    if not set(principal.roles) & {'shift_supervisor', 'security_officer', 'security_manager', 'admin'}:
        raise HTTPException(403, 'تأیید اسکن دستی به سرپرست نیاز دارد')
    row = next((s for s in store.field.scans() if s['id'] == id), None)
    if not row:
        raise HTTPException(404, 'اسکن پیدا نشد')
    authz.check_scope(row, own=False)
    if row['status'] != 'pending_review' or store.field.get('scan_reviews', id) or principal.sub == row['owner_sub']:
        raise HTTPException(409, 'اسکن برای این تأیید معتبر نیست')
    visit_id = None
    if payload.approved:
        if row['evidence']['sequence'] != 'in_order':
            raise HTTPException(409, 'اسکن خارج از ترتیب مسیر قابل تأیید نیست')
        current = store.field.get('tour', row['tour_id'])
        station = store.field.get('stations', row['station_id'])
        if not current or current['status'] != 'active' or not station:
            raise HTTPException(409, 'گشت یا ایستگاه دیگر فعال نیست')
        if any(v['owner_sub'] == row['owner_sub'] and v['completed_at'] is None for v in store.field.records('station_visits')):
            raise HTTPException(409, 'بازدید باز دیگری وجود دارد')
        tasks = [t for t in store.field.records('station_tasks') if t['station_id'] == station['id']]
        visit_id = new_id('VISIT')
        item = dict(id=visit_id, station_id=station['id'], tour_id=current['id'], owner_sub=row['owner_sub'],
            device_id=row['device_id'], zone_id=row['zone_id'], contractor_id=row['contractor_id'],
            arrived_at=row['received_at'], completed_at=None, status='active', second_sub=None,
            assurance='دستی', task_ids=[t['id'] for t in tasks], tasks=tasks,
            min_dwell_seconds=station['min_dwell_seconds'], two_person_required=station['two_person_required'],
            media_capture_allowed=station['media_capture_allowed'], tag_revision=station['tag_revision'],
            scan_id=id, trust_level='low', hazard_flags=row['hazard_flags'],
            offline_flags=row.get('offline_flags', []), manual_review_id=id,
            lon=row['lon'], lat=row['lat'])
        store.field.save('station_visits', item)
    review = dict(id=id, approved=payload.approved, reason=payload.reason, review_sub=principal.sub,
                  reviewed_at=store.now(), visit_id=visit_id)
    store.field.save('scan_reviews', review)
    store.audit('تأیید اسکن دستی' if payload.approved else 'رد اسکن دستی', id, payload.reason)
    return scan_view(row)


def visit_record(id, own=True):
    item = store.field.get('station_visits', id)
    if not item:
        raise HTTPException(404, 'بازدید پیدا نشد')
    return authz.check_scope(item, own=own)


@router.get('/api/v1/tour/station-visits', response_model=list[StationVisit])
def visits():
    principal = authz.require('read')
    return [v for v in store.field.records('station_visits') if authz.visible(principal, v)]


@router.post('/api/v1/tour/station-visits/{id}/confirm', response_model=StationVisit)
def confirm(id: str, payload: StationScan):
    principal = authz.require('read')
    item = visit_record(id, own=False)
    if 'guard' not in principal.roles or principal.sub == item['owner_sub']:
        tour_tags.denied('two_person_required', 'تأیید حضور به نگهبان دوم با هویت مستقل نیاز دارد')
    if item['completed_at'] or item['second_sub']:
        raise HTTPException(409, 'بازدید قبلاً تأیید یا تکمیل شده است')
    if (parse_timestamp(store.now()) - parse_timestamp(item['arrived_at'])).total_seconds() > store.state['settings']['two_person_window_minutes'] * 60:
        raise HTTPException(409, 'پنجره تأیید نفر دوم سپری شده است')
    station = get_station(item['station_id'])
    if station['tag_status'] != 'installed' or station['tag_revision'] != item['tag_revision']:
        raise HTTPException(409, 'نسخه تگ از آغاز بازدید تغییر کرده است')
    position(station, payload)
    tour_tags.verify_tag(station, payload.payload)
    item['second_sub'] = principal.sub
    store.field.save('station_visits', item)
    store.audit('تأیید حضور نفر دوم', id)
    return item


@router.post('/api/v1/tour/station-visits/{id}/tasks/{task_id}', response_model=StationTaskResult, status_code=201)
def answer(id: str, task_id: str, payload: StationTaskAnswer):
    principal = authz.require('read')
    visit = visit_record(id)
    if principal.sub != visit['owner_sub'] or visit['completed_at']:
        tour_tags.denied('visit_owner_required', 'پاسخ فقط برای بازدید باز خود نگهبان مجاز است')
    task = next((t for t in visit['tasks'] if t['id'] == task_id), None)
    if not task:
        raise HTTPException(404, 'وظیفه در این بازدید وجود ندارد')
    value, anomaly, evidence = payload.value, False, ''
    if task['kind'] == 'number':
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or not task['min'] <= value <= task['max'] or payload.media_id:
            raise HTTPException(422, 'عدد باید در بازه مجاز وظیفه باشد')
        evidence = f"{value} {task['unit']}"
    elif task['kind'] == 'choice':
        if value not in task['options'] or payload.media_id:
            raise HTTPException(422, 'گزینه پاسخ در فهرست مجاز نیست')
        evidence = value
    elif task['kind'] == 'seal':
        if not isinstance(value, str) or not value.strip() or len(value) > 100 or payload.media_id:
            raise HTTPException(422, 'شماره پلمب لازم است')
        anomaly = value != task['expected_value']
        evidence = f"expected={task['expected_value']}; observed={value}"
    else:
        station = get_station(visit['station_id'])
        if not visit['media_capture_allowed'] or not station['media_capture_allowed']:
            tour_tags.denied('media_capture_denied', 'ضبط رسانه در این ایستگاه مجاز نیست')
        media = store.field.get('media', payload.media_id) if payload.media_id else None
        if payload.value is not None or not media or media['tour_id'] != visit['tour_id'] or media['owner_sub'] != principal.sub or media['media_type'] != 'audio':
            raise HTTPException(422, 'رسانه صوتی متعلق به همین گشت لازم است')
        evidence = payload.media_id
    result = dict(id=f'{id}:{task_id}', visit_id=id, task_id=task_id, value=value, media_id=payload.media_id,
                  anomaly=anomaly, evidence=evidence, recorded_at=store.now())
    if store.field.get('station_results', result['id']):
        raise HTTPException(409, 'پاسخ وظیفه قبلاً ثبت شده است')
    store.field.save('station_results', result)
    store.audit('ثبت پاسخ ناهنجار پلمب' if anomaly else 'ثبت پاسخ وظیفه', task_id, evidence)
    return result


@router.get('/api/v1/tour/station-visits/{id}/results', response_model=list[StationTaskResult])
def results(id: str):
    visit_record(id)
    return [r for r in store.field.records('station_results') if r['visit_id'] == id]


@router.post('/api/v1/tour/station-visits/{id}/complete', response_model=StationVisit)
def complete(id: str):
    principal = authz.require('read')
    item = visit_record(id)
    if principal.sub != item['owner_sub'] or item['completed_at']:
        raise HTTPException(409, 'بازدید باز متعلق به همین نگهبان لازم است')
    station = get_station(item['station_id'])
    tour = record('tour', item['tour_id'])
    if tour['status'] != 'active' or (not item.get('manual_review_id') and (station['tag_status'] != 'installed' or station['tag_revision'] != item['tag_revision'])):
        raise HTTPException(409, 'گشت یا نسخه تگ از آغاز بازدید معتبر نمانده است')
    elapsed = (parse_timestamp(store.now()) - parse_timestamp(item['arrived_at'])).total_seconds()
    if elapsed < max(item['min_dwell_seconds'], station['min_dwell_seconds']):
        raise HTTPException(409, 'حداقل زمان توقف هنوز سپری نشده است')
    if (item['two_person_required'] or station['two_person_required']) and not item['second_sub']:
        tour_tags.denied('two_person_required', 'حضور نفر دوم تأیید نشده است')
    answers = {r['task_id'] for r in store.field.records('station_results') if r['visit_id'] == id}
    if any(t['required'] and t['id'] not in answers for t in item['tasks']):
        raise HTTPException(409, 'وظایف الزامی هنوز پاسخ داده نشده‌اند')
    item['completed_at'] = store.now()
    item['status'] = 'completed'
    if item.get('scan_id'):
        scan = next((s for s in store.field.scans() if s['id'] == item['scan_id']), None)
        if scan:
            item['trust_level'] = tour_evidence.trust({**scan['evidence'], 'dwell': 'ok'}, scan.get('offline_flags', []))
    store.field.save('station_visits', item)
    store.audit('تکمیل بازدید ایستگاه', id)
    return item


@router.post('/api/v1/tour/station-visits/{id}/cancel', response_model=StationVisit)
def cancel(id: str, payload: StationVisitCancel):
    principal = authz.require('read')
    item = visit_record(id)
    if principal.sub != item['owner_sub'] or item['completed_at']:
        raise HTTPException(409, 'فقط بازدید باز خود نگهبان قابل لغو است')
    item.update(status='cancelled', completed_at=store.now(), cancellation_reason=payload.reason)
    store.field.save('station_visits', item)
    store.audit('لغو بازدید ایستگاه', id, payload.reason)
    return item
