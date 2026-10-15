"""Request hardening: in-memory token-bucket rate limits and a JSON body ceiling.

Emergency reports are never rejected for rate: excess is flagged and audited only.
The bucket clock is store.now(), so limits are deterministic under an injected clock.
"""
import re
import threading

from fastapi import HTTPException

from ..core import store
from ..core.tracks import parse_timestamp

# (method, path pattern) -> category; patterns cover every enrollment, PIN, scan and upload entry point.
CATEGORIES = (
    ('POST', re.compile(r'^/api/v1/devices/enroll$'), 'enroll'),
    ('POST', re.compile(r'^/api/v1/tour/unlock$'), 'pin'),
    ('POST', re.compile(r'^/api/v1/tour/[^/]+/check-in$'), 'pin'),
    ('POST', re.compile(r'^/api/v1/tour/stations/[^/]+/(visits|manual-scan|verify-tag)$'), 'scan'),
    ('POST', re.compile(r'^/api/v1/tour/offline/scans$'), 'scan'),
    ('POST', re.compile(r'^/api/v1/media(/uploads)?$'), 'upload'),
    ('PUT', re.compile(r'^/api/v1/media/uploads/[^/]+$'), 'upload'),
    ('PUT', re.compile(r'^/api/v1/media/[^/]+/content$'), 'upload'),
    ('POST', re.compile(r'^/api/v1/tour/(safety-events|offline/emergency)$'), 'emergency'),
)
# Raw binary bodies have their own per-chunk ceilings in the media router.
RAW_BODY = (re.compile(r'^/api/v1/media/uploads/[^/]+$'), re.compile(r'^/api/v1/media/[^/]+/content$'))
MAX_KEYS = 10000


def category(method, path):
    return next((name for verb, pattern, name in CATEGORIES if verb == method and pattern.match(path)), None)


def raw_body(path):
    return any(pattern.match(path) for pattern in RAW_BODY)


class TokenBucket:
    def __init__(self):
        self.buckets = {}
        self.lock = threading.Lock()

    def take(self, key, per_minute, now):
        """Consume one token; False when the bucket is empty."""
        with self.lock:
            if len(self.buckets) > MAX_KEYS:
                self.buckets.clear()
            tokens, last = self.buckets.get(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + max(0.0, now - last) * per_minute / 60)
            allowed = tokens >= 1
            self.buckets[key] = (tokens - 1 if allowed else tokens, now)
            return allowed

    def reset(self):
        with self.lock:
            self.buckets.clear()
        _last_audit.clear()


limiter = TokenBucket()
_last_audit = {}


def audit_once(key, now, action, detail=''):
    # A flood must not flood the audit chain: one record per key per minute.
    if now - _last_audit.get(key, float('-inf')) >= 60:
        if len(_last_audit) > MAX_KEYS:
            _last_audit.clear()
        _last_audit[key] = now
        store.audit(action, key[1], detail, actor='سامانه')


def check_rate(scope, principal, method, path):
    """Raise 429 for over-limit requests; emergency reports are only flagged."""
    name = category(method, path)
    if name is None:
        return
    per_minute = store.setting('rate_limit_per_minute', name)
    now = parse_timestamp(store.now()).timestamp()
    client = (scope.get('client') or ('unknown', 0))[0]
    key = (name, principal.sub if principal else 'ip:' + client)
    if limiter.take(key, per_minute, now):
        return
    if name == 'emergency':
        scope.setdefault('state', {})['rate_flagged'] = True
        audit_once(key, now, 'اعلام خطر فراتر از نرخ مجاز؛ پذیرفته و پرچم شد')
        return
    audit_once(key, now, 'رد درخواست فراتر از نرخ مجاز', name)
    raise HTTPException(429, {'code': 'rate_limited', 'message': 'تعداد درخواست‌ها از حد مجاز بیشتر است؛ کمی بعد دوباره تلاش کنید'},
                        headers={'Retry-After': str(max(1, round(60 / per_minute)))})


def body_limit():
    return store.setting('max_json_body_bytes')


async def bounded_receive(scope, receive, limit):
    """Read the whole request body once, rejecting it beyond the ceiling, and replay it."""
    declared = dict(scope['headers']).get(b'content-length')
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise HTTPException(413, {'code': 'body_too_large', 'message': 'حجم بدنه درخواست از سقف مجاز بیشتر است'})
    chunks, size, more = [], 0, True
    while more:
        message = await receive()
        if message['type'] != 'http.request':
            return receive
        chunk = message.get('body', b'')
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, {'code': 'body_too_large', 'message': 'حجم بدنه درخواست از سقف مجاز بیشتر است'})
        chunks.append(chunk)
        more = message.get('more_body', False)
    body, sent = b''.join(chunks), False

    async def replay():
        nonlocal sent
        if not sent:
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        return await receive()
    return replay
