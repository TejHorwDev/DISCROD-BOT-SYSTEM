"""
discord_api.py - the ONLY file that talks to Discord, now multi-bot.

SELLER BOT does not run an always-online bot. Instead it uses Discord's
normal REST API - the same web addresses your browser uses when you open
discord.com. That means:

  * nothing happens until YOU click a button in the app,
  * every bot shows as "offline" in your server's member list (that is
    normal and expected - REST-only bots only "exist" for the moment a
    request is being made),
  * bot tokens are read from the .env file on YOUR PC and are NEVER sent
    to the browser or written into any log.

WHAT IS A BotClient?
  The app can now drive SEVERAL bots at once (a Seller bot, a Messenger
  bot, ...). Every bot gets its own BotClient object, which keeps:

    * the bot's token (from .env, never anywhere else),
    * a lock, so this bot only makes ONE request at a time - that is the
      politest way to use the API and keeps rate limits per bot,
    * rate-limit bookkeeping: it reads Discord's X-RateLimit-* response
      headers and, when Discord says "slow down" (a 429), it sleeps for
      exactly the time Discord asks and then retries,
    * small temporary caches (servers, channels, roles, emojis) so the
      pickers feel instant; each cache entry expires after a short time
      and every screen has a Refresh button that clears them.

A quick tour of this file:
  * DiscordAPIError   - an error translated into plain English
  * permissions + invite-link helpers
  * picture/emoji web-address helpers (Discord's "CDN")
  * TTLCache          - a tiny "remember for N seconds" box
  * BotClient         - one bot = one client (see above)
  * validate_token()  - check a pasted token before saving a new bot
"""

import json
import os
import threading
import time

import requests                     # the standard Python "web requests" library
from dotenv import load_dotenv      # reads the .env file

# Read the .env file that sits NEXT TO this file. Doing it this way means the
# app still finds your tokens even if you start it from a different folder.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Discord's REST API always starts with this address.
API_BASE = "https://discord.com/api/v10"

# Discord asks bot authors to send a readable "User-Agent" so they can see
# which application a request came from.
USER_AGENT = "SELLER-BOT-Studio/2.0 (local publishing tool, REST only)"

# ---------------------------------------------------------------------------
# Permissions. Discord stores permissions as numbers, and a server "invite"
# is just a list of ticked boxes. The app needs these:
#   View Channel         = 1024    (see the channel at all)
#   Send Messages        = 2048    (write messages into it)
#   Embed Links          = 16384   (post the nice colored "embed" cards)
#   Attach Files         = 32768   (upload pictures from your PC)
#   Read Message History = 65536   (find messages it sent earlier)
#   Mention Everyone     = 131072  (only when you explicitly allow pings)
# ---------------------------------------------------------------------------
P_VIEW_CHANNEL = 1024
P_SEND_MESSAGES = 2048
P_EMBED_LINKS = 16384
P_ATTACH_FILES = 32768
P_READ_MESSAGE_HISTORY = 65536
P_MENTION_EVERYONE = 131072
P_ADMINISTRATOR = 8    # admins implicitly have every permission

# What a bot needs for the app's core features (used for the "missing
# permissions" warning next to servers).
REQUIRED_PERMISSIONS = P_VIEW_CHANNEL | P_SEND_MESSAGES | P_EMBED_LINKS | P_ATTACH_FILES

# What the automatically generated invite link asks for.
INVITE_PERMISSIONS = REQUIRED_PERMISSIONS | P_READ_MESSAGE_HISTORY                    # 117760
INVITE_PERMISSIONS_WITH_EVERYONE = INVITE_PERMISSIONS | P_MENTION_EVERYONE            # 248832


class DiscordAPIError(Exception):
    """
    An error from Discord (or from reaching Discord) in plain English.

      .status   - the HTTP status number (0 = we could not reach Discord at all)
      .message  - the raw message from Discord, kept for debugging
      .friendly - the beginner-friendly text shown inside the app
      .kind     - a short tag like "unauthorized" or "forbidden"
      .bot      - the display name of the bot that hit the problem, so the
                  message can say WHICH bot needs fixing ("" = unknown)
    """

    def __init__(self, status, message, friendly, kind="error", bot=""):
        super().__init__(friendly)
        self.status = status
        self.message = message
        self.friendly = friendly
        self.kind = kind
        self.bot = bot


def _friendly(status, raw, bot_name="the bot", token=""):
    """Translate a Discord error number into something you can act on."""
    if status == 401:
        clean_tok = str(token or "").strip()
        if clean_tok and "." not in clean_tok:
            return (f"The token entered for {bot_name} is missing dots (it does not look like a Discord Bot Token). "
                    "You might have copied the Client Secret or Public Key from General Information! "
                    "To get your Bot Token: Go to Discord Developer Portal > your App > click 'Bot' on the left menu > click 'Reset Token' and copy the token.")
        return (f"Discord rejected the token for {bot_name} (401 Unauthorized). "
                "Make sure you copied the token from Discord Developer Portal (https://discord.com/developers/applications) "
                "> your App > click 'Bot' on the left menu > click 'Reset Token' > copy and paste that newly generated token.")
    if status == 403:
        return (f"{bot_name} is missing permissions in that place. It needs: "
                "View Channel, Send Messages, Embed Links, Attach Files "
                "(and Read Message History to edit what it sent). Open the "
                "invite link from the Bots page again, pick your server, and "
                "keep all the permission boxes ticked - inviting again is "
                "safe and will NOT remove the bot or duplicate it, it only "
                "updates its permissions.")
    if status == 404:
        return ("Discord could not find that server, channel or message. "
                "Double-check the ID. Tip: in Discord, right-click > Copy ID "
                "(needs Developer Mode, see the README). It is also possible "
                "the message was deleted by someone.")
    if status == 400:
        return f"Discord refused the request as invalid: {raw}"
    if status == 429:
        return ("Discord is limiting how fast we may send. The app already "
                "waits and retries automatically - please wait a few seconds "
                "and try again.")
    if status >= 500:
        return (f"Discord is having a problem on their side (error {status}). "
                "This usually fixes itself - try again in a moment.")
    return f"Unexpected answer from Discord (error {status}): {raw}"


def _kind(status):
    """A short machine-readable tag for each error type."""
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        429: "rate_limited",
    }.get(status, "server_busy" if status >= 500 else "error")


# ---------------------------------------------------------------------------
# Invite links + picture addresses (Discord keeps images on its "CDN",
# a network of servers that only stores pictures)
# ---------------------------------------------------------------------------

def build_invite_url(application_id, allow_everyone=False):
    """
    The invite link that adds a bot to a server with exactly the
    permissions the app needs. application_id is the bot's user id
    (for bots they are the same number - we get it from /users/@me).
    """
    permissions = (INVITE_PERMISSIONS_WITH_EVERYONE if allow_everyone
                   else INVITE_PERMISSIONS)
    return (f"https://discord.com/oauth2/authorize"
            f"?client_id={application_id}&scope=bot&permissions={permissions}")


def avatar_url(user, size=64):
    """Web address of a user's profile picture (bot avatar in the header)."""
    if user.get("avatar"):
        return (f"https://cdn.discordapp.com/avatars/{user['id']}/"
                f"{user['avatar']}.png?size={size}")
    # No custom avatar -> Discord's default blue picture
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def guild_icon_url(guild, size=32):
    """Web address of a server's little icon (None when the server has none)."""
    if guild.get("icon"):
        return (f"https://cdn.discordapp.com/icons/{guild['id']}/"
                f"{guild['icon']}.png?size={size}")
    return None


def guild_banner_url(guild, size=512):
    """Web address of a server's banner (None when the server has none)."""
    if guild.get("banner"):
        return (f"https://cdn.discordapp.com/banners/{guild['id']}/"
                f"{guild['banner']}.png?size={size}")
    return None


def emoji_url(emoji, size=44):
    """
    Web address of a custom server emoji. Animated emojis are GIFs,
    normal ones are PNGs.
    """
    extension = "gif" if emoji.get("animated") else "png"
    return (f"https://cdn.discordapp.com/emojis/{emoji['id']}."
            f"{extension}?size={size}")


# ---------------------------------------------------------------------------
# TTLCache - "remember this answer for N seconds"
# ---------------------------------------------------------------------------

class TTLCache:
    """
    A tiny cache: you put a value in under a key, and for the next
    `ttl` seconds the same key hands the value back instantly instead of
    asking Discord again. After that the entry expires by itself.
    """

    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self._box = {}                 # key -> (expires_at, value)
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._box.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if time.time() >= expires_at:
                self._box.pop(key, None)
                return None
            return value

    def set(self, key, value):
        with self._lock:
            self._box[key] = (time.time() + self.ttl, value)

    def clear(self):
        with self._lock:
            self._box.clear()


# ---------------------------------------------------------------------------
# BotClient - one instance per bot
# ---------------------------------------------------------------------------

class BotClient:
    """
    One Discord bot = one BotClient.

    How it behaves:
      * every request goes through api_request(), which:
          - takes this bot's lock (one request in flight at a time),
          - reads Discord's X-RateLimit-* headers on every answer,
          - when Discord answers 429 ("slow down"), sleeps exactly the
            asked time (retry_after) and tries again - up to 3 times,
          - retries a 5xx "Discord hiccup" once after a second,
          - turns every other error into a DiscordAPIError with a
            beginner-friendly message that names THIS bot.
      * the read calls (who am I, servers, channels, roles, emojis) keep
        short-lived caches, so opening a picker twice in a minute does
        not ask Discord twice. Pass force=True (or call clear_caches())
        to refresh.
    """

    def __init__(self, bot_id, token, display_name=""):
        self.bot_id = bot_id
        token = (token or "").strip().strip('"').strip("'")
        if token.lower().startswith("bot "):
            token = token[4:].strip()
        self.token = token
        self.display_name = display_name or bot_id
        self._lock = threading.RLock()          # one request at a time
        self._bucket_reset = {}                 # rate-limit bucket -> reset time

        # Small caches with different lifetimes (seconds).
        self._me_cache = TTLCache(600)          # 10 minutes
        self._guilds_cache = TTLCache(10)       # 10 seconds for real-time member sync
        self._channels_cache = TTLCache(30)
        self._roles_cache = TTLCache(60)
        self._emojis_cache = TTLCache(180)
        self._guild_cache = TTLCache(10)        # 10 seconds for real-time stats sync

    # ------------------------------------------------------------------
    # The one guarded request everything goes through
    # ------------------------------------------------------------------

    def _headers(self):
        return {
            "Authorization": "Bot " + self.token,
            "User-Agent": USER_AGENT,
        }

    def _note_rate_headers(self, response):
        """Remember when the rate-limit window of this route resets."""
        try:
            bucket = response.headers.get("X-RateLimit-Bucket")
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_after = response.headers.get("X-RateLimit-Reset-After")
            if bucket and remaining == "0" and reset_after:
                self._bucket_reset[bucket] = time.time() + float(reset_after)
        except (TypeError, ValueError):
            pass    # weird header values must never break a request

    def _wait_if_bucket_tired(self, endpoint):
        """
        If we recently learned that this exact route ran out of requests
        and the reset time is close (2 seconds or less), wait it out
        quietly instead of hitting a guaranteed 429. Longer waits are
        skipped - the 429 handler deals with them properly.
        """
        bucket = self._bucket_reset.get(endpoint)
        if not bucket:
            return
        wait = bucket - time.time()
        if 0 < wait <= 2.0:
            time.sleep(wait + 0.05)
        if wait <= 0:
            self._bucket_reset.pop(endpoint, None)

    def api_request(self, method, endpoint, json_body=None, data=None,
                    files=None, params=None):
        """
        Make ONE call to Discord's REST API (with all the patience built
        in) and return the decoded JSON answer.
        """
        url = endpoint if endpoint.startswith("http") else API_BASE + endpoint

        for attempt in range(1, 4):            # at most 3 tries
            # One request at a time per bot - the polite way.
            with self._lock:
                self._wait_if_bucket_tired(endpoint)
                try:
                    response = requests.request(
                        method,                 # "GET", "POST", "PATCH", "DELETE"
                        url,
                        headers=self._headers(),
                        json=json_body,         # normal JSON requests
                        data=data,              # form fields (with uploads)
                        files=files,            # picture uploads
                        params=params,          # extra ?query=parameters
                        timeout=20,             # never hang forever
                    )
                except requests.exceptions.RequestException as problem:
                    raise DiscordAPIError(
                        0,
                        str(problem),
                        "Could not reach Discord. Check your internet "
                        "connection, then try again.",
                        "network",
                        self.display_name,
                    )

            # ---- Discord answered and everything is fine -------------------
            if response.status_code < 400:
                self._note_rate_headers(response)
                if response.status_code == 204 or not response.text:
                    return None                 # success with no body
                try:
                    return response.json()
                except ValueError:
                    return None

            # ---- 429 "slow down!" -> wait exactly as asked, then retry -----
            if response.status_code == 429:
                self._note_rate_headers(response)
                wait_seconds = 1.0
                try:
                    body = response.json()
                    wait_seconds = float(body.get("retry_after", 1.0))
                except (ValueError, TypeError):
                    header_wait = response.headers.get("Retry-After")
                    if header_wait:
                        try:
                            wait_seconds = float(header_wait)
                        except ValueError:
                            pass
                # never sleep longer than 10 seconds per try
                time.sleep(min(wait_seconds, 10.0) + 0.3)
                continue                        # try again (attempt counter)

            # ---- 5xx "Discord hiccup" -> wait a moment, retry once ---------
            if 500 <= response.status_code < 600 and attempt == 1:
                time.sleep(1.0)
                continue

            # ---- a real error -> raise it with a friendly message ----------
            raw = ""
            try:
                body = response.json()
                raw = str(body.get("message", "") or "")
                if body.get("errors"):
                    # Discord adds machine details, e.g. WHICH embed field was
                    # too long. Keep a short piece so the message stays readable.
                    raw += " " + json.dumps(body["errors"])[:300]
            except ValueError:
                raw = response.text[:300]

            raise DiscordAPIError(
                response.status_code,
                raw,
                _friendly(response.status_code, raw, self.display_name, token=self.token),
                _kind(response.status_code),
                self.display_name,
            )

        # Three 429s in a row - give up with a clear message.
        raise DiscordAPIError(
            429, "still rate limited after 3 tries",
            "Discord kept asking us to slow down. Please wait a minute and "
            "try again.", "rate_limited", self.display_name)

    # ------------------------------------------------------------------
    # Read calls (all cached, all refreshable)
    # ------------------------------------------------------------------

    def get_me(self, force=False):
        """Who is this bot? Returns its id, name and avatar."""
        if not force:
            cached = self._me_cache.get("me")
            if cached:
                return cached
        me = self.api_request("GET", "/users/@me")
        self._me_cache.set("me", me)
        return me

    def get_my_guilds(self, force=False):
        """Which servers ("guilds" in Discord language) is the bot in?"""
        if not force:
            cached = self._guilds_cache.get("guilds")
            if cached:
                return cached
        guilds = self.api_request("GET", "/users/@me/guilds", params={"with_counts": "true"})
        self._guilds_cache.set("guilds", guilds)
        return guilds

    def get_guild(self, guild_id, force=False):
        """Details about one server (with member counts and boost level)."""
        if not force:
            cached = self._guild_cache.get(guild_id)
            if cached:
                return cached
        guild = self.api_request("GET", f"/guilds/{guild_id}", params={"with_counts": "true"})
        self._guild_cache.set(guild_id, guild)
        return guild

    def get_guild_channels(self, guild_id, force=False):
        """All channels of one server in one flat list (categories included)."""
        if not force:
            cached = self._channels_cache.get(guild_id)
            if cached:
                return cached
        channels = self.api_request("GET", f"/guilds/{guild_id}/channels")
        self._channels_cache.set(guild_id, channels)
        return channels

    def get_guild_roles(self, guild_id, force=False):
        """The roles of one server (for @role pings and the preview)."""
        if not force:
            cached = self._roles_cache.get(guild_id)
            if cached:
                return cached
        roles = self.api_request("GET", f"/guilds/{guild_id}/roles")
        self._roles_cache.set(guild_id, roles)
        return roles

    def get_guild_emojis(self, guild_id, force=False):
        """The custom emojis of one server."""
        if not force:
            cached = self._emojis_cache.get(guild_id)
            if cached:
                return cached
        emojis = self.api_request("GET", f"/guilds/{guild_id}/emojis")
        self._emojis_cache.set(guild_id, emojis)
        return emojis

    def get_channel(self, channel_id):
        """Details about ONE channel - used when you paste a channel ID."""
        return self.api_request("GET", f"/channels/{channel_id}")

    def clear_caches(self):
        """Forget everything remembered - the next call asks Discord again."""
        for cache in (self._me_cache, self._guilds_cache, self._channels_cache,
                      self._roles_cache, self._emojis_cache, self._guild_cache):
            cache.clear()

    # ------------------------------------------------------------------
    # Message calls (send / edit / delete)
    # ------------------------------------------------------------------

    def send_message(self, channel_id, payload, files=None):
        """
        Post a message to a channel.

        payload - the message as Python data, e.g.
                  {"content": "hello", "embeds": [ ... ]}
        files   - optional list of (filename, bytes, content_type) tuples
                  for pictures you uploaded from your PC.
        """
        if files:
            # With picture uploads Discord wants a "multipart" request: the
            # message JSON travels in a form field called "payload_json" and
            # every picture becomes a file named files[0], files[1], ...
            multipart = {"payload_json": (None, json.dumps(payload), "application/json")}
            for index, (filename, blob, content_type) in enumerate(files):
                multipart[f"files[{index}]"] = (filename, blob, content_type)
            return self.api_request("POST", f"/channels/{channel_id}/messages",
                                    files=multipart)

        return self.api_request("POST", f"/channels/{channel_id}/messages",
                                json_body=payload)

    def edit_message(self, channel_id, message_id, payload, files=None):
        """
        Change a message this bot already sent. Uses the same multipart
        trick when new files are given.
        """
        if files:
            multipart = {"payload_json": (None, json.dumps(payload), "application/json")}
            for index, (filename, blob, content_type) in enumerate(files):
                multipart[f"files[{index}]"] = (filename, blob, content_type)
            return self.api_request("PATCH",
                                    f"/channels/{channel_id}/messages/{message_id}",
                                    files=multipart)

        return self.api_request("PATCH",
                                f"/channels/{channel_id}/messages/{message_id}",
                                json_body=payload)

    def delete_message(self, channel_id, message_id):
        """Remove a message this bot already sent. Returns None on success."""
        return self.api_request("DELETE",
                                f"/channels/{channel_id}/messages/{message_id}")


# ---------------------------------------------------------------------------
# Validating a pasted token (used when adding a new bot)
# ---------------------------------------------------------------------------

def validate_token(token, display_name="This bot"):
    """
    Check that a pasted token works BEFORE saving it anywhere.
    Returns the /users/@me answer (id, username, avatar, ...).
    Raises DiscordAPIError with a friendly message when it does not work.
    """
    prober = BotClient("token-check", token, display_name)
    return prober.get_me(force=True)


# ---------------------------------------------------------------------------
# Direct Webhook Sending
# ---------------------------------------------------------------------------

def post_webhook(webhook_url, payload, files=None):
    """
    Post a message directly to a Discord Webhook URL.
    Returns the created message JSON or None.
    """
    if not webhook_url or not str(webhook_url).startswith("http"):
        raise DiscordAPIError(400, "invalid_url", "Invalid webhook URL", "bad_request")

    sep = "&" if "?" in webhook_url else "?"
    url = f"{webhook_url}{sep}wait=true"

    if files:
        multipart = {"payload_json": (None, json.dumps(payload), "application/json")}
        for index, (filename, blob, content_type) in enumerate(files):
            multipart[f"files[{index}]"] = (filename, blob, content_type)
        resp = requests.post(url, files=multipart, timeout=20)
    else:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=20)

    if resp.status_code >= 400:
        raw = resp.text[:300]
        raise DiscordAPIError(resp.status_code, raw, _friendly(resp.status_code, raw, "Webhook"), _kind(resp.status_code), "Webhook")

    try:
        return resp.json()
    except ValueError:
        return None
