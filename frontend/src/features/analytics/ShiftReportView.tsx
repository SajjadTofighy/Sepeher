import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Printer } from "lucide-react";
import { api, fa } from "../../api";
import { download } from "../../shared/lib/download";
import {
  tehranInputISO,
  tehranLocalInput,
  tehranTime,
} from "../../shared/lib/time";
import { PanelTitle } from "../../shared/ui/primitives";
import type { Data, ShiftReport, ShiftReportLine } from "../../types";
import { printShiftReport } from "./printShiftReport";

export default function ShiftReportView({
  data,
  onSource,
}: {
  data: Data;
  onSource: (id: string) => void;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["reports", "shift", range],
    queryFn: ({ signal }) =>
      api<ShiftReport>(
        `/reports/shift${range ? `?${new URLSearchParams(range)}` : ""}`,
        "GET",
        undefined,
        signal,
      ),
    refetchInterval: 3000,
  });
  const report = query.data;
  const sourceHref = (id: string) => {
    if (
      data.incidents.some((i) => i.id === id) ||
      data.assets.some((a) => a.id === id)
    )
      return "#command";
    if (data.missions.some((m) => m.id === id)) return "#missions";
    if (data.facilities.some((f) => f.id === id) || id.includes("-SEG-"))
      return "#geography";
    if (data.commands.some((c) => c.id === id)) return "#assets";
    if (id.startsWith("AUD-")) return "#audit";
    return undefined;
  };
  const renderSource = (id: string) =>
    sourceHref(id) ? (
      <a
        href={sourceHref(id)}
        dir="ltr"
        key={id}
        onClick={(e) => {
          e.preventDefault();
          onSource(id);
        }}
        aria-label={`نمایش منبع ${id}`}
      >
        {id}
      </a>
    ) : (
      <span dir="ltr" key={id}>
        {id}
      </span>
    );
  const renderLine = (line: ShiftReportLine, index: number) => (
    <li key={index}>
      <p>{line.text}</p>
      <div className="shift-sources">
        <small>منابع:</small>
        {line.source_ids.slice(0, 5).map(renderSource)}
        {line.source_ids.length > 5 && (
          <details>
            <summary>{fa(line.source_ids.length - 5)} منبع دیگر</summary>
            <div className="shift-sources">
              {line.source_ids.slice(5).map(renderSource)}
            </div>
          </details>
        )}
      </div>
    </li>
  );
  return (
    <section className="panel shift-report">
      <PanelTitle
        title="گزارش شیفت"
        sub="تجمیع رکوردهای موجود · زمان تهران · پیش‌فرض: آخرین شیفت کامل‌شده"
      >
        <div className="shift-report-actions">
          <button
            className="secondary"
            disabled={!report}
            onClick={() =>
              report &&
              download(
                `sepehr-shift-${report.window_to.slice(0, 10)}.json`,
                report,
              )
            }
          >
            <Download size={16} />
            دریافت JSON
          </button>
          <button
            className="secondary"
            disabled={!report}
            onClick={() => {
              if (!report) return;
              try {
                printShiftReport(report);
                setError("");
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <Printer size={16} />
            چاپ گزارش شیفت
          </button>
        </div>
      </PanelTitle>
      <form
        className="shift-report-range"
        onSubmit={(e) => {
          e.preventDefault();
          try {
            const a = tehranInputISO(from),
              b = tehranInputISO(to);
            if (Date.parse(a) >= Date.parse(b) || Date.parse(b) > Date.now())
              throw new Error(
                "آغاز باید قبل از پایان و پایان حداکثر زمان جاری باشد.",
              );
            setRange({ from: a, to: b });
            setError("");
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        <label className="field">
          آغاز بازه · تهران
          <input
            type="datetime-local"
            required
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label className="field">
          پایان بازه · تهران
          <input
            type="datetime-local"
            required
            value={to}
            max={tehranLocalInput(new Date())}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <button className="primary" type="submit" disabled={query.isFetching}>
          نمایش بازه
        </button>
        <button
          className="secondary"
          type="button"
          onClick={() => {
            setRange(null);
            setFrom("");
            setTo("");
            setError("");
          }}
        >
          آخرین شیفت کامل‌شده
        </button>
      </form>
      {error && <p className="error-banner">{error}</p>}
      {query.isError && (
        <p className="error-banner">
          {query.error.message}{" "}
          <button onClick={() => query.refetch()}>تلاش مجدد</button>
        </p>
      )}
      {query.isPending && (
        <div className="empty">در حال دریافت گزارش شیفت…</div>
      )}
      {report && (
        <>
          <p className="shift-window">
            {tehranTime(report.window_from)} تا {tehranTime(report.window_to)}
          </p>
          <p className="muted">
            داده‌های عملیاتی از {tehranTime(report.data_since)} · شمارش شامل
            آغاز و بدون لحظه پایان است.
          </p>
          {report.partial && (
            <p className="warning-banner" role="status">
              گزارش جزئی است؛ داده‌های پیش از شروع سرور یا بازنشانی و تاریخچه
              ناموجود در شمارش نیستند.
            </p>
          )}
          <div className="shift-report-sections">
            {Object.entries(report.sections).map(([key, section]) => (
              <section key={key}>
                <h3>
                  {section.title}
                  {section.partial && (
                    <span className="neutral-pill">پوشش جزئی بازه</span>
                  )}
                </h3>
                {section.notes.map((note) => (
                  <p className="muted" key={note}>
                    {note}
                  </p>
                ))}
                <ul>
                  {section.lines
                    .slice(0, key === "coverage" ? 2 : 3)
                    .map(renderLine)}
                </ul>
                {section.lines.length > (key === "coverage" ? 2 : 3) && (
                  <details className="shift-details">
                    <summary>
                      جزئیات{" "}
                      {fa(section.lines.length - (key === "coverage" ? 2 : 3))}{" "}
                      مورد
                    </summary>
                    <ul>
                      {section.lines
                        .slice(key === "coverage" ? 2 : 3)
                        .map(renderLine)}
                    </ul>
                  </details>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
