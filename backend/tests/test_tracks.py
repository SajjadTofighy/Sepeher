from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.core import store
from app.core.tracks import TrackStore


def test_positions_survive_reopen_reset_and_out_of_order_delivery(track_database, monkeypatch):
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        path = '/api/v1/assets/AST-001'
        point = dict(lon=49.702, lat=30.757, time='2099-01-01T12:00:00Z', speed=24)
        assert client.post(path + '/positions', json=point).status_code == 201
        # Retries with an equivalent timezone represent exactly one observation.
        assert client.post(path + '/positions', json={**point, 'time': '2099-01-01T15:30:00+03:30'}).status_code == 201
        assert client.post(path + '/positions', json={**point, 'lon': 50}).status_code == 409
        older = {**point, 'time': '2099-01-01T11:00:00Z', 'lon': 49.7}
        assert client.post(path + '/positions', json=older).status_code == 201
        monkeypatch.setattr(store, 'tracks', TrackStore(track_database.path))
        assert client.post('/api/v1/demo/reset').status_code == 200
        asset = next(a for a in client.get('/api/v1/bootstrap').json()['assets'] if a['id'] == 'AST-001')
        assert asset['lon'] == point['lon'] and asset['speed'] == 24
        points = client.get(path + '/track', params={'since': '2099-01-01T11:00:00Z'}).json()
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
