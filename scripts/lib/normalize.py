"""Title normalization contract (IMPLEMENTATION_GUIDE section 3.1).

Used for both netflix.titles.title_norm and imdb.title_names.name_norm.
An empty result is allowed but must never be used as a join key.
"""
import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_title(s):
    if s is None or s != s:  # None or NaN
        return ""
    # 1. NFKD, then drop combining marks (every Unicode category M*, so that
    #    spacing vowel signs in e.g. Devanagari do not split a word in step 4).
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))
    # 2. Casefold.
    s = s.casefold()
    # 3. '&' -> ' and '.
    s = s.replace("&", " and ")
    # 4. Anything that is not a Unicode letter or decimal digit -> space.
    s = "".join(ch if ch.isalpha() or ch.isdecimal() else " " for ch in s)
    # 5. Collapse whitespace and strip.
    return _WS.sub(" ", s).strip()
