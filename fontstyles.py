"""
fontstyles.py - the 11 Unicode "fancy text" styles, shared by everything.

What is this about?
  Discord messages are plain text, so you cannot pick a real font for them.
  But Unicode (the big table of every letter on earth) contains whole
  alphabets of LOOK-ALIKE letters: mathematical bold, gothic "fraktur",
  double-struck, monospace, circled, and more. Swapping A -> 𝐀 makes a
  heading LOOK like it uses a different font, even though it is still text.

  Both the SERVER (renderer.py, when it builds the real Discord message)
  and the PAGE (the style pickers in the Builder and Theme Studio) use
  this exact same list, so what you pick is always what gets posted.

The 11 styles:
  none          - normal letters (turns styling off)
  bold          - 𝐁𝐨𝐥𝐝
  italic        - 𝘐𝘵𝘢𝘭𝘪𝘤
  bold_italic   - 𝘽𝙤𝙡𝙙 𝙄𝙩𝙖𝙡𝙞𝙘
  script        - 𝒮𝒸𝓇𝒾𝓅𝓉
  bold_script   - 𝓑𝓸𝓵𝓭 𝓢𝓬𝓻𝓲𝓹𝓽
  fraktur       - 𝔉𝔯𝔞𝔨𝔱𝔲𝔯
  double        - 𝔻𝕠𝕦𝕓𝕝𝕖
  mono          - 𝙼𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎
  smallcaps     - sᴍᴀʟʟ ᴄᴀᴘs
  fullwidth     - Ｆｕｌｌｗｉｄｔｈ
  circled       - Ⓒⓘⓡⓒⓛⓔⓓ

How the tables are built (and why it matters):
  The fancy alphabets live in Unicode's "Mathematical Alphanumeric
  Symbols" block - mostly simple ranges, but with a handful of old
  letters that already existed elsewhere (ℬ, ℰ, ℱ, ℋ, ℐ, ℒ, ℛ, ℂ, ℍ ...).
  Instead of typing the alphabets by hand (one wrong letter and a heading
  silently loses a character - that exact bug happened once), this module
  BUILDS every table from Unicode code points, so each style is guaranteed
  to have exactly 26 + 26 + 10 letters.

  The tables are also turned into real character lists once, up front:
  fancy letters are built from TWO halves ("surrogate pairs"), and plain
  string indexing would grab only half a letter - which later crashes the
  JSON writer. Going through list() first is the fix.

Old products saved by earlier versions used the ids "bold", "script",
"smallcaps" and "mono" - they all still exist here, so old data keeps
working without any migration.
"""


def _range_chars(start, count):
    """count characters, starting at Unicode code point `start`."""
    return "".join(chr(start + index) for index in range(count))


def _alphabet(upper_start, lower_start, digit_start=None,
              upper_map=None, lower_map=None):
    """
    Build one 26+26+10 letter table.

    upper_start / lower_start - code point of styled 'A' / 'a'
    digit_start               - code point of styled '0' (None = plain 0-9)
    upper_map / lower_map     - {letter_index: code point} exceptions,
                                for the few letters Unicode keeps outside
                                the main range (script B, fraktur C, ...).
    """
    upper_map = upper_map or {}
    lower_map = lower_map or {}

    upper = "".join(
        chr(upper_map.get(index, upper_start + index)) for index in range(26))
    lower = "".join(
        chr(lower_map.get(index, lower_start + index)) for index in range(26))
    digits = _range_chars(digit_start, 10) if digit_start else "0123456789"
    return {"upper": upper, "lower": lower, "digits": digits}


# --- the four alphabets Unicode keeps in the old "letterlike symbols" block
# (keyed by letter index: 0=A, 1=B, 2=C ...)
_SCRIPT_HOLES = {1: 0x212C, 4: 0x2130, 5: 0x2131, 7: 0x210B, 8: 0x2110,
                 11: 0x2112, 17: 0x211B}                     # B E F H I L R
_FRAKTUR_HOLES = {1: 0x212D, 7: 0x210C, 8: 0x2111, 17: 0x211C, 25: 0x2128}
_DOUBLE_HOLES = {1: 0x2102, 7: 0x210D, 13: 0x2115, 15: 0x2119,
                 16: 0x211A, 17: 0x211D, 25: 0x2124}         # C H N P Q R Z

# small caps are not a Unicode range - a hand table (x and y have no twin
# and simply stay normal, which the swap leaves alone automatically)
_SMALLCAPS = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"

_STYLED_TABLES = {
    "none": {"upper": _range_chars(65, 26), "lower": _range_chars(97, 26),
             "digits": "0123456789"},
    "bold": _alphabet(0x1D400, 0x1D41A, 0x1D7CE),            # mathematical bold
    "italic": _alphabet(0x1D608, 0x1D622),                   # sans italic
    "bold_italic": _alphabet(0x1D63C, 0x1D656),              # sans bold italic
    "script": _alphabet(0x1D49C, 0x1D4B6, upper_map=_SCRIPT_HOLES),
    "bold_script": _alphabet(0x1D4D0, 0x1D4EA),              # bold script (no holes)
    "fraktur": _alphabet(0x1D504, 0x1D51E, upper_map=_FRAKTUR_HOLES),
    "double": _alphabet(0x1D538, 0x1D552, 0x1D7D8,
                        upper_map=_DOUBLE_HOLES),
    "mono": _alphabet(0x1D670, 0x1D68A, 0x1D7F6),            # monospace
    "smallcaps": {"upper": _SMALLCAPS, "lower": _SMALLCAPS,
                  "digits": "0123456789"},
    "fullwidth": _alphabet(0xFF21, 0xFF41, 0xFF10),          # fullwidth
    "circled": _alphabet(0x24B6, 0x24D0, None,
                         # digits: (1) U+2460..U+2468, then (0) U+24EA
                         upper_map={}, lower_map={}),
}
# circled digits: ① ② ③ ... ⑨ then ⓪  (there is no plain range 0-9)
_STYLED_TABLES["circled"]["digits"] = _range_chars(0x2460, 9) + chr(0x24EA)

# friendly names shown in the pickers
_STYLE_LABELS = {
    "none": "Normal (no styling)",
    "bold": "Bold",
    "italic": "Italic",
    "bold_italic": "Bold Italic",
    "script": "Script",
    "bold_script": "Bold Script",
    "fraktur": "Fraktur (gothic)",
    "double": "Double-struck",
    "mono": "Monospace",
    "smallcaps": "Small Caps",
    "fullwidth": "Fullwidth",
    "circled": "Circled",
}

# The ids in a stable, human-friendly order (used by the pickers).
STYLE_ORDER = [
    "none", "bold", "italic", "bold_italic", "script", "bold_script",
    "fraktur", "double", "mono", "smallcaps", "fullwidth", "circled",
]

# Final safety net: every table must be exactly 26 + 26 + 10 real letters.
# (This runs once at import; if a Unicode name ever moves, the app refuses
# to start with a clear message instead of posting broken headings.)
for _id, _table in _STYLED_TABLES.items():
    for _key, _wanted in (("upper", 26), ("lower", 26), ("digits", 10)):
        _letters = list(_table[_key])
        assert len(_letters) == _wanted, (
            f"fontstyles: style '{_id}' has {len(_letters)} '{_key}' letters "
            f"(expected {_wanted}) - the table builder is broken")
        for _letter in _letters:
            assert not (0xD800 <= ord(_letter) <= 0xDFFF), (
                f"fontstyles: style '{_id}' contains a broken half-letter")

# Turn every table into REAL single characters once, up front.
_STYLE_TABLES = {
    style_id: {key: list(table[key]) for key in table}
    for style_id, table in _STYLED_TABLES.items()
}


def style_exists(style_id):
    """True when the id names one of the known styles."""
    return style_id in _STYLED_TABLES


def normalize_style(style_id, default="none"):
    """Return a safe style id: unknown/empty values become the default."""
    if isinstance(style_id, str) and style_id in _STYLED_TABLES:
        return style_id
    return default


def apply_style(text, style_id):
    """
    Convert text into the chosen Unicode style.
    Anything that is not A-Z, a-z or 0-9 (emoji, spaces, punctuation,
    other alphabets) is left exactly as it is.
    """
    if not text:
        return text
    style_id = normalize_style(style_id)
    if style_id == "none":
        return str(text)

    tables = _STYLE_TABLES[style_id]
    upper, lower, digits = tables["upper"], tables["lower"], tables["digits"]

    out = []
    for character in str(text):
        code = ord(character)
        if 65 <= code <= 90:                       # A-Z
            out.append(upper[code - 65])
        elif 97 <= code <= 122:                    # a-z
            out.append(lower[code - 97])
        elif 48 <= code <= 57:                     # 0-9
            out.append(digits[code - 48])
        else:
            out.append(character)
    return "".join(out)


def style_menu():
    """
    The style list for the dashboard pickers:
    [{"id": "bold", "label": "Bold", "sample": "𝐀𝐚 𝐁𝐛 𝟏𝟐𝟑"}, ...]
    """
    menu = []
    for style_id in STYLE_ORDER:
        sample = apply_style("Aa Bb 123", style_id)
        menu.append({"id": style_id, "label": _STYLE_LABELS[style_id],
                     "sample": sample})
    return menu


def style_label(style_id):
    """The friendly name of one style ("Normal" for bad ids)."""
    style_id = normalize_style(style_id)
    return _STYLE_LABELS[style_id]
