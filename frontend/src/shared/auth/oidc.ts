// Minimal OIDC Authorization Code + PKCE (S256) client with fetch and Web Crypto.
// Tokens stay in memory only. The one-time verifier, state and nonce survive the
// redirect in sessionStorage and are removed as soon as the callback is handled.
type Discovery = {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
};
export type Tokens = { access_token: string; refresh_token?: string; id_token?: string; expires_in?: number };
const PENDING = "sepehr-oidc-pending";
const base64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const random = (size = 32) => base64url(crypto.getRandomValues(new Uint8Array(size)));
async function discover(issuer: string): Promise<Discovery> {
  const response = await fetch(issuer.replace(/\/$/, "") + "/.well-known/openid-configuration");
  if (!response.ok) throw new Error("پیکربندی سرویس هویت در دسترس نیست");
  return response.json();
}
export const redirectUri = () => location.origin + "/auth/callback";
export async function login(issuer: string, clientId: string, returnHash: string) {
  const config = await discover(issuer);
  const verifier = random(48);
  const challenge = base64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
  const state = random();
  const nonce = random();
  sessionStorage.setItem(PENDING, JSON.stringify({ verifier, state, nonce, issuer, clientId, returnHash }));
  const url = new URL(config.authorization_endpoint);
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri(),
    scope: "openid",
    state,
    nonce,
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();
  location.assign(url.toString());
}
function decodeNonce(idToken?: string) {
  try {
    return idToken ? JSON.parse(atob(idToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).nonce : undefined;
  } catch {
    return undefined;
  }
}
export async function completeLogin(): Promise<{ tokens: Tokens; issuer: string; clientId: string; returnHash: string } | null> {
  if (location.pathname !== "/auth/callback") return null;
  const params = new URLSearchParams(location.search);
  const pending = JSON.parse(sessionStorage.getItem(PENDING) || "null");
  sessionStorage.removeItem(PENDING);
  history.replaceState(null, "", "/" + (pending?.returnHash || ""));
  if (!pending || params.get("state") !== pending.state || !params.get("code")) throw new Error("پاسخ ورود معتبر نیست؛ دوباره وارد شوید");
  const config = await discover(pending.issuer);
  const response = await fetch(config.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: params.get("code")!,
      redirect_uri: redirectUri(),
      client_id: pending.clientId,
      code_verifier: pending.verifier,
    }),
  });
  if (!response.ok) throw new Error("تبادل کد ورود ناموفق بود");
  const tokens: Tokens = await response.json();
  if (decodeNonce(tokens.id_token) !== pending.nonce) throw new Error("nonce ورود معتبر نیست");
  return { tokens, issuer: pending.issuer, clientId: pending.clientId, returnHash: pending.returnHash };
}
export async function refresh(issuer: string, clientId: string, refreshToken: string): Promise<Tokens> {
  const config = await discover(issuer);
  const response = await fetch(config.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refreshToken, client_id: clientId }),
  });
  if (!response.ok) throw new Error("نشست منقضی شده است؛ دوباره وارد شوید");
  return response.json();
}
export async function logout(issuer: string, clientId: string, idToken?: string) {
  const config = await discover(issuer);
  if (!config.end_session_endpoint) return;
  const url = new URL(config.end_session_endpoint);
  url.search = new URLSearchParams({
    client_id: clientId,
    post_logout_redirect_uri: location.origin + "/",
    ...(idToken ? { id_token_hint: idToken } : {}),
  }).toString();
  location.assign(url.toString());
}
