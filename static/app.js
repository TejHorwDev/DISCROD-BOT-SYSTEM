/* ==========================================================================
   SELLER BOT - static/app.js
   ==========================================================================
   The whole dashboard, in plain JavaScript (no frameworks). It is split
   into clearly labeled parts so a beginner can find their way around:

     PART 1  Tiny helpers, app state, constants (colors, bullets, presets)
     PART 2  Fancy text (Unicode styles, straight from the server's list)
     PART 3  Discord markdown renderer (for the live preview) - XSS-safe
     PART 4  The content model: the form as data (the SERVER builds the
             actual Discord payload - renderer.py is the single truth)
     PART 5  The live preview panel: fetches /api/preview and shows the
             exact payloads the server will send + pre-flight checks
     PART 6  The form: loading it, saving it, pricing plans, image slots
     PART 7  Sending: real send, test send, Ctrl+Enter, Copy JSON,
             editing a message that was already sent
     PART 8  Product library tab
     PART 9  History tab + one-click actions (sold out, restock, price...)
     PART 10 Schedules tab
     PART 11 Settings tab + destination pickers + tabs + start-up
     PART 12 Multi-bot: registry, header switcher, Bots page, add wizard
     PART 13 Sections (the Messenger bot's content) + their preview/sending
     PART 14 Theme Studio (browse, create, duplicate, apply themes)
     PART 15 The image library popup (reuse any uploaded image anywhere)

   Golden rules used everywhere:
     * the page NEVER talks to Discord directly and NEVER sees the bot
       token - it only calls this app's own addresses (like /api/send),
     * the page never builds Discord payloads either: it sends a CONTENT
       MODEL ("what the message contains") and renderer.py on the server
       turns it into the exact payload - the preview shows that same
       output, so what you see is literally what you send.
   ========================================================================== */

"use strict";

/* ==========================================================================
   PART 1 - Tiny helpers, app state, constants
   ========================================================================== */

/* Find one element on the page:  $("#guildSelect")  */
const $ = (selector) => document.querySelector(selector);

/* Find all matching elements:    $$(".channel-row")  */
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

/* Create an element in one line:  el("div", "toast", "hello")  */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* Count characters the same way Discord does (roughly: by letters,
   not by bytes - emoji like 🎉 count as 1, not 2). */
function charCount(text) {
  return Array.from(text || "").length;
}

/* Show a small pop-up message at the bottom-right of the screen. */
function showToast(message, kind = "info") {
  let holder = $("#toastHolder");
  if (!holder) {
    holder = el("div");
    holder.id = "toastHolder";
    document.body.appendChild(holder);
  }
  const toast = el("div", "toast toast-" + kind, message);
  holder.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("toast-out");
    setTimeout(() => toast.remove(), 320);
  }, 4600);
}

/* Ask our own Flask app for JSON. Never talks to Discord directly. */
async function apiGet(url) {
  try {
    const response = await fetch(url);
    if (response.status === 401) {
      window.location.href = "/login";
      return { ok: false, error: "Unauthorized. Please log in." };
    }
    return await response.json();
  } catch {
    return { ok: false, error: "Could not talk to INDRA BOT SYSTEM. Is the app still running in its window?" };
  }
}

/* Same, but sends data with POST (or DELETE via apiSend(url, data, "DELETE")). */
async function apiSend(url, body, method = "POST") {
  try {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.status === 401) {
      window.location.href = "/login";
      return { ok: false, error: "Unauthorized. Please log in." };
    }
    return await response.json();
  } catch {
    return { ok: false, error: "Could not talk to INDRA BOT SYSTEM. Is the app still running?" };
  }
}

/* A simple unique id for products (random, saved in products.json). */
function newId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/* "2026-09-19T14:33" -> "19 Sep 2026, 14:33" for the history list. */
function prettyDateTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (isNaN(date)) return String(iso);
  return date.toLocaleString(undefined, {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/* Discord's limit numbers - used by the counters and the checks. */
const LIMITS = {
  title: 256,
  description: 4096,
  fieldName: 256,
  fieldValue: 1024,
  fields: 25,
  footer: 2048,
  content: 2000,
  total: 6000,
  embeds: 10,
};

/* The four statuses: embed color + the line shown in the embed. */
const STATUS_META = {
  available:  { color: 0x23a55a, label: "Available",   line: "✅ **Available now**" },
  limited:    { color: 0xf0b132, label: "Limited",     line: "⚠️ **Limited stock**" },
  sold_out:   { color: 0xed4245, label: "Sold out",    line: "❌ **SOLD OUT**" },
  coming_soon:{ color: 0x5865f2, label: "Coming soon", line: "🕓 **Coming soon**" },
};

/* Bullet styles for the features list. */
const BULLETS = {
  checkmark: "✅",
  sparkles: "✨",
  fire: "🔥",
  arrow: "➡️",
  bullet: "•",
};

/* The gallery trick: embeds that share the same "url" get grouped by
   Discord, and their images are shown as one grid. This is that url. */
const GALLERY_URL = "https://discord.com";

/* A blank product - everything the form can hold. A product starts with
   ONE plan called "Standard" (a single price, like the old app); add more
   plans in the builder when a product needs 1 Month / 1 Year / Lifetime... */
function newProduct() {
  const now = new Date().toISOString();
  return {
    id: newId(),
    kind: "product",
    name: "",
    tagline: "",
    category: "Software",
    categoryCustom: "",
    status: "available",
    currency: "$",
    plans: [{ id: "standard", label: "Standard", price: "", oldPrice: "", badge: "" }],
    stock: "",
    delivery: "instant",
    deliveryHours: "",
    license: "",
    features: "",
    bulletStyle: "checkmark",
    bulletCustom: "",
    included: "",
    requirements: "",
    refund: "",
    mainImage: { type: "none", value: "" },
    gallery: [ { type: "none", value: "" },
               { type: "none", value: "" },
               { type: "none", value: "" },
               { type: "none", value: "" } ],
    thumbnail: { type: "none", value: "" },
    footer: "INDRA BOT SYSTEM | Instant delivery",
    showTimestamp: true,
    saleEnds: "",
    content: "",
    preset: "modern",
    theme_id: "",
    fancyText: false,
    fancyStyle: "bold",
    planLayout: "list",
    ticketLineMode: "global",
    ticketLineText: "",
    isTemplate: false,
    createdAt: now,
    updatedAt: now,
  };
}

/* Old products (and old history snapshots) have a single price/oldPrice
   instead of plans - normalize them so the form always sees plans. */
function ensurePlans(product) {
  if (!Array.isArray(product.plans)) product.plans = [];
  if (!product.plans.length) {
    const price = String(product.price || "").trim();
    const oldPrice = String(product.oldPrice || "").trim();
    if (price || oldPrice) {
      product.plans = [{ id: "standard", label: "Standard", price, oldPrice, badge: "" }];
    } else {
      product.plans = [{ id: "standard", label: "Standard", price: "", oldPrice: "", badge: "" }];
    }
  }
  return product;
}

/* A blank section - the Messenger bot's content (announcements, rules...). */
function newSection() {
  const now = new Date().toISOString();
  return {
    id: newId(),
    kind: "section",
    name: "",
    title: "",
    body: "",
    preset: "clean",
    theme_id: "",
    bot_id: "",
    image: { type: "none", value: "" },
    thumbnail: { type: "none", value: "" },
    gallery: [],
    footer: "",
    showTimestamp: true,
    content: "",
    ticketLineMode: "hide",
    ticketLineText: "",
    starter: false,
    createdAt: now,
    updatedAt: now,
  };
}

/* Everything the page currently knows. */
const state = {
  product: newProduct(),        // the product being built right now
  settings: {},                 // saved settings (ticket line, etc.)
  config: {},                   // /api/config answer (test channel, ...)
  guilds: [],                   // servers, as delivered by /api/guilds
  guildId: "",                  // the currently selected server id
  manualChannels: [],           // channels added by pasting an ID
  roles: [],                    // roles of the selected server
  channelNames: new Map(),      // channel id -> name (for the preview)
  roleNames: new Map(),         // role id -> name (for the preview)
  imageErrors: new Map(),       // image src -> true when it failed to load
  editContext: null,            // {historyId, channelId, messageId, botId, attachments}
  library: [],                  // saved products
  history: [],                  // sent messages
  schedules: [],                // planned posts
  lastBuild: null,              // the last /api/preview answer (payloads!)

  // ---- sections (Messenger bot content) ----
  sections: [],                 // saved sections
  section: newSection(),        // the section being edited right now
  sectionEditContext: null,     // editing a sent section (like editContext)
  sectionLastBuild: null,       // the last section preview answer

  // ---- looks ----
  themes: [],                   // every theme (built-ins first)
  fontstyles: [],               // the 11 Unicode styles (with letter tables)

  // ---- multi-bot state ----
  bots: [],                     // the registry from /api/bots (tokens masked)
  activeBotId: "",              // which bot the dashboard is working as
  botStatus: new Map(),         // bot id -> {connected, name, username, avatar, error}
  botServers: new Map(),        // bot id -> [server names] (Bots page only)
  sendAsBotId: "",              // override for one send ("" = use the active bot)
};

/* The bot a send / schedule should run as: the little "Sending as"
   override in the preview wins, then the active bot from the switcher. */
function selectedBotId() {
  return state.sendAsBotId || state.activeBotId || "";
}

/* The server ID currently selected across the dashboard. */
function selectedGuildId() {
  return state.guildId || $("#guildSelect")?.value || state.settings.last_guild_id || "";
}

function updateGuildStatsBadge() {
  const badge = $("#guildLiveStatsBadge");
  if (!badge) return;
  const currentId = selectedGuildId();
  const guild = state.guilds.find((g) => g.id === currentId);
  if (guild && (guild.approximate_member_count !== undefined && guild.approximate_member_count !== null)) {
    badge.textContent = `👥 ${Number(guild.approximate_member_count).toLocaleString()} members • 🟢 ${Number(guild.approximate_presence_count || 0).toLocaleString()} online`;
    badge.style.display = "inline-flex";
  } else {
    badge.style.display = "none";
  }
}

/* The bot's display name + avatar for the preview header. */
function botIdentity() {
  const status = state.botStatus.get(selectedBotId());
  if (status && status.connected) {
    return { name: status.name || "Bot", avatar: status.avatar || "" };
  }
  const record = state.bots.find((b) => b.id === selectedBotId());
  if (record) return { name: record.display_name, avatar: record.avatar_url || "" };
  return { name: "INDRA BOT SYSTEM", avatar: "" };
}

let channelsRequestId = 0;      // guards against out-of-order channel loads
let saveTimer = null;           // debounces saving the destination selection
let previewTimer = null;        // debounces preview re-renders
let tsTimer = null;             // the 15s ticker for <t:...> countdowns
let schTimer = null;            // the 1s ticker for the schedule list

/* ==========================================================================
   PART 2 - Fancy text (Unicode styles) + small display helpers
   ==========================================================================
   The letter tables come from the SERVER (/api/fontstyles) - the exact
   same tables renderer.py uses. That way the little live preview in the
   form always matches what will actually be posted. */

/* Convert text into one of the 11 Unicode styles ("none" = unchanged). */
function applyStyle(text, styleId) {
  if (!text) return text;
  if (!styleId || styleId === "none") return String(text);
  const style = state.fontstyles.find((s) => s.id === styleId);
  if (!style) return String(text);

  /* IMPORTANT: turn the letter tables into real character arrays first.
     Fancy Unicode letters are built from TWO halves; plain string indexing
     would grab only half a letter (a "lone surrogate"), which crashes the
     JSON saving. Array.from() always gives complete letters. */
  const upper = Array.from(style.upper);
  const lower = Array.from(style.lower);
  const digits = Array.from(style.digits);
  let out = "";
  for (const character of String(text)) {
    const code = character.codePointAt(0);
    let replacement = null;
    if (code >= 65 && code <= 90) replacement = upper[code - 65];        // A-Z
    else if (code >= 97 && code <= 122) replacement = lower[code - 97];  // a-z
    else if (code >= 48 && code <= 57) replacement = digits[code - 48];  // 0-9
    out += replacement || character;
  }
  return out;
}

/* kept under the old name so the rest of the file reads naturally */
function fancyfy(text, styleId) { return applyStyle(text, styleId); }

/* Checkbox values may have been saved as the text "true"/"false" by an
   older version - accept both forms. */
function truthy(value) {
  return value === true || value === "true";
}

/* A short price summary for the library/history cards:
   one plan -> "$19.99" | several -> "$4.99 - $39.99" | none -> "Free". */
function plansSummary(content) {
  const plans = (content && Array.isArray(content.plans)) ? content.plans : [];
  const currency = (content && content.currency) || "";
  const prices = plans
    .map((plan) => parseFloat(String(plan.price || "").trim()))
    .filter((value) => Number.isFinite(value));
  if (!plans.length || !prices.length) return "Free";
  if (plans.length === 1) return currency + (plans[0].price || "Free");
  const low = Math.min(...prices), high = Math.max(...prices);
  const pretty = (value) => ("" + value).replace(/\.0$/, "");
  return low === high ? currency + pretty(low) : `${currency}${pretty(low)} - ${currency}${pretty(high)}`;
}

/* ==========================================================================
   PART 3 - Discord markdown renderer (for the preview) - XSS-safe
   ========================================================================== */

/* First line of defense: turn < > & into harmless text. */
function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/* "in 3 days" / "2 hours ago" - Discord's <t:...:R> style. */
function relativeTimeLabel(unix) {
  const diff = unix - Math.floor(Date.now() / 1000);
  const abs = Math.abs(diff);
  const table = [
    [31536000, "year"], [2592000, "month"], [604800, "week"],
    [86400, "day"], [3600, "hour"], [60, "minute"], [1, "second"],
  ];
  for (const [seconds, name] of table) {
    if (abs >= seconds) {
      const value = Math.round(abs / seconds);
      const plural = value !== 1 ? "s" : "";
      return diff >= 0 ? `in ${value} ${name}${plural}` : `${value} ${name}${plural} ago`;
    }
  }
  return "now";
}

/* The full <t:...:style> formatting (F f D d T t R). */
function formatTimestamp(unix, style) {
  const date = new Date(unix * 1000);
  if (isNaN(date.getTime())) return "invalid date";
  switch ((style || "f").toLowerCase()) {
    case "t": return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    case "T": return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    case "d": return date.toLocaleDateString(undefined, { day: "2-digit", month: "2-digit", year: "numeric" });
    case "D": return date.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
    case "F": return date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })
                 + " " + date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    case "R": return relativeTimeLabel(unix);
    default:  return date.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })
                 + " " + date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
}

/* One channel/role mention as a pretty blurple chip. */
function mentionHtml(id, kind) {
  const span = `<span class="mention" data-mention="${kind}" data-id="${id}"></span>`;
  return span;   // textContent is filled by resolveMentions() below
}

/* Look up names for every mention chip in the preview (and fetch the
   missing ones from the app in the background). */
function resolveMentions(root) {
  const chips = root.querySelectorAll("[data-mention]");
  for (const chip of chips) {
    const id = chip.dataset.id;
    const kind = chip.dataset.mention;
    if (kind === "channel") {
      chip.textContent = "#" + (state.channelNames.get(id) || "channel");
      if (!state.channelNames.has(id) && /^\d{15,21}$/.test(id) && !chip.dataset.lookup) {
        chip.dataset.lookup = "1";
        apiGet("/api/lookup-channel/" + encodeURIComponent(id)).then((data) => {
          if (data.ok) {
            state.channelNames.set(id, data.channel.name);
            chip.textContent = "#" + data.channel.name;
          } else {
            chip.textContent = "#unknown-channel";
          }
        });
      }
    } else if (kind === "role") {
      const name = state.roleNames.get(id);
      chip.textContent = "@" + (name || "role");
      if (name) {
        const role = state.roles.find((r) => r.id === id);
        if (role && role.color) chip.style.color = role.color;
      }
    } else {
      chip.textContent = "@user";
    }
  }
}

/*
 * renderMarkdown - turn Discord markdown into safe HTML for the preview.
 *
 * Order matters a lot here:
 *   1. pull out ``` code blocks ``` (their content must not be touched)
 *   2. ESCAPE ALL HTML  <- the XSS protection
 *   3. `inline code`
 *   4. spoilers, bold, italic, underline, strike, masked links
 *   5. <t:...> timestamps and <#...> / <@&...> / <@...> mentions
 *   6. line-based things: # headers, > quotes, line breaks
 *   7. put the code blocks back
 */
function renderMarkdown(source) {
  if (!source) return "";

  /* 1. code blocks */
  const codeBlocks = [];
  let working = String(source).replace(/```[a-zA-Z0-9+#-]*\n?([\s\S]*?)```/g, (_m, code) => {
    codeBlocks.push(code);
    return `\u0000CB${codeBlocks.length - 1}\u0000`;
  });

  /* 2. ESCAPE ALL HTML (XSS protection) */
  working = escapeHtml(working);

  /* 3. inline code */
  const inlineCodes = [];
  working = working.replace(/`([^`\n]+)`/g, (_m, code) => {
    inlineCodes.push(code);
    return `\u0000IC${inlineCodes.length - 1}\u0000`;
  });

  /* 4. spoilers first (so their content is not re-formatted), then the rest */
  working = working.replace(/\|\|([\s\S]+?)\|\|/g,
    '<span class="spoiler" tabindex="0" role="button" title="Click to reveal">$1</span>');

  working = working.replace(/\*\*\*([\s\S]+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  working = working.replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>");
  working = working.replace(/__([\s\S]+?)__/g, "<u>$1</u>");
  working = working.replace(/~~([\s\S]+?)~~/g, "<s>$1</s>");
  /* single * stars - but not the ** of bold (already gone) */
  working = working.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  /* single _ underscores - but not __ underline (already gone) and not inside words */
  working = working.replace(/(^|[^\w_])_([^_\n]+)_(?![\w_])/g, "$1<em>$2</em>");

  /* masked links [text](https://...) - only real web addresses */
  working = working.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  /* 5. timestamps and mentions (they were escaped to &lt; ... &gt;) */
  working = working.replace(/&lt;t:(\d{1,12})(?::([RrFfDdTt]))?&gt;/g, (_m, unix, style) =>
    `<span class="md-ts" data-unix="${unix}" data-style="${style || "f"}">${formatTimestamp(+unix, style || "f")}</span>`);

  working = working.replace(/&lt;#(\d{15,21})&gt;/g, (_m, id) => mentionHtml(id, "channel"));
  working = working.replace(/&lt;@&amp;(\d{15,21})&gt;/g, (_m, id) => mentionHtml(id, "role"));
  working = working.replace(/&lt;@!?(\d{15,21})&gt;/g, (_m, id) => mentionHtml(id, "user"));

  /* @everyone / @here get Discord's highlighted look */
  working = working.replace(/@(everyone|here)\b/g,
    '<span class="mention-everyone">@$1</span>');

  /* 6. line-based: headers, quotes, line breaks */
  const lines = working.split("\n");
  const renderedLines = lines.map((line) => {
    const trimmed = line.trimStart();
    if (/^#{3}\s/.test(trimmed)) return `<div class="md-h3">${line.replace(/^\s*#{3}\s/, "")}</div>`;
    if (/^#{2}\s/.test(trimmed)) return `<div class="md-h2">${line.replace(/^\s*#{2}\s/, "")}</div>`;
    if (/^#\s/.test(trimmed))   return `<div class="md-h1">${line.replace(/^\s*#\s/, "")}</div>`;
    if (/^&gt;\s?/.test(trimmed)) return `<div class="md-quote">${line.replace(/^\s*&gt;\s?/, "")}</div>`;
    return line;
  });
  working = renderedLines.join("<br>");

  /* 7. code back in */
  working = working.replace(/\u0000IC(\d+)\u0000/g, (_m, index) =>
    `<code class="md-code">${inlineCodes[+index]}</code>`);
  working = working.replace(/\u0000CB(\d+)\u0000/g, (_m, index) =>
    `<div class="md-codeblock">${codeBlocks[+index]}</div>`);

  return working;
}

/* ==========================================================================
   PART 4 - The content model (form -> data the server renders)
   ==========================================================================
   The page does NOT build Discord payloads anymore. It collects WHAT the
   message contains (the product/section object) and POSTs it to
   /api/preview; renderer.py on the server turns it into the exact
   payloads. The preview shows those payloads, and Send posts them.
   One builder, zero drift. */

/* The product being built, ready to send to the server. */
function buildContent() {
  const product = JSON.parse(JSON.stringify(state.product));   // deep copy
  ensurePlans(product);
  return product;
}

/* The section being edited, ready for the server. */
function buildSectionContent() {
  const section = JSON.parse(JSON.stringify(state.section));
  section.kind = "section";
  return section;
}

/* Preview sources: what the preview panes are looking at right now. */
function builderPreviewBody() { return $("#previewBody"); }
function sectionPreviewBody() { return $("#sectionPreviewBody"); }

/* ==========================================================================
   PART 5 - The live preview panel (a mini Discord, server-rendered)
   ========================================================================== */

/* The SELLER BOT avatar as an inline SVG (works offline, no account needed). */
const FALLBACK_AVATAR = "data:image/svg+xml," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">' +
  '<rect width="40" height="40" rx="20" fill="#5865F2"/>' +
  '<path d="M28.5 21.5l-8.4 8.4a1.6 1.6 0 0 1-2.3 0L8 22V12h10l10.5 10.5a1.6 1.6 0 0 1 0 2.3z" transform="translate(0.8 0.8) scale(0.95)" fill="#fff"/>' +
  '<circle cx="14" cy="16" r="2" fill="#5865F2"/></svg>');

/* "Today at 12:00 PM" like Discord shows it. */
function nowTimeLabel() {
  const date = new Date();
  let hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  return `Today at ${hours}:${minutes} ${ampm}`;
}

/* An <img> that remembers loading failures (for the pre-flight warnings). */
function previewImage(src, className) {
  const img = el("img", className);
  img.alt = "";
  img.src = src;
  img.addEventListener("error", () => { state.imageErrors.set(src, true); refreshPreviewSoon(); });
  img.addEventListener("load", () => { state.imageErrors.delete(src); });
  return img;
}

/* attachment://name -> the local address the PREVIEW can load. */
function previewSrc(url) {
  if (!url) return url;
  return url.startsWith("attachment://")
    ? "/uploads/" + url.slice("attachment://".length)
    : url;
}

/* Build ONE embed card as it looks in Discord. */
function renderEmbedNode(embedNode) {
  const wrap = el("div", "dc-embed");
  wrap.style.borderLeftColor = "#" + (embedNode.color || 0x5865f2).toString(16).padStart(6, "0");

  const top = el("div", "dc-embed-top");
  const main = el("div", "dc-embed-main");

  /* the author line above the title (themes like Royal Purple use it) */
  if (embedNode.author && embedNode.author.name) {
    const author = el("div", "dc-embed-author");
    if (embedNode.author.icon_url) {
      const icon = el("img", "dc-embed-author-icon");
      icon.alt = "";
      icon.src = previewSrc(embedNode.author.icon_url);
      icon.addEventListener("error", () => icon.remove());
      author.appendChild(icon);
    }
    author.appendChild(el("span", null, embedNode.author.name));
    main.appendChild(author);
  }

  if (embedNode.title) {
    const title = el("div", "dc-embed-title");
    /* if the embed has a url (the gallery trick), Discord shows the
       title as a link - copy that too */
    if (embedNode.url) {
      const link = el("a");
      link.href = embedNode.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.innerHTML = renderMarkdown(embedNode.title);
      title.appendChild(link);
    } else {
      title.innerHTML = renderMarkdown(embedNode.title);
    }
    main.appendChild(title);
  }

  if (embedNode.description) {
    const description = el("div", "dc-embed-desc");
    description.innerHTML = renderMarkdown(embedNode.description);
    main.appendChild(description);
  }

  /* fields - inline ones flow 3 per row, like Discord */
  if (embedNode.fields && embedNode.fields.length) {
    const fieldsBox = el("div", "dc-fields");
    for (const field of embedNode.fields) {
      const fieldNode = el("div", "dc-field" + (field.inline ? " inline" : ""));
      const nameNode = el("div", "dc-field-name");
      nameNode.innerHTML = renderMarkdown(field.name || "\u200b");
      const valueNode = el("div", "dc-field-value");
      valueNode.innerHTML = renderMarkdown(field.value || "");
      fieldNode.append(nameNode, valueNode);
      fieldsBox.appendChild(fieldNode);
    }
    main.appendChild(fieldsBox);
  }

  top.appendChild(main);

  if (embedNode.thumbnail && embedNode.thumbnail.url) {
    top.appendChild(previewImage(previewSrc(embedNode.thumbnail.url), "dc-embed-thumb"));
  }

  wrap.appendChild(top);
  return { node: wrap, main };
}

/* Add the image grid for the whole group of embeds. */
function appendImageGrid(container, embeds) {
  const images = [];
  for (const one of embeds) {
    if (one.image && one.image.url) images.push(previewSrc(one.image.url));
  }
  if (!images.length) return;

  /* Discord's grid rules: 1 = full, 2 = side by side, 3 = row of 3,
     4 = 2x2, 5+ = rows of 3 */
  let columns = "cols-1";
  if (images.length === 2) columns = "cols-2";
  else if (images.length === 3) columns = "cols-3";
  else if (images.length === 4) columns = "cols-2x2";
  else columns = "cols-3";

  const grid = el("div", "dc-embed-imgs " + columns);
  for (const src of images) grid.appendChild(previewImage(src, ""));
  container.appendChild(grid);
}

/* Render ONE Discord message (payload straight from the server) into
   `body`. Used by both the Builder preview and the Sections preview. */
function renderDiscordMessage(payload, identity, body) {
  const message = el("div", "dc-msg");
  const avatar = el("img", "dc-avatar");
  avatar.alt = "";
  avatar.src = identity.avatar || FALLBACK_AVATAR;
  avatar.addEventListener("error", () => { avatar.src = FALLBACK_AVATAR; });

  const messageBody = el("div", "dc-msg-body");
  const head = el("div", "dc-head");
  const name = el("span", "dc-name", identity.name || "INDRA BOT SYSTEM");
  const botTag = el("span", "dc-bot-tag");
  botTag.innerHTML = '✓&nbsp;BOT';
  const time = el("span", "dc-time", nowTimeLabel());
  head.append(name, botTag, time);
  messageBody.appendChild(head);

  /* the plain message above the embed (with markdown) */
  if (payload.content) {
    const content = el("div", "dc-content");
    content.innerHTML = renderMarkdown(payload.content);
    messageBody.appendChild(content);
  }

  /* the embeds */
  const embeds = payload.embeds || [];
  if (embeds.length) {
    const embedsBox = el("div", "dc-embeds");

    /* every embed of one message that shares the gallery url gets ONE
       combined image grid - exactly how Discord groups them */
    const grouping = embeds.length > 1 && embeds.every((one) => one.url === GALLERY_URL);
    let firstNode = null;

    if (grouping) {
      const rendered = renderEmbedNode(embeds[0]);
      firstNode = rendered.node;
      embedsBox.appendChild(rendered.node);
      appendImageGrid(rendered.node, embeds);
    } else {
      for (const one of embeds) {
        const rendered = renderEmbedNode(one);
        if (!firstNode) firstNode = rendered.node;
        appendImageGrid(rendered.node, [one]);
        embedsBox.appendChild(rendered.node);
      }
    }

    /* footer + timestamp belong to the LAST content embed - that is the
       card Discord actually shows them under */
    const last = embeds[embeds.length - 1];
    const withFooter = grouping ? embeds[0] : last;
    if (withFooter.footer || withFooter.timestamp) {
      const footer = el("div", "dc-embed-footer");
      if (withFooter.footer && withFooter.footer.text) {
        footer.appendChild(document.createTextNode(withFooter.footer.text));
      }
      if (withFooter.footer && withFooter.footer.text && withFooter.timestamp) {
        footer.appendChild(el("span", "sep", "•"));
      }
      if (withFooter.timestamp) footer.appendChild(el("span", null, nowTimeLabel()));
      (firstNode || embedsBox).appendChild(footer);
    }

    messageBody.appendChild(embedsBox);
  }

  /* action row components / buttons */
  const components = payload.components || [];
  for (const row of components) {
    if (row.type === 1 && Array.isArray(row.components)) {
      const rowEl = el("div", "dc-action-row");
      for (const comp of row.components) {
        if (comp.type === 2) {
          const btn = el("a", "dc-btn");
          btn.href = comp.url || "#";
          btn.target = "_blank";
          btn.rel = "noopener noreferrer";
          if (comp.emoji && comp.emoji.name) {
            btn.appendChild(el("span", null, comp.emoji.name + " "));
          }
          btn.appendChild(document.createTextNode(comp.label || "Link"));
          const extIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          extIcon.setAttribute("viewBox", "0 0 24 24");
          extIcon.classList.add("dc-ext");
          extIcon.innerHTML = '<path fill="currentColor" d="M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3m-2 16H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7Z"/>';
          btn.appendChild(extIcon);
          rowEl.appendChild(btn);
        }
      }
      if (rowEl.children.length) messageBody.appendChild(rowEl);
    }
  }

  message.append(avatar, messageBody);
  body.appendChild(message);
}

/* The image URLs of a rendered payload (for the pre-flight warnings). */
function payloadImageWarnings(messages) {
  const warnings = [];
  for (const message of messages || []) {
    for (const embed of message.embeds || []) {
      for (const key of ("image thumbnail " + "").split(" ")) {
        const url = embed[key] && embed[key].url;
        if (url && state.imageErrors.get(previewSrc(url))) {
          const short = url.length > 60 ? url.slice(0, 57) + "..." : url;
          warnings.push("Image did not load: " + short);
        }
      }
    }
  }
  return warnings;
}

/* ---- ask the server for the exact payloads (both preview panes use it) */
let previewSequence = 0;         // ignore out-of-order preview answers

async function fetchServerPreview(content, botId) {
  const myId = ++previewSequence;
  const data = await apiSend("/api/preview", { content, bot_id: botId || "" });
  if (myId !== previewSequence) return null;      // a newer request won
  if (data && typeof data === "object" && Array.isArray(data.messages)) return data;
  return { ok: false, messages: [], usage: {}, errors: [data && data.error || "The preview failed."],
           warnings: [], report: { messages: 0, embeds: 0, splits: [] }, bot: null };
}

/* The Builder preview: fetch + paint + pre-flight. */
async function renderPreview() {
  const identity = botIdentity();
  const data = await fetchServerPreview(buildContent(), selectedBotId());
  if (!data) return;

  state.lastBuild = data;
  const body = builderPreviewBody();
  body.replaceChildren();

  const messages = data.messages || [];
  if (!messages.length) {
    body.appendChild(el("div", "dc-empty muted", "Nothing to preview yet - start typing in the form."));
  }
  messages.forEach((payload, index) => {
    if (index > 0) body.appendChild(el("div", "split-divider",
      `✁ Discord message ${index + 1} of ${messages.length} (auto-split - the listing is too big for one message)`));
    renderDiscordMessage(payload, data.bot && data.bot.name ? data.bot : identity, body);
  });

  /* mention chips: fill in real names (fetches missing ones) */
  resolveMentions(body);

  /* live countdowns: refresh the <t:...> labels every 15 seconds */
  clearInterval(tsTimer);
  if (body.querySelector(".md-ts")) {
    tsTimer = setInterval(() => {
      for (const node of body.querySelectorAll(".md-ts")) {
        node.textContent = formatTimestamp(+node.dataset.unix, node.dataset.style);
      }
    }, 15000);
  }

  renderPreflight(data);
}

/* The pre-flight panel: where will it go, counters, warnings, send button. */
function renderPreflight(build) {
  /* destination line */
  const destination = $("#pfDest");
  const targets = selectedChannels();
  const guild = state.guilds.find((g) => g.id === state.guildId);
  if (targets.length) {
    const names = targets.slice(0, 3).map((t) => "#" + (t.name || t.id)).join(", ");
    const more = targets.length > 3 ? ` +${targets.length - 3} more` : "";
    destination.innerHTML = "";
    destination.append(
      document.createTextNode("Will send to: "),
      el("strong", null, names + more),
      document.createTextNode(guild ? ` in ${guild.name}` : ""),
    );
  } else {
    destination.textContent = "No channels selected yet - pick at least one at the top.";
  }

  /* counters */
  const usage = build.usage || {};
  const counters = $("#pfCounters");
  counters.replaceChildren();
  const messageCount = usage.messages || 1;
  /* when the listing is split into several messages, each message gets
     its own 6000-character budget - the chip shows the combined budget */
  const totalMax = LIMITS.total * messageCount;
  const chips = [
    ["Title", usage.title || 0, LIMITS.title],
    ["Description", usage.description || 0, LIMITS.description],
    ["Fields", usage.fields || 0, LIMITS.fields],
    ["Footer", usage.footer || 0, LIMITS.footer],
    ["Message", usage.content || 0, LIMITS.content],
    ["Embed total", usage.total || 0, totalMax],
    ["Embeds", usage.embeds || 0, LIMITS.embeds * messageCount],
  ];
  if (messageCount > 1) chips.push(["Messages", messageCount, ""]);
  for (const [label, value, max] of chips) {
    const chip = el("span", "pf-chip", max ? `${label} ${value}/${max}` : `${label} ${value}`);
    if (max && value > max) chip.classList.add("over");
    counters.appendChild(chip);
  }

  /* warnings + errors (server checks + image load checks) */
  const warningBox = $("#pfWarnings");
  warningBox.replaceChildren();
  const errors = [...(build.errors || [])];
  const warnings = [...(build.warnings || []), ...payloadImageWarnings(build.messages)];
  for (const message of errors) {
    warningBox.appendChild(el("div", "pf-warn w-error", "⛔ " + message));
  }
  if (!targets.length) {
    warningBox.appendChild(el("div", "pf-warn w-error", "⛔ Pick at least one channel at the top of the page."));
  }
  for (const message of warnings) {
    warningBox.appendChild(el("div", "pf-warn w-warn", "⚠️ " + message));
  }
  for (const split of ((build.report || {}).splits) || []) {
    warningBox.appendChild(el("div", "pf-warn w-info", "✂️ " + split.reason));
  }

  /* the send button (blocked while editing - use the orange one then) */
  const sendButton = $("#btn-send");
  const blocked = errors.length > 0 || !targets.length;
  sendButton.disabled = blocked || Boolean(state.editContext);
  sendButton.title = blocked
    ? "Fix the problems shown above first"
    : "Post the listing to the selected channels";

  const testButton = $("#btn-send-test");
  testButton.disabled = Boolean(state.editContext) || !state.config.test_channel_set;
  testButton.title = state.config.test_channel_set
    ? `Post once to your test channel (#${state.config.test_channel_id})`
    : "Set TEST_CHANNEL_ID in the .env file to use this";
}

/* Re-render soon - the spec asks for a ~300ms debounce so typing stays
   smooth and the server is not flooded with preview requests. */
function refreshPreviewSoon() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(renderPreview, 300);
}

/* ==========================================================================
   PART 6 - The form: bindings, pricing plans, image upload slots
   ========================================================================== */

/*
 * The form inputs are bound to the product with one table:
 *   [input id, product key, kind]
 * "input" events just copy the value into the product and refresh the
 * preview; special kinds do a little more.
 */
const BINDINGS = [
  ["f-name", "name", "text"],
  ["f-tagline", "tagline", "text"],
  ["f-category", "category", "select"],
  ["f-category-custom", "categoryCustom", "text"],
  ["f-status", "status", "status"],
  ["f-currency", "currency", "text"],
  ["f-stock", "stock", "text"],
  ["f-delivery", "delivery", "visibility"],
  ["f-delivery-hours", "deliveryHours", "text"],
  ["f-license", "license", "text"],
  ["f-saleends", "saleEnds", "text"],
  ["f-features", "features", "text"],
  ["f-bullet", "bulletStyle", "visibility"],
  ["f-bullet-custom", "bulletCustom", "text"],
  ["f-included", "included", "text"],
  ["f-requirements", "requirements", "text"],
  ["f-refund", "refund", "text"],
  ["f-content", "content", "text"],
  ["f-footer", "footer", "text"],
  ["f-theme", "theme_id", "theme"],
  ["f-timestamp", "showTimestamp", "checkbox"],
  ["f-fancy", "fancyText", "fancy"],
  ["f-fancy-style", "fancyStyle", "visibility"],
  ["f-ticket-mode", "ticketLineMode", "ticketMode"],
  ["f-ticket-text", "ticketLineText", "text"],
  ["f-plan-layout", "planLayout", "select"],
  ["f-ghost-ping", "ghost_ping", "checkbox"],
];

/* Write the product's values INTO all the form inputs. */
function renderForm() {
  const product = ensurePlans(state.product);
  for (const [inputId, key] of BINDINGS) {
    const input = $("#" + inputId);
    if (!input) continue;
    if (input.type === "checkbox") input.checked = truthy(product[key]);
    else input.value = product[key] ?? "";
  }
  /* the preset radio cards */
  for (const radio of $$('input[name=preset]')) {
    radio.checked = radio.value === product.preset;
  }
  updateConditionalFields();
  renderImageSlots();
  renderPlansEditor();
  renderButtonsEditor();
}

/* After any change: update the small show/hide details. */
function updateConditionalFields() {
  const product = state.product;
  $("#wrap-category-custom").hidden = product.category !== "custom";
  $("#wrap-delivery-hours").hidden = product.delivery !== "hours";
  $("#wrap-bullet-custom").hidden = product.bulletStyle !== "custom";
  $("#wrap-fancy").hidden = !truthy(product.fancyText);
  $("#fancyWarning").hidden = !truthy(product.fancyText);
  $("#f-ticket-text").hidden = product.ticketLineMode !== "show";
  /* live preview of the fancy style */
  if (truthy(product.fancyText)) {
    $("#fancyPreview").textContent =
      applyStyle(product.name || "Your Product Name", product.fancyStyle);
  }
  /* a sentence about the chosen theme */
  const theme = state.themes.find((t) => t.id === (product.theme_id || ""));
  $("#themeHint").textContent = theme
    ? (theme.description || theme.name + " - custom theme.")
    : "The classic look: the bar follows the product's status (green = available, red = sold out).";
}

/* Attach one listener per form input. */
function bindForm() {
  for (const [inputId, key] of BINDINGS) {
    const input = $("#" + inputId);
    if (!input) continue;

    input.addEventListener(input.type === "checkbox" || input.tagName === "SELECT"
                           ? "change" : "input",
      () => {
        const product = state.product;
        /* checkboxes store true/false, everything else stores the text */
        if (input.type === "checkbox") product[key] = input.checked;
        else product[key] = input.value;

        updateConditionalFields();
        refreshPreviewSoon();
      });
  }

  /* the 4 preset cards */
  for (const radio of $$('input[name=preset]')) {
    radio.addEventListener("change", () => {
      state.product.preset = radio.value;
      refreshPreviewSoon();
    });
  }

  /* save / duplicate / new */
  $("#btn-save-product").addEventListener("click", saveCurrentProduct);
  $("#btn-duplicate-product").addEventListener("click", duplicateCurrentProduct);
  $("#btn-new-product").addEventListener("click", startNewProduct);

  /* the fancy style select is filled from the server list once loaded */
  fillFontstyleSelect();
}

/* Fill #f-fancy-style from the server's style list (single truth). */
function fillFontstyleSelect() {
  const select = $("#f-fancy-style");
  if (!select) return;
  select.replaceChildren();
  for (const style of state.fontstyles) {
    const option = el("option", null, style.sample + "  " + style.label);
    option.value = style.id;
    select.appendChild(option);
  }
  select.value = state.product.fancyStyle || "bold";
}

/* Fill a theme <select> (the builder's and the section editor's). */
function fillThemeSelect(select, firstLabel) {
  if (!select) return;
  select.replaceChildren();
  const empty = el("option", null, firstLabel);
  empty.value = "";
  select.appendChild(empty);
  for (const theme of state.themes) {
    const option = el("option", null, (theme.builtin ? "" : "\u2726 ") + theme.name);
    option.value = theme.id;
    select.appendChild(option);
  }
}

/* ---------- the pricing plans editor ---------- */

/* One plan row: label, price, old price, badge, remove button. */
function renderPlansEditor() {
  const holder = $("#plansEditor");
  if (!holder) return;
  const product = ensurePlans(state.product);
  holder.replaceChildren();

  product.plans.forEach((plan, index) => {
    const row = el("div", "plan-row");

    const grip = el("span", "plan-grip", "\u2630");
    grip.title = "Plan " + (index + 1);
    row.appendChild(grip);

    const labelInput = el("input", "plan-label");
    labelInput.type = "text";
    labelInput.value = plan.label || "";
    labelInput.placeholder = "Plan name (e.g. 1 Month Key)";
    labelInput.maxLength = 80;
    labelInput.addEventListener("input", () => { plan.label = labelInput.value; refreshPreviewSoon(); });

    const priceInput = el("input", "plan-price");
    priceInput.type = "text";
    priceInput.value = plan.price || "";
    priceInput.placeholder = "Price";
    priceInput.addEventListener("input", () => { plan.price = priceInput.value; refreshPreviewSoon(); });

    const oldInput = el("input", "plan-old");
    oldInput.type = "text";
    oldInput.value = plan.oldPrice || "";
    oldInput.placeholder = "Old price";
    oldInput.title = "Shown struck-through, with an automatic -% OFF badge";
    oldInput.addEventListener("input", () => { plan.oldPrice = oldInput.value; refreshPreviewSoon(); });

    const badgeInput = el("input", "plan-badge");
    badgeInput.type = "text";
    badgeInput.value = plan.badge || "";
    badgeInput.placeholder = "Badge";
    badgeInput.maxLength = 24;
    badgeInput.title = "A small label like POPULAR or BEST VALUE";
    badgeInput.addEventListener("input", () => { plan.badge = badgeInput.value; refreshPreviewSoon(); });

    const remove = el("button", "btn btn-sm btn-danger plan-remove", "\u2715");
    remove.type = "button";
    remove.title = "Remove this plan";
    remove.addEventListener("click", () => {
      if (product.plans.length <= 1) {
        showToast("Keep at least one plan - set its price empty for a free product.", "info");
        return;
      }
      product.plans.splice(index, 1);
      renderPlansEditor();
      refreshPreviewSoon();
    });

    row.append(grip, labelInput, priceInput, oldInput, badgeInput, remove);
    holder.appendChild(row);
  });

  const addRow = el("button", "btn btn-ghost plan-add", "+ Add another plan");
  addRow.type = "button";
  addRow.addEventListener("click", () => {
    const plans = ensurePlans(state.product).plans;
    if (plans.length >= 10) {
      showToast("10 plans is the maximum - more would make the card unreadable.", "info");
      return;
    }
    plans.push({ id: "plan-" + newId(), label: "", price: "", oldPrice: "", badge: "" });
    renderPlansEditor();
    refreshPreviewSoon();
    const rows = $$("#plansEditor .plan-row");
    if (rows.length) rows[rows.length - 1].querySelector(".plan-label").focus();
  });
  holder.appendChild(addRow);
}

/* The "quick add" chips under the plans editor. */
function bindPlanQuickAdd() {
  for (const button of $$(".plan-quick")) {
    button.addEventListener("click", () => {
      const plans = ensurePlans(state.product).plans;
      if (plans.length >= 10) return;
      plans.push({ id: "plan-" + newId(), label: button.dataset.label || "New plan",
                   price: "", oldPrice: "", badge: "" });
      renderPlansEditor();
      refreshPreviewSoon();
    });
  }
}

/* ---------- image slots (URL, upload or library) ---------- */

/* Which object owns an image slot: the builder's product or the section
   editor's section. "gallery.2" means owner.gallery[2]. */
function slotOwner(slotDiv) {
  return slotDiv.closest("#sectionForm") ? state.section : state.product;
}

function getSlot(path, owner) {
  owner = owner || state.product;
  if (path.startsWith("gallery.")) return owner.gallery[+path.split(".")[1]];
  return owner[path];
}

function setSlot(path, value, owner) {
  owner = owner || state.product;
  if (path.startsWith("gallery.")) owner.gallery[+path.split(".")[1]] = value;
  else owner[path] = value;
}

/* Fill every image slot UI with what its owner holds. */
function renderImageSlots() {
  for (const slotDiv of $$(".img-slot")) {
    const path = slotDiv.dataset.slot;
    if (!path || path === "gallery") continue;         // the gallery wrapper
    const owner = slotOwner(slotDiv);
    const slot = getSlot(path, owner) || { type: "none", value: "" };

    const urlInput = slotDiv.querySelector(".img-url");
    const uploadLabel = slotDiv.querySelector(".img-upload-btn");
    const thumb = slotDiv.querySelector(".img-thumb");
    const mode = slotDiv.querySelector(".img-mode");
    if (!urlInput) continue;                            // safety net

    if (slot.type === "url") {
      urlInput.value = slot.value;
      urlInput.disabled = false;
      if (uploadLabel) uploadLabel.style.display = "none";
      if (thumb) { thumb.src = slot.value; thumb.hidden = false; }
      if (mode) mode.textContent = "Web image (URL)";
    } else if (slot.type === "upload") {
      urlInput.value = "";
      urlInput.disabled = true;
      if (uploadLabel) uploadLabel.style.display = "none";
      if (thumb) { thumb.src = "/uploads/" + slot.value; thumb.hidden = false; }
      if (mode) mode.textContent = "Uploaded from your PC: " + slot.value;
    } else {
      urlInput.value = "";
      urlInput.disabled = false;
      if (uploadLabel) uploadLabel.style.display = "";
      if (thumb) thumb.hidden = true;
      if (mode) mode.textContent = "";
    }
  }
}

/* Wire up all image slot controls (builder AND section editor). */
function bindImageSlots() {
  for (const slotDiv of $$(".img-slot")) {
    const path = slotDiv.dataset.slot;
    if (!path || path === "gallery") continue;
    const owner = () => slotOwner(slotDiv);

    const urlInput = slotDiv.querySelector(".img-url");
    const fileInput = slotDiv.querySelector(".img-file");
    const clearButton = slotDiv.querySelector(".img-clear");
    const libraryButton = slotDiv.querySelector(".img-lib-btn");

    /* typing a URL */
    urlInput.addEventListener("input", () => {
      const value = urlInput.value.trim();
      setSlot(path, value ? { type: "url", value } : { type: "none", value: "" }, owner());
      refreshPreviewSoon();
      refreshSectionPreviewSoon();
    });

    /* uploading a file from the PC */
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";                    // allow re-selecting the same file
      if (!file) return;

      /* friendly checks before even sending it */
      if (file.size > 8 * 1024 * 1024) {
        showToast("That image is bigger than 8 MB. Please use a smaller one.", "error");
        return;
      }
      if (!/^image\/(png|jpe?g|gif|webp)$/.test(file.type)) {
        showToast("Only PNG, JPG, GIF and WEBP images are allowed.", "error");
        return;
      }

      const formData = new FormData();
      formData.append("file", file);
      showToast("Uploading " + file.name + "...");
      try {
        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await response.json();
        if (!data.ok) { showToast(data.error || "The upload failed.", "error"); return; }
        setSlot(path, { type: "upload", value: data.filename }, owner());
        renderImageSlots();
        refreshPreviewSoon();
        refreshSectionPreviewSoon();
        showToast(data.note || "Image uploaded.", "success");
      } catch {
        showToast("The upload failed - is the app still running?", "error");
      }
    });

    /* the X button */
    clearButton.addEventListener("click", () => {
      setSlot(path, { type: "none", value: "" }, owner());
      renderImageSlots();
      refreshPreviewSoon();
      refreshSectionPreviewSoon();
    });

    /* the image library popup */
    if (libraryButton) {
      libraryButton.addEventListener("click", () =>
        openImageLibrary((slot) => {
          setSlot(path, slot, owner());
          renderImageSlots();
          refreshPreviewSoon();
          refreshSectionPreviewSoon();
        }));
    }
  }
}

/* ==========================================================================
   PART 7 - Sending: real send, test send, Ctrl+Enter, Copy JSON, editing
   ========================================================================== */

/* The targets the Send button will use, as [{"id", "name"}]. */
function selectedChannels() {
  const result = new Map();
  for (const input of $$("#channelGroups input[type=checkbox]:checked")) {
    result.set(input.value, { id: input.value, name: input.dataset.channelName });
  }
  for (const channel of state.manualChannels) {
    if (!result.has(channel.id)) result.set(channel.id, channel);
  }
  return Array.from(result.values());
}

/* Send the listing to the selected channels. The server renders the same
   content model the preview already showed - nothing can drift. */
async function sendListing() {
  if (state.editContext) { updateSentMessage(); return; }   // editing mode
  const build = state.lastBuild;
  if (build && build.errors && build.errors.length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }
  const targets = selectedChannels();
  if (!targets.length) { showToast("Pick at least one channel at the top first.", "error"); return; }

  const button = $("#btn-send");
  button.disabled = true;
  button.textContent = "Sending...";

  const result = await apiSend("/api/send", {
    targets,
    content: buildContent(),
    bot_id: selectedBotId(),
  });

  button.disabled = false;
  button.innerHTML = 'Send <span class="kbd">Ctrl+↵</span>';

  if (result.ok) {
    const sentCount = result.results.filter((r) => r.ok).length;
    const failed = result.results.filter((r) => !r.ok);
    if (sentCount) showToast(`Listing sent to ${sentCount} channel${sentCount > 1 ? "s" : ""}.`, "success");
    for (const failure of failed) showToast(failure.error, "error");
    loadHistory();
  } else {
    showToast(result.error || "Sending failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

/* Send test - to the TEST_CHANNEL_ID from .env only. */
async function sendTest() {
  const build = state.lastBuild;
  if (build && build.errors && build.errors.length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }
  const button = $("#btn-send-test");
  button.disabled = true;
  button.textContent = "Sending test...";

  const result = await apiSend("/api/send-test", {
    content: buildContent(),
    bot_id: selectedBotId(),
  });

  button.disabled = false;
  button.textContent = "Send test";

  if (result.ok) {
    showToast("Test sent - check your test channel in Discord!", "success");
    loadHistory();
  } else {
    showToast(result.error || "The test send failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

/* Copy JSON - show the exact payloads the server built. */
function showCopyJson(messages, titleText) {
  const build = messages || (state.lastBuild && state.lastBuild.messages);
  if (!build) return;
  const payloadText = build.length === 1
    ? build[0]
    : build;
  const json = JSON.stringify(payloadText, null, 2);
  const filesNote = "The preview above shows exactly these payloads - the server builds them, the page only displays them.";

  openModal(titleText || "The exact JSON that will be sent", `
    <pre class="json"></pre>
    <p class="muted small"></p>
    <div class="send-row">
      <button class="btn" id="modalCopyBtn">Copy to clipboard</button>
    </div>
  `);

  $("#modalBody .json").textContent = json;
  $("#modalBody .muted").textContent = filesNote;
  $("#modalCopyBtn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(json);
      showToast("JSON copied to your clipboard.", "success");
    } catch {
      showToast("Your browser blocked the clipboard - select the text and copy manually.", "error");
    }
  });
}

/* ---------- editing a message that was already sent ---------- */

/* Called from the History tab: load a sent listing back into the builder
   (products) or the Sections tab (sections). */
function startEditing(entry) {
  const snapshot = entry.content || entry.product;
  if (!snapshot) {
    showToast("This old entry has no saved content - rebuild it from the library instead.", "error");
    return;
  }
  const content = JSON.parse(JSON.stringify(snapshot));

  if (entry.kind === "section") {
    state.section = { ...newSection(), ...content };
    state.sectionEditContext = {
      historyId: entry.id,
      channelId: entry.channel_id,
      messageId: entry.message_id,
      channelName: entry.channel_name,
      botId: entry.bot_id || "",
      botName: entry.bot_name || "",
    };
    renderSectionForm();
    refreshSectionPreviewSoon();
    updateSectionEditBanner();
    switchTab("sections");
    showToast("Loaded into the section editor - change what you like, then press 'Update the Discord message'.", "success");
    return;
  }

  state.product = ensurePlans(content);
  state.product.updatedAt = new Date().toISOString();
  state.editContext = {
    historyId: entry.id,
    channelId: entry.channel_id,
    messageId: entry.message_id,
    channelName: entry.channel_name,
    botId: entry.bot_id || "",
    botName: entry.bot_name || "",
    attachments: entry.attachments || [],
  };
  renderForm();
  refreshPreviewSoon();
  updateEditBanner();
  switchTab("builder");
  showToast("Loaded into the builder - change what you like, then press 'Update the Discord message'.", "success");
}

function cancelEditing() {
  state.editContext = null;
  updateEditBanner();
  refreshPreviewSoon();
  showToast("Left editing mode. The Send button posts a new message again.");
}

function updateEditBanner() {
  const banner = $("#editBanner");
  if (state.editContext) {
    banner.hidden = false;
    $("#editBannerText").textContent =
      `You are editing the message sent in #${state.editContext.channelName || state.editContext.channelId}. ` +
      "The changes below will be applied to that same Discord message (nothing new is posted).";
    $("#btn-send").disabled = true;
  } else {
    banner.hidden = true;
  }
}

/* The orange button: re-render on the server and PATCH the original
   Discord message(s). Uploaded images survive automatically - the server
   keeps every old attachment the new message still references. */
async function updateSentMessage() {
  if (!state.editContext) return;
  const context = state.editContext;
  const build = state.lastBuild;
  if (build && build.errors && build.errors.length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }

  const button = $("#btnUpdateMessage");
  button.disabled = true;
  button.textContent = "Updating...";

  const result = await apiSend("/api/messages/update", {
    channel_id: context.channelId,
    history_id: context.historyId,
    content: buildContent(),
    bot_id: context.botId,
    action: "edited",
  });

  button.disabled = false;
  button.textContent = "Update the Discord message";

  if (result.ok) {
    showToast("The Discord message was updated.", "success");
    cancelEditing();
    loadHistory();
  } else {
    showToast(result.error || "Updating failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

/* ==========================================================================
   PART 8 - Product library tab
   ========================================================================== */

async function loadLibrary() {
  const data = await apiGet("/api/products");
  if (data.ok) {
    state.library = data.products || [];
    $("#libCount").textContent = state.library.length;
    renderLibrary();
  }
}

/* The little preview picture of a product (main image or thumbnail). */
function cardThumb(content) {
  const slot = content && (content.mainImage || content.image);
  const src = slot && slot.type !== "none" && slot.value
    ? (slot.type === "upload" ? "/uploads/" + slot.value : slot.value)
    : null;
  return src;
}

function renderLibrary() {
  const grid = $("#libGrid");
  grid.replaceChildren();

  if (!state.library.length) {
    grid.appendChild(el("p", "muted", "No products yet. Build one in the Builder tab and press Save."));
    return;
  }

  for (const raw of state.library) {
    const product = ensurePlans(JSON.parse(JSON.stringify(raw)));
    const card = el("div", "lib-card");

    const thumbSrc = cardThumb(product);
    if (thumbSrc) {
      const img = el("img", "lib-thumb");
      img.alt = "";
      img.src = thumbSrc;
      img.addEventListener("error", () => img.remove());
      card.appendChild(img);
    }

    const top = el("div", "lib-card-top");
    top.appendChild(el("div", "lib-name", product.name || "Untitled product"));
    if (product.isTemplate) top.appendChild(el("span", "tag", "template"));
    card.appendChild(top);

    const meta = el("div", "lib-meta");
    const metaBits = [
      PRESET_LABELS[product.preset] || product.preset,
      STATUS_META[product.status] ? STATUS_META[product.status].label : product.status,
      plansSummary(product),
    ];
    if (product.plans.length > 1) metaBits.push(product.plans.length + " plans");
    for (const bit of metaBits) meta.appendChild(el("span", null, bit));
    meta.appendChild(el("span", null, "updated " + prettyDateTime(product.updatedAt)));
    card.appendChild(meta);

    const actions = el("div", "lib-actions-row");
    const loadButton = el("button", "btn btn-sm", "Load & edit");
    loadButton.addEventListener("click", () => {
      if (state.editContext) { showToast("Finish or cancel editing first.", "error"); return; }
      state.product = ensurePlans(JSON.parse(JSON.stringify(product)));
      renderForm();
      refreshPreviewSoon();
      switchTab("builder");
    });
    const duplicateButton = el("button", "btn btn-sm btn-ghost", "Duplicate");
    duplicateButton.addEventListener("click", async () => {
      const copy = ensurePlans(JSON.parse(JSON.stringify(product)));
      copy.id = newId();
      copy.name = (product.name || "Product") + " (copy)";
      copy.isTemplate = false;
      await apiSend("/api/products", { product: copy });
      loadLibrary();
      showToast("Product duplicated.", "success");
    });
    const exportButton = el("button", "btn btn-sm btn-ghost", "Export");
    exportButton.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(product, null, 2)], { type: "application/json" });
      const link = el("a");
      link.href = URL.createObjectURL(blob);
      link.download = (product.name || "product").replace(/[^\w-]+/g, "-").toLowerCase() + ".json";
      link.click();
      URL.revokeObjectURL(link.href);
    });
    const deleteButton = el("button", "btn btn-sm btn-danger", "Delete");
    deleteButton.addEventListener("click", async () => {
      if (!confirm(`Delete "${product.name}" from your library? ` +
                   "(Messages already sent to Discord are NOT deleted.)")) return;
      await apiSend("/api/products/" + encodeURIComponent(product.id), {}, "DELETE");
      loadLibrary();
      showToast("Product deleted from the library.", "success");
    });

    actions.append(loadButton, duplicateButton, exportButton, deleteButton);
    card.appendChild(actions);
    grid.appendChild(card);
  }
}

const PRESET_LABELS = {
  modern: "Modern Card",
  minimal: "Minimal",
  banner: "Big Banner",
  flash: "Flash Sale",
};

async function saveCurrentProduct() {
  const product = ensurePlans(JSON.parse(JSON.stringify(state.product)));
  product.updatedAt = new Date().toISOString();
  if (!product.name.trim()) {
    showToast("Give the product a name first - it is also the embed title.", "error");
    $("#f-name").focus();
    return;
  }
  const result = await apiSend("/api/products", { product });
  if (result.ok) {
    state.product = result.product;
    showToast("Saved to your library.", "success");
    loadLibrary();
  } else {
    showToast(result.error || "Saving failed.", "error");
  }
}

async function duplicateCurrentProduct() {
  const copy = ensurePlans(JSON.parse(JSON.stringify(state.product)));
  copy.id = newId();
  copy.name = (state.product.name || "Product") + " (copy)";
  copy.isTemplate = false;
  await apiSend("/api/products", { product: copy });
  state.product = copy;
  renderForm();
  loadLibrary();
  showToast("Working on a duplicate - the original is untouched.", "success");
}

function startNewProduct() {
  if (state.editContext) { showToast("Finish or cancel editing first.", "error"); return; }
  state.product = newProduct();
  renderForm();
  refreshPreviewSoon();
  showToast("Started a blank product. (Your saved products are safe in the Library tab.)");
}

/* ==========================================================================
   PART 9 - History tab + one-click actions on sent messages
   ========================================================================== */

async function loadHistory() {
  const data = await apiGet("/api/history");
  if (data.ok) {
    state.history = data.history || [];
    renderHistory();
  }
}

function renderHistory() {
  const list = $("#histList");
  list.replaceChildren();

  if (!state.history.length) {
    list.appendChild(el("p", "muted",
      "Nothing sent yet. Build a product, pick a channel, and press Send (or 'Send test' first)."));
    return;
  }

  for (const entry of state.history) {
    const card = el("div", "hist-card" + (entry.status === "deleted" ? " status-deleted" : ""));
    const content = entry.content || entry.product || {};

    /* --- name + status tag --- */
    const top = el("div", "hist-top");
    top.appendChild(el("div", "hist-name", entry.product_name || "Untitled"));
    if (entry.kind === "section") top.appendChild(el("span", "tag tag-purple", "section"));
    const sourceTag = { manual: null, test: "tag-grey", scheduled: "tag-amber", repost: null }[entry.source];
    if (entry.status === "deleted") top.appendChild(el("span", "tag tag-grey", "deleted"));
    else if (entry.last_action) top.appendChild(el("span", "tag tag-green", entry.last_action));
    else if (sourceTag) top.appendChild(el("span", "tag " + sourceTag, entry.source));
    card.appendChild(top);

    /* --- meta line --- */
    const meta = el("div", "hist-meta");
    meta.appendChild(el("span", null,
      `#${entry.channel_name || entry.channel_id} - ${prettyDateTime(entry.ts)}`));
    if (entry.bot_name) {
      const botChip = el("span", "hist-bot-chip", "🤖 " + entry.bot_name);
      botChip.title = "The bot that posted this message";
      meta.appendChild(botChip);
    }
    const messageCount = (entry.message_ids || []).length || 1;
    if (messageCount > 1) {
      meta.appendChild(el("span", null, `${messageCount} messages`));
    }
    if (entry.attachments && entry.attachments.length) {
      meta.appendChild(el("span", null, `${entry.attachments.length} image${entry.attachments.length > 1 ? "s" : ""}`));
    }
    card.appendChild(meta);

    /* --- action buttons (only for messages that still exist) --- */
    if (entry.status !== "deleted") {
      const actions = el("div", "hist-actions");

      const actionButton = (label, className, handler) => {
        const button = el("button", "btn btn-sm " + className, label);
        button.addEventListener("click", () => handler(entry));
        return button;
      };

      if (entry.kind !== "section") {
        actions.append(
          actionButton("❌ Mark SOLD OUT", "btn-danger", () => historyStatusChange(entry, "sold_out")),
          actionButton("↩️ Restock", "btn-ghost", () => historyStatusChange(entry, "available")),
          actionButton("💰 Change prices", "btn-ghost", () => historyChangePrice(entry)),
        );
      }
      actions.append(
        actionButton("✏️ Edit", "btn-ghost", () => startEditing(entry)),
        actionButton("🔁 Repost / bump", "btn-ghost", () => historyRepost(entry)),
        actionButton("➡️ Send to...", "btn-ghost", () => historySendTo(entry)),
        actionButton("🗑 Delete message", "btn-danger", () => historyDelete(entry)),
      );
      card.appendChild(actions);
    }

    list.appendChild(card);
  }
}

/* Shared helper: send a modified content model to /api/messages/update -
   the server re-renders and patches every Discord message of the listing. */
async function historyApplyChange(entry, changeContent, actionLabel) {
  const snapshot = entry.content || entry.product;
  if (!snapshot) { showToast("This entry has no saved content and cannot be edited automatically.", "error"); return; }

  const content = JSON.parse(JSON.stringify(snapshot));
  changeContent(content);

  const result = await apiSend("/api/messages/update", {
    channel_id: entry.channel_id,
    history_id: entry.id,
    content,
    bot_id: entry.bot_id || "",
    action: actionLabel,
  });

  if (result.ok) {
    showToast("The Discord message was updated (" + actionLabel + ").", "success");
    loadHistory();
  } else {
    showToast(result.error || "Updating failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

/* Mark sold out / restock. */
function historyStatusChange(entry, status) {
  historyApplyChange(entry, (content) => { content.status = status; },
    status === "sold_out" ? "marked sold out" : "restocked");
}

/* Change prices: a small modal with EVERY plan's price. */
function historyChangePrice(entry) {
  const snapshot = entry.content || entry.product;
  if (!snapshot) { showToast("This entry has no saved content.", "error"); return; }
  const content = ensurePlans(JSON.parse(JSON.stringify(snapshot)));
  if (!content.plans.length) {
    content.plans = [{ id: "standard", label: "Standard", price: "", oldPrice: "", badge: "" }];
  }

  const rows = content.plans.map((plan, index) => `
    <div class="field">
      <label for="priceInput${index}">${escapeHtml(plan.label || "Plan")} 
        <span class="label-hint">(current: ${escapeHtml(content.currency + (plan.price || "Free"))})</span></label>
      <div class="row">
        <input id="priceInput${index}" type="text" placeholder="new price (empty = Free)" data-plan="${index}">
        <input id="oldInput${index}" type="text" placeholder="new old price (optional)" data-plan="${index}">
      </div>
    </div>`).join("");

  openModal("Change the prices", `
    <p class="muted small">Enter the new prices. Fill an "old price" to show a strikethrough with an
    automatic discount badge. Leave everything empty to make it free.</p>
    ${rows}
    <div class="send-row">
      <button class="btn" id="applyPriceBtn">Update the Discord message</button>
    </div>
  `);

  $("#priceInput0") && $("#priceInput0").focus();
  $("#applyPriceBtn").addEventListener("click", () => {
    closeModal();
    content.plans.forEach((plan, index) => {
      const priceInput = $("#priceInput" + index);
      const oldInput = $("#oldInput" + index);
      if (priceInput && priceInput.value.trim() !== "") plan.price = priceInput.value.trim();
      else if (priceInput) plan.price = "";
      if (oldInput && oldInput.value.trim() !== "") plan.oldPrice = oldInput.value.trim();
    });
    historyApplyChange(entry, (draft) => { draft.plans = content.plans; }, "prices changed");
  });
}

/* Repost: send the same content again as NEW message(s). */
async function historyRepost(entry) {
  const snapshot = entry.content || entry.product;
  if (!snapshot) { showToast("This entry is too old to repost automatically.", "error"); return; }
  const result = await apiSend("/api/send", {
    targets: [{ id: entry.channel_id, name: entry.channel_name }],
    content: snapshot,
    bot_id: entry.bot_id || "",
  });
  if (result.ok) {
    showToast("Bumped! The message was posted again.", "success");
    loadHistory();
  } else {
    showToast(result.error || "Reposting failed.", "error");
  }
}

/* Send to another channel: modal with a channel picker. */
function historySendTo(entry) {
  const channels = [...state.channelNames.entries()]
    .map(([id, name]) => ({ id, name }))
    .filter((channel) => channel.id !== entry.channel_id);

  openModal("Send this to another channel", `
    <p class="muted small">Channels of the server you selected at the top of the page.</p>
    <div class="field">
      <label for="sendToSelect">Channel</label>
      <select id="sendToSelect">
        ${channels.map((c) => `<option value="${c.id}">#${escapeHtml(c.name)}</option>`).join("") || ""}
      </select>
    </div>
    <div class="send-row">
      <button class="btn" id="sendToBtn">Send it</button>
    </div>
  `);

  if (!channels.length) $("#sendToSelect").innerHTML = '<option value="">(pick a server at the top first)</option>';
  $("#sendToBtn").addEventListener("click", async () => {
    const channelId = $("#sendToSelect").value;
    if (!channelId) { showToast("No channel picked.", "error"); return; }
    closeModal();
    const result = await apiSend("/api/send", {
      targets: [{ id: channelId, name: state.channelNames.get(channelId) || "" }],
      content: entry.content || entry.product,
      bot_id: entry.bot_id || "",
    });
    if (result.ok) { showToast("Sent to the new channel.", "success"); loadHistory(); }
    else showToast(result.error || "Sending failed.", "error");
  });
}

/* Delete the real Discord message(s). */
async function historyDelete(entry) {
  if (!confirm(`Delete this message from #${entry.channel_name || entry.channel_id} on Discord? ` +
               "This cannot be undone.")) return;
  const result = await apiSend("/api/messages/delete", {
    channel_id: entry.channel_id,
    history_id: entry.id,
    bot_id: entry.bot_id || "",
  });
  if (result.ok) { showToast("Message deleted from Discord.", "success"); loadHistory(); }
  else showToast(result.error || "Deleting failed.", "error");
}

/* ==========================================================================
   PART 10 - Schedules tab
   ========================================================================== */

async function loadSchedules() {
  const data = await apiGet("/api/schedules");
  if (data.ok) {
    state.schedules = data.schedules || [];
    $("#schCount").textContent = state.schedules.filter((s) => s.status === "pending").length;
    renderSchedules();
  }
}

function renderSchedules() {
  const list = $("#schList");
  list.replaceChildren();

  const pending = state.schedules.filter((s) => s.status === "pending");
  const others = state.schedules.filter((s) => s.status !== "pending");

  if (!state.schedules.length) {
    list.appendChild(el("p", "muted", "No scheduled posts yet."));
    return;
  }

  const makeCard = (item) => {
    const card = el("div", "sch-card");
    const left = el("div");
    const when = el("div", "sch-when", prettyDateTime(item.run_at));
    left.appendChild(when);
    if (item.status === "pending") {
      const countdown = el("div", "sch-countdown");
      countdown.dataset.runat = item.run_at;
      left.appendChild(countdown);
    }
    const names = (item.targets || []).map((t) => "#" + (t.name || t.id)).join(", ");
    left.appendChild(el("div", "sch-meta", (item.product_name ? item.product_name + " - " : "") + names));
    card.appendChild(left);

    const right = el("div", "sch-actions");
    const statusTag = el("span", "tag " + ({
      pending: "", done: "tag-green", cancelled: "tag-grey",
      missed: "tag-amber", failed: "tag-red", error: "tag-red",
    })[item.status] || "", item.status);
    right.appendChild(statusTag);

    if (item.status === "pending") {
      const cancelButton = el("button", "btn btn-sm btn-ghost", "Cancel");
      cancelButton.addEventListener("click", async () => {
        await apiSend("/api/schedules/cancel", { id: item.id });
        loadSchedules();
        showToast("Scheduled post cancelled.", "success");
      });
      right.appendChild(cancelButton);
    }
    if (item.status === "missed" || item.status === "pending") {
      const runButton = el("button", "btn btn-sm", "Run now");
      runButton.addEventListener("click", async () => {
        await apiSend("/api/schedules/run-now", { id: item.id });
        showToast("It will be posted in a few seconds...", "success");
        setTimeout(loadSchedules, 4000);
      });
      right.appendChild(runButton);
    }
    card.appendChild(right);
    return card;
  };

  for (const item of pending) list.appendChild(makeCard(item));
  for (const item of others) list.appendChild(makeCard(item));

  updateScheduleCountdowns();
}

/* "in 2 hours" labels for pending schedules (updated every second). */
function updateScheduleCountdowns() {
  for (const node of $$("#schList .sch-countdown")) {
    const date = new Date(node.dataset.runat);
    if (isNaN(date.getTime())) continue;
    const unix = Math.floor(date.getTime() / 1000);
    node.textContent = relativeTimeLabel(unix).replace(/^in /, "fires in ") ;
  }
}

async function createSchedule() {
  const runAt = $("#sch-runat").value;
  if (!runAt) { showToast("Pick a date and time first.", "error"); return; }
  const targets = selectedChannels();
  if (!targets.length) { showToast("Pick at least one channel at the top first.", "error"); return; }

  const build = state.lastBuild;
  if (build && build.errors && build.errors.length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }

  const result = await apiSend("/api/schedules", {
    run_at: runAt,
    targets,
    content: buildContent(),
    product_name: state.product.name || "Untitled product",
    bot_id: selectedBotId(),
  });

  if (result.ok) {
    showToast("Scheduled! Keep the app running at that time.", "success");
    $("#sch-runat").value = "";
    loadSchedules();
  } else {
    showToast(result.error || "Scheduling failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

/* ==========================================================================
   PART 11 - Settings tab, destination pickers, modal, tabs, start-up
   ========================================================================== */

/* ---------- the modal ---------- */

function openModal(title, bodyHtml) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = bodyHtml;
  $("#modalBack").hidden = false;
}

function closeModal() {
  $("#modalBack").hidden = true;
  $("#modalBody").replaceChildren();
}

/* ---------- tabs ---------- */

function switchTab(name) {
  for (const tab of $$(".tab")) {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  }
  for (const panel of $$(".tab-panel")) panel.hidden = true;
  const panel = $("#tab-" + name);
  if (panel) panel.hidden = false;

  /* refresh the data the tab shows */
  if (name === "library") loadLibrary();
  if (name === "history") loadHistory();
  if (name === "bots") { renderBotsPage(); refreshBotStatuses(false); }
  if (name === "sections") { loadSections(); refreshSectionPreviewSoon(); }
  if (name === "themes") { loadThemes(); }
  if (name === "stats") { loadServerStats(); }
  if (name === "vouches") { loadVouches(); }
  if (name === "schedules") { loadSchedules(); clearInterval(schTimer); schTimer = setInterval(loadSchedules, 15000); }
  else if (schTimer) { clearInterval(schTimer); schTimer = null; }

  localStorage.setItem("sb-last-tab", name);
}

/* ---------- destination: servers, channels, roles ---------- */

/*
 * loadConnectionStatus - check the ACTIVE bot's connection and update the
 * switcher in the header (name, avatar, status dot) plus the big red
 * "not connected" card when something is wrong.
 */
async function loadConnectionStatus() {
  const botId = state.activeBotId;
  setSwitcherChecking();

  const query = botId ? "?bot=" + encodeURIComponent(botId) : "";
  const data = await apiGet("/api/status" + query);

  if (data.connected && data.bot) {
    state.botStatus.set(data.bot_id || botId, {
      connected: true,
      name: data.bot.name,
      username: data.bot.username,
      avatar: data.bot.avatar_url,
      error: null,
    });
    setSwitcherState("ok", data.bot.name, data.bot.avatar_url,
                     "Connected as @" + (data.bot.username || data.bot.name));
    $("#connectionError").hidden = true;
  } else {
    state.botStatus.set(data.bot_id || botId, {
      connected: false, name: null, username: null, avatar: null,
      error: data.error || "Something went wrong while connecting to Discord.",
    });
    setSwitcherState("error", null, null, "Not connected");

    $("#connectionErrorText").textContent =
      data.error || "Something went wrong while connecting to Discord.";
    $("#connectionError").hidden = false;
  }
  renderBotMenuItems();
  refreshPreviewSoon();      // the preview shows the bot name + avatar
}

/* The three little helpers that paint the switcher button. */
function setSwitcherChecking() {
  const dot = $("#switcherDot");
  dot.className = "dot checking";
  $("#switcherSub").textContent = "connecting...";
}

function setSwitcherState(kind, name, avatarUrl, subtitle) {
  const record = state.bots.find((b) => b.id === state.activeBotId);
  $("#switcherName").textContent = name || (record ? record.display_name : "No bot yet");
  $("#switcherSub").textContent = subtitle || "";

  const dot = $("#switcherDot");
  dot.className = "dot " + (kind === "ok" ? "ok" : kind === "error" ? "error" : "checking");

  const img = $("#switcherAvatar");
  const fallback = $("#switcherAvatarFallback");
  const initials = (name || record?.display_name || "SB").slice(0, 2).toUpperCase();
  if (avatarUrl || (record && record.avatar_url)) {
    img.src = avatarUrl || record.avatar_url;
    img.hidden = false;
    fallback.hidden = true;
    img.onerror = () => { img.hidden = true; fallback.hidden = false; };
  } else {
    img.hidden = true;
    fallback.hidden = false;
    fallback.textContent = initials;
  }
}

async function loadGuilds() {
  const select = $("#guildSelect");

  select.disabled = true;
  select.replaceChildren(el("option", null, "Loading your servers..."));

  const query = state.activeBotId ? "?bot=" + encodeURIComponent(state.activeBotId) : "";
  const data = await apiGet("/api/guilds" + query);

  if (!data.ok) {
    select.replaceChildren(el("option", null, data.error || "Could not load servers"));
    return;
  }

  state.guilds = data.guilds || [];

  if (!state.guilds.length) {
    select.replaceChildren(el("option", null, "No servers yet - invite the bot first (see README)"));
    $("#channelGroups").replaceChildren(
      el("p", "muted loading-note",
         "The bot is not in any server yet. Invite it with the link from the README, then click Refresh."));
    return;
  }

  select.replaceChildren();
  for (const guild of state.guilds) {
    const memberStr = (guild.approximate_member_count !== undefined && guild.approximate_member_count !== null)
      ? ` (${Number(guild.approximate_member_count).toLocaleString()} members${guild.approximate_presence_count ? `, ${Number(guild.approximate_presence_count).toLocaleString()} online` : ""})`
      : "";
    const option = el("option", null,
      guild.name + memberStr + (guild.missing_permissions ? "   (missing permissions)" : ""));
    option.value = guild.id;
    select.appendChild(option);
  }
  select.disabled = false;

  /* restore the server you used last time */
  const savedId = state.settings.last_guild_id;
  if (savedId && state.guilds.some((guild) => guild.id === savedId)) {
    select.value = savedId;
  }

  updateGuildStatsBadge();
  await loadChannels(select.value);
  loadServerStats();
}

async function loadChannels(guildId) {
  if (!guildId || !/^\d+$/.test(guildId)) return;

  /* a guard against quick server switching (out-of-order answers) */
  const myRequestId = ++channelsRequestId;

  state.guildId = guildId;
  state.manualChannels = [];
  state.allChannels = [];
  renderManualChannels();
  updateGuildWarning();
  updateGuildStatsBadge();

  const box = $("#channelGroups");
  box.replaceChildren(el("p", "muted loading-note", "Loading channels..."));

  const botQuery = state.activeBotId ? "?bot=" + encodeURIComponent(state.activeBotId) : "";
  const data = await apiGet("/api/channels/" + encodeURIComponent(guildId) + botQuery);
  if (myRequestId !== channelsRequestId) return;

  box.replaceChildren();

  if (!data.ok) {
    box.appendChild(el("p", "muted", data.error || "Could not load channels."));
    return;
  }

  /* remember channel names for the preview mentions + ticket dropdown */
  const ticketSelect = $("#ticket-channel-select");
  const previousTicket = state.settings.ticket_channel_id;
  const emptyOption = el("option", null, "(not set - pick a channel)");
  emptyOption.value = "";
  const manualOption = el("option", null, "➕ Add by channel ID...");
  manualOption.value = "manual";
  ticketSelect.replaceChildren(emptyOption, manualOption);

  const savedIds = new Set(state.settings.last_channel_ids || []);
  let foundAny = false;

  for (const group of data.groups) {
    const section = el("div", "channel-group");
    section.appendChild(el("div", "channel-group-title", group.name || "No category"));

    for (const channel of group.channels) {
      foundAny = true;
      state.channelNames.set(channel.id, channel.name);
      state.allChannels.push(channel);

      const option = el("option", null, "#" + channel.name);
      option.value = channel.id;
      ticketSelect.appendChild(option);

      section.appendChild(makeChannelRow(channel, savedIds.has(channel.id)));
    }
    box.appendChild(section);
  }

  if (!foundAny) {
    box.appendChild(el("p", "muted", "This server has no text channels to post to."));
  }

  /* select the saved ticket channel (or show it as an extra option) */
  if (previousTicket && state.channelNames.has(previousTicket)) {
    ticketSelect.value = previousTicket;
  } else if (previousTicket) {
    const option = el("option", null, "current: #" + (state.settings.ticket_channel_name || previousTicket));
    option.value = previousTicket;
    ticketSelect.appendChild(option);
    ticketSelect.value = previousTicket;
  }

  updateSummary();
  loadServerStats();
  refreshPreviewSoon();
  loadRoles(guildId);
}

/* Build one clickable channel row (custom checkbox + # + name). */
function makeChannelRow(channel, checked) {
  const row = el("label", "channel-row");

  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = channel.id;
  input.checked = checked;
  input.dataset.channelName = channel.name;
  input.addEventListener("change", () => {
    updateSummary();
    saveSelectionSoon();
  });

  row.append(
    input,
    el("span", "checkbox"),
    el("span", "ch-hash", "#"),
    el("span", "ch-name", channel.name)
  );
  return row;
}

/* Roles of the selected server (for @role ping buttons + preview). */
async function loadRoles(guildId) {
  state.roles = [];
  state.roleNames = new Map();
  const chips = $("#roleChips");
  chips.replaceChildren();

  const botQuery = state.activeBotId ? "?bot=" + encodeURIComponent(state.activeBotId) : "";
  const data = await apiGet("/api/roles/" + encodeURIComponent(guildId) + botQuery);
  if (!data.ok) return;

  state.roles = data.roles || [];
  for (const role of state.roles) state.roleNames.set(role.id, role.name);

  const pingable = state.roles.filter((role) => !role.managed).slice(0, 15);
  if (pingable.length) {
    chips.appendChild(el("span", "muted small", "Insert a role ping:"));
    for (const role of pingable) {
      const chip = el("button", "role-chip", "@" + role.name);
      chip.type = "button";
      chip.title = "Click to insert this role ping into the message";
      chip.addEventListener("click", () => {
        const input = $("#f-content");
        const mention = `<@&${role.id}>`;
        const position = input.selectionStart ?? input.value.length;
        input.value = input.value.slice(0, position) + mention + input.value.slice(position);
        state.product.content = input.value;
        input.focus();
        refreshPreviewSoon();
      });
      chips.appendChild(chip);
    }
  }
  refreshPreviewSoon();
}

/* Warning under the server dropdown when permissions are missing. */
function updateGuildWarning() {
  const guild = state.guilds.find((item) => item.id === state.guildId);
  const warning = $("#guildWarning");

  if (guild && guild.missing_permissions) {
    warning.textContent =
      "Heads up: the bot is missing permissions in this server. It needs " +
      "View Channel, Send Messages, Embed Links and Attach Files. " +
      "Re-invite it with the invite link from the README to fix this " +
      "(that is safe - it will not be removed or duplicated).";
    warning.hidden = false;
  } else {
    warning.hidden = true;
  }
}

/* The grey line under the channels. */
function updateSummary() {
  const summary = $("#selectionSummary");
  const list = selectedChannels();

  if (!list.length) {
    summary.textContent = "No channels selected yet.";
    summary.classList.add("muted");
    return;
  }

  summary.classList.remove("muted");
  const names = list.map((channel) => "#" + channel.name);
  const shown = names.slice(0, 4).join(", ");
  const more = names.length > 4 ? ` +${names.length - 4} more` : "";
  summary.textContent = `${list.length} selected: ${shown}${more}`;
}

/* Save the destination quietly (not more than twice a second). */
function saveSelectionSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const result = await apiSend("/api/settings", {
      last_guild_id: state.guildId,
      last_channel_ids: selectedChannels().map((channel) => channel.id),
    });
    if (result.ok) state.settings = result.settings;
    refreshPreviewSoon();
  }, 500);
}

/* Manual fallback: add a channel by pasting its ID. */
async function addManualChannel() {
  const input = $("#manualChannelId");
  const feedback = $("#manualFeedback");
  const id = input.value.trim();

  feedback.textContent = "";
  feedback.className = "manual-feedback";

  if (!/^\d{15,21}$/.test(id)) {
    feedback.textContent =
      "A channel ID is 15-21 digits. Copy it in Discord: Settings > Advanced > " +
      "enable Developer Mode, then right-click the channel > Copy Channel ID.";
    feedback.className = "manual-feedback error";
    return;
  }

  if (selectedChannels().some((channel) => channel.id === id)) {
    feedback.textContent = "That channel is already selected.";
    feedback.className = "manual-feedback error";
    return;
  }

  feedback.textContent = "Checking that channel...";
  feedback.className = "manual-feedback muted";

  const data = await apiGet("/api/lookup-channel/" + encodeURIComponent(id));

  if (!data.ok) {
    feedback.textContent = data.error || "That channel could not be found.";
    feedback.className = "manual-feedback error";
    return;
  }

  const channel = data.channel;
  const label = "#" + channel.name + (channel.guild_name ? " (" + channel.guild_name + ")" : "");
  state.channelNames.set(channel.id, channel.name);

  state.manualChannels.push({ id: channel.id, name: channel.name, label });
  input.value = "";
  feedback.textContent = "Added " + label;
  feedback.className = "manual-feedback ok";

  renderManualChannels();
  updateSummary();
  saveSelectionSoon();
}

function renderManualChannels() {
  const holder = $("#manualChips");
  holder.replaceChildren();

  for (const channel of state.manualChannels) {
    const chip = el("span", "chip", channel.label + " ");
    const remove = el("button", "chip-x", "\u00d7");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove " + channel.label);
    remove.addEventListener("click", () => {
      state.manualChannels = state.manualChannels.filter((item) => item.id !== channel.id);
      renderManualChannels();
      updateSummary();
      saveSelectionSoon();
    });
    chip.appendChild(remove);
    holder.appendChild(chip);
  }
}

/* ---------- settings tab ---------- */

async function saveSettingsPartially(changes) {
  const result = await apiSend("/api/settings", changes);
  if (result.ok) state.settings = result.settings;
  refreshPreviewSoon();
}

function bindSettingsTab() {
  /* the ticket channel dropdown */
  $("#ticket-channel-select").addEventListener("change", async (event) => {
    const value = event.target.value;
    if (value === "manual") {
      /* jump to the manual box instead */
      const manualBox = $("#ticket-manual-id").closest(".manual-box");
      if (manualBox) manualBox.open = true;
      $("#ticket-manual-id").focus();
      /* put the selection back to what it was */
      event.target.value = state.settings.ticket_channel_id || "";
      return;
    }
    await saveSettingsPartially({
      ticket_channel_id: value,
      ticket_channel_name: value ? (state.channelNames.get(value) || "") : "",
    });
    if (value) showToast("Ticket channel saved: #" + state.channelNames.get(value), "success");
  });

  /* add the ticket channel by ID */
  $("#ticket-manual-btn").addEventListener("click", async () => {
    const input = $("#ticket-manual-id");
    const feedback = $("#ticket-manual-fb");
    const id = input.value.trim();

    feedback.className = "manual-feedback";
    if (!/^\d{15,21}$/.test(id)) {
      feedback.textContent = "A channel ID is 15-21 digits (right-click the channel in Discord > Copy Channel ID).";
      feedback.className = "manual-feedback error";
      return;
    }

    feedback.textContent = "Checking that channel...";
    feedback.className = "manual-feedback muted";

    const data = await apiGet("/api/lookup-channel/" + encodeURIComponent(id));
    if (!data.ok) {
      feedback.textContent = data.error || "That channel could not be found.";
      feedback.className = "manual-feedback error";
      return;
    }

    await saveSettingsPartially({
      ticket_channel_id: data.channel.id,
      ticket_channel_name: data.channel.name,
    });
    state.channelNames.set(data.channel.id, data.channel.name);

    input.value = "";
    feedback.textContent = "Saved: #" + data.channel.name;
    feedback.className = "manual-feedback ok";

    /* show it in the dropdown too, if this server is selected */
    const select = $("#ticket-channel-select");
    if (![...select.options].some((option) => option.value === data.channel.id)) {
      const option = el("option", null, "#" + data.channel.name);
      option.value = data.channel.id;
      select.appendChild(option);
    }
    select.value = data.channel.id;
  });

  /* the toggles + ticket line text */
  $("#set-ticket-enabled").addEventListener("change", (event) =>
    saveSettingsPartially({ ticket_line_enabled: event.target.checked }));

  $("#set-ticket-text").addEventListener("input", (event) => {
    clearTimeout(saveSettingsPartially._textTimer);
    saveSettingsPartially._textTimer = setTimeout(() =>
      saveSettingsPartially({ ticket_line_text: event.target.value }), 600);
  });

  $("#set-everyone").addEventListener("change", (event) => {
    saveSettingsPartially({ allow_everyone_mentions: event.target.checked });
    showToast(event.target.checked
      ? "@everyone and @here pings are now allowed - use with care!"
      : "@everyone and @here pings are blocked again (the safe default).");
  });
}

/* Fill the settings tab from what is saved. */
function renderSettingsTab() {
  $("#set-ticket-enabled").checked = state.settings.ticket_line_enabled !== false;
  $("#set-ticket-text").value = state.settings.ticket_line_text ||
    "🎫 **Want to buy?** Open a ticket in {ticket_channel}";
  $("#set-everyone").checked = Boolean(state.settings.allow_everyone_mentions);

  const info = $("#configInfo");
  info.replaceChildren();
  const addLine = (label, value) => {
    const line = el("div");
    line.append(el("strong", null, label + ": "), document.createTextNode(value));
    info.appendChild(line);
  };
  addLine("App", "INDRA BOT SYSTEM - runs 100% on your PC");
  addLine("Your data folder", state.config.data_dir || "data/ (inside the seller-bot folder)");
  addLine("Test channel", state.config.test_channel_set
    ? "#" + state.config.test_channel_id + " (used by the 'Send test' button)"
    : "not set - add TEST_CHANNEL_ID to the .env file to use 'Send test'");
  addLine("LAN access", state.config.allow_lan
    ? "ON - other devices on your Wi-Fi can open the app"
    : "off (only this PC - the safe default)");
}

/* ---------- preview toolbar + misc buttons ---------- */

function bindPreviewToolbar() {
  /* light / dark */
  $("#pv-theme").addEventListener("click", () => {
    const card = $("#previewPane .preview-card");
    const light = card.classList.toggle("light");
    $("#pv-theme").textContent = light ? "☀️" : "🌙";
  });

  /* compact / cozy */
  $("#pv-compact").addEventListener("click", () => {
    $("#previewPane .preview-card").classList.toggle("compact");
  });

  /* full screen (and the mobile FAB) */
  const openOverlay = () => {
    $("#previewPane").classList.add("overlay");
    $("#pv-close").hidden = false;
  };
  const closeOverlay = () => {
    $("#previewPane").classList.remove("overlay");
    $("#pv-close").hidden = true;
  };
  $("#pv-fullscreen").addEventListener("click", () => {
    if ($("#previewPane").classList.contains("overlay")) closeOverlay();
    else openOverlay();
  });
  $("#pv-close").addEventListener("click", closeOverlay);
  $("#fabPreview").addEventListener("click", openOverlay);

  /* send buttons */
  $("#btn-send").addEventListener("click", sendListing);
  $("#btn-send-test").addEventListener("click", sendTest);
  $("#btn-copy-json").addEventListener("click", showCopyJson);

  /* editing banner */
  $("#btnUpdateMessage").addEventListener("click", updateSentMessage);
  $("#btnCancelEdit").addEventListener("click", cancelEditing);

  /* spoilers: click to reveal (event delegation - survives re-renders) */
  $("#previewBody").addEventListener("click", (event) => {
    const spoiler = event.target.closest(".spoiler");
    if (spoiler) spoiler.classList.toggle("revealed");
  });
}

/* ==========================================================================
   PART 12 - Multi-bot: registry, header switcher, Bots page, add wizard
   ==========================================================================

   How it fits together:
     * data/bots.json (on the server) lists every bot WITHOUT secrets.
     * The tokens live only in the .env file on your PC - the server reads
       them at the moment a Discord call is made, and the browser only ever
       sees a masked hint like "\u2022\u2022\u2022\u20221234".
     * One bot is "active" (remembered in settings). The active bot feeds
       the server/channel pickers and the preview header. The little
       "Sending as" select under the preview can override it per message.
   ========================================================================== */

/* Fetch the registry and paint everything that depends on it. */
async function loadBots() {
  const data = await apiGet("/api/bots");
  if (!data.ok) return;
  state.bots = data.bots || [];
  $("#botsCount").textContent = state.bots.length;

  /* Make sure the active bot still exists and is enabled. */
  const usable = state.bots.filter((b) => b.enabled !== false);
  const remembered = state.settings.active_bot_id;
  if (!usable.length) {
    state.activeBotId = "";
  } else if (!usable.some((b) => b.id === remembered)) {
    state.activeBotId = usable[0].id;
  } else {
    state.activeBotId = remembered;
  }

  renderBotMenuItems();
  updateSendAsOptions();
  if (state.activeBotId !== remembered && remembered !== undefined) {
    /* the remembered bot vanished -> quietly save the new default */
    saveSettingsPartially({ active_bot_id: state.activeBotId });
  }
}

/* ---------- the header switcher ---------- */

function renderBotMenuItems() {
  const list = $("#botMenuList");
  if (!list) return;
  list.replaceChildren();

  if (!state.bots.length) {
    list.appendChild(el("div", "bot-menu-empty muted small",
      "No bots yet - add one to start posting."));
    return;
  }

  for (const bot of state.bots) {
    const status = state.botStatus.get(bot.id);
    const item = el("div", "bot-menu-item" +
      (bot.id === state.activeBotId ? " active" : "") +
      (bot.enabled === false ? " disabled" : ""));
    item.setAttribute("role", "menuitem");
    item.tabIndex = 0;

    const avatarWrap = el("span", "bot-avatar-wrap sm");
    if (bot.avatar_url) {
      const img = el("img", "bot-avatar");
      img.src = bot.avatar_url;
      img.alt = "";
      img.addEventListener("error", () => img.replaceWith(el("span", "bot-avatar-fallback", bot.display_name.slice(0, 2).toUpperCase())));
      avatarWrap.appendChild(img);
    } else {
      avatarWrap.appendChild(el("span", "bot-avatar-fallback", bot.display_name.slice(0, 2).toUpperCase()));
    }
    const dotKind = bot.enabled === false ? "off"
      : status ? (status.connected ? "ok" : "error") : "checking";
    avatarWrap.appendChild(el("span", "dot " + dotKind));

    const text = el("span", "bot-menu-text");
    text.appendChild(el("span", "bot-menu-name", bot.display_name));
    const sub = bot.enabled === false ? "disabled"
      : status ? (status.connected ? "connected" : (status.error || "not connected"))
      : bot.kind;
    text.appendChild(el("span", "bot-menu-sub", sub));

    item.append(avatarWrap, text);
    if (bot.id === state.activeBotId) {
      item.appendChild(el("span", "bot-menu-check", "\u2713"));
    }

    const activate = () => { closeBotMenu(); switchBot(bot.id); };
    item.addEventListener("click", activate);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    });
    list.appendChild(item);
  }
}

function openBotMenu() {
  const menu = $("#botMenu");
  menu.hidden = false;
  $("#botSwitcherBtn").setAttribute("aria-expanded", "true");
}

function closeBotMenu() {
  const menu = $("#botMenu");
  if (menu) menu.hidden = true;
  const btn = $("#botSwitcherBtn");
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function bindBotSwitcher() {
  $("#botSwitcherBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    if ($("#botMenu").hidden) { renderBotMenuItems(); openBotMenu(); }
    else closeBotMenu();
  });
  $("#botMenu").addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", closeBotMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeBotMenu();
  });

  $("#botMenuRefresh").addEventListener("click", () => refreshBotStatuses(true));
  $("#botMenuAdd").addEventListener("click", () => { closeBotMenu(); openAddBotWizard(); });
}

/* Switch the whole dashboard to another bot. */
async function switchBot(botId) {
  if (!botId || botId === state.activeBotId) return;
  state.activeBotId = botId;
  state.sendAsBotId = "";          // reset the one-send override

  const record = state.bots.find((b) => b.id === botId);
  setSwitcherState("checking", record ? record.display_name : null,
                   record ? record.avatar_url : null, "connecting...");

  await saveSettingsPartially({ active_bot_id: botId });
  updateSendAsOptions();
  renderBotMenuItems();

  /* every picker now talks as the new bot */
  await Promise.all([loadConnectionStatus(), loadGuilds()]);
  refreshPreviewSoon();
  showToast(`Now working as ${record ? record.display_name : botId}.`, "success");
}

/* Re-check every bot's connection (also fills the Bots page cards). */
async function refreshBotStatuses(loud) {
  const checkable = state.bots.filter((b) => b.enabled !== false);
  if (!checkable.length) return;

  await Promise.allSettled(checkable.map(async (bot) => {
    const data = await apiGet("/api/status?bot=" + encodeURIComponent(bot.id));
    if (data.connected && data.bot) {
      state.botStatus.set(bot.id, {
        connected: true, name: data.bot.name, username: data.bot.username,
        avatar: data.bot.avatar_url, error: null,
      });
    } else {
      state.botStatus.set(bot.id, {
        connected: false, name: null, username: null, avatar: null,
        error: data.error || "not connected",
      });
    }
  }));

  renderBotMenuItems();

  /* keep the switcher in sync when the ACTIVE bot was among them */
  if (state.activeBotId) {
    const status = state.botStatus.get(state.activeBotId);
    if (status && status.connected) {
      setSwitcherState("ok", status.name, status.avatar,
                       "Connected as @" + (status.username || status.name));
      $("#connectionError").hidden = true;
    }
  }

  /* the Bots page also wants the servers each bot is in */
  await Promise.allSettled(checkable.map(async (bot) => {
    const data = await apiGet("/api/guilds?bot=" + encodeURIComponent(bot.id));
    if (data.ok) {
      state.botServers.set(bot.id, (data.guilds || []).map((g) => g.name));
    }
  }));

  renderBotsPage();
  refreshPreviewSoon();
  if (loud) showToast("Connection check finished.", "success");
}

/* ---------- the "Sending as" select under the preview ---------- */

function updateSendAsOptions() {
  const select = $("#sendAsBot");
  if (!select) return;
  select.replaceChildren();

  const usable = state.bots.filter((b) => b.enabled !== false);
  if (!usable.length) {
    const option = el("option", null, "(no bot - add one on the Bots page)");
    option.value = "";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;

  for (const bot of usable) {
    const option = el("option", null, bot.display_name +
      (bot.kind === "seller" ? " \u{1F6CD}\uFE0F" : bot.kind === "messenger" ? " \u{1F4E3}" : ""));
    option.value = bot.id;
    if (bot.id === state.activeBotId) option.textContent += " (active)";
    select.appendChild(option);
  }
  select.value = state.activeBotId || usable[0].id;
  state.sendAsBotId = "";      // stays in sync until the user overrides it

  /* the Sections tab has its own "Sending as" select - keep it in sync */
  const sectionSelect = $("#sectionSendAsBot");
  if (sectionSelect) {
    sectionSelect.replaceChildren(...[...select.options].map((option) => {
      const copy = el("option", null, option.textContent);
      copy.value = option.value;
      return copy;
    }));
    sectionSelect.value = select.value;
  }
}

function bindSendAs() {
  const select = $("#sendAsBot");
  select.addEventListener("change", () => {
    state.sendAsBotId = select.value === state.activeBotId ? "" : select.value;
    refreshPreviewSoon();      // the preview header shows the chosen bot
  });
}

/* ---------- the Bots page ---------- */

function renderBotsPage() {
  const grid = $("#botsGrid");
  if (!grid) return;
  grid.replaceChildren();

  if (!state.bots.length) {
    grid.appendChild(el("div", "bots-empty muted",
      "No bots yet. Click \u201C\uFF0B Add bot\u201D and paste a token from the Discord " +
      "Developer Portal - the app checks it, saves it to .env (never anywhere " +
      "else) and builds the invite link for you."));
    return;
  }

  for (const bot of state.bots) {
    const status = state.botStatus.get(bot.id);
    const card = el("div", "bot-card" + (bot.enabled === false ? " is-disabled" : ""));

    /* -- head: avatar, name, kind, state -- */
    const head = el("div", "bot-card-head");
    const avatarWrap = el("span", "bot-avatar-wrap lg");
    if (bot.avatar_url) {
      const img = el("img", "bot-avatar");
      img.src = bot.avatar_url;
      img.alt = "";
      img.addEventListener("error", () => img.replaceWith(el("span", "bot-avatar-fallback", bot.display_name.slice(0, 2).toUpperCase())));
      avatarWrap.appendChild(img);
    } else {
      avatarWrap.appendChild(el("span", "bot-avatar-fallback", bot.display_name.slice(0, 2).toUpperCase()));
    }
    avatarWrap.appendChild(el("span", "dot " +
      (bot.enabled === false ? "off" : status ? (status.connected ? "ok" : "error") : "checking")));
    head.appendChild(avatarWrap);

    const headText = el("div", "bot-card-title");
    headText.appendChild(el("div", "bot-card-name", bot.display_name));
    const kindLine = el("div", "bot-card-kind");
    kindLine.appendChild(el("span", "tag", bot.kind || "custom"));
    if (bot.enabled === false) kindLine.appendChild(el("span", "tag tag-grey", "disabled"));
    if (status && status.connected) kindLine.appendChild(el("span", "tag tag-green", "\u2713 connected"));
    else if (status && status.error) kindLine.appendChild(el("span", "tag tag-red", "connection problem"));
    headText.appendChild(kindLine);
    head.appendChild(headText);
    card.appendChild(head);

    /* -- status line -- */
    if (status && status.connected) {
      card.appendChild(el("div", "bot-card-status ok",
        "\u2713 Connected as @" + (status.username || status.name || "?")));
    } else if (status && status.error) {
      const err = el("div", "bot-card-status error");
      err.textContent = "\u2717 " + status.error;
      card.appendChild(err);
    } else if (bot.enabled !== false) {
      card.appendChild(el("div", "bot-card-status muted", "Connection not checked yet - press Test connection."));
    } else {
      card.appendChild(el("div", "bot-card-status muted", "Disabled - switch it back on to use it."));
    }

    /* -- servers -- */
    const servers = state.botServers.get(bot.id);
    if (servers && servers.length) {
      const line = el("div", "bot-card-servers");
      line.appendChild(el("span", "muted small", "Servers: "));
      line.appendChild(document.createTextNode(servers.join(", ")));
      card.appendChild(line);
    }

    /* -- token hint (masked) -- */
    card.appendChild(el("div", "bot-card-token muted small",
      `Token: ${bot.token_present ? bot.token_hint : "(missing!)"} \u00B7 key: ${bot.token_env_var}`));

    if (bot.notes) card.appendChild(el("div", "bot-card-notes muted small", bot.notes));

    /* -- buttons -- */
    const actions = el("div", "bot-card-actions");
    const button = (label, className, handler, title) => {
      const node = el("button", "btn btn-sm " + className, label);
      node.type = "button";
      if (title) node.title = title;
      node.addEventListener("click", handler);
      return node;
    };

    actions.append(
      button("\u2713 Test connection", "btn-ghost", () => testBotFromCard(bot), "Ask Discord who this bot is right now"),
      button("\u{1F517} Invite link", "btn-ghost", () => showInviteDialog(bot), "Build the ready-made invite link"),
      button(bot.enabled === false ? "\u25B6\uFE0F Enable" : "\u23F8\uFE0F Disable", "btn-ghost",
             () => toggleBot(bot), "Disabled bots are skipped everywhere"),
      button("\u{1F5D1}\uFE0F Remove", "btn-danger", () => removeBot(bot),
             "Removes the bot and its token line from .env"),
    );
    card.appendChild(actions);
    grid.appendChild(card);
  }
}

/* One card button: live test (also refreshes avatar + servers). */
async function testBotFromCard(bot) {
  showToast("Checking " + bot.display_name + "...");
  const data = await apiSend("/api/bots/" + encodeURIComponent(bot.id) + "/test", {});
  if (data.ok) {
    const index = state.bots.findIndex((b) => b.id === bot.id);
    if (index >= 0) state.bots[index] = data.bot;
    state.botStatus.set(bot.id, {
      connected: true,
      name: data.bot.display_name,
      username: data.bot.display_name,
      avatar: data.bot.avatar_url,
      error: null,
    });
    if (Array.isArray(data.servers)) {
      state.botServers.set(bot.id, data.servers.map((s) => s.name));
    }
    showToast(bot.display_name + " is connected.", "success");
    renderBotsPage();
    renderBotMenuItems();
    if (bot.id === state.activeBotId) loadConnectionStatus();
  } else {
    state.botStatus.set(bot.id, {
      connected: false, name: null, username: null, avatar: null,
      error: data.error || "not connected",
    });
    showToast(data.error || "The connection test failed.", "error");
    renderBotsPage();
    renderBotMenuItems();
  }
}

/* The invite dialog: link + copy button + step-by-step instructions. */
async function showInviteDialog(bot, allowEveryoneOverride) {
  const body = { allow_everyone: Boolean(allowEveryoneOverride || bot.allow_everyone) };
  const data = await apiSend("/api/bots/" + encodeURIComponent(bot.id) + "/invite", body);
  if (!data.ok) { showToast(data.error || "Could not build the invite link.", "error"); return; }

  openModal("Invite " + bot.display_name + " to your server", `
    <p class="muted small">The link asks for exactly the permissions INDRA BOT SYSTEM needs:
    <strong>View Channels, Send Messages, Embed Links, Attach Files, Read Message History</strong>
    ${body.allow_everyone ? "+ <strong>Mention Everyone</strong>" : ""}.</p>
    <div class="field"><label for="inviteUrlBox">Invite link</label>
      <div class="row"><input id="inviteUrlBox" type="text" readonly>
      <button class="btn" id="inviteCopyBtn" type="button">Copy</button></div>
    </div>
    <div class="invite-steps">
      <div class="invite-step"><span class="n">1</span><span>Click <strong>Copy</strong>, then paste the link into your browser and press Enter.</span></div>
      <div class="invite-step"><span class="n">2</span><span>Pick your server in the <strong>Add to Server</strong> dropdown.</span></div>
      <div class="invite-step"><span class="n">3</span><span>Keep all permission boxes ticked and click <strong>Continue</strong>, then <strong>Authorise</strong>.</span></div>
      <div class="invite-step"><span class="n">4</span><span>Done! Back here, press <strong>Test connection</strong> - the bot will now see your server and its channels.</span></div>
    </div>
    <div class="send-row"><button class="btn btn-ghost" id="inviteEveryoneBtn" type="button">${body.allow_everyone ? "Rebuild without Mention Everyone" : "Rebuild with Mention Everyone permission"}</button></div>
  `);

  const box = $("#inviteUrlBox");
  box.value = data.invite_url;
  $("#inviteCopyBtn").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(data.invite_url); showToast("Invite link copied.", "success"); }
    catch { box.select(); showToast("Select the text and copy it manually.", "error"); }
  });
  $("#inviteEveryoneBtn").addEventListener("click", () => {
    showInviteDialog(bot, !body.allow_everyone);
  });
}

/* Enable / disable a bot. */
async function toggleBot(bot) {
  const enable = bot.enabled === false;
  const data = await apiSend("/api/bots/" + encodeURIComponent(bot.id) + "/toggle",
                            { enabled: enable });
  if (!data.ok) { showToast(data.error || "That did not work.", "error"); return; }
  showToast(enable ? bot.display_name + " is back on." : bot.display_name + " is now disabled.", "success");
  await loadBots();

  if (!enable && state.activeBotId === bot.id) {
    /* the active bot was switched off -> fall back to the first enabled one */
    state.settings.active_bot_id = "";
    await loadBots();
    await loadConnectionStatus();
    loadGuilds();
  }
  renderBotsPage();
}

/* Remove a bot (asks first - this deletes its token line from .env). */
async function removeBot(bot) {
  const message = bot.token_env_var === "DISCORD_TOKEN"
    ? `Remove "${bot.display_name}"? Its DISCORD_TOKEN line stays in .env untouched, but the bot disappears from the dashboard.`
    : `Remove "${bot.display_name}"? Its token line (${bot.token_env_var}) is also deleted from your .env file.`;
  if (!confirm(message)) return;

  const data = await apiSend("/api/bots/" + encodeURIComponent(bot.id), {}, "DELETE");
  if (!data.ok) { showToast(data.error || "Removing failed.", "error"); return; }

  showToast("Bot removed.", "success");
  const wasActive = state.activeBotId === bot.id;
  state.botStatus.delete(bot.id);
  state.botServers.delete(bot.id);
  await loadBots();
  if (wasActive) {
    await loadConnectionStatus();
    loadGuilds();
  }
  renderBotsPage();
  updateSendAsOptions();
}

/* ---------- the Add-bot wizard ---------- */

function openAddBotWizard() {
  openModal("Add a bot", `
    <p class="muted small">The token is checked against Discord first, then saved into your
    .env file on this PC. It is <strong>never</strong> stored in the dashboard's data files,
    never shown again, and never sent to any server other than Discord's.</p>
    <div class="field">
      <label for="wizardName">Bot name <span class="label-hint">(shown in the dashboard)</span></label>
      <input id="wizardName" type="text" maxlength="60" placeholder="e.g. Messenger Bot">
    </div>
    <div class="field">
      <label for="wizardKind">What will it do?</label>
      <select id="wizardKind">
        <option value="seller">\u{1F6CD}\uFE0F Seller - posts product listings</option>
        <option value="messenger">\u{1F4E3} Messenger - announcements, rules, updates</option>
        <option value="custom">\u{1F9E9} Custom - everything else</option>
      </select>
    </div>
    <div class="field">
      <label for="wizardToken">Bot token <span class="label-hint">(Developer Portal &gt; your app &gt; Bot &gt; Reset Token)</span></label>
      <input id="wizardToken" type="password" autocomplete="off" placeholder="Paste the token here">
    </div>
    <div class="field">
      <label class="check-label"><input id="wizardEveryone" type="checkbox">
        The invite link may also ask for <strong>Mention Everyone</strong>
        <span class="label-hint">(only tick this if you really plan to use @everyone pings)</span></label>
    </div>
    <div class="send-row">
      <button class="btn" id="wizardAddBtn" type="button">Check token &amp; add bot</button>
    </div>
  `);

  $("#wizardName").focus();
  $("#wizardAddBtn").addEventListener("click", submitAddBotWizard);
  $("#wizardToken").addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitAddBotWizard();
  });
}

async function submitAddBotWizard() {
  const name = $("#wizardName").value.trim();
  const kind = $("#wizardKind").value;
  const token = $("#wizardToken").value.trim();
  const allowEveryone = $("#wizardEveryone").checked;

  if (!name) { showToast("Give the bot a name first.", "error"); $("#wizardName").focus(); return; }
  if (!token) { showToast("Paste the bot token first.", "error"); $("#wizardToken").focus(); return; }

  const button = $("#wizardAddBtn");
  button.disabled = true;
  button.textContent = "Checking the token with Discord...";

  const data = await apiSend("/api/bots", {
    display_name: name, kind, token, allow_everyone: allowEveryone,
  });

  if (!data.ok) {
    button.disabled = false;
    button.textContent = "Check token & add bot";
    showToast(data.error || "Adding the bot failed.", "error");
    return;
  }

  /* Step 2: success + the invite link + instructions */
  await loadBots();
  renderBotsPage();

  openModal("\u2705 " + data.bot.display_name + " was added", `
    <p class="muted small">The token is saved in your .env file under
    <code>${escapeHtml(data.bot.token_env_var)}</code> and will show up masked as
    <code>${escapeHtml(data.bot.token_hint)}</code> from now on. Nothing else was stored.</p>
    <p><strong>One more step:</strong> invite the bot to your server, or it cannot post anything.</p>
    <div class="field"><label for="wizardInviteUrl">Ready-made invite link</label>
      <div class="row"><input id="wizardInviteUrl" type="text" readonly>
      <button class="btn" id="wizardInviteCopy" type="button">Copy</button></div>
    </div>
    <div class="invite-steps">
      <div class="invite-step"><span class="n">1</span><span>Paste the link into your browser and open it.</span></div>
      <div class="invite-step"><span class="n">2</span><span>Pick your server, keep the permission boxes ticked, click <strong>Continue</strong> &gt; <strong>Authorise</strong>.</span></div>
      <div class="invite-step"><span class="n">3</span><span>Come back here and press <strong>Test connection</strong> on the Bots page.</span></div>
    </div>
    <div class="send-row">
      <button class="btn" id="wizardDoneBtn" type="button">Done</button>
      <button class="btn btn-ghost" id="wizardTestNowBtn" type="button">Test connection now</button>
    </div>
  `);

  const urlBox = $("#wizardInviteUrl");
  urlBox.value = data.invite_url || "(invite link needs a connection test first - press Test connection now)";
  $("#wizardInviteCopy").addEventListener("click", async () => {
    if (!data.invite_url) return;
    try { await navigator.clipboard.writeText(data.invite_url); showToast("Invite link copied.", "success"); }
    catch { urlBox.select(); showToast("Select the text and copy it manually.", "error"); }
  });
  $("#wizardDoneBtn").addEventListener("click", () => { closeModal(); switchTab("bots"); });
  $("#wizardTestNowBtn").addEventListener("click", () => {
    closeModal();
    switchTab("bots");
    testBotFromCard(data.bot);
  });

  showToast("Bot added! Invite it to your server with the link.", "success");
}

/* ==========================================================================
   PART 13 - Sections: the Messenger bot's content (announcements, rules...)
   ========================================================================== */

async function loadSections() {
  const data = await apiGet("/api/sections");
  if (data.ok) {
    state.sections = data.sections || [];
    $("#sectionsCount").textContent = state.sections.length;
    renderSectionsGrid();
  }
}

function renderSectionsGrid() {
  const grid = $("#sectionsGrid");
  if (!grid) return;
  grid.replaceChildren();

  if (!state.sections.length) {
    grid.appendChild(el("p", "muted", "No sections yet - press 'New section' and write your first announcement or rule page."));
    return;
  }

  for (const section of state.sections) {
    const isLoaded = state.section && state.section.id === section.id;
    const card = el("div", "section-card" + (isLoaded ? " active" : ""));

    const head = el("div", "section-card-top");
    head.appendChild(el("div", "section-card-name",
      section.name || section.title || "Untitled section"));
    if (section.starter) head.appendChild(el("span", "tag", "starter"));
    if (isLoaded) head.appendChild(el("span", "tag tag-green", "in editor"));
    card.appendChild(head);

    const meta = el("div", "lib-meta");
    meta.appendChild(el("span", null, ({
      clean: "🧹 Clean", announcement: "📣 Announcement",
      rules: "📜 Rules", update: "🆕 Update",
    })[section.preset] || section.preset));
    const theme = state.themes.find((t) => t.id === section.theme_id);
    if (theme) meta.appendChild(el("span", null, theme.name));
    const bot = state.bots.find((b) => b.id === section.bot_id);
    if (bot) meta.appendChild(el("span", "hist-bot-chip", "🤖 " + bot.display_name));
    meta.appendChild(el("span", null, "updated " + prettyDateTime(section.updatedAt)));
    card.appendChild(meta);

    const actions = el("div", "lib-actions-row");
    const loadButton = el("button", "btn btn-sm", "Load & edit");
    loadButton.addEventListener("click", () => {
      if (state.sectionEditContext) { showToast("Finish or cancel editing first.", "error"); return; }
      state.section = JSON.parse(JSON.stringify(section));
      renderSectionForm();
      refreshSectionPreviewSoon();
      showToast("Loaded into the editor below.", "success");
      document.getElementById("sectionForm").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    const sendButton = el("button", "btn btn-sm btn-ghost", "Load & send");
    sendButton.title = "Load it into the editor, then use the Send buttons there";
    sendButton.addEventListener("click", () => {
      state.section = JSON.parse(JSON.stringify(section));
      renderSectionForm();
      refreshSectionPreviewSoon();
      showToast("Loaded - pick channels at the top of the page and press 'Send section'.", "success");
    });
    actions.append(loadButton, sendButton);
    card.appendChild(actions);
    grid.appendChild(card);
  }
}

/* The section form bindings: [input id, section key, kind]. */
const SECTION_BINDINGS = [
  ["s-name", "name", "text"],
  ["s-title", "title", "text"],
  ["s-body", "body", "text"],
  ["s-preset", "preset", "visibility"],
  ["s-theme", "theme_id", "theme"],
  ["s-footer", "footer", "text"],
  ["s-timestamp", "showTimestamp", "checkbox"],
  ["s-content", "content", "text"],
];

function renderSectionForm() {
  for (const [inputId, key] of SECTION_BINDINGS) {
    const input = $("#" + inputId);
    if (!input) continue;
    if (input.type === "checkbox") input.checked = truthy(state.section[key]);
    else input.value = state.section[key] ?? "";
  }
  renderImageSlots();
}

function bindSectionForm() {
  for (const [inputId, key] of SECTION_BINDINGS) {
    const input = $("#" + inputId);
    if (!input) continue;
    input.addEventListener(input.type === "checkbox" || input.tagName === "SELECT"
                           ? "change" : "input",
      () => {
        if (input.type === "checkbox") state.section[key] = input.checked;
        else state.section[key] = input.value;
        refreshSectionPreviewSoon();
      });
  }

  $("#btn-save-section").addEventListener("click", saveCurrentSection);
  $("#btn-duplicate-section").addEventListener("click", duplicateCurrentSection);
  $("#btn-blank-section").addEventListener("click", startBlankSection);
  $("#btn-delete-section").addEventListener("click", deleteCurrentSection);
  $("#btn-new-section").addEventListener("click", startBlankSection);
  $("#btn-refresh-sections").addEventListener("click", loadSections);

  /* sending */
  $("#btn-send-section").addEventListener("click", sendSection);
  $("#btn-send-section-test").addEventListener("click", sendSectionTest);
  $("#btn-section-json").addEventListener("click", () =>
    showCopyJson(state.sectionLastBuild && state.sectionLastBuild.messages,
                 "The exact JSON that will be sent"));

  /* editing banner */
  $("#btn-section-update").addEventListener("click", updateSectionSentMessage);
  $("#btn-section-cancel-edit").addEventListener("click", cancelSectionEditing);

  /* the light/dark toggle of the section preview */
  $("#spv-theme").addEventListener("click", () => {
    const card = $("#sectionPreviewPane .preview-card");
    const light = card.classList.toggle("light");
    $("#spv-theme").textContent = light ? "☀️" : "🌙";
  });

  /* which bot posts this section */
  const sendAs = $("#sectionSendAsBot");
  if (sendAs) {
    sendAs.addEventListener("change", () => {
      state.section.bot_id = sendAs.value === state.activeBotId ? "" : sendAs.value;
      refreshSectionPreviewSoon();
    });
  }
}

async function saveCurrentSection() {
  const section = JSON.parse(JSON.stringify(state.section));
  if (!section.name.trim() && !section.title.trim()) {
    showToast("Give the section a name or a title first.", "error");
    $("#s-name").focus();
    return;
  }
  if (!section.name.trim()) section.name = section.title;
  const result = await apiSend("/api/sections", { section });
  if (result.ok) {
    state.section = result.section;
    showToast("Section saved.", "success");
    loadSections();
  } else {
    showToast(result.error || "Saving failed.", "error");
  }
}

async function duplicateCurrentSection() {
  const copy = JSON.parse(JSON.stringify(state.section));
  copy.id = newId();
  copy.name = (state.section.name || "Section") + " (copy)";
  copy.starter = false;
  state.section = copy;
  renderSectionForm();
  await saveCurrentSection();
  showToast("Working on a duplicate - the original is untouched.", "success");
}

function startBlankSection() {
  if (state.sectionEditContext) { showToast("Finish or cancel editing first.", "error"); return; }
  state.section = newSection();
  renderSectionForm();
  refreshSectionPreviewSoon();
  showToast("Started a blank section.");
}

async function deleteCurrentSection() {
  const name = state.section.name || state.section.title || "this section";
  if (!confirm(`Delete ${name} from your saved sections? ` +
               "(Messages already sent to Discord are NOT deleted.)")) return;
  await apiSend("/api/sections/" + encodeURIComponent(state.section.id), {}, "DELETE");
  state.section = newSection();
  renderSectionForm();
  refreshSectionPreviewSoon();
  loadSections();
  showToast("Section deleted.", "success");
}

/* The section preview (server-rendered, like the builder's). */
let sectionPreviewTimer = null;
let sectionPreviewSequence = 0;

async function refreshSectionPreview() {
  const botId = state.section.bot_id || selectedBotId();
  const myId = ++sectionPreviewSequence;
  const data = await apiSend("/api/preview", {
    content: buildSectionContent(), bot_id: botId,
  });
  if (myId !== sectionPreviewSequence) return;

  if (data && Array.isArray(data.messages)) {
    state.sectionLastBuild = data;
  } else {
    state.sectionLastBuild = { ok: false, messages: [], usage: {},
      errors: [(data && data.error) || "The preview failed."], warnings: [],
      report: { messages: 0, embeds: 0, splits: [] }, bot: null };
  }
  const build = state.sectionLastBuild;

  const body = $("#sectionPreviewBody");
  body.replaceChildren();
  const messages = build.messages || [];
  if (!messages.length) {
    body.appendChild(el("div", "dc-empty muted", "Nothing to preview yet - write a title or some text."));
  }
  messages.forEach((payload, index) => {
    if (index > 0) body.appendChild(el("div", "split-divider",
      `✁ Discord message ${index + 1} of ${messages.length} (auto-split)`));
    renderDiscordMessage(payload, build.bot || botIdentity(), body);
  });
  resolveMentions(body);

  renderSectionPreflight(build);
}

function renderSectionPreflight(build) {
  const destination = $("#secPfDest");
  const targets = selectedChannels();
  if (targets.length) {
    destination.textContent = "Will send to: " +
      targets.slice(0, 3).map((t) => "#" + (t.name || t.id)).join(", ") +
      (targets.length > 3 ? ` +${targets.length - 3} more` : "");
  } else {
    destination.textContent = "No channels selected - pick at least one at the top of the page.";
  }

  const counters = $("#secPfCounters");
  counters.replaceChildren();
  const usage = build.usage || {};
  const chips = [
    ["Title", usage.title || 0, LIMITS.title],
    ["Text", usage.description || 0, LIMITS.description],
    ["Embed total", usage.total || 0, LIMITS.total],
  ];
  for (const [label, value, max] of chips) {
    const chip = el("span", "pf-chip", `${label} ${value}/${max}`);
    if (value > max) chip.classList.add("over");
    counters.appendChild(chip);
  }

  const warningBox = $("#secPfWarnings");
  warningBox.replaceChildren();
  for (const message of (build.errors || [])) {
    warningBox.appendChild(el("div", "pf-warn w-error", "⛔ " + message));
  }
  for (const message of (build.warnings || [])) {
    warningBox.appendChild(el("div", "pf-warn w-warn", "⚠️ " + message));
  }

  const sendButton = $("#btn-send-section");
  sendButton.disabled = Boolean((build.errors || []).length) || !targets.length ||
                        Boolean(state.sectionEditContext);

  const testButton = $("#btn-send-section-test");
  testButton.disabled = Boolean(state.sectionEditContext) || !state.config.test_channel_set;
}

function refreshSectionPreviewSoon() {
  clearTimeout(sectionPreviewTimer);
  sectionPreviewTimer = setTimeout(refreshSectionPreview, 300);
}

async function sendSection() {
  if (state.sectionEditContext) { updateSectionSentMessage(); return; }
  const build = state.sectionLastBuild;
  if ((build && build.errors || []).length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }
  const targets = selectedChannels();
  if (!targets.length) { showToast("Pick at least one channel at the top of the page first.", "error"); return; }

  const button = $("#btn-send-section");
  button.disabled = true;
  button.textContent = "Sending...";

  const result = await apiSend("/api/send", {
    targets,
    content: buildSectionContent(),
    bot_id: state.section.bot_id || selectedBotId(),
  });

  button.disabled = false;
  button.textContent = "Send section";

  if (result.ok) {
    showToast("Section sent!", "success");
    loadHistory();
  } else {
    showToast(result.error || "Sending failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

async function sendSectionTest() {
  const build = state.sectionLastBuild;
  if ((build && build.errors || []).length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }
  const button = $("#btn-send-section-test");
  button.disabled = true;
  button.textContent = "Sending test...";

  const result = await apiSend("/api/send-test", {
    content: buildSectionContent(),
    bot_id: state.section.bot_id || selectedBotId(),
  });

  button.disabled = false;
  button.textContent = "Send test";

  if (result.ok) { showToast("Test sent - check your test channel!", "success"); loadHistory(); }
  else showToast(result.error || "The test send failed.", "error");
}

/* ---- editing a sent section in place ---- */

function updateSectionEditBanner() {
  const banner = $("#sectionEditBanner");
  if (state.sectionEditContext) {
    banner.hidden = false;
    $("#sectionEditBannerText").textContent =
      `You are editing the section sent in #${state.sectionEditContext.channelName || state.sectionEditContext.channelId}. ` +
      "Your changes will be applied to that same Discord message (nothing new is posted).";
  } else {
    banner.hidden = true;
  }
}

function cancelSectionEditing() {
  state.sectionEditContext = null;
  updateSectionEditBanner();
  refreshSectionPreviewSoon();
  showToast("Left editing mode. 'Send section' posts a new message again.");
}

async function updateSectionSentMessage() {
  if (!state.sectionEditContext) return;
  const context = state.sectionEditContext;
  const build = state.sectionLastBuild;
  if ((build && build.errors || []).length) {
    showToast("Fix the problems under the preview first.", "error");
    return;
  }

  const button = $("#btn-section-update");
  button.disabled = true;
  button.textContent = "Updating...";

  const result = await apiSend("/api/messages/update", {
    channel_id: context.channelId,
    history_id: context.historyId,
    content: buildSectionContent(),
    bot_id: context.botId,
    action: "edited",
  });

  button.disabled = false;
  button.textContent = "Update the Discord message";

  if (result.ok) {
    showToast("The Discord message was updated.", "success");
    cancelSectionEditing();
    loadHistory();
  } else {
    showToast(result.error || "Updating failed.", "error");
    if (result.errors) for (const problem of result.errors) showToast(problem, "error");
  }
}

/* ==========================================================================
   PART 14 - Theme Studio: browse, create, duplicate, apply themes
   ========================================================================== */

async function loadThemes() {
  const data = await apiGet("/api/themes");
  if (data.ok) {
    state.themes = data.themes || [];
    fillThemeSelect($("#f-theme"), "✨ Match status color (no theme)");
    fillThemeSelect($("#s-theme"), "✨ Default (blurple)");
    if ($("#f-theme")) $("#f-theme").value = state.product.theme_id || "";
    if ($("#s-theme")) $("#s-theme").value = state.section.theme_id || "";
    updateConditionalFields();
    renderThemesGrid();
  }
}

function renderThemesGrid() {
  const grid = $("#themesGrid");
  if (!grid) return;
  grid.replaceChildren();

  for (const theme of state.themes) {
    const card = el("div", "theme-card" + (theme.builtin ? "" : " is-custom"));

    /* the color preview strip: theme color + a mini embed silhouette */
    const strip = el("div", "theme-strip");
    const swatch = el("div", "theme-swatch");
    swatch.style.background = theme.color || "linear-gradient(90deg,#23a55a,#f0b132,#ed4245)";
    strip.appendChild(swatch);
    const sample = el("div", "theme-sample",
      applyStyle("Aa", theme.title_style || "none"));
    strip.appendChild(sample);
    card.appendChild(strip);

    const name = el("div", "theme-name", theme.name);
    card.appendChild(name);
    if (theme.description) card.appendChild(el("div", "theme-desc muted small", theme.description));
    card.appendChild(el("div", "theme-bits muted small",
      (theme.builtin ? "built-in" : "custom") +
      (theme.author_mode === "bot" ? " · bot author line" : "") +
      (theme.bot_thumbnail ? " · bot thumbnail" : "")));

    const actions = el("div", "theme-actions");
    const button = (label, className, handler, title) => {
      const node = el("button", "btn btn-sm " + className, label);
      node.type = "button";
      if (title) node.title = title;
      node.addEventListener("click", handler);
      return node;
    };

    actions.append(
      button("Use for products", "", () => applyThemeToProduct(theme.id),
             "Apply this theme to the product in the Builder"),
      button("Use for sections", "btn-ghost", () => applyThemeToSection(theme.id),
             "Apply this theme to the section in the editor"),
    );
    if (!theme.builtin) {
      actions.append(button("✏️ Edit", "btn-ghost", () => openThemeEditor(theme)));
    }
    actions.append(
      button("⧉ Duplicate", "btn-ghost", () => duplicateTheme(theme)),
    );
    if (!theme.builtin) {
      actions.append(button("🗑", "btn-danger", () => deleteTheme(theme)));
    }
    card.appendChild(actions);
    grid.appendChild(card);
  }
}

function applyThemeToProduct(themeId) {
  state.product.theme_id = themeId;
  if ($("#f-theme")) $("#f-theme").value = themeId;
  updateConditionalFields();
  refreshPreviewSoon();
  const theme = state.themes.find((t) => t.id === themeId);
  showToast(theme ? `The Builder now uses "${theme.name}".` : "Back to the classic status colors.", "success");
  switchTab("builder");
}

function applyThemeToSection(themeId) {
  state.section.theme_id = themeId;
  if ($("#s-theme")) $("#s-theme").value = themeId;
  refreshSectionPreviewSoon();
  const theme = state.themes.find((t) => t.id === themeId);
  showToast(theme ? `The section editor now uses "${theme.name}".` : "Back to the default look.", "success");
}

async function duplicateTheme(theme) {
  const result = await apiSend("/api/themes/" + encodeURIComponent(theme.id) + "/duplicate", {});
  if (result.ok) {
    showToast(`Copied "${theme.name}" - it is now yours to edit.`, "success");
    await loadThemes();
    const copy = state.themes.find((t) => t.id === result.theme.id);
    if (copy) openThemeEditor(copy);
  } else {
    showToast(result.error || "Copying failed.", "error");
  }
}

async function deleteTheme(theme) {
  if (!confirm(`Delete your custom theme "${theme.name}"? ` +
               "Products and sections using it simply fall back to their own colors.")) return;
  const result = await apiSend("/api/themes/" + encodeURIComponent(theme.id), {}, "DELETE");
  if (result.ok) {
    showToast("Theme deleted.", "success");
    if (state.product.theme_id === theme.id) { state.product.theme_id = ""; if ($("#f-theme")) $("#f-theme").value = ""; refreshPreviewSoon(); }
    if (state.section.theme_id === theme.id) { state.section.theme_id = ""; if ($("#s-theme")) $("#s-theme").value = ""; refreshSectionPreviewSoon(); }
    loadThemes();
  } else {
    showToast(result.error || "Deleting failed.", "error");
  }
}

/* The theme editor modal (create new / edit custom). */
function openThemeEditor(theme) {
  const isNew = !theme;
  const current = theme || {
    name: "", color: "#5865F2", title_style: "none", heading_style: "none",
    author_mode: "none", author_name: "", footer_mode: "product",
    footer_text: "", bot_thumbnail: false, description: "",
  };

  const styleOptions = (selected) => state.fontstyles.map((style) =>
    `<option value="${style.id}" ${style.id === selected ? "selected" : ""}>${escapeHtml(style.sample)}  ${escapeHtml(style.label)}</option>`).join("");

  openModal(isNew ? "Create a custom theme" : `Edit "${current.name}"`, `
    <div class="grid-2">
      <div class="field">
        <label for="themeName">Theme name</label>
        <input id="themeName" type="text" maxlength="40" placeholder="e.g. My Store Look" value="${escapeHtml(current.name)}">
      </div>
      <div class="field">
        <label for="themeColor">Embed bar color <span class="label-hint">(empty = follow status)</span></label>
        <div class="row">
          <input id="themeColor" type="color" value="${current.color || "#5865f2"}">
          <input id="themeColorClear" type="checkbox" ${current.color ? "" : "checked"}>
          <span class="muted small">no fixed color (follow the product status)</span>
        </div>
      </div>
    </div>
    <div class="grid-2">
      <div class="field">
        <label for="themeTitleStyle">Title letters</label>
        <select id="themeTitleStyle">${styleOptions(current.title_style)}</select>
      </div>
      <div class="field">
        <label for="themeHeadingStyle">Field heading letters</label>
        <select id="themeHeadingStyle">${styleOptions(current.heading_style)}</select>
      </div>
    </div>
    <div class="field">
      <label for="themeAuthorMode">Author line (small name + avatar above the title)</label>
      <select id="themeAuthorMode">
        <option value="none" ${current.author_mode === "none" ? "selected" : ""}>No author line</option>
        <option value="bot" ${current.author_mode === "bot" ? "selected" : ""}>The posting bot's name + avatar</option>
        <option value="custom" ${current.author_mode === "custom" ? "selected" : ""}>A custom name...</option>
      </select>
      <input id="themeAuthorName" type="text" maxlength="60" placeholder="Custom author name"
             value="${escapeHtml(current.author_name || "")}" ${current.author_mode === "custom" ? "" : "hidden"}>
    </div>
    <div class="field">
      <label for="themeFooterMode">Footer</label>
      <select id="themeFooterMode">
        <option value="product" ${current.footer_mode === "product" ? "selected" : ""}>Use the product's own footer text</option>
        <option value="custom" ${current.footer_mode === "custom" ? "selected" : ""}>A fixed footer text for every listing...</option>
        <option value="none" ${current.footer_mode === "none" ? "selected" : ""}>No footer at all</option>
      </select>
      <input id="themeFooterText" type="text" maxlength="120" placeholder="e.g. My Store · my.store"
             value="${escapeHtml(current.footer_text || "")}" ${current.footer_mode === "custom" ? "" : "hidden"}>
    </div>
    <div class="field">
      <label class="check-label"><input id="themeBotThumb" type="checkbox" ${current.bot_thumbnail ? "checked" : ""}>
        Use the bot's avatar as thumbnail when a product has none</label>
    </div>
    <div class="send-row">
      <button class="btn" id="themeSaveBtn">${isNew ? "Create theme" : "Save changes"}</button>
    </div>
  `);

  $("#themeAuthorMode").addEventListener("change", (event) => {
    $("#themeAuthorName").hidden = event.target.value !== "custom";
  });
  $("#themeFooterMode").addEventListener("change", (event) => {
    $("#themeFooterText").hidden = event.target.value !== "custom";
  });

  $("#themeSaveBtn").addEventListener("click", async () => {
    const noColor = $("#themeColorClear").checked;
    const body = {
      theme: {
        id: isNew ? "" : current.id,
        name: $("#themeName").value.trim() || "My theme",
        color: noColor ? "" : $("#themeColor").value,
        title_style: $("#themeTitleStyle").value,
        heading_style: $("#themeHeadingStyle").value,
        author_mode: $("#themeAuthorMode").value,
        author_name: $("#themeAuthorName").value.trim(),
        footer_mode: $("#themeFooterMode").value,
        footer_text: $("#themeFooterText").value.trim(),
        bot_thumbnail: $("#themeBotThumb").checked,
        description: "",
      },
    };
    const result = await apiSend("/api/themes", body);
    if (result.ok) {
      closeModal();
      showToast(`Theme "${result.theme.name}" saved.`, "success");
      loadThemes();
    } else {
      showToast(result.error || "Saving the theme failed.", "error");
    }
  });
}

/* ==========================================================================
   PART 15 - The image library popup (reuse any uploaded image anywhere)
   ========================================================================== */

function openImageLibrary(onPick) {
  openModal("Your image library", `
    <p class="muted small">Every image you ever uploaded, on this PC. Click one to use it -
    animated GIFs are marked and never get re-compressed.</p>
    <div id="imgLibGrid" class="img-lib-grid"><p class="muted">Loading...</p></div>
  `);

  apiGet("/api/uploads").then((data) => {
    const grid = $("#imgLibGrid");
    if (!grid) return;
    grid.replaceChildren();

    if (!data.ok) {
      grid.appendChild(el("p", "muted", data.error || "Could not load the library."));
      return;
    }
    const uploads = data.uploads || [];
    if (!uploads.length) {
      grid.appendChild(el("p", "muted",
        "Nothing here yet - upload an image in any image slot first."));
      return;
    }

    for (const upload of uploads) {
      const cell = el("button", "img-lib-cell");
      cell.type = "button";
      cell.title = upload.name +
        (upload.width ? `\n${upload.width}x${upload.height}` : "") +
        `\n${(upload.bytes / 1024).toFixed(0)} KB` + (upload.animated ? " · animated" : "");

      const img = el("img");
      img.alt = "";
      img.src = upload.url;
      img.loading = "lazy";
      cell.appendChild(img);

      const caption = el("span", "img-lib-caption");
      caption.textContent = (upload.animated ? "🎬 " : "") +
        (upload.width ? `${upload.width}×${upload.height}` : upload.name.slice(0, 18));
      cell.appendChild(caption);

      cell.addEventListener("click", () => {
        closeModal();
        onPick({ type: "upload", value: upload.name });
        showToast("Image inserted from your library.", "success");
      });
      grid.appendChild(cell);
    }
  });
}

/* ==========================================================================
   PART 20 - Interactive Discord Buttons (Action Rows)
   ========================================================================== */

function renderButtonsEditor() {
  const container = $("#builderButtonsList");
  if (!container) return;
  container.replaceChildren();

  if (!Array.isArray(state.product.buttons)) state.product.buttons = [];

  if (!state.product.buttons.length) {
    container.appendChild(el("p", "muted small", "No buttons added yet. Click one of the buttons below to add one."));
    return;
  }

  state.product.buttons.forEach((btn, index) => {
    const item = el("div", "button-item");

    const labelInp = el("input");
    labelInp.type = "text";
    labelInp.placeholder = "Label (e.g. 🛒 Buy Now)";
    labelInp.value = btn.label || "";
    labelInp.addEventListener("input", () => {
      btn.label = labelInp.value;
      refreshPreviewSoon();
    });

    const urlInp = el("input");
    urlInp.type = "url";
    urlInp.placeholder = "https://your-store.com/checkout";
    urlInp.value = btn.url || "";
    urlInp.addEventListener("input", () => {
      btn.url = urlInp.value;
      refreshPreviewSoon();
    });

    const delBtn = el("button", "icon-btn", "✕");
    delBtn.type = "button";
    delBtn.title = "Remove button";
    delBtn.addEventListener("click", () => {
      state.product.buttons.splice(index, 1);
      renderButtonsEditor();
      refreshPreviewSoon();
    });

    item.append(labelInp, urlInp, delBtn);
    container.appendChild(item);
  });
}

function bindBuilderButtons() {
  $("#btnAddBuyBtn")?.addEventListener("click", () => {
    if (!Array.isArray(state.product.buttons)) state.product.buttons = [];
    if (state.product.buttons.length >= 5) { showToast("Discord allows at most 5 buttons per action row.", "error"); return; }
    state.product.buttons.push({ label: "🛒 Buy Now", url: "https://", emoji: "🛒", style: "link" });
    renderButtonsEditor();
    refreshPreviewSoon();
  });

  $("#btnAddTicketBtn")?.addEventListener("click", () => {
    if (!Array.isArray(state.product.buttons)) state.product.buttons = [];
    if (state.product.buttons.length >= 5) { showToast("Discord allows at most 5 buttons per action row.", "error"); return; }
    const guildId = selectedGuildId();
    const chId = state.settings.ticket_channel_id || "";
    const ticketUrl = (guildId && chId) ? `https://discord.com/channels/${guildId}/${chId}` : "https://discord.com";
    state.product.buttons.push({ label: "🎫 Open Ticket", url: ticketUrl, emoji: "🎫", style: "link" });
    renderButtonsEditor();
    refreshPreviewSoon();
  });

  $("#btnAddCustomBtn")?.addEventListener("click", () => {
    if (!Array.isArray(state.product.buttons)) state.product.buttons = [];
    if (state.product.buttons.length >= 5) { showToast("Discord allows at most 5 buttons per action row.", "error"); return; }
    state.product.buttons.push({ label: "⭐ Reviews / Vouches", url: "https://", emoji: "⭐", style: "link" });
    renderButtonsEditor();
    refreshPreviewSoon();
  });
}


/* ==========================================================================
   PART 21 - Discord Server Stats & Metrics
   ========================================================================== */

let statsPollTimer = null;

async function loadServerStats(silent = false) {
  const guildId = selectedGuildId();
  if (!guildId) {
    $("#statMembers").textContent = "--";
    $("#statOnline").textContent = "--";
    $("#statBoosts").textContent = "--";
    $("#statTier").textContent = "Level --";
    $("#statChannelsRoles").textContent = "-- / --";
    return;
  }
  const botId = state.activeBotId || "";
  const q = botId ? "?bot=" + encodeURIComponent(botId) : "";
  const data = await apiGet("/api/guild-stats/" + encodeURIComponent(guildId) + q);
  if (data.ok && data.stats) {
    const s = data.stats;
    const prevMembers = $("#statMembers").textContent;
    const newMembers = Number(s.approximate_member_count || 0).toLocaleString();
    const prevOnline = $("#statOnline").textContent;
    const newOnline = Number(s.approximate_presence_count || 0).toLocaleString();

    if (prevMembers !== "--" && prevMembers !== newMembers) {
      $("#statMembers").classList.remove("stat-updated");
      void $("#statMembers").offsetWidth;
      $("#statMembers").classList.add("stat-updated");
    }
    if (prevOnline !== "--" && prevOnline !== newOnline) {
      $("#statOnline").classList.remove("stat-updated");
      void $("#statOnline").offsetWidth;
      $("#statOnline").classList.add("stat-updated");
    }

    $("#statMembers").textContent = newMembers;
    $("#statOnline").textContent = newOnline;
    $("#statBoosts").textContent = s.premium_subscription_count || 0;
    $("#statTier").textContent = "Level " + (s.premium_tier || 0);
    $("#statChannelsRoles").textContent = `${s.channels_count || 0} / ${s.roles_count || 0}`;

    const badge = $("#guildLiveStatsBadge");
    if (badge) {
      badge.textContent = `👥 ${newMembers} members • 🟢 ${newOnline} online`;
      badge.style.display = "inline-flex";
    }

    const sel = $("#statsChannelSelect");
    if (sel && (!sel.children.length || sel.children.length <= 1)) {
      sel.replaceChildren();
      sel.appendChild(el("option", null, "Select channel to post stats..."));
      for (const ch of state.allChannels || []) {
        if (ch.type === 0 || ch.type === 5) {
          const opt = el("option", null, "#" + ch.name);
          opt.value = ch.id;
          sel.appendChild(opt);
        }
      }
    }
  } else if (!silent) {
    showToast(data.error || "Could not fetch server stats.", "error");
  }
}

function startStatsAutoPoll() {
  clearInterval(statsPollTimer);
  statsPollTimer = setInterval(() => {
    if (document.visibilityState === "visible" && selectedGuildId()) {
      loadServerStats(true);
    }
  }, 10000); // 10 seconds live sync
}

async function postServerStatsCard() {
  const guildId = selectedGuildId();
  const channelId = $("#statsChannelSelect")?.value;
  if (!guildId || !channelId) {
    showToast("Please pick a destination channel first.", "error");
    return;
  }
  const botId = state.activeBotId || "";
  const q = botId ? "?bot=" + encodeURIComponent(botId) : "";
  const res = await apiSend("/api/server-stats/post" + q, { guild_id: guildId, channel_id: channelId });
  if (res.ok) {
    showToast("Server statistics card posted to Discord!", "success");
  } else {
    showToast(res.error || "Failed to post server stats.", "error");
  }
}

function bindServerStats() {
  $("#btnRefreshStats")?.addEventListener("click", () => loadServerStats(false));
  $("#btnPostStatsCard")?.addEventListener("click", postServerStatsCard);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && selectedGuildId()) {
      loadServerStats(true);
    }
  });
  startStatsAutoPoll();
}


/* ==========================================================================
   PART 22 - Customer Vouches & Reviews Generator
   ========================================================================== */

async function loadVouches() {
  const data = await apiGet("/api/vouches");
  if (data.ok) {
    state.vouches = data.vouches || [];
    $("#vouchesCount").textContent = state.vouches.length;
    renderVouchesList();
  }

  const sel = $("#v-channel");
  if (sel) {
    sel.replaceChildren();
    sel.appendChild(el("option", null, "Select #vouches or #reviews channel..."));
    for (const ch of state.allChannels || []) {
      if (ch.type === 0 || ch.type === 5) {
        const opt = el("option", null, "#" + ch.name);
        opt.value = ch.id;
        sel.appendChild(opt);
      }
    }
  }
  updateVouchPreview();
}

function updateVouchPreview() {
  const container = $("#vouchPreviewBody");
  if (!container) return;
  container.replaceChildren();

  const buyer = $("#v-buyer")?.value || "Buyer#1234";
  const product = $("#v-product")?.value || "Digital Product";
  const rating = parseInt($("#v-rating")?.value || "5", 10);
  const verified = $("#v-verified")?.checked ?? true;
  const review = $("#v-review")?.value || "Instant delivery, great seller!";
  const image = $("#v-image")?.value || "";

  const stars = "⭐".repeat(rating);
  const embed = {
    title: `⭐ Customer Review • ${stars}`,
    description: `> ${review}\n`,
    color: 0xF0B132,
    fields: [
      { name: "👤 Buyer", value: `**${buyer}**` + (verified ? " `[Verified Buyer ✅]`" : ""), inline: true },
      { name: "📦 Product", value: `**${product}**`, inline: true },
      { name: "⭐ Rating", value: `${stars} \`(${rating}/5)\``, inline: true },
    ],
    footer: { text: "INDRA BOT SYSTEM • Customer Feedback & Vouches" },
    timestamp: new Date().toISOString(),
  };
  if (image) embed.image = { url: image };

  renderDiscordMessage({ embeds: [embed] }, botIdentity(), container);
}

function renderVouchesList() {
  const list = $("#vouchesList");
  if (!list) return;
  list.replaceChildren();

  if (!state.vouches || !state.vouches.length) {
    list.appendChild(el("p", "muted small", "No saved vouches yet. Fill the form above and click 'Post Vouch to Discord'."));
    return;
  }

  state.vouches.forEach((v) => {
    const card = el("div", "hist-card");
    const top = el("div", "hist-top");
    top.appendChild(el("strong", null, v.customer_name));
    top.appendChild(el("span", "tag tag-amber", "⭐".repeat(v.rating)));
    
    const body = el("div", "muted small", v.review);
    const actions = el("div", "hist-actions");
    const delBtn = el("button", "btn btn-danger btn-sm", "Delete");
    delBtn.type = "button";
    delBtn.addEventListener("click", async () => {
      if (confirm("Delete this vouch?")) {
        await apiSend("/api/vouches/" + encodeURIComponent(v.id), {}, "DELETE");
        loadVouches();
      }
    });
    actions.appendChild(delBtn);

    card.append(top, body, actions);
    list.appendChild(card);
  });
}

async function postVouch() {
  const buyer = $("#v-buyer").value.trim();
  const review = $("#v-review").value.trim();
  const channelId = $("#v-channel").value;

  if (!buyer) { showToast("Enter customer name first.", "error"); return; }
  if (!review) { showToast("Enter review text first.", "error"); return; }
  if (!channelId) { showToast("Select a destination channel for this vouch.", "error"); return; }

  const vouch = {
    customer_name: buyer,
    product_name: $("#v-product").value.trim(),
    rating: parseInt($("#v-rating").value, 10),
    verified_buyer: $("#v-verified").checked,
    review: review,
    image_url: $("#v-image").value.trim(),
  };

  const res = await apiSend("/api/vouches/send", {
    vouch,
    channel_id: channelId,
    bot_id: state.activeBotId || ""
  });

  if (res.ok) {
    showToast("Vouch card posted to Discord!", "success");
    await apiSend("/api/vouches", { vouch });
    loadVouches();
  } else {
    showToast(res.error || "Failed to post vouch.", "error");
  }
}

async function saveVouchDraft() {
  const buyer = $("#v-buyer").value.trim();
  const review = $("#v-review").value.trim();
  if (!buyer || !review) {
    showToast("Fill in buyer name and review text to save.", "error");
    return;
  }
  const vouch = {
    customer_name: buyer,
    product_name: $("#v-product").value.trim(),
    rating: parseInt($("#v-rating").value, 10),
    verified_buyer: $("#v-verified").checked,
    review: review,
    image_url: $("#v-image").value.trim(),
  };
  const res = await apiSend("/api/vouches", { vouch });
  if (res.ok) {
    showToast("Vouch saved to list.", "success");
    loadVouches();
  } else {
    showToast(res.error || "Failed to save vouch.", "error");
  }
}

function bindVouches() {
  $("#btnPostVouch")?.addEventListener("click", postVouch);
  $("#btnSaveVouchDraft")?.addEventListener("click", saveVouchDraft);

  ["#v-buyer", "#v-product", "#v-rating", "#v-verified", "#v-review", "#v-image"].forEach((sel) => {
    $(sel)?.addEventListener("input", updateVouchPreview);
    $(sel)?.addEventListener("change", updateVouchPreview);
  });
}


/* ==========================================================================
   PART 23 - Full Store Backup & Restore
   ========================================================================== */

function bindBackupRestore() {
  const restoreBtn = $("#btnRestoreBackup");
  const fileInput = $("#fileRestoreBackup");
  if (!restoreBtn || !fileInput) return;

  restoreBtn.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;

    if (!confirm("Restoring this backup will replace current settings and data (a safety backup will be created automatically). Continue?")) {
      fileInput.value = "";
      return;
    }

    const formData = new FormData();
    formData.append("backup", file);

    try {
      showToast("Restoring backup...", "info");
      const resp = await fetch("/api/backup/restore", { method: "POST", body: formData });
      const data = await resp.json();
      if (data.ok) {
        showToast(`Backup restored successfully (${data.restored_count} files)! Reloading...`, "success");
        setTimeout(() => window.location.reload(), 1500);
      } else {
        showToast(data.error || "Failed to restore backup.", "error");
      }
    } catch (err) {
      showToast("Failed to upload backup: " + err.message, "error");
    } finally {
      fileInput.value = "";
    }
  });
}

/* ---------- start-up ---------- */

async function init() {
  /* tabs */
  for (const tab of $$(".tab")) {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  }

  /* modal close */
  $("#modalClose").addEventListener("click", closeModal);
  $("#modalBack").addEventListener("click", (event) => {
    if (event.target === $("#modalBack")) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#modalBack").hidden) closeModal();
    /* Ctrl+Enter sends (or updates, while editing) */
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      if (!$("#modalBack").hidden) return;
      const sectionsActive = !$("#tab-sections").hidden;
      if (sectionsActive && state.sectionEditContext) updateSectionSentMessage();
      else if (sectionsActive) sendSection();
      else if (state.editContext) updateSentMessage();
      else sendListing();
    }
  });

  /* destination card */
  $("#statusRetry").addEventListener("click", loadConnectionStatus);
  $("#refreshGuilds").addEventListener("click", loadGuilds);
  $("#checkChannelBtn").addEventListener("click", addManualChannel);
  $("#manualChannelId").addEventListener("keydown", (event) => {
    if (event.key === "Enter") addManualChannel();
  });
  $("#guildSelect").addEventListener("change", async (event) => {
    await loadChannels(event.target.value);
    saveSelectionSoon();
  });

  /* bots page buttons */
  $("#btn-add-bot").addEventListener("click", openAddBotWizard);
  $("#btn-refresh-bots").addEventListener("click", async () => {
    await loadBots();
    renderBotsPage();
    refreshBotStatuses(true);
  });

  /* themes page buttons */
  $("#btn-new-theme").addEventListener("click", () => openThemeEditor(null));
  $("#btn-refresh-themes").addEventListener("click", loadThemes);

  /* library / history / schedules buttons */
  $("#btn-import").addEventListener("click", () => $("#file-import").click());
  $("#file-import").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const products = Array.isArray(parsed) ? parsed : parsed.products;
      const result = await apiSend("/api/products/import", { products });
      if (result.ok) {
        showToast(`Imported ${result.added} product${result.added === 1 ? "" : "s"}.`, "success");
        loadLibrary();
      } else {
        showToast(result.error || "That file could not be imported.", "error");
      }
    } catch {
      showToast("That file is not valid JSON.", "error");
    }
  });
  $("#btn-export-all").addEventListener("click", () => {
    window.location.href = "/api/products/export";
  });
  $("#btn-refresh-history").addEventListener("click", loadHistory);
  $("#sch-create").addEventListener("click", createSchedule);

  /* form + settings + preview + bots + sections + plans */
  bindForm();
  bindPlanQuickAdd();
  bindImageSlots();
  bindSettingsTab();
  bindPreviewToolbar();
  bindBotSwitcher();
  bindSendAs();
  bindSectionForm();
  bindBuilderButtons();
  bindServerStats();
  bindVouches();
  bindBackupRestore();
  bindAdminSecurity();

  /* load everything: config -> looks -> settings -> bots -> pickers + lists */
  const configData = await apiGet("/api/config");
  if (configData.ok) state.config = configData;

  const settingsData = await apiGet("/api/settings");
  if (settingsData.ok && settingsData.settings) state.settings = settingsData.settings;

  /* the looks (font styles + themes) must be in before the forms render,
     because the selects are filled from them */
  const [stylesData] = await Promise.all([apiGet("/api/fontstyles"), loadThemes()]);
  if (stylesData && stylesData.ok) {
    state.fontstyles = stylesData.styles || [];
    fillFontstyleSelect();
  }

  renderForm();
  renderSectionForm();
  renderSettingsTab();
  renderPreview();
  refreshSectionPreviewSoon();

  await loadBots();                      // must come before the connection check
  updateSendAsOptions();
  await Promise.all([loadConnectionStatus(), loadGuilds(), loadLibrary(),
                     loadHistory(), loadSchedules(), loadSections()]);
  refreshBotStatuses(false);              // fill the dots on the Bots page quietly

  /* open the tab you had open last time */
  const lastTab = localStorage.getItem("sb-last-tab");
  if (lastTab && $("#tab-" + lastTab)) switchTab(lastTab);
}

function bindAdminSecurity() {
  const emailInput = $("#adminSecEmail");
  const currPwdInput = $("#adminSecCurrentPwd");
  const newPwdInput = $("#adminSecNewPwd");
  const saveBtn = $("#btnSaveAdminSecurity");
  const feedback = $("#adminSecurityFeedback");

  async function loadAdminMe() {
    const res = await apiGet("/api/auth/me");
    if (res.ok && res.email) {
      if (emailInput) emailInput.value = res.email;
      const topbarEmail = $("#topbarAdminEmail");
      if (topbarEmail) topbarEmail.textContent = res.email;
    }
  }
  loadAdminMe();

  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const email = (emailInput ? emailInput.value : "").trim();
      const current_password = currPwdInput ? currPwdInput.value : "";
      const new_password = newPwdInput ? newPwdInput.value : "";

      if (!current_password) {
        if (feedback) {
          feedback.className = "alert alert-error small";
          feedback.textContent = "Please enter your current password to confirm changes.";
          feedback.style.display = "block";
        }
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = "Updating...";
      const res = await apiSend("/api/auth/update-credentials", {
        new_email: email,
        current_password,
        new_password
      });
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 Update Admin Credentials";

      if (res.ok) {
        showToast("Admin credentials updated successfully!", "success");
        if (currPwdInput) currPwdInput.value = "";
        if (newPwdInput) newPwdInput.value = "";
        if (feedback) {
          feedback.className = "alert alert-success small";
          feedback.textContent = "Admin credentials updated successfully.";
          feedback.style.display = "block";
        }
        const topbarEmail = $("#topbarAdminEmail");
        if (topbarEmail && res.email) topbarEmail.textContent = res.email;
      } else {
        if (feedback) {
          feedback.className = "alert alert-error small";
          feedback.textContent = res.error || "Failed to update admin credentials.";
          feedback.style.display = "block";
        }
        showToast(res.error || "Update failed", "error");
      }
    });
  }
}

document.addEventListener("DOMContentLoaded", init);

