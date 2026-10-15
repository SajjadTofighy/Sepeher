import { useQuery } from "@tanstack/react-query";
import { Download, FileCheck2, Printer, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { api, fa, parseResponse, sessionHeaders } from "../../api";
import { openPrintWindow } from "../../shared/lib/print";
import { Badge, PanelTitle } from "../../shared/ui/primitives";
import type { SecurityDossier } from "../../types";

const AUTH_LABELS: Record<string, string> = {
  public: "عمومی",
  device_signature: "امضای دستگاه",
  required: "احراز اجباری",
  optional_unless_enforce_all: "اختیاری تا فعال‌سازی سراسری",
};

export default function AssessmentPage() {
  const dossier = useQuery({ queryKey: ["assessment", "dossier"], queryFn: () => api<SecurityDossier>("/audit/security-dossier"), retry: false });
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const printLetter = async () => {
    setError("");
    try {
      const response = await fetch("/api/v1/audit/security-dossier/letter", { headers: sessionHeaders(), cache: "no-store" });
      if (!response.ok) await parseResponse(response);
      const w = openPrintWindow();
      w.document.write(await response.text());
      w.document.close();
      w.focus();
      w.print();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(dossier.data, null, 2)], { type: "application/json" }));
    a.download = "sepehr-security-dossier.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  if (dossier.isPending) return <div className="panel empty">در حال گردآوری شواهد…</div>;
  if (dossier.isError) return <div className="error-banner">{(dossier.error as Error).message} — این صفحه فقط برای نقش ممیز است.</div>;
  const d = dossier.data!;
  const counts: Record<string, number> = {};
  d.endpoints.forEach((e) => { counts[e.authentication] = (counts[e.authentication] || 0) + 1; });
  const endpoints = d.endpoints.filter((e) => !filter || e.authentication === filter);
  return (
    <section className="supervision">
      <PanelTitle title="پرونده شواهد ارزیابی امنیتی (افتا)" sub="شواهد قابل‌راستی‌آزمایی از سامانه در حال اجرا برای استعلام الزام و دامنه ارزیابی؛ این صفحه نتیجه ارزیابی نیست">
        <span className="classification-chip">{d.classification_label}</span>
      </PanelTitle>
      {error && <div className="error-banner">{error}</div>}
      <div className="report-actions">
        <button className="primary" onClick={printLetter}><Printer size={16} />چاپ پیش‌نویس نامه استعلام</button>
        <button className="secondary" onClick={download}><Download size={16} />دانلود پرونده JSON</button>
      </div>
      <p className="muted">
        بسته کامل با بررسی realm، فهرست وابستگی، نتیجه آزمون‌ها و manifest هش:{" "}
        <code dir="ltr">python scripts/security_dossier.py --out DIR --base-url URL --token TOKEN --run-tests</code>
        {" "}· ممیزی {d.audit_id} · {d.generated_at_jalali}
      </p>
      <div className="report-totals">
        <div><b>{fa(d.endpoints.length)}</b><small>مسیر API</small></div>
        {Object.entries(counts).map(([k, v]) => <div key={k}><b>{fa(v)}</b><small>{AUTH_LABELS[k] || k}</small></div>)}
        <div><b className={d.audit_chain.valid ? "ack-done" : "flag"}>{d.audit_chain.valid ? "سالم" : "ناسازگار"}</b><small>زنجیره ممیزی · {fa(d.audit_chain.count)}</small></div>
        <div><b>{d.system.auth_mode === "keycloak" ? "کیکلاک" : "نمایشی"}</b><small>{d.system.enforce_all ? "احراز سراسری" : "احراز مسیرهای گشت"}</small></div>
      </div>
      <div className="supervision-grid">
        <div className="panel comms-list">
          <h3><ShieldCheck size={16} /> کنترل دسترسی مسیرها</h3>
          <div className="comms-filters">
            <label className="field">نوع احراز<select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">همه</option>
              {Object.keys(counts).map((k) => <option key={k} value={k}>{AUTH_LABELS[k] || k}</option>)}
            </select></label>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>روش</th><th>مسیر</th><th>احراز</th><th>نقش‌ها</th></tr></thead>
            <tbody>{endpoints.map((e) => (
              <tr key={e.method + e.path}><td>{e.method}</td><td dir="ltr" className="hash">{e.path}</td>
                <td><Badge value={e.authentication === "required" ? "online" : e.authentication === "public" ? "info" : "warning"} /> {AUTH_LABELS[e.authentication]}</td>
                <td>{e.roles.join("، ") || "—"}</td></tr>
            ))}</tbody>
          </table></div>
        </div>
        <aside className="panel suspended-list">
          <h3><TriangleAlert size={16} /> ریسک‌های باقی‌مانده</h3>
          <ul>{d.residual_risks.map((r) => <li key={r}><small>{r}</small></li>)}</ul>
        </aside>
      </div>
      <div className="panel comms-list">
        <h3><FileCheck2 size={16} /> رمزنگاری</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>کاربرد</th><th>الگوریتم</th><th>پیاده‌سازی</th></tr></thead>
          <tbody>{d.cryptography.map((c) => <tr key={c.purpose}><td>{c.purpose}</td><td>{c.algorithm}</td><td>{c.implementation}</td></tr>)}</tbody>
        </table></div>
        <h3>داده‌های ذخیره‌شده</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>مخزن</th><th>شرح</th><th>شخصی</th><th>نگهداری</th><th>تعداد</th></tr></thead>
          <tbody>{d.data_inventory.map((x) => <tr key={x.store}><td dir="ltr">{x.store}</td><td>{x.description}</td><td>{x.personal ? "بله" : "خیر"}</td><td>{x.retention}</td><td>{fa(x.records)}</td></tr>)}</tbody>
        </table></div>
        <h3>سربرگ‌های امنیتی پاسخ</h3>
        <div className="table-wrap"><table>
          <tbody>{Object.entries(d.response_headers).map(([k, v]) => <tr key={k}><td dir="ltr">{k}</td><td dir="ltr" className="hash">{v}</td></tr>)}</tbody>
        </table></div>
      </div>
    </section>
  );
}
