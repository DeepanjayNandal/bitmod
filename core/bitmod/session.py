"""Session-aware caching (Layer 7).

Tracks conversation sessions in-memory to provide contextual evidence
when a query is a follow-up in an existing session.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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


def _message_text(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def _first_user_message(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            text = _message_text(msg).strip()
            if text:
                return text
    return ""


class SessionTracker:
    """In-memory LRU-bounded session tracker.

    Sessions are keyed by an explicit conversation id when the caller supplies
    one, and otherwise by the first user message in the conversation, scoped to
    the namespace and end user. When the tracker exceeds max_sessions, the
    oldest session is evicted.

    The key has to be stable as the conversation grows, which is the whole
    point. It previously hashed every message, so each turn produced a new id,
    a fresh SessionState with turn_count 0, and a tracker full of states that
    were written once and never read. Both consumers are gated on
    turn_count > 0, so query resolution never ran and session evidence was
    never added — the layer could not engage in a real conversation, only in
    tests that seeded the tracker with the turn about to be asked.
    """

    def __init__(self, max_sessions: int = 10_000):
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._max_sessions = max_sessions
        self._instance_salt = uuid.uuid4().hex
        # Opening message -> whether a user identifier came with it, so an
        # identifier that appears on some turns and not others is reported
        # rather than silently splitting one conversation into two sessions.
        self._user_id_seen: OrderedDict[str, bool] = OrderedDict()

    def _warn_on_inconsistent_user_id(self, opening: str, user_id: str | None) -> None:
        """Flag a user identifier that comes and goes within one conversation.

        The identifier is part of the fallback key, so sending it on some turns
        and not others changes the key mid-conversation and breaks the chain.
        The failure is otherwise silent: resolution simply stops happening.
        """
        if not opening:
            return
        present = bool(user_id)
        previous = self._user_id_seen.get(opening)
        if previous is not None and previous != present:
            logger.warning(
                "User identifier inconsistent within a conversation (was %s, now %s). "
                "It is part of the session key, so session continuity is broken for this "
                "conversation — send it on every turn or on none.",
                "present" if previous else "absent",
                "present" if present else "absent",
            )
        self._user_id_seen[opening] = present
        while len(self._user_id_seen) > self._max_sessions:
            self._user_id_seen.popitem(last=False)

    def _compute_session_id(
        self,
        messages: list[dict],
        conversation_id: str | None = None,
        namespace_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Derive a session id that is stable across the turns of one conversation.

        An explicit conversation id from the caller wins. Otherwise the opening
        user message identifies the conversation, scoped by namespace and by end
        user: two tenants asking the same opening question must not share
        session state, and neither must two users inside one tenant. Session
        state feeds query resolution and supplies context to the model, so a
        collision is a cross-user leak rather than a cache miss.
        """
        if conversation_id and conversation_id.strip():
            parts = [self._instance_salt, "cid", namespace_id or "", conversation_id.strip()]
            return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

        opening = _first_user_message(messages)
        self._warn_on_inconsistent_user_id(opening, user_id)
        parts = [self._instance_salt, "open", namespace_id or "", user_id or "", opening or "empty"]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def get_or_create(
        self,
        messages: list[dict],
        conversation_id: str | None = None,
        namespace_id: str | None = None,
        user_id: str | None = None,
    ) -> SessionState:
        """Get an existing session or create a new one."""
        sid = self._compute_session_id(
            messages, conversation_id=conversation_id, namespace_id=namespace_id, user_id=user_id
        )
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
