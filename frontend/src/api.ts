export async function api<T = unknown>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    signal,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    let message = "خطا در ارتباط با سرویس";
    try {
      const e = await response.json();
      message = typeof e.detail === "string" ? e.detail : "ورودی نامعتبر است";
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
export const fa = (n: number | string) => Number(n).toLocaleString("fa-IR");
export const timeFa = (s: string) =>
  new Date(s).toLocaleTimeString("fa-IR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Tehran",
  });
export const labels: Record<string, string> = {
  online: "برخط",
  offline: "قطع ارتباط",
  warning: "نیازمند بررسی",
  critical: "بحرانی",
  high: "زیاد",
  medium: "متوسط",
  low: "کم",
  info: "اطلاعاتی",
  detected: "کشف‌شده",
  confirmed: "تأییدشده",
  assigned: "ارجاع‌شده",
  en_route: "در مسیر",
  on_scene: "حضور در محل",
  closed: "خاتمه‌یافته",
  active: "فعال",
  shadow: "حالت سایه",
  draft: "پیش‌نویس",
  tested: "آزمایش‌شده",
  sent: "ارسال‌شده",
  delivered: "تحویل‌شده",
  executed: "اجراشده",
  timed_out: "بی‌پاسخ",
  position: "درخواست موقعیت",
  ping: "بررسی اتصال",
  interval: "فاصله ارسال موقعیت",
  restart: "راه‌اندازی مجدد",
  beacon: "هشدار صوتی / نوری",
  diagnostics: "وضعیت و عیب‌یابی",
  geofence_entry: "ورود به محدوده",
  connection_lost: "قطع ارتباط",
  route_deviation: "انحراف از مسیر",
  long_stop: "توقف غیرعادی",
  completed: "تکمیل‌شده",
  check_pending: "در انتظار تأیید سلامت",
  escalated: "نیازمند رسیدگی فوری",
};

export const policyConditions = [
  "geofence_entry",
  "unknown_vehicle",
  "route_deviation",
  "after_hours",
  "long_stop",
  "connection_lost",
  "tamper",
  "gps_jump",
  "sos",
  "missed_checkpoint",
  "correlated_events",
  "camera_event",
] as const;
Object.assign(labels, {
  unknown_vehicle: "خودروی سنگین خارج از فهرست مجاز در شب",
  after_hours: "تردد خارج از ساعت مجاز",
  tamper: "دست‌کاری یا قطع تغذیه",
  gps_jump: "جهش غیرممکن GPS",
  sos: "دکمه اضطراری",
  missed_checkpoint: "نرسیدن به ایستگاه گشت",
  correlated_events: "رخدادهای هم‌زمان",
  camera_event: "تکرار پلاک در دوربین‌های حساس",
  create_incident: "ایجاد پرونده حادثه",
  notify: "اعلان به اتاق کنترل",
  suggest_patrol: "پیشنهاد نزدیک‌ترین گشت",
  log_only: "فقط ثبت در سوابق",
});

export const executableConditions: readonly string[] = [
  "geofence_entry",
  "after_hours",
  "long_stop",
  "connection_lost",
  "gps_jump",
  "sos",
  "missed_checkpoint",
  "unknown_vehicle",
  "camera_event",
];
