"""Phase five: field messages, resumable media custody and categorised field reports.

Nothing here dispatches, sends to external systems or creates incidents; report
routing records which internal units must acknowledge, and humans act.
"""
import asyncio
import hashlib
import os

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse, Response

from .. import store
from ..security import auth, authz
from ..field import media as media_logic
from ..models import (CapturePolicy, FieldMedia, FieldMediaInput, FieldMessage, FieldMessageInput, FieldReport, FieldReportInput,
                      LegalHoldInput, MediaAttachInput, MediaUpload, MediaUploadInput, MediaUploadResult,
                      MEDIA_CONTENT_TYPES, ReportAckInput)
from ..tour.evidence import request_hash
from .field import ERROR_RESPONSES, FieldRoute, device_for, new_id, record, run_field

router = APIRouter(route_class=FieldRoute, tags=['field-comms'], responses=ERROR_RESPONSES)
# Raw-body endpoints are asynchronous; they run the same field transaction in a worker thread.
upload_router = APIRouter(route_class=store.StateRoute, tags=['field-comms'], responses=ERROR_RESPONSES)


def guard_tour(tour_id, request, *, active=True):
    principal = authz.require('read')
    tour = record('tour', tour_id)
    if 'guard' not in principal.roles or tour['owner_sub'] != principal.sub or (active and tour['status'] != 'active'):
        auth.fail('permission_denied', 403)
    return principal, tour, device_for(request, principal)


def security_staff():
    return authz.require('manage')


# ---------------------------------------------------------------- messages

def message_view(row, principal):
    row = {**row, 'escalation': media_logic.message_escalation(row)}
    if 'guard' in principal.roles:
        row['recipients'] = [r for r in row['recipients'] if r['owner_sub'] == principal.sub]
    return row


def message_visible(principal, row):
    if 'guard' in principal.roles:
        return authz.visible(principal, row, own=False) and (
            row['owner_sub'] == principal.sub or any(r['owner_sub'] == principal.sub for r in row['recipients']))
    return authz.visible(principal, row, own=False)


@router.get('/api/v1/messages', response_model=list[FieldMessage])
def messages():
    principal = authz.require('read')
    return [message_view(row, principal) for row in store.field.records('messages') if message_visible(principal, row)]


@router.post('/api/v1/messages', response_model=FieldMessage, status_code=201)
def send_message(payload: FieldMessageInput, request: Request):
    principal = authz.require('read')
    stamp = store.now()
    base = dict(id=new_id('MSG'), text=payload.text, priority=payload.priority, sender_sub=principal.sub,
                created_at=stamp, center_ack_at=None, center_ack_sub=None, escalation='operator')
    if 'guard' in principal.roles:
        if payload.audience is not None or payload.tour_id is None:
            raise HTTPException(422, 'پیام نگهبان فقط با شناسه گشت خود به مرکز ارسال می‌شود')
        _, tour, _ = guard_tour(payload.tour_id, request, active=False)
        item = dict(base, tour_id=tour['id'], direction='to_center', owner_sub=principal.sub, guard_id=tour['guard_id'],
                    zone_id=tour['zone_id'], contractor_id=tour['contractor_id'], recipients=[])
    else:
        security_staff()
        if payload.audience is None or payload.tour_id is not None:
            raise HTTPException(422, 'پیام مرکز به مخاطب نگهبان یا محوطه نیاز دارد')
        audience = payload.audience
        if audience.guard_id:
            guard = authz.check_scope(record('guards', audience.guard_id), own=False)
            if not guard.get('keycloak_sub'):
                auth.fail('guard_not_linked', 409)
            tour = next((t for t in store.field.records('tour') if t['status'] == 'active'
                         and t['guard_id'] == guard['id']), None)
            item = dict(base, tour_id=tour['id'] if tour else None, direction='to_guard', owner_sub=principal.sub,
                        guard_id=guard['id'], zone_id=guard['zone_id'], contractor_id=guard['contractor_id'],
                        recipients=[dict(guard_id=guard['id'], owner_sub=guard['keycloak_sub'], acknowledged_at=None)])
        else:
            if store.field.get('field_zones', audience.broadcast_zone) is None:
                raise HTTPException(404, 'محوطه پیدا نشد')
            contractor = audience.contractor_id or principal.contractor_id
            if not contractor:
                raise HTTPException(422, 'پیمانکار اعلان محوطه باید تعیین شود')
            authz.check_scope({'zone_id': audience.broadcast_zone, 'contractor_id': contractor}, own=False)
            recipients, seen = [], set()
            for tour in store.field.records('tour'):
                if (tour['status'] == 'active' and tour['zone_id'] == audience.broadcast_zone
                        and tour['contractor_id'] == contractor and tour['owner_sub'] not in seen):
                    seen.add(tour['owner_sub'])
                    recipients.append(dict(guard_id=tour['guard_id'], owner_sub=tour['owner_sub'], acknowledged_at=None))
            item = dict(base, tour_id=None, direction='broadcast', owner_sub=principal.sub, guard_id=None,
                        zone_id=audience.broadcast_zone, contractor_id=contractor, recipients=recipients)
    store.field.save('messages', item)
    store.audit('ثبت پیام میدانی' if item['direction'] == 'to_center' else 'ارسال پیام مرکز به نگهبان', item['id'],
                f"{item['direction']}:{item['priority']}")
    return message_view(item, principal)


@router.post('/api/v1/messages/{id}/ack', response_model=FieldMessage)
def acknowledge_message(id: str, request: Request):
    principal = authz.require('read')
    row = store.field.get('messages', id)
    if row is None or not message_visible(principal, row):
        raise HTTPException(404, 'پیام پیدا نشد')
    stamp = store.now()
    if 'guard' in principal.roles:
        device_for(request, principal)
        recipient = next((r for r in row['recipients'] if r['owner_sub'] == principal.sub), None)
        if recipient is None:
            raise HTTPException(409, 'رسید پیام فقط برای گیرنده آن است')
        if recipient['acknowledged_at'] is None:
            recipient['acknowledged_at'] = stamp
            store.audit('رسید صریح پیام توسط نگهبان', id)
    else:
        security_staff()
        if row['direction'] != 'to_center':
            raise HTTPException(409, 'رسید مرکز فقط برای پیام نگهبان است')
        if row['center_ack_at'] is None:
            row.update(center_ack_at=stamp, center_ack_sub=principal.sub)
            store.audit('رسید مرکز برای پیام نگهبان', id)
    row['escalation'] = media_logic.message_escalation(row, stamp)
    store.field.save('messages', row)
    return message_view(row, principal)


# ---------------------------------------------------------------- reports

def create_report(tour, device, payload, stamp, *, auth_expired=False, clock_regressed=False, offline_too_long=False):
    payload_hash = request_hash(payload)
    prior = next((r for r in store.field.records('field_reports') if r['owner_sub'] == tour['owner_sub']
                  and r['client_id'] == payload.client_id), None)
    if prior:
        if prior['request_hash'] != payload_hash:
            raise HTTPException(409, 'شناسه گزارش قبلاً برای گزارش دیگری مصرف شده است')
        return prior
    restricted = payload.category in ('damage', 'uxo', 'drone_sighting')
    item = dict(id=new_id('REPORT'), tour_id=tour['id'], guard_id=tour['guard_id'], owner_sub=tour['owner_sub'],
                device_id=device['id'], zone_id=tour['zone_id'], contractor_id=tour['contractor_id'],
                client_id=payload.client_id, request_hash=payload_hash, category=payload.category, text=payload.text,
                lon=payload.lon, lat=payload.lat, created_at=stamp,
                audiences=list(store.state['settings']['report_routing'][payload.category]), acknowledgements=[],
                restricted=restricted, safety_instruction=media_logic.SAFETY_INSTRUCTION if restricted else None,
                purge_local_media=restricted, auth_expired=auth_expired, clock_regressed=clock_regressed,
                offline_too_long=offline_too_long)
    store.field.save('field_reports', item)
    store.audit('ثبت گزارش میدانی', item['id'], f"{payload.category}:{','.join(item['audiences'])}")
    return item


@router.get('/api/v1/tour/reports', response_model=list[FieldReport])
def reports(category: str | None = None, audience: str | None = None):
    principal = authz.require('read')
    rows = [media_logic.report_view(r) for r in store.field.records('field_reports') if authz.visible(principal, r)]
    return [r for r in rows if (category is None or r['category'] == category)
            and (audience is None or audience in r['audiences'])]


@router.post('/api/v1/tour/reports', response_model=FieldReport, status_code=201)
def submit_report(payload: FieldReportInput, request: Request):
    _, tour, device = guard_tour(payload.tour_id, request)
    return media_logic.report_view(create_report(tour, device, payload, store.now()))


@router.post('/api/v1/tour/reports/{id}/ack', response_model=FieldReport)
def acknowledge_report(id: str, payload: ReportAckInput):
    principal = security_staff()
    row = store.field.get('field_reports', id)
    if row is None:
        raise HTTPException(404, 'گزارش پیدا نشد')
    authz.check_scope(row, own=False)
    if payload.audience not in row['audiences']:
        raise HTTPException(422, 'این واحد مخاطب دسته گزارش نیست')
    if not any(a['audience'] == payload.audience for a in row['acknowledgements']):
        row['acknowledgements'].append(dict(audience=payload.audience, sub=principal.sub, at=store.now()))
        store.field.save('field_reports', row)
        store.audit('رسید واحد مخاطب برای گزارش میدانی', id, payload.audience)
    return media_logic.report_view(row)


# ---------------------------------------------------------------- media

def media_scope(tour, payload, owner_sub):
    report = media_logic.report_for(payload.report_id, tour, owner_sub)
    station_id = media_logic.capture_station(tour, payload.media_type, owner_sub)
    return station_id, report['category'] if report else None


def media_record(payload, tour, device, station_id, category, stamp):
    return dict(id=new_id('MEDIA'), tour_id=tour['id'], caption=payload.caption, media_type=payload.media_type,
                report_id=payload.report_id, owner_sub=tour['owner_sub'], guard_id=tour['guard_id'],
                zone_id=tour['zone_id'], contractor_id=tour['contractor_id'], created_at=stamp, status='metadata',
                device_id=device['id'], station_id=station_id, category=category, content_type=None, size=None,
                sha256=None, server_received_at=None, legal_hold=False, incident_id=None, purged_at=None)


@router.get('/api/v1/media', response_model=list[FieldMedia])
def media():
    principal = authz.require('read')
    return [media_logic.view(m, principal) for m in store.field.records('media') if media_logic.may_view(principal, m)]


@router.post('/api/v1/media', response_model=FieldMedia, status_code=201)
def create_media(payload: FieldMediaInput, request: Request):
    principal, tour, device = guard_tour(payload.tour_id, request, active=False)
    station_id, category = media_scope(tour, payload, principal.sub)
    item = media_record(payload, tour, device, station_id, category, store.now())
    store.field.save('media', item)
    store.audit('ثبت فراداده رسانه میدانی', item['id'])
    return media_logic.view(item, principal)


@router.get('/api/v1/media/capture-policy', response_model=CapturePolicy)
def capture_policy(tour_id: str, request: Request):
    principal, tour, _ = guard_tour(tour_id, request)
    station_id = media_logic.capture_station(tour, 'audio', principal.sub)
    try:
        media_logic.capture_station(tour, 'image', principal.sub)
        allowed = True
    except HTTPException:
        allowed = False
    settings = store.state['settings']
    return dict(tour_id=tour_id, image_video_allowed=allowed, station_id=station_id,
                video_max_seconds=settings['media_video_max_seconds'], audio_max_seconds=settings['media_audio_max_seconds'],
                video_bitrate_kbps=settings['media_video_bitrate_kbps'], audio_bitrate_kbps=settings['media_audio_bitrate_kbps'],
                chunk_bytes=settings['media_chunk_bytes'], single_upload_max_bytes=settings['media_single_upload_max_bytes'],
                max_bytes=settings['media_max_bytes'])


def upload_view(row):
    return {**row, 'chunk_bytes': store.state['settings']['media_chunk_bytes']}


def own_upload(id):
    principal = authz.require('read')
    row = store.field.get('media_uploads', id)
    if row is None or row['owner_sub'] != principal.sub:
        raise HTTPException(404, 'آپلود پیدا نشد')
    return principal, row


@router.post('/api/v1/media/uploads', response_model=MediaUpload, status_code=201)
def start_upload(payload: MediaUploadInput, request: Request):
    principal, tour, device = guard_tour(payload.tour_id, request)
    if payload.size > store.state['settings']['media_max_bytes']:
        raise HTTPException(413, dict(code='media_too_large', message='حجم رسانه از سقف تنظیم‌شده بیشتر است'))
    payload_hash = request_hash(payload)
    prior = next((u for u in store.field.records('media_uploads') if u['owner_sub'] == principal.sub
                  and u['client_id'] == payload.client_id), None)
    if prior:
        if prior['request_hash'] != payload_hash:
            raise HTTPException(409, 'شناسه آپلود قبلاً برای رسانه دیگری مصرف شده است')
        return upload_view(prior)
    station_id, category = media_scope(tour, payload, principal.sub)
    stamp = store.now()
    row = dict(id=new_id('UPLOAD'), owner_sub=principal.sub, client_id=payload.client_id, request_hash=payload_hash,
               tour_id=tour['id'], device_id=device['id'], caption=payload.caption, report_id=payload.report_id,
               media_type=payload.media_type, content_type=payload.content_type, size=payload.size,
               sha256=payload.sha256, station_id=station_id, category=category, received_bytes=0,
               status='open', media_id=None, created_at=stamp, updated_at=stamp)
    media_logic.upload_path(row['id']).write_bytes(b'')
    store.field.save('media_uploads', row)
    store.audit('شروع آپلود قطعه‌ای رسانه', row['id'], f"{payload.media_type}:{payload.size}")
    return upload_view(row)


@router.get('/api/v1/media/uploads/{id}', response_model=MediaUpload)
def upload_status(id: str):
    return upload_view(own_upload(id)[1])


async def read_body(request, limit):
    declared = request.headers.get('content-length')
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise HTTPException(413, dict(code='chunk_too_large', message='اندازه بدنه از سقف مجاز بیشتر است'))
    chunks, size = [], 0
    async for block in request.stream():
        size += len(block)
        if size > limit:
            raise HTTPException(413, dict(code='chunk_too_large', message='اندازه بدنه از سقف مجاز بیشتر است'))
        chunks.append(block)
    return b''.join(chunks)


def locked_field(function, *args):
    with store.locked_state():
        return run_field(function, *args)


def write_chunk(id, offset, body):
    _, row = own_upload(id)
    if row['status'] != 'open':
        raise HTTPException(409, dict(code='upload_closed', message='آپلود بسته شده است'))
    if offset != row['received_bytes']:
        raise HTTPException(409, dict(code='upload_offset_mismatch',
                                      message=f"قطعه خارج از ترتیب است؛ ادامه از بایت {row['received_bytes']}"))
    if not body or row['received_bytes'] + len(body) > row['size']:
        raise HTTPException(422, 'قطعه خالی است یا از حجم اعلام‌شده فراتر می‌رود')
    path = media_logic.upload_path(id)
    if path.stat().st_size != row['received_bytes']:
        # A crash between write and commit leaves extra bytes; trust only committed progress.
        with open(path, 'r+b') as handle:
            handle.truncate(row['received_bytes'])
    with open(path, 'ab') as handle:
        handle.write(body)
    row.update(received_bytes=row['received_bytes'] + len(body), updated_at=store.now())
    store.field.save('media_uploads', row)
    return upload_view(row)


@upload_router.put('/api/v1/media/uploads/{id}', response_model=MediaUpload,
                   openapi_extra={'requestBody': {'required': True, 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
async def upload_chunk(id: str, request: Request, offset: int = Query(ge=0)):
    with store.locked_state():
        limit = store.state['settings']['media_chunk_bytes']
    body = await read_body(request, limit)
    return await asyncio.to_thread(locked_field, write_chunk, id, offset, body)


def finish(row, media_item, principal):
    item = media_logic.view(media_item, principal)
    return dict(upload=upload_view(row), media=item, purge_local_copy=media_logic.restricted(media_item))


@router.post('/api/v1/media/uploads/{id}/complete', response_model=MediaUploadResult)
def complete_upload(id: str):
    principal, row = own_upload(id)
    if row['status'] == 'complete':
        return finish(row, store.field.get('media', row['media_id']), principal)
    if row['status'] != 'open':
        raise HTTPException(409, dict(code='upload_closed', message='آپلود بسته شده است'))
    if row['received_bytes'] != row['size']:
        raise HTTPException(409, dict(code='upload_incomplete',
                                      message=f"آپلود ناقص است؛ {row['received_bytes']} از {row['size']} بایت"))
    path = media_logic.upload_path(id)
    stamp = store.now()
    if media_logic.sha256_file(path) != row['sha256']:
        path.unlink(missing_ok=True)
        row.update(status='failed', updated_at=stamp)
        store.field.save('media_uploads', row)
        store.audit('رد رسانه به‌دلیل ناسازگاری هش', id)
        # Return rather than raise so the failed state and audit commit with this transaction.
        return JSONResponse({'detail': {'code': 'hash_mismatch', 'message': 'هش رسانه با مقدار اعلام‌شده سازگار نیست'}},
                            status_code=422)
    tour = store.field.get('tour', row['tour_id'])
    device = store.field.device(row['device_id'])
    payload = FieldMediaInput(tour_id=row['tour_id'], caption=row['caption'], media_type=row['media_type'],
                              report_id=row['report_id'])
    item = media_record(payload, tour, device, row['station_id'], row['category'], row['created_at'])
    item.update(status='stored', content_type=row['content_type'], size=row['size'], sha256=row['sha256'],
                server_received_at=stamp)
    os.replace(path, media_logic.object_path(item['id']))
    store.field.save('media', item)
    row.update(status='complete', media_id=item['id'], updated_at=stamp)
    store.field.save('media_uploads', row)
    store.audit('ثبت رسانه با زنجیره حفاظت ادله', item['id'], f"sha256={row['sha256']}; device={row['device_id']}")
    return finish(row, item, principal)


def write_single(id, sha256, content_type, body):
    principal = authz.require('read')
    item = store.field.get('media', id)
    if item is None or item['owner_sub'] != principal.sub or 'guard' not in principal.roles:
        raise HTTPException(404, 'رسانه پیدا نشد')
    if content_type not in MEDIA_CONTENT_TYPES[item['media_type']]:
        raise HTTPException(415, dict(code='media_type_denied', message='نوع محتوا با نوع رسانه سازگار یا مجاز نیست'))
    digest = hashlib.sha256(body).hexdigest()
    if item['status'] != 'metadata':
        if item['sha256'] == digest:
            return media_logic.view(item, principal)
        raise HTTPException(409, 'محتوای رسانه قبلاً ثبت شده است')
    if digest != sha256:
        store.audit('رد رسانه به‌دلیل ناسازگاری هش', id)
        raise HTTPException(422, dict(code='hash_mismatch', message='هش رسانه با مقدار اعلام‌شده سازگار نیست'))
    temporary = media_logic.upload_path('single-' + id)
    temporary.write_bytes(body)
    os.replace(temporary, media_logic.object_path(id))
    item.update(status='stored', content_type=content_type, size=len(body), sha256=digest, server_received_at=store.now())
    store.field.save('media', item)
    store.audit('ثبت رسانه کوچک با زنجیره حفاظت ادله', id, f'sha256={digest}')
    return media_logic.view(item, principal)


@upload_router.put('/api/v1/media/{id}/content', response_model=FieldMedia,
                   openapi_extra={'requestBody': {'required': True, 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
async def upload_single(id: str, request: Request, sha256: str = Query(pattern=r'^[0-9a-f]{64}$')):
    with store.locked_state():
        limit = store.state['settings']['media_single_upload_max_bytes']
    body = await read_body(request, limit)
    content_type = request.headers.get('content-type', '').split(';')[0].strip()
    return await asyncio.to_thread(locked_field, write_single, id, sha256, content_type, body)


def media_item(id):
    principal = authz.require('read')
    item = store.field.get('media', id)
    if item is None or not media_logic.may_view(principal, item):
        raise HTTPException(404, 'رسانه پیدا نشد')
    return principal, item


@router.get('/api/v1/media/{id}/content', response_class=Response,
            responses={200: {'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
def media_content(id: str):
    principal, item = media_item(id)
    if not media_logic.may_read_content(principal, item):
        raise HTTPException(403, dict(code='media_access_denied', message='دسترسی به محتوای این رسانه مجاز نیست'))
    store.audit('مشاهده محتوای رسانه میدانی', id, item.get('category') or '')
    return Response(media_logic.object_path(id).read_bytes(), media_type=item['content_type'],
                    headers={'Cache-Control': 'no-store', 'Content-Disposition': 'inline',
                             'X-Content-SHA256': item['sha256']})


@router.post('/api/v1/media/{id}/attach', response_model=FieldMedia)
def attach_media(id: str, payload: MediaAttachInput):
    security_staff()
    principal, item = media_item(id)
    store.lookup('incidents', payload.incident_id)
    if item['status'] != 'stored':
        raise HTTPException(409, 'فقط رسانه ثبت‌شده و موجود پیوست پرونده می‌شود')
    if item.get('incident_id') not in (None, payload.incident_id):
        raise HTTPException(409, 'رسانه قبلاً پیوست پرونده دیگری شده است')
    item.update(incident_id=payload.incident_id, legal_hold=True)
    store.field.save('media', item)
    store.audit('پیوست رسانه به پرونده و نگهداری قانونی', id, payload.incident_id)
    return media_logic.view(item, principal)


@router.post('/api/v1/media/{id}/legal-hold', response_model=FieldMedia)
def legal_hold(id: str, payload: LegalHoldInput):
    staff = security_staff()
    if not set(staff.roles) & media_logic.RESTRICTED_VIEWERS:
        raise HTTPException(403, 'تغییر نگهداری قانونی به مدیر حراست نیاز دارد')
    principal, item = media_item(id)
    if not payload.hold and item.get('incident_id'):
        raise HTTPException(409, 'رسانه پیوست پرونده تا بسته شدن نگهداری قانونی دارد')
    if item['status'] == 'purged':
        raise HTTPException(409, 'رسانه پس از پایان نگهداری حذف شده است')
    item['legal_hold'] = payload.hold
    store.field.save('media', item)
    store.audit('اعمال نگهداری قانونی' if payload.hold else 'رفع نگهداری قانونی', id, payload.reason)
    return media_logic.view(item, principal)

