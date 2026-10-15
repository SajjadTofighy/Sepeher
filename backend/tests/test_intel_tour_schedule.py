"""Deterministic phase-two schedule behavior without device or network adapters."""
from datetime import date
import random

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.core import store
from app.tour import schedule as tour_schedule
from app.core.fieldstore import FieldStore
from app.main import app
from test_auth_access import bearer, link_and_enroll


def test_default_shift_cycle_breaks_idempotency_and_restart(field_database, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T06:00:00+00:00')
    assert [(s['start'], s['duration_minutes']) for s in tour_schedule.default_pattern()['segments']] == [
        ('06:00', 480), ('14:00', 480), ('22:00', 480)]
    store.field.save('guards', dict(id='G1', keycloak_sub='guard-1'))
    store.field.save('routes', dict(id='R1', guard_id='G1', station_ids=['A', 'B', 'C'],
                                    order_mode='randomized', fixed_first='A', fixed_last='C', must_precede=[['A', 'B']]))
    store.field.save('shift_patterns', dict(id='P1', cycle=dict(on_days=1, off_days=1, anchor_date='2026-10-10'),
                                            segments=[dict(start='22:00', duration_minutes=720)],
                                            breaks=[dict(start_offset_minutes=180, duration_minutes=60, label='استراحت')]))
    schedule = dict(id='S1', status='approved', first_date='2026-10-10', last_date='2026-10-12',
                    pattern_id='P1', route_id='R1', tours_per_shift=2, zone_id='Z1', contractor_id='C1')
    first = tour_schedule.materialize(schedule, date(2026, 10, 10), rng_factory=lambda seed: random.Random(7))
    assert len(first) == 2 and first[0]['station_ids'] == ['A', 'B', 'C']
    assert all(row['due_at'] < row['ends_at'] and row['owner_sub'] == 'guard-1' for row in first)
    assert all(not (1 <= int(row['due_at'][11:13]) < 2) for row in first)
    assert tour_schedule.materialize(schedule, date(2026, 10, 10)) == first
    assert tour_schedule.materialize(schedule, date(2026, 10, 11)) == []
    assert len(FieldStore(field_database.path).records('scheduled_tours')) == 2


def test_order_constraints_and_heat_warning(field_database, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T00:00:00+00:00')
    route = dict(station_ids=['A', 'B', 'C', 'D'], order_mode='randomized', fixed_first='A',
                 fixed_last='D', must_precede=[['B', 'C']])
    for seed in range(30):
        order = tour_schedule.ordered_stations(route, random.Random(seed))
        assert order[0] == 'A' and order[-1] == 'D' and order.index('B') < order.index('C')
    route['must_precede'] = [['B', 'C'], ['C', 'B']]
    with pytest.raises(HTTPException):
        tour_schedule.ordered_stations(route, random.Random(1))
    store.state['settings']['heat_profile'] = dict(months=[10], restricted_hours='تمام شبانه‌روز',
                                                   max_continuous_minutes=5, checkin_minutes=5)
    store.field.save('guards', dict(id='G1', keycloak_sub='guard-1'))
    store.field.save('routes', dict(id='R1', guard_id='G1', station_ids=['A'], order_mode='fixed'))
    schedule = dict(id='S2', status='approved', first_date='2026-10-10', last_date='2026-10-10',
                    pattern_id='DEFAULT', route_id='R1', tours_per_shift=1, zone_id='Z1', contractor_id='C1')
    rows = tour_schedule.materialize(schedule, date(2026, 10, 10), rng_factory=lambda seed: random.Random(0))
    assert rows and all(row['warnings'] for row in rows)


def test_schedule_queue_scope_handover_and_emergency_api(field_database, token_factory, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-10T00:00:00+00:00')
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        assert client.put('/api/v1/tour/zones/Z1', json=dict(name='محوطه شماتیک', points=[[0, 0], [2, 0], [2, 2], [0, 2]], media_capture_allowed=False)).status_code == 200
        assert client.put('/api/v1/guards/AST-009/scope', json=dict(zone_id='Z1', contractor_id='SCHEMATIC')).status_code == 200
        assert client.put('/api/v1/guards/AST-010/scope', json=dict(zone_id='Z1', contractor_id='SCHEMATIC')).status_code == 200
        for station_id in ('S1', 'S2'):
            store.field.save('stations', dict(id=station_id, zone_id='Z1', contractor_id='SCHEMATIC', sensitivity='حساس'))
        guard, _ = link_and_enroll(client, token_factory)
        route = client.post('/api/v1/tour/routes', json=dict(name='مسیر شماتیک', guard_id='AST-009', zone_id='Z1',
                            contractor_id='SCHEMATIC', station_ids=['S1', 'S2'], order_mode='randomized', fixed_first='S1'))
        assert route.status_code == 201, route.text
        route_id = route.json()['id']
        pattern = client.post('/api/v1/tour/shift-patterns', json=dict(name='صبح', segments=[dict(start='04:00', duration_minutes=120)]))
        assert pattern.status_code == 201, pattern.text
        schedule = client.post('/api/v1/tour/schedules', json=dict(route_id=route_id, pattern_id=pattern.json()['id'],
                               first_date='2026-10-10', last_date='2026-10-10', tours_per_shift=1))
        assert schedule.status_code == 201, schedule.text
        assert client.post('/api/v1/tour/schedules/'+schedule.json()['id']+'/approve').status_code == 200
        staff_queue = client.get('/api/v1/tour/queue').json()
        guard_queue = client.get('/api/v1/tour/queue', headers=guard).json()
        assert len(staff_queue) == len(guard_queue) == 1
        assert staff_queue[0]['station_ids'] == ['S1', 'S2'] and guard_queue[0]['station_ids'] == ['S1']
        assert client.get('/api/v1/tour/routes', headers=guard).json()[0]['station_ids'] == []
        settings = client.get('/api/v1/settings').json()
        settings['handover_required'] = True
        assert client.put('/api/v1/settings', json=settings).status_code == 200
        start = client.post('/api/v1/tour', headers=guard, json=dict(route_id=route_id, scheduled_tour_id=guard_queue[0]['id']))
        assert start.status_code == 409
        handover = client.post('/api/v1/tour/handovers', json=dict(outgoing_guard_id='AST-010', incoming_guard_id='AST-009',
                               zone_id='Z1', contractor_id='SCHEMATIC', open_items=[], notes='تحویل آزمایشی'))
        assert handover.status_code == 201, handover.text
        assert client.post('/api/v1/tour/handovers/'+handover.json()['id']+'/ack', headers=guard).status_code == 200
        assert client.post('/api/v1/tour', headers=guard, json=dict(route_id=route_id, scheduled_tour_id=guard_queue[0]['id'])).status_code == 201
        officer = bearer(token_factory(roles=['security_officer']))
        emergency = client.put('/api/v1/tour/emergency/Z1', headers=officer, json=dict(active=True, reason='رزمایش آزمایشی'))
        assert emergency.status_code == 200, emergency.text
        assert client.get('/api/v1/tour/emergency/Z1', headers=officer).json()['active'] is True
