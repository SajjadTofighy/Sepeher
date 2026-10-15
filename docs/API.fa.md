# قرارداد API

Base URL: `http://127.0.0.1:8000/api/v1`

OpenAPI کامل در `openapi.json` و Swagger در `/docs` موجود است. رابط و API هم‌مبدأ هستند. در توسعه Vite، proxy مسیرهای API را به پایتون می‌فرستد.

بک‌اند در `npm run dev` و `python run_local.py --no-install` به‌صورت پیش‌فرض روی `0.0.0.0:8000` گوش می‌دهد. برای دسترسی شبکه، رابط ساخته‌شده را در `http://<IP-سرور>:8000` و API را در `http://<IP-سرور>:8000/api/v1` باز کنید؛ آدرس‌های نسبی رابط به همان سرور متصل می‌شوند. در اجرای `run_local.py` می‌توان با `--host 127.0.0.1` دسترسی را به همان دستگاه محدود کرد. برای دسترسی به Vite در شبکه، `npm run dev -- --host 0.0.0.0` اجرا کنید؛ proxy همچنان به بک‌اند همان سرور وصل می‌شود.

| Method | Path | رفتار |
|---|---|---|
| GET | `/health` | سلامت سرویس و mode=mock |
| GET | `/bootstrap` | رکوردهای اولیه، خطوط لوله و تأسیسات و شاخص‌ها؛ پوشش تفصیلی مسیر جدا دارد |
| GET | `/assets` | فهرست تجهیزات و نیروها |
| GET | `/assets/{id}/track` | تاریخچه پایدار SQLite با since/until/limit؛ ثبت مشاهده در audit |
| GET | `/incidents` | فهرست پرونده‌ها |
| POST | `/incidents` | ثبت دستی حادثه فرایندی؛ پاسخ 201، عامل اپراتور و وضعیت detected |
| PUT/DELETE | `/incidents/{id}/hazard-area` | ثبت/پاک‌کردن محدوده خطر حادثه باز؛ audited؛ حادثه بسته 409 |
| GET | `/incidents/{id}` | جزئیات و timeline |
| POST | `/incidents/{id}/transition` | تغییر معتبر وضعیت |
| GET | `/incidents/{id}/nearby` | گشت‌های متصل به ترتیب فاصله مستقیم |
| GET | `/incidents/{id}/report` | گزارش JSON شامل incident.hazard_area و hazard.inside/approaching/closure_suggestions؛ ثبت دریافت در audit |
| GET | `/commands` | فرمان‌ها و آخرین وضعیت شبیه‌سازی |
| POST | `/commands` | ارسال فرمان ماک با idempotency |
| POST | `/policies` | پیش‌نویس سیاست |
| POST | `/policies/{id}/test` | آزمون GPS، ایستگاه زمان‌دار یا خوانش واقعی ANPR هفت روز اخیر با همان موتور؛ بدون داده واقعی ANPR، 422 |
| PATCH | `/policies/{id}/status` | عبور از مراحل انتشار |
| GET | `/missions` | مأموریت‌ها و ایستگاه‌ها |
| POST | `/missions/{id}/checkpoint` | ثبت دستی ایستگاه قدیمی؛ ایستگاه هدف‌دار برنامه باید از پوشش ثبت شود و این مسیر 409 است |
| GET | `/reports/shift?from=&to=` | گزارش هفت‌بخشی شیفت با زمان تهران، شناسه منابع و تاریخ شروع داده؛ پیش‌فرض آخرین شیفت کامل‌شده |
| GET | `/analytics` | شاخص‌ها و روند نمونه |
| GET | `/audit` | سوابق به ترتیب جدیدترین |
| GET | `/audit/verify` | بررسی زنجیره پایدار و تطبیق cache؛ فقط auditor |
| POST | `/assistant` | پاسخ قالبی و شناسه منابع |
| GET | `/events` | SSE heartbeat و شاخص‌ها؛ قابلیت اتصال آتی UI |
| POST | `/demo/scenario` | دریافت SOS نمایشی از همان مسیر رخداد دستگاه؛ تشکیل پرونده تابع سیاست و سایه/سکوت |
| POST | `/demo/reset` | بازنشانی داده عملیات نمونه؛ گشت و audit پایدار حفظ می‌شوند |

## نمونه فرمان

```json
{
  "asset_id": "AST-001",
  "command": "position",
  "channel": "data",
  "interval_seconds": 30,
  "request_id": "a-unique-client-request-id"
}
```

فرمان‌ها: `position`, `ping`, `interval`, `restart`, `beacon`, `diagnostics`.
کانال‌ها: `data`, `sms`.

پروفایل پیامکی هر تجهیز (`Asset.device_profile`) از `GET /device-profiles` انتخاب و با `PATCH /assets/{id}/settings` ثبت می‌شود: `concox_gt06` (مثلاً `WHERE#`، `TIMER,30#`، `RESET#`)، `coban_tk103` (مثلاً `fix030s***n<رمز>`، فاصله تا ۲۵۵ ثانیه یا مضرب دقیقه)، `teltonika_fmb` (`<login> <password> getgps` با دو فاصله در اعتبارنامه خالی؛ فاصله ارسال از پیامک پشتیبانی نمی‌شود) و `generic_data` بدون فرمان پیامکی. این‌ها خانواده‌های پروتکل رایج ردیاب‌های بازار ایران‌اند، نه فهرست تأییدشده برند؛ الگو باید با دفترچه سازنده و firmware نصب‌شده تطبیق داده شود. اپراتورهای مجاز سیم‌کارت: همراه اول، ایرانسل و رایتل. `sms_password` و `sms_login` فقط نوشتنی‌اند؛ پاسخ فقط `sms_password_set` دارد. `GET /commands/preview?asset_id=&command=&interval_seconds=` متن دقیق پیامک و شماره مقصد را با رمز پوشیده (`••••`) برمی‌گرداند. در `channel=sms` فرمان پشتیبانی‌نشده پروفایل یا فاصله خارج از بازه پروتکل 422 است و `Command` فیلدهای `device_profile`، `sms_destination`، `sms_text` پوشیده و `gateway=none` را دارد. درگاه پیامک متصل نیست؛ رمز واقعی در هیچ فرمان، audit یا پاسخی ذخیره نمی‌شود و تحویل همچنان شبیه‌سازی است.

پاسخ اولیه `201` و `status=sent` دارد. با گذر زمان، تجهیز برخط به delivered و executed می‌رسد. تجهیز قطع به timed_out می‌رسد. فرمان اینترنت همراه مهلت ۱۰ ثانیه و پیامک مهلت ۲۰ ثانیه در دمو دارد. تکرار request_id با payload یکسان همان فرمان را برمی‌گرداند؛ payload متفاوت با همان شناسه، خطای 409 است. ارسال مجدد باید request_id تازه داشته باشد.

## چرخه حادثه

`detected → confirmed → assigned → en_route → on_scene → closed`

```json
{"status":"assigned","asset_id":"AST-001","note":"گشت پس از بررسی اپراتور انتخاب شد"}
```

برای assigned وجود asset_id معتبر و گشت آماده لازم است. برای closed یادداشت غیرخالی لازم است. گشت موضوع خود حادثه برای اعزام پذیرفته نمی‌شود.

## چرخه سیاست

`draft → tested → shadow → active`

آزمون قواعد مکانی، تاریخچه هفت روز SQLite را با همان موتور در محیط جدا ارزیابی می‌کند؛ نرسیدن به ایستگاه از مأموریت‌های زمان‌دار و ANPR از خوانش‌های ثبت‌شده استفاده می‌کنند. آزمون SOS از GPS پشتیبانی نمی‌شود. هندسه و مجوزها فعلی‌اند و نرخ هشدار کاذب بدون بازبینی انسانی نامشخص است. وضعیت active فقط پس از shadow مجاز است. version در تغییر وضعیت افزایش می‌یابد؛ تاریخچه تغییرات در audit درج می‌شود. نام تأییدکننده در دمو ثابت است.

## خطاها و محدودیت‌ها

- `404`: رکورد/محدوده وجود ندارد.
- `409`: تعارض وضعیت، اعزام نامعتبر، idempotency conflict یا مأموریت تکمیل‌شده.
- `422`: ورودی نامعتبر، فرمان ناشناخته یا گزارش خاتمه خالی.
- خطا با `detail` بازگردانده می‌شود؛ UI پیام فارسی را نمایش می‌دهد.
- مسیرهای فاز صفر همیشه Bearer لازم دارند؛ مسیرهای قدیمی با SEPEHR_AUTH_ENFORCE_ALL (پیش‌فرض false) محافظت می‌شوند. حالت demo فقط صریح فعال می‌شود.
- queryهای لیست برای حجم کم دمو تمام رکوردها را می‌دهند. pagination سمت سرور برای نسخه عملیاتی باید اضافه شود.
- timestamps با UTC ارسال و در رابط با زمان تهران نمایش داده می‌شوند.

## تنظیمات و فاز سوم

| Method | Path | رفتار |
|---|---|---|
| GET/POST | `/zones` | فهرست / ایجاد چندضلعی نمونه |
| PUT | `/zones/{id}` | ویرایش مشخصات و هندسه محدوده |
| PATCH | `/assets/{id}/settings` | مشخصات سیم‌کارت، بسته و فاصله گزارش |
| GET/PUT | `/settings` | تنظیمات پوشش ارتباط، پوشش گشت، ریسک و برنامه، فاصله worker، retention، سکوت، dedupe و GIS؛ تغییر `patrol_game` فقط با نقش security_manager یا admin، پایدار در fieldstore و باطل‌کننده تأیید پارامترها |
| GET | `/cameras` | دوربین‌های نمونه |
| POST | `/cameras/{id}/event` | adapter همان plate-read؛ فقط event=plate با plate/time/vehicle_class واقعی؛ رخداد نمونه، intrusion و fire با 409 رد می‌شوند |

تمام کلیدهای intel_* از RuntimeSettings با حدود اعتبارسنجی به seed و فرم فارسی تنظیمات می‌رسند؛ seed فقط تماس‌های اضطراری ساختگی و سایه سراسری خاموش برای نمایش فعال را جایگزین می‌کند. حالت پوشش، ایمنی و افت فشار پیش‌فرض shadow است؛ قالب‌های سیاست ANPR نیز سایه‌اند و درگاه آن خاموش است. ایجاد/ادغام خودکار پرونده سیاست و یافته تابع مشترک موتور است؛ ثبت دستی اپراتور تشخیص خودکار نیست.

تغییر تنظیمات GIS تنها ذخیره است و هیچ URL ورودی توسط سرور فراخوانی نمی‌شود. چندضلعی‌ها حداقل سه رأس متمایز و مختصات معتبر نیاز دارند.

## زیرساخت هوشمندی و پوشش گشت

| Method | Path | رفتار |
|---|---|---|
| GET | `/intel/segments` | قطعه‌های مشتق‌شده حدود ۵۰۰ متر با pipeline_id، index، هندسه، طول و میدان |
| POST | `/intel/layers/import` | ورود اتمی GeoJSON FeatureCollection؛ LineString به خط لوله و Point به تأسیسات؛ پاسخ 201 و ثبت import در audit |
| GET | `/intel/findings?kind=&status=` | یافته‌های مستند با فیلتر اختیاری نوع و وضعیت open/acknowledged/resolved |
| POST | `/intel/findings/{id}/ack` | تأیید دریافت یافته؛ تکرار بدون audit اضافی، یافته رفع‌شده 409 و شناسه ناموجود 404 |
| GET | `/intel/coverage` | items با id، kind=segment/facility، status=ok/stale/never، last_visit، last_asset_id و age_minutes؛ totals شامل percent_ok و by_field |

ویژگی‌های هر عارضه واردشده شامل name و field (یکی از میدان‌های موجود) و id اختیاری است. تأسیسات به kind از well/station/plant/manifold، radius_m مثبت و unmanned نیاز دارد. مختصات دوبعدی WGS 84 با همان اعتبارسنجی محدوده‌ها بررسی می‌شوند؛ نوع هندسه نامعتبر 422 و شناسه تکراری 409 است. قطعه‌ها از خط مشتق می‌شوند و دستی نگهداری نمی‌شوند. لایه‌های اولیه شماتیک و ساختگی‌اند.

Finding دارای rule_id، موضوع‌ها، خلاصه فارسی، زمان‌ها، شواهد (قاعده، آستانه، بازه، نقاط زمان‌دار، مقادیر)، sources، incident_id و can_execute=false است. وضعیت پایدار تا رفع، یک یافته می‌سازد؛ تأیید دریافت latch را آزاد نمی‌کند. سایه سراسری، فقط ثبت و سکوت تعمیرات از تصمیم مشترک موتور پیروی می‌کنند. پوشش گشت حتی در حالت active پرونده ایجاد نمی‌کند و هیچ یافته‌ای فرمان یا اعزام انجام نمی‌دهد.

worker در lifespan و بدون polling مرورگر مسیرها و قابلیت‌های ثبت‌شده پوشش گشت، ایمنی و محدوده خطر را بررسی می‌کند. SEPEHR_WORKER=0 حلقه را غیرفعال می‌کند؛ tick مستقیم برای آزمون قابل فراخوانی است. شروع برنامه و demo/reset پوشش را از مشاهدات در دسترس بازسازی می‌کنند. پوشش فقط خودروهای گشت را می‌شمارد، با فاصله نمونه‌های حداکثر ۵۰ متر؛ فاصله زمانی بیش از max(report_interval×3, 120s) درون‌یابی نمی‌شود. نقاط داخل حریم خط یا شعاع تأسیسات بازدید محسوب می‌شوند. percent_ok نسبت تعداد قطعه‌ها و تأسیسات در مهلت به تعداد کل است؛ وزن‌دهی بر اساس طول انجام نمی‌شود.

پیش‌فرض تنظیمات: intel_tick_seconds=5، intel_coverage_buffer_m=200، intel_coverage_backfill_hours=72، intel_coverage_stale_hours=12، intel_coverage_unmanned_stale_hours=8 و intel_coverage_mode=shadow. بازه backfill روی همان جریان موتور اعمال می‌شود: مسیر شبیه‌سازی حدود نیم ساعت حافظه‌ای است و مسیر گزارش‌شده به آخرین ۵۰۰ نقطه موجود در نمای موتور محدود است؛ بازه ۷۲ ساعت تضمین وجود ۷۲ ساعت داده نیست. وضعیت never یعنی در این مشاهدات بازدیدی ثبت نشده، نه اثبات عدم حضور گشت.

## ایمنی گشت و رخداد اضطراری

| Method | Path | رفتار |
|---|---|---|
| GET | `/intel/safety` | episodes شامل asset_id، state، started_at، deadline، facility_id و reason |
| POST | `/intel/safety/{asset_id}/confirm` | بدنه `{"note":"..."}` یا `{}`؛ تأیید سلامت و audit؛ مهلت بسته/گذشته یا سکوت دستگاه 409 |
| POST | `/assets/{id}/events` | `{"type":"sos","time":"2026-10-07T12:00:00Z"}`؛ پاسخ 201 شامل event، alerts و incidents |

ایمنی فقط خودروهای گشت را بررسی می‌کند. توقف پیوسته با شعاع ۳۰ متر، سرعت حداکثر ۱ و همان قاعده فاصله مشاهدات موتور اثبات می‌شود. پس از intel_safety_stop_minutes=3، مهلت intel_safety_checkin_minutes=10 برای توقف حساس شروع می‌شود. حساس یعنی داخل تأسیسات بدون سرنشین، کنار خط در حریم intel_safety_remote_km=1 و دورتر از این فاصله از تأسیسات دارای سرنشین، یا خارج از intel_safety_normal_hours=06:00–20:00 به وقت تهران. حرکت بیش از ۳۰ متر اپیزود را پایان می‌دهد. تأیید اپراتور آن را confirmed نگه می‌دارد تا حرکت بعدی؛ دیرکرد high و سکوت در check_pending با آستانه پوشش محدوده و سیاست قطع ارتباط، critical می‌شود. هر اپیزود فقط یک یافته می‌سازد. intel_safety_mode پیش‌فرض shadow است و کنترل‌های سراسری اعمال می‌شوند.

SOS فقط برای دستگاه دارای قابلیت sos پذیرفته می‌شود؛ سایر دستگاه‌ها 422 فارسی دریافت می‌کنند. رخداد همسان (تجهیز، نوع، زمان UTC) تکرار نمی‌شود. SOS خارج از محدوده حفاظت نیز دریافت می‌شود؛ موضوع و بازه سیاست و سایه/سکوت در موتور اعمال می‌شوند و محل پرونده از موقعیت فعلی برچسب می‌گیرد. demo/scenario همین مسیر را استفاده می‌کند؛ اگر مسیریابی خاموش باشد، event/alerts برمی‌گرداند و پرونده تحمیلی نمی‌سازد. تاریخچه رخداد حافظه‌ای است و reset آن را پاک می‌کند؛ آزمون گذشته SOS از GPS رد می‌شود.

تنظیم intel_emergency_contacts فهرست `{name, role, phone}` است؛ داده اولیه شناسه‌های ساختگی دارد. پرونده‌های sos و patrol_safety شامل kind، emergency_contacts و backup_patrols با ETA تخمینی‌اند. فهرست پشتیبان از همان dispatchable و eta_minutes مسیر nearby ساخته می‌شود؛ هیچ تماس یا اعزامی خودکار نیست.

## محدوده حوادث فرایندی

ثبت دستی با `POST /incidents` بدنه `{title, severity, lon, lat, description}` دارد؛ شدت یکی از critical/high/medium/low/info است. kind=process و asset_id داخلی MANUAL-INC-* است و تجهیز جعلی به ناوگان اضافه نمی‌شود. چرخه و ارجاع همان چرخه موجود پرونده است.

`PUT /incidents/{id}/hazard-area` یکی از این دو بدنه را می‌پذیرد:

```json
{"type":"circle","center":[49.78,30.76],"radius_m":200,"access_points":[[49.79,30.76]]}
```

```json
{"type":"polygon","points":[[49.77,30.75],[49.79,30.75],[49.79,30.77]],"access_points":[]}
```

مختصات صرفاً مثال شماتیک‌اند. شعاع مثبت و حداکثر ۱۰۰ کیلومتر است؛ چندضلعی همان اعتبارسنجی ZoneInput را استفاده می‌کند (۳ تا ۱۰۰ رأس، سه نقطه متفاوت و مساحت مثبت). access_points اختیاری، حداکثر ۱۰۰ نقطه است. ثبت/حذف فقط برای پرونده باز مجاز، با audit و خط زمانی است. ثبت مجدد هندسه یکسان هشدار را تکرار نمی‌کند.

`GET /intel/hazard/{incident_id}` شامل inside و approaching (asset_id، name، distance_to_boundary_km و finding_id اختیاری) و closure_suggestions است. داخل از آخرین موقعیت شناخته‌شده محاسبه می‌شود. نزدیک‌شدن: خارج محدوده، در فاصله intel_hazard_approach_km=2 از مرز، کاهش فاصله در دو مشاهده اخیر معتبر، سرعت بیشتر از ۵ و عدم ارجاع به همین پرونده. فاصله مشاهدات از قاعده مشترک موتور محدود می‌شود تا حرکت قدیمی هشدار زنده نسازد. یافته hazard_approach با severity=high، شواهد هندسه و دو نقطه، latch به ازای پرونده/تجهیز و incident_id همان پرونده ثبت می‌شود؛ پرونده جدید یا فرمان نمی‌سازد. خروج از شرط، حذف/تغییر محدوده یا خاتمه پرونده یافته را رفع می‌کند.

پیشنهادها سه گشت dispatchable نزدیک مرز هستند؛ با access_points نزدیک‌ترین گشت آزاد برای هر نقطه محاسبه می‌شود (یک گشت ممکن است برای چند نقطه پیشنهاد شود). هر پیشنهاد شامل target، access_point_index اختیاری، distance_km مستقیم، eta_minutes و eta_label=تخمینی است. ارجاع از همان transition وضعیت assigned استفاده می‌کند و پس از تأیید حادثه، یک گشت پرونده را به محل حادثه اعزام می‌کند؛ کنترل چند گشت یا مسیریابی جاده‌ای وجود ندارد. گزارش JSON و چاپ وضعیت جاری محدوده و فهرست‌های داخل/نزدیک‌شونده را دارند؛ در پرونده بسته این فهرست‌های زنده خالی‌اند.

## ریسک، برآورد بیزی و راهبرد بهینه گشت

| Method | Path | رفتار |
|---|---|---|
| GET | `/intel/risk` | items با id، kind، name، field، lon/lat هدف، score، breakdown، finding_id، target_class، value و bayes؛ max_score و computed_at |
| GET | `/intel/risk/events` | دفتر شواهد مورد استفاده: سوابق واردشده، حادثه‌ها، گزارش‌های میدانی دارای مختصات، ناهنجاری پلمب و اسکن تکراری رد‌شده |
| POST | `/intel/risk/events` | نقش approval؛ `{events:[{time, category, lon/lat یا target_id, weight, description, source_ref}]}` تا ۲۰۰۰ مورد؛ source_ref کلید یکتا: تکرار همان محتوا unchanged، محتوای متفاوت 409، زمان آینده یا هدف ناشناخته 422؛ audit |
| GET | `/intel/patrol-strategy?stops=&horizon_hours=` | `PatrolStrategy` فعلی برای مجموع توقف خودروها؛ چیزی ذخیره نمی‌شود |
| GET | `/intel/patrol-game/approval` | اثر انگشت SHA-256 پارامترها و وضعیت تأیید |
| POST | `/intel/patrol-game/approve` | فقط security_manager یا admin؛ تأیید اثر انگشت فعلی با audit |
| GET | `/intel/patrol-plans` | برنامه‌های نگهداری‌شده؛ مسیر تفصیلی `/{id}` نیز موجود است |
| POST | `/intel/patrol-plans` | ساخت پیش‌نویس با shift_start، shift_end، asset_ids و stops_per_patrol؛ پاسخ 201 با `strategy` |
| POST | `/intel/patrol-plans/{id}/approve` | تأیید انسانی audited و ایجاد Missions؛ بدون اعزام یا فرمان |
| POST | `/intel/patrol-plans/{id}/discard` | کنارگذاشتن پیش‌نویس، رفع یافته پیشنهاد و audit |

امتیاز `Σ weight × normalized` است؛ هر عامل در ۰ تا ۱ است. وزن‌ها در intel_risk_weights پیش‌فرض incidents=0.4، access=0.2، staleness=0.3 و exposure=0.1 هستند؛ منفی/نامتناهی یا مجموع صفر رد می‌شود. وزن‌ها خودکار بازنرمال نمی‌شوند؛ max_score مجموع وزن‌ها و رنگ نقشه نسبت به آن است. هر ریزعامل همیشه factor، raw، normalized، weight و contribution دارد و نتیجه به Finding نوع risk_assessment با can_execute=false ارجاع دارد.

رخدادها: مجموع `exp(-ln(2) × age_days / half_life_days)` برای پرونده‌های داخل حریم، با intel_risk_incident_radius_m=500 و intel_risk_half_life_days=30؛ همه وضعیت‌های پرونده شمرده، آینده حذف و مقدار نرمال در ۱ سقف‌گذاری می‌شود. فاصله قطعه از خط و فاصله تأسیسات از مرکز آن است. این کاهش وزن زمانی فرمول ثابت است، نه یادگیری.

دیرکرد: عمر بازدید بدون گردکردن از coverage، تقسیم بر مهلت ۱۲/۸ ساعت مربوط، در ۱ سقف‌گذاری؛ never مقدار ۱. دسترسی: میانگین سه مقدار؛ راه و روستا هر کدام `max(0, 1-distance_m/1000)`، دسترسی خودروی سنگین true=1 و false=0. هر مؤلفه ناموجود 0.5 و در raw با «داده ناموجود» مشخص می‌شود. road_distance_m، village_distance_m و heavy_vehicle_access اختیاری در لایه‌های نمونه و properties ورود GeoJSON هستند؛ خصوصیات خط به قطعه‌های مشتق‌شده‌اش منتقل می‌شوند. exposure برای تأسیسات بدون سرنشین ۱ و سایر اهداف ۰ است.

```json
{"shift_start":"2026-10-09T06:00:00+03:30","shift_end":"2026-10-09T14:00:00+03:30","asset_ids":["AST-001","AST-002"],"stops_per_patrol":3}
```

برآورد بیزی: نرخ هر هدف (اقدام در سال) پیشین Gamma(r0·s, s) دارد؛ r0 نرخ پایه دسته یا مقدار اختصاصی هدف (برای قطعه و تأسیسات ضرب در 0.5+دسترسی نرمال) و s برابر prior_strength_years است. هر شاهد با وزن دسته (event_weights)، وزن خودش، کرنل گاوسی spatial_bandwidth_m (تا سه برابر آن؛ شاهد دارای target_id فقط همان هدف) و `2^(-age/half_life_days)` جمع می‌شود و مواجهه، مدت مشاهده با همان کاهش است. آغاز مشاهده نخستین محاسبه پایدار یا history_start اعلامی سازمان (هرکدام زودتر) است؛ سابقه واردشده پیش از آن هشدار می‌دهد. نرخ برنامه‌ریزی چندک risk_quantile پسین و بازه باور credible_level است.

بازی: ارزش V و احتمال اقدام ρ=1-exp(-نرخ×افق) نرمال می‌شوند؛ سود مهاجم بدون پوشش `(1-w)ρ̂ + wV̂` با w=threat_profile؛ احتمال کشف یک بازدید `min(max_detection, (attack_minutes+توقف)/افق)`؛ با پوشش `-d·capture_penalty + (1-d)·سود` و زیان مدافع `-(1-d)V̂` در برابر `-V̂`. model=stackelberg تعادل استکلبرگ قوی دقیق (ORIGAMI با حل دقیق منحنی منابع و شکست تساوی به سود مدافع)، quantal بهینه در برابر مهاجم با عقلانیت محدود quantal_rationality (گرادیان تصویرشده چندآغازی) و weighted روش قدیمی score^intel_risk_alpha است.

آغاز شیفت باید در آینده، پایان پس از آغاز و طول حداکثر هفت روز باشد؛ زمان بدون منطقه زمانی، شناسه تکراری، عضو غیرگشت یا پارامتر RNG/seed رد می‌شود. bases از Asset.patrol_base ثابت است؛ در نبود آن موقعیت فعلی با هشدار صریح استفاده می‌شود. بیشترین دیرکرد واقعی نسبت به مهلت خودِ هدف و اهداف always_visit الزامی‌اند (بیش از ظرفیت 422)؛ در نبود stale یک never با ریسک بیشتر جایگزین می‌شود. بقیه با نمونه‌گیری شانه‌ای (ترتیب تصادفی و یک آفست) دقیقاً با احتمال حاشیه‌ای راهبرد و بدون تکرار انتخاب می‌شوند؛ در model=weighted نمونه‌گیری وزن‌دار قدیمی. RNG فقط secrets.SystemRandom و پارامتر داخلی آزمون و بدون حالت ذخیره‌شده است. راهبرد پیشنهادی است و can_execute=false دارد.

ظرفیت هر گشت stops_per_patrol است؛ هر هدف به نزدیک‌ترین پایگاه دارای ظرفیت اختصاص و ایستگاه‌ها با نزدیک‌ترین همسایه مرتب می‌شوند. هدف قطعه نقطه میانی روی طول خط است. وقت‌ها در شیفت تصادفی‌اند، سفر اولیه از پایگاه و فاصله ایستگاه‌ها با eta_minutes تخمینی به‌علاوه intel_plan_dwell_minutes=10 رعایت می‌شود؛ توقف آخر نیز در شیفت جا می‌گیرد. ظرفیت بیشتر از تعداد اهداف هشدار می‌دهد و هدف تکرار نمی‌شود. زمان هدف در سه برنامه اخیراً تأییدشده نباید در حریم ±intel_plan_time_jitter_minutes=60 به وقت تهران تکرار شود؛ مقایسه ساعت از نیمه‌شب نیز عبور می‌کند. ۶۴ تلاش هر ایستگاه و ۳۲ تلاش ترتیب زمانی حد دارند؛ شیفت کوتاه یا نبود زمان سازگار 422 فارسی است و برنامه متعارض ذخیره نمی‌شود.

برنامه status=draft/approved/discarded، patrols با base و stops (مختصات، due_at، ریسک و ریز عوامل snapshot)، settings_snapshot، finding_id، warnings، mission_ids و `strategy` دارد. `PatrolStrategy` برای هر هدف دسته، ارزش، برآورد بیزی، احتمال اقدام، کشف، پوشش، احتمال انتخاب مهاجم، mandatory و selected؛ نتیجه و مبناهای uniform/proportional (و stackelberg برای مدل‌های دیگر)، درصد بهبود، آنتروپی نرمال، اثر انگشت و تأیید پارامترها، هشدارها و در صورت وجود ۵ برنامه تأییدشده آماره انطباق (مجموع مربع انحراف استاندارد پواسون-دوجمله‌ای) را دارد؛ evidence یافته برنامه پارامترهای patrol_game را نیز نگه می‌دارد؛ can_execute=false است. تأیید تکراری مأموریت اضافی نمی‌سازد، کنارگذاشتن تکراری بی‌اثر، عبور از approved به discarded یا برعکس 409 و تأیید پس از پایان شیفت 409 است. تأیید مأموریت با plan_id، plan_window_minutes و Checkpointهای دارای target_id/lon/lat/due_at ایجاد می‌کند. تأیید برنامه اعزام نیست و آمادگی آینده تجهیز تضمین نمی‌شود؛ ETA و خطوط پیش‌نمایش شماتیک‌اند.

coverage هر بازدید گشت مأموریت از target_id در due_at ± intel_plan_window_minutes=30 را ثبت می‌کند؛ مرز پنجره شامل است و بازدید در visited_at نگهداری می‌شود. پنجره در مأموریت snapshot است و تغییر تنظیمات روی مأموریت تأییدشده اثر ندارد. بازدید گشت دیگر یا خارج پنجره ایستگاه را کامل نمی‌کند. پیشرفت از همان نسبت تعداد ایستگاه‌های بازدیدشده محاسبه می‌شود. ایستگاه‌های قدیمی بدون مختصات/مهلت همچنان دستی کار می‌کنند.

شرط missed_checkpoint در موتور سیاست اجرایی است: پس از انتهای پنجره، برای هر ایستگاه بازدیدنشده با نقطه هدف در محدوده سیاست، یک هشدار با mission_id، target_id، checkpoint_index و due_at می‌سازد؛ محل فعلی ردیاب یا نداشتن GPS جدید مانع آن نیست. لچ به تفکیک سیاست/نسخه/گشت/ایستگاه است. آستانه عددی عمومی سیاست جای مهلت برنامه را نمی‌گیرد؛ موضوع، بازه زمانی، سایه و سکوت از موتور مشترک پیروی می‌کنند. ارزیابی زنده پس از اعمال coverage است؛ سایه/سکوت فقط هشدار و active مطابق مسیریابی موجود پرونده می‌سازد، بدون اعزام خودکار. آزمون این شرط از مهلت‌های مأموریت‌های نگهداری‌شده هفت روز اخیر استفاده و داده زنده را تغییر نمی‌دهد. مأموریت، برنامه، یافته و تنظیمات حافظه‌ای‌اند و reset آن‌ها را پاک می‌کند؛ یادگیری از تاریخچه گشت فاز ۳ و خارج از این نسخه است.

## گزارش خودکار شیفت (فاز ۲C)

`GET /reports/shift` آخرین شیفت کامل‌شده را می‌دهد. `intel_shifts` در settings پیش‌فرض `["06:00–14:00", "14:00–22:00", "22:00–06:00"]` دارد؛ با `engine.valid_schedule` اعتبارسنجی می‌شود، ارقام فارسی پذیرفته و بازه تکراری رد می‌شود. بازه عبوری از نیمه‌شب در روز بعد پایان می‌یابد. ساعت‌ها تهران‌اند؛ `تمام شبانه‌روز` نیز یک شیفت ۲۴ ساعته از نیمه‌شب است.

برای بازه دلخواه، **هر دو** پارامتر ISO همراه منطقه زمانی لازم‌اند؛ مانند `/reports/shift?from=2026-10-08T06%3A00%3A00%2B03%3A30&to=2026-10-08T14%3A00%3A00%2B03%3A30`. آغاز باید قبل از پایان و پایان حداکثر زمان جاری باشد؛ خطا 422 است. شمارش نیمه‌باز `[from, to)` است: رخداد دقیقاً در پایان، متعلق به شیفت بعدی است. وضعیت پایان شیفت نیز از آخرین واقعۀ قبل از پایان خوانده می‌شود.

پاسخ شامل `window_from`، `window_to` (UTC)، `timezone=Asia/Tehran`، `generated_at`، `data_since`، `data_source_id` (audit شروع دوره داده)، `partial`، `headlines`، `sections` و `can_execute=false` است. هر بخش `title`، `partial`، `notes`، `counts` و `lines` دارد. هر خط `{text, source_ids[]}` است؛ قالب فارسی قطعی، بدون مدل زبانی. خط فاقد رخداد به audit آغاز دوره استناد می‌کند تا صفرِ «ثبت‌شده» با نبود تاریخچه اشتباه نشود. شناسه حادثه، مأموریت و قطعه/تأسیسات در UI به نمای موجود متصل است؛ شناسه یافته بدون نمای جزئیات، متن منبع باقی می‌ماند.

بخش‌ها:

- `incidents`: opened/closed در بازه، still_open در پایان و severity_* برای حوادث **ثبت‌شده** در بازه؛ cycle_0..3_minutes و cycle_*_samples از نخستین اقدام متناظرِ خط زمانی در بازه، با همان store.cycle_times. اندازه‌گیری ناموجود null است؛ خط مبنای نمونه داشبورد وارد گزارش نمی‌شود.
- `coverage`: percent_ok و شمار stale/never و خط هر مورد در پایان بازه، با همان آستانه‌های پوشش. رخداد بازدیدِ بعد از پایان، گزارش گذشته را تغییر نمی‌دهد. never فقط نبود بازدید در مشاهدات موجود است.
- `trackers`: offline برای ردیاب‌هایی که وضعیت قطع در هر قسمتِ مشاهده‌شده بازه داشته‌اند، offline_known برای شمار موارد معلوم و offline_at_end برای پایان شیفت؛ connection_lost تعداد هشدارهای موتور با این شرط در بازه است. وضعیت از ثبت تغییرات موجود می‌آید؛ قطع ارتباط از سکوت دستگاه دوباره تشخیص داده نمی‌شود.
- `commands`: timed_out بر اساس updated_at پایان مهلت در بازه، همراه شناسه فرمان و تجهیز.
- `compliance`: due برای ایستگاه‌های دارای due_at در بازه، visited با visited_at در پنجره مجاز و قبل از پایان شیفت، missed پس از پایان پنجره، pending برای مهلت هنوز باز و unknown برای بازدید بدون زمان ثبت‌شده. ایستگاه قدیمی بدون due_at از شمارش زمان‌دار خارج است.
- `safety`: confirmed از audit تأیید سلامت و escalated از یافته patrol_safety ثبت‌شده در بازه؛ پایان یا حرکت بعدی گشت این شمارش را پاک نمی‌کند.
- `findings`: total/shadow و شمار هر نوع و *_shadow، بر اساس created_at؛ به‌روزرسانی یک یافته همان ثبت اولیه را تکرار نمی‌کند.

عملیات حافظه‌ای‌اند. `data_since` زمان شروع سرور یا آخرین reset است؛ بخش پیش از آن شمارش نمی‌شود و تمام بخش‌های متاثر `partial=true` و توضیح دارند. بازدیدها و تغییر وضعیت ردیاب موجود با زمان در `state.report_history` نگهداری می‌شوند تا پایان شیفت بازسازی شود؛ retention_days بر این دو تاریخچه اعمال می‌شود و گذر از مرز نگهداری نیز صریحاً جزئی/ناموجود است. تغییر لایه یا تنظیمات پس از پایان بازه، بازسازی پوشش قدیمی با هندسه/آستانه جاری را نامعتبر می‌کند؛ percent_ok/stale/never به‌جای حدس null هستند. داده GPS پایدار به‌تنهایی تاریخچه کامل عملیات نیست.

worker هنگام عبور از پایان هر شیفت دقیقاً یک audit «تولید گزارش شیفت» با ابتدا/انتهای UTC ثبت می‌کند؛ در جهش زمانی، مرزهای طی‌شده جدا ثبت می‌شوند. فقط شناسه بازه و cursor ثبت می‌شود؛ هیچ نسخه‌ای از داده گزارش ذخیره نمی‌شود. GET گزارش تشخیص، یافته، پرونده یا فرمان تازه‌ای تولید نمی‌کند. رابط در داشبورد مدیریتی با query مستقل سه‌ثانیه‌ای، بازه دلخواه، چاپ از پوسته مشترک گزارش حادثه و JSON از shared/lib/download ارائه می‌شود. دستیار در پرسش «گزارش شیفت» اعداد اصلی و source_ids همین گزارش را می‌دهد.

## زیرساخت ورودی‌های فاز سوم (§۱۰، قابلیت‌های ۴ و ۵)

پیش‌فرض و پس از reset، `intel_pressure_enabled=false` و `intel_anpr_enabled=false` هستند. هیچ رخداد فشار/پلاک اولیه، شبیه‌سازی سنسور یا تولید پس‌زمینه وجود ندارد. فقط payload صریحِ منبع بیرونی پردازش می‌شود؛ این قرارداد HTTP احراز هویت دستگاه یا تأیید واقعی مجوز بهره‌برداری نیست. اتصال سازمانی و معتبرسازی منبع باید پیش از فعال‌سازی فراهم شوند. ورودی‌ها، لچ‌ها و یافته‌ها حافظه‌ای‌اند و reset آن‌ها را پاک می‌کند.

| Method | Path | رفتار |
|---|---|---|
| POST | `/intel/ingest/pipeline-pressure` | ورودی یک‌طرفه افت فشار؛ 201 با event/finding/incident اختیاری؛ در حالت غیرفعال 409 با «نیازمند مجوز بهره‌برداری و اتصال یک‌طرفه» |
| POST | `/intel/ingest/plate-read` | خوانش واقعی پلاک؛ 201 با event/alerts/findings/incidents؛ در حالت غیرفعال 409 فارسی |

فشار:

```json
{"pipeline_id":"PIPE-REGISTERED","chainage_m":750,"time":"2026-10-08T10:00:00Z","pressure_drop_pct":25,"source":"SCADA-ONEWAY-RX"}
```

شناسه خط لوله باید ثبت‌شده باشد. دقیقاً یکی از chainage_m (متر از ابتدای خط) و segment_id لازم است؛ قطعه باید متعلق به همان خط باشد. مرز مشترک متعلق به قطعه بعدی و نقطه پایان متعلق به آخرین قطعه است. افت فشار مثبت و حداکثر ۱۰۰ درصد، زمان همراه timezone و حداکثر زمان جاری، و source غیرخالی لازم‌اند. نام‌های صریح نمونه/demo/synthetic/simulated پذیرفته نمی‌شوند؛ این کنترل جای احراز اصالت منبع را نمی‌گیرد. خط/قطعه ناموجود 404 و محل/مقدار نامعتبر 422 است.

برای هر رخداد مستقل، یافته pressure_drop با هندسه، مقدار، منبع و زمان ورودی ساخته می‌شود. `intel_pressure_mode=shadow` پیش‌فرض است؛ active فقط با لحاظ shadow_mode و maintenance_silence از مسیریابی مشترک پرونده می‌سازد. severity=high است. pressure_context پرونده شامل شناسه رخداد/خط/قطعه، last_visit از snapshot پوشش در زمان دریافت و nearest_patrol آزاد بر اساس همان nearby_patrols است. پیشنهاد در backup_patrols قرار می‌گیرد و assigned_to تهی می‌ماند. nearest_patrol_position_source مشخص می‌کند موقعیت گشت reported یا simulated است؛ هندسه و بازدید موجود ممکن است شماتیک/نمونه باشند و زمینه‌اند، نه دلیل تشخیص افت فشار. منبع تشخیص فقط افت فشار دریافتی است.

**سامانه هیچ‌گاه به سامانه‌های کنترل فرایند نمی‌نویسد.** این مسیر فقط دریافت، ثبت محلی، یافته و پرونده حراستی است؛ هیچ فرمان کنترل، تغییر فشار/شیر، اتصال نوشتنی یا اعزام گشت ایجاد نمی‌کند.

پلاک‌خوان:

```json
{"camera_id":"CAM-REGISTERED","plate":"۱۲الف ۳۴۵-۶۷","time":"2026-10-08T20:00:00Z","vehicle_class":"heavy"}
```

camera_id باید در فهرست دوربین‌های ثبت‌شده باشد؛ time دارای منطقه زمانی و غیرآینده، vehicle_class یکی از heavy/light/unknown و plate غیرخالی لازم‌اند. ارقام فارسی/عربی به لاتین، ي/ك به ی/ک و حروف لاتین به بزرگ تبدیل و فاصله/خط تیره حذف می‌شوند. همان نرمال‌سازی برای `intel_vehicle_allowlist=[]` به‌کار می‌رود؛ پلاک مجاز در هر دو قاعده نادیده گرفته می‌شود. هیچ ردیاب یا خودرو ساختگی به ناوگان اضافه نمی‌شود؛ محل خوانش از مشخصات همان دوربین ثبت می‌شود.

دو شرط موجود engine اجرایی شده‌اند، بدون مسیر هشدار موازی:

- unknown_vehicle: heavy غیرمجاز در `intel_anpr_night_hours="22:00–06:00"` با engine.in_schedule و ساعت تهران؛ محدوده، موضوع و بازه خودِ سیاست نیز باید منطبق باشند.
- camera_event: پلاک غیرمجاز در حداقل دو دوربین **متفاوت و حساس** طی `intel_anpr_repeat_window_minutes=30`. شناسه دوربین‌های حساس را اپراتور صریحاً در `intel_anpr_sensitive_camera_ids=[]` تعیین می‌کند؛ شناسه ناموجود/تکراری رد می‌شود. خوانش چندباره یک دوربین کافی نیست؛ بازه شامل دو سر است و فقط خوانش‌های ثبت‌شده تا زمان همان event استفاده می‌شوند. رده خودرو در این قاعده محدود به heavy نیست.

آستانه عمومی عددی سیاست برای این دو شرط استفاده نمی‌شود؛ قاعده اول یک خوانش و قاعده دوم حداقل دو دوربین می‌خواهد. قالب‌های سیاست اولیه این دو شرط سایه‌اند، ولی پرچم ANPR خاموش است. هر انطباق موتور یک alert و Finding مستند با شناسه خوانش‌ها/دوربین‌ها/سیاست دارد؛ active مطابق مسیریابی مشترک پرونده می‌سازد، بدون اعزام یا فرمان. لچ به تفکیک سیاست/نسخه/پلاک است؛ تا رفع شرط یا سکوت طولانی‌تر از پنجره تکرار، خوانش‌های منطبق همان دوره هشدار تازه نمی‌سازند. created_at یافته و پرونده زمان دریافت است؛ time خوانش در evidence نگهداری می‌شود تا ورودی دیررس، تاریخچه عملیاتی قبل از شروع سرور را جعل نکند.

تکرار فشار با همان خط/قطعه/فاصله طولی/زمان/منبع یا پلاک با همان دوربین/پلاک نرمال‌شده/زمان UTC همان رخداد را برمی‌گرداند؛ اختلاف افت فشار یا رده خودرو در همان کلید، 409 است. `POST /cameras/{id}/event` با `{"event":"plate","plate":...,"time":...,"vehicle_class":...}` به همین plate-read متصل است و همان idempotency را دارد. payload قبلیِ فقط event و رخدادهای intrusion/fire، حتی پس از فعال‌سازی، 409 می‌گیرند؛ از دکمه‌های نمونه دیگر پرونده یا یافته تولید نمی‌شود. تحلیل تصویر، ONVIF/VMS و اتصال فیزیکی اینجا پیاده نشده‌اند.

آزمون گذشته unknown_vehicle/camera_event فقط خوانش‌های accepted/reported نگهداری‌شده هفت روز اخیر را در sandbox سایه بازپخش می‌کند؛ یافته و پرونده زنده تغییر نمی‌کنند. نبود خوانش واقعی با 422 فارسی اعلام می‌شود و GPS/نمونه دوربین جایگزین نمی‌شود.

قابلیت ۶، ناهنجاری خودروی سازمانی، **هیچ تشخیص و endpoint جدیدی ندارد**. پیش‌نیازها سیاست حریم خصوصی مصوب، هویت واقعی و RBAC (§۱۴)، و audit دسترسی مشاهده‌کننده‌اند؛ این زیرساخت جای هیچ‌کدام را نمی‌گیرد.

## فاز صفر: هویت و گشت پایدار

همه مسیرها با پیشوند `/api/v1` هستند. `/auth/config` عمومی است و mode/issuer/client/admin_url و classification را می‌دهد؛ `/auth/me` Principal و `/auth/permissions` ماتریس واقعی authz را می‌دهند. HTTPBearer در OpenAPI ثبت شده است. مدل‌های کامل و فیلدهای لازم در OpenAPI تولیدشده هستند.

| Method | Path | مجوز و رفتار |
|---|---|---|
| GET | `/guards` | فهرست در حوزه claims؛ guard فقط خودش |
| PUT | `/guards/{id}/identity` | فقط admin؛ `{sub}`؛ پیوند صریح با audit |
| PUT | `/guards/{id}/scope` | فقط admin؛ zone_id و contractor_id |
| PUT | `/guards/{id}/credentials` | فقط admin؛ pin و duress_pin؛ فقط hash ذخیره می‌شود |
| POST | `/devices/enrollment-codes` | admin؛ owner_sub و ttl_seconds بین ۳۰ و ۶۰۰ |
| POST | `/devices/enroll` | Keycloak token و code یک‌بارمصرف؛ device_secret فقط پاسخ اول |
| GET | `/devices` | admin همه؛ دیگران فقط دستگاه خود؛ بدون secret |
| POST / PUT | `/devices/{id}/revoke` و `/certification` | admin؛ ابطال یا ex_certified |
| GET / POST | `/tour/routes` | خواندن در حوزه؛ ساخت برای کارکنان مجاز با guard_id |
| PUT | `/tour/routes/{id}/coverage` | فقط security_manager یا admin؛ `{coverage_mode, stations_per_tour, subset_mode}` با all یا optimized و shadow یا active؛ تعداد هر دور کمتر از کل و نه کمتر از ایستگاه‌های الزامی (ابتدا/انتهای ثابت و always_visit) وگرنه 422؛ audit |
| GET | `/tour/routes/{id}/strategy?horizon_hours=&stations_per_tour=` | پیش‌نمایش احتمال بازدید هر ایستگاه (`PatrolStrategy`)؛ چیزی ذخیره نمی‌شود |
| GET / POST | `/tour` | خواندن در حوزه؛ آغاز فقط مالک نگهبان با route_id و دستگاه |
| GET / POST | `/tour/{id}` و `/tour/{id}/complete` | خواندن در حوزه؛ پایان فقط مالک |
| POST | `/tour/{id}/check-in` | مالک و دستگاه؛ tag_id و pin؛ PIN اضطرار پاسخ عادی یکسان دارد |
| GET / POST | `/tour/tags/list` و `/tour/tags` | خواندن بدون کلید؛ ساخت scoped برای کارکنان مجاز |
| GET / POST | `/messages` و `/media` | حوزه و مالک tour؛ قرارداد کامل پیام و رسانه در بخش فاز پنج |
| GET | `/reports/tour` | نقش export مجاز؛ داده scoped و audit |
| GET / POST | `/approvals` | صف و درخواست اقدام حساس |
| POST | `/approvals/{id}/approve` یا `/reject` | نقش مجاز و sub متفاوت؛ target دست‌نخورده |
| POST | `/exports` | مجوز دانلود/چاپ؛ label، time و audit_id؛ همیشه audit |
| GET | `/audit/role-changes` | فقط auditor؛ آخرین صد Admin Event Keycloak از کلاینت view-events |

تأییدها actionهای rotate_tag_key، revoke_tag، delete_route و change_classification دارند؛ تغییر طبقه‌بندی فقط admin است. تغییر مستقیم classification_label با PUT settings رد می‌شود. مسیر دارای tour فعال قابل حذف نیست. تأیید تکراری یا target تغییرکرده 409 است.

محوطه و پیمانکار فقط از groups توکن خوانده می‌شوند؛ query دامنه دسترسی را گسترش نمی‌دهد. guard بدون پیوند 403 `guard_not_linked` می‌گیرد و درخواست میدانی او جز enrollment به `X-Device-Id` نیاز دارد. دستگاه ابطال‌شده 401 `device_revoked`، دستگاه دیگر 403 و دستگاه ناموجود/جاافتاده 401 است. خطای امنیتی ساختار `detail: {code, message}` دارد؛ الگوریتم/امضا/issuer/audience/azp/expiry نامعتبر 401 است. PIN نادرست 403 و پس از پنج تلاش محدود می‌شود. کد enrollment منقضی یا مصرف‌شده رد می‌شود.

هر پاسخ `X-Classification` با مقدار RFC8187 به شکل `UTF-8''...` دارد؛ حالت demo سربرگ `X-Sepehr-Demo: 1` دارد. JSON/چاپ خروجی برچسب و شناسه ممیزی دارند. pin_hash، duress_pin_hash، کلید تگ و device_secret در فهرست‌ها برنمی‌گردند. تعویض پیوند هویت، PIN قدیمی را حذف و دستگاه‌های sub قبلی را باطل می‌کند. نشست‌های Keycloak باید در runbook دستی باطل شوند.

گشت، پیوند، دستگاه، پیام، metadata رسانه، تأیید، طبقه‌بندی و audit از SEPEHR_FIELD_DB پس از startup بازسازی می‌شوند؛ reset دمو آن‌ها را پاک نمی‌کند. API باینری رسانه، اتصال و شخصی‌سازی RF واقعی تگ و ذخیره refresh در اپ میدانی متعلق به فازهای بعدی‌اند؛ اعتبارسنجی SUN فاز یک سمت سرور اضافه شده است.

## فاز یک: ایستگاه، وظیفه و تگ

پیشوند همه مسیرها `/api/v1` است و مسیرهای زیر همیشه محافظت می‌شوند. roles مجاز station_read در `/auth/permissions` هستند؛ guard دستگاه و پیوند لازم دارد. محوطه/پیمانکار ایستگاه از claims محدود می‌شوند، حتی اگر query محوطه دیگری بدهد. UI جداگانه توسعه می‌یابد.

| Method | Path | رفتار |
|---|---|---|
| GET / PUT | `/tour/zones` و `/tour/zones/{id}` | فهرست محوطه‌های مجاز؛ ثبت پایدار name/points/media_capture_allowed فقط admin |
| GET / POST | `/tour/stations` | فهرست scoped؛ ساخت با مجوز manage |
| GET / PUT | `/tour/stations/{id}` | جزئیات/ویرایش scoped؛ UID، mode، حوزه و revision مستقیم تغییر نمی‌کنند |
| POST | `/tour/stations/{id}/tag-status` | فقط damaged همراه reason؛ revoke از approvals |
| GET | `/tour/stations/{id}/tag-sheet` | export مجاز و audit؛ فقط code و SVG برای چاپ فیزیکی استفاده شوند |
| POST | `/tour/stations/{id}/sun-provisioning` | فقط admin و planned؛ کلید و NDEF/offset، no-store و audit |
| POST | `/tour/stations/{id}/install` | manage؛ اولین اسکن نصاب و موقعیت؛ planned→installed |
| POST | `/tour/stations/{id}/verify-tag` | proof مصرف‌شدنی NFC و assurance، نیازمند installed |
| GET / POST | `/tour/stations/{id}/tasks` | خواندن scoped / ساخت وظیفه با manage |
| POST | `/tour/stations/{id}/tasks/{task_id}/seal` | manage؛ expected_value جدید و reason؛ تاریخچه و audit |
| POST | `/tour/stations/{id}/visits` | guard مالک گشت؛ tour_id، payload، lon و lat |
| GET | `/tour/station-visits` | فهرست scoped؛ guard فقط بازدید خود |
| POST | `/tour/station-visits/{id}/confirm` | guard دوم، sub متفاوت، اسکن و موقعیت خودش |
| POST | `/tour/station-visits/{id}/tasks/{task_id}` | value یا media_id مطابق نوع؛ فقط مالک بازدید باز |
| GET | `/tour/station-visits/{id}/results` | پاسخ‌ها، anomaly و evidence در حوزه مجاز |
| POST | `/tour/station-visits/{id}/complete` | کنترل dwell، نفر دوم، وظایف، نسخه تگ و گشت فعال |
| POST | `/tour/station-visits/{id}/cancel` | مالک بازدید باز، reason الزامی؛ cancelled و audit |

Station افزوده‌های sensitivity، hazards، min_dwell_seconds، two_person_required، media_capture_allowed، tag_mode، tag_status و tag_revision دارد. sensitivity باید در RuntimeSettings.station_sensitivity_labels باشد؛ فهرست از PUT settings با admin قابل تغییر و پایدار است. مقدار غایب/null رسانه از محوطه به ارث می‌رسد. NFC نیازمند tag_uid هگز ۱۴ نویسه و یکتا است. statusهای planned/installed/damaged/revoked به فرایند سرور محدودند.

StationTask ورودی number با min/max/unit، choice با options، seal با expected_value و audio بدون پیکربندی اضافی دارد. فقط پیکربندی همان kind پذیرفته می‌شود. پاسخ number عدد واقعی محدود به بازه شامل دو انتها است؛ رشته عددی یا boolean پذیرفته نمی‌شود. پاسخ choice عضو options است. seal رشته مشاهده‌شده را با مقدار snapshot مقایسه و در عدم تطابق anomaly=true ثبت می‌کند. audio به media_id صوتی متعلق به همان مالک و گشت اشاره می‌کند؛ باینری رسانه از مسیرهای فاز پنج منتقل می‌شود. پاسخ ثبت‌شده بازنویسی نمی‌شود.

payload حالت qr_hmac/code برابر `SPH2:<kid>:<station_id>:<rev>:<hmac>` است؛ hmac هگز ۳۲ نویسه از HMAC-SHA256 کوتاه‌شده است. SUN URL شخصی‌سازی شامل `tag=<SPH2...>&picc=<32hex>&cmac=<16hex>` با همین ترتیب و ASCII بدون percent encoding است. offsetهای SUN بر حسب بایت از ابتدای فایل NDEF شامل NLEN هستند؛ MACInput از tag= تا قبل از مقدار cmac است. nfc_counter URL با tag/uid/counter می‌پذیرد، counter شش هگز عددی است و assurance همیشه «ضعیف» است. QR/code assurance «ایستا» و SUN «قوی» دارند؛ این مقدار در بازدید و گزارش نیز می‌آید.

revision قدیمی `tag_revision_stale`، کلید غیرفعال `tag_key_inactive`، شمارنده مساوی/کمتر `tag_replay` و CMAC نامعتبر `invalid_sun` با 403 رد می‌شوند. تگ نصب‌نشده/آسیب‌دیده/باطل، وظایف ناقص یا dwell ناکافی 409 می‌گیرند؛ حوزه و ضبط ممنوع 403 هستند. چرخش یا ابطال با همان actions فاز صفر و target_id ایستگاه در `/approvals` انجام می‌شود؛ همان sub نمی‌تواند تأیید کند و تگ چرخیده نصب مجدد لازم دارد. verify-tag شمارنده معتبر را مصرف می‌کند؛ proof همان اسکن را سپس برای visits دوباره استفاده نکنید. retry پس از پاسخ موفق نیازمند اسکن تازه است.

`/reports/tour` اکنون station_visits و task_results را نیز scoped و audited می‌دهد. فاز یک به UI، map layer یا بسته frontend تازه نیاز ندارد؛ تنها قراردادهای تولیدشده تغییر کرده‌اند.

## فاز دو: شیفت، برنامه و صف گشت پیاده

پیشوند مسیرها `/api/v1` است. بدنه دقیق و وضعیت‌های مجاز در `docs/openapi.json` هستند. الگوی `DEFAULT` از `RuntimeSettings.intel_shifts` مشتق می‌شود و بازه‌های پیش‌فرض گزارش شیفت را تغییر نمی‌دهد. الگوی تازه `segments` با `start` و `duration_minutes` تا ۱۴۴۰، `cycle` اختیاری با `on_days/off_days/anchor_date` و `breaks` با دقیقه نسبت به آغاز بخش دارد. تاریخ‌ها ISO و زمان‌های پاسخ UTC هستند؛ UI باید آن‌ها را به تهران نمایش دهد.

| Method | Path | رفتار |
|---|---|---|
| GET / POST | `/tour/shift-patterns` | فهرست شامل DEFAULT؛ ساخت الگو فقط manage |
| GET / POST | `/tour/schedules` | فهرست scoped؛ ساخت draft با route_id، pattern_id، first_date، last_date و tours_per_shift؛ سقف از `tour_schedule_max_days` |
| POST | `/tour/schedules/{id}/approve` | تأیید انسانی؛ ساخت دورهای امروز/فردا با کلید پایدار، بدون اعزام |
| GET | `/tour/queue?service_date=&contractor_id=` | فقط امروز/فردا؛ materialize تکرارپذیر؛ نگهبان فقط داده خودش و ایستگاه‌های قابل نمایش را می‌بیند |
| GET | `/tour/daily?service_date=&contractor_id=` | نقش manage؛ `walking` و `vehicles` دو فهرست مستقل |
| GET / POST | `/tour/handovers` | فهرست حوزه مجاز؛ ثبت outgoing/incoming/open_items/notes با manage |
| POST | `/tour/handovers/{id}/ack` | فقط نگهبان ورودی؛ زمان و sub تأیید ذخیره می‌شود |
| GET / PUT | `/tour/emergency/{zone_id}` | مشاهده scoped؛ تغییر فقط security_officer، security_manager یا admin، با دلیل و audit |

`TourRouteInput` اکنون station_ids، order_mode، fixed_first، fixed_last و must_precede دارد. ایستگاه‌ها باید در حوزه مسیر باشند و قیود چرخه‌دار رد می‌شوند. `TourInput.scheduled_tour_id` برای دور برنامه‌ریزی‌شده لازم است؛ هنگام وجود برنامه تأییدشده برای مسیر و تاریخ، شروع دستی همان مسیر 409 می‌دهد. در حالت `handover_required` شروع دور تا تحویل تأییدشده مجاز نیست. بازدید دور برنامه‌ریزی‌شده فقط برای ایستگاه بعدی پذیرفته می‌شود. مسیرها برای guard بدون station_ids برمی‌گردند تا ترتیب کامل آشکار نشود. در مسیر optimized هر دور ساخته‌شده زیرمجموعه پیشنهادی را با نمونه‌گیری شانه‌ای از بذر همان دور در `proposed_station_ids` و یافته tour_subset (شناسه در `selection_finding_id`) ثبت می‌کند؛ فقط وقتی allow_subset_tours روشن، پارامترها تأییدشده و تصمیم routing (subset_mode و shadow_mode/maintenance_silence سراسری) مجاز باشد `station_ids` همان زیرمجموعه و `selection_mode=optimized` است، وگرنه همه ایستگاه‌ها با هشدار دلیل؛ قید تقدم فقط بین ایستگاه‌های انتخاب‌شده اعمال می‌شود و صف نگهبان پیشنهاد را نمی‌بیند.

تنظیمات تازه: `tour_schedule_max_days=31`، `tour_time_jitter_percent=15`، `queue_reveal=next_n`، `queue_reveal_count=1`، `handover_required=false`، `two_person_window_minutes=15` و `heat_profile`. پروفایل گرما فقط هشدار می‌دهد؛ برنامه را رد نمی‌کند. تصادفی‌سازی از RNG تزریقی در آزمون و بذر امن ذخیره‌شده سمت سرور در اجرا استفاده می‌کند. فعال‌سازی اضطرار، دورهای queued محوطه را excused می‌کند و missed checkpointهای همان محوطه را در موتور مشترک از هشدار خارج می‌کند؛ خاموش‌کردن اضطرار دورهای excused را خودکار دوباره فعال نمی‌کند. API فاز دو UI جداگانه دارد.

## فاز سه: شواهد اسکن و ایمنی نگهبان

پیشوند مسیرها `/api/v1` است. هر پاسخ، حتی خطا، `X-Server-Time` بر اساس ساعت UTC سرور دارد. برنامه میدانی باید لنگر سرور و ساعت دستگاه همان لحظه را با هر اسکن بفرستد. `StationScan` اکنون `device_time`، `anchor_server_time`، `anchor_device_time`، `accuracy_m` و `client_id` اختیاری دارد؛ دو لنگر باید با هم ارسال شوند. GPS ناموجود یا نامطمئن اسکن بازدید را رد نمی‌کند؛ نصب اولیه تگ همچنان موقعیت داخل محوطه می‌خواهد. `client_id` برای همان نگهبان یکتا است؛ retry فقط با محتوای یکسان، همان بازدید را بدون مصرف دوباره SUN برمی‌گرداند و محتوای متفاوت 409 می‌گیرد.

| Method | Path | قرارداد و مجوز |
|---|---|---|
| POST | `/tour/stations/{id}/visits` | نگهبان مالک گشت؛ اسکن تگ و شواهد؛ H2S/flammable به `gas_detector_confirmed=true` نیاز دارد. پاسخ `scan_id`، `trust_level` و `hazard_flags` دارد. |
| GET | `/tour/scans` | نگهبان فقط اسکن‌های خودش؛ کارکنان در حوزه مجاز با audit هر مشاهده. رکورد scans فقط درج می‌شود؛ replay ردشده نیز با status=rejected ثبت می‌شود. |
| POST | `/tour/stations/{id}/manual-scan` | نگهبان مالک؛ `tour_id`، `reason`، `client_id` و شواهد اختیاری. UID مطابق تگ می‌تواند ارسال شود، ولی فقط `uid_only` با اعتماد low است. هر دو حالت دستی/UID در `pending_review` می‌مانند. |
| POST | `/tour/scans/{id}/review` | shift_supervisor و نقش‌های مدیریتی مجاز در همان حوزه؛ `{approved,reason}`؛ پس از تأیید، بازدید فعال ساخته می‌شود. اسکن خارج از ترتیب قابل تأیید نیست. |
| POST | `/tour/unlock` | نگهبان با گشت فعال، دستگاه ثبت‌شده و `{tour_id,pin}`؛ پاسخ عادی/اضطرار یکسان است. |
| POST | `/tour/{id}/check-in` | PIN معمولی/اضطرار از مسیر مشترک؛ event اجبار در پاسخ نگهبان منعکس نمی‌شود. فاصله مجاز گشت پیاده از `heat_profile.checkin_minutes` است و دیرکرد یافته shadow مستند می‌سازد. |
| POST | `/tour/safety-events` | نگهبان مالک گشت؛ `{tour_id,type:sos|man_down,client_id,motionless_seconds?,fall_detected?}`. رسید اول زمان دریافت سرور است؛ SOS به پرونده حادثه متصل می‌شود، man_down یافته shadow بدون اقدام خودکار دارد. |
| GET | `/tour/safety-events/{id}/receipt` | فقط صاحب SOS/man_down؛ `operator_ack_at` تا رسید انسانی null است. گزارش duress از این مسیر قابل‌دیدن نیست. |
| POST | `/incidents/{id}/ack` | نقش امنیتی؛ رسید انسانی SOS، زمان و actor در پرونده/رویداد ثبت می‌شود. |
| GET / POST | `/tour/safety-alerts` (GET) و `/tour/safety-alerts/{id}/ack` (POST) | فقط نقش امنیتی؛ دریافت فهرست و رسید duress/man_down. SOS فقط از مسیر پرونده ack می‌شود. |
| GET | `/tour/safety-alerts/stream` | SSE نقش امنیتی؛ سطح operator، shift_supervisor، security_officer از زمان دریافت و `field_sos_escalation_seconds` محاسبه می‌شود. |
| POST / GET | `/tour/musters` | ایجاد با security_officer و بالاتر برای zone_id و contractor_id؛ نگهبان فقط اعلان خودش، مرکز فهرست پاسخ و `unanswered_guard_ids` را می‌بیند. |
| POST | `/tour/musters/{id}/respond` | نگهبان شرکت‌کننده؛ `safe` یا `need_help`، تکرار همان پاسخ idempotent است. |
| GET | `/tour/musters/stream` | SSE اعلان‌های حضورشماری با دید محدود نقش؛ کلاینت باید Bearer و X-Device-Id را همراه fetch بفرستد. |

بردار `ScanEvidence` شامل tag (`sun_valid`/`counter_ok`/`hmac_valid`/`uid_only`/`manual`/`replay`)، location (`verified`/`unverified`/`unavailable`/`implausible`)، sequence، dwell و clock است. trust با قاعده قطعی در `app/tour.py` محاسبه می‌شود: روش دستی/UID/replay، جهش GPS، پسروی ساعت، ترتیب نادرست یا dwell کوتاه low است؛ SUN با موقعیت و ساعت معتبر و dwell کامل high؛ سایر شواهد پذیرفته‌شده حداکثر medium هستند. رکورد اسکن هنگام ورود ثبت می‌شود؛ `StationVisit.trust_level` پس از گذشت dwell هنگام تکمیل به‌روز می‌شود، ولی رکورد اسکن اولیه تغییر نمی‌کند. این برچسب‌ها ادعای اثبات قطعی حضور یا اصالت GPS نیستند.

`RuntimeSettings` آستانه‌های `field_location_max_accuracy_m`، `field_location_max_speed_kmh`، `field_clock_skew_seconds`، `field_man_down_idle_seconds`، `field_man_down_countdown_seconds` و `field_sos_escalation_seconds` را دارد. تشخیص عدم تحرک/سقوط و شمارش معکوس در کلاینت میدانی انجام می‌شود؛ سرور رویداد گزارش‌شده با دستگاه/گشت معتبر و آستانه را می‌پذیرد، نه اینکه حسگر گوشی را مستقل مشاهده کند. `FieldZone.emergency_contacts` فهرست تماس همان محوطه است. ذخیره رمز‌شده کلاینت، ویدئو/صوت باینری، پایش قابل اتکا در پس‌زمینه و آزمون گوشی Ex هنوز انجام نشده‌اند.

## فاز چهار: دریافت صف آفلاین امضاشده

پیشوند مسیرها `/api/v1` است. `SignedQueueRecord` دارای `kind`، `device_id`، `client_id`، `captured_at`، `previous_device_time`، `payload` و `signature` هگز ۶۴ نویسه‌ای است. امضا HMAC-SHA-256 با `device_secret` ثبت‌شده روی JSON قطعی همه فیلدها جز `signature` است (`fieldstore.canonical`: کلیدها مرتب، بدون فاصله، UTF-8). رشته‌های زمان همان صورت ارسالی را در امضا حفظ می‌کنند؛ هر دو باید ISO دارای منطقه زمانی باشند. `previous_device_time` حتی در رکورد نخست با مقدار null جزو امضا است. شناسه درخواست در retry باید بدنه یکسان داشته باشد.

| Method | Path | قرارداد و مجوز |
|---|---|---|
| POST | `/tour/offline/emergency` | فقط `kind=sos|duress|man_down` با امضای دستگاه فعال و گشت متعلق به آن؛ Bearer معتبر لازم نیست. توکن منقضی/نامعتبر یا غایب باعث `auth_expired=true` در هشدار امنیتی می‌شود. SOS و man_down همان `FieldSafetyInput`، duress فقط `{tour_id}` را در payload دارند. رسید SOS/man_down مطابق فاز سه است؛ پاسخ duress در رابط نمایش داده نشود. |
| POST | `/tour/offline/scans` | `kind=scan`، Bearer معتبر نگهبان و `X-Device-Id`، payload اسکن شامل `station_id` و `StationVisitInput`. زمان و `client_id` پوش رکورد باید با payload برابر باشند؛ همان مسیر بازدید و اعتبار تگ استفاده می‌شود. |
| POST | `/assets/{id}/positions:batch` | `records` از ۱ تا ۱۰۰ رکورد امضاشده `kind=position`، فقط تجهیز همان نگهبان، Bearer و `X-Device-Id` معتبر. هر payload همان `PositionInput` و زمان آن برابر `captured_at` است. درج از مسیر `TrackStore.append` موجود و تکرار موقعیت یکسان idempotent است. خطای میانه بسته می‌تواند درج قبلی را باقی بگذارد؛ retry همان رکوردها امن است. |

امضای نامعتبر و دستگاه باطل‌شده با 403 رد و audit می‌شوند. پاسخ API دارای `Cache-Control: no-store` است. اسکن با فاصله بیش از `RuntimeSettings.max_offline_minutes` از زمان ثبت دستگاه، `offline_flags=[offline_too_long]` می‌گیرد و trust نهایی آن حداکثر medium است. اگر `device_time` از `previous_device_time` عقب‌تر باشد، `clock_regressed` در offline_flags و شاهد clock=regressed ثبت می‌شود. `FieldSafetyAlert` نیز `auth_expired` و `clock_regressed` را برای مرکز دارد. سه تنظیم دیگر `offline_pbkdf2_iterations` و `offline_shift_grace_minutes` برای کلاینت و `max_offline_minutes` برای سرورند؛ مقدارشان از `/settings` خوانده شود.

Cache Storage پوسته، IndexedDB رمز‌شده با AES-GCM/PBKDF2، نگهداری CryptoKey، پاک‌سازی خروج/ابطال، backoff/jitter، ترتیب اولویت و هشدار کمبود فضا کار کلاینت مستقل است؛ قرارداد و معیار پذیرش در `docs/UI-HANDOFF.fa.md` آمده است. گزارش از صف با `POST /tour/offline/reports` و رسانه با آپلود قطعه‌ای قابل ازسرگیری فاز پنج ارسال می‌شود. پذیرش اضطرار بدون Bearer فقط برای مسیر ویژه بالا و فقط پس از HMAC دستگاه فعال است؛ مسیرهای دیگر احراز هویت پیشین را حفظ می‌کنند.

## فاز پنج: پیام، رسانه و گزارش‌های میدانی

پیشوند `/api/v1`؛ همه مسیرها اجباری‌اند و نگهبان Bearer و `X-Device-Id` می‌فرستد. هیچ مسیری پرونده نمی‌سازد، اعزام نمی‌کند یا به سامانه بیرونی ارسال نمی‌کند.

| Method | Path | قرارداد و مجوز |
|---|---|---|
| GET / POST | `/messages` | نگهبان با `tour_id` گشت خود به مرکز می‌فرستد (`direction=to_center`). مرکز (`manage`) با `audience` دقیقاً یکی از `guard_id` (نگهبان پیوندخورده) یا `broadcast_zone` (به‌علاوه `contractor_id` اختیاری) می‌فرستد. اعلان محوطه به نگهبانان دارای گشت فعال همان محوطه و پیمانکار می‌رسد. `priority=normal|urgent`. نگهبان فقط پیام خود یا پیامی که گیرنده آن است را می‌بیند و در `recipients` فقط خودش دیده می‌شود. |
| POST | `/messages/{id}/ack` | گیرنده نگهبان «دریافت شد» صریح ثبت می‌کند؛ مرکز برای پیام نگهبان `center_ack_at` ثبت می‌کند. پیام فوری بی‌رسید پس از `message_urgent_escalation_seconds` به `shift_supervisor` و پس از دو برابر آن به `security_officer` تشدید و audit می‌شود؛ تکرار هشدار تا رسید کار کلاینت است. |
| GET / POST | `/tour/reports` | `category=security|safety_hse|operations|damage|uxo|drone_sighting|other`، `text`، `client_id` و مختصات اختیاری؛ فقط گشت فعال خود نگهبان. `client_id` تکراری با بدنه یکسان همان گزارش را برمی‌گرداند و بدنه متفاوت 409 است. `audiences` از `RuntimeSettings.report_routing` (حراست همیشه مخاطب است). damage/uxo/drone_sighting بدون `safety_acknowledged=true` رد می‌شوند، `safety_instruction` ثابت «نزدیک نشو، از فاصله امن گزارش کن» و `purge_local_media=true` دارند. فیلتر `category` و `audience` اختیاری است. |
| POST | `/tour/reports/{id}/ack` | `manage` در حوزه؛ رسید یک واحد مخاطب (`security|hse|operations`) یک‌بار ثبت و audit می‌شود. |
| POST | `/tour/offline/reports` | رکورد امضاشده `kind=report` با payload `FieldReportInput`؛ `client_id` پوش و payload برابر. پرچم‌های `offline_too_long` و `clock_regressed` روی گزارش ثبت می‌شوند. |
| GET | `/media/capture-policy?tour_id=` | برای نگهبان گشت فعال: `image_video_allowed` از محوطه و بازدید باز ایستگاه، صوت همیشه مجاز، سقف مدت و bitrate، اندازه قطعه و سقف‌ها. |
| POST | `/media` | ثبت فراداده (`status=metadata`) با `report_id` اختیاری؛ سپس `PUT /media/{id}/content?sha256=` با بدنه خام تا `media_single_upload_max_bytes` (بیش از آن 413). `Content-Type` باید از فهرست مجاز همان `media_type` باشد (415)؛ هش ناسازگار 422 `hash_mismatch`. |
| POST | `/media/uploads` | `{tour_id, caption, media_type, content_type, sha256, size, client_id, report_id?}` → `MediaUpload` با `id`، `received_bytes` و `chunk_bytes`. تکرار `client_id` با بدنه یکسان همان آپلود را برمی‌گرداند. حجم بیش از `media_max_bytes` 413. |
| PUT | `/media/uploads/{id}?offset=` | بدنه خام یک قطعه تا `media_chunk_bytes` (بیش از آن 413 `chunk_too_large`). `offset` باید دقیقاً `received_bytes` باشد؛ در غیر این صورت 409 `upload_offset_mismatch`. |
| GET | `/media/uploads/{id}` | وضعیت برای ازسرگیری؛ فقط مالک. |
| POST | `/media/uploads/{id}/complete` | فقط پس از دریافت کامل؛ sha256 کل فایل بررسی می‌شود. ناسازگاری: 422 `hash_mismatch`، آپلود `failed` و audit. موفق: `MediaUploadResult` با رسانه `stored`، `server_received_at`، دستگاه و ثبت‌کننده؛ `purge_local_copy=true` برای دسته‌های محدود. |
| GET | `/media` | نگهبان رسانه خود؛ مرکز در حوزه. رسانه damage/uxo/drone_sighting فقط برای `security_manager` و `admin` فهرست می‌شود. هر رکورد `watermark` محاسبه‌شده برای همان بیننده (تاریخ شمسی تهران، کد نگهبان، کد ایستگاه، نام بیننده) و `retention_until` و `exportable` دارد. |
| GET | `/media/{id}/content` | محتوای اصلی دست‌نخورده با `Cache-Control: no-store`، `X-Content-SHA256` و audit هر مشاهده؛ بدون URL عمومی. نگهبان پس از ارسال، رسانه محدود را دوباره دریافت نمی‌کند (403 `media_access_denied`). نشان‌آب هنگام نمایش و خروجی در کلاینت رسم می‌شود. |
| POST | `/media/{id}/attach` | `manage`؛ پیوست به پرونده موجود و `legal_hold=true` خودکار. |
| POST | `/media/{id}/legal-hold` | `security_manager` یا `admin` با دلیل؛ رفع نگهداری رسانه پیوست پرونده 409. |
| POST | `/exports` | با `media_id` برای رسانه محدود 403 `media_export_denied` و audit. |

نگهداری: `RuntimeSettings.media_retention_days` به تفکیک دسته (رسانه بدون دسته: `other`). job worker پس از پایان دوره فایل را حذف، `status=purged` و audit می‌کند؛ رسانه `legal_hold` حذف نمی‌شود و API حذف دستی وجود ندارد. آپلود باز بی‌تحرک بیش از ۲۴ ساعت بسته می‌شود. ضبط تصویر و ویدئو در محوطه یا ایستگاه بدون `media_capture_allowed` با 403 `media_capture_denied` رد می‌شود؛ متن و صوت همیشه مجازند (تصمیم ۱۳). فایل‌ها خارج از SQLite در `SEPEHR_MEDIA_DIR` یا پوشه `media` کنار پایگاه میدانی ذخیره می‌شوند.

## فاز شش: نظارت استثنامحور و گزارش گشت

| Method | Path | قرارداد و مجوز |
|---|---|---|
| GET | `/tour/exceptions` | `manage` در حوزه؛ فهرست زنده `ExceptionItem` به ترتیب شدت: `station_missed`، `station_overdue`، `scan_low_trust`، `scan_pending_review`، `alarm_unacked`، `man_down_unacked`، `duress_unacked` (فقط نقش‌های امنیتی)، `device_silent` (دستگاه گشت فعال بی‌ارتباط بیش از `exception_device_silence_minutes`)، `muster_open`، `message_urgent_unacked` و `integrity`. بازه نگاه به عقب `integrity_window_hours` است. پاسخ `suspended` (دورهای excused یا تعلیق‌شده با اضطرار)، `emergency_zone_ids`، `counts` و وضعیت ایستگاه‌ها را جدا دارد. هر مشاهده audit می‌شود. |
| GET | `/tour/station-status` | `manage`؛ `ok` فقط وقتی آخرین اسکن پذیرفته‌شده trust دست‌کم medium دارد؛ در غیر این صورت `unverified` و بدون اسکن `never`. |
| GET | `/reports/tour/summary?window_from=&window_to=&format=json|csv` | `export` و نه نگهبان؛ پیش‌فرض ۲۴ ساعت اخیر، حداکثر ۹۳ روز. پایبندی (برنامه‌ریزی‌شده، انجام‌شده، تأییدشده با trust دست‌کم medium، درصد تأیید، ازدست‌رفته، باز، تعلیق اضطرار)، توزیع اعتماد (high/medium/low، دستی، در انتظار بازبینی، تگ ضعیف nfc_counter، تکرار ردشده)، تجمیع پیمانکار و پست بدون شناسه یا رتبه فردی، وضعیت اضطرار، شمار یافته‌های یکپارچگی و استثناها و سلامت زنجیره audit. تاریخ‌ها شمسی تهران. CSV با ماژول استاندارد `csv`، UTF-8 دارای BOM و سطر طبقه‌بندی در ابتدا و انتها است. هر ساخت و خروجی با `audit_id` ثبت می‌شود. |
| GET | `/reports/tour/guards/{guard_id}` | فقط `shift_supervisor` با حوزه همان محوطه و پیمانکار، یا `auditor` در حوزه؛ سایر نقش‌ها 403 `individual_view_denied`. نتیجه هر ایستگاه برنامه‌ریزی‌شده و اسکن‌ها با شواهد؛ هر مشاهده audit می‌شود. |

تعلیق اضطرار فقط برای دورهایی اعمال می‌شود که پنجره‌شان هنگام آغاز اضطرار هنوز باز بوده است؛ اضطرار بعدی ایستگاه ازدست‌رفته را پاک نمی‌کند. وضعیت اضطرار فقط حالت جاری ذخیره می‌شود و تاریخچه آغاز/پایان چندباره را نگه نمی‌دارد.

قواعد یکپارچگی (`intel.integrity.*`) در worker با پنجره `integrity_window_hours` اجرا می‌شوند و برای هر موضوع یک Finding دارای شواهد و `can_execute=false` می‌سازند و با رفع شرط بسته می‌شوند: `short_dwell` (لغو بازدید پیش از حداقل توقف، دست‌کم `integrity_short_dwell_count` بار)، `tag_replay` (اسکن رد‌شده با تکرار/پسروی شمارنده)، `tag_distance` (اسکن یک ایستگاه توسط دو نگهبان در `integrity_pair_minutes` با فاصله بیش از `integrity_pair_km`)، `clock` (پسروی ساعت) و `offline_repeat` (دست‌کم `integrity_offline_repeat_count` اسکن offline_too_long). حالت پیش‌فرض `integrity_mode=shadow` است و تصمیم مسیریابی مشترک (`shadow_mode` و `maintenance_silence`) اعمال می‌شود؛ این قواعد در هیچ حالتی پرونده خودکار نمی‌سازند.

## فاز هفت: سخت‌سازی، فرم کاغذی و پایلوت

همه پاسخ‌ها سربرگ‌های امنیتی CSP، HSTS، `X-Frame-Options: DENY`، `Permissions-Policy` و `nosniff` دارند. بدنه JSON بیش از `max_json_body_bytes` با 413 `body_too_large` رد می‌شود. هر فیلد ناشناخته در بدنه 422 با `type=extra_forbidden` است؛ پاسخ 422 فقط `loc`، `msg` و `type` دارد و 500 فقط `internal_error`. ثبت دستگاه، PIN/تأیید حضور، اسکن و آپلود محدودیت نرخ (`rate_limit_per_minute`) دارند و تجاوز 429 `rate_limited` با `Retry-After` است؛ SOS، man_down و صف اضطراری هرگز رد نمی‌شوند و `rate_flagged=true` در هشدار امنیتی می‌گیرند.

| Method | Path | قرارداد و مجوز |
|---|---|---|
| POST | `/tour/paper-scans` | `manage` در حوزه؛ `{scheduled_tour_id, station_id, recorded_at, form_serial, notes}` ردیف فرم کاغذی را با `method=paper`، شاهد `tag=paper` و `trust=low` ثبت می‌کند؛ اگر دور در سامانه شروع نشده بود، گشت تکمیل‌شده کاغذی ساخته می‌شود. تکرار همان ردیف idempotent و مقدار متفاوت 409 است؛ ایستگاه خارج از برنامه یا زمان آینده 422. |
| POST | `/devices/{id}/capabilities` | نگهبان برای دستگاه ثبت‌شده خودش؛ `barcode_detector`، `web_nfc`، `wake_lock`، `device_motion`، `battery_level`، `charging`، شمارنده تمدید توکن و `platform`؛ بدون موقعیت. |
| GET | `/reports/pilot?window_from=&window_to=` | `export` و نه نگهبان؛ شاخص‌های قابل محاسبه پایلوت هر کدام با مقدار، واحد، تعداد نمونه و روش سنجش، به‌علاوه فهرست سنجش‌های دستی؛ ممیزی می‌شود. |

`ScanRecord.method` یکی از `tag`، `manual` یا `paper` است.

## ورود کنسول و پرونده ارزیابی امنیتی

`GET /auth/config` افزون بر `client_id` کنسول وب، `field_client_id` اپ میدانی (`SEPEHR_OIDC_FIELD_CLIENT`، پیش‌فرض `sepehr-field`) را برمی‌گرداند.

| Method | Path | قرارداد و مجوز |
|---|---|---|
| GET | `/audit/security-dossier` | فقط `auditor`؛ `SecurityDossier` شامل سامانه و حالت احراز، همه مسیرهای `/api/v1` با `authentication` (`public`، `device_signature`، `required`، `optional_unless_enforce_all`)، مجوز و نقش‌ها، سربرگ‌های امنیتی، تنظیمات امنیتی، رمزنگاری، مخازن داده با شخصی‌بودن و نگهداری و تعداد، سلامت زنجیره ممیزی و ریسک‌های باقی‌مانده؛ با `audit_id` ممیزی می‌شود. |
| GET | `/audit/security-dossier/letter` | فقط `auditor`؛ HTML قابل چاپ پیش‌نویس نامه استعلام الزام و دامنه ارزیابی افتا بدون منبع بیرونی، `Cache-Control: no-store`؛ ممیزی می‌شود. |

