export async function api<T = unknown>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    signal,
    headers: { "Content-Type": "application/json", ...sessionHeaders() },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  return parseResponse<T>(response);
}
export async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = "خطا در ارتباط با سرویس";
    let code = "";
    try {
      const e = await response.json();
      code = typeof e.detail === "object" && e.detail?.code ? e.detail.code : "";
      message =
        typeof e.detail === "string"
          ? e.detail
          : typeof e.detail?.message === "string"
            ? e.detail.message
            : "ورودی نامعتبر است";
    } catch {}
    if (response.status === 401 && session.token) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw Object.assign(new Error(message), { status: response.status, code });
  }
  return response.json();
}
// In-memory session only; tokens never touch localStorage or sessionStorage.
export const UNAUTHORIZED_EVENT = "sepehr:unauthorized";
const session: { token?: string; deviceId?: string } = {};
export function setAuthToken(token?: string) {
  session.token = token;
}
export function setDeviceId(deviceId?: string) {
  session.deviceId = deviceId;
}
export function sessionHeaders(): Record<string, string> {
  return {
    ...(session.token ? { Authorization: "Bearer " + session.token } : {}),
    ...(session.deviceId ? { "X-Device-Id": session.deviceId } : {}),
  };
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
  urgent: "فوری",
  normal: "عادی",
  to_center: "نگهبان ← مرکز",
  to_guard: "مرکز ← نگهبان",
  broadcast: "اعلان محوطه",
  operator: "اپراتور",
  shift_supervisor: "سرپرست شیفت",
  security_officer: "مسئول حراست",
  security: "حراست",
  safety_hse: "ایمنی و HSE",
  operations: "بهره‌برداری",
  damage: "خسارت",
  uxo: "مهمات عمل‌نکرده",
  drone_sighting: "مشاهده پهپاد",
  other: "سایر",
  hse: "HSE",
  metadata: "فقط فراداده",
  stored: "ثبت‌شده",
  purged: "حذف پس از نگهداری",
  image: "تصویر",
  audio: "صوت",
  video: "ویدئو",
  station_missed: "ایستگاه ازدست‌رفته",
  station_overdue: "ایستگاه سررسیدگذشته",
  scan_low_trust: "اسکن کم‌اعتماد",
  scan_pending_review: "اسکن در انتظار بازبینی",
  alarm_unacked: "اعلام خطر بی‌رسید",
  duress_unacked: "رمز اضطرار بی‌رسید",
  man_down_unacked: "عدم تحرک بی‌رسید",
  device_silent: "دستگاه بی‌ارتباط",
  muster_open: "حضورشماری باز",
  message_urgent_unacked: "پیام فوری بی‌رسید",
  integrity: "یکپارچگی گشت",
  ok: "تأییدشده",
  unverified: "تأییدنشده",
  never: "بدون اسکن",
  verified: "تأییدشده",
  visited_unverified: "بازدید کم‌اعتماد",
  missed: "ازدست‌رفته",
  pending: "باز",
  suspended: "تعلیق اضطرار",
  security_manager: "مدیر حراست",
  admin: "مدیر سامانه",
  auditor: "ممیز",
  guard: "نگهبان",
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
