"""Deterministic patient-name and phone matching. No LLM, no randomness.

Design rule: matching may *widen* a candidate list (so a human or a follow-up question
resolves it) but must never *narrow* it by guessing. "Sharma" matching three people is
the correct answer; picking the one with the most similar spelling is a bug.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

# Politeness particles / titles that are not part of a name ("Sharma ji", "Mrs. Nair").
HONORIFICS = {
    "ji", "sahab", "saab", "sahib", "mr", "mrs", "ms", "miss", "shri", "shree", "sri", "smt",
    "madam", "sir", "bhai", "bhaiya", "didi", "aunty", "uncle", "mister",
}
# Spelling variants (Imran / Imraan, Qureshi / Quraishi) land around 0.8; unrelated names far below.
FUZZY_THRESHOLD = 0.78
FUZZY_MIN_LEN = 4


def name_tokens(name: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", name).casefold()
    words = re.findall(r"[^\W\d_]+", folded, flags=re.UNICODE)
    return [w for w in words if w not in HONORIFICS]


def normalise_phone(raw: str) -> Optional[str]:
    """Return the 10-digit Indian mobile number in ``raw``, or None if it is not one."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def _token_matches(query: str, candidate: str) -> int:
    """0 = no match, 2 = exact, 1 = initial or spelling variant."""
    if query == candidate:
        return 2
    if len(query) == 1 and candidate.startswith(query):
        return 1
    if len(candidate) == 1 and query.startswith(candidate):
        return 1
    if len(query) >= FUZZY_MIN_LEN and len(candidate) >= FUZZY_MIN_LEN:
        if SequenceMatcher(None, query, candidate).ratio() >= FUZZY_THRESHOLD:
            return 1
    return 0


def name_matches(query: str, patient_name: str) -> bool:
    """True if every token of ``query`` matches a distinct token of ``patient_name``."""
    query_tokens = name_tokens(query)
    if not query_tokens:
        return False
    available = name_tokens(patient_name)
    for token in sorted(query_tokens, key=len, reverse=True):  # longest first: stable & greedy-safe
        best_index, best_score = -1, 0
        for index, candidate in enumerate(available):
            score = _token_matches(token, candidate)
            if score > best_score:
                best_index, best_score = index, score
        if best_index < 0:
            return False
        available.pop(best_index)
    return True
