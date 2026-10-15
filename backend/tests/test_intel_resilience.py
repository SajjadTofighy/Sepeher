"""Phase seven resilience: verified backup/restore, paper fallback entry and load-test measurement."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from app.core import store
from app.field import media as field_media
from app.core.fieldstore import FieldStore
from app.main import app
from test_intel_field_media import put, start
from test_intel_field_safety import setup_field
from test_intel_supervision import SCOPE, at, scenario

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_delete_restore_equality_and_tamper_refusal(field_database, track_database, token_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T00:00:00+00:00')
    with TestClient(app) as client:
        guard, tour = setup_field(client, token_factory)
        client.put('/api/v1/tour/zones/Z1', json=dict(name='محوطه شماتیک', points=[[0, 0], [2, 0], [2, 2], [0, 2]],
                                                      media_capture_allowed=True))
        body = b'evidence-bytes' * 100
        upload = start(client, guard, tour, body).json()
        put(client, guard, upload['id'], 0, body)
        media_id = client.post(f"/api/v1/media/uploads/{upload['id']}/complete", headers=guard).json()['media']['id']
    track_database.append('AST-009', 1.0, 1.0, '2026-10-10T00:00:00+00:00')
    audits, tracks = field_database.audits(), track_database.read('AST-009')
    media_dir = field_media.media_root()
    backup, restore = script('backup'), script('restore')
    target = backup.backup(field_database.path, track_database.path, media_dir, tmp_path / 'backups')
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    listed = {row['path']: row['sha256'] for row in manifest['files']}
    assert {'field.sqlite3', 'tracks.sqlite3', f'media/objects/{media_id}.bin'} <= set(listed)
    assert listed[f'media/objects/{media_id}.bin'] == hashlib.sha256(body).hexdigest()

    restored = tmp_path / 'restored'
    field_db, track_db, restored_media = restored / 'field.sqlite3', restored / 'tracks.sqlite3', restored / 'media'
    restore.restore(target, field_db, track_db, restored_media)
    copy = FieldStore(field_db)
    assert copy.audits() == audits and copy.verify_audit()
    assert copy.get('media', media_id)['sha256'] == hashlib.sha256(body).hexdigest()
    assert (restored_media / 'objects' / f'{media_id}.bin').read_bytes() == body
    from app.core.tracks import TrackStore
    assert TrackStore(track_db).read('AST-009') == tracks
    with pytest.raises(FileExistsError):
        restore.restore(target, field_db, track_db, restored_media)
    (target / 'media' / 'objects' / f'{media_id}.bin').write_bytes(b'tampered')
    with pytest.raises(restore.ManifestError):
        restore.restore(target, field_db, track_db, restored_media, force=True)
    assert restore.main([str(target), '--field-db', str(field_db), '--track-db', str(track_db),
                         '--media-dir', str(restored_media), '--force']) == 1
    assert (restored_media / 'objects' / f'{media_id}.bin').read_bytes() == body


def test_paper_form_entry_is_low_trust_and_not_missed(field_database, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T10:00:00+00:00')
    scenario()
    with TestClient(app) as client:
        entry = dict(scheduled_tour_id='ST2', station_id='S3', recorded_at=at(7, 30), form_serial='F-0012', notes='قطع شبکه')
        created = client.post('/api/v1/tour/paper-scans', json=entry)
        assert created.status_code == 201, created.text
        row = created.json()
        assert row['method'] == 'paper' and row['trust_level'] == 'low' and row['evidence']['tag'] == 'paper'
        assert client.post('/api/v1/tour/paper-scans', json=entry).json()['id'] == row['id']
        assert client.post('/api/v1/tour/paper-scans', json={**entry, 'recorded_at': at(7, 45)}).status_code == 409
        assert client.post('/api/v1/tour/paper-scans', json={**entry, 'station_id': 'S1', 'form_serial': 'F-2'}).status_code == 422
        assert client.post('/api/v1/tour/paper-scans', json={**entry, 'recorded_at': at(11), 'form_serial': 'F-3'}).status_code == 422
        totals = client.get('/api/v1/reports/tour/summary', params=dict(window_from=at(0), window_to=at(12))).json()['totals']
        assert totals['missed'] == 0 and totals['visited'] == 3 and totals['verified'] == 1
        status = {s['station_id']: s['status'] for s in client.get('/api/v1/tour/station-status').json()}
        assert status['S3'] == 'unverified'
        assert 'ورود فرم کاغذی پشتیبان گشت' in [a['action'] for a in store.field.audits()]


def test_load_test_measurement_without_network():
    load = script('load_test')
    work = list(load.jobs(10, 'AST-009', 'STN-1', 'SPH2:1:STN-1:1:abc'))
    assert [kind for kind, _, _ in work].count('scan') == 5
    def stub(job):
        # Deterministic stand-in for HTTP: scans are rate-limited, positions accepted.
        return job[0], 429 if job[0] == 'scan' else 201, 10.0 if job[0] == 'scan' else 2.0
    report = load.run(stub, work, concurrency=2)
    assert report['total'] == 10 and set(report['by_kind']) == {'scan', 'position'}
    assert load.percentile([1, 2, 3, 4], 0.95) == 4 and load.percentile([], 0.5) is None
    assert report['by_kind']['scan']['error_rate'] == 1.0 and report['by_kind']['scan']['statuses'] == {'429': 5}
    assert report['by_kind']['position']['p95_ms'] == 2.0
    assert load.evaluate(report) == []
    assert len(load.evaluate(report, target_p95_ms=5, target_error_rate=0.01)) == 2
