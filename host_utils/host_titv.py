import re
from html import unescape
from typing import Tuple

import feedparser

from novel_mappings import HOSTING_SITE_DATA

# ===============================================================
# Tales in the Valley (free feed) host utils
# ---------------------------------------------------------------
# This module extracts:
#   - main_title      -> prefer the feed's first series category (e.g.,
#                        "[Transmigration] Everyday Life of a Cannon Fodder in a Wealthy Family")
#                        via a small feedparser patch that prefixes it to the item title so we
#                        don't have to touch your generator.
#   - chaptername     -> canonicalized as "Chapter N" or "Chapter Extra N"
#   - nameextend      -> looked up from CHAPTER_SUBTITLES for ATVHE (1..130)
#   - volume          -> always "" (TitV doesn't expose one in the RSS)
#   - clean_description -> pass-through light cleanup (generator will prefer
#                          `custom_description` from novel_mappings when set)
#   - chapter_num     -> numeric sort helper (same behavior as other hosts)
#
# Important mapping requirement:
#   In `novel_mappings.HOSTING_SITE_DATA["Tales in the Valley"]["novels"]`, make sure
#   the DICT KEY (novel title) matches what you want to emit as <title> in your
#   aggregated feed, e.g. "After Transmigrating into the Villain, I Got a HE with the Female Lead’s Older Brother".
#   We still read `short_code` for ATVHE subtitle mapping, but we now *prefer* the
#   feed's own series category for the emitted <title>.
# ===============================================================

# --- Build shortcode -> full title map from your mapping (case-insensitive)

def _build_code_map() -> dict:
    out = {}
    titv = HOSTING_SITE_DATA.get("Tales in the Valley", {})
    for novel_title, details in titv.get("novels", {}).items():
        code = (details.get("short_code") or "").strip()
        if code:
            out[code.upper()] = novel_title
    return out

CODE_TO_TITLE = _build_code_map()

# ---------------------------------------------------------------
# Feedparser patch: when parsing TitV's feed, prefix the first *series* category
# to the entry title:  "<Series> – <original title>".
# This lets split_title_titv pull the series from the left side without changing
# your generator.
# ---------------------------------------------------------------

def _pick_series_category(entry) -> str:
    try:
        tags = getattr(entry, "tags", []) or []
        # Prefer the first non-generic category
        GENERIC = {"Danmei", "Comedy"}
        for t in tags:
            term = (getattr(t, "term", "") or str(t)).strip()
            if term and term not in GENERIC:
                return term
        # fallback: longest term
        longest = max((getattr(t, "term", "") or str(t)).strip() for t in tags) if tags else ""
        return longest
    except Exception:
        return ""

if not getattr(feedparser, "_titv_series_prefix_installed", False):
    _orig_parse = feedparser.parse

    def _parse_and_prefix(url, *args, **kwargs):
        feed = _orig_parse(url, *args, **kwargs)
        try:
            if isinstance(url, str) and "talesinthevalley.com" in url:
                for e in getattr(feed, "entries", []):
                    series = _pick_series_category(e)
                    if series:
                        # Avoid duplicating if already prefixed
                        if not str(getattr(e, "title", "")).startswith(series):
                            e.title = f"{series} – {getattr(e, 'title', '')}"
        except Exception:
            pass
        return feed

    feedparser.parse = _parse_and_prefix
    feedparser._titv_series_prefix_installed = True

# --- Chapter subtitle mapping for: "After Transmigrating into the Villain, I Got a HE with the Female Lead’s Older Brother"
# Provided by user (1..130). Used *only* when the shortcode matches this series.
CHAPTER_SUBTITLES = {
    1: "Why Is It the Heroine’s Brother?!",
    2: "I Like Your Sister!",
    3: "Song Wan Ran Away",
    4: "Here to Catch You",
    5: "Won’t Run Anymore",
    6: "Call Me Brother",
    7: "Am I in the Closet?",
    8: "Put It Here",
    9: "This Good-for-Nothing Kid",
    10: "Accident",
    11: "This Life Is Too Short",
    12: "It Suits You Well",
    13: "You Didn’t Do This for Song Wan, Did You",
    14: "Discovered a Conspiracy",
    15: "Scandalous",
    16: "Crisis",
    17: "The Difference Between People",
    18: "Didn’t Say Whether It’s a Man or a Woman",
    19: "Fate Too Shallow",
    20: "Dream a Little Longer",
    21: "Unlucky Third Wheel",
    22: "I Don’t Marry Women",
    23: "Black-Hearted Sesame Dumpling",
    24: "The Brother Who’s Helped Me Many Times",
    25: "Engagement Banquet",
    26: "The Same Piece of Obsidian",
    27: "Scented Sachet",
    28: "I Have a Friend",
    29: "You Wrap Up Too",
    30: "How Should I Repay You",
    31: "The Person on the Phone",
    32: "The Runaway Horse",
    33: "I Am the Witness",
    34: "You Think Those Two Have Done It?",
    35: "Business Trip",
    36: "Flip Phone",
    37: "Like Having an Affair",
    38: "Negative Public Opinion",
    39: "Turn the Tables, Leave a Way Out for the Enemy",
    40: "Peace Talk",
    41: "Happy Birthday",
    42: "The Boomerang Hit Back",
    43: "Be Good",
    44: "Brought You Something Nice",
    45: "Why Does Young Master Always Get Sick",
    46: "He’s Not Going to Date a Girl, Right",
    47: "I’m Willing",
    48: "Impossible to Ignore",
    49: "Why Didn’t You Refuse",
    50: "Saying No but Meaning Yes",
    51: "Won’t Mistake You",
    52: "I Like Men",
    53: "The Little Fox Can’t Outplay the Old One",
    54: "And You? Do You Like Boys or Girls",
    55: "The One in His Heart",
    56: "Betrayal and Danger",
    57: "You’re Very Brave",
    58: "Cross-Server Chat",
    59: "Black-Hearted Host",
    60: "Steadfast Love",
    61: "Fury",
    62: "Didn’t Misjudge You",
    63: "Caught You",
    64: "So Useless",
    65: "He Bit Me",
    66: "To Ask or Not to Ask",
    67: "Let’s Watch the Fireworks Together",
    68: "You Want to Top Gu Jinzhou?",
    69: "That’s What Kissing Means",
    70: "He Did It on Purpose",
    71: "Once You Come, You Can’t Leave",
    72: "You Rich People Are All About Appearances",
    73: "Looks Like We Really Got Married",
    74: "Awkward Lines",
    75: "Infinite Save-Load Countdown",
    76: "Did He Lose Someone Very Important",
    77: "Called the Wrong Name—Say It Again",
    78: "Your little mouth is quite sweet",
    79: "I’m Right Here",
    80: "Can’t Smile Anymore",
    81: "This Kind Is the Easiest to Soothe",
    82: "Can We Do Something Else",
    83: "Got Tricked",
    84: "Why",
    85: "Watching Stars with You",
    86: "You Look Good",
    87: "Invitation to Alton Manor",
    88: "So You’re the One President Gu Fancies",
    89: "Run!",
    90: "A Blessing in Disguise",
    91: "The Thousand Eyes of a Lover",
    92: "Where Did You Touch",
    93: "Living Together",
    94: "What a Life Saver",
    95: "Don’t Take It Out",
    96: "Sent Back to School",
    97: "Embarrassed",
    98: "Give Me a Title",
    99: "When Will You Clarify the Rumors",
    100: "Every Cut Fatal",
    101: "You’re Getting Your House Robbed!",
    102: "He’s Mine",
    103: "Are You Two for Real",
    104: "What Did Psyduck Ever Do to You",
    105: "Hit the Snake at Seven Inches",
    106: "I’ll Be Your Pawn",
    107: "Whoever Gives the Bride Price Gives the Dowry",
    108: "Don’t Worry",
    109: "What Else Can’t You Let Go Of",
    110: "Happiness, This Thing",
    111: "Ran Away",
    112: "Repeating the Same Mistake",
    113: "No Use Crying Over Spilt Water",
    114: "Let’s Go Home",
    115: "Daylight Breaks",
    116: "What Do You Want to Raise",
    117: "Sitting on Your Pinned Chat’s Lap and Kissing You for a Minute in Public",
    118: "A Moment of Silence for My Purity",
    119: "Happy Birthday to Both of Us",
    120: "With a Box",
    121: "The Best Gift",
    122: "Wishing You Early Children and Happiness",
    123: "Will You Dance with Me",
    124: "These Aren’t Couple Rings",
    125: "I’ll Accompany You to the End",
    126: "Envy",
    127: "Still Calling Him Boyfriend?",
    128: "Remember Now?",
    129: "The Past",
    130: "You Suit Me Too",
}

CHAPTER_RE = re.compile(r"(?i)\bchapter\s*(extra)?\s*(\d+(?:\.\d+)?)")


def _canonize_chapter(label: str) -> Tuple[str, int | None, bool]:
    """Return (canonical_label, chapter_number_or_None, is_extra)."""
    s = unescape(label or "").strip()
    m = CHAPTER_RE.search(s)
    if not m:
        return s, None, False
    is_extra = bool(m.group(1))
    num_txt = m.group(2)
    # decimals like 12.5 are supported for sorting but we only subtitle pure ints
    try:
        n_int = int(float(num_txt)) if "." in num_txt else int(num_txt)
    except ValueError:
        n_int = None
    canon = f"Chapter {'Extra ' if is_extra else ''}{num_txt}"
    return canon, n_int, is_extra


def _nameextend_for(series_title: str, chapter_num_int: int | None, is_extra: bool) -> str:
    if is_extra or chapter_num_int is None:
        return ""  # only map main chapters
    # Only the ATVHE series has subtitles defined here; gate by mapping key presence
    # (safer than checking shortcode again).
    titv = HOSTING_SITE_DATA.get("Tales in the Valley", {})
    novels = titv.get("novels", {})
    if series_title not in novels:
        return ""
    return CHAPTER_SUBTITLES.get(chapter_num_int, "")


# ---------------------------------------------------------------
# Public helpers expected by free_feed_generator
# ---------------------------------------------------------------

def split_title_titv(full_title: str):
    """
    Accepts raw item.title from TitV and returns (main_title, chaptername, nameextend).

    TitV patterns seen:
      1) "ATVHE | Chapter 12"          (shortcode | chapter)
      2) "ATDIBTTS – Chapter 56 (...)" (long title – chapter)  [other series]
      3) Fallbacks that contain the word "Chapter" somewhere.
    """
    s = unescape((full_title or "").strip())

    # Pattern 1: CODE | Chapter ...
    m = re.match(r"^\s*([A-Za-z0-9]+)\s*\|\s*(.+)$", s)
    if m:
        code = m.group(1).upper()
        rhs = m.group(2).strip()
        main_title = CODE_TO_TITLE.get(code, code)  # if code not mapped, it will be skipped later
        chap_label, chap_n, is_extra = _canonize_chapter(rhs)
        nameext = _nameextend_for(main_title, chap_n, is_extra)
        return main_title, chap_label, nameext

    # Pattern 2: Long title – Chapter ... (em dash / en dash / hyphen)
    m = re.match(r"^\s*([^–—-]+?)\s*[–—-]\s*(.+)$", s)
    if m:
        main_title = m.group(1).strip()
        rhs = m.group(2).strip()
        chap_label, chap_n, is_extra = _canonize_chapter(rhs)
        nameext = _nameextend_for(main_title, chap_n, is_extra)
        return main_title, chap_label, nameext

    # Pattern 3: Anything with a Chapter token
    if "chapter" in s.lower():
        chap_label, chap_n, is_extra = _canonize_chapter(s)
        # When no series detected, use the raw head before "Chapter" as a heuristic
        head = s.split("Chapter", 1)[0].strip(" -—–|\u00a0")
        main_title = head or s
        nameext = _nameextend_for(main_title, chap_n, is_extra)
        return main_title, chap_label, nameext

    # Last resort: treat entire title as the series, no chapter
    return s, "", ""


def extract_volume_titv(_full_title: str, _link: str) -> str:
    # TitV doesn't surface a volume in RSS; keep it empty.
    return ""


def clean_description_titv(raw_desc: str) -> str:
    # Keep CDATA content mostly as-is, just trim outer whitespace and collapse
    # gratuitous runs of whitespace.
    if not raw_desc:
        return ""
    s = unescape(raw_desc)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def chapter_num(chaptername: str):
    s = (chaptername or '').lower()

    # Extras → very large rank so they come after normal chapters
    m = re.search(r'chapter\s+extra\s+(\d+)', s)
    if not m:
        m = re.search(r'\bextra\s+(\d+)', s)
    if m:
        return (10**9, int(m.group(1)))  # extras at the end

    # Normal numeric (supports decimals like 12.5)
    nums = re.findall(r"\d+(?:\.\d+)?", chaptername)
    if not nums:
        return (0,)
    out = []
    for n in nums:
        out.append(float(n) if "." in n else int(n))
    return tuple(out)


# The exported dispatch dict (mirrors the shape used in other host utils)
TALES_IN_THE_VALLEY_UTILS = {
    "split_title": split_title_titv,
    "extract_volume": extract_volume_titv,
    "clean_description": clean_description_titv,
    "chapter_num": chapter_num,
}


