"""Cache Qualification Layer — post-match validation before serving cached responses.

Ensures cached answers are appropriate for the current request context.
This is a purely additive gate that sits between cache lookup and cache serve.
It never modifies the cache — it only decides whether a hit should be served or skipped.

Primary check: context-dependent query detection. Queries like "tell me more",
"what's next", or short follow-ups with conversation history should not be served
from cache — they need the LLM to see the full conversation context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context-Dependent Query Detection
# ---------------------------------------------------------------------------

# Phrases that indicate the query depends on conversation history.
# These should NOT be served from cache without matching conversation context.
_CONTEXT_DEPENDENT_PATTERNS = re.compile(
    r"\b("
    # Anaphoric references (pointing back to prior context)
    r"what about that|tell me more|explain that|go deeper|elaborate on that"
    r"|more about that|what do you mean|can you clarify"
    r"|what did you mean|why is that|how so|in what way"
    # Continuation / sequencing
    r"|what\'?s next|what else|anything else|go on|continue"
    r"|what about the other|the next one|the previous one"
    r"|and the second|and the third|the last one"
    # Pronoun-heavy queries that need antecedent resolution
    r"|what is it|what are they|who are they|where is it"
    r"|how does it work|why does it matter|is it true"
    r"|do that again|try that again|repeat that"
    r"|the same thing|like before|as you said|you mentioned"
    r"|you just said|earlier you said|back to that"
    # Conversational commands
    r"|yes|no|ok|sure|right|exactly|correct|wrong"
    r"|summarize this|summarize that|put it together"
    r")\b",
    re.IGNORECASE,
)

# Words that carry no subject of their own. A query built only from these is
# asking for more about the previous answer, not asking about a new topic.
# Shared with session.resolve_against_history, which refuses to rewrite a query
# that contributes nothing but these.
ELABORATION_WORDS = frozenset(
    [
        "tell",
        "me",
        "more",
        "please",
        "again",
        "else",
        "next",
        "mean",
        "meant",
        "clarify",
        "explain",
        "elaborate",
        "deeper",
        "summarize",
        "summarise",
        "repeat",
        "continue",
        "said",
        "say",
        "just",
        "yes",
        "no",
        "ok",
        "okay",
        "sure",
        "right",
        "exactly",
        "correct",
        "wrong",
        "thing",
        "things",
        "same",
        "like",
        "before",
        "earlier",
        "back",
        "go",
        "on",
        "put",
        "together",
        "one",
        "ones",
        "second",
        "third",
        "last",
        "previous",
        "other",
        "another",
        "you",
        "your",
        "we",
        "us",
        "topic",
        "about",
    ]
)

# How much subject a query must carry before it stands on its own.
#
# Raw word count cannot make this call. "can you tell me more about that topic?"
# is 8 words and entirely context-dependent; "Does that policy cover
# international shipping for enterprise customers?" is 9 and entirely
# self-contained. Length is inverted between them.
#
# Counting words that are neither stopwords nor elaboration markers separates
# them cleanly — the first has 0, the second has 6. Across the phrases these
# rules were built from, context-dependent queries top out at 2 substantive
# words and self-contained ones start at 5. The bound sits in that gap.
MAX_SUBSTANTIVE_WORDS = 3

# Short queries with pronouns are almost always context-dependent
_SHORT_PRONOUN_RE = re.compile(
    r"^(what|where|when|who|how|why|is|are|do|does|did|can|will|would)\s+"
    r"(it|that|this|they|them|those|these|he|she|his|her)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Qualification Result
# ---------------------------------------------------------------------------


@dataclass
class QualificationResult:
    """Result of cache qualification check."""

    serve: bool = True
    reason: str = ""
    check: str = ""  # which check triggered the skip

    def to_dict(self) -> dict:
        return {"serve": self.serve, "reason": self.reason, "check": self.check}


# ---------------------------------------------------------------------------
# Individual Checks
# ---------------------------------------------------------------------------


def substantive_words(query: str) -> list[str]:
    """Words in a query that name a subject, rather than point at one.

    Drops stopwords and elaboration markers. What remains is what the query
    contributes on its own, independent of any previous turn.
    """
    from bitmod.cache_engine import STOPWORDS

    tokens = "".join(c if c.isalnum() or c.isspace() else " " for c in query.lower()).split()
    return [t for t in tokens if t not in STOPWORDS and t not in ELABORATION_WORDS]


def is_context_dependent(query: str, history: list | None = None) -> bool:
    """Detect if a query depends on conversation history to be meaningful."""
    q = query.strip()
    word_count = len(q.split())

    # Very short queries with history are almost always context-dependent
    if history and len(history) > 0 and word_count <= 3:
        return True

    # Anaphora only makes a query context-dependent while the query carries too
    # little subject of its own to be matched directly:
    #
    #   "how does it work"                                     -> dependent
    #   "how does it work when a customer disputes a charge?"   -> standalone
    #
    # Both open with the same anaphoric phrase; only the first needs the previous
    # turn to mean anything. Applied to the pattern list and the pronoun rule
    # alike, since either can match a long specific question.
    if len(substantive_words(q)) > MAX_SUBSTANTIVE_WORDS:
        return False

    # Pattern-based detection
    if _CONTEXT_DEPENDENT_PATTERNS.search(q):
        return True

    # Short queries starting with pronoun references
    if _SHORT_PRONOUN_RE.match(q):
        return True

    return False


# ---------------------------------------------------------------------------
# Main Qualification Gate
# ---------------------------------------------------------------------------


def qualify_cache_hit(
    query: str,
    cached_answer: str,
    history: list | None = None,
    **kwargs,
) -> QualificationResult:
    """Run qualification checks on a cache hit. Returns whether to serve it.

    This function is fast (no I/O, no LLM calls, pure regex + string checks)
    and should be called after a cache hit is found but before serving.

    Args:
        query: The user's current query.
        cached_answer: The cached answer text.
        history: Conversation history (list of message objects).

    Returns:
        QualificationResult with serve=True if the hit should be served,
        or serve=False with a reason explaining why it was skipped.
    """
    if is_context_dependent(query, history):
        return QualificationResult(
            serve=False,
            reason="Query appears context-dependent (requires conversation history)",
            check="context_dependent",
        )

    return QualificationResult(serve=True)
