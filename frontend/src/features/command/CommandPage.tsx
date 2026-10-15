import { useEffect, useState } from "react";
import {
  Activity,
  X,
  ChevronLeft,
  MapPin,
  Pause,
  Play,
} from "lucide-react";
import { fa, timeFa } from "../../api";
import { Badge, IconButton, StatStrip } from "../../shared/ui/primitives";
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
        <StatStrip items={[
          { label: "مسیرهای قابل بازپخش", value: fa(data.assets.length) },
          { label: "نقاط موقعیت", value: fa(trackPoints) },
          { label: "رخدادهای آرشیو", value: fa(data.incidents.length) },
          { label: "موقعیت خط زمان", value: `${fa(replay)}٪` },
        ]} />
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
    </div>
  );
}
