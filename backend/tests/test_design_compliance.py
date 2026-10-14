"""Behavioural regressions found by reviewing Main-Design.MD."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import engine, store
from app.main import app
from app.seed import seed


@pytest.fixture
def client(track_database):
    store.state.clear()
    store.state.update(seed())
    with TestClient(app) as client:
        yield client


def engine_case(condition, threshold=1):
    state = seed()
    state['policies'] = [{**state['policies'][0], 'condition': condition,
                          'schedule': 'تمام شبانه‌روز', 'threshold': threshold}]
    state['zones'] = [dict(id='Z1', name='test', points=[[0, 0], [2, 0], [2, 2], [0, 2]])]
    asset = {**state['assets'][0], 'lon': 1, 'lat': 1, 'authorized': False, 'track': [], 'speed': 0}
    stamp = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    incidents = []
    def create(**kwargs):
        incidents.append(kwargs)
        return {'id': 'test'}
    def evaluate(time=stamp):
        return engine.evaluate(state, asset, time.isoformat(), create, lambda *args: None)
    return state, asset, stamp, incidents, evaluate


def test_global_shadow_and_log_only_never_route():
    state, asset, stamp, incidents, evaluate = engine_case('geofence_entry')
    state['settings']['shadow_mode'] = True
    alerts = evaluate()
    assert alerts[0]['mode'] == 'shadow' and not alerts[0]['routed']
    assert not incidents
    state['settings']['shadow_mode'] = False
    state['engine']['inside'].clear()
    state['policies'][0]['action'] = 'log_only'
    assert not evaluate()[0]['routed']
    assert not incidents


def test_connection_loss_uses_region_threshold_and_rearms_after_recovery():
    state, asset, stamp, incidents, evaluate = engine_case('connection_lost', 2)
    state['zones'][0]['coverage'] = 'weak'
    asset['last_seen'] = (stamp - timedelta(minutes=10)).isoformat()
    assert evaluate() == []
    assert len(evaluate(stamp + timedelta(minutes=10))) == 1
    assert evaluate(stamp + timedelta(minutes=11)) == []
    asset['last_seen'] = (stamp + timedelta(minutes=11)).isoformat()
    assert evaluate(stamp + timedelta(minutes=11)) == []
    assert len(evaluate(stamp + timedelta(minutes=32))) == 1


def test_stop_needs_continuous_observations_not_just_silence():
    state, asset, stamp, incidents, evaluate = engine_case('long_stop', 2)
    asset['track'] = [dict(lon=1, lat=1, time=(stamp - timedelta(seconds=seconds)).isoformat())
                      for seconds in (150, 120, 90, 60, 30, 0)]
    assert len(evaluate()) == 1
    state['engine'] = {}
    asset['track'] = [asset['track'][0], asset['track'][-1]]
    assert evaluate() == []
    state['engine'] = {}
    asset['track'] = [dict(lon=1, lat=1, time=(stamp - timedelta(minutes=minutes)).isoformat()) for minutes in (10, 9, 8)]
    assert evaluate() == []


def test_gps_jump_and_after_hours_have_executable_conditions():
    state, asset, stamp, incidents, evaluate = engine_case('gps_jump', 200)
    asset['track'] = [dict(lon=0, lat=0, time=(stamp - timedelta(seconds=10)).isoformat()),
                      dict(lon=1, lat=1, time=stamp.isoformat())]
    assert evaluate()[0]['routed']
    assert incidents[0]['title'] == 'جهش غیرممکن GPS'
    state, asset, stamp, incidents, evaluate = engine_case('after_hours')
    assert evaluate() == []
    asset['speed'] = 20
    assert evaluate()[0]['routed']
    assert evaluate() == []


def test_schedule_validation_and_unsupported_policy_gate(client):
    payload = dict(name='سیاست آزمایشی', zone='Z1', condition='tamper')
    for schedule in ('25:00–06:00', 'garbage', '22:61-06:00'):
        assert client.post('/api/v1/policies', json={**payload, 'schedule': schedule}).status_code == 422
    policy = client.post('/api/v1/policies', json={**payload, 'schedule': '۲۲:۰۰–۰۶:۰۰'}).json()
    assert policy['schedule'] == '22:00–06:00'
    assert client.post(f"/api/v1/policies/{policy['id']}/test").status_code == 422
    store.lookup('policies', policy['id'])['status'] = 'shadow'
    assert client.patch(f"/api/v1/policies/{policy['id']}/status", json={'status': 'active'}).status_code == 422
    assert engine.in_schedule('22:00–06:00', '23:00')
    assert engine.in_schedule('22:00–06:00', '05:59')
    assert not engine.in_schedule('22:00–06:00', '06:00')


def test_backtest_uses_stored_positions_without_mutating_live_alerts(client, track_database):
    store.state['zones'] = [dict(id='Z1', name='test', points=[[0, 0], [2, 0], [2, 2], [0, 2]])]
    store.lookup('assets', 'AST-001')['authorized'] = False
    stamp = datetime.now(timezone.utc) - timedelta(minutes=1)
    track_database.append('AST-001', -1, -1, stamp - timedelta(minutes=1), 20)
    track_database.append('AST-001', 1, 1, stamp, 20)
    policy = client.post('/api/v1/policies', json=dict(name='ورود آزمایشی', zone='Z1')).json()
    before = deepcopy(store.state['alerts'])
    incidents = deepcopy(store.state['incidents'])
    result = client.post(f"/api/v1/policies/{policy['id']}/test").json()
    assert result['matches'] == 1 and result['samples'] >= 2
    assert not result['mock'] and result['false_positives'] is None
    assert store.state['alerts'] == before and store.state['incidents'] == incidents


def test_position_ingestion_evaluates_policy_without_map_polling(client):
    store.state['policies'] = [{**store.state['policies'][0], 'schedule': 'تمام شبانه‌روز'}]
    store.lookup('assets', 'AST-001')['authorized'] = False
    stamp = datetime.now(timezone.utc) + timedelta(seconds=1)
    response = client.post('/api/v1/assets/AST-001/positions', json=dict(lon=49.93, lat=30.75, time=stamp.isoformat()))
    assert response.status_code == 201
    assert store.state['alerts'][0]['routed']


def test_variable_checkpoint_count_and_busy_patrol(client):
    mission = store.state['missions'][0]
    mission['checkpoints'] = [dict(name='one', visited=True), dict(name='two', visited=True), dict(name='three', visited=False)]
    assert client.post('/api/v1/missions/MSN-101/checkpoint').json()['progress'] == 100
    path = '/api/v1/incidents/INC-824/transition'
    client.post(path, json={'status': 'confirmed'})
    assert client.post(path, json={'status': 'assigned', 'asset_id': 'AST-001'}).status_code == 200
    path = '/api/v1/incidents/INC-825/transition'
    client.post(path, json={'status': 'confirmed'})
    assert client.post(path, json={'status': 'assigned', 'asset_id': 'AST-001'}).status_code == 409
    assert all(p['asset_id'] != 'AST-001' for p in client.get('/api/v1/incidents/INC-825/nearby').json())
