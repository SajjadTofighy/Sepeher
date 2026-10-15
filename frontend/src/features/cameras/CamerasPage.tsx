import { useQuery } from "@tanstack/react-query";
import { Activity, Camera, Link2, MapPin, ScanLine, VideoOff } from "lucide-react";
import { api, fa } from "../../api";
import { Badge, StatStrip } from "../../shared/ui/primitives";
import type { Camera as CameraRecord } from "../../types";
export default function CamerasPage() {
  const q = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api<CameraRecord[]>("/cameras"),
  });
  const cameras = q.data || [];
  const online = cameras.filter((c) => c.status === "online").length;
  const offline = cameras.filter((c) => c.status === "offline").length;
  return (
    <section className="cameras-workspace">
      <StatStrip items={[
        { label: "کل دوربین‌ها", value: q.isPending ? "—" : fa(cameras.length) },
        { label: "برخط", value: q.isPending ? "—" : fa(online), tone: "ok" },
        { label: "قطع ارتباط", value: q.isPending ? "—" : fa(offline), tone: offline ? "danger" : undefined },
      ]} />
      <div className="camera-phase-banner">
        <Link2 size={21} />
        <div>
          <b>دوربین، یک حسگر در زنجیره فرماندهی</b>
          <p>
            فاز سوم · ورودی واقعی پلاک پس از فعال‌سازی با سیاست‌های حراست بررسی
            می‌شود. پخش ویدئو نیازمند اتصال سازمانی است.
          </p>
        </div>
        <span>PHASE 03</span>
      </div>
      {q.isPending ? (
        <div className="camera-loading"><span className="spin"><Activity size={22}/></span><div><b>در حال دریافت دوربین‌ها</b><small>همگام‌سازی وضعیت حسگرهای تصویری…</small></div></div>
      ) : q.isError ? (
        <div className="error-banner">
          دریافت دوربین‌ها ناموفق بود.{" "}
          <button onClick={() => q.refetch()}>تلاش مجدد</button>
        </div>
      ) : (
        <section className="camera-registry">
          <header className="camera-registry-head"><div className="registry-title"><b>دوربین‌ها</b><small>{fa(cameras.length)} مورد</small></div></header>
        <div className="camera-grid">
          {q.data.map((c) => (
            <article className={`camera-card ${c.status}`} key={c.id}>
              <header className="camera-card-head"><div><span className="camera-card-icon"><Camera size={17}/></span><div><b>{c.name}</b><small>{c.id} · {c.zone}</small></div></div>
                <Badge value={c.status} />
              </header>
              <div className="camera-view">
                <div className="camera-view-top">
                  <span>{c.id} / PREVIEW</span>
                  <span>موقعیت شماتیک</span>
                </div>
                {c.status === "offline" ? (
                  <VideoOff size={38} />
                ) : (
                  <Camera size={38} />
                )}
                <strong>
                  {c.status === "offline"
                    ? "ارتباط دوربین قطع است"
                    : "نمایشگر ورودی دوربین"}
                </strong>
                <p>
                  {c.status === "offline"
                    ? "وضعیت ثبت‌شده در مشخصات دوربین"
                    : "خوانش پلاک از ورودی مجاز دریافت می‌شود"}
                </p>
                <div className="camera-view-bottom">
                  <MapPin size={13} />
                  {c.zone}
                  <span>ویدئوی واقعی متصل نیست</span>
                </div>
              </div>
              <p className="camera-analysis">
                <ScanLine size={17} />
                تحلیل نمونه: {c.analysis}
              </p>
            </article>
          ))}
        </div>
        </section>
      )}
    </section>
  );
}
