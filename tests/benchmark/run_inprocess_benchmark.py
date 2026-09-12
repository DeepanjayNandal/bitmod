#!/usr/bin/env python3
"""In-process cache benchmark — drives _run_cache_pipeline directly.

Measures the nine-layer pipeline by calling it, rather than over HTTP. The
pipeline already computes everything worth reporting — every contributing layer
with its own confidence, and the accumulated total — and returns it on the
result object. Reading that directly gives exact per-layer attribution without
adding a debug surface to production for the benefit of a benchmark.

WHAT THIS MEASURES
    Cache hit rate and layer attribution, against human-labelled data.

WHAT IT DOES NOT MEASURE
    End-to-end latency. Generation is stubbed (tests.mock_llm), so a "miss"
    costs a dictionary write rather than a model call. Latency figures here are
    cache-lookup cost only and must not be quoted as response times.

    Token savings. The stub reports fixed token counts; nothing calls a
    tokenizer.

DATASET
    sentence-transformers/quora-duplicates, pair-class config. Each row is two
    questions and a human label: 1 if they mean the same thing, 0 if not. That
    label is the ground truth for both directions —

      duplicates that miss     = recall the cache did not achieve
      non-duplicates that hit  = a wrong answer served confidently

    A hit rate without the second number is not interpretable.

PASSES
    1  cold      first question of each duplicate pair; nothing cached yet
    2  repeat    the same questions again; exercises exact match
    3  paraphrase the *second* question of each pair; the real recall measure
    4  unrelated  second question of non-duplicate pairs; hits here are errors

    Layers 7 and 9 can only contribute once history exists, so a single-pass
    number would understate them regardless of merit.

    python tests/benchmark/run_inprocess_benchmark.py --pairs 500
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from bitmod.adapters.db_sqlite import SQLiteBackend  # noqa: E402
from bitmod.proxy import BitmodProxy  # noqa: E402
from bitmod.router import LLMRouter  # noqa: E402

from tests.benchmark.dataset import (  # noqa: E402
    CONFIG,
    DATASET,
    HF_ROWS_API,
    QRECC_DATASET,
    SPLIT,
    fetch_conversations,
    fetch_pairs,
)
from tests.benchmark.provenance import provenance  # noqa: E402
from tests.mock_llm import MockLLM, canned_answer, load_answer_book  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


class Recorder:
    """One row per query, keeping the evidence so layers can be analysed later."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(
        self,
        pass_name: str,
        query: str,
        result,
        expected_hit: bool | None,
        expected_answers: list[str] | None = None,
        conversation_id: str = "",
        turn_index: int = 0,
        history_len: int = 0,
    ) -> None:
        """`expected_answers` is a SET of acceptable answers, not one answer.

        One element is the normal case and it is tempting to read the field as
        singular, but it is not. Empty means no serve is correct — nothing
        relevant is cached yet, or the pair is labelled not-a-duplicate.
        5_link_traversal is the multi-element case: the query can reach its
        partner's entry by traversal or the entry stored for itself in pass 3,
        and both are answers to a labelled duplicate. Code that assumes one
        element is correct everywhere except there, where it silently undercounts
        strict recall for a reason that has nothing to do with the cache.
        """
        evidence = getattr(result, "evidence", None)
        contributions = []
        if evidence is not None:
            for item in getattr(evidence, "evidences", []) or []:
                contributions.append(
                    {
                        "layer": item.layer,
                        "confidence": round(item.confidence, 4),
                        "is_partial": bool(getattr(item, "is_partial", False)),
                    }
                )
        # The strongest candidate is recorded whether or not it served. A
        # threshold sweep asks what would have happened at a threshold lower
        # than the one this run used, and that is unanswerable from the served
        # text alone: rows that missed here would serve there, and nothing would
        # record what they served. recall_rows_with_guard.json has exactly this
        # gap and cannot be swept because of it.
        # Whether session resolution rewrote the query or bailed, not merely
        # that it ran. Only REWRITTEN bypasses the qualification gate
        # (proxy/base.py:480), so without the action the bypass rate is
        # unmeasurable — mechanisms_run records the step, not its outcome.
        session_resolution = next(
            (s.get("action", "") for s in (result.trace or []) if s.get("mechanism") == "session_resolve"), ""
        )

        best_evidence = None
        if evidence is not None and hasattr(evidence, "best_single_answer"):
            best_evidence = evidence.best_single_answer()
        served_by = (best_evidence.layer if best_evidence else "") if result.hit else ""
        if result.hit and not served_by:
            for step in result.trace or []:
                if step.get("action") in ("HIT", "FULL_HIT"):
                    served_by = step.get("mechanism", "")

        # A layer that produced no evidence may have found nothing, or may have
        # found candidates and rejected them all on threshold. Those are
        # different facts about the layer and the evidence list cannot tell them
        # apart — only the trace can, because it records the best similarity the
        # layer saw before filtering.
        near_misses: dict[str, float] = {}
        ran: list[str] = []
        for step in result.trace or []:
            mechanism = step.get("mechanism", "")
            ran.append(mechanism)
            best = (step.get("detail") or {}).get("best_sim")
            if isinstance(best, int | float) and best > 0:
                near_misses[mechanism] = max(near_misses.get(mechanism, 0.0), float(best))

        self.rows.append(
            {
                "pass": pass_name,
                "query": query[:160],
                # Conversation identity and position. filters["_context"] is a
                # hash of the history prefix, so it is empty on turn 1 and
                # changes every turn — turn_index and history_len are what make
                # a cross-conversation collision distinguishable from a correct
                # re-hit after the fact.
                "conversation_id": conversation_id,
                "turn_index": turn_index,
                "history_len": history_len,
                "session_resolution": session_resolution,
                "hit": bool(result.hit),
                "expected_hit": expected_hit,
                "served_by": served_by,
                "served_text": (result.answer_text or "") if result.hit else "",
                "best_candidate": (best_evidence.answer_text or "") if best_evidence else "",
                "expected_answers": list(expected_answers or []),
                "total_confidence": round(getattr(evidence, "total_confidence", 0.0), 4),
                "contributions": contributions,
                "lookup_ms": round(result.elapsed_ms, 2),
                "mechanisms_run": sorted(set(ran)),
                "near_misses": {k: round(v, 4) for k, v in near_misses.items()},
            }
        )


def run_pass(proxy, recorder, name, queries, expected_hit, serve_threshold, echo_every=200):
    """`queries` is (query, expected_answers) pairs — see the call sites in main."""
    print(f"  pass {name}: {len(queries)} queries", flush=True)
    for index, (query, expected_answers) in enumerate(queries, 1):
        messages = [{"role": "user", "content": query}]
        result = proxy._run_cache_pipeline(query, messages)
        recorder.add(name, query, result, expected_hit, expected_answers)
        if not result.hit:
            # Cache the stubbed answer so later passes have something to match.
            proxy._store_response(
                user_message=query,
                answer_text=canned_answer(query),
                model_used="mock-model",
                elapsed_ms=0,
                filters=result.filters or {},
                norm=result.norm,
                answer_key=result.answer_key,
                evidence=result.evidence,
                messages_for_context=messages,
            )
        if index % echo_every == 0:
            print(f"    {index}/{len(queries)}", flush=True)


def run_conversation_pass(proxy, recorder, name, conversations, expected_hit, use_rewrites=False):
    """Walk each conversation turn by turn, carrying the history forward.

    The session layer needs a conversation to exist before it can do anything,
    and a conversation only exists if the turns arrive in order against a
    stable session id. Each turn is sent with the messages that preceded it,
    exactly as a client would.

    Answers stored here are the corpus's own — real prose, mostly over the
    100-character floor that fact extraction requires — so this pass is also
    what gives the atomic-fact layer anything to search.

    With `use_rewrites`, the human self-contained rewrite is sent instead of
    the question as asked. Turn 2 of a conversation reads "why was it only
    temporary?"; its rewrite names the subject. If resolution works, the two
    reach the same cached answer, and the rewrite pass measures that against
    ground truth someone else wrote.
    """
    total = sum(len(c.turns) for c in conversations)
    print(f"  pass {name}: {len(conversations)} conversations, {total} turns", flush=True)

    for conversation in conversations:
        # Explicit id, so the benchmark exercises the same path a client using
        # X-Bitmod-Conversation-Id would take rather than the fallback.
        cid = f"bench-conv-{conversation.conversation_no}"
        messages: list[dict] = []
        for turn_index, turn in enumerate(conversation.turns, 1):
            asked = turn.rewrite if use_rewrites else turn.question
            messages.append({"role": "user", "content": asked})
            # history is messages_for_context[:-1] at proxy/base.py:445, so the
            # prefix the _context hash is computed over is len(messages) - 1.
            result = proxy._run_cache_pipeline(asked, list(messages), conversation_id=cid)
            recorder.add(
                name,
                asked,
                result,
                expected_hit,
                [turn.answer],
                conversation_id=cid,
                turn_index=turn_index,
                history_len=len(messages) - 1,
            )
            if not result.hit:
                proxy._store_response(
                    user_message=asked,
                    answer_text=turn.answer,
                    model_used="mock-model",
                    elapsed_ms=0,
                    filters=result.filters or {},
                    norm=result.norm,
                    answer_key=result.answer_key,
                    evidence=result.evidence,
                    messages_for_context=list(messages),
                    conversation_id=cid,
                )
            messages.append({"role": "assistant", "content": result.answer_text or turn.answer})


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def accumulate(confidences: list[float]) -> float:
    """PipelineEvidence._recompute_confidence, reproduced.

    Positive evidence accumulates multiplicatively; negative evidence is a flat
    subtraction from that total. Two layers contribute negatively —
    serve_verify and promotion_verify are penalties, not matches — so an
    accumulator that only multiplied positives would silently drop them and
    every counterfactual involving one would be wrong.
    """
    positive = [c for c in confidences if c > 0]
    negative = [c for c in confidences if c < 0]

    miss = 1.0
    for c in positive:
        miss *= 1.0 - c
    pos_total = 1.0 - miss if positive else 0.0
    neg_total = sum(abs(c) for c in negative)

    return max(0.0, min(1.0, pos_total - neg_total))


def analyse_layers(rows: list[dict], serve_threshold: float) -> dict:
    """How often each layer fired, and how often it changed the outcome.

    "Contributed" counts how often a layer produced any evidence at all. It says
    nothing about whether that evidence mattered — a layer can fire on every
    request and never change a decision.

    "Decisive" is the counterfactual: recompute the accumulation without that
    layer and see whether the outcome flips. The question is not the same for
    every layer, because not every layer pushes the same direction.

      positive layers   asked of serves. Removing the layer drops the total
                        below the threshold, so the serve depended on it.

      penalty layers    asked of misses. serve_verify and promotion_verify
                        subtract confidence; they can only prevent a serve,
                        never cause one. So the question inverts: without this
                        layer the total would have cleared the threshold, which
                        means its presence is what blocked the serve. Counted
                        separately as "blocked" — calling it "decisive" would
                        put a layer that stopped a serve in the same column as
                        layers that caused one.

    A layer contributing 0.0 confidence can never be either. That is not a
    defect; the session layer does exactly this by design, resolving the query
    rather than voting on it.
    """
    contributed: dict[str, int] = defaultdict(int)
    decisive: dict[str, int] = defaultdict(int)
    blocked: dict[str, int] = defaultdict(int)
    sole_server: dict[str, int] = defaultdict(int)

    for row in rows:
        layers_here = {c["layer"] for c in row["contributions"]}
        for layer in layers_here:
            contributed[layer] += 1

        penalties = {c["layer"] for c in row["contributions"] if c["confidence"] < 0}

        if row["hit"]:
            if row["served_by"]:
                sole_server[row["served_by"]] += 1

            # Early-return serves (exact, composable) carry a single piece of
            # evidence and were never a threshold decision; counterfactual is moot.
            if len(layers_here) <= 1:
                if row["served_by"]:
                    decisive[row["served_by"]] += 1
                continue

            for layer in layers_here - penalties:
                without = [c["confidence"] for c in row["contributions"] if c["layer"] != layer]
                if accumulate(without) < serve_threshold:
                    decisive[layer] += 1
        else:
            # A penalty layer only shows its effect on a query that missed.
            for layer in penalties:
                without = [c["confidence"] for c in row["contributions"] if c["layer"] != layer]
                if accumulate(without) >= serve_threshold:
                    blocked[layer] += 1

    return {
        "contributed": dict(contributed),
        "decisive": dict(decisive),
        "blocked": dict(blocked),
        "served_by": dict(sole_server),
    }


# The nine layers in pipeline order, with what a zero means for each. A layer
# reporting nothing is not evidence that it is broken, and the report has to say
# which it is — otherwise the only available reading of a zero is "defective".
LAYERS: list[tuple[str, str]] = [
    ("exact", "answer-key match; contributes 1.0 and returns immediately"),
    ("semantic", "embedding similarity, graded by _similarity_to_confidence"),
    (
        "composable",
        "fires only on comparison phrasing — decompose_query is a regex over "
        "compare/vs/versus/differences between, so questions with separable parts "
        "that do not use those words are never decomposed (see BACKLOG item 7)",
    ),
    ("fuzzy", "token overlap or edit distance, graded by measured similarity"),
    (
        "similarity_link",
        "traverses links learned from semantic near-misses in the "
        "link_learn_min..link_learn_max band; needs a query to be revisited "
        "after the link exists, so a single pass over distinct queries cannot "
        "reach it",
    ),
    (
        "atomic_facts",
        "embedding search over facts extracted from cached ANSWER text, not from "
        "ingested documents; needs answers of at least fact_min_answer_length "
        "(100) chars whose sentences survive a 30-char floor",
    ),
    (
        "session",
        "contributes 0.0 by design. The Batch 2 rewrite removed the flat +0.25 and made "
        "this layer resolve the query against history rather than vote on it, so it is "
        "carried as context for a miss. It will always read contributed N, decisive 0, "
        "and that is the layer working correctly",
    ),
    (
        "serve_verify",
        "penalty, not a match — subtracts confidence when a served candidate fails "
        "source verification, so it appears under 'blocked', never 'decisive'",
    ),
    (
        "promotion_verify",
        "penalty, and off by default (promotion_config.enabled); silent unless "
        "LLM promotion verification is switched on",
    ),
]


# Trace mechanism names, where they differ from the evidence layer name.
MECHANISM_FOR_LAYER = {
    "exact": "exact_cache",
    "semantic": "semantic_cache",
    "composable": "composable_cache",
    "fuzzy": "fuzzy_match",
    "similarity_link": "similarity_links",
    "atomic_facts": "atomic_facts",
    "session": "session_cache",
    "serve_verify": "serve_verify",
    "promotion_verify": "promotion_verify",
}


def layer_coverage(analysis: dict, rows: list[dict]) -> list[dict]:
    """Every layer, whether it fired, and what its silence means.

    Distinguishes a layer that never ran from one that ran, found candidates,
    and rejected them all on threshold. Both contribute zero evidence and they
    are not the same finding — the first says the corpus cannot reach the
    layer, the second says the layer is reachable and its threshold is the
    binding constraint.
    """
    contributed = analysis["contributed"]
    coverage = []
    for name, note in LAYERS:
        mechanism = MECHANISM_FOR_LAYER.get(name, name)
        ran = sum(1 for r in rows if mechanism in r.get("mechanisms_run", []))
        sims = [r["near_misses"][mechanism] for r in rows if mechanism in r.get("near_misses", {})]
        coverage.append(
            {
                "layer": name,
                "contributed": contributed.get(name, 0),
                "decisive": analysis["decisive"].get(name, 0),
                "blocked": analysis["blocked"].get(name, 0),
                "served": analysis["served_by"].get(name, 0),
                "exercised": name in contributed,
                "queries_where_it_ran": ran,
                "best_similarity_seen": round(max(sims), 4) if sims else None,
                "note": note,
            }
        )
    return coverage


def threshold_sweep(rows: list[dict]) -> list[dict]:
    """Precision and recall against the labels at a range of serve thresholds.

    Recomputed from the confidence each query actually accumulated, so it costs
    nothing beyond one run. Only the passes carrying a ground-truth label are
    counted: pass 3 (paraphrases, should hit) and pass 4 (unrelated, must not).

    This is an approximation of what re-running at each threshold would show,
    and it reads low rather than high. A query that served on accumulated
    confidence stopped there; at a higher threshold the pipeline would have
    continued to later layers and might have recovered. Nothing here models
    that, so the curve understates what the later layers could contribute at
    the strict end. It is exact at and below the threshold that was in force.
    """
    labelled = [r for r in rows if r["expected_hit"] is not None and r["pass"] in ("3_paraphrase", "4_unrelated")]
    duplicates = [r for r in labelled if r["expected_hit"] is True]
    non_duplicates = [r for r in labelled if r["expected_hit"] is False]

    sweep = []
    for step in range(50, 100):
        threshold = step / 100
        true_positives = sum(1 for r in duplicates if r["total_confidence"] >= threshold)
        false_positives = sum(1 for r in non_duplicates if r["total_confidence"] >= threshold)
        served = true_positives + false_positives
        sweep.append(
            {
                "threshold": round(threshold, 2),
                "recall": round(true_positives / len(duplicates), 4) if duplicates else None,
                "precision": round(true_positives / served, 4) if served else None,
                "hit_rate": round(served / len(labelled), 4) if labelled else None,
                "false_positives": false_positives,
            }
        )
    return sweep


def summarise(rows: list[dict], serve_threshold: float) -> dict:
    by_pass: dict[str, dict] = {}
    for row in rows:
        entry = by_pass.setdefault(row["pass"], {"total": 0, "hits": 0, "expected_hit": row["expected_hit"]})
        entry["total"] += 1
        entry["hits"] += 1 if row["hit"] else 0
    for entry in by_pass.values():
        entry["hit_rate"] = round(entry["hits"] / entry["total"], 4) if entry["total"] else 0.0

    correct = sum(1 for r in rows if r["expected_hit"] is not None and r["hit"] == r["expected_hit"])
    labelled = sum(1 for r in rows if r["expected_hit"] is not None)

    false_positives = [r for r in rows if r["expected_hit"] is False and r["hit"]]
    false_negatives = [r for r in rows if r["expected_hit"] is True and not r["hit"]]
    layers = analyse_layers(rows, serve_threshold)

    return {
        "queries": len(rows),
        "hits": sum(1 for r in rows if r["hit"]),
        "hit_rate": round(sum(1 for r in rows if r["hit"]) / len(rows), 4) if rows else 0.0,
        "by_pass": by_pass,
        "against_labels": {
            "labelled_queries": labelled,
            "agreement": round(correct / labelled, 4) if labelled else None,
            "false_positives": len(false_positives),
            "false_negatives": len(false_negatives),
            "false_positive_examples": [r["query"] for r in false_positives[:5]],
        },
        "layers": layers,
        "layer_coverage": layer_coverage(layers, rows),
        "threshold_sweep": threshold_sweep(rows),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _clear_scratch_db(db_path: Path) -> None:
    """Remove the scratch database and the sidecar files SQLite leaves beside it.

    In WAL mode a -wal and a -shm file live next to the .db. Deleting only the
    .db leaves those behind, and the next run opens a database carrying the
    previous run's committed pages — the cold pass would start warm.
    """
    for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if path.exists():
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="In-process cache benchmark")
    parser.add_argument("--pairs", type=int, default=500, help="labelled pairs of each kind")
    parser.add_argument("--conversations", type=int, default=150, help="QReCC conversations for the session passes")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--out", default="")
    parser.add_argument("--answers-out", default="", help="write the answer book here for the HTTP stub")
    parser.add_argument(
        "--rows-out",
        default="",
        help=(
            "write the per-query rows. Needed to calibrate anything against this workload: the "
            "summary cannot be refitted, and a constant fitted on one corpus is not known to "
            "transfer to another until it is checked against both."
        ),
    )
    args = parser.parse_args()

    from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter
    from bitmod.cache_engine import _get_config

    serve_threshold = _get_config().serve_threshold

    print(f"Fetching {args.pairs} duplicate and {args.pairs} non-duplicate pairs from {DATASET} ...", flush=True)
    duplicates, non_duplicates = fetch_pairs(args.pairs)
    print(f"  got {len(duplicates)} duplicate, {len(non_duplicates)} non-duplicate pairs", flush=True)

    print(f"Fetching {args.conversations} conversations from {QRECC_DATASET} ...", flush=True)
    conversations = fetch_conversations(args.conversations)
    turns = sum(len(c.turns) for c in conversations)
    print(f"  got {len(conversations)} conversations, {turns} turns", flush=True)

    # Both runners must generate identical text. The in-process side stores the
    # corpus answer directly; the HTTP side reaches the stub server, which reads
    # this same book rather than re-fetching and risking a different sample.
    book = {t.question: t.answer for c in conversations for t in c.turns}
    book.update({t.rewrite: t.answer for c in conversations for t in c.turns})
    load_answer_book(book)
    if args.answers_out:
        Path(args.answers_out).write_text(json.dumps(book, indent=0))
        print(f"  answer book written to {args.answers_out} ({len(book)} entries)", flush=True)

    db_path = Path(RESULTS_DIR) / "_benchmark_scratch.db"
    _clear_scratch_db(db_path)
    backend = SQLiteBackend(str(db_path))
    backend.initialize()

    mock = MockLLM()
    proxy = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=mock), default_model="mock-model")
    proxy._embedder = OllamaEmbeddingAdapter(model=args.embed_model)

    recorder = Recorder()

    # Snapshotted before the run, not at write time. Python imports at launch,
    # so a run spanning a commit executes the tree as it was when it started;
    # capturing afterwards records a tree that never ran. The tuning constants
    # go with it — a row set whose damping is unknown cannot be re-derived from,
    # and every row set predating this records only the two thresholds.
    cfg = _get_config()
    run_config = {
        "accumulation_damping": cfg.accumulation_damping,
        "calibrated_confidence": cfg.calibrated_confidence,
        "serve_threshold": cfg.serve_threshold,
        "search_threshold": cfg.search_threshold,
        "entity_guard_enabled": cfg.entity_guard_enabled,
        "fact_min_similarity": cfg.fact_min_similarity,
    }
    provenance_info = provenance()
    started = time.time()

    # Each pass carries the answers that would be correct for it, so strict
    # recall is computable later without guessing. Empty means no serve is
    # correct: nothing relevant is cached yet (1_cold) or the pair is labelled
    # not-a-duplicate (4_unrelated).
    run_pass(proxy, recorder, "1_cold", [(a, []) for a, _ in duplicates], False, serve_threshold)
    run_pass(proxy, recorder, "2_repeat", [(a, [canned_answer(a)]) for a, _ in duplicates], True, serve_threshold)
    run_pass(proxy, recorder, "3_paraphrase", [(b, [canned_answer(a)]) for a, b in duplicates], True, serve_threshold)
    run_pass(proxy, recorder, "4_unrelated", [(b, []) for _, b in non_duplicates], False, serve_threshold)

    # Pass 3 learned similarity links from its near-misses. Traversal can only
    # be reached by asking again once those links exist, which no single pass
    # over distinct queries can do.
    #
    # Two answers are acceptable here and the ambiguity is recorded rather than
    # resolved: b reaches a's entry by traversal, but where pass 3 missed, b was
    # stored under its own answer and pass 5 exact-matches that instead. Both
    # are answers to a labelled duplicate. Collapsing them to one would
    # undercount strict recall for reasons that have nothing to do with the
    # cache.
    run_pass(
        proxy,
        recorder,
        "5_link_traversal",
        [(b, [canned_answer(a), canned_answer(b)]) for a, b in duplicates],
        True,
        serve_threshold,
    )

    # Conversations: session resolution, and the real answers that atomic-fact
    # extraction needs. Expected outcome is left unlabelled — a follow-up that
    # misses on its first appearance is correct, not a recall failure.
    run_conversation_pass(proxy, recorder, "6_conversation", conversations, None)
    run_conversation_pass(proxy, recorder, "7_conversation_repeat", conversations, True)
    run_conversation_pass(proxy, recorder, "8_rewrites", conversations, True, use_rewrites=True)

    elapsed = time.time() - started

    report = {
        "harness": "in-process (_run_cache_pipeline called directly)",
        "measures": "cache hit rate and per-layer attribution",
        "does_not_measure": [
            "end-to-end latency — generation is stubbed, so lookup_ms is cache cost only",
            "token savings — the stub reports fixed token counts, nothing is tokenized",
        ],
        "dataset": {
            "name": DATASET,
            "config": CONFIG,
            "split": SPLIT,
            "source": HF_ROWS_API,
            "duplicate_pairs": len(duplicates),
            "non_duplicate_pairs": len(non_duplicates),
            "labels": "1 = human-labelled duplicate, 0 = not a duplicate",
        },
        "conversation_dataset": {
            "name": QRECC_DATASET,
            "conversations": len(conversations),
            "turns": turns,
            "context_dependent_turns": sum(1 for c in conversations for t in c.turns if t.is_context_dependent),
            "answers_at_or_above_fact_floor": sum(1 for c in conversations for t in c.turns if len(t.answer) >= 100),
            "ground_truth": "human-written self-contained Rewrite per turn",
        },
        "embedder": f"ollama/{args.embed_model}",
        "generation": "stubbed — returns the corpus answer for known questions, identical to the HTTP harness",
        "serve_threshold": serve_threshold,
        "run_config": run_config,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance_info,
        "duration_s": round(elapsed, 1),
        "summary": summarise(recorder.rows, serve_threshold),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"inprocess_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    if args.rows_out:
        Path(args.rows_out).write_text(
            json.dumps(
                {"run_config": run_config, "provenance": provenance_info, "rows": recorder.rows},
                indent=0,
            )
        )
        print(f"  {len(recorder.rows)} rows written to {args.rows_out}", flush=True)
    _clear_scratch_db(db_path)

    s = report["summary"]
    print()
    print(f"  overall hit rate : {s['hit_rate']:.1%}  ({s['hits']}/{s['queries']})")
    for name in sorted(s["by_pass"]):
        p = s["by_pass"][name]
        print(f"    {name:<14} {p['hit_rate']:>7.1%}  ({p['hits']}/{p['total']})")
    lab = s["against_labels"]
    print(f"  agreement with labels : {lab['agreement']:.1%}" if lab["agreement"] is not None else "")
    print(f"  false positives       : {lab['false_positives']}")
    print(f"  false negatives       : {lab['false_negatives']}")

    print("\n  layer               contributed  decisive  blocked")
    for entry in s["layer_coverage"]:
        if entry["exercised"]:
            flag = ""
        elif entry["queries_where_it_ran"] and entry["best_similarity_seen"] is not None:
            flag = (
                f"   (ran {entry['queries_where_it_ran']}x, "
                f"best sim {entry['best_similarity_seen']:.2f} — below threshold)"
            )
        elif entry["queries_where_it_ran"]:
            flag = f"   (ran {entry['queries_where_it_ran']}x, found nothing)"
        else:
            flag = "   (never ran)"
        print(
            f"    {entry['layer']:<18} {entry['contributed']:>10}  {entry['decisive']:>8}  {entry['blocked']:>7}{flag}"
        )

    print("\n  threshold   recall  precision   hit rate   false pos")
    for entry in s["threshold_sweep"]:
        if round(entry["threshold"] * 100) % 5:
            continue
        precision = f"{entry['precision']:.1%}" if entry["precision"] is not None else "     —"
        marker = "  <- current" if abs(entry["threshold"] - serve_threshold) < 1e-9 else ""
        print(
            f"     {entry['threshold']:.2f}    {entry['recall']:>6.1%}     {precision:>6}"
            f"    {entry['hit_rate']:>6.1%}   {entry['false_positives']:>9}{marker}"
        )
    print(f"\n  report written to {out_path}")


if __name__ == "__main__":
    main()
