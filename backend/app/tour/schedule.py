"""Durable, explicitly approved walking-tour schedules and bounded guard queues."""
from datetime import date, datetime, timedelta, timezone
import random
import secrets

from fastapi import HTTPException

from .. import engine, store
from ..tracks import parse_timestamp


def default_pattern():
    segments = []
    for interval in store.state['settings']['intel_shifts']:
        if interval == 'تمام شبانه‌روز':
            segments.append(dict(start='00:00', duration_minutes=1440))
            continue
        first, last = interval.replace('-', '–').split('–')
        a, b = [int(h) * 60 + int(m) for h, m in (value.split(':') for value in (first, last))]
        segments.append(dict(start=first, duration_minutes=(b - a) % 1440 or 1440))
    return dict(id='DEFAULT', name='شیفت‌های پیش‌فرض گزارش', segments=segments, cycle=None,
                breaks=[], created_at='1970-01-01T00:00:00+00:00')


def pattern_record(id):
    return default_pattern() if id == 'DEFAULT' else store.field.get('shift_patterns', id)


def local_day(value):
    return parse_timestamp(value).astimezone(engine.TEHRAN).date()


def shift_window(day, segment):
    hour, minute = map(int, segment['start'].split(':'))
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=engine.TEHRAN)
    return start, start + timedelta(minutes=segment['duration_minutes'])


def on_cycle(day, cycle):
    if not cycle:
        return True
    anchor = date.fromisoformat(cycle['anchor_date'])
    length = cycle['on_days'] + cycle['off_days']
    return ((day - anchor).days % length) < cycle['on_days']


def ordered_stations(route, rng):
    ids = route['station_ids'][:]
    if route.get('order_mode', 'fixed') == 'fixed':
        if ((route.get('fixed_first') and ids[0] != route['fixed_first'])
                or (route.get('fixed_last') and ids[-1] != route['fixed_last'])
                or any(ids.index(a) >= ids.index(b) for a, b in route.get('must_precede', []))):
            raise HTTPException(409, 'ترتیب ثابت با قیود تقدم سازگار نیست')
        return ids
    first, last = route.get('fixed_first'), route.get('fixed_last')
    edges = route.get('must_precede', [])[:]
    if first:
        edges += [(first, other) for other in ids if other != first]
    if last:
        edges += [(other, last) for other in ids if other != last]
    remaining = set(ids)
    result = []
    while remaining:
        available = sorted(node for node in remaining if all(a not in remaining for a, b in edges if b == node))
        if not available:
            raise HTTPException(422, 'قیود تقدم مسیر چرخه دارند')
        chosen = rng.choice(available)
        result.append(chosen)
        remaining.remove(chosen)
    return result


def _slot(start, end, breaks, tour_number, total, jitter_percent, rng):
    minutes = int((end - start).total_seconds() // 60)
    segments = [(0, minutes)]
    for item in breaks:
        left, right = item['start_offset_minutes'], item['start_offset_minutes'] + item['duration_minutes']
        segments = [(a, b) for x, y in segments for a, b in ((x, min(y, left)), (max(x, right), y)) if a < b]
    usable = sum(b - a for a, b in segments)
    if usable < total:
        raise HTTPException(409, 'پنجره شیفت برای دورها فضای کافی ندارد')
    nominal = int(usable * (tour_number + 0.5) / total)
    jitter = round(usable / total * jitter_percent / 100)
    target = max(0, min(usable - 1, nominal + rng.randint(-jitter, jitter)))
    for a, b in segments:
        width = b - a
        if target < width:
            due = start + timedelta(minutes=a + target)
            return due, min(end, start + timedelta(minutes=b))
        target -= width
    raise AssertionError('unreachable slot')


def subset_route(route, station_ids):
    """The route restricted to this tour's stations; precedence only between selected stations."""
    keep = set(station_ids)
    return {**route, 'station_ids': [id for id in route['station_ids'] if id in keep],
            'must_precede': [[a, b] for a, b in route.get('must_precede', []) if a in keep and b in keep]}


def materialize(schedule, day, *, rng_factory=None):
    """Create only today/tomorrow, with stable keys and persisted random seeds."""
    today = local_day(store.now())
    if day not in (today, today + timedelta(days=1)) or schedule['status'] != 'approved':
        return []
    if not (date.fromisoformat(schedule['first_date']) <= day <= date.fromisoformat(schedule['last_date'])):
        return []
    pattern = pattern_record(schedule['pattern_id'])
    route = store.field.get('routes', schedule['route_id'])
    if not on_cycle(day, pattern['cycle']):
        return []
    rows = []
    for index, segment in enumerate(pattern['segments']):
        start, end = shift_window(day, segment)
        for number in range(schedule['tours_per_shift']):
            key = f"{schedule['id']}:{day.isoformat()}:{index}:{number}"
            existing = store.field.get('scheduled_tours', key)
            if existing:
                rows.append(existing)
                continue
            seed = secrets.token_hex(32)
            rng = rng_factory(seed) if rng_factory else random.Random(int(seed, 16))
            due, slot_end = _slot(start, end, pattern['breaks'], number, schedule['tours_per_shift'],
                                  store.state['settings']['tour_time_jitter_percent'], rng)
            warnings, selection = [], dict(selection_mode='all', proposed_station_ids=[], selection_finding_id=None)
            visit = route
            if route.get('coverage_mode') == 'optimized':
                from ..intel import patrol_game
                horizon = segment['duration_minutes'] / 60 / schedule['tours_per_shift']
                chosen, proposed, finding_id, blocked = patrol_game.select_route_stations(
                    route, horizon, rng, store.now(), key)
                visit = subset_route(route, chosen)
                warnings.extend(blocked)
                selection = dict(selection_mode='optimized' if not blocked else 'all', proposed_station_ids=proposed,
                                 selection_finding_id=finding_id)
            stations = ordered_stations(visit, rng)
            heat = store.state['settings']['heat_profile']
            if day.month in heat['months'] and engine.in_schedule(heat['restricted_hours'], due.strftime('%H:%M')):
                warnings.append('برنامه در ساعات محدودیت گرما قرار دارد')
            if (slot_end - due).total_seconds() / 60 > heat['max_continuous_minutes']:
                warnings.append('مدت گشت پیاده از سقف پروفایل گرما بیشتر است')
            row = dict(id=key, schedule_id=schedule['id'], route_id=route['id'], guard_id=route['guard_id'],
                       owner_sub=store.field.get('guards', route['guard_id']).get('keycloak_sub'),
                       zone_id=schedule['zone_id'], contractor_id=schedule['contractor_id'],
                       service_date=day.isoformat(), segment_index=index, tour_number=number,
                       due_at=due.astimezone(timezone.utc).isoformat(), ends_at=slot_end.astimezone(timezone.utc).isoformat(),
                       station_ids=stations, status='queued', warnings=warnings, handover_id=None, tour_id=None, seed=seed,
                       **selection)
            emergency = store.field.get('emergency_modes', schedule['zone_id'])
            if emergency and emergency['active']:
                row.update(status='excused', warnings=[*warnings, 'وضعیت اضطرار'])
            store.field.save('scheduled_tours', row)
            rows.append(row)
    return rows


def queue_rows(principal, rows):
    if 'guard' not in principal.roles:
        return rows
    if store.state['settings']['queue_reveal'] == 'all':
        # A guard never sees the shadow proposal of a future unannounced subset.
        return [{**row, 'proposed_station_ids': [], 'selection_finding_id': None} for row in rows]
    count = store.state['settings']['queue_reveal_count']
    result = []
    for row in rows:
        visited = {v['station_id'] for v in store.field.records('station_visits')
                   if v.get('tour_id') == row.get('tour_id') and v.get('status') == 'completed'}
        remaining = [id for id in row['station_ids'] if id not in visited]
        result.append({**row, 'station_ids': remaining[:count], 'proposed_station_ids': [], 'selection_finding_id': None})
    return result
