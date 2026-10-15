import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { api, fa, labels, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { download } from "../../shared/lib/download";
import DataTable from "../../shared/ui/DataTable";
import { StatStrip } from "../../shared/ui/primitives";
import type { Audit, AuditVerification, Data } from "../../types";

export default function AuditPage({ data, act, setToast }: { data: Data; act: Act; setToast: (s: string) => void }) {
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const actors = new Set(data.audit.map((item) => item.actor)).size;
  const targets = new Set(data.audit.map((item) => item.target)).size;
  const columns = useMemo<ColumnDef<Audit, unknown>[]>(() => [
    { header: "زمان", accessorKey: "time", cell: ({ row }) => timeFa(row.original.time) },
    { header: "اقدام", accessorKey: "action", cell: ({ row }) => <><b>{row.original.action}</b><small className="cell-note">{labels[row.original.detail] || row.original.detail}</small></> },
    { header: "مرجع", accessorKey: "target", cell: ({ row }) => <span dir="ltr">{row.original.target}</span> },
    { header: "کاربر", accessorKey: "actor" },
    { header: "اثر انگشت", accessorKey: "hash", enableSorting: false, cell: ({ row }) => <code title={row.original.hash} dir="ltr">{row.original.hash.slice(0, 16)}…</code> },
  ], []);

  const verify = async () => {
    const result = await act(() => api<AuditVerification>("/audit/verify"));
    if (!result) return;
    setVerification(result);
    setToast(result.valid ? `زنجیره ${fa(result.count)} رکورد معتبر است` : "عدم تطابق زنجیره");
  };

  return <section className="audit-workspace">
    <StatStrip items={[
      { label: "کل سوابق", value: fa(data.audit.length) },
      { label: "عاملان", value: fa(actors) },
      { label: "مراجع یکتا", value: fa(targets) },
      { label: "سلامت زنجیره", value: verification ? (verification.valid ? "معتبر" : "عدم تطابق") : "بررسی نشده",
        note: verification ? `${fa(verification.count)} رکورد بررسی شد` : undefined,
        tone: verification ? (verification.valid ? "ok" : "danger") : undefined },
    ]} />

    <section className="panel audit-registry">
      <div className="panel-title">
        <div><h2>دفتر ثبت اقدامات</h2><p>زنجیره هش در این محیط نگهداری می‌شود؛ ذخیره‌ساز WORM پیاده‌سازی نشده است.</p></div>
        <div className="heading-actions">
          <button className="secondary" onClick={verify}><RefreshCw size={15}/> بررسی زنجیره</button>
          <button className="secondary" onClick={() => download("sepehr-audit.json", data.audit)}><Download size={15}/> دریافت خروجی</button>
        </div>
      </div>
      <DataTable rows={data.audit} columns={columns} />
    </section>
  </section>;
}
