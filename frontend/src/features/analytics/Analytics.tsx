import { CalendarRange, Download, TrendingUp } from "lucide-react";
import { useState } from "react";
import ShiftReportView from "./ShiftReportView";
import { fa } from "../../api";
import Chart from "../../shared/ui/Chart";
import { PanelTitle, StatStrip } from "../../shared/ui/primitives";
import type { Data } from "../../types";
export default function Analytics({
  data,
  onExport,
  onSource,
  theme,
}: {
  data: Data;
  onExport: () => void;
  onSource: (id: string) => void;
  theme: "dark" | "light";
}) {
  const [view, setView] = useState("metrics");
  const s = data.summary;
  const kpis = [
    { label: "تجهیزات برخط", value: `${fa(s.online)} / ${fa(s.total)}`, note: `${fa(s.maintenance)} نیازمند نگهداری` },
    { label: "پرونده باز", value: fa(s.open_incidents), note: `${fa(s.critical)} بحرانی`, tone: s.critical ? "danger" as const : undefined },
    { label: "بسته‌شده", value: fa(s.closed_incidents) },
    { label: "سیاست فعال", value: fa(s.active_policies), note: `${fa(s.policy_alerts)} هشدار · ${fa(s.shadow_alerts)} سایه` },
    { label: "پوشش گشت", value: `${fa(s.coverage)}٪`, note: s.hot_zone ? `کانون: ${s.hot_zone}` : undefined },
  ];
  const chartText = theme === "light" ? "#4f7181" : "#9ab6c6";
  const chartGrid = theme === "light" ? "#a9c2ca" : "#243b49";
  return (
    <section className="analytics-workspace">

      <div className="analytics-viewbar">
        <div className="settings-tabs analytics-tabs">
        <button
          className={view === "metrics" ? "selected" : ""}
          onClick={() => setView("metrics")}
        >
          <TrendingUp size={15}/> شاخص‌های مدیریتی
        </button>
        <button
          className={view === "shift" ? "selected" : ""}
          onClick={() => setView("shift")}
        >
          <CalendarRange size={15}/> گزارش شیفت
        </button>
        </div>
      </div>
      {view === "shift" ? (
        <ShiftReportView data={data} onSource={onSource} />
      ) : (
        <>
          <StatStrip items={kpis} />
          <div className="analytics-grid">
            <section className="panel">
              <PanelTitle
                title="روند رخدادها"
                sub="هفت روز نمونه · تعداد رخداد در هر روز"
              >
                <span className="neutral-pill">داده نمایشی</span>
              </PanelTitle>
              <Chart
                label="روند هفت روزه رخدادهای نمونه"
                option={{
                    textStyle: { fontFamily: "Vazirmatn", color: chartText },
                  grid: { top: 20, left: 30, right: 20, bottom: 55 },
                  tooltip: {
                    trigger: "axis",
                    backgroundColor: theme === "light" ? "#c8dce1" : "#132b38",
                    borderColor: theme === "light" ? "#8eafb9" : "#476573",
                    textStyle: { color: theme === "light" ? "#244b5a" : "#dceaf0", fontFamily: "Vazirmatn" },
                  },
                  xAxis: {
                    type: "category",
                    data: [
                      "چهارشنبه",
                      "پنجشنبه",
                      "جمعه",
                      "شنبه",
                      "یکشنبه",
                      "دوشنبه",
                      "امروز",
                    ],
                    axisLine: { lineStyle: { color: chartGrid } },
                    axisLabel: { fontSize: 11 },
                  },
                  yAxis: {
                    type: "value",
                    splitLine: {
                      lineStyle: { color: chartGrid, type: "dashed" },
                    },
                  },
                  dataZoom: [
                    { type: "inside" },
                    {
                      type: "slider",
                      height: 10,
                      bottom: 5,
                      borderColor: "#34505d",
                      fillerColor: "#5fb5a333",
                      handleStyle: { color: "#6bc4ad" },
                      textStyle: { color: "#83a9b8" },
                    },
                  ],
                  series: [
                    {
                      type: "line",
                      smooth: true,
                      data: s.trend,
                      symbol: "circle",
                      symbolSize: 8,
                      lineStyle: { color: "#6fd2b8", width: 3 },
                      itemStyle: {
                        color: "#89e6cf",
                        borderColor: "#224e49",
                        borderWidth: 3,
                      },
                      areaStyle: {
                        color: {
                          type: "linear",
                          x: 0,
                          y: 0,
                          x2: 0,
                          y2: 1,
                          colorStops: [
                            { offset: 0, color: "#5ba89155" },
                            { offset: 1, color: "#5ba89100" },
                          ],
                        },
                      },
                    },
                  ],
                  aria: { enabled: true },
                  animationDuration: 600,
                }}
              />
            </section>
            <section className="panel">
              <PanelTitle
                title="پوشش مناطق"
                sub="درصد قطعه‌ها و تأسیسات بازدیدشده در مهلت تعیین‌شده"
              />
              {s.fields.map((f) => (
                <div className="field-coverage" key={f.name}>
                  <div>
                    <b>{f.name}</b>
                    <span>{fa(f.coverage)}٪</span>
                  </div>
                  <div className="progress">
                    <i style={{ width: f.coverage + "%" }} />
                  </div>
                  <small>{fa(f.events)} رخداد نمونه</small>
                </div>
              ))}
            </section>
          </div>
          <section className="panel cycle-panel">
            <PanelTitle
              title="زمان‌های چرخه حادثه"
              sub="میانگین از خط زمانی پرونده‌ها، از لحظه ثبت هشدار؛ تا اولین اندازه‌گیری، خط مبنای نمونه نمایش داده می‌شود."
            >
              <button className="secondary" onClick={onExport}>
                <Download size={16} />
                خروجی شاخص‌ها
              </button>
            </PanelTitle>
            <div className="cycle-grid">
              {["تا تأیید", "تا اعزام", "تا حضور", "تا خاتمه"].map((n, i) => (
                <div key={n}>
                  <span className="cycle-index">۰{i + 1}</span>
                  <h3>{n}</h3>
                  <b>
                    {fa(s.cycle[i])}
                    <small> دقیقه</small>
                  </b>
                  <small
                    className={s.cycle_measured[i] ? "measured" : "baseline"}
                  >
                    {s.cycle_measured[i]
                      ? `اندازه‌گیری از ${fa(s.cycle_samples[i])} پرونده`
                      : "خط مبنای نمونه"}
                  </small>
                  <div
                    className="cycle-line"
                    style={{
                      width: Math.max(15, (s.cycle[i] / 20) * 100) + "%",
                    }}
                  />
                </div>
              ))}
            </div>
          </section>
          <p className="muted page-footnote">
            دسترس‌پذیری نمونه {fa(s.availability)}٪؛ سنجش واقعی پایلوت به داده‌های ثبت‌شده و زیرساخت پایش نیاز دارد.
          </p>
        </>
      )}
    </section>
  );
}
