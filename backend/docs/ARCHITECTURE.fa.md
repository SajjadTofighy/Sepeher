# معماری و راهنمای توسعه

## مرز لایه‌ها

React → کلاینت HTTP هم‌مبدأ → FastAPI routers → مخزن حافظه‌ای / قواعد دامنه → داده نمونه و تاریخچه SQLite

- `frontend/src/app`: QueryClient و ErrorBoundary.
- `frontend/src/features`: مالکیت قابلیت‌های command، incidents، assets، policies، missions، analytics، audit، assistant و settings. هر بخش، صفحه و پنل‌های مرتبط خود را دارد.
- `frontend/src/shared/ui`: dialog بومی با مدیریت فوکوس مرورگر، Badge، DataTable مبتنی بر TanStack، Chart مبتنی بر ECharts و ابزارهای مشترک.
- `frontend/src/shared/api`: hook دریافت وضعیت و schema تولیدشده OpenAPI.
- `frontend/src/types.ts`: alias قراردادهای تولیدشده؛ از تکرار DTO دستی جلوگیری می‌کند.
- `frontend/src/api.ts`: مرز HTTP، خطا و قالب‌بندی فارسی.
- `frontend/src/App.tsx`: پوسته، ناوبری و اتصال تعاملات صفحه‌ها. داده دامنه در این فایل تعریف نمی‌شود.
- `frontend/src/styles.css`: توکن‌ها، پوسته، سبک قابلیت‌ها، نقاط شکست و حالت کاهش حرکت.
- `backend/app/models.py`: قرارداد پاسخ‌ها با Pydantic.
- `backend/app/routers`: endpointهای حوزه‌ای و اعتبارسنجی ورودی.
- `backend/app/store.py`: state نمونه، lookup، ثبت سوابق، شبیه‌سازی فرمان و شاخص‌ها.
- `backend/app/seed.py`: تنها منبع رکوردهای ساختگی.
- `backend/app/main.py`: wiring برنامه، lifespan، bootstrap، health، SSE و سرو فایل‌های ساخته‌شده.

`backend/app/intel` مالک هندسه، یافته‌های مستند و قابلیت‌های پوشش گشت، ایمنی، محدوده خطر، ریسک ثابت و برنامه گشت است. worker محلی asyncio در lifespan با فاصله intel_tick_seconds ابتدا refresh_tracks و سپس tick قابلیت‌های ثبت‌شده را اجرا می‌کند؛ SEPEHR_WORKER=0 حلقه را خاموش می‌کند. یک threading.Lock در store با مالکیت تو‌در‌توی همان thread، worker و endpointهای همگام و refreshها را سری می‌کند و پاسخ‌ها پیش از آزادسازی snapshot می‌شوند. ارزیابی سیاست‌ها پس از coverage انجام می‌شود تا بازدید معتبر پیش از بررسی مهلت ایستگاه اعمال شود. ریسک و پیش‌نویس‌ها هنگام درخواست محاسبه می‌شوند؛ برنامه، ریز عوامل و پنجره بازدید ذخیره و RNG فقط SystemRandom است، بدون ذخیره حالت و بدون یادگیری. پوشش از observations_since با تقدم GPS گزارش‌شده، cursor هر گشت و backfill آغاز/بازنشانی استفاده می‌کند؛ findings، پوشش، اپیزود ایمنی، محدوده خطر، برنامه‌ها و لایه‌ها حافظه‌ای‌اند و reset آن‌ها را بازسازی می‌کند. این worker درون همان فرایند است، نه queue پایدار یا سرویس مستقل تولیدی؛ shutdown پایان tick در حال اجرا را انتظار می‌کشد.


گزارش شیفت در `intel/shift_report.py` صرفاً تجمیع داده موجود است؛ `routers/reports.py` قرارداد مستقل و `features/analytics/ShiftReportView.tsx` نمای آن را دارند. `state.report_history` فقط وقایع بازدید/تغییر وضعیت و cursor مرز شیفت را نگه می‌دارد؛ گزارش ذخیره نمی‌شود. شروع سرور/reset با data_since و audit منبع مشخص است؛ داده ناموجود و هندسه تاریخی بازسازی‌ناپذیر برچسب جزئی دارند. پوسته چاپ در `shared/lib/print.ts` میان حادثه و شیفت مشترک است.


## تصمیم‌های حفظ نظم

۱. وضعیت سرور با TanStack Query، کلید مرکزی و polling سه‌ثانیه‌ای مدیریت می‌شود. داده فرم و انتخاب‌ها محلی‌اند. در مقیاس فعلی نیازی به یک store سراسری دوم نیست.
۲. عملیات نوشتن خودکار retry نمی‌شوند؛ درخواست فرمان دارای request_id برای جلوگیری از اجرای تکراری است.
۳. ثبت دستی حادثه فرایندی و محدوده خطر نیز از مدل پرونده و هندسه مشترک استفاده می‌کنند؛ پیشنهاد کنترل دسترسی فرمان نیست و از همان ارجاع انسانی پرونده استفاده می‌کند. ماشین حالت حادثه در API اعتبارسنجی می‌شود، نه فقط با مخفی‌کردن دکمه‌ها. خاتمه بدون گزارش رد می‌شود.
۴. MapLibre مسئول هندسه، لایه و تعامل GIS است. تغییر style و GeoJSON در ماژول command محصور است. چرخه عمر نقشه، observerها و markerها cleanup دارند.
۵. نمودار ECharts با ResizeObserver تغییر اندازه می‌دهد و هنگام unmount آزاد می‌شود. SDK نمودار در مسیر analytics به‌صورت lazy بارگذاری می‌شود.
۶. جدول مشترک مسئول مرتب‌سازی، صفحه‌بندی و وضعیت خالی است؛ تعریف ستون متعلق به feature است. برای داده حجیم، به pagination و filtering سمت سرور مهاجرت دهید.
۷. UI راست‌به‌چپ است؛ شناسه‌ها و رشته‌های فنی در محل لازم چپ‌به‌راست نمایش داده می‌شوند. فونت Vazirmatn و دارایی‌ها محلی‌اند.
۸. از dialog بومی برای focus trapping، Escape و top layer استفاده شده است؛ aria-labelledby عنوان را متصل می‌کند. focus-visible و prefers-reduced-motion پشتیبانی می‌شوند.
۹. TypeScript در حالت strict اجرا می‌شود. schema تولیدشده را دستی ویرایش نکنید.

ورودی‌های فاز سوم در `intel/ingest.py` صرفاً از payload صریح و با پرچم‌های خاموش پیش‌فرض هستند؛ worker داده سنسور تولید نمی‌کند. افت فشار از Finding مشترک و ANPR از unknown_vehicle/camera_event در engine با callback ثبت Finding مسیریابی می‌شوند. adapter قدیمی دوربین همان plate-read است و نمونه ساختگی را رد می‌کند؛ replay سیاست با همان موتور و بدون callback نوشتن، فقط خوانش‌های ثبت‌شده را در sandbox می‌شمارد. ارتباط با کنترل فرایند یک‌طرفه است و هیچ write-back وجود ندارد. قابلیت ناهنجاری خودروی سازمانی تا پیش‌نیازهای حریم خصوصی/هویت/RBAC/audit مشاهده‌کننده پیاده نمی‌شود.

## مخزن‌های مستقل و اجرای دو سرویس

کد بک‌اند در مخزن `http://bitbucket.agahyarai.local/scm/sep/backend.git` و کد فرانت‌اند در مخزن `http://bitbucket.agahyarai.local/scm/sep/fronend.git` نگهداری می‌شود؛ املای `fronend` مطابق نشانی مخزن است. در مخزن مستقل، محتوای پوشه همان سرویس به ریشه منتقل می‌شود: بک‌اند `app/`، `tests/` و `requirements.txt` دارد و فرانت‌اند `src/`، `public/` و `package.json`. پوشه `docs/`، قواعد `AGENTS.md` و فایل‌های ساخت نیز همراه کد هستند. محیط مجازی، node_modules، dist، دیتابیس، خروجی آزمون و اطلاعات ورود در Git ثبت نمی‌شوند.

هر سرویس Dockerfile مستقل دارد. Dockerfile بک‌اند فقط Python و Dockerfile فرانت‌اند Node برای build و Nginx برای سرو فایل‌ها را استفاده می‌کند. فرانت‌اند مسیرهای `/api/`، `/docs` و `/openapi.json` را به `SEPEHR_API_UPSTREAM` می‌فرستد؛ مقدار پیش‌فرض `http://backend:8000` است و هنگام اجرای کانتینر قابل تغییر است. فایل‌های Swagger در فرانت‌اند سرو می‌شوند؛ بنابراین رابط مستندات را از مبدأ فرانت‌اند باز کنید. ارتباط مرورگر هم‌مبدأ می‌ماند و افزودن CORS لازم نیست. این جداسازی، احراز هویت یا امکانات تولیدی جدید ایجاد نمی‌کند.

در ساختار مشترک این پوشه، `docker compose up --build` دو سرویس را اجرا می‌کند و رابط در `http://127.0.0.1:8000` است. در cloneهای مستقل:

```bash
# در مخزن بک‌اند
python -m pip install -r requirements.txt
python -m pytest tests -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1

# در مخزن فرانت‌اند، در ترمینال جدا
npm ci
npm run typecheck
npm run build
npm run dev
```

در توسعه، Vite روی پورت 5173 مسیر API را به پورت 8000 می‌فرستد. آزمون مرورگر در مخزن مستقل به سرویس‌های از قبل اجراشده وصل می‌شود؛ برای نمونه `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npm run test:e2e`. اسکریپت‌های پیش‌نمایش تصویر، ابزار ساختار مشترک‌اند و برای clone مستقل صادر نمی‌شوند.

برای Docker در cloneهای مستقل، ابتدا شبکه مشترک بسازید و از ریشه هر مخزن image همان سرویس را بسازید:

```bash
docker network create sepehr
docker build -t sepehr-backend .
docker run -d --name backend --network sepehr --restart unless-stopped -v track-data:/app/data sepehr-backend
# در مخزن فرانت‌اند
docker build -t sepehr-frontend .
docker run -d --name frontend --network sepehr --restart unless-stopped -p 127.0.0.1:8000:80 sepehr-frontend
```

برای تغییر قرارداد در مخزن مستقل بک‌اند، `python scripts/export_openapi.py` را اجرا کنید، `docs/openapi.json` تولیدشده را به `openapi.json` در ریشه مخزن فرانت‌اند منتقل کنید و سپس `npm run api:generate` را آنجا اجرا کنید. در ساختار مشترک، اسکریپت export هر دو فایل را همگام می‌کند. DTOها همچنان از مدل Pydantic تولید می‌شوند.

## تغییر قرارداد API

مدل Pydantic / endpoint را تغییر دهید و قرارداد را مجدداً تولید کنید:

```bash
python scripts/export_openapi.py
npm run api:generate --prefix frontend
npm run typecheck --prefix frontend
python -m pytest backend/tests -q
```

## اتصال به سیستم واقعی

- مخزن حافظه‌ای را با repository روی PostgreSQL/PostGIS جایگزین کنید. از API عمومی و DTO ثابت استفاده کنید.
- درگاه Traccar یا آداپتور اختصاصی، telemetry را به مدل Asset/Track تبدیل کند؛ UI نباید پروتکل ردیاب را بشناسد.
- شبیه‌ساز فرمان را با CommandService و queue جدا جایگزین کنید؛ idempotency، correlation ID، channel timeout و ACKهای جدا را حفظ کنید.
- ثبت تراکنشی audit/outbox و ذخیره append-only/WORM بیرونی برای استنادپذیری لازم است.
- نقشهٔ پایه OSM/OpenFreeMap است. GisTools مسئول ورود GeoJSON، اندازه‌گیری و اتصال WMS raster / WFS GeoJSON با تنظیمات runtime است. اتصال مستقیم مرورگر نیازمند CORS سرویس است؛ توکن GIS در فرانت‌اند ثابت نشود.
- برای لایه‌های حجیم، vector tiles و symbol layers به جای DOM marker مناسب‌اند. markerهای فعلی برای دوازده موجودیت دمو هستند و ادعای مقیاس هزاران ردیاب ندارند.
- داده زنده تولیدی را از SSE/WebSocket به cache Query متصل کنید؛ endpoint SSE نمونه در API موجود است، ولی UI فعلی polling می‌کند.
- auth سازمانی و RBAC را در backend اضافه کنید. کاربر نمایش‌داده‌شده در دمو هویت احرازشده نیست.
- نه شرط شامل قواعد مکانی/زمانی، SOS، ایستگاه زمان‌دار و دو شرط خوانش واقعی پلاک، dedupe، سایه و سکوت تعمیرات در engine اجرا می‌شوند. ارزیابی محلی پس‌زمینه با worker موجود است؛ سه شرط دیگر، همبستگی، queue پایدار و نگهداری تاریخچه نسخه‌ها هنوز نیازمند تکمیل‌اند؛ جزئیات در DESIGN-REVIEW.fa.md است.

## طراحی بصری

تم تیره اتاق فرمان با رنگ تأکیدی سبزآبی؛ نارنجی و قرمز برای اولویت عملیاتی. نقشه سطح اصلی است و صف هشدار در مجاورت آن قرار دارد. اطلاعات تفصیلی در پنل پرونده است. رنگ‌ها و فاصله‌ها از style مشترک پیروی می‌کنند. برای تم سازمانی، ابتدا متغیرهای `:root` و سپس component classes را تغییر دهید.

## موارد عمدی خارج از این تحویل

auth تولیدی، tenancy، HA، retention jobs، احراز هویت اختصاصی GIS، اتصال IVA/ردیاب، تکمیل موتور سیاست و مسیریابی جاده‌ای. این‌ها با داده ماک جایگزین شده‌اند و مرز آن‌ها در UI و README مشخص است.
