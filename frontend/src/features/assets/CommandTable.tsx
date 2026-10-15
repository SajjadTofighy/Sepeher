import { Command } from "lucide-react";
import { fa, labels } from "../../api";
import { Badge } from "../../shared/ui/primitives";
import type { Data, Command as DeviceCommand } from "../../types";
const flow = [
  "detected",
  "confirmed",
  "assigned",
  "en_route",
  "on_scene",
  "closed",
];
export default function CommandTable({
  data,
  retry,
}: {
  data: Data;
  retry: (c: DeviceCommand) => void;
}) {
  return (
    <section className="command-history asset-command-history">
      <header className="asset-command-head"><div><b>تاریخچه فرمان‌ها</b><small>ارسال ← تحویل ← اجرا؛ پایان مهلت به‌صورت بی‌پاسخ ثبت می‌شود.</small></div><em>{fa(data.commands.length)} فرمان</em></header>
      {!data.commands.length ? (
        <div className="empty">
          <Command size={26} />
          <p>هنوز فرمانی ارسال نشده است. یک تجهیز را انتخاب کنید.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>شناسه</th>
                <th>مقصد</th>
                <th>فرمان</th>
                <th>کانال</th>
                <th>متن پیامک</th>
                <th>مهلت نمونه</th>
                <th>وضعیت</th>
                <th>اقدام</th>
              </tr>
            </thead>
            <tbody>
              {[...data.commands].reverse().map((c) => (
                <tr key={c.id}>
                  <td>{c.id}</td>
                  <td>{data.assets.find((a) => a.id === c.asset_id)?.name}</td>
                  <td>{labels[c.command]}</td>
                  <td>{c.channel === "sms" ? "پیامک" : "اینترنت همراه"}</td>
                  <td dir="ltr" className="mono">{c.sms_text ? c.sms_text.replace(/ /g, "␣") : "—"}</td>
                  <td>{fa(c.timeout_seconds)} ثانیه</td>
                  <td>
                    <Badge value={c.status} />
                  </td>
                  <td>
                    {c.status === "timed_out" && (
                      <button className="table-button" onClick={() => retry(c)}>
                        ارسال مجدد
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
