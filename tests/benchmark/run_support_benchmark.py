#!/usr/bin/env python3
"""Support-workload benchmark — precision against a dense, confusable answer set.

Drives _run_cache_pipeline directly, exactly as run_inprocess_benchmark does.
Only the query generator differs. Everything about the pipeline, the config, the
recorder, and the provenance block is shared, so a disagreement between the two
runners cannot be blamed on them exercising different code.

WHY THIS EXISTS, AND WHY PRECISION IS THE HEADLINE
    The quora corpus pairs questions at random, so a wrong serve there requires
    the cache to confuse two questions that have nothing to do with each other.
    Real support traffic is not like that: the wrong answers are the ones next
    door. This corpus has 27 intents and they include

        track_order / track_refund
        get_refund / track_refund / check_refund_policy
        cancel_order / change_order / check_cancellation_fee
        create_account / delete_account / edit_account / switch_account
        check_invoice / get_invoice

    — adversarial by construction rather than by luck.

    The same density that makes this a hard precision test makes it an easy
    recall test. 27 answers against ~1,500 queries means roughly 55 queries per
    cached answer, so after the seeding pass every query has a correct answer
    waiting. A hit rate computed here would be a fact about the corpus shape,
    not about the cache, and it is reported as context for that reason. THE HIT
    RATE FROM THIS RUNNER MUST NOT BE QUOTED AS A CACHE HIT RATE.

WHAT THIS MEASURES
    Whether a rephrased question reaches the right cached answer, and how often
    it reaches a neighbouring wrong one. Broken down by the kind of rephrasing,
    using the dataset's own variation tags.

WHAT IT DOES NOT MEASURE
    End-to-end latency or token savings — generation never runs. The cache is
    seeded directly and frozen; see --warm.

    Over-serving on out-of-domain queries. Every query in the default arm has a
    correct answer in cache, so the runner cannot see a cache that answers
    things it should have declined. --hold-out-categories is the arm that can.

    Entity handling. Placeholders are filled with one fixed value each
    (dataset.PLACEHOLDER_FILL), so no two queries differ only by an entity and
    entity_guard is never put under load.

CORPUS CAVEAT, TO BE CARRIED INTO ANY WRITE-UP
    The dataset card states the pairs were NLG-expanded from natural seed text
    under computational-linguist curation. These are curated variations, not
    logged production traffic. They are not authored by whoever wrote this
    benchmark, which was the point — but they are not organic either.

    python tests/benchmark/run_support_benchmark.py --queries 1500
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from bitmod.adapters.db_sqlite import SQLiteBackend  # noqa: E402
from bitmod.proxy import BitmodProxy  # noqa: E402
from bitmod.router import LLMRouter  # noqa: E402

from tests.benchmark.dataset import (  # noqa: E402
    BITEXT_CONFIG,
    BITEXT_DATASET,
    BITEXT_SPLIT,
    HF_ROWS_API,
    VARIATION_TAGS,
    SupportIntent,
    fetch_support_corpus,
)
from tests.benchmark.provenance import provenance  # noqa: E402
from tests.benchmark.run_inprocess_benchmark import (  # noqa: E402
    Recorder,
    _clear_scratch_db,
    analyse_layers,
    layer_coverage,
)
from tests.mock_llm import MockLLM  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


class SupportRecorder(Recorder):
    """Recorder plus the three fields this corpus has and quora does not.

    Subclassed rather than adding parameters to Recorder.add: every committed
    row set was written by that signature, and widening it for one runner's
    benefit is how a shared schema stops being shared.
    """

    def add_support(
        self,
        pass_name: str,
        query: str,
        result,
        expected_hit: bool | None,
        expected_answers: list[str],
        *,
        intent: str,
        category: str,
        flags: str,
    ) -> None:
        self.add(pass_name, query, result, expected_hit, expected_answers)
        self.rows[-1].update(
            {
                "intent": intent,
                "category": category,
                "flags": flags,
                "variations": [c for c in flags if c in VARIATION_TAGS],
            }
        )


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------


def zipf_weights(n: int, exponent: float) -> list[float]:
    """Normalised 1/rank**s over n items. exponent 0.0 gives uniform.

    ASSUMPTION, STATED RATHER THAN BURIED: rank order is dataset order, which is
    alphabetical by intent. It is not a popularity ordering, because nothing in
    this corpus records how often real users ask each thing.

    Over 27 intents this is close to decorative and the default is uniform. Zipf
    earns its place when the tail holds items asked once or twice, so that some
    queries arrive before their answer is ever cached. Every intent here is
    seeded before any paraphrase runs, so there is no cold tail for a skew to
    create and the parameter changes only how often each answer is re-asked.
    """
    raw = [1.0 / ((i + 1) ** exponent) for i in range(n)]
    total = sum(raw)
    return [r / total for r in raw]


def allocate(intents: list[SupportIntent], total: int, exponent: float) -> list[int]:
    """How many paraphrase queries each intent contributes, largest-remainder."""
    weights = zipf_weights(len(intents), exponent)
    exact = [w * total for w in weights]
    counts = [int(x) for x in exact]
    for index in sorted(range(len(exact)), key=lambda i: exact[i] - counts[i], reverse=True)[: total - sum(counts)]:
        counts[index] += 1
    return [min(c, max(0, len(intents[i].queries) - 1)) for i, c in enumerate(counts)]


def build_paraphrase_pass(intents: list[SupportIntent], total: int, exponent: float, seed: int):
    """Sample non-canonical phrasings, then interleave them deterministically.

    The canonical row is excluded — it is the seeding pass's query, and leaving
    it in would score an exact-match serve as paraphrase recall.
    """
    rng = random.Random(seed)  # noqa: S311 — reproducible sampling, nothing cryptographic
    counts = allocate(intents, total, exponent)
    picked = []
    for intent, count in zip(intents, counts):
        pool = [q for q in intent.queries if q.instruction != intent.canonical_instruction]
        picked.extend(rng.sample(pool, min(count, len(pool))))
    rng.shuffle(picked)
    return picked


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# Passes excluded from every score.
#
# 1_seed is cold by construction — nothing is cached, so a miss is the design
# working rather than a failure.
#
# 2_exact is excluded for a subtler reason, and it is the one worth stating:
# it re-sends byte-identical strings, so it hits ~100% and it does so through
# the exact-match layer, which has nothing to do with whether the cache
# generalises. Blending 27 guaranteed hits into a paraphrase measurement makes
# every headline number a weighted average of a trivially-true figure and the
# real one, with the weight set by how many intents the corpus happens to have.
# It is reported on its own as a sanity check: if it is not ~100%, the run is
# broken and nothing below it means anything.
EXCLUDED_FROM_SCORING = ("1_seed", "2_exact")


def _scored(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["pass"] not in EXCLUDED_FROM_SCORING]


def score(rows: list[dict]) -> dict:
    """Correct, wrong, and missed — kept separate, because two of them are hits.

    A served answer is correct only when it is the canonical answer of the
    query's own intent. Anything else served is WRONG, including an answer from
    a neighbouring intent that a human might call reasonable. That strictness is
    deliberate and its cost is visible in the confusion matrix: a reader who
    disagrees with the labelling can see exactly which pairs drove the number
    instead of having to take the summary on trust.
    """
    considered = _scored(rows)
    correct = wrong = missed = 0
    for row in considered:
        if not row["hit"]:
            missed += 1
        elif row["served_text"] and row["served_text"] in row["expected_answers"]:
            correct += 1
        else:
            wrong += 1

    served = correct + wrong
    answerable = [r for r in considered if r["expected_answers"]]
    answerable_correct = sum(
        1 for r in answerable if r["hit"] and r["served_text"] and r["served_text"] in r["expected_answers"]
    )
    return {
        "queries_scored": len(considered),
        "served": served,
        "correct": correct,
        "wrong": wrong,
        "missed": missed,
        "precision": round(correct / served, 4) if served else None,
        "recall": round(answerable_correct / len(answerable), 4) if answerable else None,
        "hit_rate_context_only": round(served / len(considered), 4) if considered else None,
        "wrong_per_1000_served": round(1000 * wrong / served, 1) if served else None,
    }


def retrieval_reach(rows: list[dict]) -> dict:
    """How often the RIGHT answer was the top candidate, whether or not it served.

    This separates two failures that a recall number welds together: the cache
    never found the answer, and the cache found it and declined to serve it.
    They have opposite fixes — the first is a retrieval problem, the second is a
    threshold decision — and a single recall figure cannot tell a reader which
    one they are looking at.

    `best_candidate` is the strongest candidate the pipeline assembled,
    recorded by Recorder whether or not it cleared serve_threshold. Rows with no
    candidate at all are counted in `no_candidate`: nothing was retrieved, so
    the threshold was never the binding constraint for them.
    """
    considered = [r for r in _scored(rows) if r["expected_answers"]]
    with_candidate = [r for r in considered if r["best_candidate"]]
    reached = [r for r in with_candidate if r["best_candidate"] in r["expected_answers"]]
    served_correct = sum(1 for r in reached if r["hit"] and r["served_text"] in r["expected_answers"])
    return {
        "queries": len(considered),
        "no_candidate": len(considered) - len(with_candidate),
        "right_answer_retrieved": len(reached),
        "right_answer_retrieved_rate": round(len(reached) / len(considered), 4) if considered else None,
        "of_those_served": served_correct,
        "found_but_not_served": len(reached) - served_correct,
        "note": (
            "found_but_not_served is the cost of serve_threshold on this workload: the correct answer "
            "was the top candidate and accumulated confidence did not clear the bar"
        ),
    }


def threshold_sweep(rows: list[dict]) -> list[dict]:
    """Precision and recall against serve_threshold, recomputed without re-running.

    PROJECTED, NOT MEASURED, and the error is large and one-directional.

    This re-reads one run's recorded confidences against a different bar. What it
    cannot re-read is the cache those confidences came from, and under --warm the
    cache is itself a function of the threshold: a miss is what writes an entry,
    so a lower bar serves more, writes less, and leaves later queries a sparser
    cache to retrieve from. The confidences change; the projection assumes they
    do not.

    Measured 2026-09-23, this projection against live runs at the same commit,
    held-out warm arm:

        0.80   projected 120 wrong of 1111 served    live 309 of 1285    2.6x
        0.75   projected 184 wrong of 1316 served    live 354 of 1384    1.9x

    It understates wrong serves, which is the reassuring direction. Do not quote
    a row of this as a measurement. Set BITMOD_CACHE_SERVE_THRESHOLD and run it.

    A second, smaller approximation runs the other way: a query that served
    stopped early, so at a HIGHER threshold the pipeline might have continued to
    later layers and recovered, and the curve reads low above the threshold in
    force. That one is close to vacuous on a frozen-cache run, where almost
    nothing serves at 0.85 and so almost nothing stopped early. It is not vacuous
    under --warm, and it is the smaller of the two.
    """
    considered = [r for r in _scored(rows) if r["best_candidate"]]
    answerable = [r for r in _scored(rows) if r["expected_answers"]]
    sweep = []
    for step in range(50, 100, 5):
        threshold = step / 100
        served = [r for r in considered if r["total_confidence"] >= threshold]
        correct = sum(1 for r in served if r["best_candidate"] in r["expected_answers"])
        wrong = len(served) - correct
        sweep.append(
            {
                "threshold": round(threshold, 2),
                "served": len(served),
                "correct": correct,
                "wrong": wrong,
                "precision": round(correct / len(served), 4) if served else None,
                "recall": round(correct / len(answerable), 4) if answerable else None,
            }
        )
    return sweep


def confusion(rows: list[dict], answer_to_intent: dict[str, str]) -> list[dict]:
    """Which intent's answer was served for which intent's question.

    Only wrong serves. The diagonal is the correct count and is already in
    score(); repeating it here would bury the ten rows that matter under 27 that
    do not.
    """
    pairs: dict[tuple[str, str], int] = collections.Counter()
    for row in rows:
        if row["pass"] in EXCLUDED_FROM_SCORING or not row["hit"] or not row["served_text"]:
            continue
        if row["served_text"] in row["expected_answers"]:
            continue
        served_intent = answer_to_intent.get(row["served_text"], "<not-a-canonical-answer>")
        pairs[(row["intent"], served_intent)] += 1
    return [
        {"asked": asked, "served": served, "count": count}
        for (asked, served), count in sorted(pairs.items(), key=lambda kv: -kv[1])
    ]


def confusion_at(rows: list[dict], answer_to_intent: dict[str, str], threshold: float) -> dict:
    """The same matrix, counterfactually, at a threshold the run did not use.

    WHY THIS IS NEEDED AND WHAT IT IS NOT. At serve_threshold 0.85 this corpus
    serves so little that confusion() comes back empty, and an empty matrix
    reads as "the cache never confuses these intents" when it actually means
    "the cache almost never answers". Those are opposite conclusions and the
    artifact must not let a reader take the first one.

    So the pairs are recomputed from best_candidate at a lower threshold. This
    is a projection, NOT a measurement: it assumes a query that did not serve
    would have served its recorded top candidate, which ignores that the
    pipeline stops early once it clears the bar and might have continued to a
    later layer. It is the same approximation threshold_sweep carries, named
    again here because a confusion matrix looks more like raw data than a sweep
    does and is likelier to be quoted as one.
    """
    pairs: dict[tuple[str, str], int] = collections.Counter()
    served = 0
    for row in rows:
        if row["pass"] in EXCLUDED_FROM_SCORING or not row["best_candidate"]:
            continue
        if row["total_confidence"] < threshold:
            continue
        served += 1
        if row["best_candidate"] in row["expected_answers"]:
            continue
        served_intent = answer_to_intent.get(row["best_candidate"], "<not-a-canonical-answer>")
        pairs[(row["intent"], served_intent)] += 1
    return {
        "threshold": threshold,
        "projected_serves": served,
        "projected_wrong": sum(pairs.values()),
        "basis": "projected from best_candidate, not measured — see confusion_at docstring",
        "pairs": [
            {"asked": asked, "served": srv, "count": count}
            for (asked, srv), count in sorted(pairs.items(), key=lambda kv: -kv[1])
        ],
    }


def by_variation(rows: list[dict]) -> list[dict]:
    """Per variation tag: how often retrieval reached the right answer, and how
    often it was served.

    REACH IS THE COLUMN TO READ, NOT RECALL. Serve recall depends entirely on
    where serve_threshold sits — at 0.85 this corpus serves around 1% of
    queries, so a per-tag recall table is a dozen buckets separated by one or
    two queries each, and ranking them ranks noise. Reach asks whether the
    correct entry was the top candidate, which is a property of retrieval alone
    and is measured on every query rather than on the handful that served.

    `mean_confidence` is carried alongside because it is what a threshold acts
    on: a tag whose queries reach the right answer but accumulate 0.4 is a
    different problem from one that never retrieves it at all.

    A query carries several tags at once, so these buckets overlap and do not
    sum to the total. That is a property of the dataset's tagging, not a
    counting error: an utterance can be colloquial AND contain a typo, and the
    dataset tags it both.

    B is on every row in the corpus and therefore separates nothing; it is kept
    so the table is complete and its uselessness is visible rather than edited
    out.
    """
    buckets: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row["pass"] in EXCLUDED_FROM_SCORING or not row["expected_answers"]:
            continue
        for tag in row.get("variations", []):
            buckets[tag].append(row)

    out = []
    for tag, group in buckets.items():
        reached = sum(1 for r in group if r["best_candidate"] and r["best_candidate"] in r["expected_answers"])
        correct = sum(1 for r in group if r["hit"] and r["served_text"] in r["expected_answers"])
        wrong = sum(1 for r in group if r["hit"] and r["served_text"] not in r["expected_answers"])
        confidences = [r["total_confidence"] for r in group]
        out.append(
            {
                "tag": tag,
                "meaning": VARIATION_TAGS[tag],
                "queries": len(group),
                "reached": reached,
                "reach": round(reached / len(group), 4) if group else None,
                "mean_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
                "correct": correct,
                "wrong": wrong,
                "recall": round(correct / len(group), 4) if group else None,
                "precision": round(correct / (correct + wrong), 4) if (correct + wrong) else None,
            }
        )
    return sorted(out, key=lambda e: e["reach"] if e["reach"] is not None else 1.0)


def by_intent(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row["pass"] not in EXCLUDED_FROM_SCORING:
            groups[row["intent"]].append(row)
    out = []
    for intent, group in groups.items():
        answerable = [r for r in group if r["expected_answers"]]
        correct = sum(1 for r in answerable if r["hit"] and r["served_text"] in r["expected_answers"])
        wrong = sum(1 for r in group if r["hit"] and r["served_text"] not in r["expected_answers"])
        out.append(
            {
                "intent": intent,
                "queries": len(group),
                "correct": correct,
                "wrong": wrong,
                "recall": round(correct / len(answerable), 4) if answerable else None,
            }
        )
    return sorted(out, key=lambda e: e["recall"] if e["recall"] is not None else 1.0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=1500, help="paraphrase queries across all intents")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--seed", type=int, default=20260916, help="sampling seed; the run is deterministic given it")
    parser.add_argument(
        "--zipf",
        type=float,
        default=0.0,
        help="frequency skew exponent over intents; 0.0 is uniform. See zipf_weights for why uniform is the default.",
    )
    parser.add_argument(
        "--hold-out-categories",
        default="",
        help=(
            "comma-separated CATEGORY names to leave uncached, e.g. INVOICE,CONTACT,SUBSCRIPTION. "
            "Their queries become a pass where no serve is correct. Held out by category rather than "
            "by intent so an intent's near neighbours leave with it — holding out get_invoice while "
            "seeding check_invoice leaves a magnet behind and scores a defensible answer as wrong."
        ),
    )
    parser.add_argument(
        "--warm",
        action="store_true",
        help=(
            "store missed queries as a real cache would. Default is a FROZEN cache: seeded once, never "
            "written again, so every paraphrase is an independent trial against an identical cache state "
            "and recall does not depend on query order. Warming is more realistic and less measurable."
        ),
    )
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--rows-out", default="", help="gzipped per-query rows; needed to re-analyse without re-running"
    )
    args = parser.parse_args()

    from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter
    from bitmod.cache_engine import _get_config

    print(f"Loading {BITEXT_DATASET} ...", flush=True)
    corpus = fetch_support_corpus()
    print(f"  {len(corpus)} intents, {sum(len(i.queries) for i in corpus)} phrasings", flush=True)

    held_out = {c.strip().upper() for c in args.hold_out_categories.split(",") if c.strip()}
    seeded = [i for i in corpus if i.category.upper() not in held_out]
    withheld = [i for i in corpus if i.category.upper() in held_out]
    if held_out:
        print(f"  holding out {len(withheld)} intents in {sorted(held_out)}; seeding {len(seeded)}", flush=True)

    # Canonical answers must be distinguishable, or the confusion matrix cannot
    # attribute a wrong serve to the intent that produced it.
    answer_to_intent = {i.canonical_answer: i.intent for i in corpus}
    if len(answer_to_intent) != len(corpus):
        raise SystemExit(
            f"canonical answers are not unique: {len(answer_to_intent)} distinct for {len(corpus)} intents"
        )

    db_path = RESULTS_DIR / "_support_scratch.db"
    _clear_scratch_db(db_path)
    backend = SQLiteBackend(str(db_path))
    backend.initialize()

    proxy = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=MockLLM()), default_model="mock-model")
    proxy._embedder = OllamaEmbeddingAdapter(model=args.embed_model)
    recorder = SupportRecorder()

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

    def ask(pass_name, text, intent_name, category, flags, expected, expected_hit):
        messages = [{"role": "user", "content": text}]
        result = proxy._run_cache_pipeline(text, messages)
        recorder.add_support(
            pass_name, text, result, expected_hit, expected, intent=intent_name, category=category, flags=flags
        )
        return result, messages

    def store(text, messages, result, answer):
        proxy._store_response(
            user_message=text,
            answer_text=answer,
            model_used="mock-model",
            elapsed_ms=0,
            filters=result.filters or {},
            norm=result.norm,
            answer_key=result.answer_key,
            evidence=result.evidence,
            messages_for_context=messages,
        )

    # 1_seed — one canonical question per seeded intent, stored with its
    # canonical answer. Excluded from every score: nothing is cached yet, so a
    # miss here is the design working.
    print(f"  pass 1_seed: {len(seeded)} intents", flush=True)
    for intent in seeded:
        result, messages = ask("1_seed", intent.canonical_instruction, intent.intent, intent.category, "", [], False)
        if not result.hit:
            store(intent.canonical_instruction, messages, result, intent.canonical_answer)

    # 2_exact — the identical string again. Separates "the cache works at all"
    # from "the cache generalises", which a paraphrase-only run conflates.
    print(f"  pass 2_exact: {len(seeded)} queries", flush=True)
    for intent in seeded:
        ask(
            "2_exact",
            intent.canonical_instruction,
            intent.intent,
            intent.category,
            "",
            [intent.canonical_answer],
            True,
        )

    # 3_paraphrase — the measurement.
    queries = build_paraphrase_pass(seeded, args.queries, args.zipf, args.seed)
    canonical_for = {i.intent: i.canonical_answer for i in corpus}
    print(f"  pass 3_paraphrase: {len(queries)} queries", flush=True)
    for index, query in enumerate(queries, 1):
        result, messages = ask(
            "3_paraphrase",
            query.instruction,
            query.intent,
            query.category,
            query.flags,
            [canonical_for[query.intent]],
            True,
        )
        if args.warm and not result.hit:
            store(query.instruction, messages, result, canonical_for[query.intent])
        if index % 200 == 0:
            print(f"    {index}/{len(queries)}", flush=True)

    # 4_held_out — in-domain queries whose answer was never cached. Empty
    # expected_answers, so ANY serve is wrong by construction.
    if withheld:
        held_queries = build_paraphrase_pass(withheld, max(1, args.queries // 4), args.zipf, args.seed + 1)
        print(f"  pass 4_held_out: {len(held_queries)} queries", flush=True)
        for query in held_queries:
            ask("4_held_out", query.instruction, query.intent, query.category, query.flags, [], False)

    elapsed = time.time() - started
    rows = recorder.rows
    summary = score(rows)
    held_rows = [r for r in rows if r["pass"] == "4_held_out"]

    report = {
        "harness": "in-process (_run_cache_pipeline called directly)",
        "measures": "precision against a dense confusable answer set, and recall by rephrasing type",
        "headline": "precision — see does_not_measure for why hit rate is context only",
        "does_not_measure": [
            "cache hit rate as a product figure — 27 answers over ~1,500 queries makes it a corpus property",
            "end-to-end latency or token savings — generation never runs",
            "entity handling — placeholders are filled with one fixed value each, so entity_guard is unloaded",
            (
                "over-serving on out-of-domain queries, unless --hold-out-categories is used: otherwise every "
                "query has a correct answer in cache"
            ),
        ],
        "dataset": {
            "name": BITEXT_DATASET,
            "config": BITEXT_CONFIG,
            "split": BITEXT_SPLIT,
            "source": HF_ROWS_API,
            "total_rows": sum(len(i.queries) for i in corpus),
            "intents": len(corpus),
            "categories": len({i.category for i in corpus}),
            "canonical_answer_rule": (
                "first row of each intent in dataset order — ARBITRARY, not selected. Each row carries its "
                "own generated response, so the dataset has no canonical answer; electing one is something "
                "this benchmark does to the dataset, not a property of it."
            ),
            "provenance_caveat": (
                "NLG-expanded from natural seed text under computational-linguist curation, per the dataset "
                "card. Curated variations, not logged production traffic — and not authored by this project, "
                "which is why it was chosen."
            ),
            "placeholders": "filled with one fixed value each; see dataset.PLACEHOLDER_FILL",
        },
        "arm": {
            "seeded_intents": len(seeded),
            "held_out_categories": sorted(held_out),
            "held_out_intents": sorted(i.intent for i in withheld),
            "cache_policy": "warm — misses are stored" if args.warm else "frozen — seeded once, never written again",
            "zipf_exponent": args.zipf,
            "seed": args.seed,
        },
        "embedder": f"ollama/{args.embed_model}",
        "run_config": run_config,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance_info,
        "duration_s": round(elapsed, 1),
        "summary": summary,
        "by_pass": {
            name: {
                "total": sum(1 for r in rows if r["pass"] == name),
                "hits": sum(1 for r in rows if r["pass"] == name and r["hit"]),
            }
            for name in sorted({r["pass"] for r in rows})
        },
        "held_out": (
            {
                "queries": len(held_rows),
                "served": sum(1 for r in held_rows if r["hit"]),
                "over_serve_rate": round(sum(1 for r in held_rows if r["hit"]) / len(held_rows), 4),
                "note": "every serve here is wrong by construction — the answer was never cached",
            }
            if held_rows
            else None
        ),
        "exact_match_check": {
            "queries": sum(1 for r in rows if r["pass"] == "2_exact"),
            "hits": sum(1 for r in rows if r["pass"] == "2_exact" and r["hit"]),
            "note": (
                "byte-identical re-sends, excluded from every score. Expected ~100%; anything lower means "
                "the seeding pass did not populate the cache and no other number in this report is meaningful."
            ),
        },
        "retrieval_reach": retrieval_reach(rows),
        "threshold_sweep_caveat": (
            "PROJECTED, NOT MEASURED. Re-reads this run's confidences against a different bar without "
            "re-running, so it cannot see that under --warm a lower threshold serves more, writes fewer "
            "entries, and leaves later queries a sparser cache. Measured 2026-09-23 against live runs at "
            "the same commit on the held-out warm arm, this understates wrong serves by 2.6x at 0.80 and "
            "1.9x at 0.75, always in the reassuring direction. Do not quote a row as a measurement. See "
            "the threshold_sweep docstring in run_support_benchmark.py."
        ),
        "threshold_sweep": threshold_sweep(rows),
        "confusion": confusion(rows, answer_to_intent),
        "confusion_projected": [confusion_at(rows, answer_to_intent, t) for t in (0.70, 0.60, 0.50)],
        "by_variation": by_variation(rows),
        "by_intent": by_intent(rows),
        "layer_coverage": layer_coverage(analyse_layers(rows, cfg.serve_threshold), rows),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"support_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    if args.rows_out:
        with gzip.open(args.rows_out, "wt") as handle:
            json.dump({"run_config": run_config, "provenance": provenance_info, "rows": rows}, handle, indent=0)
        print(f"  {len(rows)} rows written to {args.rows_out}", flush=True)
    _clear_scratch_db(db_path)

    s = summary
    e = report["exact_match_check"]
    print()
    print(f"  exact-match check     : {e['hits']}/{e['queries']}  (sanity only, excluded from scores)")
    print(f"  PRECISION  {s['precision']:.1%}   ({s['correct']} correct of {s['served']} served)")
    print(f"  wrong serves          : {s['wrong']}  ({s['wrong_per_1000_served']} per 1000 served)")
    print(f"  recall                : {s['recall']:.1%}")
    print(f"  hit rate (context)    : {s['hit_rate_context_only']:.1%}  <- corpus shape, not a product figure")
    if report["held_out"]:
        h = report["held_out"]
        print(f"  held-out over-serve   : {h['over_serve_rate']:.1%}  ({h['served']}/{h['queries']})")

    r = report["retrieval_reach"]
    print(
        f"\n  right answer retrieved: {r['right_answer_retrieved']}/{r['queries']} "
        f"({r['right_answer_retrieved_rate']:.1%})   served {r['of_those_served']}, "
        f"blocked by threshold {r['found_but_not_served']}"
    )

    print("\n  threshold  served  correct  wrong  precision  recall")
    for entry in report["threshold_sweep"]:
        precision = f"{entry['precision']:.1%}" if entry["precision"] is not None else "     —"
        marker = "  <- in force" if abs(entry["threshold"] - cfg.serve_threshold) < 1e-9 else ""
        print(
            f"     {entry['threshold']:.2f}   {entry['served']:>6}  {entry['correct']:>7}  "
            f"{entry['wrong']:>5}  {precision:>9}  {entry['recall']:>6.1%}{marker}"
        )

    print("\n  tag  queries   reach  mean conf  recall   meaning")
    for entry in report["by_variation"]:
        print(
            f"    {entry['tag']}  {entry['queries']:>7}  {entry['reach']:>6.1%}  "
            f"{entry['mean_confidence']:>9.3f}  {entry['recall']:>6.2%}   {entry['meaning'][:44]}"
        )

    if report["confusion"]:
        print("\n  wrong serves, measured, most frequent first")
        for entry in report["confusion"][:12]:
            print(f"    {entry['asked']:<26} -> {entry['served']:<26} {entry['count']}")
    else:
        print("\n  wrong serves, measured: none — note this is because almost nothing served, not")
        print("  because nothing was confused. The projection below is what confusion looks like.")

    for projection in report["confusion_projected"]:
        if not projection["pairs"]:
            continue
        print(
            f"\n  projected at threshold {projection['threshold']:.2f}: "
            f"{projection['projected_wrong']} wrong of {projection['projected_serves']} serves"
        )
        for entry in projection["pairs"][:8]:
            print(f"    {entry['asked']:<26} -> {entry['served']:<26} {entry['count']}")
        break

    print(f"\n  report written to {out_path}")


if __name__ == "__main__":
    main()
