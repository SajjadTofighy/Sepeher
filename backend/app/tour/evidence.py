"""Deterministic field scan evidence and trust; GPS never proves presence alone."""
from datetime import timedelta
import hashlib

from ..core import store
from ..core.fieldstore import canonical
from ..core.sim import distance_km
from ..core.tracks import parse_timestamp


def sequence_for(tour, station_id):
    scheduled_id = tour.get('scheduled_tour_id')
    if not scheduled_id:
        return 'in_order'
    scheduled = store.field.get('scheduled_tours', scheduled_id)
    done = {v['station_id'] for v in store.field.records('station_visits')
            if v['tour_id'] == tour['id'] and v['status'] == 'completed'}
    pending = [id for id in scheduled['station_ids'] if id not in done]
    return 'in_order' if pending and pending[0] == station_id else 'out_of_order'


def request_hash(payload):
    return hashlib.sha256(canonical(payload.model_dump(mode='json')).encode()).hexdigest()


def clock_evidence(payload, received_at):
    if payload.device_time is None:
        return 'unknown'
    device = payload.device_time
    if payload.previous_device_time and device < payload.previous_device_time:
        return 'regressed'
    server = parse_timestamp(received_at)
    if payload.anchor_server_time and payload.anchor_device_time:
        elapsed = (device - payload.anchor_device_time).total_seconds()
        if elapsed < -1:
            return 'regressed'
        expected = payload.anchor_server_time + timedelta(seconds=elapsed)
        if abs((expected - server).total_seconds()) > store.state['settings']['field_clock_skew_seconds']:
            return 'skewed'
        return 'ok'
    return 'ok' if abs((device - server).total_seconds()) <= store.state['settings']['field_clock_skew_seconds'] else 'skewed'


def offline_flags(payload, received_at):
    if payload.device_time is None:
        return []
    flags = []
    if (parse_timestamp(received_at) - payload.device_time).total_seconds() > \
            store.state['settings']['max_offline_minutes'] * 60:
        flags.append('offline_too_long')
    if payload.previous_device_time and payload.device_time < payload.previous_device_time:
        flags.append('clock_regressed')
    return flags


def location_evidence(payload, station, owner_sub, received_at):
    if payload.lon is None or payload.lat is None:
        return 'unavailable'
    settings = store.state['settings']
    accuracy = payload.accuracy_m
    if accuracy is None or accuracy > settings['field_location_max_accuracy_m']:
        return 'unverified'
    point = [payload.lon, payload.lat]
    previous = next((row for row in reversed(store.field.scans()) if row['owner_sub'] == owner_sub
                     and row['lon'] is not None and row['lat'] is not None), None)
    if previous:
        seconds = (parse_timestamp(received_at) - parse_timestamp(previous['received_at'])).total_seconds()
        km = distance_km([previous['lon'], previous['lat']], point)
        if seconds <= 0 or km / seconds * 3600 > settings['field_location_max_speed_kmh']:
            return 'implausible'
        # Repeated exact accuracy across distant scans is suspicious, not proof of forgery.
        if previous.get('accuracy_m') == accuracy and km > 1:
            return 'implausible'
    meters = distance_km(point, [station['lon'], station['lat']]) * 1000
    return 'verified' if meters <= max(accuracy, 30) else 'unverified'


def tag_evidence(station, proof=None, manual=False, replay=False):
    if replay:
        return 'replay'
    if manual:
        return 'manual'
    return {'nfc_sun': 'sun_valid', 'nfc_counter': 'counter_ok',
            'qr_hmac': 'hmac_valid', 'code': 'hmac_valid'}[station['tag_mode']]


def trust(evidence, flags=()):
    if (evidence['tag'] in ('manual', 'replay', 'uid_only', 'paper') or evidence['location'] == 'implausible'
            or evidence['clock'] == 'regressed' or evidence['sequence'] == 'out_of_order'
            or evidence['dwell'] == 'too_short'):
        return 'low'
    if (evidence['tag'] == 'sun_valid' and evidence['location'] == 'verified'
            and evidence['clock'] == 'ok'):
        return 'medium' if 'offline_too_long' in flags else 'high'
    if evidence['tag'] in ('sun_valid', 'counter_ok', 'hmac_valid') and evidence['clock'] != 'skewed':
        return 'medium'
    return 'low'


def evaluate(station, tour, payload, *, tag, received_at, dwell='too_short'):
    evidence = dict(tag=tag, location=location_evidence(payload, station, tour['owner_sub'], received_at),
                    sequence=sequence_for(tour, station['id']), dwell=dwell,
                    clock=clock_evidence(payload, received_at))
    return evidence, trust(evidence)
