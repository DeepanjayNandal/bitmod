"""Tests for session-aware caching (Layer 7)."""

from __future__ import annotations

import hashlib

import pytest

from bitmod.session import SessionState, SessionTracker


class TestSessionState:
    """Tests for SessionState dataclass behavior."""

    def test_defaults(self):
        """New session has empty lists and zero turns."""
        state = SessionState(session_id="abc123")
        assert state.session_id == "abc123"
        assert state.queries == []
        assert state.answers == []
        assert state.cache_keys == []
        assert state.turn_count == 0

    def test_record_appends_to_all_lists(self):
        """record() appends query, answer, and cache_key together."""
        state = SessionState(session_id="s1")
        state.record("What is X?", "X is Y.", "key-1")
        assert state.queries == ["What is X?"]
        assert state.answers == ["X is Y."]
        assert state.cache_keys == ["key-1"]
        assert state.turn_count == 1

    def test_turn_count_increments(self):
        """turn_count reflects number of recorded exchanges."""
        state = SessionState(session_id="s1")
        for i in range(5):
            state.record(f"q{i}", f"a{i}", f"k{i}")
        assert state.turn_count == 5

    def test_last_exchange_context_empty(self):
        """No exchanges returns None."""
        state = SessionState(session_id="s1")
        assert state.last_exchange_context() is None

    def test_last_exchange_context_returns_most_recent(self):
        """last_exchange_context formats the latest Q&A pair."""
        state = SessionState(session_id="s1")
        state.record("first question", "first answer", "k1")
        state.record("second question", "second answer", "k2")
        ctx = state.last_exchange_context()
        assert "second question" in ctx
        assert "second answer" in ctx
        assert "first question" not in ctx


class TestSessionTracker:
    """Tests for the LRU-bounded session tracker."""

    @pytest.fixture
    def tracker(self):
        return SessionTracker(max_sessions=5)

    def _messages(self, first_user_msg: str, extra: list[dict] | None = None) -> list[dict]:
        """Helper to build a message list with a first user message."""
        msgs = [{"role": "user", "content": first_user_msg}]
        if extra:
            msgs.extend(extra)
        return msgs

    def test_get_or_create_returns_session(self, tracker):
        """Creates a new session from messages."""
        msgs = self._messages("Hello world")
        state = tracker.get_or_create(msgs)
        assert isinstance(state, SessionState)
        assert len(state.session_id) == 16

    def test_session_id_deterministic(self, tracker):
        """Same first user message always produces the same session ID."""
        msgs = self._messages("Hello world")
        s1 = tracker.get_or_create(msgs)
        s2 = tracker.get_or_create(msgs)
        assert s1.session_id == s2.session_id

    def test_same_messages_return_same_session_object(self, tracker):
        """get_or_create is idempotent — returns the same SessionState instance."""
        msgs = self._messages("Hello world")
        s1 = tracker.get_or_create(msgs)
        s1.record("q", "a", "k")
        s2 = tracker.get_or_create(msgs)
        assert s2 is s1
        assert s2.turn_count == 1

    def test_different_first_messages_create_different_sessions(self, tracker):
        """Different first user messages produce different sessions."""
        s1 = tracker.get_or_create(self._messages("Hello"))
        s2 = tracker.get_or_create(self._messages("Goodbye"))
        assert s1.session_id != s2.session_id
        assert s1 is not s2

    def test_session_id_is_16_char_hex(self, tracker):
        """Session ID is a 16-char hex string derived from message content."""
        state = tracker.get_or_create(self._messages("What is Python?"))
        assert len(state.session_id) == 16
        assert all(c in "0123456789abcdef" for c in state.session_id)

    def test_empty_messages_handled(self, tracker):
        """Empty message list produces a deterministic session."""
        state = tracker.get_or_create([])
        assert len(state.session_id) == 16
        # Same empty input returns same session
        state2 = tracker.get_or_create([])
        assert state.session_id == state2.session_id

    def test_no_user_messages_handled(self, tracker):
        """Messages with no user role still produce a valid session."""
        msgs = [{"role": "system", "content": "You are helpful."}]
        state = tracker.get_or_create(msgs)
        assert len(state.session_id) == 16

    def test_single_message_handled(self, tracker):
        """Single user message works fine."""
        state = tracker.get_or_create([{"role": "user", "content": "Hi"}])
        assert state.turn_count == 0
        assert len(state.session_id) == 16

    def test_multipart_content_joined(self, tracker):
        """List-style content blocks produce a valid deterministic session."""
        msgs = [{"role": "user", "content": [{"text": "Hello"}, {"text": "World"}]}]
        state = tracker.get_or_create(msgs)
        assert len(state.session_id) == 16
        # Same input returns same session
        state2 = tracker.get_or_create(msgs)
        assert state.session_id == state2.session_id

    def test_record_stores_exchange(self, tracker):
        """Tracker.record delegates to SessionState.record."""
        state = tracker.get_or_create(self._messages("test"))
        tracker.record(state, "q1", "a1", "k1")
        assert state.queries == ["q1"]
        assert state.answers == ["a1"]
        assert state.cache_keys == ["k1"]

    def test_lru_eviction_when_max_exceeded(self):
        """Oldest session is evicted when max_sessions is exceeded."""
        tracker = SessionTracker(max_sessions=3)
        s1 = tracker.get_or_create([{"role": "user", "content": "msg-1"}])
        s1_id = s1.session_id
        s1.record("q", "a", "k")  # give it history so we can detect eviction
        s2 = tracker.get_or_create([{"role": "user", "content": "msg-2"}])
        s3 = tracker.get_or_create([{"role": "user", "content": "msg-3"}])

        # Adding a 4th should evict s1 (the oldest)
        tracker.get_or_create([{"role": "user", "content": "msg-4"}])

        # s1 should be gone — re-creating it gives a fresh session with no history
        s1_new = tracker.get_or_create([{"role": "user", "content": "msg-1"}])
        assert s1_new.session_id == s1_id
        assert s1_new.turn_count == 0  # fresh, history was lost on eviction

    def test_access_moves_session_to_end_preventing_eviction(self):
        """Accessing a session refreshes its LRU position."""
        tracker = SessionTracker(max_sessions=3)
        tracker.get_or_create([{"role": "user", "content": "msg-1"}])
        tracker.get_or_create([{"role": "user", "content": "msg-2"}])
        tracker.get_or_create([{"role": "user", "content": "msg-3"}])

        # Access msg-1 to refresh it — now msg-2 is oldest
        tracker.get_or_create([{"role": "user", "content": "msg-1"}])

        # Add msg-4 — should evict msg-2 (oldest), not msg-1
        tracker.get_or_create([{"role": "user", "content": "msg-4"}])

        # msg-1 should still exist, msg-2 should be gone
        s1 = tracker.get_or_create([{"role": "user", "content": "msg-1"}])
        assert len(s1.session_id) == 16  # still valid

        # msg-2 should be a fresh session (was evicted)
        s2_new = tracker.get_or_create([{"role": "user", "content": "msg-2"}])
        assert s2_new.turn_count == 0

    def test_session_id_is_stable_as_the_conversation_grows(self, tracker):
        """The id must not change when a turn is appended.

        This asserted the opposite — that two histories sharing an opening
        message get different ids — and was named for it. That is the defect:
        hashing every message meant each turn produced a new id, a fresh
        SessionState with turn_count 0, and both consumers (query resolution
        and session evidence) are gated on turn_count > 0. The layer could
        never engage in a real conversation.
        """
        turn_one = [{"role": "user", "content": "first"}]
        turn_two = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        assert tracker.get_or_create(turn_one).session_id == tracker.get_or_create(turn_two).session_id

    def test_different_openings_are_different_sessions(self, tracker):
        first = tracker.get_or_create([{"role": "user", "content": "about refunds"}])
        second = tracker.get_or_create([{"role": "user", "content": "about shipping"}])
        assert first.session_id != second.session_id

    def test_namespaces_do_not_share_a_session(self, tracker):
        """Two tenants asking the same opening question must stay separate.

        Session state feeds query resolution and supplies context to the model,
        so a collision here is a cross-tenant leak, not a cache miss.
        """
        messages = [{"role": "user", "content": "what is the refund policy"}]
        assert (
            tracker.get_or_create(messages, namespace_id="tenant-a").session_id
            != tracker.get_or_create(messages, namespace_id="tenant-b").session_id
        )

    def test_users_within_one_namespace_do_not_share_a_session(self, tracker):
        """Namespace separates tenants; nothing else separates users inside one."""
        messages = [{"role": "user", "content": "what is the refund policy"}]
        assert (
            tracker.get_or_create(messages, namespace_id="t", user_id="alice").session_id
            != tracker.get_or_create(messages, namespace_id="t", user_id="bob").session_id
        )

    def test_explicit_conversation_id_wins_over_the_opening_message(self, tracker):
        """Two conversations opening identically are separable when the caller says so.

        The fallback cannot tell them apart on its own — that is the accepted
        limit of deriving identity from the opening message, and the reason
        X-Bitmod-Conversation-Id exists.
        """
        messages = [{"role": "user", "content": "hello"}]
        assert (
            tracker.get_or_create(messages, conversation_id="conv-1").session_id
            != tracker.get_or_create(messages, conversation_id="conv-2").session_id
        )
        # And the same id keeps returning the same session as turns are added.
        grown = messages + [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "and then?"}]
        assert (
            tracker.get_or_create(messages, conversation_id="conv-1").session_id
            == tracker.get_or_create(grown, conversation_id="conv-1").session_id
        )

    def test_inconsistent_user_id_is_logged(self, tracker, caplog):
        """Sending the identifier on some turns and not others breaks continuity loudly.

        It is part of the fallback key, so dropping it mid-conversation changes
        the key and resolution silently stops happening. A warning makes that a
        five-minute diagnosis instead of a mystery.
        """
        import logging

        messages = [{"role": "user", "content": "what is the refund policy"}]
        tracker.get_or_create(messages, user_id="alice")
        with caplog.at_level(logging.WARNING, logger="bitmod.session"):
            tracker.get_or_create(messages)
        assert any("inconsistent" in r.message.lower() for r in caplog.records), (
            "dropping the user identifier mid-conversation should warn"
        )
