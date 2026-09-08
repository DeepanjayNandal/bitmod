"""Session-aware caching (Layer 7).

Tracks conversation sessions in-memory to provide contextual evidence
when a query is a follow-up in an existing session.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class SessionState:
    """Tracks a single conversation session's history."""

    session_id: str
    queries: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    cache_keys: list[str] = field(default_factory=list)

    @property
    def turn_count(self) -> int:
        return len(self.queries)

    def record(self, query: str, answer: str, cache_key: str) -> None:
        self.queries.append(query)
        self.answers.append(answer)
        self.cache_keys.append(cache_key)

    def last_exchange_context(self) -> str | None:
        """Format the most recent Q&A as supplementary context."""
        if not self.queries:
            return None
        return f"Previous Q: {self.queries[-1]}\nPrevious A: {self.answers[-1]}"


def resolve_against_history(query: str, state: SessionState) -> str | None:
    """Rewrite a context-dependent follow-up into a query that stands alone.

    Grafts the topic of the previous turn onto whatever new subject the current
    query introduces::

        previous: "what is the refund policy"
        current:  "what about electronics?"
        result:   "refund policy electronics"

    Returns ``None`` when no rewrite is possible, which is the common case and
    not an error. Two reasons it declines:

    - there is no previous turn to resolve against
    - the query contributes no subject of its own, only elaboration words

    Purely rule-based: operates on strings already held in memory, costs no
    query and no network call. An LLM rewrite would be more capable — it could
    resolve references into the *text of the previous answer*, which this
    cannot — but it would put a model call on the cache read path, paying
    latency on every conversational turn to avoid a model call only sometimes.
    Queries this declines are left for the qualification gate to block.
    """
    from bitmod.cache_qualify import substantive_words

    if not state.queries:
        return None

    # Elaboration-only query: nothing to graft, so nothing to rewrite.
    subject = substantive_words(query)
    if not subject:
        return None

    prior_subject = substantive_words(state.queries[-1])
    if not prior_subject:
        return None

    # Already shares the previous topic — the query stands on its own.
    if any(t in prior_subject for t in subject):
        return None

    merged = prior_subject + [t for t in subject if t not in prior_subject]
    return " ".join(merged)


class SessionTracker:
    """In-memory LRU-bounded session tracker.

    Sessions are keyed by the hash of the first user message in the
    conversation. When the tracker exceeds max_sessions, the oldest
    session is evicted.
    """

    def __init__(self, max_sessions: int = 10_000):
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._max_sessions = max_sessions
        self._instance_salt = uuid.uuid4().hex

    def _compute_session_id(self, messages: list[dict]) -> str:
        """Derive session ID from all user messages in the conversation.

        Uses the full conversation prefix (all messages) plus a per-instance
        random salt to avoid collisions between different users sending the
        same opening message.
        """
        parts: list[str] = [self._instance_salt]
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
            parts.append(f"{role}:{content}")
        if len(parts) == 1:
            parts.append("empty")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def get_or_create(self, messages: list[dict]) -> SessionState:
        """Get an existing session or create a new one.

        Returns the SessionState for the conversation identified by messages.
        """
        sid = self._compute_session_id(messages)
        if sid in self._sessions:
            self._sessions.move_to_end(sid)
            return self._sessions[sid]

        state = SessionState(session_id=sid)
        self._sessions[sid] = state

        # Evict oldest if over capacity
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)

        return state

    def record(self, state: SessionState, query: str, answer: str, cache_key: str) -> None:
        """Record a Q&A exchange in the session."""
        state.record(query, answer, cache_key)
