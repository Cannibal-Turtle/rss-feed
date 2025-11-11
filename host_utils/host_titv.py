import re
from html import unescape
from typing import Tuple

import feedparser
from novel_mappings import HOSTING_SITE_DATA

# ===============================================================
# Tales in the Valley (free feed) host utils — multi-series
# ===============================================================

# 1) Build shortcode -> full title map from your mapping (case-insensitive)
def _build_code_map() -> dict:
    out = {}
    titv = HOSTING_SITE_DATA.get("Tales in the Valley", {})
    for novel_title, details in titv.get("novels", {}).items():
        code = (details.get("short_code") or "").strip()
        if code:
            out[code.lower()] = novel_title
    return out

CODE_TO_TITLE = _build_code_map()

# 2) Optional per-series subtitles.
#    Add more series by shortcode key, e.g., "rsg": {1: "The End"}
CHAPTER_SUBTITLES = {
    "atvhe": {
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
        78: "Your Mouth’s Quite Sweet",
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
    },
}

# Optional subtitles for extras/side stories
EXTRA_SUBTITLES = {
    # example:
    # "rsg": {1: "The End"}
}

# Optional per-series canonicalization of <chaptername> wording:
#   "feed"   → keep whatever the feed says (default)
#   "chapter"→ force "Chapter N" / "Chapter Extra N"
SERIES_CANON = {
    # "rsg": "chapter",
    # "atvhe": "feed",
}

# 3) Feedparser patch: prefix first series category to title so split stays consistent
def _pick_series_category(entry) -> str:
    try:
        tags = getattr(entry, "tags", []) or []
        GENERIC = {"Danmei", "Comedy"}
        for t in tags:
            term = (getattr(t, "term", "") or str(t)).strip()
            if term and term not in GENERIC:
                return term
        # fallback: longest term
        return max(((getattr(t, "term", "") or str(t)).strip() for t in tags), key=len, default="")
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
                        title_now = str(getattr(e, "title", "") or "")
                        # guard against duplicates regardless of dash character
                        if not re.match(rf'^{re.escape(series)}\s*[–-]\s*', title_now):
                            e.title = f"{series} – {title_now}"
        except Exception:
            pass
        return feed
    feedparser.parse = _parse_and_prefix
    feedparser._titv_series_prefix_installed = True

# 4) Parsing helpers
DASH_RE = re.compile(r'[\u2010-\u2015\u2212\-]+')
LABEL_PATTERNS = [
    (re.compile(r'(?i)\bchapter\s+extra\s+(\d+(?:\.\d+)?)'), 'extra'),
    (re.compile(r'(?i)\bextra\s+(\d+(?:\.\d+)?)'),           'extra'),
    (re.compile(r'(?i)\bside\s*story\s*[:\- ]*(\d+(?:\.\d+)?)'), 'extra'),
    (re.compile(r'(?i)\bss\s*[:\- ]*(\d+(?:\.\d+)?)'),       'extra'),
    (re.compile(r'(?i)\bchapter\s+(\d+(?:\.\d+)?)'),         'main'),
    (re.compile(r'(?i)\bch(?:apter)?\s+(\d+(?:\.\d+)?)'),    'main'),
]

def _canonize_chaptername(short_code: str, kind: str, chapnum_txt: str, original_label: str) -> str:
    """Keep feed wording unless SERIES_CANON says to force 'Chapter' wording."""
    mode = SERIES_CANON.get(short_code, "feed")
    if mode == "chapter" and chapnum_txt:
        return f"Chapter {'Extra ' if kind == 'extra' else ''}{chapnum_txt}"
    # default: preserve feed’s wording (normalized whitespace)
    return " ".join(original_label.split())

def split_title_titv(full_title: str) -> Tuple[str, str, str]:
    """
    Returns (main_title, chaptername, nameextend).
      main_title: series (from category prefix) or shortcode→title fallback
      chaptername: either preserved from feed or forced to 'Chapter...' per SERIES_CANON
      nameextend: subtitle from CHAPTER_SUBTITLES/EXTRA_SUBTITLES when available
    """
    s = (full_title or "").strip()
    s = DASH_RE.sub(" – ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    # "Series – rest" if present
    main_title, rest = (s.split(" – ", 1) + [""])[:2] if " – " in s else ("", s)

    # Shortcode at start of 'rest' (separator optional)
    m_code = re.match(r'^\s*([A-Z0-9]{2,})\b(?:\s*[|–-]\s*)?', rest)
    short_code = (m_code.group(1).lower() if m_code else "")

    # Find first recognizable chapter label
    chaptername, chapnum_txt, kind = "", None, None
    for pat, k in LABEL_PATTERNS:
        m = pat.search(rest)
        if m:
            chapnum_txt = m.group(1)
            kind = k
            chaptername = _canonize_chaptername(short_code, kind, chapnum_txt, m.group(0))
            break

    # Subtitle lookup (main vs extra), only if integer N
    nameextend = ""
    if chapnum_txt and chapnum_txt.isdigit():
        n = int(chapnum_txt)
        if kind == "main":
            nameextend = CHAPTER_SUBTITLES.get(short_code, {}).get(n, "")
        elif kind == "extra":
            nameextend = EXTRA_SUBTITLES.get(short_code, {}).get(n, "")

    # Fallback for series title via shortcode mapping
    if not main_title and short_code in CODE_TO_TITLE:
        main_title = CODE_TO_TITLE[short_code]

    return main_title.strip(), chaptername.strip(), nameextend.strip()

def extract_volume_titv(_full_title: str, _link: str) -> str:
    return ""  # TitV RSS exposes no volume

def clean_description_titv(raw_desc: str) -> str:
    if not raw_desc:
        return ""
    s = unescape(raw_desc)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def chapter_num(chaptername: str):
    s = (chaptername or '').lower()
    # Put extras/side stories after normal chapters
    m = (re.search(r'\bchapter\s+extra\s+(\d+)', s) or
         re.search(r'\bextra\s+(\d+)', s) or
         re.search(r'\bside\s*story\s*[:\- ]*(\d+)', s) or
         re.search(r'\bss\s*[:\- ]*(\d+)', s) or
         re.search(r'\bgaiden\s+(\d+)', s) or
         re.search(r'\bspecial\s+(\d+)', s))
    if m:
        return (10**9, int(m.group(1)))

    nums = re.findall(r"\d+(?:\.\d+)?", chaptername)
    if not nums:
        return (0,)
    out = [float(n) if "." in n else int(n) for n in nums]
    return tuple(out)

async def scrape_paid_chapters_async(session, novel_url, host):
    return [], ""  # no paid items yet

TALES_IN_THE_VALLEY_UTILS = {
    "split_title": split_title_titv,
    "extract_volume": extract_volume_titv,
    "clean_description": clean_description_titv,
    "chapter_num": chapter_num,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,
}
