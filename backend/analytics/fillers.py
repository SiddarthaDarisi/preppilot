"""Filler-word detection over transcripts. Pure stdlib.

Heuristics (documented, intentionally simple):

* Hesitation sounds ``um/uh/er/ah/hmm`` match with elongations (umm, uhh,
  hmmm) on word boundaries.
* Phrase fillers: ``you know``, ``sort of``, ``kind of``, ``i mean``.
* ``basically`` and ``actually`` always count (they are overwhelmingly
  verbal padding in interview answers).
* ``so`` counts only when sentence-initial (start of text or right after
  ``.``/``!``/``?``).
* ``right`` counts only as a trailing question tag (``right?``).
* ``like`` counts only when NOT preceded by a comparison/verb cue word
  (forms of feel/look/sound/seem/be, plus would/'d/just/much/more/
  something/anything/nothing) — so "I feel like it's fine" and
  "it looks like rain" do not count, while "it was, like, hard" does.
"""
from __future__ import annotations

import re

# Regex-driven patterns (name -> compiled pattern). "like" is handled
# separately because Python's re does not allow variable-width lookbehind.
FILLER_PATTERNS: dict[str, re.Pattern[str]] = {
    "um": re.compile(r"\bum+\b", re.IGNORECASE),
    "uh": re.compile(r"\buh+\b", re.IGNORECASE),
    "er": re.compile(r"\ber+\b", re.IGNORECASE),
    "ah": re.compile(r"\bah+\b", re.IGNORECASE),
    "hmm": re.compile(r"\bhm+\b", re.IGNORECASE),
    "you know": re.compile(r"\byou\s+know\b", re.IGNORECASE),
    "sort of": re.compile(r"\bsort\s+of\b", re.IGNORECASE),
    "kind of": re.compile(r"\bkind\s+of\b", re.IGNORECASE),
    "i mean": re.compile(r"\bi\s+mean\b", re.IGNORECASE),
    "basically": re.compile(r"\bbasically\b", re.IGNORECASE),
    "actually": re.compile(r"\bactually\b", re.IGNORECASE),
    # sentence-initial "so": start of text/line or right after . ! ?
    "so": re.compile(r"(?:(?<=[.!?])\s*|^\s*)so\b", re.IGNORECASE | re.MULTILINE),
    # trailing "right?" tag
    "right": re.compile(r"\bright\s*\?", re.IGNORECASE),
}

# Words that, when immediately preceding "like", mark a legitimate
# (non-filler) use: perception verbs, copulas, and comparators.
_LIKE_EXCLUDE_BEFORE: frozenset[str] = frozenset(
    {
        "feel", "feels", "felt", "feeling",
        "look", "looks", "looked", "looking",
        "sound", "sounds", "sounded", "sounding",
        "seem", "seems", "seemed",
        "is", "was", "are", "were", "am", "be", "been", "being",
        "it's", "that's", "he's", "she's", "there's", "what's",
        "would", "'d", "d",
        "just", "much", "more", "something", "anything", "nothing",
    }
)

_WORD_RE = re.compile(r"[a-z']+")


def _count_filler_like(text: str) -> int:
    """Count 'like' occurrences whose preceding word is not an exclusion cue."""
    tokens = _WORD_RE.findall(text.lower())
    count = 0
    for i, token in enumerate(tokens):
        if token != "like":
            continue
        prev = tokens[i - 1] if i > 0 else ""
        if prev not in _LIKE_EXCLUDE_BEFORE:
            count += 1
    return count


def count_fillers(text: str) -> tuple[int, dict[str, int]]:
    """Case-insensitive filler counting; returns (total, per-filler breakdown).

    Breakdown only contains entries with a count > 0.
    """
    breakdown: dict[str, int] = {}
    if not text:
        return 0, breakdown
    for name, pattern in FILLER_PATTERNS.items():
        n = len(pattern.findall(text))
        if n:
            breakdown[name] = n
    like_count = _count_filler_like(text)
    if like_count:
        breakdown["like"] = like_count
    return sum(breakdown.values()), breakdown
