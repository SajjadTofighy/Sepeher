import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, BellRing, FileWarning, Gavel, ImageDown, MessageSquare, Paperclip, Send, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api, fa, labels, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge, Modal, PanelTitle } from "../../shared/ui/primitives";
import type {
  AuthConfiguration, Data, FieldMedia, FieldMessage, FieldReport, FieldZone, GuardRecord, ReportAudience, ReportCategory,
} from "../../types";
import { fetchMediaBlob } from "./upload";
import { watermarkedImage, watermarkLines } from "./watermark";

const CATEGORIES: ReportCategory[] = ["security", "safety_hse", "operations", "damage", "uxo", "drone_sighting", "other"];
const AUDIENCES: ReportAudience[] = ["security", "hse", "operations"];
type Tab = "messages" | "reports" | "media";

export default function FieldCommsPage({ data, act, busy }: { data: Data; act: Act; busy: boolean }) {
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("messages");
  const refresh = () => client.invalidateQueries({ queryKey: ["field-comms"] });
  const run: Act = async (fn, message) => {
    const result = await act(fn, message);
    await refresh();
    return result;
  };
  const config = useQuery({ queryKey: ["field-comms", "config"], queryFn: () => api<AuthConfiguration>("/auth/config") });
  const messages = useQuery({ queryKey: ["field-comms", "messages"], queryFn: () => api<FieldMessage[]>("/messages"), refetchInterval: 5000 });
  const reports = useQuery({ queryKey: ["field-comms", "reports"], queryFn: () => api<FieldReport[]>("/tour/reports"), refetchInterval: 10000 });
  const media = useQuery({ queryKey: ["field-comms", "media"], queryFn: () => api<FieldMedia[]>("/media"), enabled: tab === "media" });
  const escalated = (messages.data || []).filter((m) => m.escalation !== "operator").length;
  const unacked = (reports.data || []).filter((r) => r.acknowledgements.length < r.audiences.length).length;
  const classification = config.data?.classification_label || "";
  return (
    <section className="field-comms">
      <PanelTitle title="ارتباط میدانی و زنجیره حفاظت ادله" sub="ارتباط مرکز با نگهبانان، گزارش‌های دسته‌بندی‌شده و زنجیره حفاظت ادله؛ هیچ اقدامی خودکار انجام نمی‌شود">
        {classification && <span className="classification-chip">{classification}</span>}
      </PanelTitle>
      <div className="comms-tabs" role="tablist">
        {([["messages", "پیام‌ها", MessageSquare, escalated], ["reports", "گزارش‌های میدانی", FileWarning, unacked], ["media", "رسانه و ادله", Archive, 0]] as const).map(([id, name, Icon, count]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "current" : ""} onClick={() => setTab(id)}>
            <Icon size={16} />{name}{count > 0 && <em>{fa(count)}</em>}
          </button>
        ))}
      </div>
      {tab === "messages" && <Messages rows={messages.data || []} run={run} busy={busy} loading={messages.isPending} />}
      {tab === "reports" && <Reports rows={reports.data || []} run={run} busy={busy} loading={reports.isPending} />}
      {tab === "media" && <MediaList rows={media.data || []} data={data} run={run} busy={busy} classification={classification} loading={media.isPending} />}
    </section>
  );
}

function Messages({ rows, run, busy, loading }: { rows: FieldMessage[]; run: Act; busy: boolean; loading: boolean }) {
  const guards = useQuery({ queryKey: ["field-comms", "guards"], queryFn: () => api<GuardRecord[]>("/guards") });
  const zones = useQuery({ queryKey: ["field-comms", "zones"], queryFn: () => api<FieldZone[]>("/tour/zones") });
  const [mode, setMode] = useState<"guard" | "zone">("guard");
  const [target, setTarget] = useState("");
  const [contractor, setContractor] = useState("");
  const [text, setText] = useState("");
  const [urgent, setUrgent] = useState(false);
  const linked = (guards.data || []).filter((g) => g.keycloak_sub);
  const send = async () => {
    const audience = mode === "guard" ? { guard_id: target } : { broadcast_zone: target, contractor_id: contractor || null };
    const r = await run(() => api("/messages", "POST", { text, priority: urgent ? "urgent" : "normal", audience }), "پیام ثبت شد");
    if (r) setText("");
  };
  return (
    <div className="comms-grid">
      <form className="panel comms-compose" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <h3><Send size={16} /> ارسال پیام مرکز</h3>
        <div className="segmented">
          <button type="button" className={mode === "guard" ? "current" : ""} onClick={() => { setMode("guard"); setTarget(""); }}>یک نگهبان</button>
          <button type="button" className={mode === "zone" ? "current" : ""} onClick={() => { setMode("zone"); setTarget(""); }}>اعلان همگانی محوطه</button>
        </div>
        <label className="field">مخاطب
          <select required value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">انتخاب کنید</option>
            {mode === "guard"
              ? linked.map((g) => <option key={g.id} value={g.id}>{g.name} · {g.zone_id}</option>)
              : (zones.data || []).map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
          </select>
        </label>
        {mode === "zone" && (
          <label className="field">پیمانکار (برای نقش چندپیمانکاره)
            <input dir="ltr" value={contractor} onChange={(e) => setContractor(e.target.value)} placeholder="از هویت شما" />
          </label>
        )}
        <label className="field">متن پیام
          <textarea required maxLength={2000} rows={4} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <label className="check-row"><input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} />
          فوری: نگهبان باید «دریافت شد» را صریح بزند؛ بی‌پاسخ ماندن تشدید می‌شود</label>
        <button className="primary full" disabled={busy || !target || !text.trim()}>ثبت و ارسال</button>
        {mode === "guard" && !linked.length && <p className="muted">هیچ نگهبان پیوندخورده‌ای در حوزه شما نیست.</p>}
      </form>
      <div className="panel comms-list">
        {loading ? <div className="empty">در حال دریافت پیام‌ها…</div> : !rows.length ? <div className="empty"><MessageSquare size={24} /><p>پیامی ثبت نشده است</p></div> : (
          <div className="table-wrap"><table>
            <thead><tr><th>زمان</th><th>جهت</th><th>اولویت</th><th>متن</th><th>رسید</th><th>تشدید</th><th /></tr></thead>
            <tbody>{[...rows].reverse().map((m) => {
              const acked = m.recipients.filter((r) => r.acknowledged_at).length;
              return (
                <tr key={m.id} className={m.escalation !== "operator" ? "row-escalated" : ""}>
                  <td>{timeFa(m.created_at)}</td>
                  <td>{labels[m.direction]}<small>{m.guard_id || m.zone_id}</small></td>
                  <td><Badge value={m.priority === "urgent" ? "critical" : "info"} /> {labels[m.priority]}</td>
                  <td className="message-text">{m.text}</td>
                  <td>{m.direction === "to_center" ? (m.center_ack_at ? `مرکز ${timeFa(m.center_ack_at)}` : "در انتظار") : `${fa(acked)} از ${fa(m.recipients.length)}`}
                    {m.recipients.length > 1 && <details><summary>گیرندگان</summary>{m.recipients.map((r) => <div key={r.guard_id}>{r.guard_id}: {r.acknowledged_at ? timeFa(r.acknowledged_at) : "بی‌پاسخ"}</div>)}</details>}
                  </td>
                  <td>{m.escalation === "operator" ? "—" : <span className="escalation"><BellRing size={13} />{labels[m.escalation]}</span>}</td>
                  <td>{m.direction === "to_center" && !m.center_ack_at && (
                    <button className="table-button" disabled={busy} onClick={() => run(() => api(`/messages/${m.id}/ack`, "POST"), "رسید مرکز ثبت شد")}>دریافت شد</button>
                  )}</td>
                </tr>
              );
            })}</tbody>
          </table></div>
        )}
      </div>
    </div>
  );
}

function Reports({ rows, run, busy, loading }: { rows: FieldReport[]; run: Act; busy: boolean; loading: boolean }) {
  const [category, setCategory] = useState("");
  const [audience, setAudience] = useState("");
  const shown = rows.filter((r) => (!category || r.category === category) && (!audience || r.audiences.includes(audience as ReportAudience)));
  return (
    <div className="panel comms-list">
      <div className="comms-filters">
        <label className="field">دسته<select value={category} onChange={(e) => setCategory(e.target.value)}><option value="">همه</option>{CATEGORIES.map((c) => <option key={c} value={c}>{labels[c]}</option>)}</select></label>
        <label className="field">واحد مخاطب<select value={audience} onChange={(e) => setAudience(e.target.value)}><option value="">همه</option>{AUDIENCES.map((a) => <option key={a} value={a}>{labels[a]}</option>)}</select></label>
        <p className="muted">مسیریابی فقط تعیین مخاطب داخلی است؛ ارسال به واحد HSE یا بهره‌برداری با رسید انسانی ثبت می‌شود.</p>
      </div>
      {loading ? <div className="empty">در حال دریافت گزارش‌ها…</div> : !shown.length ? <div className="empty"><FileWarning size={24} /><p>گزارشی یافت نشد</p></div> : (
        <div className="report-cards">{[...shown].reverse().map((r) => (
          <article key={r.id} className={r.restricted ? "report-card restricted" : "report-card"}>
            <header><b>{labels[r.category]}</b><small>{r.id} · {r.guard_id} · {timeFa(r.created_at)}</small>
              {r.restricted && <span className="restricted-tag"><ShieldAlert size={13} />محدود: رسانه فقط مدیر حراست</span>}</header>
            {r.safety_instruction && <p className="safety-instruction">{r.safety_instruction}</p>}
            <p>{r.text}</p>
            <footer>
              {(r.offline_too_long || r.clock_regressed) && <span className="flag">{r.offline_too_long ? "آفلاین طولانی" : ""} {r.clock_regressed ? "پسروی ساعت" : ""}</span>}
              <span>{fa(r.media_ids.length)} رسانه</span>
              {r.audiences.map((a) => {
                const ack = r.acknowledgements.find((x) => x.audience === a);
                return ack ? <span key={a} className="ack-done">{labels[a]} ✓ {timeFa(ack.at)}</span> : (
                  <button key={a} className="table-button" disabled={busy} onClick={() => run(() => api(`/tour/reports/${r.id}/ack`, "POST", { audience: a }), `رسید ${labels[a]} ثبت شد`)}>رسید {labels[a]}</button>
                );
              })}
            </footer>
          </article>
        ))}</div>
      )}
    </div>
  );
}

function MediaList({ rows, data, run, busy, classification, loading }: { rows: FieldMedia[]; data: Data; run: Act; busy: boolean; classification: string; loading: boolean }) {
  const [open, setOpen] = useState<FieldMedia | null>(null);
  return (
    <div className="panel comms-list">
      {loading ? <div className="empty">در حال دریافت رسانه‌ها…</div> : !rows.length ? <div className="empty"><Archive size={24} /><p>رسانه‌ای در حوزه شما ثبت نشده است</p></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th>شناسه</th><th>نوع</th><th>دسته</th><th>نگهبان / ایستگاه</th><th>دریافت سرور</th><th>هش</th><th>نگهداری</th><th>وضعیت</th><th /></tr></thead>
          <tbody>{[...rows].reverse().map((m) => (
            <tr key={m.id}>
              <td>{m.id.slice(0, 14)}</td>
              <td>{labels[m.media_type]}</td>
              <td>{m.category ? labels[m.category] : "گشت"}</td>
              <td>{m.guard_id}<small>{m.station_id || "—"}</small></td>
              <td>{m.server_received_at ? timeFa(m.server_received_at) : "—"}</td>
              <td dir="ltr" className="hash">{m.sha256 ? m.sha256.slice(0, 12) + "…" : "—"}</td>
              <td>{m.legal_hold ? <span className="ack-done"><Gavel size={13} />قانونی</span> : m.retention_until ? new Date(m.retention_until).toLocaleDateString("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran" }) : "—"}</td>
              <td><Badge value={m.status} /></td>
              <td>{m.status === "stored" && <button className="table-button" onClick={() => setOpen(m)}>مشاهده</button>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {open && <MediaViewer media={open} data={data} run={run} busy={busy} classification={classification} onClose={() => setOpen(null)} />}
    </div>
  );
}

function MediaViewer({ media, data, run, busy, classification, onClose }: { media: FieldMedia; data: Data; run: Act; busy: boolean; classification: string; onClose: () => void }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [incident, setIncident] = useState(media.incident_id || "");
  const [reason, setReason] = useState("");
  const lines = watermarkLines(media, classification);
  useEffect(() => {
    let created = "";
    (async () => {
      try {
        const blob = await fetchMediaBlob(media);
        created = URL.createObjectURL(media.media_type === "image" ? await watermarkedImage(blob, lines) : blob);
        setUrl(created);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
    return () => { if (created) URL.revokeObjectURL(created); };
  }, [media.id]);
  const exportImage = async () => {
    const ok = await run(() => api("/exports", "POST", { name: "رسانه " + media.id, media_id: media.id }), "خروجی ممیزی‌شده آماده شد");
    if (ok && url) {
      const a = document.createElement("a");
      a.href = url;
      a.download = `${media.id}-watermarked.png`;
      a.click();
    }
  };
  return (
    <Modal title={`رسانه ${labels[media.media_type]} · ${media.id}`} onClose={onClose} wide>
      <div className="media-viewer">
        <div className="media-stage">
          {error ? <div className="error-banner">{error}</div> : !url ? <div className="empty">در حال دریافت محتوای بدون کش…</div>
            : media.media_type === "image" ? <img src={url} alt={media.caption} />
            : media.media_type === "audio" ? <audio src={url} controls controlsList="nodownload" />
            : <video src={url} controls controlsList="nodownload" disablePictureInPicture />}
          {url && media.media_type !== "image" && <div className="watermark-overlay">{lines.map((l) => <span key={l}>{l}</span>)}</div>}
        </div>
        <aside className="detail-section">
          <p>{media.caption}</p>
          <dl className="custody">
            <dt>SHA-256</dt><dd dir="ltr">{media.sha256}</dd>
            <dt>دریافت سرور</dt><dd>{media.watermark?.captured_at_jalali}</dd>
            <dt>ثبت‌کننده / دستگاه</dt><dd dir="ltr">{media.guard_id} / {media.device_id}</dd>
            <dt>حجم</dt><dd>{fa(media.size || 0)} بایت</dd>
          </dl>
          <label className="field">پیوست به پرونده (نگهداری قانونی خودکار)
            <select value={incident} onChange={(e) => setIncident(e.target.value)} disabled={!!media.incident_id}>
              <option value="">انتخاب پرونده</option>
              {data.incidents.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.title}</option>)}
            </select>
          </label>
          {!media.incident_id && <button className="secondary full" disabled={busy || !incident} onClick={() => run(() => api(`/media/${media.id}/attach`, "POST", { incident_id: incident }), "رسانه پیوست پرونده شد").then((r) => r && onClose())}><Paperclip size={15} />پیوست پرونده</button>}
          <label className="field">دلیل تغییر نگهداری قانونی<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <button className="secondary full" disabled={busy || reason.trim().length < 3 || (media.legal_hold && !!media.incident_id)}
            onClick={() => run(() => api(`/media/${media.id}/legal-hold`, "POST", { hold: !media.legal_hold, reason }), "نگهداری قانونی به‌روز شد").then((r) => r && onClose())}>
            <Gavel size={15} />{media.legal_hold ? "رفع نگهداری قانونی" : "اعمال نگهداری قانونی"}
          </button>
          {media.exportable && media.media_type === "image"
            ? <button className="primary full" disabled={busy || !url} onClick={exportImage}><ImageDown size={15} />خروجی نشان‌دار ممیزی‌شده</button>
            : <p className="muted">{media.exportable ? "خروجی صوت و ویدئو ساخته نمی‌شود؛ پخش فقط با نشان‌آب در همین صفحه." : "رسانه خسارت، مهمات و پهپاد غیرقابل خروجی است."}</p>}
        </aside>
      </div>
    </Modal>
  );
}
