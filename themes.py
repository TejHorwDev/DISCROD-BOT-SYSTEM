"""
themes.py - the theme store: your visual identity, saved as data.

WHAT IS A THEME?
  Discord embeds are customizable in a limited but powerful way:
    * the colored bar on the left side of the card,
    * an author line (small name + avatar) at the top,
    * a footer line at the bottom,
    * and - thanks to Unicode look-alike letters (fontstyles.py) - the
      "font" of the title and the field headings.

  A theme bundles all of those choices, so every listing you post can
  share one consistent look with a single click.

  A theme NEVER changes what your message says - only how it looks.

THE 12 BUILT-IN THEMES ship with the app and cannot be deleted (but you
can duplicate one into your own editable copy). Custom themes you create
in the Theme Studio are saved in data/themes.json and can be changed and
deleted freely.

Where the theme values are applied? In renderer.py, in this order:
  1. the product's / section's own settings win (its footer, its images),
  2. the theme fills in the rest (bar color, title style, author line...),
  3. anything still missing falls back to the app defaults
     (status color, normal letters, no author line).

THE ONE RULE about data/themes.json: it contains looks, never secrets.
Token handling lives in bots.py / .env only.
"""

import re
import threading
from datetime import datetime

import fontstyles
from storage import ensure_data_dir, load_json, path_for, save_json

THEMES_FILE = "themes.json"          # data/themes.json
THEMES_SCHEMA_VERSION = 1

# The id used in products/sections for "no theme - follow the status color".
NO_THEME_ID = ""

_AUTHOR_MODES = ("none", "bot", "custom")
_FOOTER_MODES = ("product", "custom", "none")

_THEMES_LOCK = threading.Lock()      # one theme save at a time


# ---------------------------------------------------------------------------
# The 12 built-in themes
# ---------------------------------------------------------------------------

BUILTIN_THEMES = [
    {
        "id": "blurple-store", "name": "Blurple Store", "builtin": True,
        "color": "#5865F2", "title_style": "bold", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "The classic Discord look - calm blue-violet, bold title.",
    },
    {
        "id": "midnight-gold", "name": "Midnight Gold", "builtin": True,
        "color": "#F0B132", "title_style": "bold_script", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Warm gold bar with elegant cursive headings - premium feel.",
    },
    {
        "id": "neon-cyber", "name": "Neon Cyber", "builtin": True,
        "color": "#00E5FF", "title_style": "mono", "heading_style": "mono",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Electric cyan with terminal-style letters - techy stores.",
    },
    {
        "id": "emerald-market", "name": "Emerald Market", "builtin": True,
        "color": "#23A55A", "title_style": "bold", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Discord green - fresh, friendly, trustworthy.",
    },
    {
        "id": "rose-boutique", "name": "Rose Boutique", "builtin": True,
        "color": "#EB459E", "title_style": "script", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Soft pink with handwritten-style titles - beauty and art shops.",
    },
    {
        "id": "sunset-flash", "name": "Sunset Flash", "builtin": True,
        "color": "#ED4245", "title_style": "bold_italic", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Hot red-orange with loud italic titles - sales and hype drops.",
    },
    {
        "id": "arctic-frost", "name": "Arctic Frost", "builtin": True,
        "color": "#58C9E6", "title_style": "italic", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Icy light blue with slim italic letters - clean and light.",
    },
    {
        "id": "royal-purple", "name": "Royal Purple", "builtin": True,
        "color": "#9B59B6", "title_style": "fraktur", "heading_style": "none",
        "author_mode": "bot", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": True,
        "description": "Deep purple, gothic headings and the bot's name + avatar on top.",
    },
    {
        "id": "toxic-lime", "name": "Toxic Lime", "builtin": True,
        "color": "#57F287", "title_style": "double", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Loud lime green with outlined 'stencil' letters - gaming gear.",
    },
    {
        "id": "vaporwave", "name": "Vaporwave", "builtin": True,
        "color": "#FF6EC7", "title_style": "fullwidth", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Retro pink with wide ａｅｓｔｈｅｔｉｃ letters.",
    },
    {
        "id": "steel-gray", "name": "Steel Gray", "builtin": True,
        "color": "#99AAB5", "title_style": "none", "heading_style": "none",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Quiet gray bar, completely normal letters - lets images speak.",
    },
    {
        "id": "candy-pop", "name": "Candy Pop", "builtin": True,
        "color": "#FF7EDB", "title_style": "circled", "heading_style": "smallcaps",
        "author_mode": "none", "author_name": "",
        "footer_mode": "product", "footer_text": "",
        "bot_thumbnail": False,
        "description": "Playful pink with circled letters - fun shops and communities.",
    },
]


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def _empty_store():
    return {"schema_version": THEMES_SCHEMA_VERSION, "themes": []}


def _load_store():
    data = load_json(THEMES_FILE, None)
    if isinstance(data, dict) and isinstance(data.get("themes"), list):
        return data
    return _empty_store()


def ensure_themes():
    """
    Make sure data/themes.json exists and holds every built-in theme.

    * first run  -> the file is created with all 12 built-ins,
    * later runs -> built-ins missing from the file (a new app version may
      have added or improved one) are re-added, but YOUR custom themes and
      any built-in you deliberately... well, built-ins cannot be deleted
      from the UI, so re-adding them is always safe.

    Returns True when the file on disk was written.
    """
    with _THEMES_LOCK:
        store = _load_store()
        known_ids = {theme.get("id") for theme in store["themes"]}
        changed = False

        for builtin in BUILTIN_THEMES:
            if builtin["id"] not in known_ids:
                store["themes"].append(dict(builtin))
                changed = True

        if changed or "schema_version" not in store:
            store["schema_version"] = THEMES_SCHEMA_VERSION
            save_json(THEMES_FILE, store)
            return True
        return False


def list_themes():
    """
    All themes: the 12 built-ins first (in their designed order), then your
    custom themes sorted by name. Never returns secrets - there are none.
    """
    store = _load_store()
    customs = sorted(
        (theme for theme in store["themes"] if not theme.get("builtin")),
        key=lambda theme: theme.get("name", "").lower())

    by_id = {theme.get("id"): theme for theme in store["themes"]}
    builtins = [by_id.get(builtin["id"]) or builtin for builtin in BUILTIN_THEMES]

    seen, result = set(), []
    for theme in builtins + customs:
        theme_id = theme.get("id")
        if theme_id in seen:
            continue
        seen.add(theme_id)
        result.append(theme)
    return result


def get_theme(theme_id):
    """One theme by id (None when it does not exist)."""
    if not theme_id:
        return None
    for theme in _load_store()["themes"]:
        if theme.get("id") == theme_id:
            return theme
    return None


# ---------------------------------------------------------------------------
# Validation + saving custom themes
# ---------------------------------------------------------------------------

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_color(value):
    """'' = follow status color; otherwise a real #rrggbb value."""
    value = str(value or "").strip()
    if not value:
        return ""
    if _HEX_COLOR.match(value):
        return value.upper()
    # tolerate values like "5865F2" or "red-ish garbage" -> give up cleanly
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return "#" + value.upper()
    return ""


def _clean_short(value, limit):
    value = str(value or "").strip()
    return value[:limit]


def sanitize_theme(incoming, theme_id=None):
    """
    Check + clean a theme coming from the browser.
    Returns (theme, error_message). `theme` is None when something is wrong.

    Only the keys a theme actually has are accepted; anything else in the
    incoming data is dropped. Built-in themes cannot be overwritten - a
    save that names a built-in id is refused with a friendly message.
    """
    if not isinstance(incoming, dict):
        return None, "That theme data was not valid."

    raw_id = theme_id if theme_id is not None else incoming.get("id")
    if not str(raw_id or "").strip():
        raw_id = incoming.get("name")          # no id given -> slug of the name
    theme_id = _clean_short(raw_id, 40)
    theme_id = re.sub(r"[^a-z0-9-]+", "-", theme_id.lower()).strip("-") or \
        "custom-theme"

    if any(theme_id == builtin["id"] for builtin in BUILTIN_THEMES):
        return None, ("Built-in themes cannot be changed. Use 'Duplicate' to "
                      "make your own editable copy first.")

    name = _clean_short(incoming.get("name"), 40) or "My theme"

    author_mode = incoming.get("author_mode")
    if author_mode not in _AUTHOR_MODES:
        author_mode = "none"
    footer_mode = incoming.get("footer_mode")
    if footer_mode not in _FOOTER_MODES:
        footer_mode = "product"

    theme = {
        "id": theme_id,
        "name": name,
        "builtin": False,
        "color": _clean_color(incoming.get("color")),
        "title_style": fontstyles.normalize_style(incoming.get("title_style")),
        "heading_style": fontstyles.normalize_style(incoming.get("heading_style")),
        "author_mode": author_mode,
        "author_name": _clean_short(incoming.get("author_name"), 60)
                       if author_mode == "custom" else "",
        "footer_mode": footer_mode,
        "footer_text": _clean_short(incoming.get("footer_text"), 120)
                       if footer_mode == "custom" else "",
        "bot_thumbnail": bool(incoming.get("bot_thumbnail")),
        "description": _clean_short(incoming.get("description"), 160),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return theme, None


def _unique_id(base, taken):
    candidate, counter = base, 2
    while candidate in taken:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def save_theme(incoming, theme_id=None):
    """
    Create or update a CUSTOM theme. Returns (theme, error).
    (Built-ins are refused - see sanitize_theme.)
    """
    theme, error = sanitize_theme(incoming, theme_id)
    if error:
        return None, error

    with _THEMES_LOCK:
        store = _load_store()
        known = {theme.get("id"): i for i, theme in enumerate(store["themes"])}

        if theme["id"] in known:
            old = store["themes"][known[theme["id"]]]
            if old.get("builtin"):
                return None, "Built-in themes cannot be changed."
            theme["created_at"] = old.get("created_at", theme["created_at"])
            store["themes"][known[theme["id"]]] = theme
        else:
            theme["id"] = _unique_id(theme["id"], known)
            store["themes"].append(theme)

        save_json(THEMES_FILE, store)
        return theme, None


def duplicate_theme(theme_id):
    """
    Copy any theme (built-in or custom) into a new editable custom one.
    Returns (new_theme, error).
    """
    original = get_theme(theme_id)
    if original is None:
        return None, "That theme does not exist."

    copy = {key: value for key, value in original.items()
            if key not in ("id", "builtin", "created_at")}
    copy["name"] = (original.get("name", "Theme") + " copy")[:40]
    copy["description"] = "Your editable copy of " + original.get("name", "?") + "."
    return save_theme(copy)


def delete_theme(theme_id):
    """
    Delete a CUSTOM theme (built-ins are protected).
    Products and sections that used it simply fall back to their own colors.
    Returns (ok, error).
    """
    with _THEMES_LOCK:
        store = _load_store()
        kept, removed = [], None
        for theme in store["themes"]:
            if theme.get("id") == theme_id:
                removed = theme
            else:
                kept.append(theme)

        if removed is None:
            return False, "That theme does not exist."
        if removed.get("builtin"):
            return False, "Built-in themes cannot be deleted - they are part of the app."

        store["themes"] = kept
        save_json(THEMES_FILE, store)
        return True, None
