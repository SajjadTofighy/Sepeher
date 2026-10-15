"""Printable AFTA (افتا) inquiry letter and evidence summary from a security dossier.

Pure rendering without store access, shared by the auditor API and
scripts/security_dossier.py. Every value is escaped; no external resources are loaded.
The letter is a draft: letterhead, number, signatory and regulatory references are
completed by the organisation before sending.
"""
from html import escape

STYLE = """body{font-family:Vazirmatn,Tahoma,sans-serif;direction:rtl;margin:40px;line-height:2;color:#14212b}
h1{font-size:20px}h2{font-size:16px;margin-top:24px}table{width:100%;border-collapse:collapse;font-size:12px}
td,th{border:1px solid #c9d3da;padding:4px 8px;text-align:right}th{background:#f1f5f7}
.classification{text-align:center;font-weight:700;color:#9b1c1c}.muted{color:#5b6c78;font-size:12px}
.blank{display:inline-block;min-width:160px;border-bottom:1px dotted #5b6c78}code{direction:ltr;unicode-bidi:embed}"""


def _page(title, classification, body):
    label = escape(classification)
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>{escape(title)}</title>'
            f'<style>{STYLE}</style></head><body><div class="classification">{label}</div>{body}'
            f'<div class="classification">{label}</div></body></html>')


def _table(headers, rows):
    head = ''.join(f'<th>{escape(str(h))}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{escape(str(c))}</td>' for c in row) + '</tr>' for row in rows)
    return f'<table><tr>{head}</tr>{body}</table>'


def render_letter(dossier, attachments=()):
    counts = {}
    for row in dossier['endpoints']:
        counts[row['authentication']] = counts.get(row['authentication'], 0) + 1
    personal = [d['description'] for d in dossier['data_inventory'] if d['personal']]
    attachment_rows = [(a['path'], a['sha256']) for a in attachments]
    body = f"""
<p>شماره: <span class="blank"></span> &nbsp; تاریخ: <span class="blank"></span> &nbsp; پیوست: دارد</p>
<p>به: مرکز مدیریت راهبردی افتا <span class="muted">(عنوان و نشانی گیرنده را واحد حراست تأیید کند)</span></p>
<p>از: {escape(dossier['organization'])} — حراست</p>
<p>موضوع: استعلام الزام و دامنه ارزیابی امنیتی سامانه «{escape(dossier['system']['name'])}»</p>
<p>با سلام و احترام، به استحضار می‌رساند سامانه یادشده برای پایش گشت نگهبانی، اعلام خطر نیروی میدانی و ثبت شواهد حضور در تأسیسات شرکت در دست پایلوت است. با توجه به قرار داشتن تأسیسات در زمره زیرساخت‌های حیاتی، خواهشمند است موارد زیر اعلام فرمایید:</p>
<ol>
<li>آیا این سامانه مشمول ارزیابی امنیتی الزامی پیش از بهره‌برداری است؟</li>
<li>سطح، دامنه و روش ارزیابی لازم (از جمله آزمون نفوذ و بازبینی کد) و آزمایشگاه‌های مورد تأیید کدام‌اند؟</li>
<li>مستندات و شواهد تکمیلی مورد نیاز برای ارزیابی چیست؟</li>
</ol>
<h2>خلاصه مشخصات سامانه</h2>
<ul>
<li>میزبانی: {escape(dossier['system']['hosting'])}؛ حالت احراز هویت: {escape(dossier['system']['auth_mode'])}؛ اعمال احراز هویت روی همه مسیرها: {'بله' if dossier['system']['enforce_all'] else 'خیر (فقط مسیرهای گشت و ممیزی)'}.</li>
<li>هویت: کیکلاک داخلی با OIDC و PKCE؛ تصمیم دسترسی سمت سرور بر اساس نقش و محوطه.</li>
<li>مسیرهای API: {len(dossier['endpoints'])} مسیر؛ احراز اجباری {counts.get('required', 0)}، امضای دستگاه {counts.get('device_signature', 0)}، عمومی {counts.get('public', 0)}، اختیاری تا فعال‌سازی سراسری {counts.get('optional_unless_enforce_all', 0)}.</li>
<li>داده شخصی ذخیره‌شده: {escape('، '.join(personal))}.</li>
<li>زنجیره ممیزی: {'سالم' if dossier['audit_chain']['valid'] else 'ناسازگار'} با {dossier['audit_chain']['count']} رکورد ({escape(dossier['audit_chain']['scope'])}).</li>
</ul>
<h2>ریسک‌های باقی‌مانده اعلام‌شده</h2>
<ul>{''.join(f'<li>{escape(r)}</li>' for r in dossier['residual_risks'])}</ul>
<h2>پیوست‌ها</h2>
{_table(('فایل', 'SHA-256'), attachment_rows) if attachment_rows else '<p>پرونده شواهد فنی سامانه.</p>'}
<p class="muted">این نامه پیش‌نویس تولید سامانه است؛ ارجاع به ضوابط و مقررات و امضا توسط حراست تکمیل می‌شود. تولید: {escape(dossier['generated_at_jalali'])}</p>
<p>امضا: <span class="blank"></span></p>"""
    return _page('استعلام ارزیابی امنیتی', dossier['classification_label'], body)


def render_summary(dossier, extra_sections=()):
    sections = [
        ('کنترل دسترسی مسیرها', _table(('روش', 'مسیر', 'احراز', 'مجوز', 'نقش‌ها'),
                                        [(e['method'], e['path'], e['authentication'], e['permission'], '، '.join(e['roles']))
                                         for e in dossier['endpoints']])),
        ('سربرگ‌های امنیتی پاسخ', _table(('سربرگ', 'مقدار'), sorted(dossier['response_headers'].items()))),
        ('رمزنگاری', _table(('کاربرد', 'الگوریتم', 'پیاده‌سازی'),
                            [(c['purpose'], c['algorithm'], c['implementation']) for c in dossier['cryptography']])),
        ('داده‌های ذخیره‌شده', _table(('مخزن', 'شرح', 'شخصی', 'نگهداری', 'تعداد'),
                                     [(d['store'], d['description'], 'بله' if d['personal'] else 'خیر', d['retention'], d['records'])
                                      for d in dossier['data_inventory']])),
        ('تنظیمات امنیتی', _table(('کلید', 'مقدار'), sorted((k, v) for k, v in dossier['settings'].items()))),
        *extra_sections,
    ]
    body = (f"<h1>پرونده شواهد ارزیابی امنیتی — {escape(dossier['system']['name'])}</h1>"
            f"<p class=\"muted\">{escape(dossier['organization'])} · تولید {escape(dossier['generated_at_jalali'])}</p>"
            + ''.join(f'<h2>{escape(title)}</h2>{content}' for title, content in sections))
    return _page('پرونده شواهد ارزیابی امنیتی', dossier['classification_label'], body)
