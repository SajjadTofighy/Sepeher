import {
  Download,
  MapPin,
  Pencil,
  Plus,
} from "lucide-react";
import { useState } from "react";
import { api, fa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { download } from "../../shared/lib/download";
import { Badge, Modal, StatStrip } from "../../shared/ui/primitives";
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
      <div className="page-toolbar">
            <button
              className="secondary"
              onClick={() => download("sepehr-zones.geojson", geojson())}
            >
              <Download size={16} />
              خروجی GeoJSON
            </button>
            <button className="primary" onClick={() => edit(null)}>
              <Plus size={16} />
              محدوده جدید
            </button>
      </div>
      <StatStrip items={[
        { label: "محدوده‌های فعال", value: fa(data.zones.length) },
        { label: "حساسیت زیاد", value: fa(data.zones.filter(z => z.risk === "high").length) },
        { label: "پوشش ضعیف", value: fa(data.zones.filter(z => z.coverage === "weak").length) },
        { label: "سیاست‌ها", value: fa(data.policies.length) },
      ]} />
      <div className="geography-layout">
        <ul className="panel zone-list">
          {data.zones.map((z) => (
            <li key={z.id}>
              <div className="zone-name"><b>{z.name}</b><Badge value={z.risk} /></div>
              <small dir="auto">
                {z.id} · {fa(z.points.length)} رأس · {fa(data.policies.filter((p) => p.zone === z.id).length)} سیاست
              </small>
              <button className="text-button" onClick={() => edit(z)}>
                <Pencil size={14} />
                ویرایش
              </button>
            </li>
          ))}
        </ul>
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
