"""Verification and deterministic time flags for signed field queue records."""
import hashlib
import hmac

from fastapi import HTTPException

from . import store
from .fieldstore import canonical
from .tracks import parse_timestamp


def verify(record):
    device = store.field.device(record.device_id)
    if device is None or device['status'] != 'active':
        store.audit('رد رکورد آفلاین دستگاه نامعتبر', record.device_id)
        raise HTTPException(403, 'دستگاه ثبت‌شده و فعال لازم است')
    message = canonical(record.model_dump(mode='json', exclude={'signature'})).encode()
    expected = hmac.new(device['device_secret'].encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(record.signature, expected):
        store.audit('رد امضای رکورد آفلاین', record.device_id)
        raise HTTPException(403, 'امضای رکورد آفلاین معتبر نیست')
    return device


def clock_regressed(record):
    return bool(record.previous_device_time and
                parse_timestamp(record.captured_at) < parse_timestamp(record.previous_device_time))


def offline_too_long(record, received_at):
    return (parse_timestamp(received_at) - parse_timestamp(record.captured_at)).total_seconds() > \
        store.state['settings']['max_offline_minutes'] * 60
