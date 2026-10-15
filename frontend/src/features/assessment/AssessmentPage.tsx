import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Download, Printer } from "lucide-react";
import { useState } from "react";
import { api, fa, parseResponse, sessionHeaders } from "../../api";
import { openPrintWindow } from "../../shared/lib/print";
import DataTable from "../../shared/ui/DataTable";
import { Badge, StatStrip } from "../../shared/ui/primitives";
import type { SecurityDossier } from "../../types";

const AUTH_LABELS: Record<string, string> = {
  public: "عمومی",
  device_signature: "امضای دستگاه",
  required: "احراز اجباری",
  optional_unless_enforce_all: "اختیاری تا فعال‌سازی سراسری",
};

type Endpoint = SecurityDossier["endpoints"][number];
const endpointColumns: ColumnDef<Endpoint, unknown>[] = [
  { header: "روش", accessorKey: "method" },
  { header: "مسیر", accessorKey: "path", cell: ({ row }) => <span dir="ltr" className="hash">{row.original.path}</span> },
  { header: "احراز", accessorKey: "authentication", cell: ({ row }) => {
    const auth = row.original.authentication;
    return <><Badge value={auth === "required" ? "online" : auth === "public" ? "info" : "warning"} /> {AUTH_LABELS[auth]}</>;
  } },
  { header: "نقش‌ها", accessorKey: "roles", enableSorting: false, cell: ({ row }) => row.original.roles.join("، ") || "—" },
];
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
      <StatStrip items={[
        { label: "مسیر API", value: fa(d.endpoints.length) },
        ...Object.entries(counts).map(([k, v]) => ({ label: AUTH_LABELS[k] || k, value: fa(v) })),
        { label: "زنجیره ممیزی", value: d.audit_chain.valid ? "سالم" : "ناسازگار", note: `${fa(d.audit_chain.count)} رکورد`, tone: d.audit_chain.valid ? "ok" as const : "danger" as const },
        { label: "هویت", value: d.system.auth_mode === "keycloak" ? "کیکلاک" : "نمایشی", note: d.system.enforce_all ? "احراز سراسری" : "احراز مسیرهای گشت" },
      ]} />
      <div className="assessment-layout">
        <div className="panel comms-list">
          <h3>کنترل دسترسی مسیرها</h3>
          <div className="comms-filters">
            <label className="field">نوع احراز<select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">همه</option>
              {Object.keys(counts).map((k) => <option key={k} value={k}>{AUTH_LABELS[k] || k}</option>)}
            </select></label>
          </div>
          <DataTable rows={endpoints} columns={endpointColumns} />
        </div>
        <aside className="panel suspended-list">
          <h3>ریسک‌های باقی‌مانده</h3>
          <ul>{d.residual_risks.map((r) => <li key={r}><small>{r}</small></li>)}</ul>
        </aside>
      </div>
      <div className="panel comms-list">
        <h3>رمزنگاری</h3>
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
