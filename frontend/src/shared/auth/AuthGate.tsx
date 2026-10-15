import { LogIn, ShieldAlert, Smartphone } from "lucide-react";
import type { ReactNode } from "react";
import FieldApp from "../../features/field-comms/FieldApp";
import { isGuardOnly, useSession } from "./session";

// Every page carries the classification label; demo mode is always visibly marked.
function SessionBars() {
  const { config } = useSession();
  if (!config) return null;
  return (
    <div className="session-bars" role="status">
      <span className="classification-bar">{config.classification_label}</span>
      {config.mode === "demo" && <span className="demo-bar">حالت نمایشی · هویت و داده واقعی نیستند</span>}
    </div>
  );
}

function LoginScreen() {
  const session = useSession();
  const locked = session.status === "locked";
  return (
    <main className="login-screen">
      <section className="panel login-card">
        <img src="/new-logo.png" alt="" />
        <h1>سپهر حراست</h1>
        <p>{locked ? "به‌دلیل عدم فعالیت، نشست قفل شد. برای ادامه دوباره وارد شوید." : "ورود با حساب سازمانی از سرویس هویت داخلی (کیکلاک)."}</p>
        {session.error && <div className="error-banner">{session.error}</div>}
        <button className="primary field-touch" disabled={!session.config?.issuer} onClick={() => session.login("web")}>
          <LogIn size={18} />ورود به کنسول مرکز
        </button>
        <button className="secondary field-touch" disabled={!session.config?.issuer} onClick={() => session.login("field")}>
          <Smartphone size={18} />ورود نگهبان به اپ میدانی
        </button>
        {!session.config?.issuer && <p className="flag"><ShieldAlert size={14} /> سرویس هویت روی سرور تنظیم نشده است.</p>}
        <small className="muted">توکن فقط در حافظه همین صفحه نگه داشته می‌شود؛ با بستن صفحه، ورود دوباره از نشست کیکلاک انجام می‌شود.</small>
      </section>
    </main>
  );
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const session = useSession();
  let content: ReactNode = children;
  if (session.status === "loading") content = <main className="login-screen"><div className="panel login-card">در حال بررسی نشست…</div></main>;
  else if (session.status === "anonymous" || session.status === "locked") content = <LoginScreen />;
  // Guards never load the command console; the server denies its legacy data to them anyway.
  else if (session.status === "authenticated" && isGuardOnly(session.principal)) content = <main className="guard-shell"><FieldApp /></main>;
  return (
    <>
      {content}
      <SessionBars />
    </>
  );
}
