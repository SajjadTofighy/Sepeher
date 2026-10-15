import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Camera, CheckCheck, LogIn, LogOut, Mic, Send, ShieldAlert, Smartphone, Square, Trash2, Upload, Video } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, fa, labels, setSession, timeFa } from "../../api";
import { completeLogin, login, logout, refresh, type Tokens } from "../../shared/auth/oidc";
import type {
  AuthConfiguration, CapturePolicy, EnrolledDevice, FieldMessage, FieldReport, Principal, ReportCategory, TourRecord,
} from "../../types";
import { pickMimeType, recordMedia, takePhoto } from "./capture";
import { uploadMedia } from "./upload";

const FIELD_CLIENT = "sepehr-field";
// Only the non-secret device identifier is remembered; the server binds it to the token's subject.
const DEVICE_KEY = "sepehr-field-device-id";
// Pilot evidence: token refreshes since the last capability report, in memory only.
const refreshCounters = { ok: 0, failed: 0 };
const REPORT_INTERVAL_MS = 30 * 60 * 1000;
const CATEGORIES: ReportCategory[] = ["security", "safety_hse", "operations", "damage", "uxo", "drone_sighting", "other"];
const RESTRICTED: ReportCategory[] = ["damage", "uxo", "drone_sighting"];
type Capture = { id: string; blob: Blob; kind: "image" | "audio" | "video"; caption: string; progress?: number; error?: string };

const readDevice = () => {
  try { return localStorage.getItem(DEVICE_KEY) || ""; } catch { return ""; }
};

export default function FieldApp() {
  const client = useQueryClient();
  const [tokens, setTokens] = useState<Tokens | null>(null);
  const [deviceId, setDeviceId] = useState(readDevice);
  const [error, setError] = useState("");
  const config = useQuery({ queryKey: ["field-app", "config"], queryFn: () => api<AuthConfiguration>("/auth/config") });
  useEffect(() => {
    completeLogin().then((result) => result && setTokens(result.tokens)).catch((e) => setError((e as Error).message));
  }, []);
  useEffect(() => {
    setSession(tokens?.access_token, deviceId || undefined);
    if (tokens) client.invalidateQueries({ queryKey: ["field-app"] });
    return () => setSession();
  }, [tokens, deviceId, client]);
  useEffect(() => {
    if (!tokens?.refresh_token || !config.data?.issuer) return;
    const timer = setTimeout(() => {
      refresh(config.data!.issuer, FIELD_CLIENT, tokens.refresh_token!)
        .then((next) => { refreshCounters.ok += 1; setTokens(next); })
        .catch((e) => { refreshCounters.failed += 1; setTokens(null); setError((e as Error).message); });
    }, Math.max(15, (tokens.expires_in || 300) - 30) * 1000);
    return () => clearTimeout(timer);
  }, [tokens, config.data]);
  const principal = useQuery({ queryKey: ["field-app", "me", tokens?.access_token], queryFn: () => api<Principal>("/auth/me"), enabled: !!tokens });
  if (config.data?.mode === "demo" && !tokens)
    return <Notice title="اپ میدانی نگهبان" text="حالت نمایشی نقش نگهبان ندارد. اپ میدانی فقط با ورود کیکلاک از کلاینت sepehr-field و دستگاه ثبت‌شده کار می‌کند. API و قرارداد این فاز در حالت کیکلاک قابل استفاده است." />;
  if (!tokens)
    return (
      <Notice title="ورود نگهبان" text={error || "ورود با حساب سازمانی کیکلاک؛ توکن فقط در حافظه همین صفحه می‌ماند."}>
        <button className="primary field-touch" disabled={!config.data?.issuer} onClick={() => login(config.data!.issuer, FIELD_CLIENT, "#field").catch((e) => setError((e as Error).message))}>
          <LogIn size={20} />ورود با کیکلاک
        </button>
      </Notice>
    );
  if (principal.data && !principal.data.roles.includes("guard"))
    return <Notice title="اپ میدانی نگهبان" text="این حساب نقش نگهبان ندارد؛ برای نظارت از صفحه «پیام، رسانه و گزارش میدانی» استفاده کنید." />;
  if (!deviceId) return <Enroll onEnrolled={(id) => { try { localStorage.setItem(DEVICE_KEY, id); } catch {} setDeviceId(id); }} />;
  return (
    <FieldWorkspace
      deviceId={deviceId}
      username={principal.data?.username || ""}
      onLogout={() => { setSession(); const id = tokens.id_token; setTokens(null); if (config.data?.issuer) logout(config.data.issuer, FIELD_CLIENT, id); }}
      onDeviceRejected={() => { try { localStorage.removeItem(DEVICE_KEY); } catch {} setDeviceId(""); }}
    />
  );
}

function Notice({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return <section className="field-app"><div className="panel field-notice"><Smartphone size={34} /><h2>{title}</h2><p>{text}</p>{children}</div></section>;
}

function Enroll({ onEnrolled }: { onEnrolled: (id: string) => void }) {
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("گوشی سازمانی");
  const [error, setError] = useState("");
  return (
    <section className="field-app">
      <form className="panel field-notice" onSubmit={async (e) => {
        e.preventDefault();
        try { onEnrolled((await api<EnrolledDevice>("/devices/enroll", "POST", { code, label })).id); } catch (err) { setError((err as Error).message); }
      }}>
        <Smartphone size={34} /><h2>ثبت یک‌باره دستگاه</h2>
        <p>کد یک‌بارمصرف را از مدیر سامانه بگیرید.</p>
        <label className="field">کد ثبت<input dir="ltr" required value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <label className="field">نام دستگاه<input required value={label} onChange={(e) => setLabel(e.target.value)} /></label>
        {error && <div className="error-banner">{error}</div>}
        <button className="primary field-touch">ثبت دستگاه</button>
      </form>
    </section>
  );
}

function useUrgentAlarm(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const ring = () => {
      navigator.vibrate?.([400, 200, 400]);
      try {
        const audio = new AudioContext();
        const tone = audio.createOscillator();
        tone.frequency.value = 880;
        tone.connect(audio.destination);
        tone.start();
        tone.stop(audio.currentTime + 0.6);
        tone.onended = () => audio.close();
      } catch {}
    };
    ring();
    const timer = setInterval(ring, 5000);
    return () => clearInterval(timer);
  }, [active]);
}

async function reportCapabilities(deviceId: string) {
  type Battery = { level: number; charging: boolean };
  const battery = await ((navigator as Navigator & { getBattery?: () => Promise<Battery> }).getBattery?.().catch(() => undefined));
  const counts = { ...refreshCounters };
  await api(`/devices/${deviceId}/capabilities`, "POST", {
    barcode_detector: "BarcodeDetector" in window,
    web_nfc: "NDEFReader" in window,
    wake_lock: "wakeLock" in navigator,
    device_motion: "DeviceMotionEvent" in window,
    battery_level: battery ? battery.level : null,
    charging: battery ? battery.charging : null,
    auth_refresh_ok: counts.ok,
    auth_refresh_failed: counts.failed,
    platform: (navigator.platform || "").slice(0, 60),
  });
  refreshCounters.ok -= counts.ok;
  refreshCounters.failed -= counts.failed;
}

function FieldWorkspace({ deviceId, username, onLogout, onDeviceRejected }: { deviceId: string; username: string; onLogout: () => void; onDeviceRejected: () => void }) {
  const client = useQueryClient();
  useEffect(() => {
    // Pilot measurement only: feature availability, battery and token refresh; never location.
    const send = () => reportCapabilities(deviceId).catch(() => undefined);
    send();
    const timer = setInterval(send, REPORT_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [deviceId]);
  const [notice, setNotice] = useState("");
  const tours = useQuery({ queryKey: ["field-app", "tours"], queryFn: () => api<TourRecord[]>("/tour"), refetchInterval: 15000 });
  const tour = (tours.data || []).find((t) => t.status === "active");
  const messages = useQuery({ queryKey: ["field-app", "messages"], queryFn: () => api<FieldMessage[]>("/messages"), refetchInterval: 5000 });
  const policy = useQuery({ queryKey: ["field-app", "policy", tour?.id], queryFn: () => api<CapturePolicy>(`/media/capture-policy?tour_id=${tour!.id}`), enabled: !!tour });
  useEffect(() => {
    const code = (tours.error as { code?: string } | null)?.code;
    if (code === "device_revoked" || code === "device_required" || code === "device_owner_mismatch") onDeviceRejected();
  }, [tours.error, onDeviceRejected]);
  const pendingUrgent = (messages.data || []).filter((m) => m.priority === "urgent" && m.recipients.some((r) => !r.acknowledged_at));
  useUrgentAlarm(pendingUrgent.length > 0);
  const ack = async (id: string) => {
    try { await api(`/messages/${id}/ack`, "POST"); client.invalidateQueries({ queryKey: ["field-app", "messages"] }); } catch (e) { setNotice((e as Error).message); }
  };
  return (
    <section className="field-app">
      <header className="panel field-header">
        <div><b>{username}</b><small>{tour ? `گشت فعال ${tour.id.slice(0, 12)}` : "گشت فعالی ندارید"}</small></div>
        <button className="secondary field-touch" onClick={onLogout}><LogOut size={18} />خروج</button>
      </header>
      {pendingUrgent.map((m) => (
        <div key={m.id} className="urgent-banner" role="alert">
          <BellRing size={22} /><p>{m.text}<small>{timeFa(m.created_at)}</small></p>
          <button className="primary field-touch" onClick={() => ack(m.id)}><CheckCheck size={18} />دریافت شد</button>
        </div>
      ))}
      {notice && <div className="error-banner">{notice}</div>}
      {tour ? (
        <>
          <ReportForm tour={tour} policy={policy.data} onDone={setNotice} />
          <MessageCenter tour={tour} rows={messages.data || []} onAck={ack} />
        </>
      ) : <div className="panel field-notice"><p>برای گزارش و رسانه، ابتدا دور گشت را از صف شروع کنید.</p></div>}
    </section>
  );
}

function ReportForm({ tour, policy, onDone }: { tour: TourRecord; policy?: CapturePolicy; onDone: (message: string) => void }) {
  const [category, setCategory] = useState<ReportCategory>("security");
  const [text, setText] = useState("");
  const [safety, setSafety] = useState(false);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [busy, setBusy] = useState(false);
  const draft = useRef(crypto.randomUUID());
  const restricted = RESTRICTED.includes(category);
  const update = useCallback((id: string, change: Partial<Capture>) => setCaptures((list) => list.map((c) => (c.id === id ? { ...c, ...change } : c))), []);
  const submit = async () => {
    setBusy(true);
    try {
      const report = await api<FieldReport>("/tour/reports", "POST", { tour_id: tour.id, category, text, client_id: draft.current, safety_acknowledged: safety });
      for (const capture of captures) {
        try {
          const result = await uploadMedia(capture.blob, { tour_id: tour.id, caption: capture.caption, media_type: capture.kind, report_id: report.id, client_id: capture.id },
            (received, total) => update(capture.id, { progress: Math.round((received / total) * 100) }));
          // Restricted evidence and every uploaded copy leave the device after server custody.
          if (result.purge_local_copy || result.media.status === "stored") setCaptures((list) => list.filter((c) => c.id !== capture.id));
        } catch (e) {
          update(capture.id, { error: (e as Error).message });
          throw e;
        }
      }
      onDone(`گزارش ${labels[category]} ثبت شد؛ مخاطب: ${report.audiences.map((a) => labels[a]).join("، ")}`);
      setText(""); setSafety(false); draft.current = crypto.randomUUID();
    } catch (e) {
      onDone((e as Error).message + " — با همان پیش‌نویس دوباره ارسال کنید؛ ادامه از آخرین قطعه دریافت‌شده است.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="panel field-report" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <h3><ShieldAlert size={18} />گزارش میدانی</h3>
      <div className="category-grid">
        {CATEGORIES.map((c) => (
          <button type="button" key={c} className={category === c ? "current field-touch" : "field-touch"} onClick={() => { setCategory(c); setSafety(false); }}>{labels[c]}</button>
        ))}
      </div>
      {restricted && (
        <label className="safety-instruction check-row field-touch">
          <input type="checkbox" checked={safety} onChange={(e) => setSafety(e.target.checked)} />
          نزدیک نشو، از فاصله امن گزارش کن. تصویر این دسته پس از ارسال از گوشی حذف می‌شود.
        </label>
      )}
      <label className="field">شرح کوتاه<textarea required minLength={3} maxLength={4000} rows={3} value={text} onChange={(e) => setText(e.target.value)} /></label>
      <CapturePanel policy={policy} onCapture={(blob, kind) => setCaptures((list) => [...list, { id: crypto.randomUUID(), blob, kind, caption: `${labels[kind]} گزارش ${labels[category]}` }])} />
      {captures.map((c) => (
        <div key={c.id} className="capture-row">
          <span>{labels[c.kind]} · {fa(Math.round(c.blob.size / 1024))} KB</span>
          {c.progress !== undefined && <progress max={100} value={c.progress} />}
          {c.error && <small className="flag">{c.error}</small>}
          <button type="button" className="icon-button" aria-label="حذف" disabled={busy} onClick={() => setCaptures((list) => list.filter((x) => x.id !== c.id))}><Trash2 size={18} /></button>
        </div>
      ))}
      <button className="primary full field-touch" disabled={busy || text.trim().length < 3 || (restricted && !safety)}><Upload size={18} />ارسال گزارش</button>
    </form>
  );
}

function CapturePanel({ policy, onCapture }: { policy?: CapturePolicy; onCapture: (blob: Blob, kind: "image" | "audio" | "video") => void }) {
  const preview = useRef<HTMLVideoElement>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [mode, setMode] = useState<"image" | "audio" | "video" | null>(null);
  const [recorder, setRecorder] = useState<{ stop: () => void } | null>(null);
  const [error, setError] = useState("");
  const stopStream = useCallback(() => { stream?.getTracks().forEach((t) => t.stop()); setStream(null); setMode(null); }, [stream]);
  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream]);
  useEffect(() => { if (preview.current && stream) preview.current.srcObject = stream; }, [stream, mode]);
  if (!policy) return null;
  const open = async (kind: "image" | "audio" | "video") => {
    setError("");
    try {
      const media = await navigator.mediaDevices.getUserMedia(kind === "audio" ? { audio: true } : { video: { facingMode: "environment" }, audio: kind === "video" });
      setStream(media); setMode(kind);
    } catch {
      setError("دسترسی به دوربین یا میکروفون داده نشد");
    }
  };
  const record = (kind: "audio" | "video") => {
    const mime = pickMimeType(kind);
    if (!stream || !mime) { setError("مرورگر قالب مجاز ضبط را پشتیبانی نمی‌کند"); return; }
    const seconds = kind === "audio" ? policy.audio_max_seconds : policy.video_max_seconds;
    const bits = (kind === "audio" ? policy.audio_bitrate_kbps : policy.video_bitrate_kbps) * 1000;
    setRecorder(recordMedia(stream, mime, kind, bits, seconds, (blob) => { setRecorder(null); onCapture(blob, kind); stopStream(); }));
  };
  return (
    <div className="capture-panel">
      <div className="capture-actions">
        <button type="button" className="secondary field-touch" disabled={!policy.image_video_allowed || !!mode} onClick={() => open("image")}><Camera size={18} />عکس</button>
        <button type="button" className="secondary field-touch" disabled={!policy.image_video_allowed || !!mode} onClick={() => open("video")}><Video size={18} />ویدئو</button>
        <button type="button" className="secondary field-touch" disabled={!!mode} onClick={() => open("audio")}><Mic size={18} />صوت</button>
      </div>
      {!policy.image_video_allowed && <small className="muted">در این محوطه یا ایستگاه فقط متن و صوت مجاز است.</small>}
      {error && <small className="flag">{error}</small>}
      {mode && (
        <div className="capture-stage">
          {mode !== "audio" && <video ref={preview} autoPlay muted playsInline />}
          {mode === "image" && <button type="button" className="primary field-touch" onClick={async () => { onCapture(await takePhoto(preview.current!), "image"); stopStream(); }}><Camera size={18} />گرفتن عکس</button>}
          {mode !== "image" && !recorder && <button type="button" className="primary field-touch" onClick={() => record(mode)}>شروع ضبط (حداکثر {fa(mode === "audio" ? policy.audio_max_seconds : policy.video_max_seconds)} ثانیه)</button>}
          {recorder && <button type="button" className="danger-button field-touch" onClick={() => recorder.stop()}><Square size={18} />پایان ضبط</button>}
          {!recorder && <button type="button" className="secondary field-touch" onClick={stopStream}>انصراف</button>}
        </div>
      )}
    </div>
  );
}

function MessageCenter({ tour, rows, onAck }: { tour: TourRecord; rows: FieldMessage[]; onAck: (id: string) => void }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="panel field-messages">
      <h3><Send size={18} />پیام با مرکز</h3>
      <form onSubmit={async (e) => {
        e.preventDefault();
        try { await api("/messages", "POST", { tour_id: tour.id, text }); setText(""); client.invalidateQueries({ queryKey: ["field-app", "messages"] }); } catch (err) { setError((err as Error).message); }
      }}>
        <textarea required maxLength={2000} rows={2} value={text} onChange={(e) => setText(e.target.value)} />
        <button className="primary field-touch" disabled={!text.trim()}><Send size={18} />ارسال</button>
      </form>
      {error && <small className="flag">{error}</small>}
      <ul>{[...rows].reverse().slice(0, 20).map((m) => {
        const mine = m.recipients[0];
        return (
          <li key={m.id} className={m.direction === "to_center" ? "outgoing" : "incoming"}>
            <p>{m.text}</p>
            <small>{timeFa(m.created_at)} · {labels[m.direction]} {m.priority === "urgent" ? "· فوری" : ""}
              {m.direction === "to_center" ? (m.center_ack_at ? " · مرکز دریافت کرد" : " · ارسال‌شده") : ""}</small>
            {mine && !mine.acknowledged_at && <button className="table-button field-touch" onClick={() => onAck(m.id)}>دریافت شد</button>}
          </li>
        );
      })}</ul>
    </div>
  );
}
