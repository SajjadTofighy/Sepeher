import {
  Download,
  Layers,
  Globe2,
  MapPin,
  Pencil,
  Plus,
  ShieldCheck,
  TriangleAlert,
  WifiOff,
} from "lucide-react";
import { useState } from "react";
import { api, fa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { download } from "../../shared/lib/download";
import { Badge, Modal } from "../../shared/ui/primitives";
import type { Asset, Data, Incident, Zone, ZoneInput } from "../../types";
import OperationalMap from "../command/OperationalMap";
export default function GeographyPage({
  data,
  act,
  busy,
  onAsset,
  onIncident,
  focusTargetId,
  theme,
}: {
  data: Data;
  act: Act;
  busy: boolean;
  onAsset: (a: Asset) => void;
  onIncident: (i: Incident) => void;
  focusTargetId?: string;
  theme: "dark" | "light";
}) {
  const [editing, setEditing] = useState<Zone | null | undefined>(undefined),
    [name, setName] = useState(""),
    [risk, setRisk] = useState("medium"),
    [coverage, setCoverage] = useState<"normal" | "weak">("normal"),
    [points, setPoints] = useState(""),
    [formError, setFormError] = useState("");
  function edit(z: Zone | null) {
    setEditing(z);
    setName(z?.name || "");
    setRisk(z?.risk || "medium");
    setCoverage(z?.coverage || "normal");
    setPoints(
      z
        ? z.points.map((p) => p.join(", ")).join("\n")
        : "49.696, 30.751\n49.708, 30.751\n49.708, 30.762\n49.696, 30.762",
    );
    setFormError("");
  }
  function geojson() {
    return {
      type: "FeatureCollection",
      features: data.zones.map((z) => ({
        type: "Feature",
        properties: {
          id: z.id,
          name: z.name,
          risk: z.risk,
          coverage: z.coverage,
        },
        geometry: {
          type: "Polygon",
          coordinates: [[...z.points, z.points[0]]],
        },
      })),
    };
  }
  async function save() {
    try {
      const coordinates = points
        .trim()
        .split("\n")
        .map((line) => line.split(",").map((v) => Number(v.trim())));
      if (
        coordinates.length < 3 ||
        coordinates.some(
          (p) => p.length !== 2 || p.some((n) => !Number.isFinite(n)),
        )
      )
        throw new Error("هر سطر یک طول و عرض جغرافیایی جداشده با کاما باشد.");
      const payload: ZoneInput = {
        name,
        risk: risk as ZoneInput["risk"],
        points: coordinates,
        coverage,
      };
      const result = await act(
        () =>
          api(
            editing ? `/zones/${editing.id}` : "/zones",
            editing ? "PUT" : "POST",
            payload,
          ),
        "محدوده جغرافیایی ذخیره شد",
      );
      if (result) setEditing(undefined);
    } catch (e) {
      setFormError((e as Error).message);
    }
  }
  return (
    <section className="geography-workspace">
      <header className="geography-hero">
        <div><span className="geography-kicker"><Globe2 size={12}/> GEOSPATIAL COMMAND</span><h1>محدوده‌ها و ناحیه‌ها <i/></h1><p>مدیریت یکپارچه محدوده‌های حفاظت، پوشش ارتباطی و لایه‌های مکانی</p></div>
        <div className="geography-actions">
            <button
              className="geo-action export"
              onClick={() => download("sepehr-zones.geojson", geojson())}
            >
              <Download size={16} />
              خروجی GeoJSON
            </button>
            <button className="geo-action create" onClick={() => edit(null)}>
              <Plus size={16} />
              محدوده جدید
            </button>
        </div>
      </header>
      <div className="geography-kpis">
        <article className="geography-kpi zones"><span><Layers size={20}/></span><div><small>محدوده‌های فعال</small><b>{fa(data.zones.length)}</b><p>ناحیه حفاظتی ثبت‌شده</p></div></article>
        <article className="geography-kpi high"><span><TriangleAlert size={20}/></span><div><small>حساسیت زیاد</small><b>{fa(data.zones.filter(z => z.risk === "high").length)}</b><p>نیازمند پایش مستمر</p></div></article>
        <article className="geography-kpi weak"><span><WifiOff size={20}/></span><div><small>پوشش ضعیف</small><b>{fa(data.zones.filter(z => z.coverage === "weak").length)}</b><p>شکاف ارتباطی شناسایی‌شده</p></div></article>
        <article className="geography-kpi policies"><span><ShieldCheck size={20}/></span><div><small>سیاست‌های مرتبط</small><b>{fa(data.policies.length)}</b><p>قانون حفاظتی فعال</p></div></article>
      </div>
      <section className="geography-console">
        <header className="geography-console-head"><div><span><MapPin size={18}/></span><div><b>نقشه اطلاعات مکانی</b><small>محدوده‌ها، تجهیزات و رخدادهای عملیاتی</small></div></div><em>GIS ONLINE <i className="live-dot"/></em></header>
        <div className="geography-layout">
          <div className="zone-cards">
            {data.zones.map((z) => (
              <article key={z.id} className="zone-card">
                <div>
                  <span className="entity-icon">
                    <Layers size={21} />
                  </span>
                  <Badge value={z.risk} />
                </div>
                <h3>{z.name}</h3>
                <p>
                  {z.id} · {fa(z.points.length)} رأس ·{" "}
                  {fa(data.policies.filter((p) => p.zone === z.id).length)}{" "}
                  سیاست مرتبط
                </p>
                <button className="secondary full" onClick={() => edit(z)}>
                  <Pencil size={14} />
                  ویرایش محدوده
                </button>
              </article>
            ))}
          </div>
          <div className="map-card">
            <OperationalMap
              focusTargetId={focusTargetId}
              data={data}
              theme={theme}
              onAsset={onAsset}
              onIncident={onIncident}
            />
          </div>
        </div>
      </section>
      <div className="geography-note">
        <ShieldCheck size={22} />
        <p>
          نقشهٔ پایه واقعی است؛ محدوده‌های اولیه دادهٔ نمونه هستند. برای
          واردکردن GeoJSON و اندازه‌گیری، ابزارهای GIS نقشه را باز کنید. اتصال
          WMS/WFS از «مدیریت سامانه ← اتصال GIS» تنظیم می‌شود.
        </p>
      </div>
      {editing !== undefined && (
        <Modal
          title={editing ? "ویرایش محدوده" : "تعریف محدوده حفاظت"}
          onClose={() => setEditing(undefined)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <label className="field">
              نام محدوده
              <input
                required
                minLength={3}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="field">
              سطح حساسیت
              <select value={risk} onChange={(e) => setRisk(e.target.value)}>
                <option value="high">زیاد</option>
                <option value="medium">متوسط</option>
                <option value="low">کم</option>
              </select>
            </label>
            <label className="field">
              پوشش ارتباطی
              <select
                value={coverage}
                onChange={(e) =>
                  setCoverage(e.target.value as "normal" | "weak")
                }
              >
                <option value="normal">عادی</option>
                <option value="weak">ضعیف</option>
              </select>
            </label>
            <label className="field">
              رؤوس چندضلعی (هر سطر: طول، عرض)
              <textarea
                className="coordinates-input"
                dir="ltr"
                rows={7}
                required
                value={points}
                onChange={(e) => setPoints(e.target.value)}
              />
            </label>
            <p className="info-box">
              حداقل سه نقطه متفاوت وارد کنید. برای نمونه از مختصات ازپیش‌پرشده
              استفاده کنید. آخرین رأس به رأس اول متصل می‌شود.
            </p>
            {formError && <p className="error-banner">{formError}</p>}
            <button className="primary full" type="submit" disabled={busy}>
              <MapPin size={16} />
              ذخیره و نمایش روی نقشه
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}
