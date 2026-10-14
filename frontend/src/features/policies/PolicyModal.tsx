import { Check } from "lucide-react";
import { useState } from "react";
import { executableConditions, labels, policyConditions } from "../../api";
import { Modal } from "../../shared/ui/primitives";
import type { Data, PolicyInput } from "../../types";
const flow = [
  "detected",
  "confirmed",
  "assigned",
  "en_route",
  "on_scene",
  "closed",
];
export default function PolicyModal({
  data,
  close,
  onSave,
  busy,
}: {
  data: Data;
  close: () => void;
  onSave: (p: PolicyInput) => void;
  busy: boolean;
}) {
  const [p, setP] = useState<PolicyInput>({
    name: "",
    zone: data.zones[0].id,
    subject: "vehicle",
    condition: "geofence_entry",
    threshold: 1,
    schedule: "تمام شبانه‌روز",
    severity: "high",
    action: "create_incident",
  });
  const set = <K extends keyof PolicyInput>(k: K, v: PolicyInput[K]) =>
    setP({ ...p, [k]: v });
  return (
    <Modal title="تعریف سیاست حراست" onClose={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSave(p);
        }}
      >
        <label className="field">
          عنوان سیاست
          <input
            required
            minLength={3}
            maxLength={120}
            value={p.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="برای مثال: توقف غیرعادی در حریم تأسیسات"
          />
        </label>
        <div className="form-grid">
          <label className="field">
            کجا؟
            <select
              value={p.zone}
              onChange={(e) => set("zone", e.target.value)}
            >
              {data.zones.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            چه کسی؟
            <select
              value={p.subject}
              onChange={(e) =>
                set("subject", e.target.value as PolicyInput["subject"])
              }
            >
              <option value="vehicle">خودرو</option>
              <option value="person">نیروی میدانی</option>
              <option value="all">همه موجودیت‌ها</option>
            </select>
          </label>
          <label className="field">
            چه شرطی؟
            <select
              value={p.condition}
              onChange={(e) =>
                set("condition", e.target.value as PolicyInput["condition"])
              }
            >
              {policyConditions.map((c) => (
                <option key={c} value={c}>
                  {labels[c]}
                  {executableConditions.includes(c) ? "" : " — فقط پیش‌نویس"}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            آستانه (
            {p.condition === "gps_jump"
              ? "کیلومتر بر ساعت"
              : p.condition === "route_deviation"
                ? "متر"
                : p.condition === "camera_event" ||
                    p.condition === "unknown_vehicle"
                  ? "قاعده ثابت ANPR"
                  : p.condition === "geofence_entry"
                    ? "تعداد"
                    : "دقیقه"}
            )
            <input
              type="number"
              min="1"
              max="3600"
              disabled={
                p.condition === "unknown_vehicle" ||
                p.condition === "camera_event"
              }
              value={
                p.condition === "camera_event"
                  ? 2
                  : p.condition === "unknown_vehicle"
                    ? 1
                    : p.threshold
              }
              onChange={(e) => set("threshold", +e.target.value)}
            />
          </label>
        </div>
        {(p.condition === "unknown_vehicle" ||
          p.condition === "camera_event") && (
          <p className="info-box">
            ورودی واقعی پلاک‌خوان و فعال‌سازی لازم است؛ بازه شب، پنجره تکرار،
            دوربین‌های حساس و فهرست مجاز در تنظیمات عملیات تعیین می‌شوند.
          </p>
        )}
        <label className="field">
          چه زمانی؟
          <input
            required
            value={p.schedule}
            onChange={(e) => set("schedule", e.target.value)}
          />
        </label>
        <label className="field">
          چه اقدامی؟
          <select
            value={p.action}
            onChange={(e) =>
              set("action", e.target.value as PolicyInput["action"])
            }
          >
            {["create_incident", "notify", "suggest_patrol", "log_only"].map(
              (a) => (
                <option key={a} value={a}>
                  {labels[a]}
                </option>
              ),
            )}
          </select>
        </label>
        <label className="field">
          اهمیت حادثه
          <select
            value={p.severity}
            onChange={(e) =>
              set("severity", e.target.value as PolicyInput["severity"])
            }
          >
            {["critical", "high", "medium", "low", "info"].map((v) => (
              <option key={v} value={v}>
                {labels[v]}
              </option>
            ))}
          </select>
        </label>
        <p className="info-box">
          شرط‌های مشخص‌شده با «فقط پیش‌نویس» هنوز ارزیابی نمی‌شوند. بازه زمانی،
          زمان اجرای شرط است؛ برای تردد خارج از ساعت، بازه ممنوع را وارد کنید.
          سیاست ابتدا به‌صورت پیش‌نویس ذخیره می‌شود؛ آزمون و اجرای سایه مراحل
          بعدی هستند.
        </p>
        <button className="primary full" disabled={busy} type="submit">
          <Check size={16} />
          ذخیره پیش‌نویس
        </button>
      </form>
    </Modal>
  );
}
