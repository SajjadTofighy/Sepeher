import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { fa } from "../../api";
export default function DataTable<T>({
  rows,
  columns,
}: {
  rows: T[];
  columns: ColumnDef<T, unknown>[];
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((h) => (
                  <th
                    key={h.id}
                    aria-sort={
                      h.column.getIsSorted() === "asc"
                        ? "ascending"
                        : h.column.getIsSorted() === "desc"
                          ? "descending"
                          : "none"
                    }
                  >
                    {h.isPlaceholder ? null : h.column.getCanSort() ? (
                      <button
                        className="sort-heading"
                        onClick={h.column.getToggleSortingHandler()}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        <ArrowUpDown size={12} />
                      </button>
                    ) : (
                      flexRender(h.column.columnDef.header, h.getContext())
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <div className="empty">رکوردی مطابق جستجو وجود ندارد.</div>
        )}
      </div>
      <div className="table-pagination">
        <span>{fa(rows.length)} رکورد</span>
        <div>
          <button
            className="icon-button"
            aria-label="صفحه قبل"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            <ChevronRight size={17} />
          </button>
          <span>
            صفحه {fa(table.getState().pagination.pageIndex + 1)} از{" "}
            {fa(Math.max(1, table.getPageCount()))}
          </span>
          <button
            className="icon-button"
            aria-label="صفحه بعد"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            <ChevronLeft size={17} />
          </button>
          <select
            aria-label="تعداد ردیف"
            value={table.getState().pagination.pageSize}
            onChange={(e) => table.setPageSize(+e.target.value)}
          >
            {[10, 25, 50].map((n) => (
              <option key={n} value={n}>
                {fa(n)} ردیف
              </option>
            ))}
          </select>
        </div>
      </div>
    </>
  );
}
