"""Labelled corpora, shared by both benchmark runners.

The two runners must differ only in transport. Loading the corpus from one
place means a disagreement between their numbers cannot be blamed on them
having read different data.

Three datasets, because no single one reaches every layer. That is a property of
the pipeline, not a gap in the search: one layer wants paraphrase pairs, another
wants multi-turn anaphora, and they cannot come from the same rows. The third
(bitext, below) is a different question entirely — not "can the cache generalise"
but "does it serve the wrong answer when the alternatives are genuinely close".

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

bitext/Bitext-customer-support-llm-chatbot-training-dataset is retail customer
support. Each row is a user phrasing, an intent label, an answer, and tags
describing how the phrasing varies. Many phrasings share one intent, so the
paraphrase grouping comes from the dataset rather than from whoever wrote the
benchmark — the objection that sank the hand-authored alternative.

Fetched through the HuggingFace rows API rather than the parquet export, so no
columnar dependency is needed and only the rows actually used are downloaded.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

HF_ROWS_API = "https://datasets-server.huggingface.co/rows"
DATASET = "sentence-transformers/quora-duplicates"
CONFIG = "pair-class"
SPLIT = "train"

QRECC_DATASET = "voidful/qrecc"
QRECC_CONFIG = "default"
QRECC_SPLIT = "train"

BITEXT_DATASET = "bitext/Bitext-customer-support-llm-chatbot-training-dataset"
BITEXT_CONFIG = "default"
BITEXT_SPLIT = "train"
BITEXT_TOTAL_ROWS = 26872  # measured against /statistics, not assumed


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def _get_with_retry(client: httpx.Client, params: dict, attempts: int = 4) -> dict:
    """The rows API returns transient 502s. A benchmark run is long enough that
    losing one to a momentary gateway error wastes more time than retrying.

    429 is handled separately from 502. A rate limit is not transient — backing
    off by the server's own Retry-After is the difference between a fetch that
    finishes and one that exhausts its attempts mid-corpus, which is what a
    plain exponential backoff did on the first full bitext pull.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(HF_ROWS_API, params=params)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            last = exc
            if attempt == attempts - 1:
                break
            wait = 2**attempt
            if exc.response.status_code == 429:
                retry_after = exc.response.headers.get("Retry-After")
                wait = max(wait, float(retry_after) if retry_after else 5.0)
            time.sleep(min(wait, 60))
        except httpx.TransportError as exc:
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


# ---------------------------------------------------------------------------
# Bitext — retail customer support, intent-grouped
# ---------------------------------------------------------------------------

# The dataset card's "Language Generation Tags" section, verbatim in meaning.
# Twelve are documented; D (indirect speech) and G (regional variation) are
# listed there as not used in this dataset and so are absent here.
VARIATION_TAGS = {
    "M": "morphological variation — inflection and derivation",
    "L": "semantic variation — synonyms, hyphenation, compounding",
    "B": "basic syntactic structure",
    "I": "interrogative structure",
    "C": "coordinated syntactic structure",
    "N": "negation",
    "P": "politeness variation",
    "Q": "colloquial variation ('can u activ8 my SIM?')",
    "W": "offensive language",
    "K": "keyword mode ('activate SIM')",
    "E": "use of abbreviations",
    "Z": "errors and typos ('how can i activaet my card')",
}

# Every placeholder appearing in an `instruction`, measured across all 26,872
# rows — there are exactly nine, so this map is complete rather than a sample.
#
# One fixed value per placeholder, NOT a varying one. A varying value would be
# the more realistic workload, and it is deliberately not what this measures:
# it would turn every repeat of a question into a different string and make the
# benchmark a test of entity handling rather than of paraphrase retrieval.
# The consequence is named in the runner's report — entity_guard is not
# exercised by these entities, and no number here says anything about it.
PLACEHOLDER_FILL = {
    "Order Number": "12345",
    "Account Type": "premium",
    "Person Name": "Alex Morgan",
    "Account Category": "standard",
    "Refund Amount": "50",
    "Currency Symbol": "$",
    "Delivery City": "Springfield",
    "Delivery Country": "United States",
    "Invoice Number": "INV-9001",
}

_PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")


def fill_placeholders(text: str) -> str:
    """Substitute the fixed value for each `{{Placeholder}}`.

    An unknown placeholder degrades to its own lowercased name rather than
    raising. Responses carry placeholders this map does not cover (48% of
    responses contain one, against 25% of instructions) and an answer reading
    "your refund of company name" is a visible defect in an artifact, where a
    crash mid-run is a lost run.
    """
    return _PLACEHOLDER_RE.sub(lambda m: PLACEHOLDER_FILL.get(m.group(1), m.group(1).lower()), text)


@dataclass
class SupportQuery:
    """One user phrasing of one intent."""

    instruction: str
    intent: str
    category: str
    flags: str
    row_index: int

    @property
    def variations(self) -> list[str]:
        """The documented tags on this phrasing, unknown letters dropped."""
        return [c for c in self.flags if c in VARIATION_TAGS]


@dataclass
class SupportIntent:
    """One intent: its canonical answer, and every phrasing that should reach it."""

    intent: str
    category: str
    canonical_instruction: str
    canonical_answer: str
    queries: list[SupportQuery] = field(default_factory=list)


def _bitext_cache_dir() -> Path:
    path = Path(__file__).resolve().parent / ".cache" / "bitext"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_support_corpus(cache_dir: Path | None = None) -> list[SupportIntent]:
    """Every row, grouped by intent, with the first row of each intent canonical.

    WHICH ROW IS CANONICAL IS ARBITRARY. It is the first occurrence in dataset
    order — not the clearest phrasing, not the most representative, and not
    chosen. Each of the ~1,000 rows sharing an intent carries its own generated
    response, so the dataset has no canonical answer of its own; electing one is
    something this benchmark does TO the dataset, and a reader has to be able to
    tell that apart from a property of the data.

    The whole corpus is fetched rather than sampled, so there is no sampling
    design to defend. Pages are cached on disk because the rows API rate-limits
    hard enough that a cold fetch of 269 pages takes tens of minutes; a second
    run costs nothing.
    """
    cache = Path(cache_dir) if cache_dir else _bitext_cache_dir()
    rows: list[dict] = []

    with httpx.Client(timeout=90) as client:
        for offset in range(0, BITEXT_TOTAL_ROWS, 100):
            page_file = cache / f"{offset:06d}.json"
            if page_file.exists():
                rows.extend(json.loads(page_file.read_text()))
                continue
            payload = _get_with_retry(
                client,
                {
                    "dataset": BITEXT_DATASET,
                    "config": BITEXT_CONFIG,
                    "split": BITEXT_SPLIT,
                    "offset": offset,
                    "length": 100,
                },
                attempts=8,
            )
            page = [item["row"] for item in payload.get("rows", [])]
            page_file.write_text(json.dumps(page))
            rows.extend(page)

    intents: dict[str, SupportIntent] = {}
    for index, row in enumerate(rows):
        name = (row.get("intent") or "").strip()
        instruction = fill_placeholders((row.get("instruction") or "").strip())
        response = fill_placeholders((row.get("response") or "").strip())
        if not name or not instruction or not response:
            continue
        entry = intents.get(name)
        if entry is None:
            entry = SupportIntent(
                intent=name,
                category=(row.get("category") or "").strip(),
                canonical_instruction=instruction,
                canonical_answer=response,
            )
            intents[name] = entry
        entry.queries.append(
            SupportQuery(
                instruction=instruction,
                intent=name,
                category=entry.category,
                flags=(row.get("flags") or "").strip(),
                row_index=index,
            )
        )

    return [intents[k] for k in sorted(intents)]
