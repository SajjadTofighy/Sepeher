from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.core import store
from app.core.tracks import TrackStore


def test_positions_survive_reopen_reset_and_out_of_order_delivery(track_database, monkeypatch):
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        path = '/api/v1/assets/AST-001'
        stamp = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        point = dict(lon=49.702, lat=30.757, time=stamp.isoformat().replace('+00:00', 'Z'), speed=24)
        assert client.post(path + '/positions', json=point).status_code == 201
        # Retries with an equivalent timezone represent exactly one observation.
        tehran = stamp.astimezone(timezone(timedelta(hours=3, minutes=30))).isoformat()
        retry = client.post(path + '/positions', json={**point, 'time': tehran})
        assert retry.status_code == 201 and retry.json()['created'] is False
        assert client.post(path + '/positions', json={**point, 'lon': 50}).status_code == 409
        older = {**point, 'time': (stamp - timedelta(hours=1)).isoformat(), 'lon': 49.7}
        assert client.post(path + '/positions', json=older).status_code == 201
        monkeypatch.setattr(store, 'tracks', TrackStore(track_database.path))
        assert client.post('/api/v1/demo/reset').status_code == 200
        asset = next(a for a in client.get('/api/v1/bootstrap').json()['assets'] if a['id'] == 'AST-001')
        assert asset['lon'] == point['lon'] and asset['speed'] == 24
        points = client.get(path + '/track', params={'since': older['time']}).json()
        assert len(points) == 2
        assert [p['lon'] for p in points] == [49.7, 49.702]
        assert client.get(path + '/track', params={'limit': 1}).json() == points[-1:]
        assert len(client.get(path + '/track', params={'since': older['time'], 'until': older['time']}).json()) == 1


def test_positions_validation_and_empty_history(track_database):
    with TestClient(app) as client:
        path = '/api/v1/assets/AST-001'
        point = dict(lon=49.702, lat=30.757, time='2099-01-01T12:00:00Z')
        for change in ({'lon': 181}, {'lat': 90}, {'speed': -1}, {'time': '2099-01-01T12:00:00'}, {'time': 'invalid'}):
            assert client.post(path + '/positions', json={**point, **change}).status_code == 422
        assert client.post('/api/v1/assets/missing/positions', json=point).status_code == 404
        for params in ({'limit': 0}, {'limit': 10001}, {'since': '2099-01-02T00:00:00Z', 'until': point['time']}, {'since': '2099-01-01T12:00:00'}):
            assert client.get(path + '/track', params=params).status_code == 422
        assert client.get(path + '/track', params={'since': '2199-01-01T00:00:00Z'}).json() == []
        assert client.post(path + '/positions', json={'lon': 49.7, 'lat': 30.75}).status_code == 201
        assert track_database.latest('AST-001')['time'] <= datetime.now(timezone.utc).isoformat(timespec='microseconds')


def iso(value):
    return value.isoformat()


def asset_view(client, asset_id='AST-001'):
    return next(a for a in client.get('/api/v1/bootstrap').json()['assets'] if a['id'] == asset_id)


def test_position_quality_flags_live_acceptance_and_evidence(track_database, monkeypatch):
    base = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
    clock = dict(now=base)
    monkeypatch.setattr(store, 'now', lambda: clock['now'].isoformat())
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        path = '/api/v1/assets/AST-001/positions'
        # Beyond the configured clock skew a future time would stay "newest" forever: rejected.
        skew = store.state['settings']['field_clock_skew_seconds']
        assert client.post(path, json=dict(lon=49.7, lat=30.7, time=iso(base + timedelta(seconds=skew + 1)))).status_code == 422
        first = client.post(path, json=dict(lon=49.7, lat=30.7, time=iso(base - timedelta(minutes=2)),
                                            accuracy_m=8, fix_source='gnss', sequence=41)).json()
        assert first['live'] and first['flags'] == [] and first['created']
        ahead = client.post(path, json=dict(lon=49.7005, lat=30.7, time=iso(base + timedelta(seconds=30)))).json()
        assert ahead['flags'] == ['accuracy_unknown', 'clock_ahead'] and ahead['live']
        # Late history fills the gap without moving the live position backwards.
        late = client.post(path, json=dict(lon=49.6995, lat=30.7, time=iso(base - timedelta(minutes=1)), accuracy_m=250)).json()
        assert set(late['flags']) == {'late', 'low_accuracy'} and late['live']
        assert asset_view(client)['lon'] == 49.7005
        # A 50 km jump in 30 s is stored as raw evidence but never becomes the live position.
        clock['now'] = base + timedelta(minutes=1)
        jump = client.post(path, json=dict(lon=50.2, lat=30.7, time=iso(base + timedelta(seconds=60)), accuracy_m=5)).json()
        assert jump['flags'] == ['implausible_speed'] and jump['live'] is False
        view = asset_view(client)
        assert view['lon'] == 49.7005 and view['position_state'] == 'fresh'
        assert view['position_accuracy_m'] is None and 'accuracy_unknown' in view['position_flags']
        observed = client.get('/api/v1/assets/AST-001/observations').json()
        raw = next(o for o in observed if o['lon'] == 50.2)
        assert raw['live'] is False and raw['received_at'] == clock['now'].isoformat(timespec='microseconds')
        assert raw['auth'] == 'principal:operator-a'
        detail = next(o for o in observed if o['sequence'] == 41)
        assert detail['accuracy_m'] == 8 and detail['fix_source'] == 'gnss'
        # Unknown accuracy is stored as null, never 0 m.
        assert next(o for o in observed if o['lon'] == 49.7005)['accuracy_m'] is None


def test_position_state_separates_stale_no_fix_and_simulated(track_database, monkeypatch):
    base = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
    clock = dict(now=base)
    monkeypatch.setattr(store, 'now', lambda: clock['now'].isoformat())
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        assert asset_view(client, 'AST-002')['position_state'] == 'simulated'
        assert client.post('/api/v1/assets/AST-001/positions', json=dict(lon=49.7, lat=30.7, time=iso(base))).status_code == 201
        assert asset_view(client)['position_state'] == 'fresh'
        from app.core.engine import observation_gap_seconds
        gap = observation_gap_seconds(store.lookup('assets', 'AST-001'))
        clock['now'] = base + timedelta(seconds=gap + 1)
        stale = asset_view(client)
        assert stale['position_state'] == 'stale' and stale['position_age_seconds'] > gap
        # Independent contact evidence (an authenticated device request) turns silence into "no fix".
        store.record_contact('AST-001', clock['now'].isoformat())
        assert asset_view(client)['position_state'] == 'no_fix'


def test_existing_track_database_is_migrated_without_loss(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.sqlite3'
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE positions (asset_id TEXT NOT NULL, time TEXT NOT NULL, lon REAL NOT NULL,
                  lat REAL NOT NULL, speed REAL, source TEXT NOT NULL DEFAULT 'reported', PRIMARY KEY (asset_id, time))""")
    db.execute("INSERT INTO positions VALUES('AST-001','2026-10-01T00:00:00.000000+00:00',49.7,30.7,5,'reported')")
    db.commit()
    db.close()
    store_ = TrackStore(path)
    row = store_.latest('AST-001')
    assert row['lon'] == 49.7 and row['accuracy_m'] is None and row['flags'] == [] and row['live'] is True
    assert row['received_at'] is None and row['fix_source'] == 'unknown'
    # Reopening is idempotent and keeps the row count.
    assert len(TrackStore(path).detailed('AST-001')) == 1


def test_incremental_track_cache_always_equals_the_database(track_database):
    import random
    rng = random.Random(7)
    asset = store.lookup('assets', 'AST-001')
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    store.refresh_track(asset)  # prime the cache
    used = set()
    for step in range(1500):
        # Mostly in order, with late arrivals, rows older than the 500 window and non-live points.
        offset = step * 10 if rng.random() < 0.8 else rng.randrange(0, max(1, step * 10))
        if offset in used:
            continue
        used.add(offset)
        track_database.append('AST-001', 49.7 + rng.random() / 100, 30.7, base + timedelta(seconds=offset),
                              received_at=base, live=rng.random() > 0.1)
        if step % 97 == 0 or step > 1490:
            store.refresh_track(asset)
            assert asset['track'] == track_database.read('AST-001', source='reported')
            latest = track_database.latest('AST-001')
            assert (asset['lon'], asset['last_seen']) == (latest['lon'], latest['time'])
