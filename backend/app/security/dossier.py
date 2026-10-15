"""Evidence for the AFTA (افتا) security-assessment inquiry, read from the running system.

The inquiry and any assessment are carried out by the organisation and an approved
laboratory; this module only assembles verifiable facts: access control per endpoint,
response security headers, security settings, cryptography, stored data categories,
audit-chain health and the documented residual risks. It changes nothing.
"""
import os

from . import auth, authz
from .. import store
from ..field.media import jalali_stamp

CRYPTOGRAPHY = (
    ('اعتبارسنجی توکن OIDC', 'RS256 (RSA-SHA256) با JWKS کش‌شده؛ هر الگوریتم دیگر رد می‌شود', 'PyJWT + cryptography'),
    ('احراز تگ NTAG 424 DNA', 'AES-128 CBC (PICCData) و AES-CMAC (SUN MAC)', 'cryptography'),
    ('امضای برچسب QR', 'HMAC-SHA256 کوتاه‌شده به ۱۲۸ بیت با کلید نسخه‌دار', 'hmac (کتابخانه استاندارد)'),
    ('امضای رکورد صف آفلاین', 'HMAC-SHA256 با راز دستگاه ثبت‌شده', 'hmac (کتابخانه استاندارد)'),
    ('رمز محلی و رمز اضطرار', 'scrypt (n=16384, r=8, p=1) با salt تصادفی و مقایسه زمان‌ثابت', 'hashlib (کتابخانه استاندارد)'),
    ('زنجیره ممیزی و یکپارچگی رسانه', 'SHA-256', 'hashlib (کتابخانه استاندارد)'),
    ('ورود وب و میدانی', 'OIDC Authorization Code با PKCE S256؛ توکن فقط در حافظه', 'Web Crypto مرورگر'),
)

DATA_INVENTORY = (
    ('guards', 'هویت و پیوند نگهبان', True, 'تا پایان همکاری؛ تصمیم کارفرما'),
    ('devices', 'دستگاه ثبت‌شده و آخرین ارتباط', True, 'تا ابطال؛ تصمیم کارفرما'),
    ('tour', 'گشت پیاده', True, 'تصمیم کارفرما (پرسش باز نگهداری)'),
    ('station_visits', 'بازدید ایستگاه', True, 'تصمیم کارفرما'),
    ('field_safety_events', 'اعلام خطر، عدم تحرک و رمز اضطرار', True, 'تصمیم کارفرما؛ رمز اضطرار فقط نقش امنیتی'),
    ('messages', 'پیام میدانی', True, 'تصمیم کارفرما'),
    ('field_reports', 'گزارش میدانی دسته‌بندی‌شده', True, 'تصمیم کارفرما'),
    ('media', 'رسانه میدانی (فایل جدا با sha256)', True, 'media_retention_days به تفکیک دسته؛ legal_hold مانع حذف'),
    ('device_reports', 'قابلیت و باتری دستگاه برای پایلوت (بدون موقعیت)', False, 'تا پایان پایلوت'),
    ('approvals', 'تأیید دونفره', False, 'دائمی'),
)

RESIDUAL_RISKS = (
    'QR ایستا قابل عکس‌برداری است؛ احراز کامل NTAG 424 در Web NFC ممکن نیست (فاز ۸).',
    'کش رمزشده IndexedDB و صف آفلاین کلاینت (فاز ۴) هنوز ساخته نشده است.',
    'حذف انتهای زنجیره ممیزی بدون مرجع بیرونی WORM یا SOC تشخیص‌پذیر نیست.',
    'تغییر نقش در کیکلاک تأیید دونفره بومی ندارد؛ جبران با Admin Events و گزارش ممیز.',
    'محدودیت نرخ درون‌حافظه‌ای و تک‌فرایندی است؛ در استقرار چندفرایندی پروکسی هم باید محدود کند.',
    'HA، تکرار پایگاه و افزونگی پیاده نشده است.',
    'آزمون نفوذ، بازبینی کد مستقل و تمرین بازیابی روی سرور واقعی انجام نشده است.',
)

SECURITY_SETTINGS = ('classification_label', 'rate_limit_per_minute', 'max_json_body_bytes', 'shadow_mode',
                     'integrity_mode', 'media_retention_days', 'media_max_bytes', 'max_offline_minutes',
                     'field_clock_skew_seconds', 'field_sos_escalation_seconds', 'message_urgent_escalation_seconds',
                     'retention_days', 'queue_reveal')


def endpoints():
    from fastapi.routing import APIRoute
    from ..main import app
    public = {'/api/v1/health', '/api/v1/auth/config'}
    rows = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith('/api/v1/'):
            continue
        for method in sorted(route.methods - {'HEAD', 'OPTIONS'}):
            mandatory = authz.protected(route.path)
            special = route.path == '/api/v1/tour/offline/emergency' and method == 'POST'
            rows.append(dict(method=method, path=route.path,
                             authentication='public' if route.path in public else 'device_signature' if special
                             else 'required' if mandatory else 'optional_unless_enforce_all',
                             permission=authz.path_permission(route.path, method) or '',
                             roles=sorted(authz.PERMISSIONS.get(authz.path_permission(route.path, method) or '', ()))))
    return sorted(rows, key=lambda r: (r['path'], r['method']))


def build():
    now = store.now()
    settings = store.state['settings']
    headers = {k: v for k, v in auth.response_metadata('/api/v1/health').items() if k not in ('X-Server-Time', 'X-Classification')}
    counts = {}
    for kind, *_ in DATA_INVENTORY:
        counts[kind] = len(store.field.devices()) if kind == 'devices' else len(store.field.records(kind))
    return dict(
        generated_at=now, generated_at_jalali=jalali_stamp(now),
        classification_label=settings['classification_label'], organization=settings['organization'],
        system=dict(name='Sepehr Command — گشت نگهبانی', version='1.0.0', hosting='استقرار داخلی بدون وابستگی اینترنتی در زمان اجرا',
                    auth_mode=auth.auth_mode(),
                    enforce_all=os.environ.get('SEPEHR_AUTH_ENFORCE_ALL', 'false').lower() == 'true',
                    oidc_issuer_configured=bool(os.environ.get('SEPEHR_OIDC_ISSUER'))),
        endpoints=endpoints(), permissions={k: sorted(v) for k, v in authz.PERMISSIONS.items()},
        response_headers=headers,
        settings={k: settings[k] for k in SECURITY_SETTINGS},
        cryptography=[dict(purpose=p, algorithm=a, implementation=i) for p, a, i in CRYPTOGRAPHY],
        data_inventory=[dict(store=k, description=d, personal=personal, retention=r, records=counts[k])
                        for k, d, personal, r in DATA_INVENTORY],
        audit_chain=dict(valid=store.field.verify_audit(), count=len(store.field.audits()),
                         scope='persistent SQLite chain; not WORM storage'),
        residual_risks=list(RESIDUAL_RISKS),
    )
