"""
Offline movie database for the Movie Chain game.

- Titles are loaded ONCE from data/movies.json when the bot starts.
- A normalized O(1) lookup index is built in memory at load time —
  the JSON file is never re-read per message.
- Validation is EXACT normalized matching only. No fuzzy matching:
  "Intersteller" never becomes "Interstellar".
- 100% offline. This module makes NO network requests and needs NO keys.

Failure policy (important):
- If data/movies.json is missing or corrupted, a clear error is logged
  and database_loaded() returns False so Movie Chain can be DISABLED
  instead of accepting unverified strings.

data/movies.json format (top-level JSON array):

    [
        {"title": "Sholay",    "category": "Bollywood"},
        {"title": "Inception", "category": "Hollywood"}
    ]

Plain string entries ("Sholay") and a {"movies": [...]} wrapper are also
accepted, so swapping in a much larger generated dataset later is trivial.
"""

import json
import os
import random
import re
import unicodedata

# Resolved relative to this file, so it works regardless of the CWD.
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "movies.json"
)

# The location can be overridden with an environment variable if needed.
MOVIES_JSON_PATH = os.environ.get("MOVIES_JSON_PATH", _DEFAULT_PATH)

MAX_TITLE_LENGTH = 80
MIN_TITLE_LENGTH = 2

# ═══════════════════════════════════════════════
# IN-MEMORY INDEXES (built once at startup)
# ═══════════════════════════════════════════════

_MOVIE_INDEX = {}        # normalized title -> {"title": ..., "category": ...}
_MOVIES_BY_LETTER = {}   # first letter -> number of titles available
_DB_LOADED = False


# ═══════════════════════════════════════════════
# NORMALIZATION
# ═══════════════════════════════════════════════

def normalize_movie_title(raw):
    """
    Normalize a movie title for comparison, caching and lookup keys.

    - lowercase
    - trims leading/trailing space
    - Unicode-normalized (accents flattened: "Amélie" -> "amelie")
    - punctuation/symbols collapsed into single spaces ("Spider-Man!" -> "spider man")
    - repeated spaces collapsed

    "  Sholay " -> "sholay", "SHOLAY" -> "sholay".
    Returns "" when nothing usable remains.
    """
    if raw is None:
        return ""

    text = str(raw).strip().lower()
    if not text:
        return ""

    # Normalize Unicode, then drop combining marks (accents)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))

    # Punctuation and symbols become spaces; letters/digits are kept
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _strip_trailing_year(text):
    """Turn 'Titanic 1997' into 'Titanic' so a year suffix is optional."""
    return re.sub(r"\s*\(?\b(19|20)\d{2}\b\)?\s*$", "", str(text or "")).strip()


def first_letter(title):
    """First alphabetic character of a title, lowercase."""
    for ch in str(title or ""):
        if ch.isalpha():
            return ch.lower()
    return ""


def get_last_letter(title):
    """
    Last meaningful alphabetic letter, lowercase.

    Spaces, punctuation, emoji and trailing numbers are ignored, so
    'Dangal!' -> 'l', 'Spider-Man' -> 'n', 'The Batman' -> 'n'.
    """
    for ch in reversed(str(title or "")):
        if ch.isalpha():
            return ch.lower()
    return ""


# ═══════════════════════════════════════════════
# DATABASE LOADING
# ═══════════════════════════════════════════════

def load_movie_database(path=None):
    """
    Read the JSON movie file and build the lookup indexes.

    Called once at import time. Returns True on success.

    Accepts:
      - [{"title": "X", "category": "Y"}, ...]   (preferred)
      - ["X", "Y", ...]                          (plain strings)
      - {"movies": [...]}                        (wrapped)

    Malformed entries are skipped and counted; the file is usable as
    long as at least one valid title exists.
    """
    global _DB_LOADED

    file_path = path or MOVIES_JSON_PATH

    if not os.path.isfile(file_path):
        print(f"[MovieChain] Movie database file not found: {file_path}")
        _DB_LOADED = False
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"[MovieChain] Movie database file is invalid ({file_path}): {exc}")
        _DB_LOADED = False
        return False

    entries = []
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict) and isinstance(raw.get("movies"), list):
        entries = raw["movies"]
    else:
        print(f"[MovieChain] Movie database has an unexpected structure: {file_path}")
        _DB_LOADED = False
        return False

    index = {}
    skipped = 0

    for item in entries:
        if isinstance(item, str):
            title, category = item.strip(), "Unknown"
        elif isinstance(item, dict):
            title = str(item.get("title", "") or "").strip()
            category = str(item.get("category") or "Unknown").strip() or "Unknown"
        else:
            skipped += 1
            continue

        if not title:
            skipped += 1
            continue

        key = normalize_movie_title(title)
        if not key or not any(ch.isalpha() for ch in key):
            skipped += 1
            continue

        # First occurrence wins so duplicate titles can't clobber records
        if key not in index:
            index[key] = {"title": title, "category": category}

    if not index:
        print(f"[MovieChain] Movie database contains no usable titles: {file_path}")
        _DB_LOADED = False
        return False

    _MOVIE_INDEX.clear()
    _MOVIE_INDEX.update(index)

    counts = {}
    for key in index:
        ch = first_letter(key)
        if ch:
            counts[ch] = counts.get(ch, 0) + 1
    _MOVIES_BY_LETTER.clear()
    _MOVIES_BY_LETTER.update(counts)

    _DB_LOADED = True
    print(
        f"[MovieChain] Loaded {len(index):,} movies from {file_path}"
        + (f" (skipped {skipped} malformed entries)" if skipped else "")
    )
    return True


# Load immediately when the module is imported (covers bot restarts).
load_movie_database()


# ═══════════════════════════════════════════════
# DATABASE ACCESS (O(1) lookups — the JSON is never re-scanned)
# ═══════════════════════════════════════════════

def database_loaded():
    """Whether a usable movie database is available."""
    return _DB_LOADED


def movie_count():
    """Number of titles in the offline database."""
    return len(_MOVIE_INDEX)


def movies_starting_with(letter):
    """How many database titles begin with the given letter."""
    return _MOVIES_BY_LETTER.get(str(letter or "").lower(), 0)


def get_movies_by_letter():
    """Copy of the letter -> available-titles index."""
    return dict(_MOVIES_BY_LETTER)


def lookup_movie(raw):
    """
    Exact normalized title lookup. Returns the database record
    {"title": ..., "category": ...}, or None when the title is unknown.

    NEVER fuzzy: only the normalized-title match (plus an optional
    trailing year) is accepted.
    """
    if not _DB_LOADED:
        return None

    key = normalize_movie_title(raw)
    if not key:
        return None

    record = _MOVIE_INDEX.get(key)
    if record:
        return record

    # Allow an optional trailing year: "Titanic 1997" -> "titanic"
    stripped = normalize_movie_title(_strip_trailing_year(raw))
    if stripped and stripped != key:
        return _MOVIE_INDEX.get(stripped)

    return None


# ═══════════════════════════════════════════════
# CHAIN LETTERS (driven by what the database actually contains)
# ═══════════════════════════════════════════════

def random_start_letter(minimum=5):
    """
    Pick an opening letter that genuinely has playable titles,
    so the first player is never handed a impossible letter.
    """
    pool = [c for c, n in _MOVIES_BY_LETTER.items() if n >= minimum]
    if not pool:
        pool = list(_MOVIES_BY_LETTER.keys())
    return random.choice(pool) if pool else "s"


def resolve_next_letter(title, minimum=3):
    """
    The required starting letter for the next turn.

    Normally the last meaningful letter of the accepted title. If that
    letter has almost no known movies (which would softlock the chain),
    walk backwards through the title to find a workable one.
    """
    text = str(title or "")
    letters = [ch.lower() for ch in text if ch.isalpha()]
    if not letters:
        return "a"

    for ch in reversed(letters):
        if _MOVIES_BY_LETTER.get(ch, 0) >= minimum:
            return ch

    return letters[-1]
