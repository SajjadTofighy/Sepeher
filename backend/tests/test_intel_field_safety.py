"""Field phase-three evidence and safety flows with injected server time."""
from urllib.parse import urlencode
import sqlite3
import pytest
from fastapi.testclient import TestClient

from app import field_safety, store, tour_tags
from app.main import app
from test_auth_access import bearer, link_and_enroll


def setup_field(client, token_factory):
    client.post('/api/v1/demo/reset')
    assert client.put('/api/v1/tour/zones/Z1', json=dict(name='محوطه شماتیک',
        points=[[0, 0], [2, 0], [2, 2], [0, 2]], media_capture_allowed=False,
        emergency_contacts=[dict(name='HSE', role='ایمنی', phone='111')])).status_code == 200
    for guard_id in ('AST-009', 'AST-010'):
        assert client.put(f'/api/v1/guards/{guard_id}/scope', json=dict(zone_id='Z1', contractor_id='SCHEMATIC')).status_code == 200
    headers, _ = link_and_enroll(client, token_factory)
    route = client.post('/api/v1/tour/routes', json=dict(name='مسیر شماتیک', guard_id='AST-009',
        zone_id='Z1', contractor_id='SCHEMATIC')).json()['id']
    response = client.post('/api/v1/tour', headers=headers, json=dict(route_id=route))
    assert response.status_code == 201, response.text
    return headers, response.json()


def station(client, **changes):
    payload = dict(zone_id='Z1', contractor_id='SCHEMATIC', name='ایستگاه شماتیک', sensitivity='حساس',
                   lon=1, lat=1, tag_mode='qr_hmac')
    payload.update(changes)
    response = client.post('/api/v1/tour/stations', json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    code = tour_tags.tag_payload(row)
    if row['tag_mode'] == 'qr_hmac':
        assert client.post(f"/api/v1/tour/stations/{row['id']}/install", json=dict(payload=code, lon=1, lat=1)).status_code == 200
    return row, code


def test_scan_evidence_clock_manual_review_and_scope(field_database, token_factory, monkeypatch):
    current = {'time': '2026-10-10T00:00:00+00:00'}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        row, code = station(client)
        path = f"/api/v1/tour/stations/{row['id']}/visits"
        scan = dict(tour_id=tour['id'], payload=code, lon=1, lat=1, accuracy_m=5,
                    device_time=current['time'], anchor_server_time=current['time'],
                    anchor_device_time=current['time'], client_id='scan-1')
        response = client.post(path, headers=guard, json=scan)
        assert response.status_code == 201, response.text
        assert response.headers['x-server-time'] == current['time']
        assert response.json()['trust_level'] == 'medium'
        record = client.get('/api/v1/tour/scans', headers=guard).json()[0]
        assert record['evidence'] == dict(tag='hmac_valid', location='verified', sequence='in_order',
                                          dwell='ok', clock='ok')
        assert record['trust_level'] == 'medium'
        with pytest.raises(sqlite3.DatabaseError), field_database.connection() as db:
            db.execute("UPDATE scans SET payload='{}' WHERE id=?", (record['id'],))
        assert client.post(path, headers=guard, json=scan).json()['id'] == response.json()['id']
        assert client.post(path, headers=guard, json={**scan, 'accuracy_m': 6}).status_code == 409
        assert client.post(f"/api/v1/tour/station-visits/{response.json()['id']}/complete", headers=guard).status_code == 200
        current['time'] = '2026-10-10T00:01:00+00:00'
        manual = client.post(f"/api/v1/tour/stations/{row['id']}/manual-scan", headers=guard,
            json=dict(tour_id=tour['id'], reason='تگ آسیب دیده است', client_id='manual-1',
                      device_time='2026-10-09T23:59:00+00:00',
                      anchor_server_time='2026-10-10T00:00:00+00:00',
                      anchor_device_time='2026-10-10T00:00:00+00:00'))
        assert manual.status_code == 201, manual.text
        assert manual.json()['evidence']['clock'] == 'regressed'
        assert manual.json()['evidence']['location'] == 'unavailable'
        assert manual.json()['trust_level'] == 'low' and manual.json()['status'] == 'pending_review'
        assert client.get('/api/v1/tour/scans', headers=bearer(token_factory(sub='unlinked', roles=['guard']))).status_code == 403
        second_guard, _ = link_and_enroll(client, token_factory, sub='guard-b', guard_id='AST-010')
        assert client.get('/api/v1/tour/scans', headers=second_guard).json() == []
        reviewed = client.post(f"/api/v1/tour/scans/{manual.json()['id']}/review",
                               json=dict(approved=True, reason='تأیید حضوری سرپرست'))
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()['status'] == 'accepted' and reviewed.json()['visit_id']
        assert client.post(f"/api/v1/tour/station-visits/{reviewed.json()['visit_id']}/complete", headers=guard).status_code == 200
        assert field_database.verify_audit()


def test_duress_sos_escalation_man_down_and_muster(field_database, token_factory, monkeypatch):
    current = {'time': '2026-10-10T00:00:00+00:00'}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        assert client.put('/api/v1/guards/AST-009/credentials', json=dict(pin='123456', duress_pin='654321')).status_code == 200
        normal = client.post(f"/api/v1/tour/{tour['id']}/check-in", headers=guard, json=dict(pin='123456'))
        duress = client.post(f"/api/v1/tour/{tour['id']}/check-in", headers=guard, json=dict(pin='654321'))
        assert normal.status_code == duress.status_code == 201
        assert normal.json().keys() == duress.json().keys()
        unlock = client.post('/api/v1/tour/unlock', headers=guard, json=dict(tour_id=tour['id'], pin='654321'))
        assert unlock.status_code == 200 and unlock.json()['unlocked'] is True
        assert client.get('/api/v1/tour/safety-alerts', headers=guard).status_code == 403
        officer = bearer(token_factory(roles=['security_officer']))
        alerts = client.get('/api/v1/tour/safety-alerts', headers=officer).json()
        assert len([a for a in alerts if a['type'] == 'duress']) == 2
        sos = client.post('/api/v1/tour/safety-events', headers=guard,
                          json=dict(tour_id=tour['id'], type='sos', client_id='sos-1'))
        assert sos.status_code == 201, sos.text
        receipt = sos.json()
        assert receipt['operator_ack_at'] is None and receipt['incident_id']
        assert client.post('/api/v1/tour/safety-events', headers=guard,
                           json=dict(tour_id=tour['id'], type='sos', client_id='sos-1')).json()['id'] == receipt['id']
        assert client.post('/api/v1/tour/safety-events', headers=guard,
                           json=dict(tour_id=tour['id'], type='sos', client_id='sos-1',
                                     motionless_seconds=42)).status_code == 409
        bad = client.post('/api/v1/tour/safety-events', headers=guard,
                          json=dict(tour_id=tour['id'], type='man_down', client_id='fall-0', motionless_seconds=1))
        assert bad.status_code == 422
        fall = client.post('/api/v1/tour/safety-events', headers=guard,
                           json=dict(tour_id=tour['id'], type='man_down', client_id='fall-1', fall_detected=True))
        assert fall.status_code == 201 and fall.json()['incident_id'] is None
        finding = next(f for f in store.state['findings'] if f['rule_id'] == 'intel.field_man_down')
        assert finding['can_execute'] is False and finding['mode'] == 'shadow'
        current['time'] = '2026-10-10T00:02:01+00:00'
        field_safety.tick(current['time'])
        levels = {a['id']: a['escalation'] for a in client.get('/api/v1/tour/safety-alerts', headers=officer).json()}
        assert levels[receipt['id']] == 'security_officer'
        ack = client.post(f"/api/v1/incidents/{receipt['incident_id']}/ack", headers=officer)
        assert ack.status_code == 200, ack.text
        assert client.get(f"/api/v1/tour/safety-events/{receipt['id']}/receipt", headers=guard).json()['operator_ack_at'] == current['time']
        muster = client.post('/api/v1/tour/musters', headers=officer,
                             json=dict(zone_id='Z1', reason='تمرین حضورشماری'))
        assert muster.status_code == 201 and muster.json()['unanswered_guard_ids'] == ['AST-009']
        notice = client.get('/api/v1/tour/musters', headers=guard).json()[0]
        assert 'participants' not in notice and notice['response'] is None
        answer = client.post(f"/api/v1/tour/musters/{muster.json()['id']}/respond", headers=guard,
                             json=dict(response='safe'))
        assert answer.status_code == 200 and answer.json()['response'] == 'safe'
        assert client.get('/api/v1/tour/musters', headers=officer).json()[0]['unanswered_guard_ids'] == []


def test_gps_anomaly_ex_warning_and_overdue_checkin(field_database, token_factory, monkeypatch):
    current = {'time': '2026-10-10T00:00:00+00:00'}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, active = setup_field(client, token_factory)
        first, code = station(client)
        first_visit = client.post(f"/api/v1/tour/stations/{first['id']}/visits", headers=guard,
            json=dict(tour_id=active['id'], payload=code, lon=1, lat=1, accuracy_m=5,
                      device_time=current['time']))
        assert first_visit.status_code == 201
        assert client.post(f"/api/v1/tour/station-visits/{first_visit.json()['id']}/complete", headers=guard).status_code == 200
        second, second_code = station(client, lon=1.5, lat=1.5, hazards=['ex_zone_1'])
        current['time'] = '2026-10-10T00:00:01+00:00'
        second_visit = client.post(f"/api/v1/tour/stations/{second['id']}/visits", headers=guard,
            json=dict(tour_id=active['id'], payload=second_code, lon=1.5, lat=1.5,
                      accuracy_m=5, device_time=current['time']))
        assert second_visit.status_code == 201, second_visit.text
        assert second_visit.json()['trust_level'] == 'low'
        assert second_visit.json()['hazard_flags'] == ['دستگاه فاقد گواهی Ex']
        second_scan = client.get('/api/v1/tour/scans', headers=guard).json()[-1]
        assert second_scan['evidence']['location'] == 'implausible'
        assert client.post(f"/api/v1/tour/station-visits/{second_visit.json()['id']}/complete", headers=guard).status_code == 200
        hazardous, hazardous_code = station(client, hazards=['h2s'])
        denied = client.post(f"/api/v1/tour/stations/{hazardous['id']}/visits", headers=guard,
            json=dict(tour_id=active['id'], payload=hazardous_code))
        assert denied.status_code == 409
        no_gps = client.post(f"/api/v1/tour/stations/{hazardous['id']}/visits", headers=guard,
            json=dict(tour_id=active['id'], payload=hazardous_code, gas_detector_confirmed=True))
        assert no_gps.status_code == 201, no_gps.text
        assert client.get('/api/v1/tour/scans', headers=guard).json()[-1]['evidence']['location'] == 'unavailable'
        settings = client.get('/api/v1/settings').json()
        settings['heat_profile']['checkin_minutes'] = 1
        assert client.put('/api/v1/settings', json=settings).status_code == 200
        current['time'] = '2026-10-10T00:02:00+00:00'
        field_safety.tick(current['time'])
        finding = next(f for f in store.state['findings'] if f['rule_id'] == 'intel.field_checkin')
        assert finding['can_execute'] is False and finding['mode'] == 'shadow'
        assert client.put('/api/v1/guards/AST-009/credentials', json=dict(pin='123456', duress_pin='654321')).status_code == 200
        assert client.post(f"/api/v1/tour/{active['id']}/check-in", headers=guard, json=dict(pin='123456')).status_code == 201
        field_safety.tick(current['time'])
        assert finding['status'] == 'resolved'


def test_replayed_visit_scan_is_recorded_without_acceptance(field_database, token_factory, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T00:00:00+00:00')
    with TestClient(app) as client:
        guard, active = setup_field(client, token_factory)
        row, code = station(client, tag_mode='nfc_counter', tag_uid='04ABCDEF123456')
        def signed(counter):
            return 'https://field.test/nfc?' + urlencode(dict(tag=code, uid=row['tag_uid'], counter=f'{counter:06X}'))
        assert client.post(f"/api/v1/tour/stations/{row['id']}/install",
                           json=dict(payload=signed(1), lon=1, lat=1)).status_code == 200
        path = f"/api/v1/tour/stations/{row['id']}/visits"
        visit = client.post(path, headers=guard,
                            json=dict(tour_id=active['id'], payload=signed(2), lon=1, lat=1))
        assert visit.status_code == 201
        assert client.post(f"/api/v1/tour/station-visits/{visit.json()['id']}/complete", headers=guard).status_code == 200
        replay = client.post(path, headers=guard,
                             json=dict(tour_id=active['id'], payload=signed(2), lon=1, lat=1))
        assert replay.status_code == 403 and replay.json()['detail']['code'] == 'tag_replay'
        rows = client.get('/api/v1/tour/scans', headers=guard).json()
        assert [r['evidence']['tag'] for r in rows] == ['counter_ok', 'replay']
        assert rows[-1]['status'] == 'rejected' and rows[-1]['trust_level'] == 'low'
