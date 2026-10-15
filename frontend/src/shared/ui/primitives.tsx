import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { labels } from "../../api";
export function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value}`}>
      <i />
      {labels[value] || value}
    </span>
  );
}
export function IconButton({
  children,
  label,
  onClick,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className="icon-button"
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className={wide ? "modal wide" : "modal"}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <header>
        <div>
          <span className="eyebrow">SEPEHR / OPERATIONS</span>
          <h2 id={titleId}>{title}</h2>
        </div>
        <IconButton label="بستن" onClick={onClose}>
          <X size={20} />
        </IconButton>
      </header>
      {children}
    </dialog>
  );
}
export function PanelTitle({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children?: ReactNode;
}) {
  return (
    <div className="panel-title">
      <div>
        <h2>{title}</h2>
        {sub && <p>{sub}</p>}
      </div>
      {children}
    </div>
  );
}
export type StatItem = { label: string; value: ReactNode; note?: ReactNode; tone?: "danger" | "warn" | "ok" };
/** One flat row of key figures; replaces per-page KPI cards. */
export function StatStrip({ items }: { items: StatItem[] }) {
  return (
    <dl className="stat-strip">
      {items.map((item) => (
        <div key={item.label} className={item.tone}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.note && <small>{item.note}</small>}
        </div>
      ))}
    </dl>
  );
}
