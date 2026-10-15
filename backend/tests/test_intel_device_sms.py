"""SMS command rendering for tracker protocol families; no gateway, password never recorded."""
from fastapi.testclient import TestClient

from app.core import store
from app.field import device_profiles
from app.main import app


def test_profile_templates():
    gt06 = dict(device_profile='concox_gt06')
    assert device_profiles.render(gt06, 'interval', 30) == 'TIMER,30#'
    assert device_profiles.render(gt06, 'restart', 30) == 'RESET#'
    tk103 = dict(device_profile='coban_tk103')
    assert device_profiles.render(tk103, 'interval', 30, masked=False) == 'fix030s***n123456'
    assert device_profiles.render(tk103, 'interval', 600, masked=False) == 'fix010m***n123456'
    assert device_profiles.render({**tk103, 'sms_password': '654321'}, 'ping', 30) == 'imei••••'
    assert device_profiles.render(dict(device_profile='teltonika_fmb'), 'position', 30) == '  getgps'


def test_sms_command_preview_validation_and_masking(field_database):
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        assert {p['id'] for p in client.get('/api/v1/device-profiles').json()} >= {'concox_gt06', 'coban_tk103', 'teltonika_fmb'}
        settings = dict(carrier='رایتل', sim='0920 000 0001', report_interval=30, device_profile='coban_tk103',
                        sms_password='246810')
        updated = client.patch('/api/v1/assets/AST-001/settings', json=settings).json()
        assert updated['sms_password_set'] and 'sms_password' not in updated and updated['carrier'] == 'رایتل'
        preview = client.get('/api/v1/commands/preview?asset_id=AST-001&command=interval&interval_seconds=60').json()
        assert preview['sms_text'] == 'fix060s***n••••' and preview['sms_destination'] == '0920 000 0001'
        assert preview['gateway'] == 'none'
        assert client.get('/api/v1/commands/preview?asset_id=AST-001&command=interval&interval_seconds=3601').status_code == 422
        assert client.get('/api/v1/commands/preview?asset_id=AST-001&command=interval&interval_seconds=301').status_code == 422
        assert client.post('/api/v1/commands', json=dict(asset_id='AST-001', command='beacon', channel='sms',
                                                         request_id='b1')).status_code == 422
        sent = client.post('/api/v1/commands', json=dict(asset_id='AST-001', command='position', channel='sms',
                                                         request_id='p1')).json()
        assert sent['sms_text'] == 'fix010s001n••••' and sent['mock'] is True
        assert '246810' not in str(store.state['commands']) and '246810' not in str(store.field.audits())
        data = client.post('/api/v1/commands', json=dict(asset_id='AST-001', command='beacon', channel='data',
                                                         request_id='b2')).json()
        assert data['sms_text'] is None and data['device_profile'] == 'coban_tk103'
