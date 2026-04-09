"""Single source of truth for title normalization.

This is the only title normalizer in the entire WikiMind codebase. Any
code that needs to compare article titles — the wikilink resolver, the
knowledge graph builder, future search features — MUST import
``normalize_title`` from this module. Do NOT add a second normalizer
anywhere else. Doing so will reintroduce the slug-divergence bug tracked
in issue #96.

The algorithm is intentionally simple:
    1. Unicode NFKD decomposition + ASCII strip (so "Café" → "Cafe").
    2. Lowercase.
    3. Strip apostrophes entirely, so "it's" → "its" (not "it-s").
       Both ASCII and Unicode right single quotation mark (U+2019).
    4. Replace every run of non-alphanumeric characters (except hyphens)
       with a single hyphen. Underscores count as non-alphanumeric.
    5. Strip leading and trailing hyphens.
    6. Collapse consecutive hyphens to one.

The output is suitable for exact-match comparison: two strings produce
the same output iff they normalize to the same canonical form.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM_HYPHEN = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN = re.compile(r"-{2,}")


def normalize_title(s: str) -> str:
    """Canonicalize a title for wikilink resolution.

    Args:
        s: Raw title string. May be empty, contain unicode, contain
           punctuation, contain mixed whitespace.

    Returns:
        A lowercase ASCII string containing only ``[a-z0-9-]``. Empty
        input yields an empty string.
    """
    # 1. Unicode → ASCII (NFKD normalizes U+2019 to ASCII "'" along with
    #    other compatibility characters; the apostrophe strip in step 3
    #    then removes it).
    ascii_form = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # 2. Lowercase
    lower = ascii_form.lower()
    # 3. Strip apostrophes before hyphenation so "Karpathy's" → "karpathys",
    #    not "karpathy-s". Matches the documented contract in the unit tests.
    no_apostrophes = lower.replace("'", "")
    # 4. Replace runs of non-alnum-non-hyphen with a single hyphen
    hyphenated = _NON_ALNUM_HYPHEN.sub("-", no_apostrophes)
    # 5. Strip leading/trailing hyphens
    stripped = hyphenated.strip("-")
    # 6. Collapse consecutive hyphens
    return _MULTI_HYPHEN.sub("-", stripped)
