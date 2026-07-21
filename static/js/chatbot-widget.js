/* Glimerz chatbot widget — floating avatar bubble that expands into a
 * chat panel. Loaded on every page via footer.html.
 *
 * Config: fill in CHATBOT_FUNCTION_URL below with your deployed
 * chatbot Edge Function URL before this goes live.
 */
(function () {
  const CHATBOT_FUNCTION_URL = "https://yayljmqelmsmcsuhxqdj.supabase.co/functions/v1/chatbot";
  const CHATBOT_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlheWxqbXFlbG1zbWNzdWh4cWRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM3ODUyOTMsImV4cCI6MjA5OTM2MTI5M30.XITDKls3bKtsXVssJuGQvy8iE4gwl2VtDF1F3dbrDcs"; // same anon key used in the dashboard — safe to expose client-side

  const COLORS = {
    cream: "#fdfbf7",
    surface: "#ffffff",
    border: "#e5ddd0",
    ink: "#2c2c2c",
    muted: "#7a7a7a",
    gold: "#aa8453",
    goldDeep: "#8a6a41",
  };

  // ---------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------
  const style = document.createElement("style");
  style.textContent = `
    #glimerz-chat-bubble {
      position: fixed;
      bottom: 22px;
      right: 22px;
      width: 58px;
      height: 58px;
      border-radius: 50%;
      background: ${COLORS.gold};
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(44,44,44,0.18);
      z-index: 999998;
      transition: transform 0.15s ease, background 0.15s ease;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    #glimerz-chat-bubble:hover { background: ${COLORS.goldDeep}; transform: scale(1.05); }
    #glimerz-chat-bubble svg { width: 26px; height: 26px; }

    #glimerz-chat-panel {
      position: fixed;
      bottom: 92px;
      right: 22px;
      width: 340px;
      max-width: calc(100vw - 32px);
      height: 460px;
      max-height: calc(100vh - 140px);
      background: ${COLORS.cream};
      border: 1px solid ${COLORS.border};
      border-radius: 10px;
      box-shadow: 0 10px 40px rgba(44,44,44,0.22);
      display: none;
      flex-direction: column;
      overflow: hidden;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    #glimerz-chat-panel.open { display: flex; }

    #glimerz-chat-header {
      background: ${COLORS.surface};
      border-bottom: 1px solid ${COLORS.border};
      padding: 14px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    #glimerz-chat-header .title {
      font-family: Georgia, serif;
      color: ${COLORS.gold};
      font-size: 1.05rem;
    }
    #glimerz-chat-header .sub {
      color: ${COLORS.muted};
      font-size: 0.72rem;
      font-style: italic;
    }
    #glimerz-chat-close {
      background: none;
      border: none;
      color: ${COLORS.muted};
      font-size: 1.2rem;
      cursor: pointer;
      line-height: 1;
      padding: 4px;
    }
    #glimerz-chat-close:hover { color: ${COLORS.ink}; }

    #glimerz-chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .glimerz-msg {
      max-width: 85%;
      padding: 9px 12px;
      border-radius: 12px;
      font-size: 0.87rem;
      line-height: 1.45;
    }
    .glimerz-msg.user {
      align-self: flex-end;
      background: ${COLORS.gold};
      color: #fff;
      border-bottom-right-radius: 3px;
    }
    .glimerz-msg.assistant {
      align-self: flex-start;
      background: ${COLORS.surface};
      border: 1px solid ${COLORS.border};
      color: ${COLORS.ink};
      border-bottom-left-radius: 3px;
    }
    .glimerz-msg.typing { color: ${COLORS.muted}; font-style: italic; }

    .glimerz-product-card {
      align-self: flex-start;
      max-width: 85%;
      background: ${COLORS.surface};
      border: 1px solid ${COLORS.border};
      border-radius: 8px;
      overflow: hidden;
      text-decoration: none;
      color: ${COLORS.ink};
      display: block;
    }
    .glimerz-product-card img {
      width: 100%;
      height: 110px;
      object-fit: cover;
      display: block;
    }
    .glimerz-product-card .name {
      padding: 8px 10px;
      font-size: 0.8rem;
      line-height: 1.35;
    }
    .glimerz-product-card .cta {
      padding: 0 10px 8px;
      font-size: 0.72rem;
      color: ${COLORS.gold};
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    #glimerz-chat-input-row {
      display: flex;
      border-top: 1px solid ${COLORS.border};
      background: ${COLORS.surface};
    }
    #glimerz-chat-input {
      flex: 1;
      border: none;
      padding: 12px 14px;
      font-size: 0.87rem;
      background: transparent;
      color: ${COLORS.ink};
      font-family: inherit;
    }
    #glimerz-chat-input:focus { outline: none; }
    #glimerz-chat-send {
      border: none;
      background: transparent;
      color: ${COLORS.gold};
      padding: 0 16px;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 600;
    }
    #glimerz-chat-send:hover { color: ${COLORS.goldDeep}; }
    #glimerz-chat-send:disabled { color: ${COLORS.muted}; cursor: default; }

    @media (max-width: 420px) {
      #glimerz-chat-panel { right: 16px; left: 16px; width: auto; bottom: 84px; }
      #glimerz-chat-bubble { right: 16px; bottom: 16px; }
    }
  `;
  document.head.appendChild(style);

  // ---------------------------------------------------------------
  // Markup
  // ---------------------------------------------------------------
  const bubble = document.createElement("div");
  bubble.id = "glimerz-chat-bubble";
  bubble.setAttribute("role", "button");
  bubble.setAttribute("aria-label", "Open chat");
  bubble.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>`;

  const panel = document.createElement("div");
  panel.id = "glimerz-chat-panel";
  panel.innerHTML = `
    <div id="glimerz-chat-header">
      <div>
        <div class="title">Glimerz</div>
        <div class="sub">Ask me about home & kitchen ideas</div>
      </div>
      <button id="glimerz-chat-close" aria-label="Close chat">&times;</button>
    </div>
    <div id="glimerz-chat-messages"></div>
    <div id="glimerz-chat-input-row">
      <input id="glimerz-chat-input" type="text" placeholder="Ask about decor, kitchen ideas…" autocomplete="off" />
      <button id="glimerz-chat-send">Send</button>
    </div>
  `;

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  const messagesEl = panel.querySelector("#glimerz-chat-messages");
  const inputEl = panel.querySelector("#glimerz-chat-input");
  const sendBtn = panel.querySelector("#glimerz-chat-send");
  const closeBtn = panel.querySelector("#glimerz-chat-close");

  let history = [];
  let opened = false;

  function addMessage(role, text) {
    const el = document.createElement("div");
    el.className = `glimerz-msg ${role}`;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function addProductCard(product) {
    const a = document.createElement("a");
    a.className = "glimerz-product-card";
    a.href = product.affiliate_link || product.source_post_url || "#";
    a.target = "_blank";
    a.rel = "noopener sponsored";
    a.innerHTML = `
      ${product.photo ? `<img src="${escapeAttr(product.photo)}" alt="" loading="lazy" />` : ""}
      <div class="name">${escapeHtml(product.product_name)}</div>
      <div class="cta">View on Amazon →</div>
    `;
    messagesEl.appendChild(a);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
  }
  function escapeAttr(str) {
    return (str ?? "").replace(/"/g, "&quot;");
  }

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    inputEl.value = "";
    sendBtn.disabled = true;
    addMessage("user", text);

    const typingEl = addMessage("assistant typing", "Thinking…");

    try {
      const resp = await fetch(CHATBOT_FUNCTION_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "authorization": `Bearer ${CHATBOT_ANON_KEY}`,
        },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await resp.json();

      typingEl.remove();

      if (!resp.ok || data.error) {
        addMessage("assistant", "Sorry, something went wrong on my end. Please try again in a moment.");
        sendBtn.disabled = false;
        return;
      }

      addMessage("assistant", data.reply);
      history.push({ role: "user", content: text });
      history.push({ role: "assistant", content: data.reply });

      // Keep history from growing unbounded across a long session.
      if (history.length > 12) history = history.slice(-12);

      (data.products || []).forEach(addProductCard);
    } catch (e) {
      typingEl.remove();
      addMessage("assistant", "Sorry, I couldn't connect just now. Please try again.");
    }

    sendBtn.disabled = false;
    inputEl.focus();
  }

  bubble.addEventListener("click", () => {
    opened = !opened;
    panel.classList.toggle("open", opened);
    if (opened && messagesEl.children.length === 0) {
      addMessage("assistant", "Hi! I'm the Glimerz assistant — ask me about home decor or kitchen ideas, and I'll point you to the right pieces.");
    }
    if (opened) inputEl.focus();
  });

  closeBtn.addEventListener("click", () => {
    opened = false;
    panel.classList.remove("open");
  });

  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendMessage();
  });
})();
