#!/usr/bin/env python3
"""Where should the atomic-fact layer's threshold sit, given what it compares?

fact_min_similarity is 0.80, which is the scale the semantic layer uses to
compare a question against another question. The fact layer compares a question
against a declarative sentence, and those score lower by construction: the two
texts differ in grammatical shape even when the fact answers the question
exactly. The layer borrowed a number from a comparison it does not perform, and
contributed 10 pieces of evidence in 4,600 queries as a result.

A separate defect has already been fixed: the query was key-normalised and the
facts were not, so the two sides of the cosine went through different
preprocessing. CacheEmbedder now owns that, which is worth about 0.20 of median
similarity on its own. This is the remaining question.

LABELS
    QReCC supplies them without anything being invented. Facts extracted from a
    turn's own answer are what that turn's question should match; facts from
    other turns are what it should not. Same shape of ground truth as the other
    fits — someone else's data, not our judgement.

    python tests/benchmark/fit_fact_threshold.py --conversations 60
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from bitmod.cache_engine import (  # noqa: E402
    CacheEmbedder,
    _cosine_similarity,
    _get_config,
    decompose_answer,
)

from tests.benchmark.dataset import fetch_conversations  # noqa: E402
from tests.benchmark.provenance import provenance  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def build_pairs(conversations, embedder, negatives_per_turn: int = 3, seed: int = 31):
    """(question, fact, is_from_this_turn) — positives and sampled negatives."""
    cfg = _get_config()
    turns = []
    for conversation in conversations:
        for turn in conversation.turns:
            if len(turn.answer) < cfg.fact_min_answer_length:
                continue  # the layer would store nothing for this answer
            facts = [f["fact_text"] for f in decompose_answer(turn.answer)]
            if facts:
                turns.append((turn.rewrite or turn.question, facts))
    if len(turns) < 2:
        return []

    rng = random.Random(seed)  # noqa: S311 — reproducible negative sampling, not cryptography
    vectors: dict[str, list[float]] = {}

    def vec(text: str):
        if text not in vectors:
            vectors[text] = embedder.embed(text)
        return vectors[text]

    rows = []
    for index, (question, facts) in enumerate(turns):
        for fact in facts:
            rows.append({"similarity": _cosine_similarity(vec(question), vec(fact)), "label": 1})
        for _ in range(negatives_per_turn):
            other = rng.randrange(len(turns))
            if other == index:
                continue
            fact = rng.choice(turns[other][1])
            rows.append({"similarity": _cosine_similarity(vec(question), vec(fact)), "label": 0})
    return rows


def sweep(rows: list[dict]) -> list[dict]:
    positives = [r["similarity"] for r in rows if r["label"] == 1]
    negatives = [r["similarity"] for r in rows if r["label"] == 0]
    out = []
    for step in range(30, 96, 5):
        threshold = step / 100
        tp = sum(1 for s in positives if s >= threshold)
        fp = sum(1 for s in negatives if s >= threshold)
        out.append(
            {
                "threshold": round(threshold, 2),
                "recall": round(tp / len(positives), 4) if positives else None,
                "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
                "facts_admitted": tp + fp,
                "wrong_facts": fp,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the atomic-fact threshold")
    parser.add_argument("--conversations", type=int, default=60)
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

    cfg = _get_config()
    # Wrapped, so both sides are preprocessed the way production does it.
    embedder = CacheEmbedder(OllamaEmbeddingAdapter(model=args.embed_model))

    conversations = fetch_conversations(args.conversations)
    rows = build_pairs(conversations, embedder)
    positives = [r["similarity"] for r in rows if r["label"] == 1]
    negatives = [r["similarity"] for r in rows if r["label"] == 0]

    print(f"{len(positives)} question/own-fact pairs, {len(negatives)} question/other-fact pairs")
    print(f"  own facts   median {statistics.median(positives):.3f}  mean {statistics.mean(positives):.3f}")
    print(f"  other facts median {statistics.median(negatives):.3f}  mean {statistics.mean(negatives):.3f}")
    print(f"\ncurrent fact_min_similarity = {cfg.fact_min_similarity}")

    table = sweep(rows)
    print(f"\n{'threshold':>10}{'recall':>10}{'precision':>12}{'wrong facts':>14}")
    for entry in table:
        precision = f"{entry['precision']:.1%}" if entry["precision"] is not None else "—"
        marker = "  <- current" if abs(entry["threshold"] - cfg.fact_min_similarity) < 1e-9 else ""
        print(
            f"{entry['threshold']:>10.2f}{entry['recall']:>10.1%}{precision:>12}"
            f"{entry['wrong_facts']:>14}{marker}"
        )

    report = {"provenance": provenance(),
        "positives": len(positives),
        "negatives": len(negatives),
        "own_fact_median": round(statistics.median(positives), 4),
        "other_fact_median": round(statistics.median(negatives), 4),
        "current_threshold": cfg.fact_min_similarity,
        "sweep": table,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else RESULTS_DIR / "fact_threshold.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
