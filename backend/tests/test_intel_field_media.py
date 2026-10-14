"""Phase five: messages, resumable media custody and categorised field reports."""
import hashlib
import hmac

from fastapi.testclient import TestClient

from app import field_media, store
from app.fieldstore import canonical
from app.main import app
from app.intel import worker
from test_auth_access import bearer, link_and_enroll
from test_intel_field_safety import setup_field

T0 = '2026-10-10T00:00:00+00:00'


def clocked(monkeypatch, value=T0):
    current = {'time': value}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    return current


def allow_images(client):
    assert client.put('/api/v1/tour/zones/Z1', json=dict(name='محوطه شماتیک',
        points=[[0, 0], [2, 0], [2, 2], [0, 2]], media_capture_allowed=True)).status_code == 200


def report(client, guard, tour, category='security', client_id='rep-1', **changes):
    payload = dict(tour_id=tour['id'], category=category, text='گزارش شماتیک میدانی', client_id=client_id)
    payload.update(changes)
    return client.post('/api/v1/tour/reports', headers=guard, json=payload)


def start(client, guard, tour, body, client_id='up-1', media_type='image', content_type='image/jpeg', **changes):
    payload = dict(tour_id=tour['id'], caption='تصویر شماتیک', media_type=media_type, content_type=content_type,
                   sha256=hashlib.sha256(body).hexdigest(), size=len(body), client_id=client_id)
    payload.update(changes)
    return client.post('/api/v1/media/uploads', headers=guard, json=payload)


def put(client, guard, upload_id, offset, body):
    return client.put(f'/api/v1/media/uploads/{upload_id}?offset={offset}', headers=guard, content=body)


def test_jalali_is_pure_and_tehran_based():
    assert field_media.jalali(2026, 3, 21) == (1405, 1, 1)
    assert field_media.jalali(2026, 10, 14) == (1405, 7, 22)
    assert field_media.jalali(2024, 3, 20) == (1403, 1, 1)
    assert field_media.jalali_stamp('2026-10-13T21:00:00+00:00') == '1405/07/22 00:30'


def test_chunked_upload_order_resume_hash_and_custody(field_database, token_factory, monkeypatch):
    clocked(monkeypatch)
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        allow_images(client)
        client.put('/api/v1/settings', json={**client.get('/api/v1/settings').json(), 'media_chunk_bytes': 16384})
        body = bytes(range(256)) * 160
        created = start(client, guard, tour, body)
        assert created.status_code == 201, created.text
        upload = created.json()
        assert start(client, guard, tour, body).json()['id'] == upload['id']
        assert start(client, guard, tour, body + b'x').status_code == 409
        assert put(client, guard, upload['id'], 16384, body[16384:32768]).status_code == 409
        assert put(client, guard, upload['id'], 0, body[:16385]).status_code == 413
        assert put(client, guard, upload['id'], 0, body[:16384]).json()['received_bytes'] == 16384
        assert put(client, guard, upload['id'], 0, body[:16384]).json()['detail']['code'] == 'upload_offset_mismatch'
        status = client.get(f"/api/v1/media/uploads/{upload['id']}", headers=guard).json()
        assert status['received_bytes'] == 16384 and status['status'] == 'open'
        assert client.post(f"/api/v1/media/uploads/{upload['id']}/complete", headers=guard).status_code == 409
        for offset in range(status['received_bytes'], len(body), 16384):
            assert put(client, guard, upload['id'], offset, body[offset:offset + 16384]).status_code == 200
        done = client.post(f"/api/v1/media/uploads/{upload['id']}/complete", headers=guard)
        assert done.status_code == 200, done.text
        media = done.json()['media']
        assert media['status'] == 'stored' and media['sha256'] == hashlib.sha256(body).hexdigest()
        assert media['server_received_at'] == T0 and media['device_id'] == guard['X-Device-Id']
        assert done.json()['purge_local_copy'] is False
        assert media['watermark']['guard_code'] == 'AST-009' and media['watermark']['captured_at_jalali'] == '1405/07/18 03:30'
        content = client.get(f"/api/v1/media/{media['id']}/content", headers=guard)
        assert content.content == body and content.headers['cache-control'] == 'no-store'
        assert client.post(f"/api/v1/media/uploads/{upload['id']}/complete", headers=guard).json()['media']['id'] == media['id']
        other, _ = link_and_enroll(client, token_factory, sub='guard-b', guard_id='AST-010')
        assert client.get(f"/api/v1/media/{media['id']}/content", headers=other).status_code == 404
        assert client.get(f"/api/v1/media/uploads/{upload['id']}", headers=other).status_code == 404

        bad = start(client, guard, tour, b'original', client_id='up-bad')
        put(client, guard, bad.json()['id'], 0, b'tampered')
        rejected = client.post(f"/api/v1/media/uploads/{bad.json()['id']}/complete", headers=guard)
        assert rejected.status_code == 422 and rejected.json()['detail']['code'] == 'hash_mismatch'
        assert client.get(f"/api/v1/media/uploads/{bad.json()['id']}", headers=guard).json()['status'] == 'failed'
        actions = [a['action'] for a in store.field.audits()]
        assert 'ثبت رسانه با زنجیره حفاظت ادله' in actions and 'رد رسانه به‌دلیل ناسازگاری هش' in actions
        assert store.field.verify_audit()


def test_capture_policy_single_put_and_content_types(field_database, token_factory, monkeypatch):
    clocked(monkeypatch)
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)  # zone media_capture_allowed=False
        policy = client.get(f"/api/v1/media/capture-policy?tour_id={tour['id']}", headers=guard).json()
        assert policy['image_video_allowed'] is False and policy['audio_allowed'] is True
        image = start(client, guard, tour, b'img')
        assert image.status_code == 403 and image.json()['detail']['code'] == 'media_capture_denied'
        assert start(client, guard, tour, b'v', media_type='video', content_type='video/webm').status_code == 403
        assert start(client, guard, tour, b'a', media_type='audio', content_type='image/png').status_code == 422
        audio = client.post('/api/v1/media', headers=guard, json=dict(tour_id=tour['id'], caption='صوت', media_type='audio')).json()
        assert audio['status'] == 'metadata'
        path = f"/api/v1/media/{audio['id']}/content?sha256=" + hashlib.sha256(b'voice').hexdigest()
        assert client.put(path, headers={**guard, 'Content-Type': 'image/png'}, content=b'voice').status_code == 415
        assert client.put(path, headers={**guard, 'Content-Type': 'audio/webm'}, content=b'other').status_code == 422
        stored = client.put(path, headers={**guard, 'Content-Type': 'audio/webm'}, content=b'voice')
        assert stored.status_code == 200 and stored.json()['status'] == 'stored'
        assert client.put(path, headers={**guard, 'Content-Type': 'audio/webm'}, content=b'voice').status_code == 200
        settings = client.get('/api/v1/settings').json()
        client.put('/api/v1/settings', json={**settings, 'media_single_upload_max_bytes': 1024})
        large = client.post('/api/v1/media', headers=guard, json=dict(tour_id=tour['id'], caption='بزرگ', media_type='audio')).json()
        big = b'x' * 2048
        assert client.put(f"/api/v1/media/{large['id']}/content?sha256=" + hashlib.sha256(big).hexdigest(),
                          headers={**guard, 'Content-Type': 'audio/webm'}, content=big).status_code == 413


def test_restricted_reports_routing_access_export_and_legal_hold(field_database, token_factory, monkeypatch):
    current = clocked(monkeypatch)
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        allow_images(client)
        assert report(client, guard, tour, category='damage').status_code == 422
        damage = report(client, guard, tour, category='damage', safety_acknowledged=True)
        assert damage.status_code == 201, damage.text
        row = damage.json()
        assert row['restricted'] and row['purge_local_media'] and row['safety_instruction'] == 'نزدیک نشو، از فاصله امن گزارش کن'
        assert row['can_execute'] is False
        assert report(client, guard, tour, category='damage', safety_acknowledged=True).json()['id'] == row['id']
        assert report(client, guard, tour, category='security', safety_acknowledged=True).status_code == 409
        hse = report(client, guard, tour, category='safety_hse', client_id='rep-hse').json()
        assert hse['audiences'] == ['security', 'hse', 'operations']
        assert [r['id'] for r in client.get('/api/v1/tour/reports?audience=hse').json()] == [hse['id']]
        assert client.post(f"/api/v1/tour/reports/{hse['id']}/ack", json=dict(audience='hse')).json()['acknowledgements'][0]['audience'] == 'hse'
        assert client.post(f"/api/v1/tour/reports/{row['id']}/ack", json=dict(audience='hse')).status_code == 422

        body = b'damage-photo'
        upload = start(client, guard, tour, body, client_id='dmg', report_id=row['id']).json()
        put(client, guard, upload['id'], 0, body)
        done = client.post(f"/api/v1/media/uploads/{upload['id']}/complete", headers=guard).json()
        media_id = done['media']['id']
        assert done['purge_local_copy'] is True and done['media']['category'] == 'damage' and done['media']['exportable'] is False
        assert client.get(f"/api/v1/media/{media_id}/content", headers=guard).status_code == 403
        officer = bearer(token_factory(sub='officer', roles=['security_officer']))
        assert media_id not in [m['id'] for m in client.get('/api/v1/media', headers=officer).json()]
        assert client.get(f"/api/v1/media/{media_id}/content", headers=officer).status_code == 404
        manager = bearer(token_factory(sub='manager', roles=['security_manager']))
        assert client.get(f"/api/v1/media/{media_id}/content", headers=manager).content == body
        denied = client.post('/api/v1/exports', headers=manager, json=dict(name='رسانه', media_id=media_id))
        assert denied.status_code == 403 and denied.json()['detail']['code'] == 'media_export_denied'
        assert media_id in client.get(f"/api/v1/tour/reports", headers=manager).json()[0]['media_ids']

        normal = start(client, guard, tour, b'normal', client_id='keep').json()
        put(client, guard, normal['id'], 0, b'normal')
        kept = client.post(f"/api/v1/media/uploads/{normal['id']}/complete", headers=guard).json()['media']['id']
        attached = client.post(f'/api/v1/media/{kept}/attach', json=dict(incident_id='INC-824'))
        assert attached.status_code == 200 and attached.json()['legal_hold'] is True
        assert client.post(f'/api/v1/media/{kept}/legal-hold', json=dict(hold=False, reason='آزمایش رفع')).status_code == 409
        assert client.post(f'/api/v1/media/{media_id}/legal-hold', headers=officer, json=dict(hold=True, reason='آزمایش')).status_code == 403
        current['time'] = '2028-12-01T00:00:00+00:00'
        worker.tick(current['time'])
        assert store.field.get('media', media_id)['status'] == 'purged'
        assert not field_media.object_path(media_id).exists()
        assert store.field.get('media', kept)['status'] == 'stored' and field_media.object_path(kept).exists()
        assert 'حذف رسانه پس از پایان دوره نگهداری' in [a['action'] for a in store.field.audits()]


def test_urgent_messages_broadcast_receipts_and_escalation(field_database, token_factory, monkeypatch):
    current = clocked(monkeypatch)
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        assert client.post('/api/v1/messages', json=dict(text='بدون مخاطب')).status_code == 422
        assert client.post('/api/v1/messages', headers=guard, json=dict(text='x', audience=dict(guard_id='AST-009'))).status_code == 422
        direct = client.post('/api/v1/messages', json=dict(text='فوری: به ایستگاه بازگردید', priority='urgent',
                                                           audience=dict(guard_id='AST-009')))
        assert direct.status_code == 201, direct.text
        broadcast = client.post('/api/v1/messages', json=dict(text='اعلان اضطراری محوطه', priority='urgent',
                                                              audience=dict(broadcast_zone='Z1', contractor_id='SCHEMATIC'))).json()
        assert [r['guard_id'] for r in broadcast['recipients']] == ['AST-009']
        inbox = client.get('/api/v1/messages', headers=guard).json()
        assert {m['id'] for m in inbox} == {direct.json()['id'], broadcast['id']}
        current['time'] = '2026-10-10T00:02:00+00:00'
        worker.tick(current['time'])
        assert store.field.get('messages', direct.json()['id'])['escalation'] == 'shift_supervisor'
        current['time'] = '2026-10-10T00:04:00+00:00'
        assert client.get('/api/v1/messages').json()[0]['escalation'] == 'security_officer'
        acked = client.post(f"/api/v1/messages/{direct.json()['id']}/ack", headers=guard)
        assert acked.json()['recipients'][0]['acknowledged_at'] == current['time'] and acked.json()['escalation'] == 'operator'
        assert client.post(f"/api/v1/messages/{broadcast['id']}/ack").status_code == 409
        to_center = client.post('/api/v1/messages', headers=guard, json=dict(tour_id=tour['id'], text='نیاز به پشتیبانی')).json()
        assert to_center['direction'] == 'to_center' and to_center['escalation'] == 'operator'
        assert client.post(f"/api/v1/messages/{to_center['id']}/ack").json()['center_ack_at'] == current['time']
        other, _ = link_and_enroll(client, token_factory, sub='guard-b', guard_id='AST-010')
        assert client.get('/api/v1/messages', headers=other).json() == []
        assert client.post(f"/api/v1/messages/{direct.json()['id']}/ack", headers=other).status_code == 404
        assert 'تشدید پیام فوری بی‌رسید' in [a['action'] for a in store.field.audits()]


def test_signed_offline_report_flags(field_database, token_factory, monkeypatch):
    clocked(monkeypatch, '2026-10-10T05:00:00+00:00')
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        device = store.field.device(guard['X-Device-Id'])
        record = dict(kind='report', device_id=device['id'], client_id='off-rep', captured_at='2026-10-10T01:00:00+00:00',
                      previous_device_time='2026-10-10T01:30:00+00:00',
                      payload=dict(tour_id=tour['id'], category='uxo', text='شیء مشکوک در حاشیه جاده',
                                   client_id='off-rep', safety_acknowledged=True))
        record['signature'] = hmac.new(device['device_secret'].encode(), canonical(record).encode(), hashlib.sha256).hexdigest()
        accepted = client.post('/api/v1/tour/offline/reports', headers=guard, json=record)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()['offline_too_long'] and accepted.json()['clock_regressed']
        assert accepted.json()['audiences'] == ['security', 'hse']
        assert client.post('/api/v1/tour/offline/reports', headers=guard, json={**record, 'signature': '0' * 64}).status_code == 403
