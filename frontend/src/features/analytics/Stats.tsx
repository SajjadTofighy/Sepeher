import { RadioTower, Route, Target, TriangleAlert } from "lucide-react";
import { fa } from "../../api";
import type { Data } from "../../types";
export default function Stats({ data }: { data: Data }) {
  return (
    <div className="stats">
      {[
        {
          title: "تجهیزات برخط",
          value: `${fa(data.summary.online)}`,
          total: `/ ${fa(data.summary.total)}`,
          icon: RadioTower,
          meta: data.summary.offline + data.summary.warning
            ? `${fa(data.summary.offline)} قطع · ${fa(data.summary.warning)} نیازمند بررسی`
            : "همه تجهیزات در وضعیت عادی",
          color: "teal",
        },
        {
          title: "مأموریت‌های فعال",
          value: fa(data.summary.missions),
          icon: Route,
          meta: "پوشش سه ناحیه عملیاتی",
          color: "blue",
        },
        {
          title: "حوادث بحرانی باز",
          value: fa(data.summary.critical),
          icon: TriangleAlert,
          meta: data.summary.hot_zone
            ? `کانون: ${data.summary.hot_zone}`
            : "پرونده بحرانی بازی نیست",
          color: "orange",
        },
        {
          title: "پوشش گشت",
          value: fa(data.summary.coverage) + "٪",
          icon: Target,
          meta: `${fa(data.summary.policy_alerts)} هشدار سیاست · ${fa(data.summary.open_incidents)} پرونده باز`,
          color: "teal",
        },
      ].map((s, i) => (
        <div key={i} className={`stat ${s.color}`}>
          <div className="stat-top">
            <span>{s.title}</span>
            <s.icon size={19} />
          </div>
          <div className="stat-value">
            {s.value}
            <small>{s.total}</small>
            <svg viewBox="0 0 100 30">
              <path
                d={
                  i === 2
                    ? "M0 22 15 22 25 12 42 14 50 5 70 8 80 4 100 4"
                    : "M0 24 10 20 23 24 32 12 45 16 59 10 65 14 78 4 90 8 100 2"
                }
              />
            </svg>
          </div>
          <small>{s.meta}</small>
        </div>
      ))}
    </div>
  );
}
