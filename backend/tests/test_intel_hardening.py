"""Phase seven hardening: headers, rate limits, body ceiling, strict inputs, safe errors, realm baseline."""
import copy
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core import store
from app.core.fieldstore import canonical
from app.main import app
from test_auth_access import bearer
from test_intel_field_safety import setup_field

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings(client, **changes):
    current = client.get('/api/v1/settings').json()
    current.update(changes)
    assert client.put('/api/v1/settings', json=current).status_code == 200


def test_security_headers_and_strict_csp(field_database):
    with TestClient(app) as client:
        headers = client.get('/api/v1/health').headers
        assert headers['strict-transport-security'] == 'max-age=31536000'
        assert headers['x-content-type-options'] == 'nosniff' and headers['referrer-policy'] == 'no-referrer'
        assert headers['x-frame-options'] == 'DENY'
        policy = headers['permissions-policy']
        assert all(f'{feature}=(self)' in policy for feature in ('camera', 'microphone', 'geolocation', 'nfc'))
        assert 'payment=()' in policy
        csp = headers['content-security-policy']
        assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp and 'http' not in csp.split('connect-src')[0]


def test_rate_limits_reject_but_never_drop_emergency(field_database, token_factory, monkeypatch):
    current = {'time': '2026-10-10T00:00:00+00:00'}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        settings(client, rate_limit_per_minute=dict(enroll=2, pin=10, scan=60, upload=600, emergency=1))
        attacker = bearer(token_factory(sub='guard-x', roles=['guard']))
        codes = [client.post('/api/v1/devices/enroll', headers=attacker, json=dict(code='w' * 43, label='x')).status_code
                 for _ in range(3)]
        assert codes[:2] == [403, 403] and codes[2] == 429
        limited = client.post('/api/v1/devices/enroll', headers=attacker, json=dict(code='w' * 43, label='x'))
        assert limited.json()['detail']['code'] == 'rate_limited' and int(limited.headers['retry-after']) >= 1
        current['time'] = '2026-10-10T00:01:00+00:00'
        assert client.post('/api/v1/devices/enroll', headers=attacker, json=dict(code='w' * 43, label='x')).status_code == 403

        device = store.field.device(guard['X-Device-Id'])
        receipts = []
        for index in range(3):
            record = dict(kind='sos', device_id=device['id'], client_id=f'sos-{index}', captured_at=current['time'],
                          previous_device_time=None,
                          payload=dict(tour_id=tour['id'], type='sos', client_id=f'sos-{index}'))
            record['signature'] = hmac.new(device['device_secret'].encode(), canonical(record).encode(), hashlib.sha256).hexdigest()
            response = client.post('/api/v1/tour/offline/emergency', json=record, headers={'Authorization': ''})
            assert response.status_code == 201, response.text
            receipts.append(response.json()['id'])
        flags = [store.field.get('field_safety_events', id)['rate_flagged'] for id in receipts]
        assert flags == [False, True, True]
        actions = [a['action'] for a in store.field.audits()]
        assert actions.count('اعلام خطر فراتر از نرخ مجاز؛ پذیرفته و پرچم شد') == 1
        assert actions.count('رد درخواست فراتر از نرخ مجاز') == 1


def test_body_ceiling_strict_inputs_and_sanitized_errors(field_database, monkeypatch):
    with TestClient(app) as client:
        settings(client, max_json_body_bytes=65536)
        big = client.post('/api/v1/assistant', content=b'{"question": "' + b'x' * 70000 + b'"}',
                          headers={'Content-Type': 'application/json'})
        assert big.status_code == 413 and big.json()['detail']['code'] == 'body_too_large'
        extra = client.post('/api/v1/assistant', json=dict(question='وضعیت جاری چیست؟', injected='/etc/passwd'))
        assert extra.status_code == 422
        detail = extra.json()['detail']
        assert detail[0]['type'] == 'extra_forbidden' and '/etc/passwd' not in extra.text
        assert set(detail[0]) == {'loc', 'msg', 'type'}

        def explode(*args, **kwargs):
            raise RuntimeError('/srv/sepehr/backend/app/store.py secret stack detail')
        import app.main as main_module
        monkeypatch.setattr(main_module, 'summary', explode)
        failed = client.get('/api/v1/analytics')
        assert failed.status_code == 500 and failed.json() == {'detail': {'code': 'internal_error', 'message': 'خطای داخلی سرویس'}}
        assert 'store.py' not in failed.text and 'Traceback' not in failed.text


def test_every_request_body_model_forbids_unknown_fields():
    import typing
    from fastapi.routing import APIRoute
    from pydantic import BaseModel

    def walk(kind, found):
        if isinstance(kind, type) and issubclass(kind, BaseModel):
            if kind not in found:
                found.add(kind)
                for field in kind.model_fields.values():
                    walk(field.annotation, found)
        else:
            for argument in typing.get_args(kind):
                walk(argument, found)
    models = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.body_field:
            walk(route.body_field.type_, models)
    assert models and all(model.model_config.get('extra') == 'forbid' for model in models), \
        sorted(m.__name__ for m in models if m.model_config.get('extra') != 'forbid')


def test_realm_baseline_checker_and_dependency_inventory(tmp_path):
    checker = script('check_keycloak_realm')
    realm = json.loads((ROOT / 'deploy/keycloak/realm-sepehr.json').read_text(encoding='utf-8'))
    assert not [r for r in checker.check(realm, version='26.7.4') if r['status'] == 'fail']
    weak = copy.deepcopy(realm)
    weak.update(registrationAllowed=True, bruteForceProtected=False, adminEventsEnabled=False, accessTokenLifespan=3600)
    weak['clients'][0].update(directAccessGrantsEnabled=True, redirectUris=['https://app.example/*'], attributes={})
    weak['clients'][1]['secret'] = 'leaked'
    failed = {r['check'] for r in checker.check(weak, version='26.7.4', advisories=[dict(id='ADV-1', fixed_in='26.8.0')])
              if r['status'] == 'fail'}
    assert {'registration_disabled', 'brute_force_detection', 'admin_events', 'access_token_lifespan',
            'sepehr-web:direct_access_grants', 'sepehr-web:redirectUris_no_wildcard', 'sepehr-web:pkce_s256',
            'no_embedded_secrets', 'advisory:ADV-1'} <= failed
    path = tmp_path / 'weak.json'
    path.write_text(json.dumps(weak), encoding='utf-8')
    assert checker.main([str(path), '--keycloak-version', '26.7.4', '--json']) == 1
    rows = script('dependency_inventory').inventory()
    assert {'ecosystem': 'pypi', 'name': 'fastapi', 'version': '0.115.12'}.items() <= next(r for r in rows if r['name'] == 'fastapi').items()
    assert any(r['name'] == 'react' and r['scope'] == 'runtime' and r['version'] for r in rows)
    assert all(r['version'] and r['version'] != 'UNPINNED' for r in rows)
