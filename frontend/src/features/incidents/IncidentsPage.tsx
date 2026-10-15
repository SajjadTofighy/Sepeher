import type { ColumnDef } from "@tanstack/react-table";
import { ArrowUpLeft } from "lucide-react";
import { useMemo } from "react";
import { fa,labels,timeFa } from "../../api";
import DataTable from "../../shared/ui/DataTable";
import { Badge, StatStrip } from "../../shared/ui/primitives";
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
      <StatStrip items={[
        { label: "حوادث باز", value: fa(open.length), tone: open.length ? "warn" : undefined },
        { label: "بحرانی", value: fa(critical), tone: critical ? "danger" : undefined },
        { label: "در حال رسیدگی", value: fa(active) },
        { label: "خاتمه‌یافته", value: fa(closed) },
      ]} />
      <section className="incident-registry">
        <div className="incident-registry-head">
          <div className="registry-title"><b>پرونده‌ها</b><small>{fa(rows.length)} مورد</small></div>
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
