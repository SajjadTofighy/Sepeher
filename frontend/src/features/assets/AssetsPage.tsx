import type { ColumnDef } from "@tanstack/react-table";
import { ArrowUpLeft, Battery, Car, Signal, UserRound } from "lucide-react";
import { useMemo } from "react";
import { fa, timeFa } from "../../api";
import DataTable from "../../shared/ui/DataTable";
import { Badge, StatStrip } from "../../shared/ui/primitives";
import SearchBox from "../../shared/ui/SearchBox";
import type { Asset, Command, Data } from "../../types";
import CommandTable from "./CommandTable";
export default function AssetsPage({
  data,
  search,
  setSearch,
  onOpen,
  onRetry,
}: {
  data: Data;
  search: string;
  setSearch: (s: string) => void;
  onOpen: (a: Asset) => void;
  onRetry: (c: Command) => void;
}) {
  const rows = useMemo(
    () => data.assets.filter((a) => (a.name + a.field + a.id).includes(search)),
    [data.assets, search],
  );
  const columns = useMemo<ColumnDef<Asset, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "موجودیت",
        cell: ({ row: { original: a } }) => (
          <div className="entity">
            <div className="entity-icon">
              {a.kind === "vehicle" ? (
                <Car size={19} />
              ) : (
                <UserRound size={19} />
              )}
            </div>
            <div>
              <strong>{a.name}</strong>
              <small>{a.id}</small>
            </div>
          </div>
        ),
      },
      { accessorKey: "field", header: "ناحیه" },
      {
        accessorKey: "status",
        header: "وضعیت",
        cell: ({ row }) => <Badge value={row.original.status} />,
      },
      {
        accessorKey: "speed",
        header: "سرعت",
        cell: ({ row }) => (
          <>
            {fa(row.original.speed)} <small className="inline">km/h</small>
          </>
        ),
      },
      {
        accessorKey: "battery",
        header: "باتری / سیگنال",
        cell: ({ row: { original: a } }) => (
          <span className="battery">
            <Battery size={17} />
            {fa(a.battery)}٪ <Signal size={16} />
            {fa(a.signal)}/۴
          </span>
        ),
      },
      {
        accessorKey: "last_seen",
        header: "آخرین دریافت",
        cell: ({ row }) => timeFa(row.original.last_seen),
      },
      {
        id: "actions",
        header: "کنترل",
        cell: ({ row }) => (
          <button className="table-button" onClick={() => onOpen(row.original)}>
            مشاهده و فرمان <ArrowUpLeft size={16} />
          </button>
        ),
      },
    ],
    [onOpen],
  );
  const online = data.assets.filter((a) => a.status === "online").length;
  const offline = data.assets.filter((a) => a.status === "offline").length;
  const warning = data.assets.filter((a) => a.status === "warning").length;
  const vehicles = data.assets.filter((a) => a.kind === "vehicle").length;
  return (
    <section className="assets-workspace">
      <StatStrip items={[
        { label: "کل موجودیت‌ها", value: fa(data.assets.length), note: `${fa(vehicles)} وسیله نقلیه` },
        { label: "برخط", value: fa(online), tone: "ok" },
        { label: "نیازمند بررسی", value: fa(warning), tone: warning ? "warn" : undefined },
        { label: "قطع ارتباط", value: fa(offline), tone: offline ? "danger" : undefined },
      ]} />
      <section className="asset-registry">
        <div className="asset-registry-head">
          <div className="asset-registry-title"><div><b>ناوگان و نیروهای میدانی</b><small>{fa(rows.length)} موجودیت مطابق جستجو</small></div></div>
          <div className="asset-search"><SearchBox value={search} set={setSearch}/></div>
        </div>
        <DataTable rows={rows} columns={columns}/>
      </section>
      <CommandTable data={data} retry={onRetry} />
    </section>
  );
}
