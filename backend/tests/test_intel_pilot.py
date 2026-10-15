"""Phase seven pilot measurement: device capability reports and computed pilot indicators."""
from fastapi.testclient import TestClient

from app.core import store
from app.main import app
from test_auth_access import bearer
from test_intel_field_safety import setup_field
from test_intel_supervision import SCOPE, at, scenario, scan


def test_capability_reports_and_pilot_metrics(field_database, token_factory, monkeypatch):
    current = {'time': at(9)}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        device_id = guard['X-Device-Id']
        report = dict(barcode_detector=True, web_nfc=False, wake_lock=True, device_motion=True, battery_level=0.9,
                      charging=False, auth_refresh_ok=3, auth_refresh_failed=1, platform='Android')
        assert client.post(f'/api/v1/devices/{device_id}/capabilities', headers=guard, json=report).status_code == 201
        current['time'] = at(11)
        assert client.post(f'/api/v1/devices/{device_id}/capabilities', headers=guard,
                           json={**report, 'battery_level': 0.7, 'auth_refresh_ok': 1, 'auth_refresh_failed': 0}).status_code == 201
        assert client.post('/api/v1/devices/OTHER/capabilities', headers=guard, json=report).status_code == 403
        assert client.post(f'/api/v1/devices/{device_id}/capabilities', headers=guard, json={**report, 'lat': 1}).status_code == 422

        scenario()
        scan('SCAN-H', 'S1', trust='high', received=at(7), )
        store.field.save('field_safety_events', dict(id='SAFE-A', tour_id='TOUR-A', guard_id='AST-009', owner_sub='guard-a',
                                                     device_id='DEV-1', type='sos', created_at=at(8), operator_ack_at=at(8, 0).replace(':00:00+', ':00:30+'),
                                                     escalation='operator', **SCOPE))
        store.field.save('field_safety_events', dict(id='SAFE-B', tour_id='TOUR-A', guard_id='AST-009', owner_sub='guard-a',
                                                     device_id='DEV-1', type='man_down', created_at=at(8, 30), operator_ack_at=None,
                                                     escalation='operator', **SCOPE))
        current['time'] = at(12)
        result = client.get('/api/v1/reports/pilot', params=dict(window_from=at(0), window_to=at(12)))
        assert result.status_code == 200, result.text
        metrics = {m['key']: m for m in result.json()['metrics']}
        assert metrics['trust_high_ratio']['value'] == round(100 / 3, 3) and metrics['trust_high_ratio']['samples'] == 3
        assert metrics['alarm_ack_median']['value'] == 30 and metrics['alarm_unacked']['value'] == 1
        assert metrics['missed_not_visited']['value'] == 40 and metrics['suspended_emergency']['value'] == 20
        assert metrics['battery_drain']['value'] == 10 and metrics['token_refresh_success']['value'] == 80
        assert metrics['barcode_detector']['value'] == 100 and metrics['web_nfc']['value'] == 0
        assert all(m['method'] for m in metrics.values()) and result.json()['manual_measurements']
        assert 'خروجی شاخص‌های پایلوت' in [a['action'] for a in store.field.audits()]
        assert client.get('/api/v1/reports/pilot', headers=guard).status_code == 403
        assert client.get('/api/v1/reports/pilot', headers=bearer(token_factory(sub='sup', roles=['shift_supervisor']))).status_code == 200
