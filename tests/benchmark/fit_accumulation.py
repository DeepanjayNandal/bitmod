#!/usr/bin/env python3
"""Is accumulated confidence a probability? Measure, do not argue.

Layers combine as 1 - prod(1 - c_i) — noisy-OR, which assumes the layers are
conditionally independent given the label. They are not. Semantic similarity and
fuzzy similarity are computed from the same two strings; when one is high the
other usually is, so treating them as separate evidence counts the same signal
twice and the total overstates.

That was defensible while the inputs were arbitrary scores, because nobody read
the output as a probability. Calibrating the per-layer curve makes it worse, not
better: the inputs now *are* probabilities, so the output claims to be one, and
a threshold set against it reads as a false-positive budget it cannot honour.

So this checks the combiner the same way the per-layer curve was checked. Fit a
logistic on accumulated -> P(duplicate), compare calibration on held-out data
against the raw accumulated value, and report the reliability curve either way.
If noisy-OR is already calibrated, that is the finding and nothing changes.

Input is a rows file from the recall harness: one row per query with the
accumulated confidence, the per-layer contributions, and whether the pair was a
labelled duplicate.

    python tests/benchmark/fit_accumulation.py --rows <path>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

import numpy as np  # noqa: E402

from tests.benchmark.fit_confidence_curve import (  # noqa: E402
    brier,
    fit_logistic,
    log_loss,
    logistic,
    reliability,
)
from tests.benchmark.provenance import provenance  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_rows(path: Path, require_correct: bool) -> list[dict]:
    """One (accumulated confidence, label) pair per query.

    `require_correct` treats a hit that served some other cached entry as a
    negative rather than a positive. A duplicate whose partner is cached but
    which was answered from a different entry is a wrong answer, and counting
    it as recall would teach the fit that high confidence means correct when it
    did not.
    """
    payload = json.loads(path.read_text())
    rows = []
    for row in payload["rows"]:
        label = 1 if row["kind"] == "duplicate" else 0
        if require_correct and label == 1 and row.get("hit"):
            served = (row.get("served_text") or "").strip()
            expected = (row.get("correct_answer") or "").strip()
            if served and expected and served != expected:
                label = 0
        rows.append(
            {
                "x": float(row["total_confidence"]),
                "y": label,
                "layers": sorted({c["layer"] for c in row.get("contributions", [])}),
                "n_layers": len({c["layer"] for c in row.get("contributions", []) if c["confidence"] > 0}),
            }
        )
    return rows


def evaluate(rows: list[dict], a: float | None = None, b: float | None = None) -> dict:
    labels = [r["y"] for r in rows]
    raw = [min(max(r["x"], 0.0), 1.0) for r in rows]
    out = {
        "n": len(rows),
        "raw": {"brier": round(brier(raw, labels), 4), "log_loss": round(log_loss(raw, labels), 4)},
        "reliability_raw": reliability(raw, labels),
    }
    if a is not None and b is not None:
        fitted = [logistic(r["x"], a, b) for r in rows]
        out["fitted"] = {"brier": round(brier(fitted, labels), 4), "log_loss": round(log_loss(fitted, labels), 4)}
        out["reliability_fitted"] = reliability(fitted, labels)
    return out


def overstatement_by_layer_count(rows: list[dict]) -> list[dict]:
    """Where noisy-OR should go wrong, if the independence assumption is the problem.

    One contributing layer means no combining happened, so the accumulated value
    is whatever that layer said. Two or more means the assumption was used. If
    the total overstates because layers are correlated, the gap between claimed
    and observed should widen as more layers contribute.
    """
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        buckets.setdefault(min(row["n_layers"], 4), []).append(row)
    summary = []
    for count in sorted(buckets):
        group = buckets[count]
        claimed = sum(min(max(r["x"], 0.0), 1.0) for r in group) / len(group)
        observed = sum(r["y"] for r in group) / len(group)
        summary.append(
            {
                "contributing_layers": count,
                "n": len(group),
                "mean_claimed": round(claimed, 4),
                "observed_rate": round(observed, 4),
                "overstatement": round(claimed - observed, 4),
            }
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate accumulated confidence")
    parser.add_argument("--rows", required=True)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument(
        "--count-wrong-serves-as-negative",
        action="store_true",
        default=False,
        help=(
            "relabel a hit that returned a different entry's answer as a negative. Off by "
            "default: exact-string matching is too strict, because 19 of 33 such serves on "
            "inspection returned a semantically identical question from another pair — the "
            "corpus contains cross-pair near-duplicates. The target here is P(duplicate | "
            "accumulated), the same target the per-layer curve was fitted against."
        ),
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows = load_rows(Path(args.rows), args.count_wrong_serves_as_negative)
    random.Random(args.seed).shuffle(rows)  # noqa: S311 — reproducible split, not cryptography
    split = int(len(rows) * 0.7)
    train, test = rows[:split], rows[split:]

    # A whisper of regularisation. The feature separates perfectly at both ends
    # — accumulated 0.0 and 1.0 are near-deterministic — and the line search
    # handles the resulting flat curvature, but a small penalty costs nothing
    # and keeps the fit finite if the data shifts.
    a, b = fit_logistic(
        np.array([r["x"] for r in train], dtype=float),
        np.array([r["y"] for r in train], dtype=float),
        l2=0.01,
    )
    report = {
        "provenance": provenance(),
        "rows": args.rows,
        "a": round(a, 4),
        "b": round(b, 4),
        "held_out": evaluate(test, a, b),
    }
    report["overstatement"] = overstatement_by_layer_count(rows)

    held = report["held_out"]
    print(f"accumulated confidence as a probability — held out on {held['n']} queries\n")
    print(f"{'':<26}{'Brier':>10}{'log loss':>11}")
    print(f"  {'raw (noisy-OR)':<24}{held['raw']['brier']:>10.4f}{held['raw']['log_loss']:>11.4f}")
    print(f"  {'recalibrated':<24}{held['fitted']['brier']:>10.4f}{held['fitted']['log_loss']:>11.4f}")

    print("\nreliability — what it claimed against what happened")
    print(f"{'bin':<12}{'n':>5}{'claimed':>10}{'observed':>10}{'gap':>9}")
    for entry in held["reliability_raw"]:
        gap = entry["predicted"] - entry["observed"]
        print(f"{entry['bin']:<12}{entry['n']:>5}{entry['predicted']:>10.3f}{entry['observed']:>10.3f}{gap:>+9.3f}")

    print("\noverstatement by number of contributing layers")
    print(f"{'layers':>8}{'n':>7}{'claimed':>10}{'observed':>10}{'gap':>9}")
    for entry in report["overstatement"]:
        print(
            f"{entry['contributing_layers']:>8}{entry['n']:>7}{entry['mean_claimed']:>10.3f}"
            f"{entry['observed_rate']:>10.3f}{entry['overstatement']:>+9.3f}"
        )

    improved = held["fitted"]["brier"] < held["raw"]["brier"]
    print(f"\n  {'RECALIBRATE — noisy-OR is not calibrated' if improved else 'KEEP noisy-OR — already calibrated'}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else RESULTS_DIR / "accumulation_fit.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"  written to {out}")


if __name__ == "__main__":
    main()
