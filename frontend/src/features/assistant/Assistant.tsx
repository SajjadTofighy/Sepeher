import {
  ChevronLeft,
  FileText,
  LoaderCircle,
  Send,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import { Modal } from "../../shared/ui/primitives";
import type { AssistantAnswer, Data, Incident } from "../../types";
const flow = [
  "detected",
  "confirmed",
  "assigned",
  "en_route",
  "on_scene",
  "closed",
];
export default function Assistant({
  data,
  close,
  onIncident,
}: {
  data: Data;
  close: () => void;
  onIncident: (i: Incident) => void;
}) {
  const [q, setQ] = useState(""),
    [loading, setLoading] = useState(false),
    [messages, setMessages] = useState<
      { q: string; answer: string; sources: string[] }[]
    >([]),
    [err, setErr] = useState("");
  async function ask(question: string) {
    if (question.trim().length < 2 || loading) return;
    setLoading(true);
    setErr("");
    try {
      const r = await api<AssistantAnswer>("/assistant", "POST", { question });
      setMessages((m) => [...m, { q: question, ...r }]);
      setQ("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <Modal title="دستیار سپهر" onClose={close}>
      <div className="assistant-intro">
        <div className="spark-icon">
          <Sparkles size={28} />
        </div>
        <h3>از وضعیت منطقه بپرسید</h3>
        <p>
          پاسخ از رکوردهای زنده سامانه ساخته می‌شود و به پرونده منبع ارجاع
          می‌دهد؛ دستیار هیچ فرمانی صادر نمی‌کند.
        </p>
        <span className="phase-chip p1">پاسخ قاعده‌محور · بدون مدل زبانی</span>
      </div>
      <div className="suggestions">
        {[
          "الان چه اتفاق مهمی در منطقه افتاده است؟",
          "گزارش شیفت را نشان بده",
          "کدام گشت‌ها خارج از مسیر هستند؟",
          "در ۲۴ ساعت گذشته کدام منطقه بیشترین هشدار را داشته است؟",
          `چرا حادثه ${(data.incidents.find((i) => i.status !== "closed") || data.incidents[0])?.id.slice(4) ?? "۸۲۴"} مهم است؟`,
        ].map((s) => (
          <button key={s} onClick={() => ask(s)} disabled={loading}>
            {s}
            <ChevronLeft size={14} />
          </button>
        ))}
      </div>
      <div className="chat-messages">
        {messages.map((m, j) => (
          <div key={j}>
            <p className="question">{m.q}</p>
            <div className="answer">
              <Sparkles size={17} />
              <p>{m.answer}</p>
              <div>
                {m.sources.map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      const i = data.incidents.find((i) => i.id === s);
                      if (i) onIncident(i);
                    }}
                  >
                    <FileText size={14} />
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
      {err && <p className="error-banner">{err}</p>}
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
        }}
      >
        <input
          aria-label="پرسش از دستیار"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="پرسش خود را بنویسید…"
        />
        <button
          className="primary"
          type="submit"
          aria-label="ارسال پرسش"
          disabled={loading || q.trim().length < 2}
        >
          {loading ? (
            <LoaderCircle size={19} className="spin" />
          ) : (
            <Send size={19} />
          )}
        </button>
      </form>
    </Modal>
  );
}
