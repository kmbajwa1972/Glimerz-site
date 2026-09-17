import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SB_URL")!;
const SERVICE_ROLE = Deno.env.get("SB_SERVICE_ROLE_KEY")!;
const supabase = createClient(SUPABASE_URL, SERVICE_ROLE);

export type TikTokContentItem = {
  id: string;
  title: string | null;
  body: string | null;
  media_urls: string[] | null;
  target_url: string | null;
};

async function getToken() {
  const { data, error } = await supabase.from("platform_tokens").select("*").eq("platform", "tiktok").single();
  if (error || !data) throw new Error("No TikTok token stored in platform_tokens.");
  let accessToken = data.access_token as string;
  const expiresAt = data.expires_at ? new Date(data.expires_at).getTime() : 0;
  if (!expiresAt || expiresAt > Date.now() + 10 * 60 * 1000) return { accessToken, openId: (data.config as Record<string, unknown>)?.open_id as string | undefined };
  if (!data.refresh_token) throw new Error("TikTok access token expired and no refresh token is stored.");

  const clientKey = Deno.env.get("TIKTOK_CLIENT_KEY")!;
  const clientSecret = Deno.env.get("TIKTOK_CLIENT_SECRET")!;
  const resp = await fetch("https://open.tiktokapis.com/v2/oauth/token/", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", "cache-control": "no-cache" },
    body: new URLSearchParams({ client_key: clientKey, client_secret: clientSecret, grant_type: "refresh_token", refresh_token: data.refresh_token }),
  });
  const refreshed = await resp.json();
  if (!resp.ok || refreshed.error) throw new Error(`TikTok token refresh failed: ${refreshed.error ?? resp.status} ${refreshed.error_description ?? ""}`);

  const newExpiresAt = new Date(Date.now() + Number(refreshed.expires_in ?? 86400) * 1000).toISOString();
  const config = { ...(data.config as Record<string, unknown> ?? {}), open_id: refreshed.open_id, scope: refreshed.scope, token_type: refreshed.token_type, refresh_expires_in: refreshed.refresh_expires_in };
  const update = await supabase.from("platform_tokens").update({ access_token: refreshed.access_token, refresh_token: refreshed.refresh_token ?? data.refresh_token, expires_at: newExpiresAt, config, updated_at: new Date().toISOString() }).eq("platform", "tiktok");
  if (update.error) throw new Error(`TikTok token refresh was successful but could not be saved: ${update.error.message}`);
  accessToken = refreshed.access_token;
  return { accessToken, openId: refreshed.open_id as string | undefined };
}

export async function publishTikTokPhoto(item: TikTokContentItem): Promise<string> {
  const imageUrl = item.media_urls?.[0];
  if (!imageUrl) throw new Error("No image URL available for TikTok photo post.");

  const { accessToken } = await getToken();
  const creatorResp = await fetch("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "content-type": "application/json; charset=UTF-8" },
    body: "{}",
  });
  const creator = await creatorResp.json();
  if (!creatorResp.ok || creator.error?.code !== "ok") throw new Error(`TikTok creator info failed: ${creator.error?.message ?? creatorResp.status}`);

  const options = creator.data?.privacy_level_options ?? [];
  const requested = Deno.env.get("TIKTOK_PRIVACY_LEVEL") ?? "SELF_ONLY";
  const privacy = options.includes(requested) ? requested : options.includes("SELF_ONLY") ? "SELF_ONLY" : options[0];
  if (!privacy) throw new Error("TikTok did not return a usable privacy level.");

  const title = (item.title ?? "Glimerz").slice(0, 90);
  const description = (item.body ?? item.target_url ?? "").slice(0, 4000);
  const resp = await fetch("https://open.tiktokapis.com/v2/post/publish/content/init/", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "content-type": "application/json; charset=UTF-8" },
    body: JSON.stringify({
      post_info: {
        title,
        description,
        privacy_level: privacy,
        disable_comment: false,
        auto_add_music: true,
        brand_organic_toggle: true,
      },
      source_info: { source: "PULL_FROM_URL", photo_cover_index: 0, photo_images: [imageUrl] },
      post_mode: "DIRECT_POST",
      media_type: "PHOTO",
    }),
  });
  const result = await resp.json();
  if (!resp.ok || result.error?.code !== "ok") throw new Error(`TikTok photo publish failed: ${result.error?.code ?? resp.status} ${result.error?.message ?? ""}`);
  return result.data.publish_id as string;
}
