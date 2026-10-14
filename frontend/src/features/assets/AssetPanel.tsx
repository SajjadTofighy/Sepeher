import { useQuery } from "@tanstack/react-query";
import { Battery, Car, History, MessageSquareText, Send, Signal } from "lucide-react";
import { useState } from "react";
import { api, fa, labels, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge, Modal } from "../../shared/ui/primitives";
import type { Asset, CommandPreview, Data, DeviceProfile } from "../../types";
import AssetSettingsForm from "./AssetSettingsForm";
const flow = [
  "detected",
  "confirmed",
  "assigned",
  "en_route",
  "on_scene",
  "closed",
];
export default function AssetPanel({
  asset: a,
  data,
  busy,
  act,
  close,
  onReplay,
}: {
  asset: Asset;
  data: Data;
  busy: boolean;
  act: Act;
  close: () => void;
  onReplay: () => void;
}) {
  const [cmd, setCmd] = useState("position"),
    [channel, setChannel] = useState("data"),
    [interval, setIntervalValue] = useState(30),
    [confirm, setConfirm] = useState(false);
  const profiles = useQuery({ queryKey: ["device-profiles"], queryFn: () => api<DeviceProfile[]>("/device-profiles"), staleTime: Infinity });
  const profile = profiles.data?.find((p) => p.id === a.device_profile);
  const preview = useQuery({
    queryKey: ["command-preview", a.id, a.device_profile, a.sms_password_set, cmd, interval],
    queryFn: () => api<CommandPreview>(`/commands/preview?asset_id=${a.id}&command=${cmd}&channel=sms&interval_seconds=${interval}`),
    enabled: channel === "sms" && interval >= 5 && interval <= 3600,
    retry: false,
  });
  const recent = data.commands
    .filter((c) => c.asset_id === a.id)
    .slice(-3)
    .reverse();
  return (
    <Modal title={a.name} onClose={close}>
      <div className="detail-tags">
        <Badge value={a.status} />
        <span className="mono">{a.id}</span>
        <span className="neutral-pill">{a.field}</span>
      </div>
      <div className="asset-stats">
        <div>
          <Car size={20} />
          <b>{fa(a.speed)}</b>
          <small>کیلومتر بر ساعت</small>
        </div>
        <div>
          <Battery size={20} />
          <b>{fa(a.battery)}٪</b>
          <small>باتری</small>
        </div>
        <div>
          <Signal size={20} />
          <b>{fa(a.signal)} / ۴</b>
          <small>سیگنال</small>
        </div>
      </div>
      <div className="detail-grid">
        <span>مأموریت</span>
        <b>{a.mission}</b>
        <span>سیم‌کارت</span>
        <b dir="ltr">{a.sim}</b>
        <span>اپراتور</span>
        <b>{a.carrier}</b>
        <span>پروفایل پیامکی</span>
        <b>{profile?.label || a.device_profile}{a.sms_password_set ? " · رمز ثبت‌شده" : ""}</b>
        <span>نسخه دستگاه</span>
        <b>{a.firmware}</b>
        <span>آخرین ارتباط</span>
        <b>{timeFa(a.last_seen)}</b>
      </div>
      <button
        className="secondary full"
        onClick={async () => {
          const r = await act(
            () => api(`/assets/${a.id}/track`),
            "تاریخچه موقعیت بارگذاری شد",
          );
          if (r) onReplay();
        }}
      >
        <History size={16} />
        بازپخش مسیر این موجودیت
      </button>
      <AssetSettingsForm asset={a} act={act} busy={busy} />
      <div className="detail-section">
        <h3>ارسال فرمان به دستگاه</h3>
        <p>ارسال و پاسخ در این محیط شبیه‌سازی می‌شود.</p>
        <div className="form-grid">
          <label className="field">
            نوع فرمان
            <select
              value={cmd}
              onChange={(e) => {
                setCmd(e.target.value);
                setConfirm(false);
              }}
            >
              {[
                "position",
                "ping",
                "interval",
                "restart",
                "beacon",
                "diagnostics",
              ].map((c) => (
                <option key={c} value={c}>
                  {labels[c]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            کانال ارتباطی
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              <option value="data">اینترنت همراه</option>
              <option value="sms">پیامک</option>
            </select>
          </label>
        </div>
        {cmd === "interval" && (
          <label className="field">
            فاصله ارسال (۵ تا ۳۶۰۰ ثانیه)
            <input
              type="number"
              min="5"
              max="3600"
              value={interval}
              onChange={(e) => setIntervalValue(+e.target.value)}
            />
          </label>
        )}
        {channel === "sms" && (
          <div className="sms-preview">
            <MessageSquareText size={16} />
            {preview.isError ? <p className="flag">{(preview.error as Error).message}</p> : preview.data ? (
              <div>
                <small>متن دقیق پیامک به {preview.data.sms_destination} (رمز دستگاه پوشیده):</small>
                <code dir="ltr">{preview.data.sms_text?.replace(/ /g, "␣")}</code>
                <small className="muted">{preview.data.note}. درگاه پیامک متصل نیست؛ تحویل نمایشی است.</small>
              </div>
            ) : <small>در حال ساخت پیش‌نمایش…</small>}
          </div>
        )}
        {confirm ? (
          <div className="confirm-box">
            <p>
              فرمان «{labels[cmd]}» برای {a.name} ثبت شود؟
            </p>
            <div>
              <button
                className="primary"
                disabled={busy || interval < 5 || interval > 3600 || (channel === "sms" && !preview.data)}
                onClick={async () => {
                  const r = await act(
                    () =>
                      api("/commands", "POST", {
                        asset_id: a.id,
                        command: cmd,
                        channel,
                        interval_seconds: interval,
                        request_id: crypto.randomUUID(),
                      }),
                    "فرمان نمایشی ارسال شد",
                  );
                  if (r) setConfirm(false);
                }}
              >
                تأیید ارسال
              </button>
              <button className="secondary" onClick={() => setConfirm(false)}>
                انصراف
              </button>
            </div>
          </div>
        ) : (
          <button className="primary full" onClick={() => setConfirm(true)}>
            <Send size={16} />
            بررسی و ارسال فرمان
          </button>
        )}
      </div>
      {recent.length > 0 && (
        <div className="detail-section">
          <h3>آخرین فرمان‌ها</h3>
          {recent.map((c) => (
            <div className="command-row" key={c.id}>
              <div>
                {labels[c.command]}
                <small>{c.id}</small>
              </div>
              <Badge value={c.status} />
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
