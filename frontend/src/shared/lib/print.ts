import { tehranTime } from "./time";

export const escapePrintText = (value: string) =>
  value.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function openPrintWindow() {
  const w = window.open("", "_blank");
  if (!w) throw new Error("برای چاپ، پنجرهٔ جدید را در مرورگر مجاز کنید.");
  return w;
}

// Header and body are composed by feature renderers with escaped record values.
export function writePrintReport(
  w: Window,
  report: {
    title: string;
    header: string;
    generatedAt: string;
    body: string;
    footer: string;
  },
) {
  w.document
    .write(`<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>${escapePrintText(report.title)}</title><style>
body{font-family:Vazirmatn,Tahoma,sans-serif;color:#14212b;margin:40px;line-height:1.9}
header{display:flex;justify-content:space-between;border-bottom:3px solid #1d7f6e;padding-bottom:12px}
h1{font-size:22px;margin:0}small,.muted{color:#5b6c78}
.tag{display:inline-block;border:1px solid #c9d3da;border-radius:4px;padding:0 8px;margin-left:6px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0}
.grid div{border:1px solid #d7e0e5;border-radius:6px;padding:10px}.grid b{display:block;font-size:15px}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #e1e7eb;padding:8px;text-align:right}
th{background:#f1f5f7}footer{margin-top:30px;font-size:11px;color:#6b7b86}
</style></head><body>
<header><div>${report.header}</div><div class="muted">تولید: ${escapePrintText(tehranTime(report.generatedAt))}</div></header>
${report.body}
<footer>${escapePrintText(report.footer)}</footer>
<script>window.onload=()=>window.print()</script></body></html>`);
  w.document.close();
  return true;
}
