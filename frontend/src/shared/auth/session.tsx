import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, setAuthToken, UNAUTHORIZED_EVENT } from "../../api";
import type { AuthConfiguration, Principal } from "../../types";
import { completeLogin, login as startLogin, logout as endSession, refresh, type Tokens } from "./oidc";

// Authentication state only; server data stays in TanStack Query.
export type SessionStatus = "loading" | "demo" | "anonymous" | "locked" | "authenticated";
type Session = {
  status: SessionStatus;
  config?: AuthConfiguration;
  principal?: Principal;
  clientId?: string;
  error: string;
  login: (client: "web" | "field") => void;
  logout: () => void;
  unlock: () => void;
};

// Pilot evidence: token refreshes since the last field capability report, in memory only.
export const refreshCounters = { ok: 0, failed: 0 };
const SessionContext = createContext<Session | null>(null);
const STAFF = ["shift_supervisor", "security_officer", "security_manager", "admin", "auditor"];
export const isGuardOnly = (principal?: Principal) =>
  !!principal && principal.roles.includes("guard") && !principal.roles.some((role) => STAFF.includes(role));

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [tokens, setTokens] = useState<Tokens | null>(null);
  const [clientId, setClientId] = useState<string>();
  const [error, setError] = useState("");
  const [locked, setLocked] = useState(false);
  const [callbackDone, setCallbackDone] = useState(location.pathname !== "/auth/callback");
  const activity = useRef(Date.now());
  // Bumped whenever a session ends, so a token refresh still in flight can never revive it.
  const generation = useRef(0);
  const config = useQuery({ queryKey: ["auth", "config"], queryFn: () => api<AuthConfiguration>("/auth/config"), staleTime: Infinity });

  const clear = useCallback((message = "") => {
    generation.current += 1;
    setAuthToken(undefined);
    setTokens(null);
    setError(message);
    client.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" || q.queryKey[1] === "me" });
  }, [client]);

  useEffect(() => {
    completeLogin()
      .then((result) => {
        if (result) {
          setAuthToken(result.tokens.access_token);
          setTokens(result.tokens);
          setClientId(result.clientId);
          activity.current = Date.now();
        }
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setCallbackDone(true));
  }, []);

  useEffect(() => {
    const expired = () => { if (tokens) clear("نشست منقضی شده یا دسترسی رد شد؛ دوباره وارد شوید"); };
    window.addEventListener(UNAUTHORIZED_EVENT, expired);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, expired);
  }, [tokens, clear]);

  useEffect(() => {
    if (!tokens?.refresh_token || !config.data?.issuer || !clientId) return;
    const timer = setTimeout(() => {
      const started = generation.current;
      refresh(config.data!.issuer, clientId, tokens.refresh_token!)
        .then((next) => {
          refreshCounters.ok += 1;
          if (generation.current !== started) return;
          setAuthToken(next.access_token);
          setTokens(next);
        })
        .catch((e) => { refreshCounters.failed += 1; if (generation.current === started) clear((e as Error).message); });
    }, Math.max(15, (tokens.expires_in || 300) - 30) * 1000);
    return () => clearTimeout(timer);
  }, [tokens, config.data, clientId, clear]);

  useEffect(() => {
    // Idle lock: tokens leave memory; re-entry uses the Keycloak SSO session or a new login.
    if (!tokens || !config.data) return;
    const touch = () => { activity.current = Date.now(); };
    const events = ["pointerdown", "keydown", "touchstart"] as const;
    events.forEach((name) => window.addEventListener(name, touch, { passive: true }));
    const timer = setInterval(() => {
      if (Date.now() - activity.current >= config.data!.idle_seconds * 1000) {
        clear();
        setLocked(true);
      }
    }, 5000);
    return () => { events.forEach((name) => window.removeEventListener(name, touch)); clearInterval(timer); };
  }, [tokens, config.data, clear]);

  const principal = useQuery({
    // Keyed by session, not token, so a silent refresh never blanks the app.
    queryKey: ["auth", "me"],
    queryFn: () => api<Principal>("/auth/me"),
    enabled: !!tokens,
    staleTime: Infinity,
  });

  const login = useCallback((kind: "web" | "field") => {
    if (!config.data?.issuer) { setError("سرویس هویت در سرور تنظیم نشده است"); return; }
    const id = kind === "field" ? config.data.field_client_id || "sepehr-field" : config.data.client_id;
    startLogin(config.data.issuer, id, kind === "field" ? "#field" : location.hash || "#command").catch((e) => setError((e as Error).message));
  }, [config.data]);

  const logout = useCallback(() => {
    const idToken = tokens?.id_token;
    const id = clientId;
    clear();
    setLocked(false);
    if (config.data?.issuer && id) endSession(config.data.issuer, id, idToken).catch(() => undefined);
  }, [tokens, clientId, config.data, clear]);

  const status: SessionStatus = !config.data || !callbackDone || (tokens && principal.isPending)
    ? "loading"
    : tokens && principal.data ? "authenticated"
    : config.data.mode === "demo" ? "demo"
    : locked ? "locked" : "anonymous";

  const value = useMemo<Session>(() => ({
    status, config: config.data, principal: tokens ? principal.data : undefined, clientId, error,
    login, logout, unlock: () => setLocked(false),
  }), [status, config.data, principal.data, tokens, clientId, error, login, logout]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is missing");
  return session;
}
