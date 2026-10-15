import { fa } from "../../api";
import { StatStrip } from "../../shared/ui/primitives";
import type { Data } from "../../types";
export default function Stats({ data }: { data: Data }) {
  const s = data.summary;
  return (
    <StatStrip
      items={[
        {
          label: "تجهیزات برخط",
          value: <>{fa(s.online)} <small>/ {fa(s.total)}</small></>,
          note: s.offline + s.warning ? `${fa(s.offline)} قطع · ${fa(s.warning)} نیازمند بررسی` : "همه در وضعیت عادی",
          tone: s.offline ? "warn" : undefined,
        },
        { label: "مأموریت‌های فعال", value: fa(s.missions) },
        {
          label: "حوادث بحرانی باز",
          value: fa(s.critical),
          note: s.hot_zone ? `کانون: ${s.hot_zone}` : undefined,
          tone: s.critical ? "danger" : undefined,
        },
        {
          label: "پوشش گشت",
          value: `${fa(s.coverage)}٪`,
          note: `${fa(s.policy_alerts)} هشدار سیاست · ${fa(s.open_incidents)} پرونده باز`,
        },
      ]}
    />
  );
}
