"""Labelled corpora, shared by both benchmark runners.

The two runners must differ only in transport. Loading the corpus from one
place means a disagreement between their numbers cannot be blamed on them
having read different data.

Two datasets, because no single one reaches every layer. That is a property of
the pipeline, not a gap in the search: one layer wants paraphrase pairs, another
wants multi-turn anaphora, and they cannot come from the same rows.

sentence-transformers/quora-duplicates carries a human label per pair: 1 if the
two questions mean the same thing, 0 if not. That gives ground truth in both
directions — duplicates that miss are recall the cache did not achieve, and
non-duplicates that hit are wrong answers served confidently.

voidful/qrecc is conversational QA. Each turn carries the context-dependent
question, a human-written self-contained Rewrite, the answer, and the source
URL. The rewrite is ground truth for query resolution written by someone other
than us, which is the same property that made quora worth using. Its answers are
real prose — median 129 characters, three quarters above the 100-character floor
that atomic-fact extraction requires — which is what the previous stub answer
("Mock answer to: ...", 40 characters, no sentence terminator) could never
satisfy.

Fetched through the HuggingFace rows API rather than the parquet export, so no
columnar dependency is needed and only the rows actually used are downloaded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

HF_ROWS_API = "https://datasets-server.huggingface.co/rows"
DATASET = "sentence-transformers/quora-duplicates"
CONFIG = "pair-class"
SPLIT = "train"

QRECC_DATASET = "voidful/qrecc"
QRECC_CONFIG = "default"
QRECC_SPLIT = "train"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def _get_with_retry(client: httpx.Client, params: dict, attempts: int = 4) -> dict:
    """The rows API returns transient 502s. A benchmark run is long enough that
    losing one to a momentary gateway error wastes more time than retrying."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(HF_ROWS_API, params=params)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"dataset fetch failed after {attempts} attempts: {last}")


def fetch_pairs(target_pairs: int) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (duplicate_pairs, non_duplicate_pairs) from the labelled split."""
    duplicates: list[tuple[str, str]] = []
    non_duplicates: list[tuple[str, str]] = []
    offset, page = 0, 100

    with httpx.Client(timeout=60) as client:
        while len(duplicates) < target_pairs or len(non_duplicates) < target_pairs:
            payload = _get_with_retry(
                client,
                {"dataset": DATASET, "config": CONFIG, "split": SPLIT, "offset": offset, "length": page},
            )
            rows = payload.get("rows", [])
            if not rows:
                break
            for item in rows:
                row = item["row"]
                pair = (row["sentence1"], row["sentence2"])
                if not pair[0] or not pair[1]:
                    continue
                if str(row["label"]) == "1":
                    if len(duplicates) < target_pairs:
                        duplicates.append(pair)
                elif len(non_duplicates) < target_pairs:
                    non_duplicates.append(pair)
            offset += page
            if offset > 50_000:
                break

    return duplicates, non_duplicates


# ---------------------------------------------------------------------------
# QReCC — conversational QA with human rewrites
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """One turn of a conversation."""

    question: str  # as asked, often context-dependent ("Why was it only temporary?")
    rewrite: str  # the same question made self-contained, written by a human
    answer: str  # real prose, long enough for fact extraction to engage
    turn_no: int

    @property
    def is_context_dependent(self) -> bool:
        """The question differs from its rewrite, so it cannot stand alone."""
        return self.question.strip().lower() != self.rewrite.strip().lower()


@dataclass
class Conversation:
    """A sequence of turns sharing a subject."""

    conversation_no: int
    turns: list[Turn] = field(default_factory=list)


def fetch_conversations(target: int, min_turns: int = 4) -> list[Conversation]:
    """Return conversations of at least `min_turns` turns, in order.

    Short conversations are dropped: the session layer needs prior turns to
    resolve against, and a two-turn exchange barely exercises it.

    Rows arrive grouped by conversation and ordered by turn, but that is not
    promised, so turns are sorted by Turn_no before use — a session benchmark
    that fed turns out of order would measure nothing.
    """
    conversations: dict[int, Conversation] = {}
    offset, page = 0, 100

    with httpx.Client(timeout=60) as client:
        while len([c for c in conversations.values() if len(c.turns) >= min_turns]) < target:
            payload = _get_with_retry(
                client,
                {
                    "dataset": QRECC_DATASET,
                    "config": QRECC_CONFIG,
                    "split": QRECC_SPLIT,
                    "offset": offset,
                    "length": page,
                },
            )
            rows = payload.get("rows", [])
            if not rows:
                break
            for item in rows:
                row = item["row"]
                question, answer = (row.get("Question") or "").strip(), (row.get("Answer") or "").strip()
                if not question or not answer:
                    continue
                number = int(row["Conversation_no"])
                conversation = conversations.setdefault(number, Conversation(conversation_no=number))
                conversation.turns.append(
                    Turn(
                        question=question,
                        rewrite=(row.get("Rewrite") or question).strip(),
                        answer=answer,
                        turn_no=int(row.get("Turn_no") or 0),
                    )
                )
            offset += page
            if offset > 50_000:
                break

    usable = [c for c in conversations.values() if len(c.turns) >= min_turns]
    for conversation in usable:
        conversation.turns.sort(key=lambda t: t.turn_no)
    usable.sort(key=lambda c: c.conversation_no)
    return usable[:target]
