import { Check, Pencil } from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import type { Act } from "../../shared/lib/actions";
import type { Asset, AssetSettings } from "../../types";
export default function AssetSettingsForm({
  asset,
  act,
  busy,
}: {
  asset: Asset;
  act: Act;
  busy: boolean;
}) {
  const [p, setP] = useState<AssetSettings>({
    carrier: asset.carrier as AssetSettings["carrier"],
    sim: asset.sim,
    report_interval: asset.report_interval || 30,
    data_package: (asset.data_package ||
      "active") as AssetSettings["data_package"],
  });
  return (
    <details className="asset-settings">
      <summary>
        <Pencil size={15} />
        ویرایش مشخصات تجهیز و سیم‌کارت
      </summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          act(
            () => api(`/assets/${asset.id}/settings`, "PATCH", p),
            "مشخصات تجهیز ذخیره شد",
          );
        }}
      >
        <label className="field">
          شماره یا شناسه سیم‌کارت
          <input
            minLength={4}
            maxLength={30}
            required
            dir="ltr"
            value={p.sim}
            onChange={(e) => setP({ ...p, sim: e.target.value })}
          />
        </label>
        <div className="form-grid">
          <label className="field">
            اپراتور
            <select
              value={p.carrier}
              onChange={(e) =>
                setP({
                  ...p,
                  carrier: e.target.value as AssetSettings["carrier"],
                })
              }
            >
              <option>همراه اول</option>
              <option>ایرانسل</option>
            </select>
          </label>
          <label className="field">
            وضعیت بسته
            <select
              value={p.data_package}
              onChange={(e) =>
                setP({
                  ...p,
                  data_package: e.target.value as AssetSettings["data_package"],
                })
              }
            >
              <option value="active">فعال</option>
              <option value="expiring">نیازمند تمدید</option>
              <option value="expired">منقضی</option>
            </select>
          </label>
        </div>
        <label className="field">
          فاصله گزارش‌دهی (ثانیه)
          <input
            type="number"
            min={5}
            max={3600}
            required
            value={p.report_interval}
            onChange={(e) => setP({ ...p, report_interval: +e.target.value })}
          />
        </label>
        <button className="secondary full" type="submit" disabled={busy}>
          <Check size={15} />
          ذخیره مشخصات نمونه
        </button>
      </form>
    </details>
  );
}
