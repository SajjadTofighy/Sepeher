"""Patrol integrity rules over durable scans and visits; shadow by default.

Each rule is a deterministic threshold over a configurable look-back window and
raises one evidence-bearing finding per subject until the condition clears.
Findings never create incidents automatically; humans review them.
"""
from collections import defaultdict
from datetime import timedelta
from itertools import combinations

from ..core import store
from ..core.sim import distance_km
from ..core.tracks import parse_timestamp
from . import findings

RULES = {
    'intel.integrity.short_dwell': 'توقف کوتاه تکرارشونده در ایستگاه',
    'intel.integrity.tag_replay': 'تکرار یا پسروی شمارنده تگ (نشانه شبیه‌سازی)',
    'intel.integrity.tag_distance': 'اسکن یک تگ توسط دو نگهبان در زمان نزدیک از دو مکان دور',
    'intel.integrity.clock': 'پسروی ساعت دستگاه',
    'intel.integrity.offline_repeat': 'ارسال آفلاین طولانی تکرارشونده',
}


def _guard_of(tours, tour_id):
    return tours.get(tour_id, {}).get('guard_id')


def _points(scans):
    return [(s['lon'], s['lat'], s['received_at']) for s in scans if s.get('lon') is not None and s.get('lat') is not None]


def _candidates(now):
    settings = store.state['settings']
    start = parse_timestamp(now) - timedelta(hours=settings['integrity_window_hours'])
    recent = lambda value: start <= parse_timestamp(value) <= parse_timestamp(now)
    tours = {t['id']: t for t in store.field.records('tour')}
    scans = [s for s in store.field.scans() if recent(s['received_at'])]
    found = defaultdict(dict)

    def add(rule, subject, rows, scope, values, thresholds):
        found[rule][subject] = dict(rows=rows, scope=scope, values=values, thresholds=thresholds)

    by_guard = defaultdict(list)
    for visit in store.field.records('station_visits'):
        if (visit['status'] == 'cancelled' and visit.get('completed_at') and recent(visit['completed_at'])
                and (parse_timestamp(visit['completed_at']) - parse_timestamp(visit['arrived_at'])).total_seconds()
                < visit['min_dwell_seconds']):
            by_guard[_guard_of(tours, visit['tour_id'])].append(visit)
    for guard_id, visits in by_guard.items():
        if guard_id and len(visits) >= settings['integrity_short_dwell_count']:
            add('intel.integrity.short_dwell', guard_id, [], visits[-1],
                dict(guard_id=guard_id, visit_ids=[v['id'] for v in visits], count=len(visits)),
                dict(count=settings['integrity_short_dwell_count']))
    by_station = defaultdict(list)
    for scan in scans:
        if scan['status'] == 'rejected' and scan.get('reason') == 'tag_replay':
            by_station[scan['station_id']].append(scan)
    for station_id, rows in by_station.items():
        add('intel.integrity.tag_replay', station_id, rows, rows[-1],
            dict(station_id=station_id, scan_ids=[s['id'] for s in rows], count=len(rows)), dict(count=1))
    located = defaultdict(list)
    for scan in scans:
        if scan['status'] != 'rejected' and scan.get('lon') is not None and scan.get('lat') is not None:
            located[scan['station_id']].append(scan)
    for station_id, rows in located.items():
        for a, b in combinations(rows, 2):
            minutes = abs((parse_timestamp(a['received_at']) - parse_timestamp(b['received_at'])).total_seconds()) / 60
            km = distance_km([a['lon'], a['lat']], [b['lon'], b['lat']])
            if (a['owner_sub'] != b['owner_sub'] and minutes <= settings['integrity_pair_minutes']
                    and km > settings['integrity_pair_km']):
                add('intel.integrity.tag_distance', station_id, [a, b], b,
                    dict(station_id=station_id, scan_ids=[a['id'], b['id']], distance_km=round(km, 3),
                         minutes=round(minutes, 1)),
                    dict(pair_minutes=settings['integrity_pair_minutes'], pair_km=settings['integrity_pair_km']))
                break
    clock, offline = defaultdict(list), defaultdict(list)
    for scan in scans:
        guard_id = _guard_of(tours, scan['tour_id'])
        if scan['evidence']['clock'] == 'regressed' or 'clock_regressed' in scan.get('offline_flags', []):
            clock[guard_id].append(scan)
        if 'offline_too_long' in scan.get('offline_flags', []):
            offline[guard_id].append(scan)
    for guard_id, rows in clock.items():
        if guard_id:
            add('intel.integrity.clock', guard_id, rows, rows[-1],
                dict(guard_id=guard_id, scan_ids=[s['id'] for s in rows], count=len(rows)), dict(count=1))
    for guard_id, rows in offline.items():
        if guard_id and len(rows) >= settings['integrity_offline_repeat_count']:
            add('intel.integrity.offline_repeat', guard_id, rows, rows[-1],
                dict(guard_id=guard_id, scan_ids=[s['id'] for s in rows], count=len(rows)),
                dict(count=settings['integrity_offline_repeat_count']))
    return found


def tick(now):
    settings = store.state['settings']
    window_from = (parse_timestamp(now) - timedelta(hours=settings['integrity_window_hours'])).isoformat()
    found = _candidates(now)
    for rule, subjects in found.items():
        for subject, data in subjects.items():
            values = dict(data['values'], zone_id=data['scope']['zone_id'], contractor_id=data['scope']['contractor_id'])
            sources = values.get('scan_ids') or values.get('visit_ids') or [subject]
            findings.raise_finding(
                rule_id=rule, kind='patrol_integrity', subject_ids=[subject], severity='high' if 'tag' in rule else 'medium',
                summary=RULES[rule], mode=settings['integrity_mode'], needs_incident=False, now_iso=now,
                evidence=dict(rule=RULES[rule], thresholds=data['thresholds'], window_from=window_from, window_to=now,
                              points=_points(data['rows']), values=values),
                sources=list(sources))
    for finding in list(store.state['findings']):
        if (finding['rule_id'] in RULES and finding['status'] != 'resolved'
                and finding['subject_ids'][0] not in found.get(finding['rule_id'], {})):
            findings.resolve_finding(finding['id'], now_iso=now)
