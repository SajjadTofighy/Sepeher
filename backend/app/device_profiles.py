"""SMS command templates for tracker protocol families common in the Iranian market.

Most vehicle trackers sold in Iran, including locally branded units, use one of a few
widely cloned protocol families: GT06/Concox, TK103/Coban, or Teltonika FMB. The
templates follow those families' public manuals. Firmware differs between vendors,
so each profile must be checked against the installed unit's manual before field
use. No SMS gateway is connected; the rendered text is recorded with the device
password masked, and delivery stays simulated.
"""
from fastapi import HTTPException

MASK = '••••'
NOTE = 'الگو از مستندات عمومی خانواده پروتکل است؛ پیش از بهره‌برداری با دفترچه سازنده و نسخه firmware تجهیز نصب‌شده تطبیق دهید'


def tk103_interval(seconds):
    if seconds <= 255:
        return f'{seconds:03}s'
    if seconds % 60 == 0 and seconds // 60 <= 255:
        return f'{seconds // 60:03}m'
    raise ValueError('فاصله TK103 باید حداکثر ۲۵۵ ثانیه یا مضرب دقیقه تا ۲۵۵ دقیقه باشد')


def gt06_interval(seconds):
    if seconds < 10:
        raise ValueError('فاصله GT06 دست‌کم ۱۰ ثانیه است')
    return str(seconds)


PROFILES = {
    'generic_data': dict(
        label='اینترنت همراه (بدون فرمان پیامکی)', family='داده', default_password='',
        sms=None),
    'concox_gt06': dict(
        label='خانواده GT06 / Concox', family='GT06', default_password='',
        sms=dict(position='WHERE#', ping='STATUS#', diagnostics='PARAM#', restart='RESET#',
                 interval='TIMER,{interval}#'),
        interval=gt06_interval),
    'coban_tk103': dict(
        label='خانواده TK103 / Coban', family='TK103', default_password='123456',
        sms=dict(position='fix010s001n{password}', ping='imei{password}', diagnostics='check{password}',
                 interval='fix{interval}***n{password}'),
        interval=tk103_interval),
    'teltonika_fmb': dict(
        label='Teltonika FMB', family='FMB', default_password='',
        # FMB SMS syntax is "<login> <password> <command>"; empty credentials keep two spaces.
        sms=dict(position='{login} {password} getgps', ping='{login} {password} getstatus',
                 diagnostics='{login} {password} getinfo', restart='{login} {password} cpureset'),
        interval=None),
}


def profile(name):
    found = PROFILES.get(name)
    if found is None:
        raise HTTPException(422, 'پروفایل تجهیز ناشناخته است')
    return found


def render(asset, command, interval_seconds, *, masked=True):
    """Exact SMS text for one command; the stored copy never contains the device password."""
    spec = profile(asset.get('device_profile', 'generic_data'))
    template = (spec['sms'] or {}).get(command)
    if template is None:
        raise HTTPException(422, 'این فرمان برای پروفایل پیامکی تجهیز پشتیبانی نمی‌شود')
    interval = ''
    if '{interval}' in template:
        try:
            interval = spec['interval'](interval_seconds)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    password = asset.get('sms_password') or spec['default_password']
    login = asset.get('sms_login') or ''
    return template.format(interval=interval, password=MASK if masked and password else password,
                           login=MASK if masked and login else login)


def catalog():
    return [dict(id=key, label=value['label'], family=value['family'],
                 sms_commands=sorted((value['sms'] or {}).keys()), note=NOTE)
            for key, value in PROFILES.items()]
