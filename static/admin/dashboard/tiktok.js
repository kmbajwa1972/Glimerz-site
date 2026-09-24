/*
  Glimerz dashboard – TikTok connect card + "Post to TikTok" screen.
  Talks to the deployed Edge Functions: tiktok-post (actions) and tiktok-oauth (login).

  Setup (once your Supabase client `supabase` exists and you're signed in):
    GlimerzTikTok.init({
      supabaseUrl: "https://yayljmqelmsmcsuhxqdj.supabase.co",
      anonKey: SUPABASE_ANON_KEY,
      getAccessToken: async () => (await supabase.auth.getSession()).data.session?.access_token,
      mount: "#tiktok-connect",
      onPublished: () => loadPending(),   // optional: refresh your lists
    });

  On each pending tiktok_video item:
    GlimerzTikTok.openPostDialog({ itemId: item.id, videoUrl: item.media_urls[0], caption: item.body });
*/
(function () {
  const PRIVACY_LABELS = { PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers", SELF_ONLY: "Only me" };
  const MUSIC_URL = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en";
  const BRANDED_URL = "https://www.tiktok.com/legal/page/global/bc-policy/en";

  let cfg = null;
  let account = null;

  const css = `
  .gtt{--gtt-bg:#fdfbf7;--gtt-panel:#ffffff;--gtt-line:#e5ddd0;--gtt-text:#2c2c2c;--gtt-dim:#7a7a7a;--gtt-go:#5f6e56;--gtt-err:#954632;color:var(--gtt-text);font:inherit}
  .gtt-card{display:flex;align-items:center;gap:14px;padding:14px 16px;border:1px solid var(--gtt-line);border-radius:12px;background:var(--gtt-panel)}
  .gtt-avatar{width:44px;height:44px;border-radius:50%;object-fit:cover;background:var(--gtt-line);flex:none}
  .gtt-grow{flex:1;min-width:0}
  .gtt-name{font-weight:600}
  .gtt-sub{color:var(--gtt-dim);font-size:.875rem;margin:0}
  .gtt button{font:inherit;cursor:pointer;border-radius:8px;padding:9px 16px;border:1px solid var(--gtt-line);background:transparent;color:var(--gtt-text)}
  .gtt button.gtt-primary{background:var(--gtt-go);border-color:var(--gtt-go);color:#fff;font-weight:600}
  .gtt button:disabled{opacity:.45;cursor:not-allowed}
  .gtt button:focus-visible,.gtt input:focus-visible,.gtt select:focus-visible,.gtt textarea:focus-visible{outline:2px solid var(--gtt-go);outline-offset:2px}
  dialog.gtt{width:min(720px,94vw);border:1px solid var(--gtt-line);border-radius:14px;padding:0;background:var(--gtt-bg)}
  dialog.gtt::backdrop{background:rgba(44,44,44,.45)}
  .gtt-head{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--gtt-line)}
  .gtt-head h2{margin:0;font-family:Georgia,serif;font-weight:400;font-size:1.2rem;flex:1}
  .gtt-body{display:grid;grid-template-columns:220px 1fr;gap:20px;padding:20px}
  @media (max-width:640px){.gtt-body{grid-template-columns:1fr}}
  .gtt video{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:10px;background:#000}
  .gtt label.gtt-field{display:block;margin-bottom:16px}
  .gtt-field>span{display:block;font-size:.875rem;color:var(--gtt-dim);margin-bottom:6px}
  .gtt textarea,.gtt select{width:100%;box-sizing:border-box;background:var(--gtt-panel);color:var(--gtt-text);border:1px solid var(--gtt-line);border-radius:8px;padding:9px 10px;font:inherit}
  .gtt textarea{min-height:90px;resize:vertical}
  .gtt fieldset{border:0;padding:0;margin:0 0 16px}
  .gtt legend{font-size:.875rem;color:var(--gtt-dim);margin-bottom:6px;padding:0}
  .gtt-checks{display:flex;gap:18px;flex-wrap:wrap}
  .gtt-check{display:flex;align-items:center;gap:8px}
  .gtt-check.is-off{opacity:.45}
  .gtt-note{font-size:.8125rem;color:var(--gtt-dim);margin:6px 0 0}
  .gtt-consent{font-size:.875rem;margin:4px 0 0;display:flex;gap:8px;align-items:flex-start}
  .gtt a{color:var(--gtt-go)}
  .gtt-foot{display:flex;gap:10px;justify-content:flex-end;align-items:center;padding:14px 20px;border-top:1px solid var(--gtt-line);flex-wrap:wrap}
  .gtt-msg{flex:1;min-width:200px;font-size:.875rem;color:var(--gtt-dim)}
  .gtt-msg.is-err{color:var(--gtt-err)}
  .gtt-msg.is-ok{color:var(--gtt-go)}
  .gtt-toast{position:fixed;right:20px;bottom:20px;z-index:9999;padding:12px 16px;border-radius:10px;background:var(--gtt-panel);border:1px solid var(--gtt-line)}
  `;

  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function toast(text) { const t = el(`<div class="gtt gtt-toast" role="status">${esc(text)}</div>`); document.body.appendChild(t); setTimeout(() => t.remove(), 5000); }

  async function call(action, extra) {
    const token = await cfg.getAccessToken();
    if (!token) throw new Error("Sign in to the dashboard first.");
    const res = await fetch(`${cfg.supabaseUrl}/functions/v1/tiktok-post`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, apikey: cfg.anonKey },
      body: JSON.stringify({ action, ...(extra || {}) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(data.error || `Request failed (${res.status})`); e.code = data.code; throw e; }
    return data;
  }

  // ---------- Connect card ----------
  async function renderCard() {
    const mount = document.querySelector(cfg.mount);
    if (!mount) return;
    mount.innerHTML = `<div class="gtt gtt-card"><p class="gtt-grow gtt-sub">Checking TikTok connection…</p></div>`;
    try { account = await call("account"); } catch (e) { account = { connected: false, error: e.message }; }

    if (account.connected) {
      mount.innerHTML = `
        <div class="gtt gtt-card">
          ${account.avatar_url ? `<img class="gtt-avatar" src="${esc(account.avatar_url)}" alt="">` : `<div class="gtt-avatar"></div>`}
          <div class="gtt-grow">
            <div class="gtt-name">${esc(account.nickname || "TikTok account")}</div>
            <p class="gtt-sub">${account.username ? "@" + esc(account.username) + " · " : ""}Connected to TikTok</p>
          </div>
          <button type="button" data-act="disconnect">Disconnect</button>
        </div>`;
      mount.querySelector('[data-act="disconnect"]').onclick = async (ev) => {
        if (!confirm("Disconnect TikTok? You'll need to connect again to post.")) return;
        ev.target.disabled = true;
        await call("disconnect").catch((e) => toast(e.message));
        renderCard();
      };
    } else {
      const sub = account.error ? esc(account.error)
        : account.reason === "reconnect" ? "Access expired. Connect again to keep posting."
        : "Connect your TikTok account to post approved videos.";
      mount.innerHTML = `
        <div class="gtt gtt-card">
          <div class="gtt-avatar"></div>
          <div class="gtt-grow"><div class="gtt-name">TikTok</div><p class="gtt-sub">${sub}</p></div>
          <button type="button" class="gtt-primary" data-act="connect">Connect TikTok</button>
        </div>`;
      mount.querySelector('[data-act="connect"]').onclick = async (ev) => {
        ev.target.disabled = true;
        try {
          const token = await cfg.getAccessToken();
          const res = await fetch(`${cfg.supabaseUrl}/functions/v1/tiktok-oauth/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, apikey: cfg.anonKey },
            body: "{}",
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok || !data.url) throw new Error(data.error || "Couldn't start TikTok login.");
          location.href = data.url;
        } catch (e) { toast(e.message); ev.target.disabled = false; }
      };
    }
  }

  // ---------- Post dialog ----------
  async function openPostDialog({ itemId, videoUrl, caption = "", onPublished }) {
    if (!account?.connected) { toast("Connect TikTok first."); return; }

    const d = el(`
      <dialog class="gtt" aria-labelledby="gtt-title">
        <div class="gtt-head">
          <img class="gtt-avatar" alt="" hidden>
          <h2 id="gtt-title">Post to TikTok</h2>
          <button type="button" data-act="close">Close</button>
        </div>
        <div class="gtt-body">
          <div>
            <video src="${esc(videoUrl)}" controls playsinline preload="metadata"></video>
            <p class="gtt-note" data-duration></p>
          </div>
          <div>
            <p class="gtt-sub" data-creator style="margin-bottom:14px">Loading your TikTok settings…</p>
            <label class="gtt-field"><span>Caption</span>
              <textarea maxlength="2200" data-caption>${esc(caption)}</textarea></label>
            <label class="gtt-field"><span>Who can view this video</span>
              <select data-privacy><option value="" selected disabled>Choose</option></select></label>
            <fieldset><legend>Allow users to</legend>
              <div class="gtt-checks">
                <label class="gtt-check" data-wrap="comment"><input type="checkbox" data-allow="comment"> Comment</label>
                <label class="gtt-check" data-wrap="duet"><input type="checkbox" data-allow="duet"> Duet</label>
                <label class="gtt-check" data-wrap="stitch"><input type="checkbox" data-allow="stitch"> Stitch</label>
              </div>
            </fieldset>
            <fieldset>
              <label class="gtt-check"><input type="checkbox" data-disclose> Disclose video content</label>
              <div data-disclose-opts hidden>
                <p class="gtt-note">Turn this on if the video promotes yourself, a third party, or both.</p>
                <div class="gtt-checks" style="margin-top:8px">
                  <label class="gtt-check"><input type="checkbox" data-brand-own> Your brand</label>
                  <label class="gtt-check"><input type="checkbox" data-brand-paid> Branded content</label>
                </div>
                <p class="gtt-note" data-label-note></p>
              </div>
            </fieldset>
            <p class="gtt-note" style="margin:0 0 12px">This video will be labeled as AI-generated on TikTok.</p>
            <label class="gtt-consent"><input type="checkbox" data-consent><span data-consent-text></span></label>
          </div>
        </div>
        <div class="gtt-foot">
          <span class="gtt-msg" data-msg aria-live="polite"></span>
          ${account.can_draft ? `<button type="button" data-act="draft">Send to TikTok as draft</button>` : ""}
          <button type="button" class="gtt-primary" data-act="post" disabled>Post</button>
        </div>
      </dialog>`);
    document.body.appendChild(d);
    d.showModal();
    d.addEventListener("close", () => d.remove());

    const $ = (s) => d.querySelector(s);
    const msg = (text, kind) => { const m = $("[data-msg]"); m.textContent = text; m.className = "gtt-msg" + (kind ? " is-" + kind : ""); };
    $('[data-act="close"]').onclick = () => d.close();

    let info = null, tooLong = false, busy = false, done = false;

    function refresh() {
      const disclose = $("[data-disclose]").checked;
      const own = $("[data-brand-own]").checked, paid = $("[data-brand-paid]").checked;
      $("[data-disclose-opts]").hidden = !disclose;

      const priv = $("[data-privacy]");
      const selfOpt = priv.querySelector('option[value="SELF_ONLY"]');
      if (selfOpt) {
        selfOpt.disabled = disclose && paid;
        selfOpt.textContent = selfOpt.disabled ? "Only me (not available for branded content)" : "Only me";
        if (selfOpt.disabled && priv.value === "SELF_ONLY") priv.value = "";
      }
      $("[data-label-note]").textContent = !disclose ? "" :
        paid ? "Your video will be labeled \u201cPaid partnership\u201d." :
        own ? "Your video will be labeled \u201cPromotional content\u201d." :
        "Choose Your brand, Branded content, or both.";
      $("[data-consent-text]").innerHTML = disclose && paid
        ? `By posting, you agree to TikTok's <a href="${BRANDED_URL}" target="_blank" rel="noopener">Branded Content Policy</a> and <a href="${MUSIC_URL}" target="_blank" rel="noopener">Music Usage Confirmation</a>.`
        : `By posting, you agree to TikTok's <a href="${MUSIC_URL}" target="_blank" rel="noopener">Music Usage Confirmation</a>.`;

      const ready = info && !busy && !done && !tooLong && priv.value && $("[data-consent]").checked && (!disclose || own || paid);
      $('[data-act="post"]').disabled = !ready;
      const dr = $('[data-act="draft"]'); if (dr) dr.disabled = !info || busy || done || tooLong;
    }
    d.addEventListener("change", refresh);
    d.addEventListener("input", refresh);
    refresh();

    // Fresh creator info every time the screen opens (TikTok requirement).
    try {
      info = await call("creator_info");
      const av = $(".gtt-head img");
      if (info.creator_avatar_url) { av.src = info.creator_avatar_url; av.hidden = false; }
      $("[data-creator]").textContent = `Posting to ${info.creator_nickname || "your account"}${info.creator_username ? " (@" + info.creator_username + ")" : ""}`;
      const priv = $("[data-privacy]");
      for (const v of info.privacy_level_options || []) priv.appendChild(new Option(PRIVACY_LABELS[v] || v, v));
      for (const k of ["comment", "duet", "stitch"]) {
        if (info[`${k}_disabled`]) {
          $(`[data-allow="${k}"]`).disabled = true;
          $(`[data-wrap="${k}"]`).classList.add("is-off");
          $(`[data-wrap="${k}"]`).title = "Turned off in your TikTok settings";
        }
      }
    } catch (e) {
      $("[data-creator]").textContent = "";
      msg(e.code === "spam_risk_too_many_posts" ? "TikTok says you've reached today's posting limit. Try again later." : e.message, "err");
      info = null;
    }

    const vid = $("video");
    const checkDuration = () => {
      if (!info || !vid.duration) return;
      const max = info.max_video_post_duration_sec;
      tooLong = !!max && vid.duration > max;
      $("[data-duration]").textContent = tooLong
        ? `This video is ${Math.round(vid.duration)}s. Your account can post up to ${max}s.`
        : `${Math.round(vid.duration)}s`;
      refresh();
    };
    vid.addEventListener("loadedmetadata", checkDuration);
    checkDuration();
    refresh();

    async function poll(publishId, doneText) {
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        let s;
        try { s = await call("status", { publish_id: publishId, item_id: itemId }); } catch { continue; }
        if (s.status === "PUBLISH_COMPLETE" || s.status === "SEND_TO_USER_INBOX") { msg(doneText, "ok"); return; }
        if (s.status === "FAILED") { msg(`TikTok couldn't process the video: ${s.fail_reason || "unknown reason"}`, "err"); return; }
        msg("TikTok is processing the video…");
      }
      msg("Still processing. Check your TikTok profile in a few minutes.");
    }

    $('[data-act="post"]').onclick = async () => {
      busy = true; refresh(); msg("Uploading to TikTok…");
      const disclose = $("[data-disclose]").checked;
      try {
        const { publish_id } = await call("post", {
          item_id: itemId,
          caption: $("[data-caption]").value,
          privacy_level: $("[data-privacy]").value,
          disable_comment: !$('[data-allow="comment"]').checked,
          disable_duet: !$('[data-allow="duet"]').checked,
          disable_stitch: !$('[data-allow="stitch"]').checked,
          brand_organic_toggle: disclose && $("[data-brand-own]").checked,
          brand_content_toggle: disclose && $("[data-brand-paid]").checked,
          consent: $("[data-consent]").checked,
        });
        done = true; busy = false; refresh();
        msg("Uploaded. TikTok is processing the video…");
        onPublished?.(); cfg.onPublished?.();
        await poll(publish_id, "Posted to TikTok. It may take a few minutes to appear on your profile.");
      } catch (e) { busy = false; refresh(); msg(e.message, "err"); }
    };

    const draftBtn = $('[data-act="draft"]');
    if (draftBtn) draftBtn.onclick = async () => {
      busy = true; refresh(); msg("Sending to TikTok…");
      try {
        const { publish_id } = await call("draft", { item_id: itemId });
        done = true; busy = false; refresh();
        await poll(publish_id, "Sent. Open the TikTok app and check your inbox to finish posting.");
      } catch (e) { busy = false; refresh(); msg(e.message, "err"); }
    };
  }

  function init(options) {
    cfg = { mount: "#tiktok-connect", ...options };
    if (!document.getElementById("gtt-style")) {
      const s = document.createElement("style"); s.id = "gtt-style"; s.textContent = css; document.head.appendChild(s);
    }
    handleReturn();
    return renderCard();
  }

  // Message after TikTok sends you back to the dashboard.
  function handleReturn() {
    const p = new URLSearchParams(location.search);
    const r = p.get("tiktok");
    if (!r) return;
    toast(r === "connected" ? "TikTok connected." : `TikTok connection failed: ${p.get("tiktok_message") || "unknown error"}`);
    p.delete("tiktok"); p.delete("tiktok_message");
    history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : "") + location.hash);
  }

  window.GlimerzTikTok = { init, openPostDialog, refresh: () => renderCard() };
})();
