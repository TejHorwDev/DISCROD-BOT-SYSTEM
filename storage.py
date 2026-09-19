"""
storage.py - safe JSON storage, versioned migrations and backups.

Why does this file exist?
  All of SELLER BOT's data (your products, bots, settings, history,
  schedules) lives in simple JSON files inside the "data/" folder, right
  next to this file. JSON is just text - you can open the files with
  Notepad and read them.

  This file takes care of four jobs:

    1. SAFE SAVES. If you save a file the normal way and the app is closed
       at exactly the wrong moment, the file can end up half-written and
       broken. To make that impossible, we ALWAYS:
           a. write the new content to a temporary file (products.json.tmp)
           b. flush it down to the disk
           c. "atomically" swap it over the real file in one step
       The swap is done by the operating system itself, so the real file is
       always either the complete OLD version or the complete NEW version.

    2. FILE LOCKS. The web page and the background schedule worker can try
       to save the same file at the same millisecond. A small "lock" per
       file makes them politely wait for each other instead.

    3. VERSIONED MIGRATIONS. When a new version of the app changes the
       shape of a data file, a small "migration" function upgrades your
       old file to the new shape. Every file stores its version in a
       "schema_version" key, so a migration only runs when it is actually
       needed, and running it twice changes nothing (that is what
       "idempotent" means).

    4. BACKUPS. Before any migration touches your data, the whole data/
       folder is copied to data/backup_<date-and-time>/ - so even if
       something surprising happens, nothing is ever lost.

The current file shapes:

    products.json ("schema version 3" - adds pricing plans + theme):
        {
          "schema_version": 3,
          "items": [ {..., "plans": [...], "theme_id": ""}, ... ]
        }
    history.json / schedules.json / sections.json (version 2 / 2 / 1):
        {
          "schema_version": 2,
          "items": [ {...}, {...} ]     <- a list of records
        }
    settings.json:
        { "schema_version": 2, "last_guild_id": "...", ... }

    Version 1 (the original app) stored plain lists like [ {...}, ... ]
    without any version key - the migration wraps them and stamps every
    record with the bot that owns it (bot_id "seller"). Version 2 made
    the app multi-bot. Version 3 (products only) gives every product its
    pricing plans (1 Month Key / 3 Months Key / ... each with its own
    price) - old single-price products become a one-plan product, so old
    listings render exactly the way they always did.

You never need to call anything in this file yourself; app.py uses it.
"""

import json     # built-in Python module for reading/writing JSON
import os       # built-in module for files and folders
import shutil   # used only for making backups
import threading
from datetime import datetime

# The data folder lives next to this file:  seller-bot/data/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------------------------------------------------------------------
# The current schema version of every data file this module owns.
# Bump a number here AND add/extend the migration in _MIGRATIONS below
# whenever the shape of that file changes.  (bots.json is owned by bots.py
# and stays at version 1 for now.)
# ---------------------------------------------------------------------------
CURRENT_SCHEMA = {
    "products.json": 3,
    "history.json": 2,
    "schedules.json": 2,
    "settings.json": 2,
    "sections.json": 1,
    "vouches.json": 1,
}

# The list of files that use the {"schema_version": ..., "items": [...]}
# "wrapped list" shape.  load_items() / save_items() work with these.
LIST_FILES = ("products.json", "history.json", "schedules.json",
              "sections.json", "vouches.json")

# ---------------------------------------------------------------------------
# Per-file locks - so two threads never write the same file at once
# ---------------------------------------------------------------------------

_FILE_LOCKS = {}                      # file name -> threading.Lock
_FILE_LOCKS_GUARD = threading.Lock()  # protects the dictionary above


def _lock_for(filename):
    """Return the one lock that belongs to this data file (created once)."""
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(filename)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[filename] = lock
        return lock


# ---------------------------------------------------------------------------
# Basic folder + path helpers
# ---------------------------------------------------------------------------

def ensure_data_dir(base_dir=None):
    """Create the data/ folder (or user data folder) if it does not exist yet."""
    os.makedirs(base_dir or DATA_DIR, exist_ok=True)


def path_for(filename, base_dir=None):
    """
    Turn a simple file name into a full path inside the data folder (or user folder).
    Example:  path_for("settings.json") -> .../seller-bot/data/settings.json
    """
    return os.path.join(base_dir or DATA_DIR, filename)


# ---------------------------------------------------------------------------
# Raw load / save (used by migrations and by bots.py for its own file)
# ---------------------------------------------------------------------------

def load_json(filename, default, base_dir=None):
    """
    Read a JSON file from the data folder and return it as Python data.

    filename - the file name, e.g. "settings.json"
    default  - what to return if the file does not exist yet
    base_dir - optional custom directory (e.g. data/users/<user_id>/)
    """
    ensure_data_dir(base_dir)
    path = path_for(filename, base_dir)

    # No file yet? That is fine - return the default (first run).
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read().strip()
            if not content:
                return default          # an empty file counts as "not there yet"
            return json.loads(content)  # turn the text into Python data
    except (json.JSONDecodeError, OSError):
        try:
            os.replace(path, path + ".corrupted")
        except OSError:
            pass
        return default


def save_json(filename, data, base_dir=None):
    """
    Save Python data into a JSON file in the data folder - the safe way.
    """
    ensure_data_dir(base_dir)
    path = path_for(filename, base_dir)
    tmp_path = path + ".tmp"

    lock_key = f"{base_dir or ''}:{filename}"
    with _lock_for(lock_key):
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())

        os.replace(tmp_path, path)
    return True


# ---------------------------------------------------------------------------
# Typed helpers for the two file shapes we use
# ---------------------------------------------------------------------------

def load_items(filename, base_dir=None):
    """
    Read a "wrapped list" file (products / history / schedules) and return
    ONLY the list of records. Missing file or old shape -> empty list.
    """
    doc = load_json(filename, None, base_dir=base_dir)
    if isinstance(doc, dict) and isinstance(doc.get("items"), list):
        return doc["items"]
    if isinstance(doc, list):            # very old shape, just in case
        return doc
    return []


def save_items(filename, items, base_dir=None):
    """Save a list of records into a "wrapped list" file with the version."""
    save_json(filename, {
        "schema_version": CURRENT_SCHEMA.get(filename, 1),
        "items": items,
    }, base_dir=base_dir)


def load_doc(filename, base_dir=None):
    """Read a dictionary file (settings.json ...). Missing -> empty dict."""
    doc = load_json(filename, None, base_dir=base_dir)
    return doc if isinstance(doc, dict) else {}


def save_doc(filename, doc, base_dir=None):
    """Save a dictionary file, stamping the current schema version on it."""
    payload = dict(doc) if isinstance(doc, dict) else {}
    payload["schema_version"] = CURRENT_SCHEMA.get(filename, 1)
    save_json(filename, payload, base_dir=base_dir)


# ---------------------------------------------------------------------------
# Backups - copy the whole data folder before touching anything
# ---------------------------------------------------------------------------

def _backup_name_taken():
    """Set of backup folder names that already exist (to never overwrite)."""
    try:
        return {name for name in os.listdir(DATA_DIR) if name.startswith("backup_")}
    except OSError:
        return set()


def backup_data_dir():
    """
    Copy everything in data/ into data/backup_<timestamp>/ and return the
    backup folder name. Returns None when there was nothing to copy.

    What gets copied:
      * every file directly inside data/ (the JSON files),
      * the uploads/ and media/ folders (pictures),
    What is NOT copied:
      * old backup folders themselves (no backups of backups),
      * the cache/ folder (it only holds throw-away generated banners).
    """
    ensure_data_dir()

    entries = os.listdir(DATA_DIR)
    copyable = [name for name in entries
                if not name.startswith("backup_") and name != "cache"]
    if not copyable:
        return None                       # brand new install - nothing to keep

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    taken = _backup_name_taken()
    name = f"backup_{stamp}"
    counter = 1
    while name in taken:                  # two backups in the same second
        name = f"backup_{stamp}-{counter}"
        counter += 1

    destination = os.path.join(DATA_DIR, name)
    os.makedirs(destination, exist_ok=True)

    for entry in copyable:
        source = os.path.join(DATA_DIR, entry)
        try:
            if os.path.isdir(source):
                shutil.copytree(source, os.path.join(destination, entry),
                                dirs_exist_ok=True)
            elif os.path.isfile(source):
                shutil.copy2(source, os.path.join(destination, entry))
        except OSError:
            # A single stubborn file must never stop the whole backup.
            pass

    return name


# ---------------------------------------------------------------------------
# Migrations - upgrade old data files to the current shape, safely
# ---------------------------------------------------------------------------

def _stamp_bot_id(record):
    """Make sure one record says which bot owns it (default: "seller")."""
    if isinstance(record, dict) and not record.get("bot_id"):
        record["bot_id"] = "seller"
    return record


def _migrate_list_file(filename, version=2):
    """
    Upgrade one "wrapped list" file (products / history / schedules /
    sections).

    Version 1 (old app):  [ {...}, {...} ]          <- plain list
    Version 2 (multi-bot): {"schema_version": 2,
                            "items": [ {..., "bot_id": "seller"}, ... ]}

    `version` is the CURRENT version of that file (sections.json stays at
    version 1 - it is brand new and has no older shapes to upgrade).

    Returns True when the file on disk was changed.
    """
    raw = load_json(filename, None)

    # Missing file: nothing to migrate (it will be created fresh later).
    if raw is None:
        return False

    # Already AT (or past) this step - only re-stamp bot_id on records
    # that lost it (idempotent safety net; saves only when needed).
    if isinstance(raw, dict) and isinstance(raw.get("items"), list) and \
            raw.get("schema_version", 0) >= version:
        changed = False
        if version >= 2:
            for record in raw["items"]:
                if isinstance(record, dict) and not record.get("bot_id"):
                    record["bot_id"] = "seller"
                    changed = True
        if changed:
            save_json(filename, raw)
            return True
        return False

    # An older wrapped shape (v1/v2) -> bring it to this version.
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        items = [_stamp_bot_id(record) for record in raw["items"]] \
            if version >= 2 else raw["items"]
        save_json(filename, {"schema_version": version, "items": items})
        return True
    if isinstance(raw, list):
        items = [_stamp_bot_id(record) for record in raw] \
            if version >= 2 else list(raw)
        save_json(filename, {"schema_version": version, "items": items})
        return True

    # Something unexpected (for example a dict without "items"). We never
    # destroy data: rename it aside and start a clean file.
    path = path_for(filename)
    try:
        os.replace(path, path + ".unexpected")
    except OSError:
        pass
    save_json(filename, {"schema_version": version, "items": []})
    return True


def _migrate_products_v3():
    """
    products.json v2 -> v3: every product gains its pricing plans.

    * a product that already has a non-empty "plans" list keeps it,
    * an old single-price product gets one plan ("Standard") built from
      its price / oldPrice - so old listings keep rendering exactly as
      they did,
    * "theme_id" is added ("" = follow the status color, no theme).

    Idempotent: a v3 file with plans in place is left completely alone.
    Returns True when the file on disk was changed.
    """
    raw = load_json("products.json", None)
    if raw is None:
        return False                          # created fresh on first run
    if not (isinstance(raw, dict) and isinstance(raw.get("items"), list)):
        return False                          # the wrap migration handles it

    changed = False
    for product in raw["items"]:
        if not isinstance(product, dict):
            continue
        plans = product.get("plans")
        if not isinstance(plans, list) or not plans:
            price = str(product.get("price") or "").strip()
            old = str(product.get("oldPrice") or "").strip()
            new_plans = ([{"id": "standard", "label": "Standard",
                           "price": price, "oldPrice": old, "badge": ""}]
                         if (price or old) else [])
            # only count as a change when the value really differs (a free
            # product with plans already [] must not wake the migration)
            if new_plans != plans:
                product["plans"] = new_plans
                changed = True
        if "theme_id" not in product:
            product["theme_id"] = ""
            changed = True

    if raw.get("schema_version") != 3:
        raw["schema_version"] = 3
        changed = True

    if changed:
        save_json("products.json", raw)
    return changed


def _migrate_settings():
    """
    settings.json v1 was a plain dict without a version key. v2 simply adds
    "schema_version": 2 (the values themselves did not change).
    Returns True when the file on disk was changed.
    """
    raw = load_json("settings.json", None)
    if raw is None:
        return False                          # will be created fresh later
    if not isinstance(raw, dict):
        return False                          # should never happen

    if raw.get("schema_version") == CURRENT_SCHEMA["settings.json"]:
        return False

    raw["schema_version"] = CURRENT_SCHEMA["settings.json"]
    save_json("settings.json", raw)
    return True


# Which migration runs for which file. Keep this table and the functions
# above in sync, and bump CURRENT_SCHEMA when you add a new step.
def _migrate_products():
    """Products run BOTH steps in one pass: wrap old shapes, then add plans."""
    changed = _migrate_list_file("products.json", version=2)
    return _migrate_products_v3() or changed


_MIGRATIONS = {
    "products.json": _migrate_products,
    "history.json": lambda: _migrate_list_file("history.json"),
    "schedules.json": lambda: _migrate_list_file("schedules.json"),
    "sections.json": lambda: _migrate_list_file("sections.json", version=1),
    "settings.json": _migrate_settings,
}


def run_migrations():
    """
    Upgrade every data file to the current shape.

    IMPORTANT details:
      * a full backup of data/ is made FIRST, but only when at least one
        file actually needs changing (a no-op run never clutters data/),
      * every migration checks the version before touching anything, so
        running this on every start is completely safe,
      * it returns a small report that the app prints in its console.

    (bots.json is created/migrated by bots.ensure_registry() right after
    this runs - it is that module's own file.)
    """
    report = {"backup": None, "migrated": []}

    # Peek first: does anything need changing? Only then take a backup.
    needs_change = False
    for filename, migrate in _MIGRATIONS.items():
        probe = load_json(filename, None)
        if filename in LIST_FILES:
            wanted = CURRENT_SCHEMA[filename]
            if isinstance(probe, list):
                needs_change = True
            elif isinstance(probe, dict):
                if probe.get("schema_version") != wanted:
                    needs_change = True
                else:
                    # at the right version, but records may need re-stamps
                    items = probe.get("items", [])
                    if wanted >= 2 and any(isinstance(r, dict) and not r.get("bot_id")
                                           for r in items):
                        needs_change = True
                    if filename == "products.json" and any(
                            isinstance(r, dict) and
                            (not isinstance(r.get("plans"), list) or not r.get("plans"))
                            and (str(r.get("price") or "").strip()
                                 or str(r.get("oldPrice") or "").strip())
                            for r in items):
                        needs_change = True
                    if filename == "products.json" and any(
                            isinstance(r, dict) and "theme_id" not in r
                            for r in items):
                        needs_change = True
            elif probe is not None:
                needs_change = True
        else:  # settings.json
            if probe is not None and probe.get("schema_version") != CURRENT_SCHEMA[filename]:
                needs_change = True

    if needs_change:
        report["backup"] = backup_data_dir()

    for filename, migrate in _MIGRATIONS.items():
        try:
            if migrate():
                report["migrated"].append(filename)
        except Exception as problem:      # a migration must never crash the app
            print(f"  WARNING: could not migrate {filename}: {problem}")

    return report


# ---------------------------------------------------------------------------
# First-run creation of missing data files
# ---------------------------------------------------------------------------

def ensure_data_files(default_factories, base_dir=None):
    """
    Create any missing data file using the given factory functions.

    default_factories - {"products.json": callable, ...} where the callable
                        returns the COMPLETE first-run content of that file.
                        Only called when the file does not exist yet.
    """
    ensure_data_dir(base_dir=base_dir)
    for filename, factory in default_factories.items():
        if not os.path.exists(path_for(filename, base_dir=base_dir)):
            save_json(filename, factory(), base_dir=base_dir)

