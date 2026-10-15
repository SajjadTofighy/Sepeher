"""Phase six: exception board, station verification, integrity rules and patrol reports."""
from fastapi.testclient import TestClient

from app.core import store
from app.intel import worker
from app.main import app
from test_auth_access import bearer

NOW = '2026-10-10T10:00:00+00:00'
SCOPE = dict(zone_id='Z1', contractor_id='SCHEMATIC')


def clock(monkeypatch, value=NOW):
    current = {'time': value}
    monkeypatch.setattr(store, 'now', lambda: current['time'])
    return current


def at(hour, minute=0, day=10):
    return f'2026-10-{day:02}T{hour:02}:{minute:02}:00+00:00'


def scan(id, station_id, owner='guard-a', tour='TOUR-A', trust='medium', status='accepted', received=at(6, 30),
         lon=None, lat=None, tag='hmac_valid', clock_value='ok', flags=(), reason=''):
    row = dict(id=id, station_id=station_id, tour_id=tour, visit_id=None, owner_sub=owner, device_id='DEV-1',
               client_id=id, received_at=received, device_time=received, lon=lon, lat=lat, accuracy_m=5,
               evidence=dict(tag=tag, location='verified', sequence='in_order', dwell='ok', clock=clock_value),
               trust_level=trust, status=status, review_sub=None, reviewed_at=None, reason=reason,
               hazard_flags=[], offline_flags=list(flags), **SCOPE)
    store.field.append_scan(row)
    return row


def scenario():
    """Four scheduled checks: one verified, one visited unverified, one missed, one open; one excused."""
    field = store.field
    for guard_id, sub in (('AST-009', 'guard-a'), ('AST-010', 'guard-b')):
        field.save('guards', dict(id=guard_id, name='نگهبان شماتیک', keycloak_sub=sub, **SCOPE))
    for station_id in ('S1', 'S2', 'S3'):
        field.save('stations', dict(id=station_id, name='ایستگاه ' + station_id, tag_mode='qr_hmac', **SCOPE))
    field.save('tour', dict(id='TOUR-A', guard_id='AST-009', owner_sub='guard-a', status='completed',
                            started_at=at(6), **SCOPE))
    field.save('tour', dict(id='TOUR-B', guard_id='AST-010', owner_sub='guard-b', status='completed',
                            started_at=at(6), **SCOPE))
    tours = [('ST1', at(6), at(8), ['S1', 'S2'], 'completed', 'TOUR-A'), ('ST2', at(7), at(9), ['S3'], 'queued', None),
             ('ST3', at(9, 30), at(11), ['S1'], 'queued', None), ('ST4', at(8), at(9), ['S2'], 'excused', None)]
    for id, due, ends, stations, status, tour in tours:
        field.save('scheduled_tours', dict(id=id, guard_id='AST-009', due_at=due, ends_at=ends, station_ids=stations,
                                           status=status, tour_id=tour, warnings=['وضعیت اضطرار'] if status == 'excused' else [],
                                           **SCOPE))
    for id, station_id, trust in (('V1', 'S1', 'high'), ('V2', 'S2', 'low')):
        field.save('station_visits', dict(id=id, tour_id='TOUR-A', station_id=station_id, status='completed',
                                          owner_sub='guard-a', arrived_at=at(6, 10), completed_at=at(6, 20),
                                          min_dwell_seconds=0, trust_level=trust, **SCOPE))
    scan('SCAN-1', 'S1', trust='medium')
    scan('SCAN-2', 'S2', trust='low', clock_value='skewed')


def test_board_station_status_and_report_counts_with_emergency(field_database, monkeypatch):
    current = clock(monkeypatch)
    scenario()
    with TestClient(app) as client:
        board = client.get('/api/v1/tour/exceptions')
        assert board.status_code == 200, board.text
        data = board.json()
        kinds = {(i['kind'], i['station_id']) for i in data['items']}
        assert {('station_missed', 'S3'), ('station_overdue', 'S1'), ('scan_low_trust', 'S2')} <= kinds
        assert all(i['can_execute'] is False for i in data['items'])
        assert [s['scheduled_tour_id'] for s in data['suspended']] == ['ST4']
        assert {s['station_id']: s['status'] for s in data['stations']} == {'S1': 'ok', 'S2': 'unverified', 'S3': 'never'}
        assert data['classification_label'] == 'محرمانه' and data['generated_at_jalali'] == '1405/07/18 13:30'

        report = client.get('/api/v1/reports/tour/summary', params=dict(window_from=at(0), window_to=at(12))).json()
        assert report['totals'] == dict(planned=4, visited=2, verified=1, verified_percent=25.0, missed=1, pending=1, suspended=1)
        assert report['contractors'] == [dict(contractor_id='SCHEMATIC', zone_id='Z1', **report['totals'])]
        assert report['trust']['medium'] == 1 and report['trust']['low'] == 1
        assert report['audit_chain']['valid'] is True and report['viewer'] == 'operator-a'
        assert 'guard_id' not in str(report['contractors'])

        # Emergency started 08:30: ST2 (window to 09:00) and ST3 are suspended, not missed.
        store.field.save('emergency_modes', dict(id='Z1', active=True, reason='هشدار پهپاد', changed_at=at(8, 30), actor_sub='o'))
        totals = client.get('/api/v1/reports/tour/summary', params=dict(window_from=at(0), window_to=at(12))).json()['totals']
        assert totals['missed'] == 0 and totals['pending'] == 0 and totals['suspended'] == 3 and totals['planned'] == 2
        # An emergency starting after the window closed never erases a missed station.
        store.field.save('emergency_modes', dict(id='Z1', active=True, reason='بعدی', changed_at=at(9, 45), actor_sub='o'))
        assert client.get('/api/v1/reports/tour/summary', params=dict(window_from=at(0), window_to=at(12))).json()['totals']['missed'] == 1
        current['time'] = at(12)
        assert client.get('/api/v1/reports/tour/summary', params=dict(window_from=at(12), window_to=at(0))).status_code == 422


def test_integrity_rules_cloned_tag_shadow_and_resolution(field_database, monkeypatch):
    current = clock(monkeypatch)
    scenario()
    scan('SCAN-R', 'S1', status='rejected', trust='low', tag='replay', reason='tag_replay', received=at(7))
    scan('SCAN-P1', 'S3', owner='guard-a', received=at(7, 0), lon=49.80, lat=30.80)
    scan('SCAN-P2', 'S3', owner='guard-b', tour='TOUR-B', received=at(7, 5), lon=50.30, lat=30.80)
    scan('SCAN-C', 'S2', clock_value='regressed', trust='low', received=at(7, 10), flags=['clock_regressed'])
    for index in range(3):
        scan(f'SCAN-O{index}', 'S2', tour='TOUR-B', owner='guard-b', received=at(8, index), flags=['offline_too_long'])
        store.field.save('station_visits', dict(id=f'VC{index}', tour_id='TOUR-B', station_id='S2', status='cancelled',
                                                owner_sub='guard-b', arrived_at=at(8, 10 + index),
                                                completed_at=at(8, 10 + index) .replace(':00+', ':20+'),
                                                min_dwell_seconds=120, **SCOPE))
    store.state['settings']['shadow_mode'] = False
    worker.tick(current['time'])
    rules = {f['rule_id']: f for f in store.state['findings'] if f['rule_id'].startswith('intel.integrity.')}
    assert set(rules) == {'intel.integrity.tag_replay', 'intel.integrity.tag_distance', 'intel.integrity.clock',
                          'intel.integrity.offline_repeat', 'intel.integrity.short_dwell'}
    assert rules['intel.integrity.tag_replay']['subject_ids'] == ['S1']
    assert rules['intel.integrity.tag_distance']['evidence']['values']['scan_ids'] == ['SCAN-P1', 'SCAN-P2']
    assert rules['intel.integrity.short_dwell']['subject_ids'] == ['AST-010']
    assert all(f['mode'] == 'shadow' and f['can_execute'] is False and f['incident_id'] is None for f in rules.values())
    with TestClient(app) as client:
        items = [i for i in client.get('/api/v1/tour/exceptions').json()['items'] if i['kind'] == 'integrity']
        assert len(items) == 5
        report = client.get('/api/v1/reports/tour/summary', params=dict(window_from=at(0), window_to=at(12))).json()
        assert report['trust']['rejected_replay'] == 1 and report['integrity']['intel.integrity.tag_replay'] == 1
    current['time'] = at(12, day=12)
    worker.tick(current['time'])
    assert all(f['status'] == 'resolved' for f in store.state['findings'] if f['rule_id'].startswith('intel.integrity.'))


def test_access_duress_individual_view_and_audited_csv(field_database, token_factory, monkeypatch):
    clock(monkeypatch)
    scenario()
    store.field.save('field_safety_events', dict(id='SAFE-D', tour_id='TOUR-A', guard_id='AST-009', owner_sub='guard-a',
                                                 device_id='DEV-1', type='duress', created_at=at(9), operator_ack_at=None,
                                                 escalation='operator', **SCOPE))
    with TestClient(app) as client:
        supervisor = bearer(token_factory(sub='sup', roles=['shift_supervisor']))
        other_zone = bearer(token_factory(sub='sup2', roles=['shift_supervisor'], groups=['/zones/Z2', '/contractors/SCHEMATIC']))
        manager = bearer(token_factory(sub='mgr', roles=['security_manager']))
        auditor = bearer(token_factory(sub='aud', roles=['auditor']))
        guard = bearer(token_factory(sub='guard-a', roles=['guard']))
        assert any(i['kind'] == 'duress_unacked' for i in client.get('/api/v1/tour/exceptions', headers=supervisor).json()['items'])
        assert client.get('/api/v1/tour/exceptions', headers=auditor).status_code == 403
        assert client.get('/api/v1/tour/exceptions', headers=other_zone).json()['items'] == []

        path = '/api/v1/reports/tour/guards/AST-009'
        params = dict(window_from=at(0), window_to=at(12))
        detail = client.get(path, headers=supervisor, params=params)
        assert detail.status_code == 200, detail.text
        assert [c['outcome'] for c in detail.json()['checks']].count('missed') == 1
        assert client.get(path, headers=auditor, params=params).status_code == 200
        assert client.get(path, headers=other_zone, params=params).status_code == 403
        denied = client.get(path, headers=manager, params=params)
        assert denied.status_code == 403 and denied.json()['detail']['code'] == 'individual_view_denied'
        assert client.get(path, headers=guard, params=params).status_code == 403
        views = [a for a in store.field.audits() if a['action'] == 'مشاهده نمای فردی نگهبان']
        assert [a['sub'] for a in views] == ['sup', 'aud']

        exported = client.get('/api/v1/reports/tour/summary', headers=manager, params=dict(format='csv', **params))
        assert exported.status_code == 200 and exported.headers['content-type'].startswith('text/csv')
        lines = exported.content.decode('utf-8-sig').strip().splitlines()
        assert lines[0] == 'طبقه‌بندی,محرمانه' and lines[-1] == 'طبقه‌بندی,محرمانه'
        assert 'SCHEMATIC,Z1,4,2,1,25.0,1,1,1' in lines
        assert 'AST-009' not in exported.content.decode('utf-8-sig')
        exports = [a for a in store.field.audits() if a['action'] == 'خروجی گزارش گشت نگهبانی']
        assert [(a['sub'], a['detail']) for a in exports] == [('mgr', 'csv')]
        assert client.get('/api/v1/reports/tour/summary', headers=guard).status_code == 403
        assert store.field.verify_audit()
