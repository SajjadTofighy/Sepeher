"""AFTA security-assessment inquiry evidence: auditor dossier, letter draft and offline package."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from app import store
from app.main import app
from test_auth_access import bearer

ROOT = Path(__file__).resolve().parents[2]


def test_auth_config_exposes_both_public_clients(field_database, monkeypatch):
    monkeypatch.setenv('SEPEHR_OIDC_ISSUER', 'https://identity.test/realms/sepehr')
    with TestClient(app) as client:
        config = client.get('/api/v1/auth/config', headers={'Authorization': ''}).json()
        assert config['client_id'] == 'sepehr-web' and config['field_client_id'] == 'sepehr-field'
        assert config['issuer'] == 'https://identity.test/realms/sepehr' and config['idle_seconds'] == 900


def test_security_dossier_is_auditor_only_complete_and_audited(field_database, token_factory, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-15T08:00:00+00:00')
    with TestClient(app) as client:
        auditor = bearer(token_factory(sub='aud', roles=['auditor']))
        for roles in (['admin'], ['security_manager'], ['guard']):
            assert client.get('/api/v1/audit/security-dossier', headers=bearer(token_factory(sub='x', roles=roles))).status_code == 403
        response = client.get('/api/v1/audit/security-dossier', headers=auditor)
        assert response.status_code == 200, response.text
        dossier = response.json()
        endpoints = {(e['method'], e['path']): e for e in dossier['endpoints']}
        assert endpoints[('GET', '/api/v1/health')]['authentication'] == 'public'
        assert endpoints[('POST', '/api/v1/tour/offline/emergency')]['authentication'] == 'device_signature'
        assert endpoints[('GET', '/api/v1/audit/security-dossier')]['roles'] == ['auditor']
        assert endpoints[('GET', '/api/v1/media/{id}/content')]['authentication'] == 'required'
        assert all(e['authentication'] != 'optional_unless_enforce_all' for e in dossier['endpoints']
                   if e['path'].startswith(('/api/v1/tour', '/api/v1/media', '/api/v1/devices', '/api/v1/audit')))
        assert dossier['response_headers']['X-Frame-Options'] == 'DENY' and 'Permissions-Policy' in dossier['response_headers']
        assert any('scrypt' in c['algorithm'] for c in dossier['cryptography'])
        assert dossier['audit_chain']['valid'] is True and dossier['residual_risks']
        assert dossier['generated_at_jalali'] == '1405/07/23 11:30' and dossier['audit_id'].startswith('AUD-')
        letter = client.get('/api/v1/audit/security-dossier/letter', headers=auditor)
        assert letter.status_code == 200 and letter.headers['content-type'].startswith('text/html')
        assert 'مرکز مدیریت راهبردی افتا' in letter.text and 'http' not in letter.text.split('<body>')[1]
        actions = [a['action'] for a in store.field.audits()]
        assert 'دریافت پرونده شواهد ارزیابی امنیتی (افتا)' in actions and 'تولید پیش‌نویس استعلام افتا' in actions


def test_offline_package_manifest_and_letter(field_database, token_factory, tmp_path):
    with TestClient(app) as client:
        dossier = client.get('/api/v1/audit/security-dossier', headers=bearer(token_factory(sub='aud', roles=['auditor']))).json()
    saved = tmp_path / 'dossier.json'
    saved.write_text(json.dumps(dossier, ensure_ascii=False), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('security_dossier_script', ROOT / 'scripts' / 'security_dossier.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(['--out', str(tmp_path / 'out'), '--dossier-json', str(saved)]) == 0
    target = next((tmp_path / 'out').iterdir())
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    names = {f['path'] for f in manifest['files']}
    assert names == {'dossier.json', 'realm-check.json', 'dependencies.json', 'summary.html', 'inquiry-letter.html'}
    for row in manifest['files']:
        assert hashlib.sha256((target / row['path']).read_bytes()).hexdigest() == row['sha256']
    assert manifest['realm_failures'] == []
    letter = (target / 'inquiry-letter.html').read_text(encoding='utf-8')
    assert hashlib.sha256((target / 'dossier.json').read_bytes()).hexdigest() in letter
    summary = (target / 'summary.html').read_text(encoding='utf-8')
    assert 'fastapi' in summary and '/api/v1/tour/exceptions' in summary
    assert '<script' not in summary and 'src="http' not in summary and 'href="http' not in summary
