# گزارش اعتبارسنجی بازبینی طراحی

تاریخ: ۲۰۲۶-۱۰-۰۷. نتیجه تطبیق کامل در [DESIGN-REVIEW.fa.md](DESIGN-REVIEW.fa.md) است.

## اجراشده

- ۲۹ تست backend با موفقیت: چرخه حادثه، جلوگیری از اعزام گشت مشغول، فرمان مجاز/ممنوع و idempotency، وضعیت/مهلت فرمان نمونه، دروازه سیاست، تاریخچه پایدار، اعتبارسنجی GIS، دستیار و سناریوی نمایش.
- هشت تست جدید در `backend/tests/test_design_compliance.py`: سایه سراسری و فقط ثبت، قطع ارتباط با پوشش و بازیابی، توقف با مشاهدات پیوسته، جهش GPS و تردد، زمان‌بندی و مسدودکردن شرط فاقد موتور، آزمون روی داده ذخیره‌شده بدون تغییر وضعیت زنده، ارزیابی در دریافت موقعیت، تعداد متغیر ایستگاه و گشت مشغول.
- TypeScript strict و بسته production فرانت‌اند با موفقیت ساخته شدند.
- ۱۶ تست Playwright در Chrome با موفقیت: GeoJSON و اندازه‌گیری، درخواست‌های WMS/WFS، تنظیمات GIS، fallback بدون WebGL، نقشه موبایل، تور پنج‌دقیقه‌ای، مسیر و بازپخش، fullscreen، چرخه کامل حادثه و تأیید فرمان نمونه.
- قرارداد OpenAPI و schema TypeScript بازتولید شدند.

## محیط اجرا

فایل‌های `.venv` و برخی وابستگی‌های Node موجود برای macOS بودند؛ برای بررسی لینوکس، محیط Python موقت در `/tmp/sepehr-verify-venv` ساخته شد و وابستگی‌های Node سازگار با لینوکس نصب شدند. پایگاه‌های آزمون در مسیر موقت قرار داشتند. FastAPI TestClient به علت محدودیت socket محیط محدود، بیرون از sandbox اجرا شد. یک هشدار deprecation از ترکیب Starlette/AnyIO وجود دارد؛ تست‌ها شکست نخوردند.

فرمان‌های استفاده‌شده:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /tmp/sepehr-verify-venv/bin/python -m pytest backend/tests -q
npm --prefix frontend run api:generate
npm --prefix frontend run build
# پس از اجرای uvicorn محلی با پایگاه موقت و Chrome نصب‌شده:
PLAYWRIGHT_CHANNEL=chrome npm --prefix frontend run test:e2e
```

مسیر `/tmp` محیط بررسی است، نه بخشی از بسته تحویل؛ در محیط دیگر باید یک virtualenv سازگار ایجاد و `backend/requirements.txt` نصب شود. `PYTEST_DISABLE_PLUGIN_AUTOLOAD` برای جلوگیری از دخالت pluginهای ROS محیط میزبان به کار رفت.

## محدودیت‌ها

- این بررسی آزمون امنیت سازمانی، ظرفیت/بار، HA، بازیابی پشتیبان، سخت‌افزار ردیاب، SMS یا پذیرش پایلوت نیست.
- سرویس GIS سازمان، ONVIF/VMS، APN و هویت سازمانی متصل نشده‌اند.
- Docker و Windows در این بازبینی اجرا نشدند.
- نصب npm وجود پنج هشدار آسیب‌پذیری وابستگی را گزارش کرد؛ این بازبینی اصلاح نسخه‌های امنیتی یا ممیزی کامل dependencyها نیست و پیش از استقرار باید بررسی شوند.
- زمان‌ها و خطاهای آزمایش به معنای تحقق شاخص‌های بخش ۱۷ طرح نیستند.
