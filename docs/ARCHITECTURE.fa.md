# معماری و راهنمای توسعه

## مرز لایه‌ها

React → OIDC/PKCE و کلاینت HTTP → IdentityMiddleware و authz → FastAPI routers → fieldstore پایدار / قواعد دامنه و state نمونه

- `frontend/src/app`: QueryClient و ErrorBoundary.
- `frontend/src/features`: مالکیت قابلیت‌های command، incidents، assets، policies، missions، analytics، audit، assistant و settings. هر بخش، صفحه و پنل‌های مرتبط خود را دارد.
- `frontend/src/shared/ui`: dialog بومی با مدیریت فوکوس مرورگر، Badge، DataTable مبتنی بر TanStack، Chart مبتنی بر ECharts و ابزارهای مشترک.
- `frontend/src/shared/api`: hook دریافت وضعیت و schema تولیدشده OpenAPI.
- `frontend/src/types.ts`: alias قراردادهای تولیدشده؛ از تکرار DTO دستی جلوگیری می‌کند.
- `frontend/src/api.ts`: مرز HTTP، خطا و قالب‌بندی فارسی.
- `frontend/src/App.tsx`: پوسته، ناوبری و اتصال تعاملات صفحه‌ها. داده دامنه در این فایل تعریف نمی‌شود.
- `frontend/src/styles.css`: توکن‌ها، پوسته، سبک قابلیت‌ها، نقاط شکست و حالت کاهش حرکت.
- `backend/app/routers`: endpointهای حوزه‌ای و بررسی ارجاع/وضعیت؛ اعتبارسنجی شکل ورودی در مدل مشترک است.
- `backend/app/core`: پکیج هسته، مشترک بین همهٔ ماژول‌های دیگر (`routers`، `intel`، `security`، `field`، `tour`). `models.py` تنها مالک قراردادهای ورودی و پاسخ با Pydantic و پیش‌فرض/حدود RuntimeSettings است. `store.py` state نمونه، lookup، ثبت سوابق، شبیه‌سازی فرمان و شاخص‌ها را نگه می‌دارد. `fieldstore.py` SQLite گشت، دستگاه، پیوند هویت، PIN و ممیزی را دارد؛ state کش بازسازی‌شدنی است. `engine.py` سیاست‌های مبتنی بر موقعیت و تصمیم مسیریابی مشترک، `sim.py` شبیه‌سازی حرکت و فاصلهٔ کروی، `tracks.py` تاریخچهٔ GPS پایدار و `seed.py` تنها منبع رکوردهای ساختگی است.
- `backend/app/security`: `auth.py` (OIDC/RS256)، `authz.py` (مجوز)، `hardening.py` (نرخ/سقف بدنه)، `dossier.py` و `afta_letter.py` (شواهد و نامه افتا).
- `backend/app/field`: `media.py`، `safety.py` (SOS/duress/man_down)، `offline.py` (صف امضاشده آفلاین)، `device_profiles.py` (پیکربندی پیامکی ردیاب).
- `backend/app/tour`: `evidence.py` (قواعد trust اسکن، نام قبلی `tour.py`)، `schedule.py`، `tags.py`، `sun.py` (NTAG 424)، `qr.py` و `supervision.py` (تابلوی استثنا).
- `frontend/src/shared/auth`: جریان OIDC بدون SDK یا ذخیره توکن در مرورگر.
- `backend/app/main.py`: wiring برنامه، lifespan، bootstrap، health، SSE و سرو فایل‌های ساخته‌شده.

`backend/app/intel` مالک هندسه، یافته‌های مستند و قابلیت‌های پوشش گشت، ایمنی، محدوده خطر، ریسک ثابت، برنامه گشت و قواعد یکپارچگی گشت پیاده (`intel/integrity.py`) است. `intel/game.py` و `intel/bayes.py` محاسبات خالص و قطعی‌اند (بازی امنیتی و گاما-پواسون) و به store وابسته نیستند جز خواندن دفتر شواهد؛ `intel/patrol_game.py` تنها محل تبدیل پارامترهای سازمان به بازی، تأیید پارامترها و تصمیم زیرمجموعه مسیر است و `patrol.py` و `tour/schedule.py` از آن استفاده می‌کنند. دفتر رخدادهای ریسک (`risk_events`، شامل نسخه پایدار هر حادثه) و تأیید پارامترها در fieldstore پایدارند. تابلوی استثنا و گزارش گشت در `app/tour/supervision.py` فقط از رکوردهای پایدار fieldstore محاسبه می‌شوند و چیزی نمی‌نویسند جز audit مشاهده و خروجی. worker محلی asyncio در lifespan با فاصله intel_tick_seconds ابتدا refresh_tracks و سپس tick قابلیت‌های ثبت‌شده را اجرا می‌کند؛ SEPEHR_WORKER=0 حلقه را خاموش می‌کند. یک threading.Lock در store با مالکیت تو‌در‌توی همان thread، worker و endpointهای همگام و refreshها را سری می‌کند و پاسخ‌ها پیش از آزادسازی snapshot می‌شوند. ارزیابی سیاست‌ها پس از coverage انجام می‌شود تا بازدید معتبر پیش از بررسی مهلت ایستگاه اعمال شود. ریسک، برآورد بیزی، راهبرد و پیش‌نویس‌ها هنگام درخواست محاسبه می‌شوند؛ برنامه، ریز عوامل، راهبرد و پنجره بازدید ذخیره و RNG برنامه خودرویی فقط SystemRandom است، بدون ذخیره حالت و بدون یادگیری ماشینی؛ انتخاب زیرمجموعه دور پیاده از بذر ذخیره‌شده همان دور قابل بازتولید است. پوشش از observations_since با تقدم GPS گزارش‌شده، cursor هر گشت و backfill آغاز/بازنشانی استفاده می‌کند؛ findings، پوشش، اپیزود ایمنی، محدوده خطر، برنامه‌ها و لایه‌ها حافظه‌ای‌اند و reset آن‌ها را بازسازی می‌کند. این worker درون همان فرایند است، نه queue پایدار یا سرویس مستقل تولیدی؛ shutdown پایان tick در حال اجرا را انتظار می‌کشد.


مسیر دریافت موقعیت: کش ممیزی در حافظه فقط پس از commit تراکنش fieldstore رشد می‌کند و هر درخواست کل زنجیره را دوباره نمی‌خواند؛ موقعیت‌های GPS ممیزی جداگانه ندارند و در `core/tracks.py` با شواهد کیفیت ذخیره می‌شوند. TrackStore برای هر thread یک اتصال SQLite نگه می‌دارد و store آخرین موقعیت و دنباله ۵۰۰ نقطه‌ای را با شمارنده نسخه و listener درج به‌صورت افزایشی هم‌سان با پایگاه نگه می‌دارد. میان‌افزار و `/health` برای خواندن تنظیمات قفل سراسری نمی‌گیرند تا حلقه رویداد هرگز پشت یک handler کند نماند. `core/journal.py` با مقایسه اثر انگشت موجودیت‌ها دفتر تغییرات محدود با epoch فرایند می‌سازد؛ کنسول پس از bootstrap فقط تغییرات را می‌گیرد. فرمان‌های مأموریت انسانی در `field/mission_commands.py` و fieldstore پایدارند و با فرمان دستگاه یکی نیستند.

گزارش شیفت در `intel/shift_report.py` صرفاً تجمیع داده موجود است؛ `routers/reports.py` قرارداد مستقل و `features/analytics/ShiftReportView.tsx` نمای آن را دارند. `state.report_history` فقط وقایع بازدید/تغییر وضعیت و cursor مرز شیفت را نگه می‌دارد؛ گزارش ذخیره نمی‌شود. شروع سرور/reset با data_since و audit منبع مشخص است؛ داده ناموجود و هندسه تاریخی بازسازی‌ناپذیر برچسب جزئی دارند. پوسته چاپ در `shared/lib/print.ts` میان حادثه و شیفت مشترک است.


## تصمیم‌های حفظ نظم

۱. وضعیت سرور با TanStack Query، کلیدهای query حوزه‌ای و فاصله polling سه‌ثانیه‌ای مشترک در useOperations مدیریت می‌شود. داده فرم و انتخاب‌ها محلی‌اند. در مقیاس فعلی نیازی به یک store سراسری دوم نیست.
۲. عملیات نوشتن خودکار retry نمی‌شوند؛ درخواست فرمان دارای request_id برای جلوگیری از اجرای تکراری است.
۳. ثبت دستی حادثه فرایندی و محدوده خطر نیز از مدل پرونده و هندسه مشترک استفاده می‌کنند؛ پیشنهاد کنترل دسترسی فرمان نیست و از همان ارجاع انسانی پرونده استفاده می‌کند. ماشین حالت حادثه در API اعتبارسنجی می‌شود، نه فقط با مخفی‌کردن دکمه‌ها. خاتمه بدون گزارش رد می‌شود.
۴. MapLibre مسئول هندسه، لایه و تعامل GIS است. OperationalMap مالک لایه‌های عملیاتی با توابع مشترک source/layer، visibility و popup است؛ GisTools ابزار ورود، اندازه‌گیری و سرویس GIS را نگه می‌دارد. اعتبارسنجی GeoJSON مرورگر در gis.ts و قرارداد ورود سرور در models.py است؛ دو مرز مستقل‌اند و شرط چندضلعی سمت سرور میان محدوده حفاظت و خطر مشترک است. چرخه عمر نقشه، observerها و markerها cleanup دارند.
۵. نمودار ECharts با ResizeObserver تغییر اندازه می‌دهد و هنگام unmount آزاد می‌شود. SDK نمودار در مسیر analytics به‌صورت lazy بارگذاری می‌شود.
۶. جدول مشترک مسئول مرتب‌سازی، صفحه‌بندی و وضعیت خالی است؛ تعریف ستون متعلق به feature است. برای داده حجیم، به pagination و filtering سمت سرور مهاجرت دهید.
۷. UI راست‌به‌چپ است؛ شناسه‌ها و رشته‌های فنی در محل لازم چپ‌به‌راست نمایش داده می‌شوند. فونت Vazirmatn و دارایی‌ها محلی‌اند.
۸. از dialog بومی برای focus trapping، Escape و top layer استفاده شده است؛ aria-labelledby عنوان را متصل می‌کند. focus-visible و prefers-reduced-motion پشتیبانی می‌شوند.
۹. TypeScript در حالت strict اجرا می‌شود. schema تولیدشده را دستی ویرایش نکنید.

فاصله جغرافیایی در sim.distance_km، هندسه متری در intel/geo، چندضلعی/بازه و توقف/شعاع/فاصله مشاهدات در engine، صلاحیت گشت/ETA در routers/incidents (travel) و گراف راه آفلاین، مسیر سریع‌ترین و جست‌وجوی معکوس چندمبدأ در core/roads مالک واحد دارند. parse_timestamp در tracks زمان‌های دارای offset/Z را مشترک تفسیر می‌کند. تصمیم مسیریابی در engine.routing_decision و ایجاد/ادغام خودکار پرونده در engine.route_incident مشترک سیاست و یافته است؛ ثبت دستی اپراتور جدا از مسیریابی خودکار و تابع store.create_incident است.

ورودی‌های فاز سوم در `intel/ingest.py` صرفاً از payload صریح و با پرچم‌های خاموش پیش‌فرض هستند؛ worker داده سنسور تولید نمی‌کند. افت فشار از Finding مشترک و ANPR از unknown_vehicle/camera_event در engine با callback ثبت Finding مسیریابی می‌شوند. adapter قدیمی دوربین همان plate-read است و نمونه ساختگی را رد می‌کند؛ replay سیاست با همان موتور و بدون callback نوشتن، فقط خوانش‌های ثبت‌شده را در sandbox می‌شمارد. ارتباط با کنترل فرایند یک‌طرفه است و هیچ write-back وجود ندارد. قابلیت ناهنجاری خودروی سازمانی تا پیش‌نیازهای حریم خصوصی/هویت/RBAC/audit مشاهده‌کننده پیاده نمی‌شود.

## مخزن‌های مستقل و اجرای سرویس‌ها

کد بک‌اند در مخزن `http://bitbucket.agahyarai.local/scm/sep/backend.git` و کد فرانت‌اند در مخزن `http://bitbucket.agahyarai.local/scm/sep/fronend.git` نگهداری می‌شود؛ املای `fronend` مطابق نشانی مخزن است. در مخزن مستقل، محتوای پوشه همان سرویس به ریشه منتقل می‌شود: بک‌اند `app/`، `tests/` و `requirements.txt` دارد و فرانت‌اند `src/`، `public/` و `package.json`. پوشه `docs/`، قواعد `AGENTS.md` و فایل‌های ساخت نیز همراه کد هستند. محیط مجازی، node_modules، dist، دیتابیس، خروجی آزمون و اطلاعات ورود در Git ثبت نمی‌شوند.

هر سرویس Dockerfile مستقل دارد. Dockerfile بک‌اند فقط Python و Dockerfile فرانت‌اند Node برای build و Nginx برای سرو فایل‌ها را استفاده می‌کند. فرانت‌اند مسیرهای `/api/`، `/docs` و `/openapi.json` را به `SEPEHR_API_UPSTREAM` می‌فرستد؛ مقدار پیش‌فرض `http://backend:8000` است و هنگام اجرای کانتینر قابل تغییر است. فایل‌های Swagger در فرانت‌اند سرو می‌شوند؛ بنابراین رابط مستندات را از مبدأ فرانت‌اند باز کنید. ارتباط مرورگر هم‌مبدأ می‌ماند و افزودن CORS لازم نیست. IdentityMiddleware مرز احراز هویت API و authz مرز تصمیم مجوز هستند.

در ساختار مشترک این پوشه، ابتدا `npm run docker:init` و سپس `npm run docker:up` را اجرا کنید. چهار سرویس backend، frontend، Keycloak و PostgreSQL اجرا می‌شوند؛ رابط در `http://127.0.0.1:8000` و SSO در `http://127.0.0.1:8080` و کنسول مدیریت فقط در `http://127.0.0.1:8081/admin/` است. فایل `.env` با دسترسی ۶۰۰ و رمزهای تصادفی ساخته می‌شود؛ اجرای دوباره init آن را بازنویسی نمی‌کند. فایل نمونه `.env.example` راز ندارد. تغییر رمز PostgreSQL در `.env` روی دیتابیس موجود اعمال نمی‌شود و نیازمند چرخش رمز در خود دیتابیس است؛ رمز bootstrap مدیر نیز فقط در راه‌اندازی اولیه استفاده می‌شود.

`npm run docker:build` ایمیج‌های backend و frontend را می‌سازد؛ `docker:config` اعتبار Compose را بدون چاپ رازها بررسی می‌کند، `docker:logs` لاگ‌ها را نشان می‌دهد و `docker:down` سرویس‌ها را بدون حذف volume متوقف می‌کند. `docker:up` تا سلامت سرویس‌ها حداکثر ۳۰۰ ثانیه منتظر می‌ماند. volumeهای `track-data` و `keycloak-data` مستقل‌اند؛ PostgreSQL پورت منتشرشده ندارد. فقط PyJWT و cryptography طبق استثنای مصوب به بک‌اند اضافه شده‌اند؛ فرانت‌اند وابستگی تازه ندارد.

### هویت، امنیت و پایداری گشت

`deploy/keycloak/realm-sepehr.json` بدون راز و کاربر، realm `sepehr` را با `start --import-realm` وارد می‌کند. Keycloak `26.7.4` و PostgreSQL `17.6-alpine` ثابت‌اند؛ حالت dev و دیتابیس داخلی استفاده نمی‌شوند. realm موجود با restart بازنویسی نمی‌شود. ارتقای آن با `npm run keycloak:sync-security` ابتدا پیش‌نمایش و با `-- --apply` اعمال می‌شود؛ کاربران، عضویت‌ها و URLهای دقیق موجود حفظ می‌شوند. این ابزار پس از ساخت و اعتبارسنجی جریان MFA آن را فعال می‌کند؛ قبل از اعمال، پشتیبان PostgreSQL بگیرید.

کلاینت‌های public `sepehr-web` و `sepehr-field` از Authorization Code و PKCE اجباری S256 استفاده می‌کنند. redirect `/auth/callback` و origin فقط loopbackهای 8000 و 5173 هستند و باید برای استقرار جایگزین شوند؛ wildcard، implicit و Direct Access Grants خاموش‌اند. `sepehr-api` فقط audience است. mapperهای audience و groups، نقش‌های guard، shift_supervisor، security_officer، security_manager، auditor و admin و گروه‌های والد zones/contractors تعریف شده‌اند. مدیر زیرگروه شناسه‌های واقعی و پیوند sub به نگهبان را صریحاً می‌سازد؛ ورود اول Asset نمی‌سازد.

جریان browser ابتدا cookie/password را احراز می‌کند، سپس شرط نقش ترکیبی داخلی `sepehr-mfa-required` را بررسی می‌کند. همه نقش‌های غیر guard عضو این نقش‌اند و OTP برای آن‌ها اجباری است؛ کاربر دارای guard و یک نقش مدیریتی نیز OTP می‌گیرد. ثبت‌نام/ورود اجتماعی خاموش، تشخیص brute force روشن و رمز حداقل ۱۲ نویسه با حروف بزرگ/کوچک، عدد و نماد لازم است. زبان فارسی و Events و Admin Events بدون payload حساس فعال‌اند.

مقادیر پیشنهادی برای تأیید حراست: access token پنج دقیقه؛ SSO idle سی دقیقه؛ SSO max و client session max میدانی سیزده ساعت، با فرض شیفت دوازده‌ساعته و یک ساعت مهلت؛ rotation refresh با reuse صفر؛ نگهداری رخداد هفت روز؛ قفل UI پس از پانزده دقیقه عدم فعالیت. طول شیفت واقعی و retention باید پیش از بهره‌برداری تأیید شوند.

`SEPEHR_AUTH_MODE` پیش‌فرض keycloak است. demo فقط با تنظیم صریح یا `npm run dev:demo`/`python run_local.py --demo` فعال می‌شود و همه پاسخ‌ها `X-Sepehr-Demo: 1` دارند. تنظیمات issuer، audience و azp از `SEPEHR_OIDC_ISSUER`، `SEPEHR_OIDC_AUDIENCE=sepehr-api` و `SEPEHR_OIDC_CLIENTS=sepehr-web,sepehr-field` می‌آیند. JWKS داخلی از `SEPEHR_OIDC_JWKS_URL` قابل تنظیم است؛ issuer همچنان عمومی و دقیق بررسی می‌شود. RS256، iss، aud، azp، exp، nbf با leeway پنج ثانیه و typ=Bearer الزامی‌اند. کش کلید پنج دقیقه و حداقل فاصله بازخوانی ده ثانیه است؛ kid ناشناخته یک بازخوانی محدود می‌گیرد و قطعی JWKS کلید معتبر کش‌شده را از کار نمی‌اندازد، همراه هشدار.

گشت، نگهبان، دستگاه، پیام، رسانه، گزارش گشت، ممیزی، تأیید و خروجی همیشه محافظت می‌شوند. APIهای قدیمی پشت `SEPEHR_AUTH_ENFORCE_ALL` با پیش‌فرض false هستند؛ overlay تولید آن را true می‌کند. ماتریس مجوز در authz داده است و UI آن را از `/auth/permissions` می‌خواند. محوطه/پیمانکار از claims groups است، نگهبان فقط داده خودش را می‌بیند و بدون پیوند `guard_not_linked` می‌گیرد. فیلدهای هویت در پاسخ عمومی قدیمی حذف می‌شوند. درخواست نگهبان میدانی جز enrollment به `X-Device-Id` فعال و متعلق به sub نیاز دارد. کد enrollment یک‌بارمصرف، وابسته به sub و پیش‌فرض پنج دقیقه است؛ ابطال دستگاه فوری است.

فرانت‌اند با fetch و Web Crypto یک popup هم‌مبدأ برای PKCE/state/nonce باز می‌کند؛ بستن یا reload تب حافظه را پاک می‌کند و ورود بعدی از نشست SSO انجام می‌شود. access/refresh/ID token و verifier در localStorage یا sessionStorage ذخیره نمی‌شوند. امضای ID token با JWKS و issuer/audience/subject/nonce بررسی می‌شود؛ طبق [OIDC بند 12.2](https://openid.net/specs/openid-connect-core-1_0.html#RefreshTokenResponse) نبود nonce در پاسخ refresh مجاز است و nonce موجود باید همان nonce اولیه باشد. refresh موازی یکی می‌شود؛ قفل/خروج توکن و cache Query را پاک می‌کند. logout با POST به end_session انجام می‌شود تا ID token در URL قرار نگیرد.

`SEPEHR_FIELD_DB` مسیر SQLite جداست. WAL، foreign_keys، schema_version و migrationهای شماره‌دار idempotent فعال‌اند. guard metadata/identity، routes، tours، check-ins، tags، devices، messages، field_reports، media، media_uploads، approvals و classification در fieldstore منبع حقیقت‌اند؛ startup و پایان تراکنش cache را بازسازی می‌کنند. عملیات میدانی و audit در یک تراکنش زیر store.locked_state اجرا می‌شوند؛ شکست عملیات rollback دارد. reset نمونه این داده‌ها را حذف نمی‌کند. موجودیت‌های قدیمی فرمان/حادثه/سیاست هنوز حافظه‌ای‌اند. رمز ورود فقط در Keycloak است؛ PIN و PIN اضطرار با salt تصادفی، scrypt و compare_digest نگهداری می‌شوند. پنج PIN نادرست قفل پنج‌دقیقه‌ای دارد. باینری رسانه خارج از SQLite و دست‌نخورده در `SEPEHR_MEDIA_DIR` (پیش‌فرض پوشه `media` کنار پایگاه میدانی) با sha256، زمان دریافت سرور، ثبت‌کننده و دستگاه نگهداری می‌شود؛ آپلود قطعه‌ای فقط با offset برابر پیشرفت ثبت‌شده جلو می‌رود و حذف فقط از job نگهداری `field_media.tick` در worker و بدون legal_hold انجام می‌شود. نشان‌آب در کلاینت رسم می‌شود. کانال ارسال پیام یا پیامک بیرونی وجود ندارد؛ فرمان پیامکی تجهیز فقط متن پوشیده پروفایل پروتکل (`device_profiles.py`) را ثبت می‌کند.

همان `store.audit` کنشگر sub/username و prev_hash را ثبت می‌کند؛ hash برابر SHA256(prev_hash + JSON کانونیکال بدون hash) است. audit پایدار و append-only با trigger منع update/delete است. `/audit/verify` فقط auditor زنجیره دیتابیس و cache را بررسی می‌کند؛ مرجع WORM بیرونی هنوز لازم است تا حذف انتهای فایل/جایگزینی کامل آن قابل کشف شود. چرخش کلید/ابطال تگ، حذف مسیر و تغییر classification نیازمند دو sub متفاوت، target بدون تغییر و تراکنش مشترک‌اند. تغییر نقش فقط در Keycloak انجام می‌شود؛ `/audit/role-changes` آخرین صد Admin Event را با service client `sepehr-audit` و فقط view-events می‌خواند. secret خارج realm در env است.

classification پیش‌فرض «محرمانه» در header `X-Classification` به شکل `UTF-8''` و percent encoding منتقل می‌شود؛ UI آن را نمایش می‌دهد. دریافت مجوز خروجی/چاپ `/exports` و گزارش گشت audit دارد و فایل JSON/چاپ برچسب، زمان و audit_id می‌گیرد. این کنترل جلوی کپی دستی صفحه توسط کاربر مجاز را نمی‌گیرد. زمان ذخیره UTC و نمایش Asia/Tehran است؛ startup افست تابستان ۱۴۰۲ به بعد را برای +03:30 بررسی و در صورت ناسازگاری هشدار می‌دهد.

ساخت اپلیکیشن و کاربر جدید:

```bash
npm run keycloak:client -- --client-id new-web --redirect-uri http://127.0.0.1:5173/auth/callback --origin http://127.0.0.1:5173 --dry-run
# همان فرمان بدون --dry-run منابع را ایجاد می‌کند.
npm run keycloak:user -- --username new-guard --role guard
npm run keycloak:user -- --username new-supervisor --role shift_supervisor
npm run keycloak:audit
npm run keycloak:sync-security -- --apply
```

ساخت client به معنی ثبت اپلیکیشن OIDC در Keycloak است؛ scaffold پروژه تازه ایجاد نمی‌کند. برای پذیرش client جدید در Sepehr، فهرست azp مجاز را نیز به‌روز کنید. رمز مدیر و موقت کاربر بدون echo پرسیده می‌شوند؛ ابزار فایل .env را خودکار نمی‌خواند. گزینه‌های `--server`، `--realm` و `--admin` قبل از subcommand می‌آیند؛ پیش‌فرض مدیریت `http://127.0.0.1:8081` است. کلاینت موجود در create-client بازنویسی نمی‌شود. کاربر تا تکمیل نقش/گروه غیرفعال می‌ماند و sub برای پیوند دستی نشان داده می‌شود. configure-audit secret را در env-file با دسترسی ۶۰۰ می‌نویسد؛ سپس backend را recreate کنید. راز در خروجی چاپ نمی‌شود.

### استقرار و راهنمای عملیات

Compose محلی فقط loopback HTTP دارد. خود Keycloak پورت host ندارد؛ Nginx پورت 8080 فقط realms/resources را می‌دهد و admin را 404 می‌کند، مدیریت از 8081 است. `deploy/compose.production.yaml` و `deploy/nginx/production.conf.template` TLS و سه hostname مستقل app/SSO/admin را با hostname-admin روی پورت 9443، bind خصوصی و allowlist شبکه مدیریت اعمال می‌کنند. فایل `deploy/.env.production.example` را با مقادیر واقعی در .env تکمیل کنید؛ certهای app، identity و admin در `SEPEHR_TLS_DIR` لازم‌اند. `npm run docker:production:check` اعتبار hostname، شبکه خصوصی، digest و Compose را بررسی می‌کند؛ `docker:production:pull` ایمیج‌های داخلی pinned با sha256 را دریافت می‌کند. digest باید با manifest مصوب سازمان تطبیق یابد؛ نمونه‌ها digest معتبر عملیاتی ندارند. استقرار با هر دو فایل Compose و secrets سازمانی انجام می‌شود.

برای وصله: backup سازگار PostgreSQL و SQLite بگیرید؛ نسخه و digest تأییدشده داخلی را تعیین کنید؛ migration/import، guard و کاربر OTPدار، refresh/logout و حوزه دسترسی را در staging بررسی کنید؛ سپس منتشر کنید. rollback دیتابیس از backup همان نسخه است. LDAP/AD اختیاری از User Federation با TLS و حساب read-only سازمانی تنظیم می‌شود؛ اتصال واقعی در این تحویل آزموده نشده است. در ابطال دستگاه، مدیر پس از revoke در Sepehr نشست‌های همان کاربر را در Keycloak Users → Sessions → Logout all sessions دستی باطل کند. audit پیش و پس از تغییر حفظ شود؛ reset دمو ابزار پاک‌سازی امنیتی نیست.

بررسی مرورگر واقعی روی Keycloak و app محلی نشان داد منابع صفحه ورود، OTP و پنل گشت و نقشه عملیات فقط از مبدأهای محلی دریافت می‌شوند. آزمون مرورگر state دست‌کاری‌شده و ID token با nonce متفاوت را نیز رد کرد. فونت و Swagger محلی‌اند؛ نقشه پیش‌فرض grid شماتیک SVG محلی است و به OSM/OpenFreeMap درخواست ندارد. bundle واقعی tiles/glyphs سازمانی باید جدا تأمین شود. اتصال GIS فقط به originهای مصوب `SEPEHR_GIS_ORIGINS` مجاز است و همان originها باید در `SEPEHR_RESOURCE_ORIGINS` برای CSP افزوده شوند. این بررسی شامل سرویس GIS یا theme سفارشی نصب‌نشده سازمان نیست.

مبنا: [کانتینر Keycloak](https://www.keycloak.org/server/containers)، [health](https://www.keycloak.org/observability/health)، [reverse proxy](https://www.keycloak.org/server/reverseproxy). فایل جداگانه README کیکلاک طبق قاعده عدم ایجاد Markdown تازه ساخته نشد؛ راهنمای آن همین‌جا نگهداری می‌شود.

در cloneهای مستقل:

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

- موجودیت‌های عملیاتی قدیمی حافظه‌ای را با repository روی PostgreSQL/PostGIS جایگزین کنید. از API عمومی و DTO ثابت استفاده کنید.
- درگاه Traccar یا آداپتور اختصاصی، telemetry را به مدل Asset/Track تبدیل کند؛ UI نباید پروتکل ردیاب را بشناسد.
- شبیه‌ساز فرمان را با CommandService و queue جدا جایگزین کنید؛ idempotency، correlation ID، channel timeout و ACKهای جدا را حفظ کنید.
- تراکنش گشت/audit موجود است؛ outbox و WORM بیرونی برای استنادپذیری سازمانی باقی‌اند.
- نقشهٔ پایه پیش‌فرض شماتیک محلی است؛ tiles سازمانی باید تأمین شوند. GisTools مسئول ورود GeoJSON، اندازه‌گیری و اتصال WMS raster / WFS GeoJSON با تنظیمات runtime است. اتصال مستقیم مرورگر نیازمند CORS سرویس است؛ توکن GIS در فرانت‌اند ثابت نشود.
- برای لایه‌های حجیم، vector tiles و symbol layers به جای DOM marker مناسب‌اند. markerهای فعلی برای ناوگان کوچک نمونه هستند و ادعای مقیاس هزاران ردیاب ندارند.
- داده زنده تولیدی را از SSE/WebSocket به cache Query متصل کنید؛ endpoint SSE نمونه در API موجود است، ولی UI فعلی polling می‌کند.
- پیش از تولید SEPEHR_AUTH_ENFORCE_ALL را روشن، حوزه و نقش کاربران و سیاست سازمانی را تأیید کنید؛ demo هویت واقعی نیست.
- نه شرط شامل قواعد مکانی/زمانی، SOS، ایستگاه زمان‌دار و دو شرط خوانش واقعی پلاک، dedupe، سایه و سکوت تعمیرات در engine اجرا می‌شوند. ارزیابی محلی پس‌زمینه با worker موجود است؛ سه شرط دیگر، همبستگی، queue پایدار و نگهداری تاریخچه نسخه‌ها هنوز نیازمند تکمیل‌اند؛ جزئیات در DESIGN-REVIEW.fa.md است.

## طراحی بصری

تم تیره اتاق فرمان با رنگ تأکیدی سبزآبی؛ نارنجی و قرمز برای اولویت عملیاتی. نقشه سطح اصلی است و صف هشدار در مجاورت آن قرار دارد. اطلاعات تفصیلی در پنل پرونده است. رنگ‌ها و فاصله‌ها از style مشترک پیروی می‌کنند. برای تم سازمانی، ابتدا متغیرهای `:root` و سپس component classes را تغییر دهید.

## موارد عمدی خارج از این تحویل

پذیرش عملیاتی امنیت سازمانی، tenancy جامع عملیات، HA، نگهداری داده عملیات قدیمی، احراز هویت اختصاصی GIS، اتصال واقعی IVA/ردیاب، سه شرط باقی‌مانده سیاست و مسیریابی جاده‌ای. شبیه‌سازی موقعیت، فرمان، داده اولیه و شاخص‌های نمونه جای تحقق این امکانات را نمی‌گیرد؛ ورود GPS و درگاه‌های خاموش فشار/ANPR اتصال سخت‌افزار یا هویت معتبر منبع را اثبات نمی‌کنند.

## فاز یک: ایستگاه و برچسب پایدار

routers/stations.py همان FieldRoute، store.locked_state و تراکنش fieldstore فاز صفر را استفاده می‌کند. محوطه‌های گشت با PUT /tour/zones/{id} در entities به‌عنوان field_zones ثبت می‌شوند؛ Zoneهای نمایشی state منبع حقیقت آن‌ها نیستند. Station، StationTask، نصب تگ، بازدید، پاسخ وظیفه و تاریخچه تعویض پلمب در fieldstore هستند. migration شماره ۳ جدول‌های tag_keys و tag_counters و index فقط یک کلید فعال برای هر ایستگاه را اضافه می‌کند و داده فاز صفر را حفظ می‌کند. کلیدها وارد cache یا پاسخ عمومی نمی‌شوند.

حساسیت از RuntimeSettings.station_sensitivity_labels انتخاب می‌شود؛ مقادیر اولیه نمونه پیکربندی هستند، enum ثابت نیستند. تغییر فهرست فقط admin و پایدار است و حذف برچسب مورد استفاده رد می‌شود. media_capture_allowed در ایجاد ایستگاه، اگر null/غایب باشد از محوطه پایدار گرفته و ذخیره می‌شود. شماره UID و حالت تگ و حوزه ایستگاه پس از ایجاد قابل بازنویسی نیستند. hazards مقادیر h2s/flammable/ex_zone_1/ex_zone_2/heat/other هستند؛ در فاز سه H2S/flammable تأیید گازسنج می‌خواهند و Ex پرچم دستگاه می‌دهد، اما تشخیص حسگر یا صدور مجوز HSE نیست.

QR/کد قالب SPH2:kid:station_id:rev:hmac دارد. HMAC-SHA256 با خروجی کوتاه‌شده ۱۲۸ بیتی روی چهار جزء اول و کلید فعال tag_keys محاسبه می‌شود. rev باید tag_revision فعلی باشد. qr.py فقط کتابخانه استاندارد، حالت byte، تصحیح M و نسخه ۱ تا ۶ دارد؛ mask پیش‌فرض صفر قطعی است و هر هشت mask پشتیبانی می‌شوند. ماتریس‌های مرجع ۴۸ حالت یک‌بار با [python-qrcode 8.2](https://github.com/lincolnloop/python-qrcode) ساخته و در backend/tests/fixtures/qr_reference.json نگهداری شده‌اند؛ این ابزار وابستگی runtime نیست. SVG چهار ماژول حاشیه سفید دارد. برگه فیزیکی فقط code/SVG خنثی را چاپ می‌کند؛ نام، نوع، حساسیت و metadata گزارش نباید روی آن چاپ شوند. QR و code ایستا هستند و اثبات حضور زنده یا مقاومت در برابر کپی ندارند.

NTAG 424 با تأیید صریح کاربر فعال است. tour_sun.py پروفایل PICCData رمز‌شده با UID هفت‌بایتی و شمارنده ۲۴بیتی little-endian را با AES-128-CBC و CMAC از cryptography مصوب بررسی می‌کند. MAC با مقایسه ثابت زمانی و UID با مقدار تخصیص‌یافته کنترل می‌شود. مبنا [NXP AN12196](https://www.nxp.com.cn/docs/en/application-note/AN12196.pdf)، بخش‌های 3.4.2 و 3.4.4 است؛ بردار رسمی با counter=61 در آزمون ثابت استفاده شده است. URL شخصی‌سازی دقیقاً tag=SPH2:...&picc=<32hex>&cmac=<16hex> است. MACInput از ابتدای tag= تا پایان cmac=، بدون مقدار CMAC، محاسبه می‌شود؛ در نتیجه شناسه/نسخه ایستگاه هم در MAC پوشش دارند. endpoint admin آماده‌سازی کلیدهای تصادفی، NDEF URI کوتاه و offsetها را برای فایل NDEF شامل دو بایت NLEN می‌دهد، همراه audit و Cache-Control:no-store. SEPEHR_FIELD_TAG_BASE_URL مبدأ HTTPS یا loopback دقیق URL است؛ Compose تولید از SEPEHR_FIELD_TAG_PRODUCTION_URL یا hostname برنامه با مسیر /nfc استفاده می‌کند. این مسیر برای رابط اسکن تیم UI رزرو شده و در این تحویل handler مرورگر ندارد. ابزار نصاب باید کلیدهای واقعی و تنظیمات SDM را روی سخت‌افزار اعمال کند؛ تنظیم RF/TagTamper یا همه پروفایل‌های NXP پیاده نشده‌اند.

nfc_counter فقط URL شامل tag، uid هگز ۱۴ نویسه و counter هگز شش نویسه با نمایش عددی big-endian می‌پذیرد؛ این mirror رمزنگاری‌شده نیست و همیشه «ضعیف» گزارش می‌شود. برای هر دو حالت NFC، شمارنده برابر یا کمتر از آخرین مقدار replay است. شمارنده در تراکنش همان عملیات مصرف می‌شود؛ rollback مقدار را مصرف نمی‌کند و restart/چرخش کلید آن را صفر نمی‌کند. چرخش کلید تنها از تأیید دونفره فاز صفر، کلید قدیمی را غیرفعال و revision را افزایش می‌دهد؛ وضعیت planned و نصب مجدد لازم می‌شود. ابطال نیز فقط از همان مسیر، revision را افزایش و کلیدها را غیرفعال می‌کند. اولین اسکن مجاز نصاب با موقعیت داخل محوطه، زمان، sub و assurance ثبت و وضعیت installed می‌شود.

بازدید فقط با نگهبان پیوندخورده، دستگاه فعال متعلق به sub و گشت فعال در همان محوطه/پیمانکار آغاز می‌شود. نسخه تگ، حداقل dwell و وظایف در ورود snapshot می‌شوند. خروج پیش از زمان حداقل سرور یا بدون وظایف الزامی و تأیید نفر دوم رد می‌شود؛ سخت‌ترشدن سیاست جاری نیز اعمال می‌شود. تأیید نفر دوم باید از نگهبان مستقل همان حوزه و با اسکن خودش باشد. بازدید نامعتبر در اثر ابطال/چرخش با دلیل و audit قابل لغو است و cancelled با completed تفاوت دارد. عدد خارج بازه و گزینه نامعتبر 422 است؛ پلمب متفاوت anomaly و evidence می‌گیرد. این پرچم ثبت داده وظیفه است و فرمان یا اجرای خودکار ندارد. تعویض پلمب فقط شماره تازه، دلیل و audit دارد؛ snapshot بازدید قبلی را بازنویسی نمی‌کند. audio به metadata رسانه صوتی همان گشت اشاره می‌کند؛ ضبط/ذخیره باینری رسانه هنوز این endpoint نیست. ضبط رسانه در بازدید با سیاست ممنوع رد می‌شود.

API ایستگاه‌ها همیشه احراز هویت و station_read دارد و محوطه/پیمانکار از Principal محدود می‌شوند؛ query نمی‌تواند حوزه را گسترش دهد. گزارش گشت بازدیدها و پاسخ‌ها، از جمله assurance ضعیف/قوی/ایستا/دستی را با مجوز خروجی و audit برمی‌گرداند. بنا به دستور کاربر UI و لایه OperationalMap جداگانه توسعه می‌یابند؛ تیم UI از GET /tour/stations و ماتریس /auth/permissions استفاده کند و فقط پس از مجوز نقش، لایه را فعال کند. قرارداد OpenAPI تولیدشده آماده اتصال است.

## فاز دو: شیفت و صف پایدار

`app/tour_schedule.py` محاسبه پنجره شیفت، چرخه، استراحت و ترتیب ایستگاه و `routers/schedules.py` مجوز، تأیید و API را نگه می‌دارند. `fieldstore` منبع حقیقت الگوهای سفارشی، برنامه‌ها، دورهای ساخته‌شده، تحویل شیفت و وضعیت اضطرار است؛ `store.restore_field_state` کش آن‌ها را بازسازی می‌کند. الگوی پیش‌فرض از `intel_shifts` خوانده می‌شود و `intel/shift_report.py` منطق گزارش پیشین را حفظ می‌کند. ساخت تدریجی فقط امروز و فردا را پوشش می‌دهد و اعزام خودکار ندارد.

## فاز سه: شاهد اسکن و ایمنی میدانی

`app/tour/evidence.py` تنها محل قواعد قطعی ساعت، GPS، ترتیب و trust اسکن است. migration شماره ۴ جدول append-only `scans` و کلید یکتای `(owner_sub, client_id)` را اضافه می‌کند. بازبینی دستی در entities جدا ذخیره می‌شود تا شاهد خام دست‌کاری نشود. `routers/stations.py` اعتبار تگ فاز یک را استفاده می‌کند؛ GPS در بازدید فقط شاهد است و فقدان یا ضعف آن اسکن را رد نمی‌کند. اسکن replay با status=rejected ثبت می‌شود. snapshot بازدید پس از سپری‌شدن dwell سطح اعتماد نهایی می‌گیرد؛ شاهد اولیه immutable می‌ماند.

`app/field/safety.py` رویداد صریح SOS، duress و man_down و زمان تشدید را نگه می‌دارد. man_down از گزارش حسگر کلاینت پس از شمارش معکوس می‌آید؛ یافته مرتبط به‌صورت shadow و بدون اقدام خودکار در موتور یافته مشترک ثبت می‌شود. دیرکرد check-in گشت پیاده نیز Finding با شواهد و مسیریابی سایه مشترک است. `intel/worker.py` همان قفل مشترک را برای tick این بخش استفاده می‌کند. SOS صریح نگهبان از `store.create_incident` پرونده می‌گیرد؛ رسید سرور در رویداد پایدار است و رسید اپراتور از `/incidents/{id}/ack` ثبت می‌شود. خود پرونده در state قدیمی حافظه‌ای است، پس بازیابی کامل پرونده SOS پس از restart هنوز وابسته به تکمیل پایداری عمومی رخدادهاست. SSE امنیتی و حضورشماری از رکوردهای پایدار fieldstore خوانده می‌شوند. هیچ‌کدام فرمان یا اعزام خودکار ندارند.

## فاز چهار: مرز صف آفلاین و سرور

`app/offline.py` فقط امضای HMAC رکورد صف با راز دستگاه ثبت‌شده و پرچم زمان را بررسی می‌کند؛ راز در پاسخ عمومی بازنشر نمی‌شود. `/tour/offline/emergency` تنها استثنای middleware برای Bearer منقضی/غایب است: امضای دستگاه فعال و تعلق گشت به `owner_sub` پیش از ثبت بررسی می‌شود. اعلان SOS و man_down به همان `field_safety.py` فاز سه می‌روند؛ duress در پاسخ قابل‌نمایش نگهبان افشا نمی‌شود. `/tour/offline/scans` به همان `stations.arrival` و `/assets/{id}/positions:batch` به همان `record_position` و `TrackStore.append` وصل‌اند؛ مسیرهای معمول آنلاین سازگار مانده‌اند. APIها `Cache-Control: no-store` دارند. IndexedDB، Cache Storage پوسته، CryptoKey و ترتیب تخلیه صف مرز کلاینت مستقل‌اند و در سرور شبیه‌سازی نمی‌شوند. SQLite موقعیت و fieldstore دو مخزن مستقل‌اند؛ بسته موقعیت در خطای میانه اتمیک نیست و retry یکسان لازم است.

## فاز هفت: سخت‌سازی

`IdentityMiddleware` روی همه پاسخ‌ها CSP بدون مبدأ بیرونی (جز issuer و GIS داخلی مصوب در `connect-src`)، `frame-ancestors 'none'`، `form-action 'self'`، HSTS، `X-Content-Type-Options: nosniff`، `Referrer-Policy: no-referrer`، `X-Frame-Options: DENY` و `Permissions-Policy` می‌گذارد که دوربین، میکروفون، موقعیت و NFC را فقط برای همین مبدأ مجاز می‌کند؛ قالب nginx همان سربرگ‌ها را دارد. `app/hardening.py` سطل توکن درون‌حافظه‌ای با ساعت `store.now()` برای ثبت دستگاه، PIN/تأیید حضور، اسکن و آپلود دارد (`RuntimeSettings.rate_limit_per_minute`)؛ اعلام خطر (SOS، man_down و صف اضطراری) هرگز به‌خاطر نرخ رد نمی‌شود و فقط `rate_flagged` و یک ممیزی در دقیقه می‌گیرد. بدنه JSON پیش از احراز هویت با سقف `max_json_body_bytes` خوانده و در صورت تجاوز 413 می‌شود؛ مسیرهای باینری رسانه سقف جداگانه دارند. همه مدل‌های ورودی `extra="forbid"` دارند (آزمون روی همه مسیرها بررسی می‌کند) و مدل‌های پاسخ مشتق از آن‌ها صریحاً `extra="ignore"` هستند تا رفتار پاسخ تغییر نکند. خطای اعتبارسنجی فقط `loc`، `msg` و `type` را بازمی‌گرداند و خطای داخلی فقط کد `internal_error` دارد. شمارنده‌ها حافظه‌ای و تک‌فرایندی‌اند؛ در استقرار چندفرایندی باید محدودیت در پروکسی هم اعمال شود.

`scripts/check_keycloak_realm.py` realm صادرشده را برای PKCE S256، نبود wildcard، خاموشی Direct Access Grants/implicit/ثبت‌نام، Brute Force، چرخش refresh token، سقف عمر توکن و نشست، سیاست رمز، Events/Admin Events و نبود راز بررسی و نسخه کیکلاک (از `compose.yaml` یا ورودی) را با فهرست دستی وصله‌ها مقایسه می‌کند. `scripts/dependency_inventory.py` فهرست وابستگی‌های مستقیم (و با `--all` همه بسته‌های npm) را از `backend/requirements.txt` و `frontend/package-lock.json` با نسخه دقیق برای بازبینی امنیتی می‌دهد. وابستگی‌های مستقیم فعلی: پایتون fastapi 0.115.12، uvicorn 0.34.2، httpx 0.28.1، pytest 8.3.5، PyJWT 2.10.1، cryptography 44.0.3؛ npm اجرایی @fontsource/vazirmatn 5.2.5، @tanstack/react-query 5.83.0، @tanstack/react-table 8.21.3، echarts 5.6.0، lucide-react 0.468.0، maplibre-gl 5.6.2، react و react-dom 19.1.1 و ابزارهای ساخت فهرست‌شده در خروجی اسکریپت.

## مدل تهدید (STRIDE)

طبق AGENTS.md سند جدا ساخته نشد؛ این بخش جایگزین `THREAT-MODEL.fa.md` است.

| تهدید | STRIDE | کنترل پیاده‌شده | آزمون | ریسک باقی‌مانده |
|---|---|---|---|---|
| تکرار و شبیه‌سازی تگ | Spoofing | NTAG 424 SUN با CMAC و شمارنده پایدار؛ شمارنده آینه‌شده با برچسب «ضعیف»؛ QR با کلید و revision نسخه‌دار؛ قاعده سایه `tag_replay` و `tag_distance` | `test_sun_provisioning_scans_replay_and_key_change`، `test_counter_mirror_weak_replay_and_restart`، `test_integrity_rules_cloned_tag_shadow_and_resolution` | QR ایستا قابل عکس‌برداری است؛ Web NFC احراز کامل NTAG 424 را ندارد (فاز ۸) |
| دستکاری ساعت گوشی | Tampering | لنگر `X-Server-Time`، شاهد clock، پرچم `clock_regressed`، قاعده `clock` | `test_scan_evidence_clock_manual_review_and_scope`، `test_signed_scan_offline_flags_and_invalid_signature` | ساعت جلوکشیده در آفلاین کوتاه فقط skew دیده می‌شود |
| جعل GPS | Spoofing | GPS فقط شاهد کمکی؛ جهش، سرعت ناممکن و دقت ثابت مشکوک «implausible» | `test_gps_anomaly_ex_warning_and_overdue_checkin` | تشخیص mock location در مرورگر ممکن نیست |
| گوشی گم‌شده | Information disclosure | ابطال دستگاه فوری (`device_revoked`)، دستگاه وابسته به sub، رسانه محدود پس از ارسال حذف می‌شود | `test_device_revocation_ownership_one_time_code_and_expiry`، `test_expired_token_emergency_and_revoked_device` | کش رمزشده IndexedDB (فاز ۴) هنوز ساخته نشده؛ ابطال نشست کیکلاک دستی است |
| نگهبان تحت اجبار | Spoofing | رمز اضطرار با پاسخ یکسان، duress فقط برای نقش امنیتی و در تابلوی استثنا | `test_checkin_pin_hash_duress_and_rate_limit`، `test_duress_sos_escalation_man_down_and_muster`، `test_access_duress_individual_view_and_audited_csv` | اگر مهاجم PIN عادی را بداند، اجبار پنهان نمی‌ماند |
| کاربر داخلی مخرب | Repudiation / Elevation | ماتریس مجوز سمت سرور، حوزه از claim، تأیید دونفره تغییرات حساس، نمای فردی محدود و ممیزی هر مشاهده و خروجی، زنجیره هش | `test_two_person_approval_classification_and_replay`، `test_audit_append_only_tampering_persistence_and_identity_reassignment` | حذف انتهای زنجیره بدون مرجع بیرونی (WORM/SOC) تشخیص‌پذیر نیست |
| ادمین مخرب کیکلاک | Elevation | ادمین محدود، Admin Events، گزارش `audit/role-changes` برای ممیز، کنسول فقط شبکه مدیریت | `test_role_changes_from_service_client_are_filtered_and_audited`، `test_realm_baseline_checker_and_dependency_inventory` | تغییر نقش در کیکلاک تأیید دونفره بومی ندارد |
| سرقت توکن | Spoofing | توکن کوتاه‌عمر، PKCE، توکن وب فقط در حافظه، پیوند دستگاه با sub، چرخش refresh token | `test_invalid_claims`، `test_device_revocation_ownership_one_time_code_and_expiry` | XSS در همان مبدأ می‌تواند توکن حافظه را بخواند؛ CSP سخت آن را محدود می‌کند |
| آسیب‌پذیری وصله‌نشده کیکلاک | Elevation | نسخه ثابت، `check_keycloak_realm.py` با فهرست وصله، روند وصله در RUNBOOK | `test_realm_baseline_checker_and_dependency_inventory` | فهرست وصله دستی است و به به‌روزرسانی منظم نیاز دارد |
| نشت تصاویر خسارت | Information disclosure | رسانه damage/uxo/drone فقط مدیر حراست، غیرقابل خروجی، no-store، حذف از گوشی، ممیزی هر مشاهده | `test_restricted_reports_routing_access_export_and_legal_hold` | عکس از صفحه نمایش قابل جلوگیری نیست |
| از کار افتادن سرور یا کیکلاک | Denial of service | کش JWKS، صف آفلاین امضاشده، فرم کاغذی با trust کم، پشتیبان و بازیابی با manifest | `test_unavailable_jwks_retains_cached_key`، `test_backup_delete_restore_equality_and_tamper_refusal`، `test_paper_form_entry_is_low_trust_and_not_missed` | HA و تکرار پایگاه پیاده نشده است |
| DoS روی مسیر اعلام خطر | Denial of service | اعلام خطر هرگز به‌خاطر نرخ رد نمی‌شود و فقط پرچم می‌گیرد؛ سقف بدنه؛ ممیزی یک‌بار در دقیقه | `test_rate_limits_reject_but_never_drop_emergency`، `test_body_ceiling_strict_inputs_and_sanitized_errors` | سیل درخواست امضاشده از دستگاه فعال پذیرفته می‌شود؛ ابطال دستگاه پاسخ است |

## دستورالعمل بهره‌برداری (RUNBOOK)

طبق AGENTS.md سند جدا ساخته نشد؛ این بخش جایگزین `RUNBOOK.fa.md` است.

- **قطع سرور Sepehr:** نگهبانان در اپ ادامه می‌دهند؛ اعلام خطر از صف امضاشده پس از وصل ارسال می‌شود. اگر اپ هم کار نکند، «فرم کاغذی پشتیبان گشت» از صفحه «راهنما و فرم پشتیبان» چاپ و پس از بازگشت از «نظارت ← ورود فرم کاغذی» با شماره سریال ثبت شود (روش کاغذی، اعتماد کم). تماس اضطراری محوطه از فهرست چاپی استفاده شود.
- **قطع کیکلاک:** توکن‌های معتبر تا پایان عمر و کلید JWKS کش‌شده کار می‌کنند؛ ورود تازه ممکن نیست. اعلام خطر با امضای دستگاه حتی با توکن منقضی پذیرفته می‌شود. وضعیت را به همه شیفت‌ها اعلام و زمان قطع را ثبت کنید.
- **قطع شبکه میدان:** صف اپ اولویت اضطرار دارد؛ اسکن دیرتر از `max_offline_minutes` پرچم و اعتماد حداکثر متوسط می‌گیرد. تکرار آن قاعده `offline_repeat` را فعال می‌کند.
- **قطع یا جعل GPS:** اثبات حضور بر تگ است؛ موقعیت «implausible» را بررسی کنید و تصمیم را به GPS وابسته نکنید.
- **وضعیت اضطرار (حمله هوایی، حادثه):** مسئول حراست از `/tour/emergency/{zone}` فعال می‌کند؛ مهلت‌ها تعلیق و حضورشماری آغاز می‌شود؛ پس از پایان، وضعیت را غیرفعال کنید.
- **دستگاه گم‌شده:** فوراً `POST /devices/{id}/revoke`؛ سپس در کنسول کیکلاک نشست‌های کاربر را ابطال (Users ← Sessions ← Sign out) و در صورت لزوم رمز را بازنشانی کنید. کد ثبت تازه برای گوشی جایگزین صادر شود.
- **چرخش کلید تگ:** از صف تأیید دونفره (`rotate_tag_key`) درخواست و توسط نفر دوم تأیید شود؛ برگه خنثی تازه چاپ و نصب، سپس نصب با اسکن نصاب ثبت شود.
- **ابطال نشست‌های کیکلاک کاربر:** کنسول ادمین فقط از شبکه مدیریت؛ اقدام در Admin Events ثبت و در گزارش `audit/role-changes` برای ممیز دیده می‌شود.
- **نصب وصله کیکلاک:** فهرست وصله را در فایل advisories به‌روز کنید و `python scripts/check_keycloak_realm.py --advisories advisories.json` اجرا کنید؛ ایمیج تازه را از مخزن داخلی با بررسی هش بکشید، از PostgreSQL پشتیبان بگیرید، در محیط آزمون اجرا و سپس در پنجره نگهداری جایگزین کنید.
- **پشتیبان‌گیری:** روزانه `python scripts/backup.py --out /secure/backups` (SQLite سازگار با سرویس در حال اجرا و رسانه با manifest sha256) و `pg_dump -Fc -h <db> -U keycloak keycloak > keycloak-<date>.dump`. نسخه‌ها رمزشده و خارج از سرور نگهداری شوند.
- **بازیابی:** سرویس را متوقف کنید؛ `python scripts/restore.py <backup-dir> --force` (manifest و integrity بررسی می‌شود و در ناسازگاری هیچ چیز بازنویسی نمی‌شود)؛ `pg_restore -c -d keycloak keycloak-<date>.dump`؛ سرویس را آغاز و `GET /api/v1/audit/verify` را با نقش ممیز بررسی کنید. تمرین بازیابی دست‌کم فصلی انجام شود.
- **آزمون بار:** فقط روی محیط آزمون: `python scripts/load_test.py --base-url ... --token ... --asset-id ... --station-id ... --tag-payload ...`؛ اهداف عددی تا توافق با کارفرما خالی‌اند.

## نشست وب و پرونده ارزیابی امنیتی

`frontend/src/shared/auth/session.tsx` تنها مالک وضعیت احراز هویت رابط است (نه داده سرور): پیکربندی را از `/auth/config` می‌خواند، ورود PKCE را برای `client_id` کنسول یا `field_client_id` اپ میدانی آغاز می‌کند، توکن را فقط در حافظه `api.ts` نگه می‌دارد، پیش از انقضا تمدید می‌کند و با شمارنده نسل، پاسخ تمدید دیررس پس از خروج یا قفل را نادیده می‌گیرد. رویداد 401 از `parseResponse` نشست را پاک و صفحه ورود را نشان می‌دهد؛ عدم فعالیت بیش از `idle_seconds` توکن را از حافظه حذف و صفحه قفل را نمایش می‌دهد. `AuthGate` پیش از بارگذاری کنسول ورود را الزامی، نگهبان را به اپ میدانی محدود و نوار طبقه‌بندی و حالت دمو را روی همه صفحه‌ها نشان می‌دهد. فقط شناسه غیرمحرمانه دستگاه در localStorage می‌ماند و verifier یک‌بارمصرف PKCE تا بازگشت از کیکلاک در sessionStorage است.

`app/security_dossier.py` شواهد استعلام افتا را از سامانه در حال اجرا گردآوری می‌کند و فقط ممیزی می‌نویسد؛ نوع احراز هر مسیر از همان `authz.path_permission` و `authz.protected` گرفته می‌شود که middleware اعمال می‌کند. `app/afta_letter.py` رندر خالص و escape‌شده نامه و خلاصه است و `scripts/security_dossier.py` آن را بدون import برنامه و بدون نوشتن در پایگاه تولیدی بسته‌بندی می‌کند. `scripts/stub_oidc.py` فقط برای آزمون است، به 127.0.0.1 محدود است و PKCE S256، redirect دقیق و کد یک‌بارمصرف را اعمال می‌کند؛ هرگز مستقر نشود. اجرای آزمون مرورگر: `SEPEHR_E2E_OIDC=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:8765 npx playwright test login.spec.ts` با بک‌اند در حالت keycloak و issuer برابر IdP آزمایشی.

