"""
app.py - SELLER BOT Studio's web server (the heart of the app).

Start it with:   python app.py       (or just double-click run.bat / run.sh)
Then open:       http://localhost:5000

What this file does:
  1. It serves the dashboard page you see in the browser (templates/index.html).
  2. It offers small JSON "endpoints" that the page calls in the background
     while you work. The browser NEVER talks to Discord directly and NEVER
     sees a bot token - every Discord call happens here, on your PC, through
     a BotClient from discord_api.py (one per bot, from bots.py's registry).

  A quick map of the endpoints:

     The dashboard page
       GET  /                          -> the page itself

     Bots (the registry lives in data/bots.json, tokens ONLY in .env)
       GET    /api/bots                -> list bots (tokens masked)
       POST   /api/bots                -> add a bot (validates the token first)
       POST   /api/bots/<id>           -> rename / note / ping-permission changes
       POST   /api/bots/<id>/toggle    -> enable or disable a bot
       POST   /api/bots/<id>/test      -> live "does it connect?" check
       POST   /api/bots/<id>/invite    -> build the ready-made invite link
       DELETE /api/bots/<id>           -> remove a bot

     Connection + pickers (all accept ?bot=<id>, default = active bot)
       GET  /api/status                -> is that bot's token OK? who is it?
       GET  /api/guilds                -> which servers is the bot in?
       GET  /api/channels/<id>         -> channels of one server (by category)
       GET  /api/roles/<id>            -> roles of one server (for @role pings)
       GET  /api/emojis/<id>           -> custom emojis of one server
       GET  /api/lookup-channel/<id>   -> check a channel ID pasted by hand

     Settings (remembered in data/settings.json)
       GET/POST /api/settings          -> your choices (channels, ticket line...)
       GET  /api/config                -> harmless app settings for the page

     Product library (data/products.json)
       GET  /api/products              -> list saved products
       POST /api/products              -> save (create or update) one product
       DELETE /api/products/<id>       -> delete one product
       POST /api/products/import       -> add products from a JSON file
       GET  /api/products/export       -> download all products as a JSON file

     Images uploaded from your PC (data/uploads/)
       POST /api/upload                -> receive one picture (max 8 MB)
       GET  /uploads/<name>            -> show an uploaded picture

     Sending + history (every entry remembers WHICH bot sent it)
       POST /api/preview              -> render a content model -> payloads
                                          (THE same output Send posts)
       POST /api/send                 -> post to the chosen channel(s)
       POST /api/send-test            -> post once to TEST_CHANNEL_ID
       GET  /api/history              -> everything ever posted
       POST /api/messages/update      -> edit a sent message in place
       POST /api/messages/delete      -> delete a sent message

     Sections (the Messenger bot's content - announcements, rules...)
       GET/POST /api/sections        -> list / save sections
       DELETE /api/sections/<id>     -> delete one
       (posting a section uses /api/send with kind "section")

     Looks
       GET  /api/fontstyles           -> the 11 Unicode heading styles
       GET/POST /api/themes           -> list / save themes
       POST /api/themes/<id>/duplicate -> copy any theme (built-ins too)
       DELETE /api/themes/<id>       -> delete a CUSTOM theme

     Scheduled posts (data/schedules.json) + a small background worker
       GET/POST /api/schedules         -> list / plan a post for later
       POST /api/schedules/cancel      -> cancel one
       POST /api/schedules/run-now     -> fire one on the next tick
"""

import json
import os
import re
import shutil
import socket
import threading
import time
import uuid
import zipfile
from datetime import datetime
from functools import wraps
from io import BytesIO

from dotenv import load_dotenv
from flask import (Flask, jsonify, request, render_template, send_file,
                   send_from_directory, session, redirect, url_for,
                   has_request_context)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import bots
import discord_api
import fontstyles
import renderer
import storage
import themes

# Pillow is the app's one image tool: it checks that uploads really are
# pictures, reads their size, and can shrink huge photos so Discord does
# not choke on them. (It is in requirements.txt; if someone deleted it,
# the app still runs - uploads then fall back to the simpler magic-byte
# check from the first version.)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:                                  # pragma: no cover
    PIL_AVAILABLE = False

# Read the .env file that sits next to this file.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)

# Secret key for secure session cookies
app.secret_key = os.getenv("SECRET_KEY", "indra_bot_secret_key_8f39c2e17b54a06d")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_NAME"] = "indra_session"

# Never accept giant uploads. Discord allows 8 MB per file, so anything
# bigger than this is a mistake anyway. (The per-file 8 MB check happens
# in /api/upload - this is just the hard outer limit.)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # 10 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ADMIN_FILE = os.path.join(DATA_DIR, "admin.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LICENSES_FILE = os.path.join(DATA_DIR, "licenses.json")
WEBHOOK_FILE = os.path.join(DATA_DIR, "admin_webhook.json")

SEED_LICENSES = [
    "INDRA-VIP-2026",
    "INDRA-FRIEND-7788",
    "INDRA-PRO-9921",
    "INDRA-CORE-5544",
    "INDRA-ELITE-1122",
    "INDRA-NEXUS-3344",
]

# ---------------------------------------------------------------------------
# Admin authentication helpers
# ---------------------------------------------------------------------------

def get_admin_credentials():
    """Return stored admin credentials or defaults from .env."""
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
    env_email = (os.getenv("ADMIN_EMAIL") or "").strip()
    env_password = (os.getenv("ADMIN_PASSWORD") or "").strip()

    if os.path.isfile(ADMIN_FILE):
        try:
            with open(ADMIN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("email"):
                    if env_email and env_email.lower() != data.get("email", "").lower():
                        data["email"] = env_email
                        if env_password:
                            data["password_hash"] = generate_password_hash(env_password)
                        save_admin_credentials(data["email"], env_password)
                    return data
        except Exception:
            pass
    # Fallback to .env
    email = env_email or "admin@indra.gg"
    password = env_password or "indra2026!"
    return {
        "email": email,
        "password_hash": generate_password_hash(password)
    }

def save_admin_credentials(email, new_password=None):
    """Update admin credentials and write to data/admin.json."""
    current = get_admin_credentials()
    email = email.strip() if email else current.get("email", "admin@indra.gg")
    pwd_hash = generate_password_hash(new_password) if new_password else current.get("password_hash")
    data = {"email": email, "password_hash": pwd_hash, "updatedAt": datetime.now().isoformat()}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data

# ---------------------------------------------------------------------------
# Multi-tenancy, User and License System
# ---------------------------------------------------------------------------

def load_licenses():
    """Load licenses from data/licenses.json or initialize with default seed keys."""
    if os.path.isfile(LICENSES_FILE):
        try:
            with open(LICENSES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("licenses"), list):
                    return data.get("licenses")
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    now = datetime.now().isoformat(timespec="seconds")
    initial = [
        {"key": key, "status": "unused", "created_at": now, "used_by": None, "used_by_id": None, "used_at": None}
        for key in SEED_LICENSES
    ]
    save_licenses(initial)
    return initial

def save_licenses(licenses_list):
    """Save licenses list to data/licenses.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LICENSES_FILE, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "licenses": licenses_list}, f, indent=2)

def load_users():
    """Load users from data/users.json or initialize with master admin."""
    users = []
    if os.path.isfile(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("users"), list):
                    users = data.get("users")
                elif isinstance(data, list):
                    users = data
        except Exception:
            pass

    admin_creds = get_admin_credentials()
    now = datetime.now().isoformat(timespec="seconds")
    admin_email = str(admin_creds.get("email") or os.getenv("ADMIN_EMAIL") or "admin@indra.gg").strip().lower()
    admin_hash = admin_creds.get("password_hash")

    found_admin = False
    for u in users:
        if u.get("id") == "admin":
            u["email"] = admin_email
            if admin_hash:
                u["password_hash"] = admin_hash
            found_admin = True
            break

    if not found_admin:
        users.insert(0, {
            "id": "admin",
            "email": admin_email,
            "password_hash": admin_hash,
            "role": "admin",
            "status": "active",
            "license_key": "MASTER-KEY",
            "created_at": now,
            "last_login": now,
        })
        save_users(users)

    return users

def save_users(users_list):
    """Save users list to data/users.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "users": users_list}, f, indent=2)

def get_user_by_id(uid):
    """Find a user dict by id from users.json."""
    if not uid:
        return None
    for u in load_users():
        if u.get("id") == uid:
            return u
    return None

def current_user():
    """Return dict of current logged-in user or None."""
    if not has_request_context() or not session.get("authenticated"):
        return None
    uid = session.get("user_id")
    if uid:
        u = get_user_by_id(uid)
        if u:
            return u
    if session.get("role") == "admin" or session.get("admin_email"):
        return {
            "id": "admin",
            "email": session.get("admin_email") or session.get("email") or "admin@indra.gg",
            "role": "admin",
            "status": "active"
        }
    return None

def current_user_id():
    """Current user id or None."""
    u = current_user()
    return u.get("id") if u else None

def is_admin():
    """Check if current session user is master admin."""
    u = current_user()
    return u.get("role") == "admin" if u else False

def current_user_dir():
    """Return isolated data directory for current user. Master admin returns None (root data/)."""
    if not has_request_context():
        return None
    u = current_user()
    if not u or u.get("role") == "admin":
        return None
    uid = u.get("id")
    user_dir = os.path.join(DATA_DIR, "users", uid)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def admin_required(f):
    """Decorator to protect routes that require master admin privileges."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            return jsonify({"ok": False, "error": "Forbidden: Master Admin privileges required."}), 403
        return f(*args, **kwargs)
    return decorated_function

# Override load_items and save_items to automatically scope to user directory!
def load_items(filename, base_dir=None):
    if base_dir is None:
        base_dir = current_user_dir()
    return storage.load_items(filename, base_dir=base_dir)

def save_items(filename, items, base_dir=None):
    if base_dir is None:
        base_dir = current_user_dir()
    return storage.save_items(filename, items, base_dir=base_dir)

# Rate limiting for Discord sends: 2.5 seconds cooldown per user
USER_LAST_SEND = {}

def check_send_rate_limit():
    """Enforce a 2.5 second cooldown per user on Discord dispatch to avoid hitting rate limits."""
    uid = current_user_id() or "admin"
    now = time.time()
    last_time = USER_LAST_SEND.get(uid, 0)
    cooldown = 2.5
    if now - last_time < cooldown:
        remaining = round(cooldown - (now - last_time), 1)
        return jsonify({
            "ok": False,
            "error": f"⚡ Rate limit: Please wait {remaining}s before sending again to protect against Discord rate limits.",
            "error_kind": "rate_limited"
        }), 429
    USER_LAST_SEND[uid] = now
    return None

def send_admin_webhook_alert(content):
    """Helper to dispatch alerts to master Discord webhook if configured."""
    try:
        doc = storage.load_doc("admin_webhook.json")
        webhook_url = doc.get("webhook_url", "").strip()
        if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
            return
        import urllib.request
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"content": content}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "IndraBotSystem/2.0"}
        )
        urllib.request.urlopen(req, timeout=4)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Data files - created automatically (and safely) on first run in data/
# ---------------------------------------------------------------------------

def _plan(plan_id, label, price, old_price="", badge=""):
    """One pricing plan row, as the builder creates them."""
    return {"id": plan_id, "label": label, "price": price,
            "oldPrice": old_price, "badge": badge}


def _starter_products():
    """
    The four example products the app ships with - one per layout preset.
    They are normal products: load one, change everything, or delete it.
    (Built here as a function so the "Flash Sale" example can set its
    sale-end time to two days from NOW, whenever the first run happens.)

    The Flash Sale template also shows off PRICING PLANS: one product,
    several keys/lengths, each with its own price.
    """
    now = datetime.now().isoformat(timespec="seconds")
    sale_ends = datetime.fromtimestamp(time.time() + 48 * 3600).strftime("%Y-%m-%dT%H:%M")
    base = {
        "categoryCustom": "", "status": "available",
        "stock": "", "delivery": "instant", "deliveryHours": "",
        "mainImage": {"type": "none", "value": ""},
        "gallery": [{"type": "none", "value": ""} for _ in range(4)],
        "thumbnail": {"type": "none", "value": ""},
        "footer": "INDRA BOT SYSTEM | Instant delivery", "showTimestamp": True,
        "saleEnds": "", "content": "",
        "fancyText": False, "fancyStyle": "bold",
        "ticketLineMode": "global", "ticketLineText": "",
        "planLayout": "list",
        "plans": [], "theme_id": "",
        "isTemplate": True, "createdAt": now, "updatedAt": now,
        "bot_id": "seller",
    }
    return [
        {**base, **{
            "id": "tpl-modern",
            "name": "NovaNotes Pro - Notes app with AI search",
            "tagline": "Your notes, instantly findable. Lifetime license, all future updates included.",
            "category": "Software", "currency": "$",
            "plans": [_plan("standard", "Standard", "19.99", "29.99")],
            "license": "Lifetime + free updates",
            "features": "Instant download after purchase\nWorks on Windows, Mac and Linux\nEnd-to-end encrypted sync\nAI-powered search across all notes\nImport from Evernote and Notion",
            "bulletStyle": "checkmark", "bulletCustom": "",
            "included": "NovaNotes Pro installer (Windows/Mac/Linux)\nLifetime license key\nSetup guide (PDF)\nEmail support for 12 months",
            "requirements": "Windows 10+ / macOS 12+ / Ubuntu 20.04+\n4 GB RAM\n200 MB free disk space",
            "refund": "7-day money-back guarantee if the app does not work as described. Open a ticket and we will sort it out.",
            "preset": "modern",
        }},
        {**base, **{
            "id": "tpl-minimal",
            "name": "The Freelance Launch Kit (E-book)",
            "tagline": "120 pages on going from zero to your first paying client - worksheets included.",
            "category": "E-book", "status": "coming_soon",
            "currency": "$",
            "plans": [_plan("standard", "Standard", "9")],
            "license": "Personal use",
            "features": "120-page PDF e-book\n15 fill-in worksheets\nCold email + proposal templates\nPricing calculator (Google Sheets)",
            "bulletStyle": "sparkles", "bulletCustom": "",
            "included": "E-book PDF\nWorksheet pack\nFree lifetime updates",
            "requirements": "Any PDF reader",
            "refund": "Due to the digital nature, all sales are final - but message us if anything is wrong and we will fix it.",
            "preset": "minimal",
        }},
        {**base, **{
            "id": "tpl-banner",
            "name": "Aurora Icon Pack - 480 vector icons",
            "tagline": "A clean, modern icon set for web and app designers. SVG + PNG + Figma file.",
            "category": "Design Assets", "status": "limited",
            "currency": "$", "stock": "50",
            "plans": [_plan("standard", "Standard", "14")],
            "license": "Commercial license",
            "features": "480 icons in 4 styles (line, solid, duotone, filled)\nSVG + 3 PNG sizes\nFigma and Sketch libraries\nFree monthly icon drops",
            "bulletStyle": "fire", "bulletCustom": "",
            "included": "Icon pack (ZIP download)\nFigma file\nCommercial license (PDF)",
            "requirements": "Figma (free account) or any SVG editor",
            "refund": "Refunds within 14 days if the files are damaged or not as described.",
            "preset": "banner",
        }},
        {**base, **{
            "id": "tpl-flash",
            "name": "Nitro Games Key Bundle",
            "tagline": "5 Steam game keys in one bundle - this weekend only.",
            "category": "Game Key/Account",
            "currency": "$", "stock": "25",
            "plans": [
                _plan("1m", "1 Month Key", "4.99", "7.99", "POPULAR"),
                _plan("3m", "3 Months Key", "9.99"),
                _plan("1y", "1 Year Key", "19.99", "29.99", "BEST VALUE"),
                _plan("lifetime", "Lifetime Key", "39.99"),
            ],
            "license": "1 key per purchase",
            "features": "5 x Steam game keys (region-free)\nInstant delivery in your ticket\nGiftable - great as a present",
            "bulletStyle": "arrow", "bulletCustom": "",
            "included": "5 x Steam key (sent in your ticket)",
            "requirements": "A free Steam account",
            "refund": "Keys are checked before sending. No refunds once a key is revealed.",
            "preset": "flash", "saleEnds": sale_ends,
        }},
    ]


def _starter_sections():
    """
    The three starter sections for your Messenger bot - an announcement,
    a rules page and an update. Load one, make it yours, or delete it.
    """
    now = datetime.now().isoformat(timespec="seconds")
    base = {
        "kind": "section", "title": "", "body": "",
        "image": {"type": "none", "value": ""},
        "thumbnail": {"type": "none", "value": ""}, "gallery": [],
        "footer": "", "showTimestamp": True, "content": "",
        "ticketLineMode": "hide", "ticketLineText": "",
        "theme_id": "", "starter": True,
        "createdAt": now, "updatedAt": now,
    }
    return [
        {**base, **{
            "id": "sec-announcements", "name": "Announcements",
            "title": "Announcements",
            "preset": "announcement", "bot_id": "",
            "body": "📢 **Welcome to the server!**\n\nThis channel is where we post every important announcement - drops, sales, events and changes.\n\nTurn on notifications for this channel so you never miss one.",
            "footer": "Server announcements",
        }},
        {**base, **{
            "id": "sec-rules", "name": "Server Rules",
            "title": "Server Rules",
            "preset": "rules", "bot_id": "",
            "body": "**1.** Be respectful to everyone.\n**2.** No spam, no advertising, no DM advertising.\n**3.** Keep conversations in the right channels.\n**4.** No illegal or NSFW content.\n**5.** Staff decisions are final - open a ticket if you disagree.",
            "footer": "Last updated: " + datetime.now().strftime("%d %b %Y"),
        }},
        {**base, **{
            "id": "sec-updates", "name": "Updates Log",
            "title": "Latest Updates",
            "preset": "update", "bot_id": "",
            "body": "🆕 **v2.0** - The store got a big upgrade: pricing plans, themes and more.\n\n🆕 **v1.5** - Faster delivery and a fresh look for every listing.",
            "footer": "We ship improvements every week",
        }},
    ]


# The settings the app knows about, with their defaults. The page may only
# save these keys, so nothing strange can ever end up in settings.json.
DEFAULT_SETTINGS = {
    "last_guild_id": "",          # the server you picked last time
    "last_channel_ids": [],       # the channels you ticked last time
    "active_bot_id": "",          # which bot the dashboard is working as
    "ticket_channel_id": "",      # where customers open tickets
    "ticket_channel_name": "",    # its name, for showing in the preview
    "ticket_line_enabled": True,  # show the "open a ticket" line?
    "ticket_line_text": "🎫 **Want to buy?** Open a ticket in {ticket_channel}",
    "allow_everyone_mentions": False,   # allow @everyone / @here pings?
}

# One small lock so the background schedule thread and the page never
# write to the same JSON file at the same millisecond.
DATA_LOCK = threading.Lock()


def mark_missed_schedules():
    """
    Any schedule that should have fired while the app was closed is marked
    "missed" - the page shows it and offers "Run now".
    (Called on every startup, right after the data files exist.)
    """
    with DATA_LOCK:
        schedules = load_items("schedules.json")
        changed = False
        now = datetime.now()
        for item in schedules:
            if item.get("status") != "pending":
                continue
            try:
                due = datetime.fromisoformat(str(item.get("run_at", "")))
            except ValueError:
                # A schedule with a broken date can never fire - mark it
                # clearly AND SAVE THE CHANGE (a bug in the old app let
                # these stay "pending" forever, silently).
                item["status"] = "error"
                item["error"] = "The saved date was invalid."
                changed = True
                continue
            if due <= now:
                item["status"] = "missed"
                changed = True
        if changed:
            save_items("schedules.json", schedules)


def ensure_data_files(base_dir=None):
    """On first run or user account creation, create the data folder and starter files."""
    storage.ensure_data_files({
        "products.json": lambda: {"schema_version": 3, "items": _starter_products()},
        "settings.json": lambda: {"schema_version": 2, **DEFAULT_SETTINGS},
        "history.json": lambda: {"schema_version": 2, "items": []},
        "schedules.json": lambda: {"schema_version": 2, "items": []},
        "sections.json": lambda: {"schema_version": 1, "items": _starter_sections()},
        "links.json": lambda: {"schema_version": 1, "items": []},
        "vouches.json": lambda: {"schema_version": 1, "items": []},
    }, base_dir=base_dir)
    themes.ensure_themes(base_dir=base_dir)          # data/themes.json + the 12 built-ins
    bots.ensure_registry(base_dir=base_dir)
    if base_dir is None:
        mark_missed_schedules()


def get_settings(base_dir=None):
    """Read settings.json and fill in defaults for anything missing."""
    if base_dir is None:
        base_dir = current_user_dir()
    saved = storage.load_doc("settings.json", base_dir=base_dir)
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(saved, dict):
        saved.pop("schema_version", None)      # bookkeeping, not a setting
        merged.update(saved)
    return merged


def save_settings(settings, base_dir=None):
    """Save settings.json for current user or given base_dir."""
    if base_dir is None:
        base_dir = current_user_dir()
    storage.save_doc("settings.json", settings, base_dir=base_dir)


# ---------------------------------------------------------------------------
# STARTUP: migrate old data (with a backup first), then load the bot registry
# ---------------------------------------------------------------------------

_migration_report = storage.run_migrations()    # backup happens inside, if needed
bots.ensure_registry()                         # DISCORD_TOKEN becomes bot #1
ensure_data_files()                             # data files + themes + sections
load_licenses()                                 # ensure licenses.json exists with seed keys
load_users()                                    # ensure users.json exists

if _migration_report["migrated"] or _migration_report["backup"]:
    print("  Data files upgraded to the current format.")
    if _migration_report["backup"]:
        print(f"  A safety copy of your old data was put in data/{_migration_report['backup']}/")
    if _migration_report["migrated"]:
        print("  Upgraded: " + ", ".join(_migration_report["migrated"]))


# ---------------------------------------------------------------------------
# Authentication & Protected Routes
# ---------------------------------------------------------------------------

@app.before_request
def require_authentication():
    """Protect all dashboard routes and APIs. Unauthenticated users are redirected to /login or receive 401."""
    path = request.path
    if (path in ("/login", "/logout", "/register") or
        path.startswith("/static/") or
        path == "/favicon.ico"):
        return None

    if not session.get("authenticated"):
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Unauthorized. Please log in.", "unauthorized": True}), 401
        return redirect("/login")

    # Check if user account was suspended or deleted by admin
    uid = session.get("user_id")
    if uid and uid != "admin":
        user = get_user_by_id(uid)
        if not user or user.get("status") == "suspended":
            session.clear()
            if path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Your account has been suspended by the administrator.", "unauthorized": True}), 403
            return redirect("/login")

    return None


@app.get("/register")
def register_page():
    """Show the one-time license key registration page."""
    if session.get("authenticated"):
        return redirect("/")
    return render_template("register.html")


@app.post("/register")
def register_submit():
    """Redeem a one-time license key and create an isolated user account."""
    data = request.get_json(silent=True) or request.form or {}
    key_input = str(data.get("license_key") or "").strip().upper()
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    confirm_pwd = str(data.get("confirm_password") or "")

    def fail(msg, code=400):
        if request.is_json:
            return jsonify({"ok": False, "error": msg}), code
        return render_template("register.html", error=msg), code

    if not key_input:
        return fail("Please enter a valid license key.")
    if not email or "@" not in email:
        return fail("Please enter a valid email address.")
    if not password or len(password) < 6:
        return fail("Password must be at least 6 characters long.")
    if confirm_pwd and password != confirm_pwd:
        return fail("Passwords do not match.")

    licenses = load_licenses()
    matched_lic = None
    for lic in licenses:
        if lic.get("key", "").upper() == key_input:
            matched_lic = lic
            break

    if not matched_lic:
        return fail("Invalid license key. Please check with your administrator.")
    if matched_lic.get("status") != "unused":
        return fail(f"This license key has already been redeemed by {matched_lic.get('used_by', 'another user')}.")

    users = load_users()
    for u in users:
        if str(u.get("email", "")).lower() == email:
            return fail("An account with this email address already exists.")

    user_id = "u_" + uuid.uuid4().hex[:8]
    now = datetime.now().isoformat(timespec="seconds")

    matched_lic["status"] = "used"
    matched_lic["used_by"] = email
    matched_lic["used_by_id"] = user_id
    matched_lic["used_at"] = now
    save_licenses(licenses)

    new_user = {
        "id": user_id,
        "email": email,
        "password_hash": generate_password_hash(password),
        "role": "user",
        "status": "active",
        "license_key": key_input,
        "created_at": now,
        "last_login": now,
    }
    users.append(new_user)
    save_users(users)

    # Initialize isolated user folder
    user_dir = os.path.join(DATA_DIR, "users", user_id)
    os.makedirs(user_dir, exist_ok=True)
    ensure_data_files(base_dir=user_dir)

    # Set session
    session["authenticated"] = True
    session["user_id"] = user_id
    session["email"] = email
    session["role"] = "user"

    # Send admin alert
    send_admin_webhook_alert(f"🎉 **New Friend Registered!**\n- **Email:** `{email}`\n- **User ID:** `{user_id}`\n- **License Key:** `{key_input}`\n- **Time:** `{now}`")

    if request.is_json:
        return jsonify({"ok": True, "user": {"id": user_id, "email": email, "role": "user"}})
    return redirect("/")


@app.get("/login")
def login_page():
    """Show the login screen."""
    if session.get("authenticated"):
        return redirect("/")
    return render_template("login.html")


@app.post("/login")
def login_submit():
    """Verify admin or friend user email and password."""
    data = request.get_json(silent=True) or request.form or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")

    # Always re-read .env with override=True so changes in .env take effect immediately!
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
    env_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    env_password = (os.getenv("ADMIN_PASSWORD") or "").strip()

    # 1. Check root admin
    creds = get_admin_credentials()
    admin_email = str(creds.get("email") or "").strip().lower()
    pwd_hash = creds.get("password_hash", "")

    is_root_admin = (
        (admin_email and email == admin_email and (check_password_hash(pwd_hash, password) or (env_password and password == env_password)))
        or
        (env_email and email == env_email and (password == env_password or (pwd_hash and check_password_hash(pwd_hash, password))))
    )

    if is_root_admin:
        active_email = admin_email or env_email or email
        session["authenticated"] = True
        session["user_id"] = "admin"
        session["admin_email"] = active_email
        session["email"] = active_email
        session["role"] = "admin"
        if request.is_json:
            return jsonify({"ok": True, "email": active_email, "role": "admin"})
        return redirect("/")

    # 2. Check registered users in users.json
    users = load_users()
    matched_user = None
    for u in users:
        if str(u.get("email", "")).lower() == email:
            matched_user = u
            break

    if matched_user:
        if matched_user.get("status") == "suspended":
            if request.is_json:
                return jsonify({"ok": False, "error": "Your account has been suspended by the administrator."}), 403
            return render_template("login.html", error="Your account has been suspended by the administrator."), 403

        if check_password_hash(matched_user.get("password_hash", ""), password):
            matched_user["last_login"] = datetime.now().isoformat(timespec="seconds")
            save_users(users)

            session["authenticated"] = True
            session["user_id"] = matched_user["id"]
            session["email"] = matched_user["email"]
            session["role"] = matched_user.get("role", "user")
            if request.is_json:
                return jsonify({"ok": True, "email": matched_user["email"], "role": session["role"]})
            return redirect("/")

    if request.is_json:
        return jsonify({"ok": False, "error": "Invalid email or password."}), 401
    return render_template("login.html", error="Invalid email or password."), 401


@app.route("/logout", methods=["GET", "POST"])
def logout():
    """Sign out and clear session."""
    session.clear()
    return redirect("/login")


@app.get("/api/auth/me")
def api_auth_me():
    """Return currently logged-in user status, id, email, and role."""
    u = current_user()
    if not u:
        return jsonify({"ok": True, "authenticated": False, "role": "guest"})
    return jsonify({
        "ok": True,
        "authenticated": True,
        "logged_in": True,
        "user_id": u.get("id"),
        "email": u.get("email"),
        "role": u.get("role", "user"),
        "user": {
            "id": u.get("id"),
            "email": u.get("email"),
            "role": u.get("role", "user")
        }
    })


@app.post("/api/auth/update-credentials")
def api_auth_update():
    """Allow logged-in admin or user to update email and password."""
    data = request.get_json(silent=True) or {}
    current_pwd = str(data.get("current_password") or "")
    new_email = str(data.get("new_email") or "").strip()
    new_pwd = str(data.get("new_password") or "")

    u = current_user()
    if not u:
        return jsonify({"ok": False, "error": "Not authenticated."}), 401

    if is_admin():
        creds = get_admin_credentials()
        env_password = (os.getenv("ADMIN_PASSWORD") or "").strip()
        valid_current = (
            check_password_hash(creds.get("password_hash", ""), current_pwd) or
            (env_password and current_pwd == env_password)
        )
        if not valid_current:
            return jsonify({"ok": False, "error": "Current password is incorrect."}), 400

        if new_email and "@" not in new_email:
            return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400

        if new_pwd and len(new_pwd) < 6:
            return jsonify({"ok": False, "error": "New password must be at least 6 characters long."}), 400

        saved = save_admin_credentials(new_email or creds.get("email"), new_pwd if new_pwd else None)
        session["admin_email"] = saved.get("email")
        session["email"] = saved.get("email")
        return jsonify({"ok": True, "email": saved.get("email")})

    # For regular tenant users:
    users = load_users()
    target_user = None
    for item in users:
        if item.get("id") == u.get("id"):
            target_user = item
            break

    if not target_user:
        return jsonify({"ok": False, "error": "User account not found."}), 404

    if not check_password_hash(target_user.get("password_hash", ""), current_pwd):
        return jsonify({"ok": False, "error": "Current password is incorrect."}), 400

    if new_email and "@" not in new_email:
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400

    if new_pwd and len(new_pwd) < 6:
        return jsonify({"ok": False, "error": "New password must be at least 6 characters long."}), 400

    if new_email:
        target_user["email"] = new_email
        session["email"] = new_email
    if new_pwd:
        target_user["password_hash"] = generate_password_hash(new_pwd)

    save_users(users)
    return jsonify({"ok": True, "email": target_user["email"]})


# ---------------------------------------------------------------------------
# Admin Hub Endpoints (Master Admin Only)
# ---------------------------------------------------------------------------

@app.get("/api/admin/users")
@admin_required
def api_admin_users_list():
    """List all registered users and their status."""
    users = load_users()
    safe_users = [
        {
            "id": u.get("id"),
            "email": u.get("email"),
            "role": u.get("role", "user"),
            "status": u.get("status", "active"),
            "license_key": u.get("license_key", ""),
            "created_at": u.get("created_at", ""),
            "last_login": u.get("last_login", ""),
        }
        for u in users
    ]
    return jsonify({"ok": True, "users": safe_users})


@app.post("/api/admin/users/action")
@admin_required
def api_admin_user_action():
    """Suspend, unsuspend, reset password, or delete user + wipe data."""
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip()
    target_id = str(data.get("user_id") or "").strip()

    if not target_id or target_id == "admin":
        return jsonify({"ok": False, "error": "Cannot modify master admin account."}), 400

    users = load_users()
    target = None
    for u in users:
        if u.get("id") == target_id:
            target = u
            break

    if not target:
        return jsonify({"ok": False, "error": "User not found."}), 404

    if action == "suspend":
        target["status"] = "suspended"
        save_users(users)
        return jsonify({"ok": True, "message": f"User {target['email']} has been suspended."})

    elif action == "unsuspend":
        target["status"] = "active"
        save_users(users)
        return jsonify({"ok": True, "message": f"User {target['email']} has been activated."})

    elif action == "reset_password":
        new_pwd = str(data.get("new_password") or "").strip()
        if len(new_pwd) < 6:
            return jsonify({"ok": False, "error": "Password must be at least 6 characters."}), 400
        target["password_hash"] = generate_password_hash(new_pwd)
        save_users(users)
        return jsonify({"ok": True, "message": f"Password reset for {target['email']}."})

    elif action == "delete":
        users = [u for u in users if u.get("id") != target_id]
        save_users(users)
        user_dir = os.path.join(DATA_DIR, "users", target_id)
        if os.path.isdir(user_dir):
            try:
                shutil.rmtree(user_dir)
            except Exception:
                pass
        return jsonify({"ok": True, "message": f"User {target['email']} and all their data were permanently deleted."})

    return jsonify({"ok": False, "error": "Unknown action."}), 400


@app.get("/api/admin/licenses")
@admin_required
def api_admin_licenses_list():
    """List all license keys and their redemption status."""
    return jsonify({"ok": True, "licenses": load_licenses()})


@app.post("/api/admin/licenses")
@admin_required
def api_admin_licenses_action():
    """Generate new license keys or revoke an unused key."""
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "generate").strip()

    licenses = load_licenses()
    now = datetime.now().isoformat(timespec="seconds")

    if action == "generate":
        custom_key = str(data.get("key") or "").strip().upper()
        if custom_key:
            if any(l.get("key", "").upper() == custom_key for l in licenses):
                return jsonify({"ok": False, "error": f"License key {custom_key} already exists."}), 400
            lic_entry = {
                "key": custom_key,
                "status": "unused",
                "created_at": now,
                "used_by": None,
                "used_by_id": None,
                "used_at": None,
            }
            licenses.append(lic_entry)
            save_licenses(licenses)
            return jsonify({"ok": True, "created": [custom_key], "licenses": licenses})

        prefix = str(data.get("prefix") or "INDRA").strip().upper()[:10] or "INDRA"
        try:
            count = min(max(int(data.get("count", 1)), 1), 20)
        except Exception:
            count = 1
        created_keys = []
        for _ in range(count):
            rand_code = uuid.uuid4().hex[:4].upper() + "-" + uuid.uuid4().hex[:4].upper()
            new_key = f"{prefix}-{rand_code}"
            lic_entry = {
                "key": new_key,
                "status": "unused",
                "created_at": now,
                "used_by": None,
                "used_by_id": None,
                "used_at": None,
            }
            licenses.append(lic_entry)
            created_keys.append(new_key)
        save_licenses(licenses)
        return jsonify({"ok": True, "created": created_keys, "licenses": licenses})

    elif action == "revoke":
        target_key = str(data.get("key") or "").strip().upper()
        for lic in licenses:
            if lic.get("key", "").upper() == target_key:
                if lic.get("status") == "used":
                    return jsonify({"ok": False, "error": "Cannot revoke a key that has already been redeemed."}), 400
                lic["status"] = "revoked"
                save_licenses(licenses)
                return jsonify({"ok": True, "message": f"License {target_key} revoked."})
        return jsonify({"ok": False, "error": "License key not found."}), 404

    return jsonify({"ok": False, "error": "Unknown action."}), 400


@app.get("/api/admin/webhook")
@admin_required
def api_admin_webhook_get():
    """Get configured Discord alert webhook."""
    doc = storage.load_doc("admin_webhook.json")
    return jsonify({"ok": True, "webhook_url": doc.get("webhook_url", "")})


@app.post("/api/admin/webhook")
@admin_required
def api_admin_webhook_set():
    """Save or test Discord alert webhook."""
    data = request.get_json(silent=True) or {}
    webhook_url = str(data.get("webhook_url") or "").strip()
    storage.save_doc("admin_webhook.json", {"webhook_url": webhook_url})

    if data.get("test") and webhook_url:
        import urllib.request
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps({"content": "👑 **INDRA BOT SYSTEM Admin Alert** connected successfully!"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "IndraBotSystem/2.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
            return jsonify({"ok": True, "message": "Test ping sent to Discord webhook successfully!"})
        except Exception as e:
            return jsonify({"ok": False, "error": f"Webhook test failed: {str(e)}"}), 400

    return jsonify({"ok": True, "webhook_url": webhook_url})


@app.post("/api/admin/purge-uploads")
@admin_required
def api_admin_purge_uploads():
    """Purge temporary uploads cache to guarantee zero storage waste and maximum speed."""
    freed_bytes = 0
    count = 0
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            fpath = os.path.join(UPLOAD_DIR, name)
            if os.path.isfile(fpath):
                try:
                    freed_bytes += os.path.getsize(fpath)
                    os.remove(fpath)
                    count += 1
                except OSError:
                    pass
    mb_freed = round(freed_bytes / (1024 * 1024), 2)
    return jsonify({"ok": True, "files_deleted": count, "mb_freed": mb_freed, "message": f"Purged {count} cached files, freed {mb_freed} MB."})


# ---------------------------------------------------------------------------
# Zero-Storage Emoji & GIF Hub APIs
# ---------------------------------------------------------------------------

@app.get("/api/emojis-hub")
def api_emojis_hub():
    """Curated emojis for shop, gaming, crypto, social, and announcement embeds."""
    categories = {
        "Shop & Sales": ["💰", "💎", "🛒", "🏷️", "💳", "📦", "🎁", "🔥", "⚡", "⭐", "✨", "🎉", "🚀", "💥", "🏆", "👑"],
        "Status & Alerts": ["✅", "🟢", "🟡", "🔴", "⚠️", "⛔", "🔒", "📢", "🔔", "📌", "ℹ️", "🛡️", "🎯", "🌟", "💡", "📈"],
        "Gaming & Tech": ["🎮", "🕹️", "💻", "⌨️", "🖥️", "⚡", "👾", "🤖", "🌐", "🔗", "⚙️", "🔧", "🔋", "🔑", "🛰️", "🚀"],
        "Social & Reaction": ["❤️", "💬", "👋", "🤝", "🔥", "💯", "😎", "🥳", "👀", "🙌", "👑", "✨", "💫", "🌟", "🤩", "🚀"]
    }
    return jsonify({"ok": True, "emojis": categories})


@app.get("/api/gifs-hub")
def api_gifs_hub():
    """Curated zero-storage direct GIF URLs for banners, sales, and welcome embeds."""
    gifs = [
        {"title": "Neon Cyber Grid", "url": "https://media.giphy.com/media/xT9IgzoKnwFNmISR8I/giphy.gif", "category": "Tech"},
        {"title": "Anime Sale Banner", "url": "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif", "category": "Sales"},
        {"title": "Electric Glow Line", "url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif", "category": "Divider"},
        {"title": "Fireworks Sparkles", "url": "https://media.giphy.com/media/26tOZ42Mg6pbTUPHW/giphy.gif", "category": "Celebration"},
        {"title": "Discord Nitro Wave", "url": "https://media.giphy.com/media/ule4akeEDWAYJJWTdQ/giphy.gif", "category": "Gaming"},
        {"title": "Retro Vaporwave Sunset", "url": "https://media.giphy.com/media/L1R1tvI9svkIWwpVYr/giphy.gif", "category": "Aesthetic"},
        {"title": "Gold Coins Rain", "url": "https://media.giphy.com/media/67ThRZlYBvibtdF9UC/giphy.gif", "category": "Crypto/Shop"},
        {"title": "Welcome Wave", "url": "https://media.giphy.com/media/ASd0Ukj0BC5roG5Lmp/giphy.gif", "category": "Welcome"}
    ]
    return jsonify({"ok": True, "gifs": gifs})


# ---------------------------------------------------------------------------
# The dashboard page
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    """Show the INDRA BOT SYSTEM dashboard."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Small bot helpers used by many routes
# ---------------------------------------------------------------------------

def _requested_bot_id():
    """
    Which bot did the page ask for? The ?bot= query parameter wins; without
    it we use the active bot from the settings (or the first enabled bot).
    """
    from_query = (request.args.get("bot") or "").strip()
    if from_query:
        return from_query
    return get_settings().get("active_bot_id") or bots.default_bot_id(base_dir=current_user_dir())


def _bot_or_error(bot_id=None):
    """
    Resolve the bot a request should run as.
    Returns (record, client, None) or (None, None, error_response).

    When a SPECIFIC bot was asked for (?bot=... / bot_id in the body),
    it must exist and be enabled - otherwise the user gets a clear error
    instead of a different bot silently posting the message. Only an
    empty request falls back to the active/default bot.
    """
    ud = current_user_dir()
    bot_id = (bot_id or "").strip() or _requested_bot_id()
    record = bots.resolve_bot(bot_id, strict=bool(bot_id), base_dir=ud)

    if record is None:
        # an explicit id that is unknown or disabled -> say which and why
        known = bots.get_bot_record(bot_id, base_dir=ud) if bot_id else None
        if not bot_id:
            return None, None, (jsonify({
                "ok": False,
                "error": ("There is no bot yet. Open the Bots page and add one "
                          "(paste its token from the Discord Developer Portal)."),
                "error_kind": "no_bot",
            }), 400)
        if known is not None:
            return None, None, (jsonify({
                "ok": False,
                "error": (f"{known.get('display_name', bot_id)} is disabled, so it "
                          "cannot be used right now. Enable it on the Bots page, or "
                          "pick another bot."),
                "error_kind": "bot_disabled",
            }), 400)
        return None, None, (jsonify({
            "ok": False,
            "error": (f"There is no bot with id '{bot_id}'. Check the Bots page - "
                      "the id is shown on each card."),
            "error_kind": "unknown_bot",
        }), 400)

    if not bots.read_token(record, base_dir=ud):
        return None, None, (jsonify({
            "ok": False,
            "error": (f"{record.get('display_name', 'The bot')} has no token configured. "
                      "Open the Bots page and paste a valid bot token."),
            "error_kind": "no_token",
        }), 400)
    return record, bots.get_client(record["id"], base_dir=ud), None


def _bot_error_response(error):
    """Turn a DiscordAPIError into a clean JSON answer that names the bot."""
    friendly = error.friendly
    if error.bot and error.bot not in friendly:
        friendly = f"{error.bot}: {friendly}"
    return jsonify({"ok": False, "error": friendly, "error_kind": error.kind}), 400


# ---------------------------------------------------------------------------
# Connection status - the pill / switcher in the top bar
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    """
    Is a bot's token working? Called by the switcher in the header.

    Answers either:
      { "connected": true,  "bot": { id, name, username, avatar_url, bot_id } }
    or
      { "connected": false, "error": "plain-English problem + fix" }
    """
    ud = current_user_dir()
    bot_id = (request.args.get("bot") or "").strip() or _requested_bot_id()
    record = bots.get_bot_record(bot_id, base_dir=ud) if bot_id else bots.resolve_bot(None, base_dir=ud)

    if record is None:
        return jsonify({
            "connected": False, "bot": None, "bot_id": bot_id,
            "error": ("No bot is set up yet. Open the Bots page and add one - "
                      "you only need its name and its token from the Discord "
                      "Developer Portal (Bot tab > Reset Token)."),
            "error_kind": "no_bot",
        })

    if not bots.read_token(record, base_dir=ud):
        return jsonify({
            "connected": False, "bot": None, "bot_id": record.get("id"),
            "error": (f"{record.get('display_name', 'The bot')} has no token configured. "
                      "Open the Bots page and add the bot token."),
            "error_kind": "no_token",
        })

    try:
        client = bots.get_client(record["id"], base_dir=ud)
        me = client.get_me()
        return jsonify({
            "connected": True,
            "bot_id": record.get("id"),
            "bot": {
                "id": me.get("id"),
                "name": me.get("display_name") or me.get("username", "Bot"),
                "username": me.get("username"),
                "avatar_url": discord_api.avatar_url(me),
            },
            "error": None, "error_kind": None,
        })
    except discord_api.DiscordAPIError as error:
        return jsonify({
            "connected": False, "bot": None, "bot_id": record.get("id"),
            "error": error.friendly, "error_kind": error.kind,
        })


# ---------------------------------------------------------------------------
# Bots page - the registry API (NO tokens ever leave this file)
# ---------------------------------------------------------------------------

@app.get("/api/bots")
def api_bots_list():
    """Every registered bot, with the token replaced by a '••••last4' hint."""
    return jsonify({"ok": True, "bots": bots.list_bots(base_dir=current_user_dir())})


@app.post("/api/bots")
def api_bots_add():
    """
    Add a bot (step 1 of the wizard). The page sends:
      display_name, kind ("seller" | "messenger" | "custom"),
      token (pasted by the user), allow_everyone (invite permissions),
      notes (optional).
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Nothing was sent."}), 400

    display_name = str(data.get("display_name") or data.get("name") or "").strip()
    token = str(data.get("token", "")).strip()
    kind = str(data.get("kind", "custom")).strip()
    allow_everyone = bool(data.get("allow_everyone", False))
    notes = str(data.get("notes", "")).strip()

    if not display_name:
        return jsonify({"ok": False, "error": "Give the bot a name first."}), 400
    if not token:
        return jsonify({"ok": False,
                        "error": "Paste the bot token (Discord Developer Portal > "
                                 "your app > Bot > Reset Token > Copy)."}), 400
    if _has_broken_characters(data):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    ud = current_user_dir()
    try:
        record = bots.add_bot(display_name, kind, token,
                              allow_everyone=allow_everyone, notes=notes, base_dir=ud)
    except discord_api.DiscordAPIError as error:
        return _bot_error_response(error)

    try:
        invite_url = bots.invite_url_for(record["id"], base_dir=ud)
    except (discord_api.DiscordAPIError, KeyError):
        invite_url = None

    return jsonify({
        "ok": True,
        "bot": record,
        "invite_url": invite_url,
    })


@app.post("/api/bots/<bot_id>")
def api_bots_update(bot_id):
    """Rename a bot, change its kind, its note, or its ping permission."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Nothing was sent."}), 400

    changes = {}
    if "display_name" in data:
        name = str(data["display_name"]).strip()[:60]
        if not name:
            return jsonify({"ok": False, "error": "The bot needs a name."}), 400
        changes["display_name"] = name
    if "kind" in data and data["kind"] in bots.KINDS:
        changes["kind"] = data["kind"]
    if "notes" in data:
        changes["notes"] = str(data["notes"]).strip()[:200]
    if "allow_everyone" in data:
        changes["allow_everyone"] = bool(data["allow_everyone"])
    if _has_broken_characters(changes):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    record = bots.update_bot(bot_id, base_dir=current_user_dir(), **changes)
    if record is None:
        return jsonify({"ok": False, "error": "That bot does not exist."}), 404
    return jsonify({"ok": True, "bot": record})


@app.post("/api/bots/<bot_id>/toggle")
def api_bots_toggle(bot_id):
    """Switch a bot on (usable everywhere) or off (skipped everywhere)."""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    record = bots.set_enabled(bot_id, enabled, base_dir=current_user_dir())
    if record is None:
        return jsonify({"ok": False, "error": "That bot does not exist."}), 404
    return jsonify({"ok": True, "bot": record})


@app.post("/api/bots/<bot_id>/test")
def api_bots_test(bot_id):
    """The 'Test connection' button: ask Discord who this bot is RIGHT NOW."""
    ud = current_user_dir()
    try:
        record = bots.test_bot(bot_id, base_dir=ud)
    except KeyError:
        return jsonify({"ok": False, "error": "That bot does not exist."}), 404
    except discord_api.DiscordAPIError as error:
        return _bot_error_response(error)

    servers = []
    try:
        guilds = bots.get_client(bot_id, base_dir=ud).get_my_guilds()
        servers = [{"id": g.get("id"), "name": g.get("name", "?")}
                   for g in guilds]
    except (discord_api.DiscordAPIError, KeyError):
        pass

    return jsonify({"ok": True, "bot": record, "servers": servers})


@app.post("/api/bots/<bot_id>/invite")
def api_bots_invite(bot_id):
    """Build the invite link for a bot."""
    data = request.get_json(silent=True) or {}
    allow_everyone = bool(data.get("allow_everyone", False))
    try:
        url = bots.invite_url_for(bot_id, allow_everyone, base_dir=current_user_dir())
    except KeyError:
        return jsonify({"ok": False, "error": "That bot does not exist."}), 404
    except discord_api.DiscordAPIError as error:
        return _bot_error_response(error)
    return jsonify({"ok": True, "invite_url": url})


@app.delete("/api/bots/<bot_id>")
def api_bots_remove(bot_id):
    """Remove a bot from the user's registry."""
    ud = current_user_dir()
    if not bots.remove_bot(bot_id, base_dir=ud):
        return jsonify({"ok": False, "error": "That bot does not exist."}), 404

    # If the removed bot was the active one, fall back to another.
    settings = get_settings(base_dir=ud)
    if settings.get("active_bot_id") == bot_id:
        settings["active_bot_id"] = bots.default_bot_id(base_dir=ud)
        save_settings(settings, base_dir=ud)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Server ("guild") and channel pickers - every route is bot-scoped
# ---------------------------------------------------------------------------

@app.get("/api/guilds")
def api_guilds():
    """
    List the servers the bot is a member of, sorted by name.

    For every server we also check whether the bot has the permissions it
    needs, so the page can show a friendly warning next to servers that
    were invited without them.
    """
    record, client, error = _bot_or_error()
    if error:
        return error

    try:
        guilds = client.get_my_guilds()
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    result = []
    for guild in guilds:
        if not isinstance(guild, dict) or not guild.get("id"):
            continue                      # defensive: skip broken entries
        # Permissions arrive as a string of digits - turn into a number.
        try:
            perms = int(guild.get("permissions", 0))
        except (TypeError, ValueError):
            perms = 0

        has_admin = bool(perms & discord_api.P_ADMINISTRATOR)
        has_needed = (perms & discord_api.REQUIRED_PERMISSIONS) == discord_api.REQUIRED_PERMISSIONS

        result.append({
            "id": guild["id"],
            "name": guild.get("name", "Unnamed server"),
            "icon_url": discord_api.guild_icon_url(guild),
            "missing_permissions": not (has_admin or has_needed),
            "approximate_member_count": guild.get("approximate_member_count", 0),
            "approximate_presence_count": guild.get("approximate_presence_count", 0),
        })

    result.sort(key=lambda guild: guild["name"].lower())
    return jsonify({"ok": True, "bot_id": record["id"], "guilds": result})


@app.get("/api/channels/<guild_id>")
def api_channels(guild_id):
    """
    List a server's channels, grouped by their category (the collapsible
    folders in Discord's sidebar).

    Only channels that can receive text messages are included
    (type 0 = normal text channel, 5 = announcement channel).
    Voice channels are skipped - you cannot post listings into them.
    """
    if not guild_id.isdigit():
        return jsonify({"ok": False,
                        "error": "That server ID looks wrong - it should be numbers only."})

    record, client, error = _bot_or_error()
    if error:
        return error

    try:
        all_channels = client.get_guild_channels(guild_id)
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    # Discord sends every channel AND every category in one flat list, in no
    # guaranteed order. So: pass 1 - remember the categories, pass 2 - drop
    # each channel into its category's bucket.
    categories = {}
    for channel in all_channels:
        if channel.get("type") == 4:            # 4 = category folder
            categories[channel["id"]] = channel

    buckets = {}                # category id -> list of channels inside it
    without_category = []       # channels that hang directly in the server

    for channel in all_channels:
        kind = channel.get("type")
        if kind not in (0, 5):                  # keep text + announcement only
            continue

        entry = {
            "id": channel["id"],
            "name": channel.get("name", "channel"),
            "type": kind,
            # "position" is Discord's own sort number - we use it to show the
            # channels in the same order as the sidebar, then remove it.
            "position": channel.get("position", 0),
        }

        parent_id = channel.get("parent_id")
        if parent_id and parent_id in categories:
            buckets.setdefault(parent_id, []).append(entry)
        else:
            without_category.append(entry)

    groups = []
    if without_category:
        without_category.sort(key=lambda c: c["position"])
        groups.append({"id": None, "name": "No category", "channels": without_category})

    for category_id, category in sorted(categories.items(),
                                        key=lambda item: item[1].get("position", 0)):
        members = buckets.get(category_id, [])
        if not members:
            continue                             # category with no text channels
        members.sort(key=lambda c: c["position"])
        groups.append({
            "id": category_id,
            "name": category.get("name", "Category"),
            "channels": members,
        })

    # Remove the helper key - the browser does not need it.
    for group in groups:
        for channel in group["channels"]:
            channel.pop("position", None)

    return jsonify({"ok": True, "bot_id": record["id"],
                    "guild_id": guild_id, "groups": groups})


@app.get("/api/roles/<guild_id>")
def api_roles(guild_id):
    """
    The roles of one server. Used for two little niceties in the page:
      * the "insert @role ping" buttons under the message-above-embed field
      * showing role names (instead of <@&123>) in the live preview
    """
    if not guild_id.isdigit():
        return jsonify({"ok": False, "error": "That server ID looks wrong."})

    record, client, error = _bot_or_error()
    if error:
        return error

    try:
        roles = client.get_guild_roles(guild_id)
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    result = []
    for role in roles:
        if guild_id and role.get("id") == guild_id:
            continue                      # the @everyone role - skip it
        color = role.get("color") or 0
        result.append({
            "id": role["id"],
            "name": role.get("name", "role"),
            "managed": bool(role.get("managed")),   # bot roles - cannot be pinged
            "position": role.get("position", 0),
            "color": f"#{color:06x}" if color else None,
        })

    result.sort(key=lambda role: role["position"], reverse=True)
    return jsonify({"ok": True, "roles": result})


@app.get("/api/emojis/<guild_id>")
def api_emojis(guild_id):
    """
    The custom emojis of one server (used by the emoji picker so you can
    click a server emoji instead of remembering its name).
    """
    if not guild_id.isdigit():
        return jsonify({"ok": False, "error": "That server ID looks wrong."})

    record, client, error = _bot_or_error()
    if error:
        return error

    try:
        emojis = client.get_guild_emojis(guild_id)
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    result = []
    for emoji in emojis:
        if not isinstance(emoji, dict) or not emoji.get("id"):
            continue
        result.append({
            "id": emoji["id"],
            "name": emoji.get("name", "emoji"),
            "animated": bool(emoji.get("animated")),
            "url": discord_api.emoji_url(emoji),
            # how you write it in a message:  :name:
            "tag": f":{emoji.get('name', 'emoji')}:",
        })

    result.sort(key=lambda e: e["name"].lower())
    return jsonify({"ok": True, "emojis": result})


@app.get("/api/lookup-channel/<channel_id>")
def api_lookup_channel(channel_id):
    """
    Check a channel ID that was pasted by hand (the fallback in the picker)
    and return its name and server, so you know you picked the right one.
    """
    # A real channel ID is 15-21 digits - anything else cannot be right,
    # so we answer with a helpful hint instead of a confusing Discord error.
    if not (channel_id.isdigit() and 15 <= len(channel_id) <= 21):
        return jsonify({
            "ok": False,
            "error": ("A channel ID is 15-21 digits. In Discord: Settings > "
                      "Advanced > enable Developer Mode, then right-click the "
                      "channel and choose 'Copy Channel ID'."),
        })

    record, client, error = _bot_or_error()
    if error:
        return error

    try:
        channel = client.get_channel(channel_id)
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    # Also fetch the server's name so we can show "#store in My Server".
    guild_name = None
    if channel.get("guild_id"):
        try:
            guild = client.get_guild(channel["guild_id"])
            guild_name = guild.get("name")
        except discord_api.DiscordAPIError:
            guild_name = None   # not fatal - we just skip the server name

    return jsonify({
        "ok": True,
        "channel": {
            "id": channel["id"],
            "name": channel.get("name", "channel"),
            "type": channel.get("type"),
            "guild_id": channel.get("guild_id"),
            "guild_name": guild_name,
        },
    })


# ---------------------------------------------------------------------------
# Settings - how the app remembers your choices
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def api_get_settings():
    """Send the saved settings to the page."""
    return jsonify({"ok": True, "settings": get_settings()})


@app.post("/api/settings")
def api_save_settings():
    """
    Save the settings keys the page sends. Only keys the app knows are
    accepted (see DEFAULT_SETTINGS above), and their types are checked.
    """
    incoming = request.get_json(silent=True)
    if not isinstance(incoming, dict):
        return jsonify({"ok": False, "error": "The settings data was not valid."})

    settings = get_settings()
    for key, value in incoming.items():
        if key == "last_guild_id":
            if isinstance(value, str):
                settings[key] = value
        elif key in ("active_bot_id", "ticket_channel_id",
                     "ticket_channel_name", "ticket_line_text"):
            if isinstance(value, str):
                settings[key] = value
        elif key == "last_channel_ids":
            if isinstance(value, list) and all(isinstance(i, str) for i in value):
                settings[key] = value
        elif key in ("ticket_line_enabled", "allow_everyone_mentions"):
            if isinstance(value, bool):
                settings[key] = value
        # anything else -> unknown key -> silently ignored

    # the active bot must really exist and be enabled
    if settings.get("active_bot_id"):
        record = bots.get_bot_record(settings["active_bot_id"])
        if not record or not record.get("enabled", True):
            settings["active_bot_id"] = bots.default_bot_id()

    storage.save_doc("settings.json", settings)
    return jsonify({"ok": True, "settings": settings})


@app.get("/api/config")
def api_config():
    """
    Harmless app settings for the page (nothing secret - no token!).
    Tells the page whether the "Send test" button can work, and where
    your data lives.
    """
    test_channel = os.getenv("TEST_CHANNEL_ID", "").strip()
    return jsonify({
        "ok": True,
        "test_channel_id": test_channel,
        "test_channel_set": bool(test_channel),
        "allow_lan": os.getenv("ALLOW_LAN", "").strip().lower() in ("1", "true", "yes", "on"),
        "data_dir": DATA_DIR,
        "app_name": "INDRA BOT SYSTEM",
        "bot_count": bots.count_enabled(),
        "invite_permissions": discord_api.INVITE_PERMISSIONS,
        "invite_permissions_everyone": discord_api.INVITE_PERMISSIONS_WITH_EVERYONE,
    })


# ---------------------------------------------------------------------------
# Product library (data/products.json)
# ---------------------------------------------------------------------------

@app.get("/api/products")
def api_products_list():
    """All saved products, newest first."""
    products = load_items("products.json")
    products.sort(key=lambda p: p.get("updatedAt", ""), reverse=True)
    return jsonify({"ok": True, "products": products})


def _clean_product(incoming):
    """Trim + sanitize the fields of one product the page sent."""
    incoming["id"] = str(incoming.get("id", ""))[:64]
    incoming["name"] = str(incoming.get("name", "")).strip()[:200] or "Untitled product"
    incoming["updatedAt"] = datetime.now().isoformat(timespec="seconds")

    # pricing plans: keep the shape tight (max 10, short labels)
    plans = []
    for index, plan in enumerate(incoming.get("plans") or []):
        if not isinstance(plan, dict):
            continue
        label = str(plan.get("label", "")).strip()[:80]
        if not label:
            continue
        plans.append({
            "id": str(plan.get("id") or f"plan-{index + 1}")[:40],
            "label": label,
            "price": str(plan.get("price") or "").strip()[:24],
            "oldPrice": str(plan.get("oldPrice") or "").strip()[:24],
            "badge": str(plan.get("badge") or "").strip()[:24],
        })
    incoming["plans"] = plans[:10]
    incoming["theme_id"] = str(incoming.get("theme_id") or "").strip()[:40]

    # remember which bot this product belongs to (default: the active one)
    if not incoming.get("bot_id"):
        incoming["bot_id"] = get_settings().get("active_bot_id") or bots.default_bot_id()
    return incoming


@app.post("/api/products")
def api_products_save():
    """
    Save one product (create it if the id is new, update it if it exists).
    The page sends the whole product object it built in the form.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("product"), dict):
        return jsonify({"ok": False, "error": "No product was sent."})

    incoming = data["product"]
    if not isinstance(incoming.get("id"), str) or not incoming["id"]:
        return jsonify({"ok": False, "error": "The product has no id."})
    if _has_broken_characters(incoming):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE})

    incoming = _clean_product(incoming)

    with DATA_LOCK:
        products = load_items("products.json")
        found = False
        for index, product in enumerate(products):
            if product.get("id") == incoming["id"]:
                products[index] = incoming
                found = True
                break
        if not found:
            products.append(incoming)
        save_items("products.json", products)

    return jsonify({"ok": True, "product": incoming})


@app.delete("/api/products/<product_id>")
def api_products_delete(product_id):
    """Delete one saved product."""
    with DATA_LOCK:
        products = load_items("products.json")
        products = [p for p in products if p.get("id") != product_id]
        save_items("products.json", products)
    return jsonify({"ok": True})


@app.post("/api/products/import")
def api_products_import():
    """
    Add products from a JSON file you exported earlier (or from a friend).
    Products with an id that already exists are replaced.
    """
    data = request.get_json(silent=True)
    incoming = data.get("products") if isinstance(data, dict) else None
    if not isinstance(incoming, list):
        # also accept a bare list
        incoming = data if isinstance(data, list) else None
    if not isinstance(incoming, list):
        return jsonify({"ok": False, "error": "That file did not contain a products list."})

    if _has_broken_characters(incoming):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE})

    clean = []
    for item in incoming:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("id"), str) or not item["id"]:
            item["id"] = uuid.uuid4().hex[:12]
        item = _clean_product(item)
        if not item.get("bot_id"):
            item["bot_id"] = "seller"
        clean.append(item)

    if not clean:
        return jsonify({"ok": False, "error": "No valid products were found in that file."})

    with DATA_LOCK:
        products = load_items("products.json")
        by_id = {p["id"]: i for i, p in enumerate(products)}
        for item in clean:
            if item["id"] in by_id:
                products[by_id[item["id"]]] = item
            else:
                products.append(item)
                by_id[item["id"]] = len(products) - 1
        save_items("products.json", products)

    return jsonify({"ok": True, "added": len(clean)})


@app.get("/api/products/export")
def api_products_export():
    """Download all saved products as one JSON file (a backup)."""
    products = load_items("products.json")
    blob = json.dumps(products, indent=2, ensure_ascii=False).encode("utf-8")
    return send_file(BytesIO(blob), as_attachment=True,
                     download_name="indra-products.json",
                     mimetype="application/json")


# ---------------------------------------------------------------------------
# Server Stats (Live Discord Metrics & Welcome Cards)
# ---------------------------------------------------------------------------

@app.get("/api/guild-stats/<guild_id>")
def api_guild_stats(guild_id):
    """Fetch live member count, online count, boosts, and details for a server."""
    record, client, err = _bot_or_error()
    if err:
        return err
    try:
        guild = client.get_guild(guild_id, force=True)
        channels = client.get_guild_channels(guild_id)
        roles = client.get_guild_roles(guild_id)
        stats = {
            "id": guild.get("id", guild_id),
            "name": guild.get("name", "Unknown Server"),
            "approximate_member_count": guild.get("approximate_member_count", 0),
            "approximate_presence_count": guild.get("approximate_presence_count", 0),
            "premium_subscription_count": guild.get("premium_subscription_count", 0),
            "premium_tier": guild.get("premium_tier", 0),
            "channels_count": len(channels) if isinstance(channels, list) else 0,
            "roles_count": len(roles) if isinstance(roles, list) else 0,
            "icon_url": discord_api.guild_icon_url(guild, 128),
            "banner_url": discord_api.guild_banner_url(guild, 512),
            "description": guild.get("description") or "",
        }
        return jsonify({"ok": True, "stats": stats})
    except discord_api.DiscordAPIError as err:
        return _bot_error_response(err)


@app.post("/api/server-stats/post")
def api_server_stats_post():
    """Post an aesthetic Server Stats & Info Card directly to a Discord channel."""
    data = request.get_json(silent=True) or {}
    guild_id = str(data.get("guild_id") or "").strip()
    channel_id = str(data.get("channel_id") or "").strip()
    bot_id = str(data.get("bot_id") or "").strip()
    record, client, err = _bot_or_error(bot_id)
    if err:
        return err
    if not guild_id or not channel_id:
        return jsonify({"ok": False, "error": "Server ID and Channel ID are required."}), 400

    try:
        guild = client.get_guild(guild_id, force=True)
        channels = client.get_guild_channels(guild_id)
        roles = client.get_guild_roles(guild_id)
        icon = discord_api.guild_icon_url(guild, 128)
        banner = discord_api.guild_banner_url(guild, 512)

        members = guild.get("approximate_member_count", "N/A")
        online = guild.get("approximate_presence_count", "N/A")
        boosts = guild.get("premium_subscription_count", 0)
        tier = guild.get("premium_tier", 0)

        embed = {
            "title": f"📊 {guild.get('name', 'Server')} • Live Statistics",
            "description": (f"Welcome to **{guild.get('name')}**! Here is our live community overview:\n\n"
                            f"> 👥 **Total Members:** `{members}`\n"
                            f"> 🟢 **Online Now:** `{online}`\n"
                            f"> 🚀 **Server Boosts:** `{boosts}` (Level {tier})\n"
                            f"> 💬 **Channels:** `{len(channels)}` | 🏷️ **Roles:** `{len(roles)}`\n"),
            "color": 0x5865F2,
            "footer": {"text": "INDRA BOT SYSTEM • Live Community Stats"},
            "timestamp": datetime.now().isoformat(),
        }
        if icon:
            embed["thumbnail"] = {"url": icon}
        if banner:
            embed["image"] = {"url": banner}

        res = client.send_message(channel_id, {"embeds": [embed]})
        return jsonify({"ok": True, "message_id": res.get("id") if res else ""})
    except discord_api.DiscordAPIError as err:
        return _bot_error_response(err)


# ---------------------------------------------------------------------------
# Vouches & Customer Review Card Generator (data/vouches.json)
# ---------------------------------------------------------------------------

@app.get("/api/vouches")
def api_vouches_list():
    """List all saved customer vouches / reviews."""
    vouches = load_items("vouches.json")
    vouches.sort(key=lambda v: v.get("createdAt", ""), reverse=True)
    return jsonify({"ok": True, "vouches": vouches})


@app.post("/api/vouches")
def api_vouches_save():
    """Save or update a customer vouch."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("vouch"), dict):
        return jsonify({"ok": False, "error": "No vouch data provided."}), 400

    v = data["vouch"]
    vouch_id = str(v.get("id") or "").strip() or ("vouch-" + uuid.uuid4().hex[:8])
    rating = max(1, min(5, int(v.get("rating") or 5)))
    now_str = datetime.now().isoformat(timespec="seconds")

    incoming = {
        "id": vouch_id,
        "customer_name": str(v.get("customer_name") or "Anonymous").strip()[:80],
        "rating": rating,
        "product_name": str(v.get("product_name") or "Digital Product").strip()[:100],
        "review": str(v.get("review") or "").strip()[:2000],
        "image_url": str(v.get("image_url") or "").strip(),
        "verified_buyer": bool(v.get("verified_buyer", True)),
        "createdAt": v.get("createdAt") or now_str,
        "updatedAt": now_str,
    }

    with DATA_LOCK:
        vouches = load_items("vouches.json")
        found = False
        for i, existing in enumerate(vouches):
            if existing.get("id") == vouch_id:
                vouches[i] = incoming
                found = True
                break
        if not found:
            vouches.append(incoming)
        save_items("vouches.json", vouches)

    return jsonify({"ok": True, "vouch": incoming})


@app.delete("/api/vouches/<vouch_id>")
def api_vouches_delete(vouch_id):
    """Delete a customer vouch."""
    with DATA_LOCK:
        vouches = load_items("vouches.json")
        vouches = [v for v in vouches if v.get("id") != vouch_id]
        save_items("vouches.json", vouches)
    return jsonify({"ok": True})


@app.post("/api/vouches/send")
def api_vouches_send():
    """Post a customer review embed directly to Discord."""
    data = request.get_json(silent=True) or {}
    v = data.get("vouch") or {}
    channel_id = str(data.get("channel_id") or "").strip()
    bot_id = str(data.get("bot_id") or "").strip()

    record, client, err = _bot_or_error(bot_id)
    if err:
        return err
    if not channel_id:
        return jsonify({"ok": False, "error": "Please pick a channel for vouches."}), 400

    stars = "⭐" * max(1, min(5, int(v.get("rating") or 5)))
    buyer = str(v.get("customer_name") or "Verified Customer")
    product = str(v.get("product_name") or "Product")
    review = str(v.get("review") or "Great purchase, fast and smooth delivery!")

    embed = {
        "title": f"⭐ Customer Review • {stars}",
        "description": f"> {review}\n",
        "color": 0xF0B132,
        "fields": [
            {"name": "👤 Buyer", "value": f"**{buyer}**" + (" `[Verified Buyer ✅]`" if v.get("verified_buyer") else ""), "inline": True},
            {"name": "📦 Product", "value": f"**{product}**", "inline": True},
            {"name": "⭐ Rating", "value": f"{stars} `({v.get('rating', 5)}/5)`", "inline": True},
        ],
        "footer": {"text": "INDRA BOT SYSTEM • Customer Feedback & Vouches"},
        "timestamp": datetime.now().isoformat(),
    }
    img = str(v.get("image_url") or "").strip()
    if img:
        embed["image"] = {"url": img}

    try:
        sent = client.send_message(channel_id, {"embeds": [embed]})
        return jsonify({"ok": True, "message_id": sent.get("id") if sent else ""})
    except discord_api.DiscordAPIError as err:
        return _bot_error_response(err)


# ---------------------------------------------------------------------------
# Link Sender & Directory Hub (data/links.json)
# ---------------------------------------------------------------------------

DEFAULT_STARTER_LINKS = [
    {
        "id": "links-official",
        "name": "🌐 Official Hub & Store",
        "title": "🌐 INDRA BOT SYSTEM • Official Links",
        "description": "Welcome to our official directory! Use the buttons below to access our store, community, and support portals.",
        "color": "#5865F2",
        "thumbnail_url": "",
        "banner_url": "",
        "render_buttons": True,
        "links": [
            {"emoji": "🌐", "label": "Official Website", "url": "https://indra.gg", "description": "Explore features, documentation & guides", "button": True},
            {"emoji": "🛒", "label": "Digital Store", "url": "https://indra.gg/shop", "description": "Instant delivery keys, products & subscriptions", "button": True},
            {"emoji": "💬", "label": "Discord Community", "url": "https://discord.gg/indra", "description": "Join our community & customer chat", "button": True},
            {"emoji": "⭐", "label": "Customer Vouches", "url": "https://indra.gg/vouches", "description": "Read verified customer reviews & feedback", "button": True}
        ],
        "createdAt": "2026-09-19T12:00:00"
    }
]

@app.get("/api/links")
def api_links_list():
    """List all saved link directory presets."""
    links = load_items("links.json")
    if not links:
        links = DEFAULT_STARTER_LINKS
        save_items("links.json", links)
    links.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return jsonify({"ok": True, "links": links})

@app.post("/api/links")
def api_links_save():
    """Save or update a link directory preset."""
    data = request.get_json(silent=True) or {}
    bundle = data.get("bundle")
    if not isinstance(bundle, dict):
        return jsonify({"ok": False, "error": "No link bundle data sent."}), 400

    link_id = str(bundle.get("id") or "").strip() or ("link-" + uuid.uuid4().hex[:8])
    now_str = datetime.now().isoformat(timespec="seconds")
    incoming = {
        "id": link_id,
        "name": str(bundle.get("name") or "Untitled Links").strip()[:100],
        "title": str(bundle.get("title") or "🌐 Official Links").strip()[:200],
        "description": str(bundle.get("description") or "").strip()[:4000],
        "color": str(bundle.get("color") or "#5865F2").strip()[:20],
        "thumbnail_url": str(bundle.get("thumbnail_url") or "").strip(),
        "banner_url": str(bundle.get("banner_url") or "").strip(),
        "render_buttons": bool(bundle.get("render_buttons", True)),
        "links": bundle.get("links") if isinstance(bundle.get("links"), list) else [],
        "createdAt": bundle.get("createdAt") or now_str,
        "updatedAt": now_str
    }

    with DATA_LOCK:
        all_links = load_items("links.json")
        found = False
        for i, existing in enumerate(all_links):
            if existing.get("id") == link_id:
                all_links[i] = incoming
                found = True
                break
        if not found:
            all_links.append(incoming)
        save_items("links.json", all_links)

    return jsonify({"ok": True, "bundle": incoming})

@app.delete("/api/links/<link_id>")
def api_links_delete(link_id):
    """Delete a link directory preset."""
    with DATA_LOCK:
        all_links = load_items("links.json")
        all_links = [l for l in all_links if l.get("id") != link_id]
        save_items("links.json", all_links)
    return jsonify({"ok": True})

@app.post("/api/links/send")
def api_links_send():
    """Post an aesthetic link directory to Discord with optional interactive button action rows."""
    rate_err = check_send_rate_limit()
    if rate_err:
        return rate_err

    data = request.get_json(silent=True) or {}
    channel_id = str(data.get("channel_id") or "").strip()
    bot_id = str(data.get("bot_id") or "").strip()
    bundle = data.get("bundle") or {}

    record, client, err = _bot_or_error(bot_id)
    if err:
        return err
    if not channel_id:
        return jsonify({"ok": False, "error": "Please pick a channel to send the links."}), 400

    title = str(bundle.get("title") or "🌐 Official Links").strip()
    description = str(bundle.get("description") or "").strip()
    color_hex = str(bundle.get("color") or "#5865F2").strip()
    try:
        color_int = int(color_hex.lstrip("#"), 16)
    except Exception:
        color_int = 0x5865F2

    thumbnail_url = str(bundle.get("thumbnail_url") or "").strip()
    banner_url = str(bundle.get("banner_url") or "").strip()
    render_buttons = bool(bundle.get("render_buttons", True))
    raw_links = bundle.get("links") if isinstance(bundle.get("links"), list) else []

    lines = []
    if description:
        lines.append(description)
        lines.append("")

    buttons_to_render = []
    for l in raw_links:
        if not isinstance(l, dict):
            continue
        emoji = str(l.get("emoji") or "🔗").strip()
        label = str(l.get("label") or "Link").strip()
        url = str(l.get("url") or "").strip()
        subtext = str(l.get("description") or "").strip()
        include_btn = bool(l.get("button", True))

        if not url:
            continue

        if subtext:
            lines.append(f"{emoji} [**{label}**]({url})\n> {subtext}\n")
        else:
            lines.append(f"{emoji} [**{label}**]({url})\n")

        if include_btn and render_buttons and url.startswith(("http://", "https://", "discord://")):
            btn_label = f"{emoji} {label}" if emoji and emoji != "🔗" else label
            buttons_to_render.append({
                "type": 2,          # Button
                "style": 5,         # Link button
                "label": btn_label[:80],
                "url": url[:512]
            })

    embed = {
        "title": title[:256],
        "description": "\n".join(lines)[:4096],
        "color": color_int,
        "footer": {"text": "INDRA BOT SYSTEM • Official Links & Directory"},
        "timestamp": datetime.now().isoformat()
    }
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}
    if banner_url:
        embed["image"] = {"url": banner_url}

    payload = {"embeds": [embed]}

    if buttons_to_render:
        action_rows = []
        for i in range(0, min(len(buttons_to_render), 25), 5):
            chunk = buttons_to_render[i:i+5]
            action_rows.append({"type": 1, "components": chunk})
        payload["components"] = action_rows

    ping_role = str(data.get("ping_role") or "").strip()
    is_ghost = bool(data.get("ghost_ping"))
    settings = get_settings()
    mention_rules = build_allowed_mentions(settings.get("allow_everyone_mentions", False))
    payload["allowed_mentions"] = mention_rules

    if ping_role:
        payload["content"] = ping_role

    try:
        if is_ghost and payload.get("content"):
            ping_text = payload["content"]
            payload["content"] = ""
            def _ghost_ping_worker(p_text=ping_text, ch_id=channel_id):
                try:
                    p_res = client.send_message(ch_id, {"content": p_text, "allowed_mentions": mention_rules})
                    if p_res and p_res.get("id"):
                        time.sleep(5)
                        client.delete_message(ch_id, p_res["id"])
                except Exception as ex:
                    print(f"Ghost ping worker failed: {ex}")
            threading.Thread(target=_ghost_ping_worker, daemon=True).start()

        sent = client.send_message(channel_id, payload)
        return jsonify({"ok": True, "message_id": sent.get("id") if sent else ""})
    except discord_api.DiscordAPIError as err:
        return _bot_error_response(err)


# ---------------------------------------------------------------------------
# Full Backup & Restore (ZIP)
# ---------------------------------------------------------------------------

@app.get("/api/backup/download")
def api_backup_download():
    """Package the whole data/ directory into a ZIP file for download."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        with DATA_LOCK:
            for root, _, files in os.walk(DATA_DIR):
                for fname in files:
                    if fname.endswith(".tmp") or fname.endswith(".lock"):
                        continue
                    full_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(full_p, DATA_DIR)
                    archive.write(full_p, arcname=rel_p)

    buffer.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(buffer, as_attachment=True,
                     download_name=f"indra_bot_backup_{ts}.zip",
                     mimetype="application/zip")


@app.post("/api/backup/restore")
def api_backup_restore():
    """Restore a ZIP backup into data/ with automatic pre-restore backup."""
    if "backup" not in request.files:
        return jsonify({"ok": False, "error": "No backup file uploaded."}), 400

    upload = request.files["backup"]
    if not upload.filename.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "Please upload a valid .zip file."}), 400

    try:
        buffer = BytesIO(upload.read())
        with zipfile.ZipFile(buffer, "r") as archive:
            valid_files = [f for f in archive.namelist() if f.endswith(".json")]
            if not valid_files:
                return jsonify({"ok": False, "error": "The ZIP contains no valid JSON data files."}), 400

            with DATA_LOCK:
                storage.backup_data_folder("pre_restore")
                for f in valid_files:
                    clean_name = os.path.basename(f)
                    if clean_name.endswith(".json"):
                        content = archive.read(f)
                        with open(os.path.join(DATA_DIR, clean_name), "wb") as out:
                            out.write(content)

        return jsonify({"ok": True, "restored_count": len(valid_files)})
    except Exception as err:
        return jsonify({"ok": False, "error": f"Failed to restore backup: {err}"}), 500


# ---------------------------------------------------------------------------
# Sections (data/sections.json) - the Messenger bot's content:
# announcements, rules, updates - anything that is not a product listing.
# A section is a content model too, so sending it is just /api/send with
# kind "section" - the renderer does the rest.
# ---------------------------------------------------------------------------

SECTION_PRESETS = ("clean", "announcement", "rules", "update")


@app.get("/api/sections")
def api_sections_list():
    """All saved sections, newest first."""
    sections = load_items("sections.json")
    sections.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
    return jsonify({"ok": True, "sections": sections})


@app.post("/api/sections")
def api_sections_save():
    """
    Save one section (create it if the id is new, update it if it exists).
    The page sends the whole section object built in the Sections tab.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("section"), dict):
        return jsonify({"ok": False, "error": "No section was sent."}), 400

    incoming = data["section"]
    if not isinstance(incoming.get("id"), str) or not incoming["id"]:
        return jsonify({"ok": False, "error": "The section has no id."}), 400
    if _has_broken_characters(incoming):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    incoming["id"] = incoming["id"][:64]
    incoming["kind"] = "section"
    incoming["name"] = str(incoming.get("name", "")).strip()[:120] or "Untitled section"
    incoming["title"] = str(incoming.get("title", "")).strip()[:200]
    incoming["body"] = str(incoming.get("body", "")).strip()
    incoming["preset"] = incoming.get("preset") if incoming.get("preset") in SECTION_PRESETS \
        else "clean"
    incoming["theme_id"] = str(incoming.get("theme_id") or "").strip()[:40]
    incoming["ticketLineMode"] = "hide"          # sections never carry a ticket line
    incoming["updatedAt"] = datetime.now().isoformat(timespec="seconds")

    # the section may remember which bot usually posts it ("" = the active bot)
    if not isinstance(incoming.get("bot_id"), str):
        incoming["bot_id"] = ""

    with DATA_LOCK:
        sections = load_items("sections.json")
        found = False
        for index, section in enumerate(sections):
            if section.get("id") == incoming["id"]:
                sections[index] = incoming
                found = True
                break
        if not found:
            sections.append(incoming)
        save_items("sections.json", sections)

    return jsonify({"ok": True, "section": incoming})


@app.delete("/api/sections/<section_id>")
def api_sections_delete(section_id):
    """Delete one saved section (messages already sent are NOT deleted)."""
    with DATA_LOCK:
        sections = load_items("sections.json")
        sections = [s for s in sections if s.get("id") != section_id]
        save_items("sections.json", sections)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Looks: font styles + themes (data/themes.json)
# ---------------------------------------------------------------------------

@app.get("/api/fontstyles")
def api_fontstyles():
    """
    The 11 Unicode heading styles for the pickers in the page - including
    the letter tables, so the page can show live styled previews exactly
    like the server will render them (one source of truth again).
    """
    import fontstyles as _fs
    menu = []
    for style_id in _fs.STYLE_ORDER:
        menu.append({
            "id": style_id,
            "label": _fs._STYLE_LABELS[style_id],
            "sample": _fs.apply_style("Aa Bb 123", style_id),
            "upper": _fs._STYLED_TABLES[style_id]["upper"],
            "lower": _fs._STYLED_TABLES[style_id]["lower"],
            "digits": _fs._STYLED_TABLES[style_id]["digits"],
        })
    return jsonify({"ok": True, "styles": menu})


@app.get("/api/themes")
def api_themes_list():
    """Every theme: the 12 built-ins first, then your custom ones."""
    return jsonify({"ok": True, "themes": themes.list_themes(base_dir=current_user_dir())})


@app.post("/api/themes")
def api_themes_save():
    """
    Create or update a CUSTOM theme. Built-in themes are refused - use the
    duplicate button to make your own editable copy of one of those.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("theme"), dict):
        return jsonify({"ok": False, "error": "No theme was sent."}), 400
    if _has_broken_characters(data["theme"]):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    theme, error = themes.save_theme(data["theme"],
                                     data.get("id") or data["theme"].get("id"),
                                     base_dir=current_user_dir())
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "theme": theme})


@app.post("/api/themes/<theme_id>/duplicate")
def api_themes_duplicate(theme_id):
    """Copy any theme (built-ins included) into your own editable one."""
    theme, error = themes.duplicate_theme(theme_id, base_dir=current_user_dir())
    if error:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "theme": theme})


@app.delete("/api/themes/<theme_id>")
def api_themes_delete(theme_id):
    """Delete a CUSTOM theme (built-ins are part of the app and stay)."""
    ok, error = themes.delete_theme(theme_id, base_dir=current_user_dir())
    if not ok:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Image uploads from your PC (data/uploads/)
# ---------------------------------------------------------------------------

# only these picture types are allowed (Discord's own list)
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024      # 8 MB, like Discord


def _extension_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _looks_like_image(blob, extension):
    """Check the first bytes of the file really are a picture of that type."""
    if extension == "png":
        return blob[:8] == b"\x89PNG\r\n\x1a\n"
    if extension in ("jpg", "jpeg"):
        return blob[:3] == b"\xff\xd8\xff"
    if extension == "gif":
        return blob[:6] in (b"GIF87a", b"GIF89a")
    if extension == "webp":
        return blob[:4] == b"RIFF" and blob[8:12] == b"WEBP"
    return False


# Photos wider than this get scaled down on upload - Discord's own preview
# never shows more than about this width, so nothing is lost visually.
MAX_IMAGE_WIDTH = 2000
# A PNG this heavy is almost always a photo saved in the wrong format.
HEAVY_PNG_BYTES = 1_500_000


def _inspect_and_maybe_optimize(blob, extension, stem):
    """
    Pillow's two jobs on upload:
      1. PROVE the file is a real, complete image (a half-downloaded or
         renamed file is rejected instead of breaking the Discord post),
      2. shrink what Discord would shrink anyway: giant photos are scaled
         down to 2000px, and heavy PNG photos become much smaller JPEGs.
         Animated GIFs are never touched - re-encoding would kill the
         animation.

    Returns (blob, filename, info_dict). Falls back to the original bytes
    when Pillow is missing or the image does not need any help.
    """
    info = {"width": None, "height": None, "animated": False,
            "optimized": False, "note": ""}
    if not PIL_AVAILABLE:
        info["note"] = "Pillow is not installed - the file was saved as-is."
        return blob, f"{stem}.{extension}", info

    try:
        image = Image.open(BytesIO(blob))
        image.load()                       # decode everything - proves it is whole
        info["width"], info["height"] = image.size
        animated = getattr(image, "is_animated", False)
        info["animated"] = bool(animated)
    except Exception as problem:            # OSError / DecompressionBombError...
        return None, "", {"error": f"That file is not a valid image ({problem})."}

    # anything animated (GIF stickers and friends) goes out untouched
    if animated:
        info["note"] = "Animated image - saved exactly as uploaded."
        return blob, f"{stem}.{extension}", info

    try:
        needs_resize = image.width > MAX_IMAGE_WIDTH
        has_alpha = (image.mode in ("RGBA", "LA", "PA") or
                     (image.mode == "P" and "transparency" in image.info))
        needs_format = (extension == "png" and len(blob) > HEAVY_PNG_BYTES
                        and not has_alpha)

        if not needs_resize and not needs_format:
            info["note"] = "Already web-friendly - saved as uploaded."
            return blob, f"{stem}.{extension}", info

        work = image.convert("RGB") if needs_format else image
        if needs_resize:
            new_height = round(image.height * MAX_IMAGE_WIDTH / image.width)
            work = work.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)
            info["width"], info["height"] = work.size

        if needs_format:
            buffer = BytesIO()
            work.save(buffer, "JPEG", quality=85, optimize=True)
            new_extension = "jpg"
            info["note"] = "Converted to JPEG and scaled down - much smaller, same look."
        elif needs_resize:
            buffer = BytesIO()
            if work.mode == "P":
                work = work.convert("RGBA")
            work.save(buffer, image.format or "PNG", optimize=True)
            new_extension = extension
            info["note"] = "Scaled down to 2000px wide - Discord shows the same size."
        else:
            return blob, f"{stem}.{extension}", info

        if buffer.tell() >= len(blob):
            # optimization would make it BIGGER - keep the original
            info.update({"optimized": False,
                         "note": "Already well compressed - saved as uploaded."})
            info["width"], info["height"] = image.size
            return blob, f"{stem}.{extension}", info

        info["optimized"] = True
        return buffer.getvalue(), f"{stem}.{new_extension}", info
    except Exception as problem:
        # an optimization problem must never lose the user's picture
        info["note"] = f"Saved as uploaded (could not optimize: {problem})."
        return blob, f"{stem}.{extension}", info


def _valid_upload_name(name):
    """Upload names we create ourselves: letters/digits/dot/dash/underscore only."""
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name))


@app.post("/api/upload")
def api_upload():
    """
    Receive ONE image from the page (the "Upload" button next to an image
    field). Checks: max 8 MB, type png/jpg/jpeg/gif/webp, and Pillow opens
    it as a real picture. Oversized photos are automatically scaled down
    and heavy PNG photos become JPEGs, so posts stay light and fast.
    The file is saved in data/uploads/ and the page shows it via
    /uploads/<name>.
    """
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "error": "No file was received."})

    original = secure_filename(file.filename) or "image"
    extension = _extension_of(original)
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"ok": False,
                        "error": "Only PNG, JPG, JPEG, GIF and WEBP images are allowed."})

    blob = file.read()
    if len(blob) == 0:
        return jsonify({"ok": False, "error": "That file is empty."})
    if len(blob) > MAX_IMAGE_BYTES:
        return jsonify({"ok": False, "error": "That image is too big - the maximum is 8 MB."})
    if not _looks_like_image(blob, extension):
        return jsonify({"ok": False,
                        "error": "That file says it is an image but its content is not a "
                                 "valid " + extension.upper() + " picture."})

    # A safe, unique name: "photo_a1b2c3d4e5.png" - no spaces or weird chars,
    # so it can safely be referenced as attachment://photo_a1b2c3d4e5.png
    stem = original.rsplit(".", 1)[0][:40] or "image"

    blob, name, info = _inspect_and_maybe_optimize(blob, extension, stem)
    if blob is None:
        return jsonify({"ok": False, "error": info.get("error", "That file is not a valid image.")})
    name = f"{name.rsplit('.', 1)[0]}_{uuid.uuid4().hex[:10]}.{name.rsplit('.', 1)[-1]}"

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, name), "wb") as out:
        out.write(blob)

    return jsonify({
        "ok": True,
        "filename": name,
        "url": "/uploads/" + name,
        "bytes": len(blob),
        "width": info.get("width"),
        "height": info.get("height"),
        "animated": info.get("animated", False),
        "optimized": info.get("optimized", False),
        "note": info.get("note", ""),
    })


def _image_info(path):
    """Size + animation flag of one uploaded file (best effort, never raises)."""
    info = {"width": None, "height": None, "animated": False}
    if not PIL_AVAILABLE:
        return info
    try:
        with Image.open(path) as image:
            info["width"], info["height"] = image.size
            info["animated"] = bool(getattr(image, "is_animated", False))
    except Exception:
        pass
    return info


@app.get("/api/uploads")
def api_uploads_list():
    """
    Every picture you ever uploaded (the "Image library" popup) - newest
    first, with size and dimensions, so any image can be reused in any
    slot with one click.
    """
    entries = []
    if os.path.isdir(UPLOAD_DIR):
        for name in os.listdir(UPLOAD_DIR):
            path = os.path.join(UPLOAD_DIR, name)
            if not os.path.isfile(path) or not _valid_upload_name(name):
                continue
            if _extension_of(name) not in ALLOWED_IMAGE_EXTENSIONS:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append({
                "name": name,
                "url": "/uploads/" + name,
                "bytes": stat.st_size,
                "mtime": stat.st_mtime,
                **_image_info(path),
            })
    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return jsonify({"ok": True, "uploads": entries})


@app.get("/uploads/<filename>")
def api_serve_upload(filename):
    """Show an uploaded image in the preview. (Uploads folder only.)"""
    if not _valid_upload_name(filename):
        return jsonify({"ok": False, "error": "Not a valid file name."}), 404
    return send_from_directory(UPLOAD_DIR, filename, max_age=3600)


# ---------------------------------------------------------------------------
# Discord limit checks (done AGAIN here, even though the page checks too)
# ---------------------------------------------------------------------------

def _has_broken_characters(value, depth=0):
    """
    True when any text inside the data contains a "lone surrogate" - a
    broken half-character that cannot be saved or sent. This can only
    happen if a client bypassed the page, but we check anyway so the app
    can never crash on it.
    """
    if depth > 8:
        return False
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, list):
        return any(_has_broken_characters(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return any(_has_broken_characters(item, depth + 1) for item in value.values())
    return False


BROKEN_CHARACTERS_MESSAGE = ("The message contains a broken character (this can "
                             "happen with fancy Unicode text). Try turning 'Fancy "
                             "text' off and retype the affected text.")


def validate_discord_payload(payload):
    """
    Return a list of plain-English problems with a message payload, or an
    empty list when everything is within Discord's limits.
    Discord's limits: title 256, description 4096, field name 256,
    field value 1024, max 25 fields, footer 2048, author name 256,
    content 2000, 6000 characters across all embeds, max 10 embeds.
    """
    errors = []

    if _has_broken_characters(payload):
        errors.append(BROKEN_CHARACTERS_MESSAGE)
        return errors

    content = payload.get("content") or ""
    if len(content) > 2000:
        errors.append("The plain message above the embed is longer than 2000 characters.")

    embeds = payload.get("embeds") or []
    if len(embeds) > 10:
        errors.append("Too many embeds (Discord allows 10 per message).")

    total = 0
    for number, embed in enumerate(embeds, start=1):
        label = f"Embed {number}"
        if not isinstance(embed, dict):
            errors.append(f"{label} is malformed.")
            continue

        title = embed.get("title") or ""
        description = embed.get("description") or ""
        footer = (embed.get("footer") or {}).get("text") or ""
        author = (embed.get("author") or {}).get("name") or ""
        fields = embed.get("fields") or []

        if len(title) > 256:
            errors.append(f"{label}: the title is longer than 256 characters.")
        if len(description) > 4096:
            errors.append(f"{label}: the description is longer than 4096 characters.")
        if len(footer) > 2048:
            errors.append(f"{label}: the footer is longer than 2048 characters.")
        if len(author) > 256:
            errors.append(f"{label}: the author name is longer than 256 characters.")
        if len(fields) > 25:
            errors.append(f"{label}: more than 25 fields.")

        for field in fields:
            if not isinstance(field, dict):
                continue
            if len(field.get("name") or "") > 256:
                errors.append(f"{label}: a field name is longer than 256 characters.")
            if len(field.get("value") or "") > 1024:
                errors.append(f"{label}: a field value is longer than 1024 characters "
                              "(usually the Features list - make it shorter).")

        total += len(title) + len(description) + len(footer) + len(author)
        for field in fields:
            if isinstance(field, dict):
                total += len(field.get("name") or "") + len(field.get("value") or "")

    if total > 6000:
        errors.append("The embeds together are longer than Discord's 6000 character limit.")

    return errors


def resolve_upload_files(names):
    """
    Turn a list of uploaded-image names into (filename, bytes, mime) tuples
    ready for sending, and report any that are missing on disk.
    """
    files, missing = [], []
    for name in names:
        if not _valid_upload_name(name):
            missing.append(name)
            continue
        path = os.path.join(UPLOAD_DIR, name)
        if not os.path.isfile(path):
            missing.append(name)
            continue
        with open(path, "rb") as handle:
            blob = handle.read()
        mime = "image/" + ("jpeg" if _extension_of(name) in ("jpg", "jpeg")
                           else _extension_of(name))
        files.append((name, blob, mime))
    return files, missing


def build_allowed_mentions(allow_everyone):
    """
    The safe-by-default mention rules:
      * user and role mentions (like @Buyers) keep working,
      * @everyone / @here are blocked unless you explicitly turned them on.
    """
    parse = ["users", "roles"]
    if allow_everyone:
        parse.append("everyone")
    return {"parse": parse}


# ---------------------------------------------------------------------------
# Sending + history (every entry remembers WHICH bot did it)
#
# The pipeline is ALWAYS the same now:
#     content model -> renderer.render_content() -> Discord payloads
# The browser never builds payloads; it sends the content model and the
# server is the single source of truth (what the preview shows is exactly
# what gets posted).
# ---------------------------------------------------------------------------

def record_history(entry):
    """Append one line to the sent-messages history (data/history.json)."""
    with DATA_LOCK:
        history = load_items("history.json")
        history.append(entry)
        save_items("history.json", history)


def _bot_identity(record):
    """
    The {"name", "avatar_url"} the renderer puts into author lines.
    Uses the cached avatar from the registry; only asks Discord when the
    bot has never been tested. Works offline for tested bots.
    """
    record = record or {}
    avatar = str(record.get("avatar_url") or "")
    if not avatar and record.get("id"):
        try:
            me = bots.get_client(record["id"]).get_me()
            avatar = discord_api.avatar_url(me)
        except (discord_api.DiscordAPIError, KeyError):
            avatar = ""
    return {"name": record.get("display_name") or "INDRA BOT SYSTEM",
            "avatar_url": avatar}


def render_for_bot(content, record):
    """
    Render one content model as the given bot, applying its theme and the
    global settings. Returns the renderer's full result dict (never None) -
    check result["ok"] and result["errors"] before sending.
    """
    content = content if isinstance(content, dict) else {}
    theme = themes.get_theme(str(content.get("theme_id") or ""), base_dir=current_user_dir()) \
        if content.get("theme_id") else None
    return renderer.render_content(content, bot=_bot_identity(record),
                                   theme=theme, settings=get_settings())


def _validate_rendered(result):
    """
    The renderer promises Discord's limits - this double-checks every
    message it produced (defense in depth before anything leaves the PC).
    """
    problems = []
    for message in result.get("messages") or []:
        payload = {"content": message.get("content") or "",
                   "embeds": message.get("embeds") or []}
        problems.extend(validate_discord_payload(payload))
    return problems


def send_to_channels(bot_record, client, targets, content, messages, source):
    """
    Post the rendered messages to a list of channels and record history.

    bot_record - which bot is sending ({"id", "display_name"})
    client     - that bot's BotClient
    targets    - list of {"id": channel id, "name": channel name}
    content    - the content model (stored in history for later edits)
    messages   - renderer output: [{"content", "embeds", "files"}]
    source     - "manual" | "test" | "scheduled" | "repost"

    A listing can be SEVERAL Discord messages (the auto-split) - all of
    them are sent in order, and the history entry remembers every id.

    Returns one result per channel: ok / error (+ message ids when ok).
    """
    settings = get_settings()
    mention_rules = build_allowed_mentions(settings.get("allow_everyone_mentions", False))

    results = []
    for target in targets:
        channel_id = str(target.get("id", ""))
        channel_name = target.get("name", "")
        sent_ids = []
        attachments_all = []
        files_used = []
        problem = None

        is_ghost = bool(content.get("ghost_ping"))
        for message in messages:
            outgoing = {"content": message.get("content") or "",
                        "embeds": message.get("embeds") or []}
            if message.get("components"):
                outgoing["components"] = message["components"]
            outgoing["allowed_mentions"] = mention_rules

            if is_ghost and outgoing.get("content"):
                ping_text = outgoing["content"]
                outgoing["content"] = ""
                def _ghost_ping_worker(p_text=ping_text, ch_id=channel_id):
                    try:
                        p_res = client.send_message(ch_id, {"content": p_text, "allowed_mentions": mention_rules})
                        if p_res and p_res.get("id"):
                            time.sleep(5.0)
                            client.delete_message(ch_id, p_res["id"])
                    except Exception:
                        pass
                threading.Thread(target=_ghost_ping_worker, daemon=True).start()

            try:
                files, missing = resolve_upload_files(message.get("files") or [])
            except OSError as error:
                problem = f"Could not read an uploaded image: {error}"
                break
            if missing:
                problem = ("These uploaded images could not be found anymore - "
                           "please upload them again: " + ", ".join(missing))
                break

            try:
                if bot_record.get("kind") == "webhook":
                    wh_url = bots.read_token(bot_record)
                    sent = discord_api.post_webhook(wh_url, outgoing, files=files or None)
                    sent = sent or {"id": "wh_" + uuid.uuid4().hex[:8]}
                else:
                    sent = client.send_message(channel_id, outgoing, files=files or None)
            except discord_api.DiscordAPIError as error:
                friendly = error.friendly
                if error.bot and error.bot not in friendly:
                    friendly = f"{error.bot}: {friendly}"
                problem = friendly
                break

            sent_ids.append(sent["id"])
            for attachment in sent.get("attachments") or []:
                attachments_all.append({
                    "id": attachment["id"],
                    "filename": attachment["filename"],
                    "message_index": len(sent_ids) - 1,
                })
            files_used.extend(f[0] for f in (files or []))

        if problem and not sent_ids:
            results.append({"channel_id": channel_id, "ok": False,
                            "error": problem, "error_kind": "send_failed"})
            continue

        # remember what was sent (even a partial send is worth recording)
        normalized = renderer.normalize_content(content)
        record_history({
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "kind": normalized["kind"],
            "bot_id": bot_record.get("id", ""),
            "bot_name": bot_record.get("display_name", ""),
            "channel_id": channel_id,
            "channel_name": channel_name,
            "message_id": sent_ids[0] if sent_ids else "",
            "message_ids": sent_ids,
            "product_id": str(content.get("id") or ""),
            "product_name": (content.get("name") or content.get("title")
                             or "Untitled"),
            "product": content,          # snapshot (the content model)
            "content": content,          # same thing under its new name
            "theme_id": str(content.get("theme_id") or ""),
            "payload": (messages[0] if messages else {}),
            "files": files_used,
            "attachments": attachments_all,
            "status": "sent",
            "last_action": "",
        })

        if problem:
            results.append({"channel_id": channel_id, "ok": True,
                            "partial": True, "error": problem,
                            "message_id": sent_ids[0],
                            "message_ids": sent_ids})
        else:
            results.append({"channel_id": channel_id, "ok": True,
                            "message_id": sent_ids[0],
                            "message_ids": sent_ids,
                            "attachments": attachments_all})
    return results


def _clean_targets(raw):
    """
    Keep only well-formed channel targets from the page, and throw away
    duplicates (a direct API call used to be able to double-post).
    """
    targets = []
    seen = set()
    if isinstance(raw, list):
        for item in raw:
            entry = None
            if isinstance(item, dict) and str(item.get("id", "")).isdigit():
                entry = {"id": str(item["id"]), "name": str(item.get("name", ""))}
            elif isinstance(item, str) and item.isdigit():
                entry = {"id": item, "name": ""}
            if entry and entry["id"] not in seen:
                seen.add(entry["id"])
                targets.append(entry)
    return targets


def _bot_for_sending(data):
    """
    Work out which bot a send/edit/schedule should run as:
    the request's bot_id wins, then the content's bot_id, then the
    active bot. Returns (record, client, error_response).
    """
    bot_id = str((data or {}).get("bot_id", "")).strip()
    if not bot_id:
        content = (data or {}).get("content")
        if isinstance(content, dict):
            bot_id = str(content.get("bot_id", "")).strip()
    return _bot_or_error(bot_id or None)


def _render_request_content(data):
    """
    Shared body of /api/preview, /api/send and /api/send-test:
    check the content model, render it, verify the result.
    Returns (result, error_response). `result` is the renderer's dict.
    """
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, dict):
        return None, (jsonify({"ok": False,
                               "error": "The message content is missing."}), 400)
    if _has_broken_characters(content):
        return None, (jsonify({"ok": False,
                               "error": BROKEN_CHARACTERS_MESSAGE}), 400)

    bot_id = str(data.get("bot_id", "")).strip() or \
        str(content.get("bot_id", "")).strip()
    record = bots.resolve_bot(bot_id or None, base_dir=current_user_dir()) or {}

    result = render_for_bot(content, record)
    if not result["ok"]:
        return None, (jsonify({"ok": False,
                               "error": "Discord would reject this message:",
                               "errors": result["errors"]}), 400)

    problems = _validate_rendered(result)
    if problems:
        return None, (jsonify({"ok": False,
                               "error": "Discord would reject this message:",
                               "errors": problems}), 400)
    return result, None


@app.post("/api/preview")
def api_preview():
    """
    THE preview endpoint: the page sends the content model, the SERVER
    renders it (the exact same code that will send it), and the page shows
    the payloads it gets back. What you see is what you send - literally.

    No token is needed and nothing leaves this PC, so the preview works
    even when the bot is offline.
    """
    data = request.get_json(silent=True) or {}
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, dict):
        return jsonify({"ok": False, "error": "The message content is missing."}), 400
    if _has_broken_characters(content):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    bot_id = str(data.get("bot_id", "")).strip() or \
        str(content.get("bot_id", "")).strip()
    record = bots.resolve_bot(bot_id or None, base_dir=current_user_dir()) or {}

    result = render_for_bot(content, record)
    return jsonify({
        "ok": result["ok"],
        "bot": {"id": record.get("id", ""),
                "name": record.get("display_name", "SELLER BOT"),
                "avatar_url": record.get("avatar_url", "")},
        "messages": result["messages"],
        "usage": result["usage"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "report": result["report"],
    })


@app.post("/api/send")
def api_send():
    """
    Post a listing (product OR section) to one or more channels.
    The page sends:
      targets - [{"id": "...", "name": "store"}, ...]
      content - the content model (the product/section as built)
      bot_id  - which bot sends this (optional; default: the active bot)
    The server renders it with renderer.py - the same output the preview
    already showed - and posts every message of the auto-split, in order.
    """
    rate_err = check_send_rate_limit()
    if rate_err:
        return rate_err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Nothing was sent."}), 400

    targets = _clean_targets(data.get("targets"))
    if not targets:
        return jsonify({"ok": False,
                        "error": "Pick at least one channel first."}), 400

    result, error = _render_request_content(data)
    if error:
        return error

    record, client, error = _bot_for_sending(data)
    if error:
        return error

    results = send_to_channels(record, client, targets, data["content"],
                               result["messages"], "manual")

    any_ok = any(r["ok"] for r in results)
    return jsonify({"ok": any_ok, "results": results,
                    "error": None if any_ok else results[0]["error"]})


@app.post("/api/send-test")
def api_send_test():
    """
    Same as /api/send, but posts ONLY to TEST_CHANNEL_ID from the .env file,
    so you can check how the real message looks before the real send.
    """
    rate_err = check_send_rate_limit()
    if rate_err:
        return rate_err

    test_channel = os.getenv("TEST_CHANNEL_ID", "").strip()
    if not (test_channel.isdigit() and 15 <= len(test_channel) <= 21):
        return jsonify({"ok": False,
                        "error": "TEST_CHANNEL_ID is not set in the .env file. Add the ID "
                                 "of a private test channel there and restart the app."}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Nothing was sent."}), 400

    result, error = _render_request_content(data)
    if error:
        return error

    record, client, error = _bot_for_sending(data)
    if error:
        return error

    # Find out the channel's name so the history reads nicely.
    channel_name = ""
    try:
        info = client.get_channel(test_channel)
        channel_name = info.get("name", "")
    except discord_api.DiscordAPIError:
        pass

    results = send_to_channels(record, client,
                               [{"id": test_channel, "name": channel_name}],
                               data["content"], result["messages"], "test")

    any_ok = any(r["ok"] for r in results)
    return jsonify({"ok": any_ok, "results": results,
                    "error": None if any_ok else results[0]["error"]})


# ---------------------------------------------------------------------------
# History + actions on sent messages
# ---------------------------------------------------------------------------

@app.get("/api/history")
def api_history():
    """Everything the bots ever posted, newest first."""
    history = load_items("history.json")
    history.sort(key=lambda h: h.get("ts", ""), reverse=True)
    return jsonify({"ok": True, "history": history})


def _update_history_entry(history_id, updater):
    """Change one history entry (under the data lock). Returns it or None."""
    if not history_id:
        return None
    with DATA_LOCK:
        history = load_items("history.json")
        for entry in history:
            if entry.get("id") == history_id:
                updater(entry)
                save_items("history.json", history)
                return entry
    return None


def _find_history_entry(history_id):
    """Look up one history entry without changing it."""
    if not history_id:
        return None
    for entry in load_items("history.json"):
        if entry.get("id") == history_id:
            return entry
    return None


def _bot_for_message_action(data):
    """
    Which bot owns a message action? The request's bot_id wins, then the
    bot stored in the history entry (that is the bot that SENT it - only
    that bot is allowed to edit or delete its own messages), then the
    active bot.
    """
    bot_id = str((data or {}).get("bot_id", "")).strip()
    if not bot_id:
        entry = _find_history_entry(str((data or {}).get("history_id", "")))
        if entry:
            bot_id = str(entry.get("bot_id", "")).strip()
    return _bot_or_error(bot_id or None)


@app.post("/api/messages/update")
def api_message_update():
    """
    Edit messages a bot already sent (mark sold out, change price, edit
    the listing, ...). The page sends the NEW CONTENT MODEL - the server
    re-renders it (exactly like a fresh send) and patches the Discord
    messages to match.

    Because a listing can be several Discord messages (the auto-split),
    the edit works on ALL of them:
      * same count   -> each message is patched in place,
      * more now     -> the existing ones are patched, extras are posted,
      * fewer now    -> the surplus messages are deleted.

    Uploaded images survive the edit: for every message the server keeps
    the old attachments whose filenames the new payload still references
    (Discord matches attachment://filename), and uploads only the new ones.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Nothing was sent."}), 400

    channel_id = str(data.get("channel_id", ""))
    history_id = str(data.get("history_id", ""))
    action = str(data.get("action", "edited"))

    # find the history entry - it knows every message id of this listing
    entry = _find_history_entry(history_id)
    if entry is None:
        return jsonify({"ok": False,
                        "error": "That message is not in the history anymore."}), 400

    ids = entry.get("message_ids")
    if not isinstance(ids, list) or not ids:
        ids = [entry.get("message_id")]
    old_ids = [str(mid) for mid in ids if str(mid).isdigit()]
    if not (channel_id.isdigit() and old_ids):
        return jsonify({"ok": False, "error": "Channel or message id is missing."}), 400

    # the NEW content model - the entry's own snapshot when the page sends
    # none (used by one-click actions like "mark sold out")
    content = data.get("content") if isinstance(data.get("content"), dict) \
        else (entry.get("content") or entry.get("product"))
    if not isinstance(content, dict):
        return jsonify({"ok": False,
                        "error": "This entry has no saved content to rebuild from."}), 400
    if _has_broken_characters(content):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    record, client, error = _bot_for_message_action(data)
    if error:
        return error

    # render the new version as THIS bot (the one that owns the messages)
    result = render_for_bot(content, record)
    if not result["ok"]:
        return jsonify({"ok": False, "error": "Discord would reject this message:",
                        "errors": result["errors"]}), 400
    problems = _validate_rendered(result)
    if problems:
        return jsonify({"ok": False, "error": "Discord would reject this message:",
                        "errors": problems}), 400

    new_messages = result["messages"]
    settings = get_settings()
    mention_rules = build_allowed_mentions(settings.get("allow_everyone_mentions", False))

    # attachments grouped by the message they belong to
    def _attachments_of(message_index):
        group = []
        for attachment in entry.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            if int(attachment.get("message_index", 0) or 0) == message_index:
                group.append(attachment)
        return group

    def _refs_in(message):
        """The attachment:// filenames a rendered message references."""
        refs = set()

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("url", "icon_url") and isinstance(value, str) \
                            and value.startswith("attachment://"):
                        refs.add(value[len("attachment://"):])
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(message.get("embeds"))
        return refs

    final_ids = list(old_ids)
    final_attachments = []
    files_used = []
    try:
        for index in range(max(len(old_ids), len(new_messages))):
            old_id = old_ids[index] if index < len(old_ids) else None
            new_message = new_messages[index] if index < len(new_messages) else None

            if new_message is None:
                # fewer messages now -> the surplus is deleted
                client.delete_message(channel_id, old_id)
                final_ids = [mid for mid in final_ids if mid != old_id]
                continue

            outgoing = {"content": new_message.get("content") or "",
                        "embeds": new_message.get("embeds") or []}
            outgoing["allowed_mentions"] = mention_rules

            old_attachments = _attachments_of(index) if old_id else []
            refs = _refs_in(new_message)
            keep = [a["id"] for a in old_attachments if a.get("filename") in refs]
            outgoing["attachments"] = [{"id": attachment_id} for attachment_id in keep]

            files, missing = resolve_upload_files(new_message.get("files") or [])
            if missing:
                return jsonify({"ok": False,
                                "error": "These uploaded images could not be found "
                                         "anymore - upload them again: "
                                         + ", ".join(missing)}), 400
            files_used.extend(f[0] for f in files)

            if old_id is None:
                # more messages now -> post the extra one
                sent = client.send_message(channel_id, outgoing, files=files or None)
                final_ids.append(sent["id"])
                for attachment in sent.get("attachments") or []:
                    final_attachments.append({"id": attachment["id"],
                                              "filename": attachment["filename"],
                                              "message_index": index})
            else:
                sent = client.edit_message(channel_id, old_id, outgoing,
                                           files=files or None)
                for attachment in sent.get("attachments") or []:
                    final_attachments.append({"id": attachment["id"],
                                              "filename": attachment["filename"],
                                              "message_index": index})
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    updated_entry = _update_history_entry(history_id, lambda item: item.update({
        "message_id": final_ids[0] if final_ids else "",
        "message_ids": final_ids,
        "content": content,
        "product": content,
        "theme_id": str(content.get("theme_id") or ""),
        "payload": (new_messages[0] if new_messages else {}),
        "bot_id": record.get("id", ""),
        "bot_name": record.get("display_name", ""),
        "files": files_used,
        "attachments": final_attachments,
        "last_action": action,
        "status": "sent",
    }))

    return jsonify({"ok": True, "message_id": final_ids[0] if final_ids else "",
                    "message_ids": final_ids, "attachments": final_attachments,
                    "history": updated_entry})


@app.post("/api/messages/delete")
def api_message_delete():
    """
    Delete a listing a bot already sent - every Discord message of the
    auto-split, straight from Discord.
    """
    data = request.get_json(silent=True) or {}
    channel_id = str(data.get("channel_id", ""))
    history_id = str(data.get("history_id", ""))

    entry = _find_history_entry(history_id)
    if entry is None:
        return jsonify({"ok": False, "error": "Channel or message id is missing."}), 400

    channel_id = channel_id or str(entry.get("channel_id", ""))
    message_ids = [str(mid) for mid in (entry.get("message_ids") or
                                        [entry.get("message_id")])]
    message_ids = [mid for mid in message_ids if mid.isdigit()]
    if not (channel_id.isdigit() and message_ids):
        return jsonify({"ok": False, "error": "Channel or message id is missing."}), 400

    record, client, error = _bot_for_message_action(data)
    if error:
        return error

    try:
        for message_id in message_ids:
            client.delete_message(channel_id, message_id)
    except discord_api.DiscordAPIError as problem:
        return _bot_error_response(problem)

    _update_history_entry(history_id, lambda item: item.update({
        "status": "deleted", "last_action": "deleted",
    }))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Scheduled posts (data/schedules.json) + the background worker
# ---------------------------------------------------------------------------

@app.get("/api/schedules")
def api_schedules_list():
    """Your planned posts, soonest first."""
    schedules = load_items("schedules.json")
    schedules.sort(key=lambda s: (s.get("status") != "pending", s.get("run_at", "")))
    return jsonify({"ok": True, "schedules": schedules})


@app.post("/api/schedules")
def api_schedules_create():
    """
    Plan a post for a date + time. The app must be RUNNING at that moment -
    it is a local tool, not a 24/7 server (the page reminds you too).

    The CONTENT MODEL is stored (not a finished payload), so the worker
    renders it fresh when the time comes - with the theme, the pricing
    plans and the ticket line exactly as they are at that moment.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Nothing was sent."}), 400

    targets = _clean_targets(data.get("targets"))
    if not targets:
        return jsonify({"ok": False, "error": "Pick at least one channel first."}), 400

    run_at_raw = str(data.get("run_at", ""))
    try:
        run_at = datetime.fromisoformat(run_at_raw)
    except ValueError:
        return jsonify({"ok": False,
                        "error": "Pick a valid date and time (format YYYY-MM-DD HH:MM)."}), 400

    content = data.get("content")
    if not isinstance(content, dict):
        return jsonify({"ok": False, "error": "The message content is missing."}), 400
    if _has_broken_characters(content):
        return jsonify({"ok": False, "error": BROKEN_CHARACTERS_MESSAGE}), 400

    # make sure it renders cleanly BEFORE we promise to post it later
    result, error = _render_request_content(data)
    if error:
        return error

    record, client, error = _bot_for_sending(data)
    if error:
        return error

    schedule = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_at": run_at.isoformat(timespec="seconds"),
        "status": "pending",
        "kind": renderer.normalize_content(content)["kind"],
        "bot_id": record.get("id", ""),
        "bot_name": record.get("display_name", ""),
        "targets": targets,
        "content": content,
        "product_name": str(data.get("product_name") or content.get("name")
                             or content.get("title") or "Untitled"),
        "results": None,
    }

    with DATA_LOCK:
        schedules = load_items("schedules.json")
        schedules.append(schedule)
        save_items("schedules.json", schedules)

    return jsonify({"ok": True, "schedule": schedule})


@app.post("/api/schedules/cancel")
def api_schedules_cancel():
    """Cancel a planned post (nothing has been sent yet)."""
    schedule_id = str((request.get_json(silent=True) or {}).get("id", ""))
    with DATA_LOCK:
        schedules = load_items("schedules.json")
        for item in schedules:
            if item.get("id") == schedule_id and item.get("status") == "pending":
                item["status"] = "cancelled"
        save_items("schedules.json", schedules)
    return jsonify({"ok": True})


@app.post("/api/schedules/run-now")
def api_schedules_run_now():
    """Make a planned post fire on the next worker tick (about 5 seconds)."""
    schedule_id = str((request.get_json(silent=True) or {}).get("id", ""))
    with DATA_LOCK:
        schedules = load_items("schedules.json")
        for item in schedules:
            if item.get("id") == schedule_id and item.get("status") in ("pending", "missed"):
                item["status"] = "pending"
                item["run_at"] = datetime.now().isoformat(timespec="seconds")
        save_items("schedules.json", schedules)
    return jsonify({"ok": True})


def run_due_schedules():
    """
    The worker's heart: send every pending schedule whose time has come.
    (Also called once at startup in case something is due right now.)
    """
    now = datetime.now()

    due = []
    with DATA_LOCK:
        schedules = load_items("schedules.json")
        changed = False
        for item in schedules:
            if item.get("status") != "pending":
                continue
            try:
                if datetime.fromisoformat(str(item.get("run_at", ""))) <= now:
                    due.append(item)
            except ValueError:
                # a broken date is saved as an error right away (and this
                # time the change is actually SAVED - see the audit fix)
                item["status"] = "error"
                item["error"] = "The saved date was invalid."
                changed = True
        if changed:
            save_items("schedules.json", schedules)

    for item in due:
        # send outside the lock - network calls can take a moment

        # the schedule remembers which bot should post it
        bot_id = str(item.get("bot_id", ""))
        record = bots.resolve_bot(bot_id)

        results = []
        error_note = None
        if record is None or not bots.read_token(record):
            error_note = ("The bot for this schedule no longer exists or has no "
                          "token - edit the schedule or pick another bot.")
        else:
            try:
                client = bots.get_client(record["id"])
                # render fresh at fire time: theme, plans and the ticket
                # line are applied exactly as they are RIGHT NOW
                rendered = render_for_bot(item.get("content") or {}, record)
                if not rendered["ok"]:
                    error_note = "Discord would reject this message: " + \
                        ("; ".join(rendered["errors"])[:200])
                else:
                    results = send_to_channels(record, client,
                                               item.get("targets") or [],
                                               item.get("content") or {},
                                               rendered["messages"],
                                               "scheduled")
            except Exception as problem:             # never let the worker die
                print(f"  Schedule {item.get('id')} failed: {problem}")
                error_note = str(problem)[:200]

        if error_note:
            summary = [{"channel_id": "", "ok": False, "error": error_note}]
        else:
            summary = [{k: r.get(k) for k in ("channel_id", "ok", "error")}
                       for r in results]

        with DATA_LOCK:
            schedules = load_items("schedules.json")
            for saved in schedules:
                if saved.get("id") == item.get("id"):
                    saved["status"] = "done" if any(r["ok"] for r in results) else "failed"
                    saved["results"] = summary
            save_items("schedules.json", schedules)


def scheduler_loop():
    """Runs every 5 seconds in the background while the app is open."""
    while True:
        try:
            run_due_schedules()
        except Exception as problem:
            # a hiccup must never stop the worker - but it SHOULD be visible
            print(f"  (schedule worker hiccup: {problem})")
        time.sleep(5)


def start_scheduler():
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Friendly error pages
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def page_not_found(_error):
    return jsonify({"ok": False, "error": "That page does not exist."}), 404


@app.errorhandler(413)
def file_too_big(_error):
    return jsonify({"ok": False,
                    "error": "That file is too big. The maximum is 8 MB per image."}), 413


@app.errorhandler(500)
def server_error(_error):
    return jsonify({
        "ok": False,
        "error": ("Something went wrong inside SELLER BOT. Look at the app "
                  "window for details, then try again."),
    }), 500


@app.after_request
def add_safety_headers(response):
    """Tiny safety net: never let the browser guess a file type."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


# ---------------------------------------------------------------------------
# Start the app
# ---------------------------------------------------------------------------

def _local_ip_hint():
    """Best guess of this PC's address on your Wi-Fi (for ALLOW_LAN mode)."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))   # opens a connection but sends nothing
        ip_address = probe.getsockname()[0]
        probe.close()
        return ip_address
    except OSError:
        return "this-pc-ip"


if __name__ == "__main__":
    # ALLOW_LAN=true in .env opens the app to other devices on your Wi-Fi.
    # Default (false) keeps it private to this PC - the safe choice.
    allow_lan = os.getenv("ALLOW_LAN", "").strip().lower() in ("1", "true", "yes", "on")
    port = int(os.getenv("PORT", "5000"))
    host = "0.0.0.0" if allow_lan else "127.0.0.1"

    print()
    print("  ==================================================")
    print("   INDRA BOT SYSTEM  -  multi-bot Discord publisher")
    print("  ==================================================")
    print()
    print(bots.startup_report())
    print()
    print("   Open this address in your browser:")
    print(f"       http://localhost:{port}")
    print()
    if allow_lan:
        print("   ALLOW_LAN is ON - other devices on your Wi-Fi can open")
        print("   the app too, for example from your phone:")
        print(f"       http://{_local_ip_hint()}:{port}")
        print("   (Turn this OFF in .env when you do not need it.)")
    else:
        print("   Only this PC can open the app (the safe default).")
        print("   To use it from your phone on the same Wi-Fi, set")
        print("   ALLOW_LAN=true in the .env file and restart.")
    print()
    print("   Bots show as OFFLINE in Discord - that is normal for a")
    print("   REST-only tool. They 'appear' only for the moment a")
    print("   message is posted. Tickets are handled by your other bot.")
    print()
    print("   Keep this window open while using SELLER BOT.")
    print("   Scheduled posts only fire while the app is running.")
    print("   Stop the app with CTRL+C (or close this window).")
    print()

    start_scheduler()   # the background worker for scheduled posts
    # debug=False keeps things simple and predictable (no auto-reloader).
    app.run(host=host, port=port, debug=False)
