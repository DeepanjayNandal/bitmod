"""Refuse a cached answer when the two questions name different things.

Embedding similarity measures whether two sentences are alike. It does not
measure whether they are about the same subject, and for a cache those come
apart in a specific way: two questions built from the same template with one
name swapped score as near-identical, because they are near-identical.

Measured on 500 labelled pairs, these were served from cache:

    "What universities does Sigma-Aldrich recruit new grads from?"
        answered with Sigma Designs

    "Why is saltwater taffy candy imported in Austria?"
        answered with the answer about China

    "Refund policy for US customers" / "for EU customers"
        the case the product's own pitch opens with, and there was no
        mechanism for it

No threshold or verification layer can catch this. They all act on a
confidence number that is already computed, and the number is high correctly.
The only thing that separates these questions is that they name different
things, so that is what this checks.

A veto, not a vote. It cannot raise confidence, only refuse — which is what
makes it safe to apply after the layers have spoken.

WHAT IT DOES NOT CATCH
    Measured against 130 hand-classified serves, this addresses one of three
    classes of wrong serve and about a sixth of them by count. The largest
    class shares every entity and the same question shape while asking
    something different — "Will there be a war between India and Pakistan?"
    answered with "who will win?" — and nothing rule-based separates those.
    See BACKLOG for the breakdown.
"""

from __future__ import annotations

import re

# Two or more capitals, so "US", "EU", "GST", "WW3" survive but "How" does not.
_ACRONYM = re.compile(r"\b[A-Z]{2,}[0-9]*\b")
_NUMBER = re.compile(r"\b\d[\d,]*\b")
# A capitalised word, optionally hyphenated or followed by more capitalised
# words: "Trump", "Sigma-Aldrich", "World War".
_PROPER = re.compile(r"\b[A-Z][a-z]+(?:[-‑][A-Z][a-z]+)*(?:\s+[A-Z][a-z]+)*\b")

# Capitalised because they open a sentence or a question, not because they name
# anything. Without this every question contributes its first word.
_SENTENCE_OPENERS = frozenset(
    {
        "how",
        "what",
        "why",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "whom",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "can",
        "could",
        "will",
        "would",
        "should",
        "may",
        "might",
        "shall",
        "the",
        "a",
        "an",
        "i",
        "if",
        "in",
        "on",
        "it",
        "this",
        "that",
        "there",
        "any",
        "my",
        "your",
        "some",
    }
)

_ROMAN = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}


def _canonical(token: str) -> str:
    """Fold spellings of the same thing together.

    Roman numerals become digits so "World War 3" and "world war III" name one
    war, and thousands separators go so "60,000" and "60000" are one number.
    """
    cleaned = token.strip().lower().replace(",", "")
    return _ROMAN.get(cleaned, cleaned)


def extract(text: str) -> set[str]:
    """Names, acronyms and numbers — what makes two similar questions different."""
    found: set[str] = set()
    for match in _ACRONYM.finditer(text):
        found.add(_canonical(match.group()))
    for match in _NUMBER.finditer(text):
        found.add(_canonical(match.group()))
    for match in _PROPER.finditer(text):
        words = [w for w in match.group().split() if w.lower() not in _SENTENCE_OPENERS]
        if words:
            found.add(_canonical(" ".join(words)))
    return {e for e in found if e}


def _absorbed(entity: str, others: set[str]) -> bool:
    """Whether some other entity names the same thing more or less fully.

    "Trump" against "Donald Trump" is one person written two ways, not two
    people. Token containment rather than substring, so "Austria" is not
    absorbed by "Australia".
    """
    tokens = set(entity.split())
    for other in others:
        other_tokens = set(other.split())
        if tokens <= other_tokens or other_tokens <= tokens:
            return True
    return False


def conflicts(question: str, candidate: str) -> bool:
    """True when each question names something the other does not.

    Both sides must name something distinct. One-sided extras are additional
    detail, not disagreement: "best gaming laptop under 60k INR" against "best
    gaming laptop under Rs 60000" differ in what was written down, and refusing
    on that would cost recall for nothing.
    """
    left, right = extract(question), extract(candidate)
    if not left or not right:
        return False
    unmatched_left = {e for e in left if not _absorbed(e, right)}
    unmatched_right = {e for e in right if not _absorbed(e, left)}
    return bool(unmatched_left) and bool(unmatched_right)
