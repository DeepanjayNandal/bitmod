#!/usr/bin/env python3
"""Pick serve_threshold from the false-positive rate it produces, not by feel.

Confidence is a calibrated probability now, so the threshold is the error
budget stated as a number: serve when P(this answer is right) is at least X.
This reports what each choice of X costs in wrong answers per thousand queries.

TWO BOUNDS, NOT ONE
    Whether a serve was correct is not perfectly knowable from the labels. The
    corpus contains the same question in more than one pair, so a serve that
    returned another pair's answer is sometimes right and sometimes wrong.

    strict   only the pair's own partner counts as correct
    lenient  any serve on a labelled duplicate counts as correct

    Hand-classifying 33 such serves put 19 of them substantively correct, so
    the truth sits nearer the lenient bound — but both are reported rather than
    a single number resting on that judgement.

    python tests/benchmark/sweep_thresholds.py --rows <path> --budget <n>

--budget has no default. The tolerable error rate is a product judgement, not a
property of the code, so it is stated at the call site every time. It is also
denominated in rows of the supplied file — see its help text, and ADR-004.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    rows = []
    for row in payload["rows"]:
        best = (row.get("best_candidate") or row.get("served_text") or "").strip()
        rows.append(
            {
                "confidence": float(row["total_confidence"]),
                "duplicate": row["kind"] == "duplicate",
                "own_partner": bool(best) and best == (row.get("correct_answer") or "").strip(),
            }
        )
    return rows


def sweep(rows: list[dict], step: int = 5) -> list[dict]:
    total = len(rows)
    duplicates = sum(1 for r in rows if r["duplicate"])
    out = []
    for value in range(30, 100, step):
        threshold = value / 100
        served = [r for r in rows if r["confidence"] >= threshold]
        strict_right = sum(1 for r in served if r["duplicate"] and r["own_partner"])
        lenient_right = sum(1 for r in served if r["duplicate"])
        out.append(
            {
                "threshold": round(threshold, 2),
                "served": len(served),
                "recall_strict": round(strict_right / duplicates, 4),
                "recall_lenient": round(lenient_right / duplicates, 4),
                "precision_strict": round(strict_right / len(served), 4) if served else None,
                "precision_lenient": round(lenient_right / len(served), 4) if served else None,
                "wrong_per_1000_sweepset_strict": round((len(served) - strict_right) / total * 1000, 1),
                "wrong_per_1000_sweepset_lenient": round((len(served) - lenient_right) / total * 1000, 1),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Choose serve_threshold from its error rate")
    parser.add_argument("--rows", required=True)
    parser.add_argument(
        "--budget",
        type=float,
        required=True,
        help=(
            "tolerable wrong answers per 1000 ROWS IN THE SUPPLIED ROW FILE. For the quora "
            "sweep set this is 1000 rows, half labelled non-duplicates, so it is NOT comparable "
            "to ADR-004's 6-per-1000, which is measured over the 4,600-query mixed run. See "
            "docs/adr/004-damped-evidence-accumulation.md."
        ),
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows = load(Path(args.rows))
    table = sweep(rows)

    duplicates = sum(1 for r in rows if r["duplicate"])
    denominator = {
        "rows_file": str(args.rows),
        "rows": len(rows),
        "duplicates": duplicates,
        "non_duplicates": len(rows) - duplicates,
    }

    print(f"rows file: {denominator['rows_file']}")
    print(
        f"denominator: {denominator['rows']} rows "
        f"({denominator['duplicates']} labelled duplicates, "
        f"{denominator['non_duplicates']} labelled non-duplicates)"
    )
    print(f"budget: {args.budget} wrong per 1000 rows of THIS set — not ADR-004's 4,600-query rate.\n")
    print(f"{'thresh':>7}{'served':>8}{'recall':>18}{'precision':>18}{'wrong/1000 sweepset':>20}")
    print(f"{'':>7}{'':>8}{'strict':>9}{'lenient':>9}{'strict':>9}{'lenient':>9}{'strict':>10}{'lenient':>10}")
    for entry in table:
        ps = f"{entry['precision_strict']:.1%}" if entry["precision_strict"] is not None else "—"
        pl = f"{entry['precision_lenient']:.1%}" if entry["precision_lenient"] is not None else "—"
        print(
            f"{entry['threshold']:>7.2f}{entry['served']:>8}"
            f"{entry['recall_strict']:>9.1%}{entry['recall_lenient']:>9.1%}"
            f"{ps:>9}{pl:>9}"
            f"{entry['wrong_per_1000_sweepset_strict']:>10.1f}{entry['wrong_per_1000_sweepset_lenient']:>10.1f}"
        )

    within = [e for e in table if e["wrong_per_1000_sweepset_lenient"] <= args.budget]
    print()
    if within:
        best = max(within, key=lambda e: e["recall_lenient"])
        print(
            f"  most recall inside the budget: threshold {best['threshold']:.2f} — "
            f"recall {best['recall_lenient']:.1%} lenient / {best['recall_strict']:.1%} strict, "
            f"{best['wrong_per_1000_sweepset_lenient']:.1f} wrong per 1000 rows of this set"
        )
    else:
        cheapest = min(table, key=lambda e: e["wrong_per_1000_sweepset_lenient"])
        print(
            f"  no threshold meets {args.budget} per 1000. The cheapest is "
            f"{cheapest['threshold']:.2f} at {cheapest['wrong_per_1000_sweepset_lenient']:.1f} — "
            "the budget needs the qualification gate and verification layers, not confidence alone."
        )

    if args.out:
        Path(args.out).write_text(
            json.dumps({"budget": args.budget, "denominator": denominator, "sweep": table}, indent=2)
        )
        print(f"  written to {args.out}")


if __name__ == "__main__":
    main()
