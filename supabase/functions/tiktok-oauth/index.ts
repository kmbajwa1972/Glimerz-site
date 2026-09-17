import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SB_URL")!;
const SERVICE_ROLE = Deno.env.get("SB_SERVICE_ROLE_KEY")!;
const CLIENT_KEY = Deno.env.get("TIKTOK_CLIENT_KEY")!;
const CLIENT_SECRET = Deno.env.get("TIKTOK_CLIENT_SECRET")!;
const STATE_SECRET = Deno.env.get("TIKTOK_OAUTH_STATE_SECRET")!;
const REDIRECT_URI = Deno.env.get("TIKTOK_REDIRECT_URI") ?? `${SUPABASE_URL}/functions/v1/tiktok-oauth/callback`;
const SCOPES = Deno.env.get("TIKTOK_SCOPES") ?? "user.info.basic,video.publish";
const supabase = createClient(SUPABASE_URL, SERVICE_ROLE);

const enc = new TextEncoder();
function b64url(bytes: Uint8Array) { return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
function unb64url(s: string) { const p = s.replace(/-/g, "+").replace(/_/g, "/"); return Uint8Array.from(atob(p + "=".repeat((4 - p.length % 4) % 4)), c => c.charCodeAt(0)); }
async function hmac(value: string) {
  const key = await crypto.subtle.importKey("raw", enc.encode(STATE_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(value)));
}
async function makeState() {
  const payload = `${Date.now()}.${crypto.randomUUID()}`;
  return `${b64url(enc.encode(payload))}.${b64url(await hmac(payload))}`;
}
async function verifyState(state: string) {
  const [p, sig] = state.split(".");
  if (!p || !sig) return false;
  const payload = new TextDecoder().decode(unb64url(p));
  const [ts] = payload.split(".");
  if (!ts || Date.now() - Number(ts) > 10 * 60 * 1000 || Number(ts) > Date.now() + 60_000) return false;
  const expected = await hmac(payload);
  const actual = unb64url(sig);
  if (actual.length !== expected.length) return false;
  let diff = 0; for (let i = 0; i < actual.length; i++) diff |= actual[i] ^ expected[i];
  return diff === 0;
}
function html(title: string, body: string, status = 200) { return new Response(`<!doctype html><meta charset="utf-8"><title>${title}</title><style>body{font-family:Arial;max-width:720px;margin:60px auto;padding:20px}code{word-break:break-all}</style><h1>${title}</h1><p>${body}</p>`, { status, headers: { "content-type": "text/html; charset=utf-8" } }); }

Deno.serve(async (req) => {
  const url = new URL(req.url);
  if (url.pathname.endsWith("/authorize") || url.pathname.endsWith("/authorize/")) {
    if (!STATE_SECRET || !CLIENT_KEY || !CLIENT_SECRET) return html("TikTok OAuth not configured", "Required TikTok secrets are missing.", 500);
    const state = await makeState();
    const auth = new URL("https://www.tiktok.com/v2/auth/authorize/");
    auth.searchParams.set("client_key", CLIENT_KEY);
    auth.searchParams.set("response_type", "code");
    auth.searchParams.set("scope", SCOPES);
    auth.searchParams.set("redirect_uri", REDIRECT_URI);
    auth.searchParams.set("state", state);
    return Response.redirect(auth.toString(), 302);
  }

  if (!(url.pathname.endsWith("/callback") || url.pathname.endsWith("/callback/"))) return html("TikTok OAuth", `Use <a href="${url.origin}${url.pathname.replace(/\/$/, "")}/authorize">Connect TikTok</a>.`);
  const error = url.searchParams.get("error");
  if (error) return html("TikTok authorization failed", `${error}: ${url.searchParams.get("error_description") ?? "authorization was denied"}`, 400);
  const state = url.searchParams.get("state") ?? "";
  if (!(await verifyState(state))) return html("Invalid OAuth state", "The authorization request could not be verified. Start again.", 400);
  const code = url.searchParams.get("code");
  if (!code) return html("Missing authorization code", "TikTok did not return an authorization code.", 400);

  const tokenResp = await fetch("https://open.tiktokapis.com/v2/oauth/token/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", "cache-control": "no-cache" }, body: new URLSearchParams({ client_key: CLIENT_KEY, client_secret: CLIENT_SECRET, code, grant_type: "authorization_code", redirect_uri: REDIRECT_URI }) });
  const token = await tokenResp.json();
  if (!tokenResp.ok || token.error) return html("TikTok token exchange failed", `${token.error ?? tokenResp.status}: ${token.error_description ?? "token exchange failed"}`, 502);

  const expiresAt = new Date(Date.now() + Number(token.expires_in ?? 86400) * 1000).toISOString();
  const config = { open_id: token.open_id, scope: token.scope, token_type: token.token_type, refresh_expires_in: token.refresh_expires_in };
  const { data: existing } = await supabase.from("platform_tokens").select("platform").eq("platform", "tiktok").maybeSingle();
  const row = { platform: "tiktok", access_token: token.access_token, refresh_token: token.refresh_token, expires_at: expiresAt, config, updated_at: new Date().toISOString() };
  const db = existing ? await supabase.from("platform_tokens").update(row).eq("platform", "tiktok") : await supabase.from("platform_tokens").insert(row);
  if (db.error) return html("TikTok connected but not saved", db.error.message, 500);
  return html("TikTok connected", `Glimerz has stored the TikTok authorization securely in Supabase.<br><br>Token expires: ${expiresAt}`);
});
