"""Signed offline queue, emergency auth fallback and delayed scan evidence."""
import hashlib
import hmac

from fastapi.testclient import TestClient

from app import store, tour
from app.fieldstore import canonical
from app.main import app
from app.models import SignedQueueRecord
from test_auth_access import bearer
from test_intel_field_safety import setup_field, station


def signed(kind, device_id, client_id, captured_at, payload, previous_device_time=None):
    row = dict(kind=kind, device_id=device_id, client_id=client_id, captured_at=captured_at,
               previous_device_time=previous_device_time, payload=payload)
    secret = store.field.device(device_id)['device_secret']
    canonical_record = SignedQueueRecord.model_validate({**row, 'signature': '0' * 64})
    body = canonical(canonical_record.model_dump(mode='json', exclude={'signature'}))
    row['signature'] = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return row


def test_signed_scan_offline_flags_and_invalid_signature(field_database, token_factory, monkeypatch):
    current = {'time': '2026-10-10T02:01:00+00:00'}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, active = setup_field(client, token_factory)
        device_id = guard['X-Device-Id']
        station_row, code = station(client)
        captured = '2026-10-10T00:00:00+00:00'
        payload = dict(station_id=station_row['id'], tour_id=active['id'], payload=code,
                       lon=1, lat=1, accuracy_m=5, device_time=captured,
                       previous_device_time='2026-10-10T00:01:00+00:00', client_id='offline-scan-1')
        row = signed('scan', device_id, 'offline-scan-1', captured, payload,
                     previous_device_time=payload['previous_device_time'])
        invalid = {**row, 'signature': '0' * 64}
        assert client.post('/api/v1/tour/offline/scans', headers=guard, json=invalid).status_code == 403
        assert any(a['action'] == 'رد امضای رکورد آفلاین' for a in field_database.audits())
        response = client.post('/api/v1/tour/offline/scans', headers=guard, json=row)
        assert response.status_code == 201, response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['offline_flags'] == ['offline_too_long', 'clock_regressed']
        scan = client.get('/api/v1/tour/scans', headers=guard).json()[0]
        assert scan['evidence']['clock'] == 'regressed'
        assert scan['offline_flags'] == ['offline_too_long', 'clock_regressed']
        assert client.post('/api/v1/tour/offline/scans', headers=guard, json=row).json()['id'] == response.json()['id']
        assert tour.trust(dict(tag='sun_valid', location='verified', sequence='in_order',
                               dwell='ok', clock='ok'), ['offline_too_long']) == 'medium'
        settings = client.get('/api/v1/settings').json()
        assert settings['offline_pbkdf2_iterations'] >= 100000
        assert settings['offline_shift_grace_minutes'] == 60
        assert field_database.verify_audit()


def test_expired_token_emergency_and_revoked_device(field_database, token_factory, monkeypatch):
    current = {'time': '2026-10-10T00:00:00+00:00'}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, active = setup_field(client, token_factory)
        device_id = guard['X-Device-Id']
        expired = bearer(token_factory(sub='guard-a', roles=['guard'], exp=1))
        payload = dict(tour_id=active['id'], type='sos', client_id='offline-sos-1')
        row = signed('sos', device_id, 'offline-sos-1', current['time'], payload)
        assert client.post('/api/v1/tour/offline/emergency', headers=expired,
                           json={**row, 'signature': '0' * 64}).status_code == 403
        response = client.post('/api/v1/tour/offline/emergency', headers=expired, json=row)
        assert response.status_code == 201, response.text
        assert response.json()['incident_id']
        assert client.post('/api/v1/tour/offline/emergency', headers=expired, json=row).json()['id'] == response.json()['id']
        alerts = client.get('/api/v1/tour/safety-alerts').json()
        assert next(a for a in alerts if a['id'] == response.json()['id'])['auth_expired'] is True
        silent = signed('duress', device_id, 'offline-duress-1', current['time'],
                        dict(tour_id=active['id']))
        assert client.post('/api/v1/tour/offline/emergency', headers=expired, json=silent).status_code == 201
        assert any(a['type'] == 'duress' and a['auth_expired'] for a in client.get('/api/v1/tour/safety-alerts').json())
        assert client.post(f'/api/v1/devices/{device_id}/revoke').status_code == 200
        again = signed('man_down', device_id, 'offline-fall-1', current['time'],
                       dict(tour_id=active['id'], type='man_down', client_id='offline-fall-1', fall_detected=True))
        assert client.post('/api/v1/tour/offline/emergency', headers=expired, json=again).status_code == 403
        assert field_database.verify_audit()


def test_position_batch_reuses_track_ingestion(field_database, token_factory, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T00:00:00+00:00')
    with TestClient(app) as client:
        guard, _ = setup_field(client, token_factory)
        device_id = guard['X-Device-Id']
        point = dict(lon=1, lat=1, time='2026-10-10T00:00:01+00:00', speed=0)
        row = signed('position', device_id, 'offline-pos-1', point['time'], point,
                     previous_device_time='2026-10-10T00:00:02+00:00')
        endpoint = '/api/v1/assets/AST-009/positions:batch'
        response = client.post(endpoint, headers=guard, json=dict(records=[row]))
        assert response.status_code == 201, response.text
        assert response.json()['clock_regressed_client_ids'] == ['offline-pos-1']
        assert client.post(endpoint, headers=guard, json=dict(records=[row])).status_code == 201
        assert store.tracks.read('AST-009', since=point['time'], until=point['time'])[0]['lon'] == 1
        assert client.post('/api/v1/assets/AST-010/positions:batch', headers=guard,
                           json=dict(records=[row])).status_code == 403
