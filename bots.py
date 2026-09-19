"""
bots.py - the multi-bot registry: which bots exist, and where their tokens live.

THE ONE RULE THIS MODULE ENFORCES:
    data/bots.json knows everything ABOUT a bot (its name, kind, which .env
    variable holds its token, its cached avatar...) but NEVER a secret.
    The tokens themselves live ONLY in the .env file on your PC and are
    never sent to the browser, never printed, never logged.

What is a "bot record"? This is what one entry in bots.json looks like:

    {
      "id": "seller",                  <- stable short id used everywhere
      "display_name": "SELLER BOT",    <- shown in the dashboard
      "kind": "seller",                <- "seller" | "messenger" | "custom"
      "token_env_var": "DISCORD_TOKEN",<- WHICH .env key has the token
      "application_id": "123...",      <- for building invite links
      "avatar_url": "https://...",     <- cached picture (works offline-ish)
      "enabled": true,                 <- disabled bots are skipped everywhere
      "allow_everyone": false,         <- invite link may ask for ping perms
      "notes": "",                     <- your own note-to-self
      "created_at": "2026-..."
    }

Backward compatibility: the very first version of the app had a single
DISCORD_TOKEN in .env. On first start, ensure_registry() turns that into
bot #1 (id "seller", name "SELLER BOT") pointing at the same DISCORD_TOKEN
line - so nothing breaks and no token is copied anywhere. Once bots.json
exists, this never happens again (that way "Remove" really means removed).

A quick tour of this file:
  * registry load/save (through storage.py's safe writer)
  * ensure_registry()      - one-time migration from the old single token
  * list_bots()            - everything the dashboard may see (tokens masked)
  * add_bot()              - validate token -> write .env -> save record
  * update_bot() / set_enabled() / remove_bot()
  * test_bot()             - live "does it still connect?" check
  * invite_url_for()       - the ready-made invite link
  * get_client()           - the BotClient object for a bot (cached)
  * write_env_var()/remove_env_var() - the careful .env editor
"""

import os
import re
import threading
from datetime import datetime

import discord_api
from storage import ensure_data_dir, load_json, path_for, save_json

REGISTRY_FILE = "bots.json"          # data/bots.json
KINDS = ("seller", "messenger", "custom", "webhook")

_REGISTRY_LOCK = threading.Lock()    # one registry change at a time
_CLIENT_CACHE = {}                   # (bot_id, token) -> BotClient

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


# ---------------------------------------------------------------------------
# Registry load / save
# ---------------------------------------------------------------------------

def _empty_registry():
    return {"schema_version": 1, "bots": []}


def load_registry(base_dir=None):
    """Read bots.json (or an empty registry on first run)."""
    data = load_json(REGISTRY_FILE, None, base_dir=base_dir)
    if isinstance(data, dict) and isinstance(data.get("bots"), list):
        return data
    if isinstance(data, list):          # future-proof: a bare list of bots
        return {"schema_version": 1, "bots": data}
    return _empty_registry()


def save_registry(registry, base_dir=None):
    """Save bots.json the safe way (atomic write, file lock)."""
    save_json(REGISTRY_FILE, registry, base_dir=base_dir)


def _records(registry=None, base_dir=None):
    """The bot records as a list (from the given or freshly loaded registry)."""
    registry = registry if registry is not None else load_registry(base_dir=base_dir)
    return registry.get("bots", [])


# ---------------------------------------------------------------------------
# First-run migration: DISCORD_TOKEN becomes bot #1
# ---------------------------------------------------------------------------

def ensure_registry(base_dir=None):
    """
    Make sure bots.json exists and holds the legacy "seller" bot.

    Rules:
      * If bots.json does not exist yet AND the old DISCORD_TOKEN is set (and base_dir is None),
        we create the registry with bot "seller" (display name SELLER BOT,
        kind seller, token_env_var DISCORD_TOKEN - the SAME .env line, so
        nothing changes for existing installs).
      * If bots.json does not exist and there is no token, we create an
        empty registry - the user adds bots from the dashboard.
      * If bots.json already exists we never touch it here. That is on
        purpose: removing a bot must stick, so we do not keep re-adding
        the old DISCORD_TOKEN bot behind your back.

    Returns True when a registry file was created.
    """
    with _REGISTRY_LOCK:
        if os.path.exists(path_for(REGISTRY_FILE, base_dir=base_dir)):
            return False

        registry = _empty_registry()

        if base_dir is None:
            legacy_token = os.getenv("DISCORD_TOKEN", "").strip()
            if legacy_token:
                registry["bots"].append({
                    "id": "seller",
                    "display_name": "INDRA BOT SYSTEM",
                    "kind": "seller",
                    "token_env_var": "DISCORD_TOKEN",
                    "application_id": "",
                    "avatar_url": "",
                    "enabled": True,
                    "allow_everyone": False,
                    "notes": "Imported from the old single-token setup.",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })

        save_registry(registry, base_dir=base_dir)
        return True


# ---------------------------------------------------------------------------
# Public views (this is ALL the browser ever gets to see)
# ---------------------------------------------------------------------------

def mask_token(token):
    """'abc123XYZ' -> '••••XYZ' (only the last 4 characters ever shown)."""
    token = (token or "").strip()
    if not token:
        return ""
    return "••••" + token[-4:]


def _read_user_tokens(base_dir):
    data = load_json("tokens.json", {}, base_dir=base_dir)
    return data if isinstance(data, dict) else {}


def _write_user_tokens(base_dir, tokens):
    save_json("tokens.json", tokens if isinstance(tokens, dict) else {}, base_dir=base_dir)


def read_token(record, base_dir=None):
    """The bot's token, read fresh from the environment or user tokens (never stored in bots.json)."""
    if not record:
        return ""
    if base_dir:
        tokens = _read_user_tokens(base_dir)
        return str(tokens.get(record.get("id"), "")).strip()
    return os.getenv(record.get("token_env_var", ""), "").strip()


def _public(record, base_dir=None):
    """
    A bot record with the token replaced by a masked hint. The raw token
    is read from .env or tokens.json only at the moment a Discord call is made.
    """
    out = dict(record)
    token = read_token(record, base_dir=base_dir)
    out["token_hint"] = mask_token(token)
    out["token_present"] = bool(token)
    return out


def list_bots(base_dir=None):
    """All bots as the dashboard may see them (no secrets)."""
    return [_public(record, base_dir=base_dir) for record in _records(base_dir=base_dir)]


def get_bot_record(bot_id, base_dir=None):
    """One record (the private version - use _public() before sending out)."""
    for record in _records(base_dir=base_dir):
        if record.get("id") == bot_id:
            return record
    return None


def count_enabled(base_dir=None):
    """How many bots are switched on right now."""
    return sum(1 for record in _records(base_dir=base_dir) if record.get("enabled", True))


# ---------------------------------------------------------------------------
# The careful .env editor
# ---------------------------------------------------------------------------

def write_env_var(key, value):
    """
    Set KEY=value in the .env file - WITHOUT touching any other line.

    How it stays safe:
      * every other line (including your comments) is copied as-is,
      * if KEY already exists, only that one line is replaced,
      * otherwise the new line is added at the end,
      * the file is written atomically (temp file + swap) so a crash can
        never leave it half-written,
      * the running app's own environment is updated too, so the new bot
        works immediately without a restart.
    """
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()

    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    replaced = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")

    tmp_path = ENV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, ENV_PATH)

    os.environ[key] = value          # update the running app immediately


def remove_env_var(key):
    """Delete the KEY=... line from .env (other lines untouched)."""
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    kept = [line for line in lines if not pattern.match(line)]

    if len(kept) == len(lines):
        return                        # nothing to remove

    tmp_path = ENV_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(kept) + ("\n" if kept else ""))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, ENV_PATH)

    os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# Clients (the BotClient object that actually talks to Discord)
# ---------------------------------------------------------------------------

def get_client(bot_id, base_dir=None):
    """
    The BotClient for one bot, created fresh if its token changed.
    Raises KeyError when the bot id is unknown.
    """
    record = get_bot_record(bot_id, base_dir=base_dir)
    if record is None:
        raise KeyError(f"unknown bot: {bot_id}")

    token = read_token(record, base_dir=base_dir)
    cache_key = (base_dir or "global", bot_id, token)
    with _REGISTRY_LOCK:
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            client = discord_api.BotClient(bot_id, token,
                                           record.get("display_name", bot_id))
            _CLIENT_CACHE[cache_key] = client
        return client


# ---------------------------------------------------------------------------
# Actions the dashboard buttons trigger
# ---------------------------------------------------------------------------

def _unique_id(display_name, taken):
    clean = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-") or "bot"
    candidate, counter = clean, 2
    while candidate in taken:
        candidate = f"{clean}-{counter}"
        counter += 1
    return candidate


def env_var_for(bot_id):
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", bot_id).upper()
    return f"DISCORD_TOKEN_{clean}"


def add_bot(display_name, kind, token, allow_everyone=False, notes="", base_dir=None):
    """
    Add a new bot (the "Add bot" wizard).

    Step by step:
      1. the pasted token is checked against Discord (GET /users/@me) -
         if it does not work, NOTHING is saved and the friendly error
         travels back to the page,
      2. a short unique id and a .env key name are chosen,
      3. the token is written into .env (admin) or tokens.json (user),
      4. the bot record (name, kind, application id, avatar) is saved.

    Returns the new PUBLIC record (no token in it).
    Raises discord_api.DiscordAPIError when the token check fails.
    """
    display_name = str(display_name or "").strip()[:60] or "New bot"
    token = str(token or "").strip().strip('"').strip("'")
    if token.lower().startswith("bot "):
        token = token[4:].strip()

    # Auto-detect webhook URL if user pasted a webhook
    if token.startswith("https://discord.com/api/webhooks/") or token.startswith("https://discordapp.com/api/webhooks/"):
        kind = "webhook"

    if kind not in KINDS:
        kind = "custom"
    if not token:
        raise discord_api.DiscordAPIError(
            0, "empty token",
            "Paste the bot token first (Discord Developer Portal > your app "
            "> Bot > Reset Token).", "no_token", display_name)

    # 1. validate BEFORE saving anything
    if kind == "webhook":
        if not token.startswith("https://discord.com/api/webhooks/"):
            raise discord_api.DiscordAPIError(
                0, "invalid_webhook",
                "Please paste a valid Discord Webhook URL (starts with https://discord.com/api/webhooks/...).",
                "invalid_webhook", display_name)
        me = {"id": "webhook", "username": display_name, "avatar": None}
    else:
        me = discord_api.validate_token(token, display_name)

    with _REGISTRY_LOCK:
        registry = load_registry(base_dir=base_dir)
        existing = {record.get("id") for record in registry.get("bots", [])}

        bot_id = _unique_id(display_name, existing)
        env_key = env_var_for(bot_id)

        # 2. token goes to tokens.json (if base_dir) or .env (if root admin)
        if base_dir:
            tokens = _read_user_tokens(base_dir)
            tokens[bot_id] = token
            _write_user_tokens(base_dir, tokens)
            env_key = f"USER_BOT_{bot_id}"
        else:
            write_env_var(env_key, token)

        # 3. the record itself
        record = {
            "id": bot_id,
            "display_name": display_name,
            "kind": kind,
            "token_env_var": env_key,
            "application_id": me.get("id", ""),
            "avatar_url": discord_api.avatar_url(me),
            "enabled": True,
            "allow_everyone": bool(allow_everyone),
            "notes": str(notes or "")[:200],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        registry["bots"].append(record)
        save_registry(registry, base_dir=base_dir)

    return _public(record, base_dir=base_dir)


def update_bot(bot_id, base_dir=None, **changes):
    """
    Change editable fields of a bot (display_name, kind, notes,
    allow_everyone, enabled, application_id, avatar_url).
    Only known fields are accepted; unknown ones are ignored.
    """
    allowed = {"display_name", "kind", "notes", "allow_everyone",
               "enabled", "application_id", "avatar_url"}
    with _REGISTRY_LOCK:
        registry = load_registry(base_dir=base_dir)
        for record in registry.get("bots", []):
            if record.get("id") == bot_id:
                for key, value in changes.items():
                    if key in allowed:
                        record[key] = value
                save_registry(registry, base_dir=base_dir)
                return _public(record, base_dir=base_dir)
    return None


def set_enabled(bot_id, enabled, base_dir=None):
    """Switch a bot on or off. Returns the updated public record (or None)."""
    return update_bot(bot_id, base_dir=base_dir, enabled=bool(enabled))


def remove_bot(bot_id, base_dir=None):
    """
    Remove a bot from the registry.

    * its token line is deleted from .env (or tokens.json for users)
    * the bot's BotClient cache entry is dropped.
    """
    with _REGISTRY_LOCK:
        registry = load_registry(base_dir=base_dir)
        kept = []
        removed = None
        for record in registry.get("bots", []):
            if record.get("id") == bot_id:
                removed = record
            else:
                kept.append(record)
        if removed is None:
            return False

        registry["bots"] = kept
        save_registry(registry, base_dir=base_dir)

        if base_dir:
            tokens = _read_user_tokens(base_dir)
            tokens.pop(bot_id, None)
            _write_user_tokens(base_dir, tokens)
        else:
            env_key = removed.get("token_env_var", "")
            if env_key and env_key != "DISCORD_TOKEN":
                remove_env_var(env_key)

        cache_key = (base_dir or "global", bot_id, read_token(removed, base_dir=base_dir))
        _CLIENT_CACHE.pop(cache_key, None)
        return True


def test_bot(bot_id, base_dir=None):
    """
    Live connection check: ask Discord who this bot is right now.
    Returns the public record refreshed with the live identity.
    Raises discord_api.DiscordAPIError when the check fails.
    """
    record = get_bot_record(bot_id, base_dir=base_dir)
    if record is None:
        raise KeyError(bot_id)

    token = read_token(record, base_dir=base_dir)
    if not token:
        raise discord_api.DiscordAPIError(
            0, "no token",
            f"{record.get('display_name', bot_id)} has no token configured. "
            "Please paste the bot token in your Bot settings.",
            "no_token", record.get("display_name", bot_id))

    client = get_client(bot_id, base_dir=base_dir)
    me = client.get_me(force=True)          # skip the cache - a real check

    # refresh the cached identity (application id never changes, avatar may)
    return update_bot(
        bot_id,
        base_dir=base_dir,
        application_id=me.get("id", record.get("application_id", "")),
        avatar_url=discord_api.avatar_url(me),
    )


def invite_url_for(bot_id, allow_everyone=False, base_dir=None):
    """
    The ready-made invite link for a bot (scope=bot + exactly the
    permissions the app needs). allow_everyone=True adds the
    "Mention Everyone" permission to the invite.
    """
    record = get_bot_record(bot_id, base_dir=base_dir)
    if record is None:
        raise KeyError(bot_id)

    application_id = record.get("application_id") or ""
    if not application_id:
        # not known yet (never tested) - do a live lookup so the link works
        me = get_client(bot_id, base_dir=base_dir).get_me(force=True)
        application_id = me.get("id", "")
        update_bot(bot_id, base_dir=base_dir, application_id=application_id,
                   avatar_url=discord_api.avatar_url(me))

    wants_everyone = allow_everyone or record.get("allow_everyone", False)
    return discord_api.build_invite_url(application_id, wants_everyone)


def default_bot_id(base_dir=None):
    """The first enabled bot (the one the dashboard opens with), or ''."""
    for record in _records(base_dir=base_dir):
        if record.get("enabled", True):
            return record.get("id", "")
    return ""


def resolve_bot(bot_id, strict=False, base_dir=None):
    """
    The bot an action should run as.

    strict=False (the default): a helpful fallback - when bot_id is empty
    or points to a bot that cannot be used, the first enabled bot is
    returned instead (used when the caller had no strong opinion).

    strict=True: EXACTLY the requested bot or None. Used when the user
    explicitly picked a bot - a typo or a disabled bot must be a clear
    error, never a silent switch to a different bot posting the message.
    """
    if bot_id:
        record = get_bot_record(bot_id, base_dir=base_dir)
        if record and record.get("enabled", True):
            return record        # exists and enabled - good in both modes
        if strict:
            return None          # explicit request for an unknown/disabled bot
    return get_bot_record(default_bot_id(base_dir=base_dir), base_dir=base_dir)


# ---------------------------------------------------------------------------
# Startup housekeeping
# ---------------------------------------------------------------------------

def startup_report():
    """
    A few lines for the console: how many bots, which ones, and a hint
    when the legacy DISCORD_TOKEN is set but not used by any bot.
    """
    records = _records()
    lines = [f"   Bots registered: {len(records)}"]
    for record in records:
        state = "on" if record.get("enabled", True) else "off"
        lines.append(f"     - {record.get('display_name', '?')} "
                     f"[{record.get('kind', '?')}] ({state}) "
                     f"token key: {record.get('token_env_var', '?')}")
    if not records:
        lines.append("     (none yet - add one from the dashboard's Bots page)")
    return "\n".join(lines)
