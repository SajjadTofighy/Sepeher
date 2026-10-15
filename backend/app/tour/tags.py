"""Scoped station tags; secret keys and anti-replay counters are durable."""
import hashlib
import hmac
import re
import secrets
from urllib.parse import parse_qs, urlsplit
from fastapi import HTTPException
from ..core import store
from .sun import verify_sun


def denied(code, message, status=403):
    raise HTTPException(status, dict(code=code, message=message))


def active_key(station_id, kid=None):
    with store.field.connection() as db:
        query = 'SELECT * FROM tag_keys WHERE station_id=? AND active=1'
        args = [station_id]
        if kid is not None:
            query += ' AND kid=?'
            args.append(kid)
        row = db.execute(query, args).fetchone()
    if not row:
        denied('tag_key_inactive', 'نسخه کلید تگ فعال نیست')
    return dict(row)


def new_key(station_id):
    with store.field.connection() as db:
        versions = [int(row[0]) for row in db.execute('SELECT kid FROM tag_keys WHERE station_id=?', (station_id,))]
        kid = str(max(versions, default=0) + 1)
        db.execute('UPDATE tag_keys SET active=0 WHERE station_id=?', (station_id,))
        db.execute('INSERT INTO tag_keys VALUES(?,?,?,?,?,1)',
                   (station_id, kid, secrets.token_hex(32), secrets.token_hex(16), secrets.token_hex(16)))
    return kid


def tag_payload(station):
    key = active_key(station['id'])
    prefix = f"SPH2:{key['kid']}:{station['id']}:{station['tag_revision']}"
    # 128-bit truncated HMAC, hexadecimal, to fit QR version <=6 at level M.
    mac = hmac.new(bytes.fromhex(key['hmac_key']), prefix.encode('ascii'), hashlib.sha256).digest()[:16].hex()
    return prefix + ':' + mac


def counter_once(station_id, counter):
    with store.field.connection() as db:
        row = db.execute('SELECT counter FROM tag_counters WHERE station_id=?', (station_id,)).fetchone()
        if row and counter <= row[0]:
            denied('tag_replay', 'شمارنده تگ تکراری یا عقب‌رفته است')
        db.execute('INSERT INTO tag_counters VALUES(?,?) ON CONFLICT(station_id) DO UPDATE SET counter=excluded.counter', (station_id, counter))


def verify_tag(station, payload):
    """Validate and consume proof inside the caller's shared field transaction."""
    if station['tag_status'] in ('damaged', 'revoked'):
        denied('tag_unavailable', 'تگ آسیب‌دیده یا ابطال‌شده معتبر نیست')
    query, raw_query = {}, ''
    if not payload.startswith('SPH2:'):
        url = urlsplit(payload)
        if url.scheme not in ('https', 'http') or not url.netloc or url.fragment:
            denied('invalid_tag', 'ساختار برچسب معتبر نیست')
        raw_query = url.query
        try:
            query = parse_qs(raw_query, strict_parsing=True)
        except ValueError:
            denied('invalid_tag', 'پارامتر برچسب معتبر نیست')
        if any(len(values) != 1 for values in query.values()):
            denied('invalid_tag', 'پارامتر تکراری برچسب مجاز نیست')
        payload = query.get('tag', [''])[0]
    match = re.fullmatch(r'SPH2:([1-9][0-9]*):(STN-[a-f0-9]{24}):([1-9][0-9]*):([a-f0-9]{32})', payload)
    if not match or match[2] != station['id']:
        denied('invalid_tag', 'برچسب متعلق به این ایستگاه نیست')
    kid, _, rev, supplied = match.groups()
    if int(rev) != station['tag_revision']:
        denied('tag_revision_stale', 'نسخه برچسب قدیمی است')
    key = active_key(station['id'], kid)
    expected = tag_payload(station).rsplit(':', 1)[1]
    if not hmac.compare_digest(expected, supplied):
        denied('invalid_tag', 'امضای برچسب معتبر نیست')
    counter, assurance = None, 'ایستا'
    if station['tag_mode'] == 'nfc_counter':
        if set(query) != {'tag', 'uid', 'counter'} or not re.fullmatch(r'[0-9a-fA-F]{6}', query['counter'][0]):
            denied('invalid_tag', 'URL شمارنده NFC معتبر نیست')
        if not re.fullmatch(r'[0-9A-Fa-f]{14}', query['uid'][0]):
            denied('invalid_tag', 'ساختار UID معتبر نیست')
        uid = query['uid'][0].upper()
        if not hmac.compare_digest(uid, station['tag_uid'].upper()):
            denied('tag_uid_mismatch', 'شناسه تگ با ایستگاه تطابق ندارد')
        counter = int(query['counter'][0], 16)
        assurance = 'ضعیف'
    elif station['tag_mode'] == 'nfc_sun':
        # Fixed personalization profile: MACInput starts at raw "tag=" and
        # includes encrypted PICCData and the literal "&cmac=" prefix.
        if set(query) != {'tag', 'picc', 'cmac'} or not re.fullmatch(r'tag=SPH2:[^&]+&picc=[0-9A-Fa-f]{32}&cmac=[0-9A-Fa-f]{16}', raw_query):
            denied('invalid_tag', 'پروفایل URL تگ SUN معتبر نیست')
        try:
            uid, counter = verify_sun(query['picc'][0], query['cmac'][0], bytes.fromhex(key['meta_key']),
                                      bytes.fromhex(key['file_key']), raw_query[:-16].encode('ascii'))
        except ValueError:
            denied('invalid_sun', 'امضای SUN معتبر نیست')
        if not hmac.compare_digest(uid, station['tag_uid'].upper()):
            denied('tag_uid_mismatch', 'شناسه SUN متعلق به ایستگاه نیست')
        assurance = 'قوی'
    elif query:
        denied('invalid_tag', 'این حالت برچسب URL نمی‌پذیرد')
    if counter is not None:
        counter_once(station['id'], counter)
    return dict(station_id=station['id'], tag_revision=int(rev), kid=kid, assurance=assurance, counter=counter)


def change_station_tag(station, action):
    if action == 'revoke_tag':
        station['tag_status'] = 'revoked'
        with store.field.connection() as db:
            db.execute('UPDATE tag_keys SET active=0 WHERE station_id=?', (station['id'],))
    else:
        new_key(station['id'])
        station['tag_status'] = 'planned'
    station['tag_revision'] += 1
    # The lifetime counter is deliberately never reset by key rotation.
    store.field.save('stations', station)
