import { useEffect, useState } from "react";
import {
  Activity,
  CalendarClock,
  Clock3,
  Database,
  X,
  ChevronLeft,
  MapPin,
  Pause,
  Play,
  Route,
  Sparkles,
} from "lucide-react";
import { fa, timeFa } from "../../api";
import { Badge, IconButton } from "../../shared/ui/primitives";
import type { Asset, Data, Incident } from "../../types";
import Map from "./OperationalMap";
import PatrolSafetyList from "./PatrolSafetyList";
import ProcessIncidentButton from "../incidents/ProcessIncidentButton";
import type { HazardDrawing } from "../geography/GisTools";
import type { Act } from "../../shared/lib/actions";
export default function CommandPage({
  data,
  theme,
  page,
  asset,
  selectedIncident,
  replay,
  playing,
  incidentFilter,
  filteredIncidents,
  openAsset,
  openIncident,
  go,
  setReplay,
  setPlaying,
  setIncidentFilter,
  setAssistant,
  presenting = false,
  act,
  busy,
  hazardDrawing,
}: {
  data: Data;
  theme: "dark" | "light";
  page: string;
  asset: Asset | null;
  selectedIncident: Incident | null;
  replay: number;
  playing: boolean;
  incidentFilter: string;
  filteredIncidents: Incident[];
  openAsset: (a: Asset) => void;
  openIncident: (i: Incident) => void;
  go: (s: string) => void;
  setReplay: (n: number) => void;
  setPlaying: (b: boolean) => void;
  setIncidentFilter: (s: string) => void;
  setAssistant: (b: boolean) => void;
  presenting?: boolean;
  act: Act;
  busy: boolean;
  hazardDrawing?: HazardDrawing;
}) {
  const [eventsOpen, setEventsOpen] = useState(() => window.innerWidth > 640);
  const isReplay = page === "replay";
  const trackPoints = data.assets.reduce((sum, item) => sum + (item.track?.length || 0), 0);
  const visibleIncidents = filteredIncidents.filter((item) => isReplay || item.status !== "closed");
  // The guided demo narrates incidents itself; give the map the full stage.
  useEffect(() => {
    if (presenting) setEventsOpen(false);
  }, [presenting]);
  return (
    <div className={isReplay ? "replay-workspace" : undefined}>
      {isReplay && <>
        <header className="replay-hero">
          <div className="replay-hero-copy">
            <span className="replay-kicker"><CalendarClock size={15}/> TEMPORAL OPERATIONS ARCHIVE</span>
            <h2>تاریخچه و بازپخش عملیات</h2>
            <p>مرور هماهنگ مسیر موجودیت‌ها و رخدادهای ثبت‌شده روی خط زمان عملیاتی</p>
          </div>
          <div className="replay-session-state"><span><i/> داده ثبت‌شده</span><b>{fa(replay)}٪</b><small>موقعیت خط زمان</small></div>
          <div className="replay-hero-orbit" aria-hidden="true"><Clock3 size={34}/><i/><i/></div>
        </header>
        <div className="replay-kpis">
          <article><span className="cyan"><Route size={17}/></span><div><small>مسیرهای قابل بازپخش</small><b>{fa(data.assets.length)}</b><em>موجودیت ثبت‌شده</em></div></article>
          <article><span className="green"><Database size={17}/></span><div><small>نقاط موقعیت</small><b>{fa(trackPoints)}</b><em>نمونه زمانی</em></div></article>
          <article><span className="violet"><Activity size={17}/></span><div><small>رخدادهای آرشیو</small><b>{fa(data.incidents.length)}</b><em>پرونده قابل بررسی</em></div></article>
          <article><span className="amber"><Clock3 size={17}/></span><div><small>وضعیت بازپخش</small><b>{playing ? "در حال پخش" : "متوقف"}</b><em>{fa(replay)} درصد مسیر</em></div></article>
        </div>
      </>}
      <div className="command-grid command-map-layout">
        <section className={`map-card ${isReplay ? "replay-map-card" : ""}`}>
          <div className="map-card-header">
            <div>
              <span className="live-dot" />
              <b>
                {isReplay
                  ? "بازپخش مسیرهای ثبت‌شده"
                  : "نقشه عملیات زنده"}
              </b>
              <span className="count-label">
                {fa(data.assets.length)} موجودیت
              </span>
            </div>
            <div className="map-scope">
              <MapPin size={14} /> آغاجاری · امیدیه · خوزستان
            </div>
            {!isReplay && !presenting && (
              <ProcessIncidentButton
                act={act}
                busy={busy}
                onCreated={openIncident}
              />
            )}
          </div>
          <Map
            command
            data={data}
            theme={theme}
            onAsset={openAsset}
            onIncident={openIncident}
            selected={asset?.id}
            focus={selectedIncident}
            replay={isReplay ? replay : 100}
            hazardDrawing={hazardDrawing}
          >
            {!presenting && !isReplay && (
              <PatrolSafetyList data={data} />
            )}
            <button
              className="floating-feed-toggle"
              aria-label="نمایش رخدادها"
              aria-expanded={eventsOpen}
              onClick={() => setEventsOpen(!eventsOpen)}
            >
              <Activity size={15} /> رخدادها{" "}
              <span>{fa(data.summary.open_incidents)}</span>
            </button>
            {eventsOpen && (
              <section className="floating-events" aria-label="رخدادهای شناور">
                <div className="event-panel-header">
                  <div>
                    <span className="eyebrow">PRIORITY FEED</span>
                    <h2>
                      {isReplay ? "رخدادهای ثبت‌شده" : "رخدادهای اولویت‌دار"}{" "}
                      <span>{fa(data.summary.open_incidents)}</span>
                    </h2>
                  </div>
                  <button
                    className="floating-close"
                    aria-label="جمع‌کردن رخدادها"
                    onClick={() => setEventsOpen(false)}
                  >
                    <X size={16} />
                  </button>
                </div>
                <div className="segmented">
                  <button
                    className={incidentFilter === "all" ? "selected" : ""}
                    onClick={() => setIncidentFilter("all")}
                  >
                    همه
                  </button>
                  <button
                    className={incidentFilter === "critical" ? "selected" : ""}
                    onClick={() => setIncidentFilter("critical")}
                  >
                    بحرانی
                  </button>
                  <button
                    className={incidentFilter === "high" ? "selected" : ""}
                    onClick={() => setIncidentFilter("high")}
                  >
                    زیاد
                  </button>
                </div>
                <div className="event-list">
                  {visibleIncidents.map((i) => (
                      <button
                        key={i.id}
                        className={`event-card ${i.severity} ${selectedIncident?.id === i.id ? "chosen" : ""}`}
                        onClick={() => openIncident(i)}
                      >
                        <div className="event-meta">
                          <Badge value={i.severity} />
                          <span>{timeFa(i.created_at)}</span>
                        </div>
                        <h3>{i.title}</h3>
                        <p>
                          <MapPin size={13} />
                          {i.zone}
                        </p>
                        <div className="event-footer">
                          <span dir="ltr">{i.id}</span>
                          <span>
                            بررسی حادثه <ChevronLeft size={13} />
                          </span>
                        </div>
                      </button>
                    ))}
                  {!visibleIncidents.length && (
                    <div className="empty">
                      رخداد بازی در این فیلتر وجود ندارد.
                    </div>
                  )}
                </div>
                <button
                  className="text-button event-more"
                  onClick={() => go("incidents")}
                >
                  مشاهده تمام پرونده‌ها <ChevronLeft size={15} />
                </button>
              </section>
            )}
          </Map>
          <div className="timeline-bar">
            <IconButton
              label={playing ? "توقف بازپخش" : "پخش مسیرها"}
              onClick={() => {
                go("replay");
                if (replay >= 100) setReplay(0);
                setPlaying(!playing);
              }}
            >
              {playing ? <Pause size={17} /> : <Play size={17} />}
            </IconButton>
            <div className="timeline-track">
              <div>
                <span>آغاز مسیر</span>
                <span>میانه مسیر</span>
                <span>آخرین موقعیت</span>
              </div>
              <input
                aria-label="زمان بازپخش"
                type="range"
                min="0"
                max="100"
                value={replay}
                onChange={(e) => {
                  go("replay");
                  setReplay(+e.target.value);
                }}
              />
            </div>
            <span className="time-pill">
              {isReplay ? `${fa(replay)}٪ مسیر` : "برخط"}
            </span>
          </div>
        </section>
      </div>
      <div className={`command-bottom ${isReplay ? "replay-bottom" : ""}`}>
        <div className="brief">
          <div className="spark-icon">
            <Sparkles size={22} />
          </div>
          <div>
            <h3>
              {isReplay ? "تحلیل بازه بازپخش" : "خلاصه وضعیت شیفت"} <span>دستیار نمایشی</span>
            </h3>
            <p>
              {isReplay ? `${fa(data.assets.length)} مسیر و ${fa(trackPoints)} نقطه موقعیت در این نمای زمانی قابل بررسی است.` : <>{fa(data.summary.online)} تجهیز متصل است. {fa(data.summary.open_incidents)} پرونده باز، برای بررسی و اقدام در صف قرار دارد.</>}
            </p>
          </div>
          <button className="text-button" onClick={() => setAssistant(true)}>
            بررسی با سپهر <ChevronLeft size={16} />
          </button>
        </div>
        <div className="shift-status">
          <Activity size={19} />
          <div>
            <strong>{isReplay ? "آرشیو عملیاتی" : "پایش فعال"}</strong>
            <small>{isReplay ? "نمایش داده ثبت‌شده بدون تغییر منبع" : "به‌روزرسانی اطلاعات هر ۳ ثانیه"}</small>
          </div>
          <span className="mini-bars">▂▅▃▇▅▃</span>
        </div>
      </div>
    </div>
  );
}
