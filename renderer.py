"""
renderer.py - THE single source of truth for what gets posted to Discord.

WHY DOES THIS FILE EXIST?
  In the first version of SELLER BOT, the BROWSER built the Discord
  message (the embed JSON) and both the preview and the send button used
  that. That meant the same rules (Discord's limits, the ticket line,
  price formatting...) lived in two places, and "what you see" could drift
  away from "what you send".

  Now there is exactly ONE builder: this one, on the server.

      content model  +  theme  +  bot identity  +  settings
              |
              v
        renderer.render_content()
              |
              v
   exact message payloads (the same ones the preview shows)

  The browser sends a "content model" (a plain description of WHAT the
  message contains) and gets back ready-made Discord payloads. The
  preview shows those payloads, and Send posts those payloads. Perfect
  WYSIWYG, always.

WHAT IS A CONTENT MODEL?
  A dictionary that describes the message, not its Discord layout:

    { "kind": "product" | "section", "name"/"title", "tagline"/"body",
      "preset": "modern" | "minimal" | "banner" | "flash"     (products)
                "clean" | "announcement" | "rules" | "update" (sections)
      "plans": [ {"label": "1 Month Key", "price": "4.99",
                  "oldPrice": "7.99", "badge": "POPULAR"} ],
      ... features, images, footer, ticket line settings, theme_id ... }

  Old products from earlier versions (single price/oldPrice fields, no
  plans) are accepted unchanged - they are normalized to a one-plan
  product automatically, so old history entries stay editable.

DISCORD'S LIMITS AND THE AUTO-SPLIT
  A single embed allows: title 256, description 4096, 25 fields
  (name 256 / value 1024), footer 2048, author 256. A message allows
  10 embeds, 6000 characters across all embeds, and 2000 characters of
  plain text. When a listing outgrows those numbers, render_content()
  splits it for you - extra description becomes extra embeds, extra
  fields flow into a follow-up card, and when a message is full a new
  message is started. Every split is noted in the "report" so the
  preview can show "Message 1 of 2" dividers.

A quick tour of this file:
  * constants (status colors, bullets, the gallery trick)
  * small text helpers (prices, plans, delivery, the ticket line)
  * content normalization (fills defaults, accepts old shapes)
  * the four product presets + the four section presets
  * the auto-split packer
  * render_content() - the one public entry point
"""

import re
from datetime import datetime, timezone

import fontstyles
import themes as themes_store   # only used for theme lookup by callers

# ---------------------------------------------------------------------------
# Discord's official limits (the packer guarantees every one of them)
# ---------------------------------------------------------------------------

LIMITS = {
    "title": 256,
    "description": 4096,
    "fieldName": 256,
    "fieldValue": 1024,
    "fields": 25,
    "footer": 2048,
    "author": 256,
    "content": 2000,
    "total": 6000,        # all embeds of one message together
    "embeds": 10,         # embeds per message
}

# The four product statuses: embed color + the line shown in the embed.
STATUS_META = {
    "available":  {"color": 0x23A55A, "label": "Available",    "line": "✅ **Available now**"},
    "limited":    {"color": 0xF0B132, "label": "Limited",      "line": "⚠️ **Limited stock**"},
    "sold_out":   {"color": 0xED4245, "label": "Sold out",     "line": "❌ **SOLD OUT**"},
    "coming_soon": {"color": 0x5865F2, "label": "Coming soon", "line": "🕓 **Coming soon**"},
}

# Bullet styles for the features list.
BULLETS = {
    "checkmark": "✅",
    "sparkles": "✨",
    "fire": "🔥",
    "arrow": "➡️",
    "bullet": "•",
}

# The gallery trick: embeds that share the same "url" get grouped by
# Discord, and their images are shown as one grid. This is that url.
GALLERY_URL = "https://discord.com"

# The small divider line some presets put between description and fields.
DIVIDER = "\u200b\u200b\u200b"


def char_count(text):
    """Count characters the way Discord does (by letters, not bytes)."""
    return len(list(str(text or "")))


def _first_float(value):
    """A number from free text ("4.99" -> 4.99), or None."""
    try:
        number = float(str(value).strip())
        return number if number == number else None      # NaN check
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Content normalization
# ---------------------------------------------------------------------------

def _norm_slot(slot):
    """An image slot: {"type": "none"|"url"|"upload", "value": "..."}."""
    if isinstance(slot, dict):
        kind = slot.get("type")
        value = str(slot.get("value") or "").strip()
        if kind in ("url", "upload") and value:
            return {"type": kind, "value": value}
    return {"type": "none", "value": ""}


def _norm_plans(content):
    """
    The pricing plans of a product, always a clean list of dicts.

    New products carry an explicit "plans" list. Old products (and old
    history snapshots) only have "price" / "oldPrice" - those become a
    single plan called "Standard", so every old listing still renders
    exactly the way it did.
    """
    plans = []
    raw = content.get("plans")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:80]
            if not label:
                continue
            plans.append({
                "id": str(item.get("id") or "")[:40] or ("plan-" + str(len(plans) + 1)),
                "label": label,
                "price": str(item.get("price") or "").strip()[:24],
                "oldPrice": str(item.get("oldPrice") or "").strip()[:24],
                "badge": str(item.get("badge") or "").strip()[:24],
            })
    if not plans:
        # legacy single-price product -> one plan
        price = str(content.get("price") or "").strip()[:24]
        old = str(content.get("oldPrice") or "").strip()[:24]
        if price or old:
            plans.append({"id": "standard", "label": "Standard",
                          "price": price, "oldPrice": old, "badge": ""})
    return plans[:10]        # hard cap: 10 plans keep every layout readable


def normalize_content(content):
    """
    Fill in every default so the rest of the renderer can trust the data.
    Accepts the current shape AND all older product shapes.
    """
    content = dict(content or {})
    content["kind"] = "section" if content.get("kind") == "section" else "product"
    content["plans"] = _norm_plans(content)
    content["currency"] = str(content.get("currency") or "").strip()[:5]
    content["theme_id"] = str(content.get("theme_id") or "").strip()[:40]
    content["preset"] = str(content.get("preset") or "").strip() or (
        "clean" if content["kind"] == "section" else "modern")
    content["status"] = content.get("status") if content.get("status") in STATUS_META \
        else "available"
    content["fancyText"] = content.get("fancyText") in (True, "true", 1)
    content["fancyStyle"] = fontstyles.normalize_style(content.get("fancyStyle"))
    content["showTimestamp"] = content.get("showTimestamp") in (True, "true", 1, None) \
        if content.get("showTimestamp") is None else \
        content.get("showTimestamp") in (True, "true", 1)

    for key in ("mainImage", "thumbnail", "image"):
        content[key] = _norm_slot(content.get(key))
    gallery = content.get("gallery")
    content["gallery"] = ([_norm_slot(item) for item in gallery]
                          if isinstance(gallery, list) else [])
    content["gallery"] = [slot for slot in content["gallery"]
                          if slot["type"] != "none"][:4]

    # sections: body instead of tagline+features
    content["title"] = str(content.get("title") or content.get("name") or "").strip()
    content["body"] = str(content.get("body") or "").strip()

    for key in ("name", "tagline", "features", "included", "requirements",
                "refund", "footer", "content", "license", "stock",
                "deliveryHours", "bulletCustom"):
        content[key] = str(content.get(key) or "").strip()
    content["category"] = str(content.get("category") or "").strip()
    content["categoryCustom"] = str(content.get("categoryCustom") or "").strip()
    content["delivery"] = content.get("delivery") if content.get("delivery") in \
        ("instant", "manual", "hours") else "instant"
    content["bulletStyle"] = content.get("bulletStyle") if content.get("bulletStyle") in BULLETS \
        else ("custom" if content.get("bulletStyle") == "custom" else "checkmark")
    content["saleEnds"] = str(content.get("saleEnds") or "").strip()
    content["ticketLineMode"] = content.get("ticketLineMode") if content.get("ticketLineMode") in \
        ("global", "show", "hide") else ("hide" if content["kind"] == "section" else "global")
    content["ticketLineText"] = str(content.get("ticketLineText") or "").strip()
    content["planLayout"] = content.get("planLayout") if content.get("planLayout") in ("list", "stacked", "grid") else "list"

    raw_buttons = content.get("buttons")
    buttons = []
    if isinstance(raw_buttons, list):
        for b in raw_buttons:
            if isinstance(b, dict):
                lbl = str(b.get("label") or "").strip()[:80]
                u = str(b.get("url") or "").strip()
                if lbl and u:
                    buttons.append({
                        "label": lbl,
                        "url": u,
                        "emoji": str(b.get("emoji") or "").strip()[:10],
                        "style": "link",
                    })
    content["buttons"] = buttons[:5]
    return content


# ---------------------------------------------------------------------------
# Price / plan / label helpers
# ---------------------------------------------------------------------------

def _plan_price_display(plan, currency):
    """One plan's price as markdown: ~~$7.99~~ **$4.99** (🔥 -38% OFF)."""
    price = plan["price"]
    old = plan["oldPrice"]
    if not price:
        return "**Free**"
    price_number, old_number = _first_float(price), _first_float(old)
    discount = (round((1 - price_number / old_number) * 100)
                if price_number is not None and old_number is not None
                and old_number > price_number >= 0 else None)
    if discount is not None:
        return f"~~{currency}{old}~~ **{currency}{price}** (🔥 **-{discount}% OFF**)"
    return f"**{currency}{price}**"


def price_display(content):
    """The headline price (first plan / single plan)."""
    plans = content["plans"]
    currency = content["currency"]
    if not plans:
        return "**Free**"
    return _plan_price_display(plans[0], currency)


def plans_price_line(content):
    """All plans as one text block (used by the Minimal preset and List layout)."""
    currency = content["currency"]
    lines = []
    for plan in content["plans"]:
        badge = f" `[{plan['badge']}]`" if plan.get("badge") else ""
        lines.append(f"• **{plan['label']}**{badge} ── {_plan_price_display(plan, currency)}")
    return "\n".join(lines)


def plain_price(content):
    """The {price} placeholder text: single plan, or 'from' the cheapest."""
    plans = [plan for plan in content["plans"] if plan["price"]] or content["plans"]
    currency = content["currency"]
    if not plans:
        return "Free"
    if len(plans) == 1:
        return (currency + plans[0]["price"]) if plans[0]["price"] else "Free"
    prices = [_first_float(plan["price"]) for plan in plans]
    prices = [value for value in prices if value is not None]
    if prices:
        cheapest = min(prices)
        pretty = ("%g" % cheapest)
        return f"from {currency}{pretty}"
    return "Free"


def cheapest_price(content):
    """The lowest numeric price (for the Big Banner headline), or None."""
    prices = [_first_float(plan["price"]) for plan in content["plans"]]
    prices = [value for value in prices if value is not None]
    return min(prices) if prices else None


def delivery_label(content):
    if content["delivery"] == "manual":
        return "🧑‍🔧 Manual delivery"
    if content["delivery"] == "hours":
        return f"⏱️ Within {content['deliveryHours'] or '24'} hours"
    return "⚡ Instant delivery"


def category_label(content):
    if content["category"] == "custom":
        return content["categoryCustom"].strip()
    return content["category"]


def sale_ends_unix(content):
    """The 'sale ends' moment as a UNIX timestamp (None when not set/invalid)."""
    raw = content["saleEnds"]
    if not raw:
        return None
    try:
        date = datetime.fromisoformat(str(raw))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return int(date.timestamp())
    except ValueError:
        return None


def ticket_line(content, settings):
    """
    The "open a ticket" line - by app promise the LAST thing in a listing.
    Sold-out products show ❌ SOLD OUT instead. Sections never show it
    (their default ticketLineMode is "hide").
    """
    settings = settings or {}
    if content["kind"] == "product" and content["status"] == "sold_out":
        return "❌ **SOLD OUT**"

    mode = content["ticketLineMode"]
    if mode == "hide":
        return None
    enabled = mode == "show" or settings.get("ticket_line_enabled", True)
    if not enabled:
        return None

    text = (content["ticketLineText"] or
            str(settings.get("ticket_line_text") or "").strip() or
            "🎫 **Want to buy?** Open a ticket in {ticket_channel}")

    mention = (f"<#{settings['ticket_channel_id']}>"
               if str(settings.get("ticket_channel_id") or "").strip()
               else "**#ticket-channel**")

    return (text
            .replace("{ticket_channel}", mention)
            .replace("{product}", content.get("name") or "this product")
            .replace("{price}", plain_price(content)))


# ---------------------------------------------------------------------------
# Theme merging
# ---------------------------------------------------------------------------

def merge_theme(content, theme):
    """
    The effective styling for one content item. Product settings win over
    the theme; the theme wins over the plain defaults. Returns a dict with
    color, title_style, heading_style, author {name, icon_url}, footer_text,
    and whether the bot avatar should be used as a thumbnail.
    """
    theme = theme or {}
    content = content if isinstance(content, dict) else {}

    # -- the left bar color ---------------------------------------------
    color_hex = str(theme.get("color") or "").strip()
    theme_color = None
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color_hex):
        theme_color = int(color_hex[1:], 16)

    # -- letter styles ----------------------------------------------------
    # the product's own "fancy text" wins over the theme's styles
    if content.get("fancyText") in (True, "true", 1):
        title_style = content.get("fancyStyle")
        heading_style = content.get("fancyStyle")
    else:
        title_style = theme.get("title_style") or "none"
        heading_style = theme.get("heading_style") or "none"

    # -- author line -----------------------------------------------------
    author = None
    if theme.get("author_mode") == "bot":
        author = "bot"
    elif theme.get("author_mode") == "custom" and theme.get("author_name"):
        author = {
            "name": str(theme.get("author_name") or "")[:256],
            "icon_url": str(theme.get("author_icon") or "").strip(),
        }

    # -- footer text -----------------------------------------------------
    footer_text = content.get("footer")
    if not footer_text and theme.get("footer_text"):
        footer_text = theme.get("footer_text")

    return {
        "color": theme_color,
        "title_style": title_style,
        "heading_style": heading_style,
        "author": author,
        "footer_text": str(footer_text or "")[:2048],
        "bot_thumbnail": bool(theme.get("bot_thumbnail")),
    }


# ---------------------------------------------------------------------------
# Building the pieces (title / description / fields / images)
# ---------------------------------------------------------------------------

def _build_product_pieces(content, style, settings):
    """Everything the four product presets share, computed once."""
    fancy_title = fontstyles.apply_style(content["name"], style["title_style"]) \
        if content["name"] else ""

    status = STATUS_META[content["status"]]
    sold_out = content["status"] == "sold_out"
    flash = content["preset"] == "flash"
    stock = content["stock"]

    if sold_out:
        status_line = "❌ **SOLD OUT**"
    elif content["status"] == "limited" and stock:
        status_line = f"⚠️ **Limited stock** - only {stock} left!"
    else:
        status_line = status["line"]

    sale_unix = sale_ends_unix(content)
    sale_field = f"<t:{sale_unix}:R>" if sale_unix else None

    first = content["plans"][0] if content["plans"] else None
    discount = None
    if first:
        price_number, old_number = _first_float(first["price"]), _first_float(first["oldPrice"])
        if price_number is not None and old_number is not None and old_number > price_number:
            discount = round((1 - price_number / old_number) * 100)

    tagline = content["tagline"]
    plans_block = plans_price_line(content)
    single_plan = len(content["plans"]) <= 1

    # ---- description, per preset ----
    parts = []
    if content["preset"] == "banner":
        if single_plan:
            parts.append(f"# {price_display(content)}")
        elif cheapest_price(content) is not None:
            parts.append(f"# from {content['currency']}{('%g' % cheapest_price(content))}")
        else:
            parts.append("# **Free**")
        if tagline:
            parts.append(tagline)
        parts += ["", status_line]
    elif flash:
        parts.append(f"🔥 **FLASH SALE**{f' - **{discount}% OFF**' if discount else ''} 🔥")
        if tagline:
            parts.append(tagline)
        parts += ["", status_line]
        if sale_field:
            parts.append(f"⏰ **Sale ends {sale_field}**")
    elif content["preset"] == "minimal":
        if tagline:
            parts.append(tagline)
        parts += ["", f"{status_line} - 💰 {price_display(content)}"]
    else:      # modern
        if tagline:
            parts.append(tagline)
        parts += ["", status_line]

    description = "\n".join(parts).strip()

    # ---- fields ----
    fields = []
    inline = lambda name, value: fields.append({"name": name, "value": value, "inline": True})
    block = lambda name, value: fields.append({"name": name, "value": value, "inline": False})
    heading = lambda text: fontstyles.apply_style(text, style["heading_style"])

    category = category_label(content)
    bullet = (content["bulletCustom"] or "•") if content["bulletStyle"] == "custom" \
        else BULLETS.get(content["bulletStyle"], "•")
    features = "\n".join(f"{bullet} {line.strip()}"
                         for line in content["features"].splitlines()
                         if line.strip())

    if content["preset"] == "minimal":
        if plans_block:
            description += ("\n\n" if description else "") + plans_block
        if features:
            description += "\n\n" + features
    else:
        if category:
            inline(heading("🏷️ Category"), category)
        if stock or content["status"] == "limited":
            inline("📦 Stock", stock if stock else "Limited - while stocks last")
        if content["license"]:
            inline("🔑 License", content["license"])
        if sale_field and not flash:
            inline("⏰ Sale ends", sale_field)

        plan_layout = content.get("planLayout") or "list"
        if single_plan:
            if content["preset"] != "banner":
                block(heading("💰 Price"), price_display(content))
        elif plans_block:
            if plan_layout == "stacked":
                for plan in content["plans"]:
                    badge = f" `[{plan['badge']}]`" if plan.get("badge") else ""
                    block(heading(f"💵 {plan['label']}"), _plan_price_display(plan, content["currency"]) + badge)
            elif plan_layout == "grid":
                for plan in content["plans"]:
                    badge = f" {plan['badge']}" if plan.get("badge") else ""
                    inline(heading(f"💵 {plan['label']}"), _plan_price_display(plan, content["currency"]) + badge)
            else:  # "list" (default - one by one)
                block(heading("📋 Available Plans & Pricing"), plans_block)

        block(heading("🚚 Delivery"), delivery_label(content))
        if features:
            block(heading("✨ Features"), features)
        if content["included"]:
            block(heading("📦 What's included"), content["included"])
        if content["requirements"]:
            block(heading("🖥️ Requirements"), content["requirements"])
        if content["refund"]:
            block(heading("🛡️ Refund & support"), content["refund"])

    ticket = ticket_line(content, settings)
    if ticket:
        if content["preset"] == "minimal":
            description += "\n\n" + ticket
        else:
            fields.append({"name": DIVIDER, "value": ticket, "inline": False})

    images = _collect_images(content, style)

    return {
        "title": (f"~~{fancy_title}~~" if sold_out and fancy_title else fancy_title),
        "description": description or None,
        "fields": fields,
        "color": style["color"] if style["color"] is not None
                 else (0xED4245 if flash else status["color"]),
        "footer": style["footer_text"],
        "timestamp": content.get("showTimestamp") in (True, "true", 1),
        "images": images,
    }


# The four section presets: a small icon + a subtitle line each.
SECTION_PRESETS = {
    "clean":        {"icon": "",           "label": "Clean"},
    "announcement": {"icon": "📣 ",        "label": "Announcement"},
    "rules":        {"icon": "📜 ",        "label": "Rules"},
    "update":       {"icon": "🆕 ",        "label": "Update"},
}


def _build_section_pieces(content, style, settings):
    """A messenger section: title, body, optional images - clean and simple."""
    preset = SECTION_PRESETS.get(content["preset"], SECTION_PRESETS["clean"])

    title = fontstyles.apply_style(content["title"], style["title_style"]) \
        if content["title"] else ""
    if preset["icon"]:
        title = preset["icon"] + title

    description = content["body"] or None

    images = _collect_images(content, style)

    return {
        "title": title or None,
        "description": description,
        "fields": [],
        "color": style["color"] if style["color"] is not None else 0x5865F2,
        "footer": style["footer_text"],
        "timestamp": content.get("showTimestamp") in (True, "true", 1, None),
        "images": images,
    }


def _collect_images(content, style):
    """
    Every image of the content, as Discord-ready references.
    Uploads become attachment://name (the file travels WITH the message);
    web addresses stay as they are.
    """
    def ref(slot):
        if slot["type"] == "none":
            return None
        if slot["type"] == "upload":
            return "attachment://" + slot["value"]
        return slot["value"]

    main_slot = content.get("mainImage") if content["kind"] == "product" \
        else content.get("image")
    thumbnail = ref(content["thumbnail"])
    # a theme may ask for the bot avatar as a thumbnail when none is set
    if not thumbnail and style.get("bot_thumbnail") and content.get("_bot_avatar"):
        thumbnail = content["_bot_avatar"]

    return {
        "main": ref(main_slot),
        "thumbnail": thumbnail,
        "gallery": [ref(slot) for slot in content["gallery"]],
    }


def _upload_names_from_refs(refs):
    """The upload file names hidden inside a list of attachment:// refs."""
    names = []
    for ref in refs:
        if ref and ref.startswith("attachment://"):
            name = ref[len("attachment://"):]
            if name and name not in names:
                names.append(name)
    return names


# ---------------------------------------------------------------------------
# The auto-split packer
# ---------------------------------------------------------------------------

def _split_description(description):
    """
    A description that fits Discord's 4096 limit, as several parts.
    Splits at blank lines first (then single newlines, then hard cuts),
    so paragraphs stay together whenever possible.
    """
    if char_count(description) <= LIMITS["description"]:
        return [description]

    limit = LIMITS["description"]
    parts, current = [], ""
    paragraphs = description.split("\n\n")

    def push_hard(paragraph):
        """One paragraph that alone is too long: cut it at line/hard bounds."""
        nonlocal current
        for line in paragraph.split("\n"):
            if char_count(line) <= limit:
                if char_count(current + ("\n" if current else "") + line) <= limit:
                    current += ("\n" if current else "") + line
                    continue
                if current:
                    parts.append(current)
                current = line if char_count(line) <= limit else ""
                if char_count(line) > limit:
                    hard_cut(line)
            else:
                hard_cut(line)

    def hard_cut(line):
        nonlocal current
        words, piece = line.split(" "), ""
        for word in words:
            candidate = (piece + " " + word) if piece else word
            if char_count(candidate) > limit:
                parts.append(piece)
                piece = word if char_count(word) <= limit else ""
                if not piece:
                    # a single word longer than the limit: chop by letters
                    letters = list(word)
                    while letters:
                        parts.append("".join(letters[:limit]))
                        letters = letters[limit:]
            else:
                piece = candidate
        current = piece

    for paragraph in paragraphs:
        if char_count(paragraph) <= limit:
            candidate = current + ("\n\n" if current else "") + paragraph
            if char_count(candidate) <= limit:
                current = candidate
                continue
            parts.append(current)
            current = paragraph
        else:
            push_hard(paragraph)

    if current:
        parts.append(current)
    return [part for part in parts if part.strip()]


def _embed_chars(embed):
    """How many of Discord's 6000 characters this embed uses."""
    total = char_count(embed.get("title")) + char_count(embed.get("description"))
    total += char_count((embed.get("footer") or {}).get("text"))
    total += char_count((embed.get("author") or {}).get("name"))
    for field in embed.get("fields") or []:
        total += char_count(field.get("name")) + char_count(field.get("value"))
    return total


def _pack_into_messages(embeds, plain_content, buttons=None):
    """
    Distribute the finished embeds into messages:
    max 10 embeds and 6000 characters each. Returns a list of
    {"content", "embeds", "files"} with the plain text on the first one.
    """
    messages = []
    current, current_chars = [], 0

    for embed in embeds:
        embed_chars = _embed_chars(embed)
        would_exceed = (len(current) + 1 > LIMITS["embeds"] or
                        (current and current_chars + embed_chars > LIMITS["total"]))
        if would_exceed and current:
            messages.append(current)
            current, current_chars = [], 0
        current.append(embed)
        current_chars += embed_chars

    if current:
        messages.append(current)

    packed = []
    for index, message_embeds in enumerate(messages):
        files = _upload_names_from_refs(_all_image_refs(message_embeds))
        packed.append({
            "content": plain_content if index == 0 else "",
            "embeds": message_embeds,
            "files": files,
        })

    if buttons and packed:
        action_row = {"type": 1, "components": []}
        for b in buttons:
            btn = {
                "type": 2,
                "style": 5,
                "label": b["label"],
                "url": b["url"],
            }
            if b.get("emoji"):
                btn["emoji"] = {"name": b["emoji"]}
            action_row["components"].append(btn)
        if action_row["components"]:
            packed[-1]["components"] = [action_row]

    return packed


def _all_image_refs(embeds):
    """Every image/thumbnail reference used anywhere in these embeds."""
    refs = []
    for embed in embeds:
        for key in ("image", "thumbnail"):
            ref = (embed.get(key) or {}).get("url")
            if ref:
                refs.append(ref)
    return refs


# ---------------------------------------------------------------------------
# The one public entry point
# ---------------------------------------------------------------------------

def render_content(content, bot=None, theme=None, settings=None):
    """
    Turn a content model into exact Discord payloads.

      content  - the product/section as built in the dashboard
      bot      - {"name": ..., "avatar_url": ...} of the sending bot
      theme    - the theme dict to apply (None = plain defaults)
      settings - the app settings (ticket line text, ticket channel...)

    Returns:
      {
        "ok": True/False,                    False only for hard errors
        "messages": [ {content, embeds, files}, ... ],
        "usage":   {content, title, description, fields, footer,
                    total, embeds, messages},
        "errors":   [...],                   blocks sending
        "warnings": [...],
        "report":   {"messages": n, "embeds": m, "splits": [...]},
      }
    """
    bot = bot or {}
    settings = settings or {}
    content = normalize_content(content)

    # the bot identity rides along inside the content for the theme merge
    content["_bot_name"] = bot.get("name") or "INDRA BOT SYSTEM"
    content["_bot_avatar"] = bot.get("avatar_url") or None

    style = merge_theme(content, theme)
    errors, warnings, splits = [], [], []

    if content["kind"] == "section":
        pieces = _build_section_pieces(content, style, settings)
    else:
        pieces = _build_product_pieces(content, style, settings)

    # ---- hard errors: things Discord would refuse outright --------------
    if char_count(pieces["title"]) > LIMITS["title"]:
        errors.append(f"The title is too long ({char_count(pieces['title'])}/{LIMITS['title']} characters).")
    if char_count(style["footer_text"]) > LIMITS["footer"]:
        errors.append(f"The footer is too long ({char_count(style['footer_text'])}/{LIMITS['footer']} characters).")
    if style["author"] and char_count(style["author"]["name"]) > LIMITS["author"]:
        errors.append("The author name is longer than 256 characters.")
    plain_content = content["content"][:LIMITS["content"] + 1]
    if char_count(plain_content) > LIMITS["content"]:
        errors.append(f"The plain message is too long ({char_count(plain_content)}/{LIMITS['content']} characters).")
    if content["kind"] == "product" and not content["name"]:
        errors.append("Give the product a name (it becomes the embed title).")
    if content["kind"] == "section" and not content["title"] and not content["body"]:
        errors.append("Write a title or some text for this section first.")
    for field in pieces["fields"]:
        if char_count(field["name"]) > LIMITS["fieldName"]:
            errors.append("A field name is longer than 256 characters.")
        if char_count(field["value"]) > LIMITS["fieldValue"]:
            errors.append(f"The field \"{(field['name'] or 'list').strip()[:40]}\" is longer than 1024 characters - shorten it.")

    # ---- assemble the embeds (with auto-split) ---------------------------
    description = pieces["description"] or ""
    description_parts = _split_description(description) if description else []

    embeds = []
    primary = {
        "color": pieces["color"],
        "title": pieces["title"] or None,
        "description": description_parts[0] if description_parts else None,
    }
    if style["author"]:
        author = {"name": style["author"]["name"]}
        if style["author"]["icon_url"]:
            author["icon_url"] = style["author"]["icon_url"]
        primary["author"] = author
    if pieces["images"]["main"]:
        primary["image"] = {"url": pieces["images"]["main"]}
    if pieces["images"]["thumbnail"]:
        primary["thumbnail"] = {"url": pieces["images"]["thumbnail"]}

    # the gallery trick needs the primary embed to share the group url
    if pieces["images"]["gallery"]:
        primary["url"] = GALLERY_URL

    embeds.append(primary)

    # ---- distribute the fields over the primary + follow-up cards -------
    # Two budgets matter at once: at most 25 fields per embed AND at most
    # 6000 characters per embed (title + description + footer + author +
    # all fields together - a card full of long lists would break that
    # second one even with only 25 fields).
    footer_text = pieces["footer"]
    reserved_chars = (char_count(primary.get("title")) +
                      char_count(primary.get("description")) +
                      char_count(footer_text) +
                      char_count((primary.get("author") or {}).get("name")))

    remaining = list(pieces["fields"])
    budget = LIMITS["total"] - reserved_chars

    # fill the primary card first
    if remaining:
        held, held_chars = [], 0
        while remaining and len(held) < LIMITS["fields"]:
            candidate = remaining[0]
            candidate_chars = char_count(candidate["name"]) + char_count(candidate["value"])
            if held and held_chars + candidate_chars > budget:
                break
            held.append(remaining.pop(0))
            held_chars += candidate_chars
        if held:
            primary["fields"] = held

    # everything that did not fit -> follow-up cards (same color)
    while remaining:
        group, group_chars = [], 0
        while remaining and len(group) < LIMITS["fields"] and \
                group_chars + char_count(remaining[0]["name"]) + \
                char_count(remaining[0]["value"]) <= LIMITS["total"]:
            field = remaining.pop(0)
            group.append(field)
            group_chars += char_count(field["name"]) + char_count(field["value"])
        embeds.append({"color": pieces["color"], "fields": group})
        splits.append({"reason": "The fields did not fit on one card - the "
                                 "rest moved to a follow-up embed.",
                       "chars": group_chars})

    # description overflow -> plain continuation cards (no title, same color)
    for part in description_parts[1:]:
        embeds.append({"color": pieces["color"], "description": part})
        splits.append({"reason": "The text did not fit into one card - "
                                 "it continues on the next embed.",
                       "chars": char_count(part)})

    # gallery embeds (the grid trick)
    for ref in pieces["images"]["gallery"]:
        embeds.append({"url": GALLERY_URL, "color": pieces["color"],
                       "image": {"url": ref}})

    # footer + timestamp live on the LAST content embed (Discord shows it
    # at the bottom of that card) - which is the last non-gallery embed.
    footer_index = 0
    for index in range(len(embeds) - 1, -1, -1):
        if embeds[index].get("fields") or embeds[index].get("description"):
            footer_index = index
            break
    if footer_text:
        embeds[footer_index]["footer"] = {"text": footer_text[:LIMITS["footer"]]}
    if pieces["timestamp"]:
        embeds[footer_index]["timestamp"] = datetime.now(timezone.utc).isoformat()

    # ---- drop keys that are empty/None, like Discord expects -------------
    for embed in embeds:
        for key in ("title", "description", "url", "image", "thumbnail",
                    "footer", "timestamp", "author"):
            if key in embed and (embed[key] is None or embed[key] == {}):
                embed.pop(key)

    messages = _pack_into_messages(embeds, content["content"], content.get("buttons"))
    if len(messages) > 1:
        splits.append({"reason": "One Discord message cannot hold all of this - "
                                 "it will be posted as several messages.",
                       "chars": 0})

    # ---- usage numbers for the counters -----------------------------------
    first_embed = messages[0]["embeds"][0] if messages and messages[0]["embeds"] else {}
    usage = {
        "content": char_count(messages[0]["content"] if messages else ""),
        "title": char_count(first_embed.get("title")),
        "description": char_count(first_embed.get("description")),
        "fields": sum(len(embed.get("fields") or []) for embed in
                      (messages[0]["embeds"] if messages else [])),
        "footer": char_count((first_embed.get("footer") or {}).get("text")),
        "total": sum(_embed_chars(embed) for message in messages
                     for embed in message["embeds"]),
        "embeds": sum(len(message["embeds"]) for message in messages),
        "messages": len(messages),
    }

    # ---- soft warnings ------------------------------------------------------
    if content["kind"] == "product":
        if content["ticketLineMode"] != "hide" and \
                settings.get("ticket_line_enabled", True) and \
                content["status"] != "sold_out" and \
                not str(settings.get("ticket_channel_id") or "").strip():
            warnings.append("Ticket channel is not set - the ticket line will show "
                            "as plain text. Pick one in the Settings tab.")
    if content["saleEnds"]:
        unix = sale_ends_unix(content)
        if unix and unix < datetime.now(timezone.utc).timestamp():
            warnings.append("The 'Sale ends' time is in the past - Discord will "
                            "show it as '... ago'.")
    if content["kind"] == "product" and len(content["plans"]) > 6:
        warnings.append("More than 6 pricing plans make the card hard to read - "
                        "consider splitting the product.")
    if not usage["title"] and not usage["description"] and not usage["fields"] \
            and not usage["embeds"]:
        warnings.append("The message is empty - fill in a few fields so customers see something.")

    return {
        "ok": not errors,
        "messages": messages,
        "usage": usage,
        "errors": errors,
        "warnings": warnings,
        "report": {"messages": len(messages), "embeds": usage["embeds"],
                   "splits": splits},
    }
