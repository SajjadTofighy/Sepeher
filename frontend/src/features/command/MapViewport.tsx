import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize, Minimize } from "lucide-react";

export default function MapViewport({
  children,
  command = false,
}: {
  children: ReactNode;
  command?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [fallback, setFallback] = useState(false);
  useEffect(() => {
    const change = () =>
      setFullscreen(document.fullscreenElement === root.current);
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFallback(false);
    };
    document.addEventListener("fullscreenchange", change);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("fullscreenchange", change);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  useEffect(() => {
    if (!fallback) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [fallback]);
  const active = fullscreen || fallback;
  async function toggle() {
    if (fallback) return setFallback(false);
    if (fullscreen) {
      await document.exitFullscreen();
      return;
    }
    try {
      await root.current!.requestFullscreen();
    } catch {
      setFallback(true);
    }
  }
  return (
    <div
      ref={root}
      className={`map-viewport ${command ? "command-map-viewport" : ""} ${fallback ? "fullscreen-fallback" : ""}`}
      data-fullscreen={active}
    >
      {children}
      <button
        className="map-fullscreen"
        aria-label={active ? "خروج از تمام‌صفحه" : "نقشه تمام‌صفحه"}
        title={active ? "خروج از تمام‌صفحه" : "نقشه تمام‌صفحه"}
        onClick={() => void toggle()}
      >
        {active ? <Minimize size={18} /> : <Maximize size={18} />}
      </button>
    </div>
  );
}
