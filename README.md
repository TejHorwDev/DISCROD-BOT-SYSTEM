# SELLER BOT STUDIO

A multi-bot Discord publishing studio that runs 100% on your PC.
Build beautiful product listings, pricing plans, announcements and rules
pages in your browser, then post them to your server through one (or
several) of your own bots.

No gateway connection, no slash commands, no always-running loop - the
app talks to Discord's normal REST API only when YOU click a button.
Tickets are handled by your other bot (the one that is already online);
SELLER BOT just makes sure every listing ends with a clickable
"open a ticket" line pointing at it.

---

## What's inside (v2.0 - the big upgrade)

| Feature | What it does |
|---|---|
| **Multi-bot dashboard** | Add as many bots as you like (Seller bot, Messenger bot, ...). Switch between them in the header, or override the bot per message. Tokens live ONLY in your `.env` file - the dashboard never even receives them. |
| **Pricing plans** | One product, many plans: `1 Month Key $4.99`, `3 Months Key $9.99`, `1 Year Key $19.99`, `Lifetime Key $49.99` - each with its own price, optional strike-through "old price" (with automatic `-38% OFF` badge) and a small badge like `POPULAR`. Quick-add buttons for common key lengths. |
| **Sections (Messenger bot content)** | Announcements, server rules, update logs - anything that is not a product. Four types (Clean / Announcement / Rules / Update), own images, own theme, own sending bot. Three starter sections ship with the app. |
| **Real theme system** | 12 built-in themes (color bar + Unicode heading style + optional author line + footer), plus the Theme Studio to create your own. Themes never change what a message says - only how it looks. |
| **11 Unicode heading styles** | Bold, Italic, Bold Italic, Script, Bold Script, Fraktur, Double-struck, Monospace, Small Caps, Fullwidth, Circled - applied by the server, shown live in the preview. |
| **One source of truth rendering** | The page sends a *content model*; `renderer.py` on the server builds the exact Discord payload. The preview shows that payload, and Send posts that payload. What you see is literally what you send. |
| **Auto-split** | A listing too big for one Discord message? It is automatically split into several embeds and messages (all of Discord's limits enforced), with clear "Message 1 of 2" dividers in the preview. |
| **Images & GIFs everywhere** | Product banners, thumbnails, 4-image galleries (shown as a Discord grid), section images, an image LIBRARY that remembers every upload for reuse. Pillow verifies every file and smartly shrinks oversized photos (animated GIFs are never touched). |
| **Everything else from v1** | 4 layout presets (Modern Card / Minimal / Big Banner / Flash Sale), fancy text, the ticket line, scheduled posts, history with one-click Sold out / Restock / Change prices / Edit / Repost / Delete, test sends, LAN mode. |

---

## Quick start (5 minutes)

### 1. Create your bot on Discord

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Left side: **Bot** tab -> **Reset Token** -> **Copy** the token.
   (Treat it like a password - anyone with it controls your bot.)
3. That's it for now - the app builds the invite link for you later.

### 2. Start SELLER BOT

* **Windows**: double-click **run.bat**
* **Mac / Linux**: run **bash run.sh**

The first run creates a private Python environment, installs the four
packages (flask, requests, python-dotenv, pillow) and opens your browser
at **http://localhost:5000**.

### 3. Add the bot in the app

1. Open the **Bots** tab -> **+ Add bot**.
2. Give it a name (e.g. `SELLER BOT`), pick what it will do, paste the token.
3. The app checks the token with Discord, saves it into `.env` (nowhere
   else!) and shows the ready-made **invite link**.
4. Open the link, pick your server, keep all permission boxes ticked,
   click **Continue** -> **Authorise**.
5. Back in the app: **Test connection** - the bot now sees your server.

### 4. Post your first listing

1. At the top: pick your **server** and tick one or more **channels**.
2. **Builder** tab: name your product, add pricing plans, features, images.
3. Watch the **live preview** on the right - it is the exact message.
4. **Send** (or **Send test** first - see "Test channel" below).

### 5. Optional: the test channel

Add a private channel's ID to `.env` to unlock the **Send test** button:

```
TEST_CHANNEL_ID=1234567890123456789
```

(To copy an ID: Discord Settings -> Advanced -> enable **Developer Mode**,
then right-click the channel -> **Copy Channel ID**.)

---

## The tour, tab by tab

### Builder
The product form (name, plans, features, images, layout, theme, ticket
line) on the left, the live Discord preview + pre-flight checks on the
right. Everything you change is re-rendered by the server after ~0.3s -
the preview is never a guess, it is the actual payload.

The four layout presets change how the same data is arranged:

* **Modern Card** - colored status bar, fields in a grid
* **Minimal** - everything in the description, no fields
* **Big Banner** - huge price headline at the top
* **Flash Sale** - red accent, discount + countdown in your face

### Library
Everything you saved, with thumbnails and plan summaries. Load, duplicate,
export or delete. **Import JSON** brings products from a friend or a
backup.

### Sections
Your Messenger bot's content. Write an announcement or a rules page, pick
a type and a theme, and post it with any bot (a Messenger bot feels
right). Editing a sent section later works exactly like editing a sent
product.

### History
Every message every bot posted, with one-click actions:
**Mark SOLD OUT** (red, struck-through title), **Restock**, **Change
prices** (edits every plan), **Edit**, **Repost / bump**, **Send to...**
(another channel) and **Delete**. These edit the REAL Discord messages
through the API. Multi-message listings are handled as a unit - all of
their Discord messages are updated or deleted together.

### Scheduled
Plan a post for a later date + time. The listing is stored as content
(not a finished message), so it renders with the theme and ticket line
exactly as they are at fire time. SELLER BOT is a local app: schedules
only fire while it is running; missed ones are marked and can be run with
one click.

### Bots
The multi-bot registry: add, test, invite, enable/disable and remove
bots. Each bot has its own rate-limit handling. Bots show as **offline**
in Discord - that is completely normal for a REST-only tool; they only
"appear" for the moment a message is posted.

### Themes
The Theme Studio: 12 built-in themes to browse, a editor for your own
(color, title/heading letter style, author line, footer, bot thumbnail),
duplicate any built-in to make it yours. Apply themes in the Builder and
the Sections tab.

### Settings
The ticket channel (every listing ends with a clickable mention of it),
the ticket line text (placeholders: `{ticket_channel}`, `{product}`,
`{price}`), and the `@everyone` safety switch (off by default - normal
role pings always work).

---

## How it works (and why it is safe)

```
your browser  <->  this app (Flask, on your PC)  <->  Discord REST API
                        |
                        +-> renderer.py  = the ONE place a Discord message is built
                        +-> data/*.json  = products, sections, themes, history, schedules
                        +-> .env         = bot tokens (never sent to the browser)
```

* **Tokens** live only in the `.env` file on your PC. The dashboard only
  ever shows `••••last4`. Removing a bot deletes its token line (except
  the legacy `DISCORD_TOKEN`, which is kept untouched).
* **Data** is plain JSON in `data/` - open it in Notepad anytime. Saves
  are atomic (a crash can never leave a half-written file), and any
  upgrade makes a full backup first (`data/backup_<timestamp>/`).
* **Every upload** is checked with Pillow: it must really be a complete
  PNG/JPG/GIF/WEBP picture, max 8 MB. Oversized photos are scaled down to
  2000px and heavy PNG photos become JPEGs - animated GIFs are stored
  byte-for-byte unchanged.
* **Discord's limits** (title 256, description 4096, field values 1024,
  25 fields, 6000 characters per message, 10 embeds...) are enforced by
  the renderer and double-checked before anything leaves your PC.

## Upgrading from v1?

Just start the new version - nothing to do by hand:

* your old `DISCORD_TOKEN` becomes bot #1 ("SELLER BOT"),
* every product gets its single price turned into a one-plan product
  (renders exactly like before),
* all files are upgraded in place after a full automatic backup,
* old history entries stay editable - the renderer understands old data.

---

## File map

| File | What it is |
|---|---|
| `app.py` | the web server + all JSON endpoints |
| `renderer.py` | THE single source of truth for Discord payloads (presets, plans, themes, auto-split) |
| `themes.py` | the theme store + the 12 built-ins (`data/themes.json`) |
| `fontstyles.py` | the 11 Unicode heading styles (shared by server + page) |
| `bots.py` | the multi-bot registry (tokens stay in `.env`) |
| `discord_api.py` | the only file that talks to Discord (rate limits, retries, friendly errors) |
| `storage.py` | safe JSON storage, versioned migrations, backups |
| `templates/index.html`, `static/app.js`, `static/style.css` | the dashboard |
| `run.bat` / `run.sh` | one-click starters |
| `data/` | your products, sections, themes, history, schedules, uploads (created on first run) |

## Troubleshooting

| Problem | Fix |
|---|---|
| "Bot not connected" | Wrong/old token in `.env` - reset it in the Developer Portal and update the file, or remove + re-add the bot on the Bots page. |
| Bot shows offline in Discord | Normal! REST-only bots only appear while a message is being posted. |
| Server list is empty | The bot was never invited - use the invite link button on the Bots page. |
| "missing permissions" next to a server | Re-open the invite link and keep all boxes ticked - inviting again is safe and only updates permissions. |
| Message did not post | Read the error toast - it names the bot and the exact permission or limit problem. |
| Ticket line shows as plain text | Pick the ticket channel in the Settings tab. |
| Preview shows "Message 1 of 2" | Not an error - your listing is bigger than one Discord message, so it will be posted as several. Shorten it if you prefer one. |
| Image upload rejected | Must be a real PNG/JPG/GIF/WEBP under 8 MB. |
| Schedule did not fire | The app must be running at that time. It is marked "missed" - press Run now. |
| Port 5000 already in use | Set `PORT=5001` in `.env` and open `http://localhost:5001`. |
| Want to use it from your phone | Set `ALLOW_LAN=true` in `.env`, restart, open the printed Wi-Fi address. |

## Security notes

* Never share your `.env` file or bot tokens.
* If a token leaks: Developer Portal -> your app -> Bot -> **Reset Token**
  - the old one stops working immediately.
* The app binds to `127.0.0.1` by default (only your PC can open it).
  `ALLOW_LAN=true` opens it to your Wi-Fi - turn it off when you do not
  need it.

## Final test checklist

1. Bots page: bot added, **Test connection** green, server listed.
2. Builder: type a name, add a second plan - preview shows both prices.
3. Pick a theme - preview bar color + title letters change.
4. Tick a channel, press **Send test** - check your test channel.
5. Press **Send** - check the real channel + the History tab.
6. History: **Mark SOLD OUT** - the Discord message turns red and struck-through.
7. History: **Change prices** - both plans update in Discord.
8. Sections: load "Server Rules", send it - your rules page posts as an embed with your bot's name on top.
9. Themes: create a custom theme, use it for a product.
10. Restart the app - everything is still there (products, sections, themes, history).
