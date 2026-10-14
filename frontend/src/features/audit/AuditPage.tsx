import { useState } from "react";
import { Activity, CheckCircle2, Database, Download, Fingerprint, FileClock, RefreshCw, ShieldCheck, UserRoundCheck } from "lucide-react";
import { api, fa, labels, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { download } from "../../shared/lib/download";
import type { AuditVerification, Data } from "../../types";

export default function AuditPage({ data, act, setToast }: { data: Data; act: Act; setToast: (s: string) => void }) {
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const actors = new Set(data.audit.map((item) => item.actor)).size;
  const targets = new Set(data.audit.map((item) => item.target)).size;

  const verify = async () => {
    const result = await act(() => api<AuditVerification>("/audit/verify"));
    if (!result) return;
    setVerification(result);
    setToast(result.valid ? `زنجیره ${fa(result.count)} رکورد معتبر است` : "عدم تطابق زنجیره");
  };

  return <section className="audit-workspace">
    <header className="audit-hero">
      <div className="audit-hero-copy">
        <span className="audit-kicker"><Fingerprint size={15}/> SECURITY OBSERVABILITY</span>
        <h2>گزارش‌ها و پایش یکپارچگی</h2>
        <p>ردیابی تغییرات، بررسی زنجیره سوابق و مشاهده‌پذیری اقدامات سامانه</p>
        <div className="audit-ledger-state"><span><i className="live-dot"/> دفتر ثبت در حال پایش</span><small>ثبت زنجیره‌ای اقدامات عملیاتی</small></div>
      </div>
      <div className="audit-hero-seal" aria-hidden="true"><ShieldCheck size={42}/><i/><i/></div>
      <div className={`audit-integrity ${verification ? (verification.valid ? "valid" : "invalid") : "idle"}`}>
        <small>وضعیت آخرین بررسی</small>
        <strong>{verification ? (verification.valid ? "زنجیره معتبر" : "عدم تطابق") : "آماده بررسی"}</strong>
        <span>{verification ? `${fa(verification.count)} رکورد ارزیابی شد` : "کنترل یکپارچگی اجرا نشده"}</span>
      </div>
    </header>

    <div className="audit-kpis">
      <article className="cyan"><span><FileClock size={18}/></span><div><small>کل سوابق</small><b>{fa(data.audit.length)}</b><em>رویداد ثبت‌شده</em></div></article>
      <article className="green"><span><UserRoundCheck size={18}/></span><div><small>عاملان ثبت‌شده</small><b>{fa(actors)}</b><em>هویت عملیاتی</em></div></article>
      <article className="violet"><span><Database size={18}/></span><div><small>مراجع یکتا</small><b>{fa(targets)}</b><em>موجودیت ممیزی‌شده</em></div></article>
      <article className="amber"><span><CheckCircle2 size={18}/></span><div><small>سلامت زنجیره</small><b>{verification ? (verification.valid ? "معتبر" : "خطا") : "نامشخص"}</b><em>نیازمند بررسی دوره‌ای</em></div></article>
    </div>

    <section className="audit-control-strip">
      <div className="audit-control-copy"><span><Activity size={18}/></span><div><b>کنترل دفتر اقدامات</b><small>زنجیره هش نمونه در حافظه است؛ ذخیره‌ساز WORM در این محیط نمایشی پیاده‌سازی نشده است.</small></div></div>
      <div className="audit-actions">
        <button className="secondary audit-verify" onClick={verify}><RefreshCw size={15}/> بررسی زنجیره</button>
        <button className="secondary audit-export" onClick={() => download("sepehr-audit.json", data.audit)}><Download size={15}/> دریافت خروجی</button>
      </div>
    </section>

    <section className="audit-registry">
      <header className="audit-registry-head">
        <div><span><Fingerprint size={19}/></span><div><b>دفتر ثبت اقدامات</b><small>ترتیب زمانی سوابق و اثر انگشت رمزنگاری‌شده هر رکورد</small></div></div>
        <span className="audit-record-count">{fa(data.audit.length)} رکورد</span>
      </header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>زمان ثبت</th><th>اقدام و جزئیات</th><th>مرجع</th><th>کاربر</th><th>اثر انگشت رکورد</th></tr></thead>
          <tbody>{data.audit.map((item, index) => <tr key={item.id}>
            <td><div className="audit-time"><i /><span>{timeFa(item.time)}<small>#{fa(data.audit.length - index)}</small></span></div></td>
            <td><div className="audit-action-cell"><span><Activity size={14}/></span><div><strong>{item.action}</strong><small>{labels[item.detail] || item.detail}</small></div></div></td>
            <td><span className="audit-target" dir="ltr">{item.target}</span></td>
            <td><span className="audit-actor"><UserRoundCheck size={13}/>{item.actor}</span></td>
            <td><code className="audit-hash" title={item.hash}><Fingerprint size={13}/>{item.hash.slice(0, 18)}…</code></td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  </section>;
}
