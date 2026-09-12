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

    THE TRUTH IS NEAR STRICT, AND IT DEPENDS ON THE STRATUM. 373 rows disagree
    at 0.75 on the 4,600-query baseline. Classified by hand:

        quora passes         81-100% substantively correct  (census, 55 rows)
        conversation passes    5-10% substantively correct  (20 of 88, 20 of 230)

    85% of disagreements are conversation-pass, where a follow-up reaches an
    answer about a different subject entirely, so roughly a fifth are correct
    overall. See tests/benchmark/results/disagreement_classification.json —
    read its strata, not its weighted average.

    This supersedes an earlier figure of 19 of 33, which had no artifact behind
    it and described the quora mechanism only: cross-pair near-duplicates, which
    account for 15% of the disagreements it was being applied to. On that
    stratum it understated correctness; applied to the whole population it
    overstated it about fourfold.

    Both bounds are still reported, because neither is the answer on its own.

    python tests/benchmark/sweep_thresholds.py --rows <path> --budget <n>

--budget has no default. The tolerable error rate is a product judgement, not a
property of the code, so it is stated at the call site every time. It is also
denominated in rows of the supplied file — see its help text, and ADR-004.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


def read_payload(path: Path) -> dict:
    """Read a row dump, gzipped or not.

    The 4,600-row dumps are committed gzipped: around 3.8 MB of JSON compresses
    to roughly 0.3. Keeping them in the repo is the point — every row set this
    project has derived a decision from until now lived only in a scratchpad,
    which is why `threshold_sweep.json` cannot be regenerated and the damping
    fits cannot be re-derived at all.
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def detect_schema(payload: dict) -> str:
    """Which harness wrote this row file. The two are not interchangeable."""
    first = (payload.get("rows") or [{}])[0]
    if "kind" in first:
        return "quora"
    if "expected_hit" in first:
        return "inprocess"
    raise SystemExit("unrecognised row schema: expected 'kind' (quora pairs) or 'expected_hit' (in-process run)")


def load(path: Path) -> list[dict]:
    """Quora pair schema: one row per labelled pair, keyed on `kind`.

    Every row is scorable — the label says whether a serve would be right, for
    all of them.
    """
    payload = read_payload(path)
    rows = []
    for row in payload["rows"]:
        candidate = (row.get("best_candidate") or row.get("served_text") or "").strip()
        rows.append(
            {
                "confidence": float(row["total_confidence"]),
                "duplicate": row["kind"] == "duplicate",
                "own_partner": bool(candidate) and candidate == (row.get("correct_answer") or "").strip(),
                "scorable": True,
            }
        )
    return rows


def load_inprocess(path: Path, unlabelled: str) -> list[dict]:
    """In-process 4,600-query schema: `pass`, `expected_hit`, `expected_answers`.

    `expected_hit` is True where a correct serve is expected, False where any
    serve is wrong, and None for the 700 conversation-pass rows, which carry no
    label: a follow-up that misses on its first appearance is correct, not a
    recall failure.

    Those unlabelled rows are the 4,600-versus-3,900 split, and the caller must
    choose, because the two answer different questions:

        drop  remove them. Denominator 3,900, every remaining row scorable.
        keep  leave them in the denominator at 4,600 but never score them, so a
              serve on one is neither right nor wrong. This is ADR-004's
              convention — wrong answers counted on the labelled rows, the rate
              expressed over the whole run.

    `expected_answers` is a set of acceptable answers, not one answer. See
    Recorder.add in run_inprocess_benchmark.py for why 5_link_traversal has two.
    """
    payload = read_payload(path)
    rows = []
    for row in payload["rows"]:
        expected_hit = row.get("expected_hit")
        if expected_hit is None and unlabelled == "drop":
            continue
        candidate = (row.get("best_candidate") or row.get("served_text") or "").strip()
        acceptable = {a.strip() for a in (row.get("expected_answers") or []) if a and a.strip()}
        rows.append(
            {
                "confidence": float(row["total_confidence"]),
                "duplicate": expected_hit is True,
                "own_partner": bool(candidate) and candidate in acceptable,
                "scorable": expected_hit is not None,
            }
        )
    return rows


# The decision lives between 0.80 and 0.95, and a 0.05 grid cannot resolve it.
# At damping 0.5 the wrong-answer rate jumps from 7.0 to 19.0 per 1000 between
# 0.90 and 0.85, so every budget from 8 to 18 selects 0.90 — not because the
# answer is stable across that range but because the grid has no point inside
# it. Flatness that comes from missing points reads exactly like flatness that
# comes from the data. Coarse outside the region, 0.01 inside it.
FINE_FROM, FINE_TO = 80, 95


def thresholds(coarse_step: int = 5) -> list[float]:
    coarse = [value / 100 for value in range(30, FINE_FROM, coarse_step)]
    fine = [value / 100 for value in range(FINE_FROM, FINE_TO + 1)]
    return coarse + fine


def sweep(rows: list[dict], step: int = 5) -> list[dict]:
    total = len(rows)
    duplicates = sum(1 for r in rows if r["duplicate"])
    out = []
    for threshold in thresholds(step):
        served = [r for r in rows if r["confidence"] >= threshold]
        # Only scorable serves can be right or wrong. An unlabelled row that
        # serves is neither, so it stays in the denominator without being
        # counted against the threshold. Every quora row is scorable, so this
        # is the identity there.
        scored = [r for r in served if r["scorable"]]
        strict_right = sum(1 for r in scored if r["duplicate"] and r["own_partner"])
        lenient_right = sum(1 for r in scored if r["duplicate"])
        out.append(
            {
                "threshold": round(threshold, 2),
                "served": len(served),
                "scored": len(scored),
                "recall_strict": round(strict_right / duplicates, 4) if duplicates else None,
                "recall_lenient": round(lenient_right / duplicates, 4) if duplicates else None,
                "precision_strict": round(strict_right / len(scored), 4) if scored else None,
                "precision_lenient": round(lenient_right / len(scored), 4) if scored else None,
                "wrong_per_1000_sweepset_strict": round((len(scored) - strict_right) / total * 1000, 1),
                "wrong_per_1000_sweepset_lenient": round((len(scored) - lenient_right) / total * 1000, 1),
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
    parser.add_argument(
        "--unlabelled",
        choices=("drop", "keep"),
        default=None,
        help=(
            "in-process schema only, and required when the file contains unlabelled rows. "
            "'drop' removes them (denominator 3,900); 'keep' leaves them in the denominator "
            "(4,600) without ever scoring them, which is ADR-004's convention. The two are "
            "different questions, so there is no default."
        ),
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    path = Path(args.rows)
    payload = read_payload(path)
    schema = detect_schema(payload)

    if schema == "quora":
        if args.unlabelled is not None:
            parser.error("--unlabelled applies to the in-process schema; this file is quora pairs")
        rows = load(path)
    else:
        has_unlabelled = any(r.get("expected_hit") is None for r in payload["rows"])
        if has_unlabelled and args.unlabelled is None:
            parser.error(
                "this run contains unlabelled rows (expected_hit null). Pass --unlabelled drop "
                "for a 3,900-row denominator, or --unlabelled keep for 4,600 with those rows "
                "never scored. See ADR-004."
            )
        rows = load_inprocess(path, args.unlabelled or "keep")

    table = sweep(rows)

    duplicates = sum(1 for r in rows if r["duplicate"])
    scorable = sum(1 for r in rows if r["scorable"])
    denominator = {
        "rows_file": str(args.rows),
        "schema": schema,
        "rows": len(rows),
        "recall_eligible_rows": duplicates,
        "scorable_rows": scorable,
        "unscorable_rows": len(rows) - scorable,
        "unlabelled_policy": args.unlabelled if schema == "inprocess" else None,
    }

    print(f"rows file: {denominator['rows_file']}  (schema: {schema})")
    print(
        f"denominator: {denominator['rows']} rows — "
        f"{denominator['recall_eligible_rows']} where a correct serve is expected, "
        f"{denominator['scorable_rows']} scorable, {denominator['unscorable_rows']} unscorable"
    )
    if schema == "inprocess":
        print(f"unlabelled rows: {denominator['unlabelled_policy']}")
    print(f"budget: {args.budget} wrong per 1000 rows of THIS set — not ADR-004's 4,600-query rate.\n")
    print(f"{'thresh':>7}{'served':>8}{'recall':>18}{'precision':>18}{'wrong/1000 sweepset':>20}")
    print(f"{'':>7}{'':>8}{'strict':>9}{'lenient':>9}{'strict':>9}{'lenient':>9}{'strict':>10}{'lenient':>10}")
    for entry in table:
        ps = f"{entry['precision_strict']:.1%}" if entry["precision_strict"] is not None else "—"
        pl = f"{entry['precision_lenient']:.1%}" if entry["precision_lenient"] is not None else "—"
        rs = f"{entry['recall_strict']:.1%}" if entry["recall_strict"] is not None else "—"
        rl = f"{entry['recall_lenient']:.1%}" if entry["recall_lenient"] is not None else "—"
        print(
            f"{entry['threshold']:>7.2f}{entry['served']:>8}"
            f"{rs:>9}{rl:>9}"
            f"{ps:>9}{pl:>9}"
            f"{entry['wrong_per_1000_sweepset_strict']:>10.1f}{entry['wrong_per_1000_sweepset_lenient']:>10.1f}"
        )

    within = [e for e in table if e["wrong_per_1000_sweepset_lenient"] <= args.budget]
    print()
    if within:
        best = max(within, key=lambda e: e["recall_lenient"] or 0.0)
        print(
            f"  most recall inside the budget: threshold {best['threshold']:.2f} — "
            f"recall {(best['recall_lenient'] or 0.0):.1%} lenient / "
            f"{(best['recall_strict'] or 0.0):.1%} strict, "
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
