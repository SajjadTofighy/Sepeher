"""Station contracts, durable tags and task validation, with injected clocks."""
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from app import store
from app.tour import qr, tags as tour_tags
from app.fieldstore import FieldStore
from app.main import app
from app.tour.sun import cmac, verify_sun
from test_auth_access import bearer, create_route, link_and_enroll


@pytest.fixture
def client(field_database, monkeypatch):
    monkeypatch.setattr(store, 'now', lambda: '2026-10-08T00:00:00+00:00')
    with TestClient(app) as client:
        client.post('/api/v1/demo/reset')
        response = client.put('/api/v1/tour/zones/Z1', json=dict(name='محوطه آزمون شماتیک', points=[[0,0],[2,0],[2,2],[0,2]], media_capture_allowed=False))
        assert response.status_code == 200, response.text
        yield client


def create_station(client, **changes):
    payload = dict(zone_id='Z1', contractor_id='SCHEMATIC', name='ایستگاه آزمون شماتیک', sensitivity='حساس',
                   lon=1, lat=1, tag_mode='qr_hmac')
    payload.update(changes)
    response = client.post('/api/v1/tour/stations', json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def scan(payload, **changes):
    return dict(payload=payload, lon=1, lat=1, **changes)


def install(client, station, payload=None):
    payload = payload or tour_tags.tag_payload(station)
    response = client.post(f"/api/v1/tour/stations/{station['id']}/install", json=scan(payload))
    assert response.status_code == 200, response.text
    return response.json()


def approval(client, station, action, token_factory):
    request = client.post('/api/v1/approvals', json=dict(action=action, target_id=station['id']))
    assert request.status_code == 201, request.text
    id = request.json()['id']
    assert client.post(f'/api/v1/approvals/{id}/approve').status_code == 403
    result = client.post(f'/api/v1/approvals/{id}/approve', headers=bearer(token_factory(sub='independent-admin')))
    assert result.status_code == 200, result.text
    return client.get(f"/api/v1/tour/stations/{station['id']}").json()


def start_visit(client, token_factory, station, payload=None):
    headers, _ = link_and_enroll(client, token_factory)
    route = create_route(client)
    tour = client.post('/api/v1/tour', headers=headers, json={'route_id': route}).json()
    result = client.post(f"/api/v1/tour/stations/{station['id']}/visits", headers=headers,
                         json=scan(payload or tour_tags.tag_payload(station), tour_id=tour['id']))
    assert result.status_code == 201, result.text
    return result.json(), headers


def sun_payload(station, counter):
    key = tour_tags.active_key(station['id'])
    uid = bytes.fromhex(station['tag_uid'])
    counter_bytes = counter.to_bytes(3, 'little')
    plain = bytes([0xC7]) + uid + counter_bytes + bytes(5)
    encoder = Cipher(algorithms.AES(bytes.fromhex(key['meta_key'])), modes.CBC(bytes(16))).encryptor()
    encrypted = (encoder.update(plain) + encoder.finalize()).hex().upper()
    query = f"tag={tour_tags.tag_payload(station)}&picc={encrypted}&cmac="
    session = cmac(bytes.fromhex(key['file_key']), bytes.fromhex('3CC300010080') + uid + counter_bytes)
    return 'https://field.test/nfc?' + query + cmac(session, query.encode())[1::2].hex().upper()


def test_station_settings_scope_and_persistence(client, token_factory, monkeypatch):
    station = create_station(client, hazards=['h2s','ex_zone_1'])
    assert station['media_capture_allowed'] is False and station['tag_revision'] == 1
    bad = {k:v for k,v in station.items() if k not in ('id','tag_status','tag_revision','created_at')}
    assert client.post('/api/v1/tour/stations', json={**bad,'sensitivity':'غیرمجاز'}).status_code == 422
    assert client.post('/api/v1/tour/stations', json={**bad,'lon':3}).status_code == 422
    outsider = bearer(token_factory(roles=['security_officer'], groups=['/zones/Z2','/contractors/SCHEMATIC']))
    assert client.get('/api/v1/tour/stations?zone_id=Z1', headers=outsider).json() == []
    assert client.get('/api/v1/tour/stations/'+station['id'], headers=outsider).status_code == 403
    foreign = bearer(token_factory(roles=['security_officer'], groups=['/zones/Z1','/contractors/OTHER']))
    assert client.get('/api/v1/tour/stations', headers=foreign).json() == []
    assert client.get('/api/v1/tour/stations', headers={'Authorization':''}).status_code == 401
    settings = client.get('/api/v1/settings').json()
    settings['station_sensitivity_labels'] = ['حساس','برچسب سازمانی']
    assert client.put('/api/v1/settings', json=settings).status_code == 200
    assert create_station(client, sensitivity='برچسب سازمانی')['sensitivity'] == 'برچسب سازمانی'
    settings['station_sensitivity_labels'] = ['برچسب سازمانی']
    assert client.put('/api/v1/settings', json=settings).status_code == 409
    path = store.field.path
    monkeypatch.setattr(store, 'field', FieldStore(path))
    client.post('/api/v1/demo/reset')
    assert client.get('/api/v1/tour/stations/'+station['id']).json() == station
    assert client.get('/api/v1/settings').json()['station_sensitivity_labels'] == ['حساس','برچسب سازمانی']
    assert store.field.verify_audit()


def test_tag_revision_key_rotation_revoke_and_neutral_sheet(client, token_factory):
    station = create_station(client)
    payload = tour_tags.tag_payload(station)
    sheet = client.get(f"/api/v1/tour/stations/{station['id']}/tag-sheet").json()
    assert sheet['code'] == payload and sheet['svg'].startswith('<svg')
    assert station['name'] not in sheet['svg'] and station['sensitivity'] not in sheet['svg']
    installed = install(client, station)
    assert installed['tag_status'] == 'installed'
    assert store.field.records('tag_installations')[0]['lon'] == 1
    verify = f"/api/v1/tour/stations/{station['id']}/verify-tag"
    assert client.post(verify, json=scan(payload)).status_code == 200
    corrupt = payload[:-1] + ('1' if payload[-1] != '1' else '2')
    assert client.post(verify, json=scan(corrupt)).status_code == 403
    assert client.post(verify, json={**scan(payload),'lon':5}).status_code == 403
    rotated = approval(client, station, 'rotate_tag_key', token_factory)
    assert rotated['tag_revision'] == 2 and rotated['tag_status'] == 'planned'
    new_payload = tour_tags.tag_payload(rotated)
    install(client, rotated)
    old_rev = client.post(verify, json=scan(payload))
    assert old_rev.json()['detail']['code'] == 'tag_revision_stale'
    old_key = payload.split(':');old_key[3] = '2'
    assert client.post(verify, json=scan(':'.join(old_key))).json()['detail']['code'] == 'tag_key_inactive'
    assert client.post(verify, json=scan(new_payload)).status_code == 200
    approval(client, rotated, 'revoke_tag', token_factory)
    assert client.post(verify, json=scan(new_payload)).status_code == 409
    with store.field.connection() as db:
        assert db.execute('SELECT count(*) FROM tag_keys WHERE active=1').fetchone()[0] == 0


def test_counter_mirror_weak_replay_and_restart(client, monkeypatch):
    station = create_station(client, tag_mode='nfc_counter', tag_uid='04ABCDEF123456')
    code = tour_tags.tag_payload(station)
    def payload(counter, uid=station['tag_uid']):
        return 'https://field.test/nfc?' + urlencode(dict(tag=code, uid=uid, counter=f'{counter:06X}'))
    install(client, station, payload(1))
    path=f"/api/v1/tour/stations/{station['id']}/verify-tag"
    result=client.post(path,json=scan(payload(2)))
    assert result.json()['assurance']=='ضعیف'
    for count in (1,2):
        assert client.post(path,json=scan(payload(count))).json()['detail']['code']=='tag_replay'
    monkeypatch.setattr(store,'field',FieldStore(store.field.path))
    assert client.post(path,json=scan(payload(2))).status_code==403
    assert client.post(path,json=scan(payload(3, '04FFFFFFFFFFFF'))).status_code==403
    assert client.post(path,json=scan(payload(3))).status_code==200


def test_sun_official_nxp_vector_and_negative_cases():
    picc='EF963FF7828658A599F3041510671E88'
    assert verify_sun(picc,'94EED9EE65337086',bytes(16),bytes(16))==('04DE5F1EACC040',61)
    for encrypted, mac, meta, key in [(picc,'00'*8,bytes(16),bytes(16)),('00'*16,'00'*8,bytes(16),bytes(16)),(picc,'94EED9EE65337086',bytes([1])*16,bytes(16)),(picc,'94EED9EE65337086',bytes(16),bytes([1])*16)]:
        with pytest.raises(ValueError):verify_sun(encrypted,mac,meta,key)


def test_sun_provisioning_scans_replay_and_key_change(client, token_factory, monkeypatch):
    station=create_station(client,tag_mode='nfc_sun',tag_uid='04DE5F1EACC040')
    endpoint=f"/api/v1/tour/stations/{station['id']}/sun-provisioning"
    provision=client.post(endpoint)
    assert provision.status_code==200, provision.text
    assert provision.headers['cache-control']=='no-store'
    body=provision.json();ndef=bytes.fromhex(body['ndef_hex'])
    assert ndef[body['picc_data_offset']:body['picc_data_offset']+32]==b'0'*32
    assert ndef[body['mac_input_offset']:body['mac_input_offset']+4]==b'tag='
    assert ndef[body['mac_offset']:body['mac_offset']+16]==b'0'*16
    assert client.post(endpoint,headers=bearer(token_factory(roles=['security_officer']))).status_code==403
    install(client,station,sun_payload(station,1))
    endpoint=f"/api/v1/tour/stations/{station['id']}/verify-tag"
    proof=sun_payload(station,2)
    assert client.post(endpoint,json=scan(proof)).json()['assurance']=='قوی'
    assert client.post(endpoint,json=scan(proof)).json()['detail']['code']=='tag_replay'
    forged=sun_payload(station,3);forged=forged[:-1]+('0' if forged[-1]!='0' else '1')
    assert client.post(endpoint,json=scan(forged)).json()['detail']['code']=='invalid_sun'
    assert client.post(endpoint,json=scan(sun_payload(station,3))).status_code==200
    rotated=approval(client,station,'rotate_tag_key',token_factory)
    failed=client.post(f"/api/v1/tour/stations/{station['id']}/install",json=scan(sun_payload(rotated,3)))
    assert failed.json()['detail']['code']=='tag_replay'  # rotation never clears lifetime counter
    install(client,rotated,sun_payload(rotated,4))
    assert client.post(endpoint,json=scan(sun_payload(rotated,5))).status_code==200


def test_tasks_seal_number_choice_audio_and_dwell(client, token_factory, monkeypatch):
    station=create_station(client,min_dwell_seconds=30,media_capture_allowed=True)
    install(client,station)
    tasks=[]
    for payload in [dict(kind='number',label='فشار',min=0,max=10,unit='bar'),dict(kind='seal',label='پلمب',expected_value='S1'),dict(kind='choice',label='وضعیت',options=['سالم','خراب']),dict(kind='audio',label='صوت')]:
        result=client.post(f"/api/v1/tour/stations/{station['id']}/tasks",json=payload)
        assert result.status_code==201,result.text
        tasks.append(result.json())
    visit,headers=start_visit(client,token_factory,station)
    path=f"/api/v1/tour/station-visits/{visit['id']}"
    assert client.post(path+'/complete',headers=headers).status_code==409
    number=path+'/tasks/'+tasks[0]['id']
    for value in (-1,11,'5',True):
        assert client.post(number,headers=headers,json={'value':value}).status_code==422
    assert client.post(number,headers=headers,json={'value':10}).status_code==201
    seal=path+'/tasks/'+tasks[1]['id']
    result=client.post(seal,headers=headers,json={'value':'S2'})
    assert result.json()['anomaly'] is True and 'S1' in result.json()['evidence']
    replacement=client.post(f"/api/v1/tour/stations/{station['id']}/tasks/{tasks[1]['id']}/seal",json=dict(expected_value='S2',reason='تعویض مصوب آزمایشی'))
    assert replacement.status_code==201 and replacement.json()['previous_value']=='S1'
    assert store.field.get('station_visits',visit['id'])['tasks'][1]['expected_value']=='S1'
    choice=path+'/tasks/'+tasks[2]['id']
    assert client.post(choice,headers=headers,json={'value':'ناشناخته'}).status_code==422
    assert client.post(choice,headers=headers,json={'value':'سالم'}).status_code==201
    audio=client.post('/api/v1/media',headers=headers,json=dict(tour_id=visit['tour_id'],caption='صوت آزمایشی',media_type='audio')).json()
    assert client.post(path+'/tasks/'+tasks[3]['id'],headers=headers,json={'media_id':audio['id']}).status_code==201
    monkeypatch.setattr(store,'now',lambda:'2026-10-08T00:00:30+00:00')
    assert client.post(path+'/complete',headers=headers).status_code==200
    assert client.post(number,headers=headers,json={'value':0}).status_code==403
    assert len(client.get(path+'/results',headers=headers).json())==4
    assert store.field.verify_audit()


def test_matching_seal_and_media_policy(client,token_factory):
    station=create_station(client)
    install(client,station)
    task=client.post(f"/api/v1/tour/stations/{station['id']}/tasks",json=dict(kind='seal',label='پلمب',expected_value='OK')).json()
    assert client.post(f"/api/v1/tour/stations/{station['id']}/tasks",json=dict(kind='audio',label='صوت')).status_code==409
    visit,headers=start_visit(client,token_factory,station)
    result=client.post(f"/api/v1/tour/station-visits/{visit['id']}/tasks/{task['id']}",headers=headers,json={'value':'OK'})
    assert result.json()['anomaly'] is False
    assert client.post('/api/v1/media',headers=headers,json=dict(tour_id=visit['tour_id'],caption='ممنوع',media_type='image')).status_code==403
    assert client.post('/api/v1/media',headers=headers,json=dict(tour_id=visit['tour_id'],caption='صوت مجاز',media_type='audio')).status_code==201
    assert client.post(f"/api/v1/tour/stations/{station['id']}/tasks/{task['id']}/seal",json={'expected_value':'NEW','reason':''}).status_code==422


def test_two_person_visit_identity_scope_and_completion(client,token_factory):
    station=create_station(client,two_person_required=True)
    install(client,station)
    visit,headers=start_visit(client,token_factory,station)
    path=f"/api/v1/tour/station-visits/{visit['id']}"
    assert client.post(path+'/complete',headers=headers).status_code==403
    assert client.post(path+'/confirm',headers=headers,json=scan(tour_tags.tag_payload(station))).status_code==403
    second,_=link_and_enroll(client,token_factory,sub='guard-b',guard_id='AST-010')
    assert client.post(path+'/confirm',headers=second,json=scan(tour_tags.tag_payload(station))).status_code==200
    assert client.post(path+'/complete',headers=headers).status_code==200


@pytest.mark.parametrize('case',json.loads((Path(__file__).parent/'fixtures/qr_reference.json').read_text())['cases'],ids=lambda c:f"v{c['version']}-mask{c['mask']}")
def test_qr_reference_matrices(case):
    actual=[''.join('1' if dark else '0' for dark in row) for row in qr.matrix(case['text'],case['version'],case['mask'])]
    assert actual==case['rows']


def test_qr_limits_and_byte_capacity():
    for length,version in [(14,1),(15,2),(26,2),(42,3),(62,4),(84,5),(106,6)]:
        assert len(qr.matrix('x'*length))==17+version*4
    with pytest.raises(ValueError):qr.matrix('x'*107)
    with pytest.raises(ValueError):qr.matrix('x'*15,1)
    with pytest.raises(ValueError):qr.matrix('x',7)
    assert len(qr.matrix('سپهر'))==21


def test_cancel_revoked_visit_and_counter_transaction_rollback(client, token_factory):
    station=create_station(client,tag_mode='nfc_sun',tag_uid='04DE5F1EACC040')
    install(client,station,sun_payload(station,1))
    visit,headers=start_visit(client,token_factory,station,sun_payload(station,2))
    assert client.post(f"/api/v1/tour/{visit['tour_id']}/complete",headers=headers).status_code==409
    revoked=approval(client,station,'revoke_tag',token_factory)
    assert revoked['tag_status']=='revoked'
    path=f"/api/v1/tour/station-visits/{visit['id']}"
    assert client.post(path+'/complete',headers=headers).status_code==409
    cancelled=client.post(path+'/cancel',headers=headers,json={'reason':'تگ در حین بازدید باطل شد'})
    assert cancelled.status_code==200 and cancelled.json()['status']=='cancelled'
    assert client.post(f"/api/v1/tour/{visit['tour_id']}/complete",headers=headers).status_code==200


def test_no_tag_state_bypass_and_atomic_replay_rollback(client,token_factory):
    station=create_station(client,tag_mode='nfc_counter',tag_uid='04ABCDEF123456')
    def proof(counter):
        return 'https://field.test/nfc?'+urlencode(dict(tag=tour_tags.tag_payload(station),uid=station['tag_uid'],counter=f'{counter:06X}'))
    install(client,station,proof(1))
    before=store.field.audits()
    with pytest.raises(RuntimeError):
        with store.locked_state(),store.field.transaction():
            tour_tags.verify_tag(store.field.get('stations',station['id']),proof(2))
            raise RuntimeError('simulated rollback')
    assert client.post(f"/api/v1/tour/stations/{station['id']}/verify-tag",json=scan(proof(2))).status_code==200
    assert len(store.field.audits())==len(before)+1
    direct={k:v for k,v in station.items() if k not in ('id','tag_status','tag_revision','created_at')}
    assert client.put(f"/api/v1/tour/stations/{station['id']}",json={**direct,'tag_status':'revoked'}).status_code==422
    assert client.post(f"/api/v1/tour/stations/{station['id']}/tag-status",json={'tag_status':'revoked','reason':'دور زدن تأیید'}).status_code==422


def test_phase_zero_database_migration_preserves_entities(tmp_path, monkeypatch):
    from app import fieldstore
    migrations=fieldstore.MIGRATIONS
    with monkeypatch.context() as patch:
        patch.setattr(fieldstore,'MIGRATIONS',migrations[:2])
        old=FieldStore(tmp_path/'migration.sqlite3')
        old.save('existing',dict(id='PRESERVED',value='phase-zero'))
    upgraded=FieldStore(old.path)
    assert upgraded.get('existing','PRESERVED')['value']=='phase-zero'
    with upgraded.connection() as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0]==len(migrations)
        assert db.execute('SELECT count(*) FROM tag_keys').fetchone()[0]==0
    assert FieldStore(old.path).get('existing','PRESERVED') is not None


def test_sun_wrong_uid_and_duplicate_params_are_rejected(client):
    station=create_station(client,tag_mode='nfc_sun',tag_uid='04DE5F1EACC040')
    install(client,station,sun_payload(station,1))
    path=f"/api/v1/tour/stations/{station['id']}/verify-tag"
    proof=sun_payload({**station,'tag_uid':'04ABCDEF123456'},2)
    assert client.post(path,json=scan(proof)).json()['detail']['code']=='tag_uid_mismatch'
    valid=sun_payload(station,2)
    assert client.post(path,json=scan(valid+'&cmac=00')).status_code==403
    assert client.post(path,json=scan(valid)).status_code==200
    secret=tour_tags.active_key(station['id'])['meta_key']
    assert secret not in client.get('/api/v1/tour/stations').text
    assert secret not in client.get(f"/api/v1/tour/stations/{station['id']}/tag-sheet").text


def test_guard_assignment_uses_durable_zone_without_legacy_state(client,token_factory):
    zone='FIELD-ONLY'
    assert all(z['id']!=zone for z in store.state['zones'])
    response=client.put('/api/v1/tour/zones/'+zone,json=dict(name='محوطه مستقل شماتیک',points=[[0,0],[2,0],[2,2],[0,2]],media_capture_allowed=True))
    assert response.status_code==200
    scope=client.put('/api/v1/guards/AST-009/scope',json=dict(zone_id=zone,contractor_id='SCHEMATIC'))
    assert scope.status_code==200,scope.text
    def scoped_token(**kwargs):
        return token_factory(groups=['/zones/'+zone,'/contractors/SCHEMATIC'],**kwargs)
    headers,_=link_and_enroll(client,scoped_token)
    station=create_station(client,zone_id=zone)
    install(client,station)
    route=create_route(client,zone=zone)
    tour=client.post('/api/v1/tour',headers=headers,json={'route_id':route})
    assert tour.status_code==201
    listed=client.get('/api/v1/tour/stations',headers=headers)
    assert listed.status_code==200 and [s['id'] for s in listed.json()]==[station['id']]
    assert all(z['id']!=zone for z in store.state['zones'])
