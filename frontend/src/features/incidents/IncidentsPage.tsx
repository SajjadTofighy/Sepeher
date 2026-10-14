import type { ColumnDef } from "@tanstack/react-table";
import { Activity, ArrowUpLeft, CheckCircle2, Clock3, Radio, Siren, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { fa,labels,timeFa } from "../../api";
import DataTable from "../../shared/ui/DataTable";
import { Badge } from "../../shared/ui/primitives";
import SearchBox from "../../shared/ui/SearchBox";
import type { Incident } from "../../types";
export default function IncidentsPage({
  rows,
  allRows,
  search,
  setSearch,
  filter,
  setFilter,
  onOpen,
}: {
  rows: Incident[];
  allRows: Incident[];
  search: string;
  setSearch: (s: string) => void;
  filter: string;
  setFilter: (s: string) => void;
  onOpen: (i: Incident) => void;
}) {
  const columns = useMemo<ColumnDef<Incident, unknown>[]>(
    () => [
      {
        accessorKey: "title",
        header: "پرونده / موضوع",
        cell: ({ row }) => (
          <>
            <strong>{row.original.title}</strong>
            <small>{row.original.id}</small>
          </>
        ),
      },
      { accessorKey: "zone", header: "محدوده" },
      {
        accessorKey: "severity",
        header: "اهمیت",
        cell: ({ row }) => <Badge value={row.original.severity} />,
      },
      {
        accessorKey: "status",
        header: "وضعیت",
        cell: ({ row }) => <Badge value={row.original.status} />,
      },
      {
        accessorKey: "created_at",
        header: "زمان کشف",
        cell: ({ row }) => timeFa(row.original.created_at),
      },
      {
        id: "actions",
        header: "اقدام",
        cell: ({ row }) => (
          <button className="table-button" onClick={() => onOpen(row.original)}>
            پرونده <ArrowUpLeft size={16} />
          </button>
        ),
      },
    ],
    [onOpen],
  );
  const open = allRows.filter((i) => i.status !== "closed");
  const critical = open.filter((i) => i.severity === "critical").length;
  const active = open.filter((i) => ["confirmed", "assigned", "en_route", "on_scene"].includes(i.status)).length;
  const closed = allRows.filter((i) => i.status === "closed").length;
  return (
    <section className="incidents-workspace">
      <header className="incidents-hero">
        <div>
          <span className="incidents-kicker"><Radio size={12}/> INCIDENT COMMAND</span>
          <h1>مدیریت حوادث <i/></h1>
          <p>پایش، اولویت‌بندی و مدیریت یکپارچه پرونده‌های عملیاتی</p>
        </div>
        <div className="incidents-live"><span className="live-dot"/><div><b>پایش زنده فعال است</b><small>به‌روزرسانی خودکار اطلاعات</small></div></div>
      </header>
      <div className="incident-kpis">
        <article className="incident-kpi danger"><span><Siren size={20}/></span><div><small>حوادث باز</small><b>{fa(open.length)}</b><p>نیازمند بررسی و اقدام</p></div></article>
        <article className="incident-kpi critical"><span><TriangleAlert size={20}/></span><div><small>بحرانی</small><b>{fa(critical)}</b><p>اولویت رسیدگی فوری</p></div></article>
        <article className="incident-kpi active"><span><Activity size={20}/></span><div><small>در حال رسیدگی</small><b>{fa(active)}</b><p>عملیات فعال میدانی</p></div></article>
        <article className="incident-kpi resolved"><span><CheckCircle2 size={20}/></span><div><small>خاتمه‌یافته</small><b>{fa(closed)}</b><p>پرونده‌های تکمیل‌شده</p></div></article>
      </div>
      <section className="incident-registry">
        <div className="incident-registry-head">
          <div className="registry-title"><span><Clock3 size={18}/></span><div><b>پرونده‌های عملیات</b><small>{fa(rows.length)} پرونده مطابق فیلتر فعلی</small></div></div>
          <div className="filters incident-filters">
          <SearchBox value={search} set={setSearch} />
          <select
            aria-label="فیلتر اهمیت"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">همه سطوح</option>
            {["critical", "high", "medium", "low"].map((x) => (
              <option key={x} value={x}>
                {labels[x]}
              </option>
            ))}
          </select>
          </div>
        </div>
        <DataTable rows={rows} columns={columns} />
      </section>
    </section>
  );
}
