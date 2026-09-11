#!/usr/bin/env python3
"""Fit similarity -> confidence against labelled data, and check it beats the incumbent.

The mapping in _similarity_to_confidence was written by hand in the first
commit and never checked against anything. Its slope inverts: it is steepest
between 0.85 and 0.92 and flattest between 0.92 and 0.98, which is exactly
where serve decisions are made. A lone semantic match therefore has to reach
cosine 0.980 before it can serve on its own, and 76 of 500 labelled duplicates
sat above 0.92 and were refused.

Replacing one hand-drawn curve with another would not be an improvement, so
this fits one instead.

WHAT IS BEING FITTED
    P(these two questions mean the same thing | cosine similarity).

    Framing confidence as a probability is the point. Accumulated confidence
    then has a meaning, and serve_threshold becomes a statement about how often
    a served answer may be wrong rather than a number chosen by feel.

METHOD
    Two-parameter logistic, fitted by Newton-Raphson. Preferred to isotonic
    regression because roughly a fifth of Quora's duplicate labels are wrong on
    inspection, and a non-parametric fit chases that noise; a monotone
    two-parameter curve cannot.

    Validation is a held-out split. If the fit does not beat the incumbent
    curve out of sample it is not adopted — that is a real possible outcome and
    the script says so rather than shipping the fit regardless.

    python tests/benchmark/fit_confidence_curve.py --pairs 500
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

import numpy as np  # noqa: E402
from bitmod.cache_engine import (  # noqa: E402
    CacheEmbedder,
    _cosine_similarity,
    _similarity_to_confidence,
    fuzzy_similarity,
    normalize_query_fuzzy,
)

from tests.benchmark.dataset import fetch_pairs  # noqa: E402
from tests.benchmark.provenance import provenance  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def fit_logistic(x: np.ndarray, y: np.ndarray, iterations: int = 100, l2: float = 0.0) -> tuple[float, float]:
    """P(y=1|x) = 1 / (1 + exp(-(a*x + b))), by Newton-Raphson.

    Two parameters and a concave log-likelihood, so this converges in a handful
    of steps from any sane start and needs no learning rate to tune.

    `l2` penalises large coefficients and exists for features that separate the
    classes perfectly somewhere in their range. Cosine does not — every value
    carries both labels — but accumulated confidence does: an exact-key match
    always produces 1.0 and is always a duplicate, so the unpenalised maximum
    likelihood is at infinity and Newton walks toward it until exp overflows.
    A small penalty keeps the fit finite without materially moving it where the
    data actually constrains it.
    """
    a, b = 1.0, 0.0
    design = np.column_stack([x, np.ones_like(x)])
    penalty = np.array([[l2, 0.0], [0.0, l2]])

    def penalised_log_likelihood(theta: np.ndarray) -> float:
        z = design @ theta
        # log(1+exp(z)) computed without overflowing on large positive z
        ll = float(np.sum(y * z - np.logaddexp(0.0, z)))
        return ll - 0.5 * l2 * float(theta @ theta)

    theta = np.array([a, b])
    current = penalised_log_likelihood(theta)
    for _ in range(iterations):
        p = _sigmoid(design @ theta)
        gradient = design.T @ (y - p) - l2 * theta
        weights = np.clip(p * (1.0 - p), 1e-9, None)
        hessian = design.T @ (design * weights[:, None]) + penalty
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            break

        # Backtrack. Where the feature saturates, p(1-p) hits the clip, the
        # Hessian degenerates to the penalty alone and the raw Newton step is
        # enormous — it ran to a slope of -98394 on accumulated confidence,
        # which separates perfectly at both ends. Only accept a step that
        # actually improves the objective.
        scale = 1.0
        for _ in range(40):
            candidate = theta + scale * step
            if penalised_log_likelihood(candidate) > current:
                break
            scale /= 2.0
        else:
            break

        theta = theta + scale * step
        previous, current = current, penalised_log_likelihood(theta)
        if abs(current - previous) < 1e-12:
            break
    return float(theta[0]), float(theta[1])


def _sigmoid(z: np.ndarray) -> np.ndarray:
    """Overflow-free: exp is only ever applied to a non-positive number."""
    out = np.empty_like(z, dtype=float)
    positive = z >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    exp_z = np.exp(z[~positive])
    out[~positive] = exp_z / (1.0 + exp_z)
    return out


def logistic(x: float, a: float, b: float) -> float:
    z = a * x + b
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def brier(predictions: list[float], labels: list[int]) -> float:
    """Mean squared error of probabilistic predictions. Lower is better."""
    return sum((p - y) ** 2 for p, y in zip(predictions, labels, strict=True)) / len(labels)


def log_loss(predictions: list[float], labels: list[int]) -> float:
    eps = 1e-12
    return -sum(
        y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps))
        for p, y in zip(predictions, labels, strict=True)
    ) / len(labels)


def reliability(predictions: list[float], labels: list[int], bins: int = 10) -> list[dict]:
    """Predicted probability against observed frequency, per bin.

    A calibrated curve tracks the diagonal. The incumbent is not trying to be a
    probability at all, so this is where the difference shows rather than in a
    single score.
    """
    out = []
    for index in range(bins):
        lo, hi = index / bins, (index + 1) / bins
        chosen = [
            (p, y) for p, y in zip(predictions, labels, strict=True) if lo <= p < hi or (index == bins - 1 and p == 1.0)
        ]
        if not chosen:
            continue
        out.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": len(chosen),
                "predicted": round(sum(p for p, _ in chosen) / len(chosen), 4),
                "observed": round(sum(y for _, y in chosen) / len(chosen), 4),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def build_dataset(pairs: int, embedder) -> list[dict]:
    duplicates, non_duplicates = fetch_pairs(pairs)
    rows = []
    for label, group in ((1, duplicates), (0, non_duplicates)):
        for first, second in group:
            rows.append(
                {
                    "label": label,
                    "cosine": _cosine_similarity(embedder.embed(first), embedder.embed(second)),
                    # Lexical overlap, computed without the embedding model, so
                    # it can flag suspect labels without using the feature being
                    # fitted.
                    "lexical": fuzzy_similarity(normalize_query_fuzzy(first), normalize_query_fuzzy(second)),
                    "a": first,
                    "b": second,
                }
            )
    return rows


def drop_suspect_labels(rows: list[dict], decile: float = 0.10) -> tuple[list[dict], float]:
    """Remove labelled duplicates with the least lexical overlap.

    Inspection of 100 false negatives put roughly a fifth of the duplicate
    labels wrong — pairs like "best history podcasts" against "best podcast in
    history" that are not the same question. Those tend to share few words.

    This is a blunt instrument and it biases the fit: genuine paraphrases with
    low lexical overlap are exactly what semantic matching is *for*, and this
    throws some of them away too. It is reported alongside the raw fit rather
    than instead of it, so the difference between the two is visible.
    """
    duplicates = [r for r in rows if r["label"] == 1]
    if not duplicates:
        return rows, 0.0
    cutoff = float(np.quantile([r["lexical"] for r in duplicates], decile))
    kept = [r for r in rows if r["label"] == 0 or r["lexical"] > cutoff]
    return kept, cutoff


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def evaluate(rows: list[dict], a: float, b: float) -> dict:
    fitted = [logistic(r["cosine"], a, b) for r in rows]
    incumbent = [_similarity_to_confidence(r["cosine"], "semantic") for r in rows]
    labels = [r["label"] for r in rows]
    return {
        "n": len(rows),
        "fitted": {"brier": round(brier(fitted, labels), 4), "log_loss": round(log_loss(fitted, labels), 4)},
        "incumbent": {"brier": round(brier(incumbent, labels), 4), "log_loss": round(log_loss(incumbent, labels), 4)},
        "reliability_fitted": reliability(fitted, labels),
        "reliability_incumbent": reliability(incumbent, labels),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit similarity -> confidence")
    parser.add_argument("--pairs", type=int, default=500)
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter

    # Wrapped, so the cosines fitted here are the cosines production computes.
    embedder = CacheEmbedder(OllamaEmbeddingAdapter(model=args.embed_model))

    print(f"embedding {args.pairs * 2} pairs ...", flush=True)
    rows = build_dataset(args.pairs, embedder)

    random.Random(args.seed).shuffle(rows)  # noqa: S311 — reproducible split, not cryptography
    split = int(len(rows) * 0.7)
    train_all, test = rows[:split], rows[split:]
    train_clean, cutoff = drop_suspect_labels(train_all)

    report: dict = {
        "provenance": provenance(),
        "pairs": args.pairs,
        "embedder": f"ollama/{args.embed_model}",
        "held_out": len(test),
    }

    print(f"\n{'fit':<22}{'a':>9}{'b':>9}   cosine at P=0.5")
    for name, train in (("raw labels", train_all), ("noise-adjusted", train_clean)):
        x = np.array([r["cosine"] for r in train], dtype=float)
        y = np.array([r["label"] for r in train], dtype=float)
        a, b = fit_logistic(x, y)
        midpoint = -b / a if a else float("nan")
        print(f"  {name:<20}{a:>9.3f}{b:>9.3f}{midpoint:>18.3f}")
        report[name] = {"a": round(a, 4), "b": round(b, 4), "midpoint": round(midpoint, 4), **evaluate(test, a, b)}
    report["noise_adjusted_cutoff"] = round(cutoff, 4)
    report["noise_adjusted_dropped"] = len(train_all) - len(train_clean)

    print(f"\nheld-out {len(test)} pairs — lower is better")
    print(f"{'fit':<22}{'Brier':>10}{'log loss':>11}")
    for name in ("raw labels", "noise-adjusted"):
        r = report[name]
        print(f"  {name:<20}{r['fitted']['brier']:>10.4f}{r['fitted']['log_loss']:>11.4f}")
    inc = report["raw labels"]["incumbent"]
    print(f"  {'incumbent (hand)':<20}{inc['brier']:>10.4f}{inc['log_loss']:>11.4f}")

    best = min(("raw labels", "noise-adjusted"), key=lambda n: report[n]["fitted"]["brier"])
    verdict = report[best]["fitted"]["brier"] < inc["brier"]
    report["adopt"] = bool(verdict)
    report["best_fit"] = best
    print(f"\n  {'ADOPT ' + best if verdict else 'KEEP THE INCUMBENT — the fit does not beat it out of sample'}")

    print(f"\ncosine -> confidence, {best} fit against incumbent")
    a, b = report[best]["a"], report[best]["b"]
    print(f"{'cosine':>8}{'fitted':>10}{'incumbent':>12}")
    for cos in (0.70, 0.75, 0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.99):
        print(f"{cos:>8.2f}{logistic(cos, a, b):>10.3f}{_similarity_to_confidence(cos, 'semantic'):>12.3f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else RESULTS_DIR / "confidence_curve_fit.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
