import { Activity, BarChart3, CalendarRange, Download, Gauge, ShieldCheck, Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";
import ShiftReportView from "./ShiftReportView";
import { fa } from "../../api";
import Chart from "../../shared/ui/Chart";
import { PanelTitle } from "../../shared/ui/primitives";
import type { Data } from "../../types";
import Stats from "./Stats";
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
    [
      "هشدارهای سیاست",
      fa(s.policy_alerts),
      `${fa(s.shadow_alerts)} در حالت سایه`,
    ],
    [
      "پرونده‌های بسته‌شده",
      fa(s.closed_incidents),
      `${fa(s.open_incidents)} پرونده باز`,
    ],
    [
      "تجهیزات نیازمند نگهداری",
      fa(s.maintenance),
      "قطع یا بسته داده رو به اتمام",
    ],
    [
      "سیاست‌های فعال",
      fa(s.active_policies),
      `از ${fa(data.policies.length)} سیاست تعریف‌شده`,
    ],
    ["کانون رخداد", s.hot_zone || "—", "بیشترین پرونده باز"],
  ];
  const chartText = theme === "light" ? "#4f7181" : "#9ab6c6";
  const chartGrid = theme === "light" ? "#a9c2ca" : "#243b49";
  return (
    <section className="analytics-workspace">
      <header className="analytics-hero">
        <div className="analytics-hero-copy">
          <span className="analytics-kicker"><BarChart3 size={15}/> EXECUTIVE INTELLIGENCE</span>
          <h2>داشبورد مدیریتی عملیات</h2>
          <p>نمای یکپارچه آمادگی، ریسک و عملکرد شیفت برای تصمیم‌گیری سریع مدیریتی</p>
          <div className="analytics-live-state"><span><i className="live-dot"/> داده عملیاتی همگام</span><small>آخرین وضعیت تجمیع‌شده سامانه</small></div>
        </div>
        <div className="analytics-hero-score">
          <span><Gauge size={19}/><small>دسترس‌پذیری سامانه</small></span>
          <strong>{fa(s.availability)}<small>٪</small></strong>
          <div><i style={{width: `${s.availability}%`}}/></div>
        </div>
        <div className="analytics-signal" aria-hidden="true"><i/><i/><i/><i/><i/><i/></div>
      </header>

      <Stats data={data}/>

      <div className="analytics-viewbar">
        <div><span><Sparkles size={17}/></span><div><b>مرکز تحلیل مدیریت</b><small>انتخاب نمای شاخص‌ها یا گزارش تفصیلی شیفت</small></div></div>
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
          <div className="kpi-strip">
            {kpis.map(([t, v, m], index) => (
              <div className={`management-kpi kpi-${index + 1}`} key={t}>
                <small>{t}</small>
                <b>{v}</b>
                <span>{m}</span>
              </div>
            ))}
          </div>
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
          <div className="analytics-note">
            <ShieldCheck size={24} />
            <p>
              دسترس‌پذیری نمونه <b>{fa(s.availability)}٪</b> · برای سنجش واقعی
              پایلوت، اتصال به داده‌های ثبت‌شده و زیرساخت پایش لازم است.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
