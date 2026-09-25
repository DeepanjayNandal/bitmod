#!/usr/bin/env python3
"""Latency through the running gateway — real HTTP, real generation.

The companion to measure_latency.py, which drives the pipeline in-process. That
one answers "what does the cache cost"; this one answers "what does a client
see", and the difference between them is the HTTP stack, which is exactly what
the README's cached-latency figure appears to include.

    docker compose up -d
    python tests/benchmark/measure_latency_http.py --calls 10

WHY THIS NEEDS NO API KEY
    A cached response never reaches a model, so the cached figure is complete
    and honest without any provider credential. Only the cold path calls a
    model, and it is reported separately and conditionally.

WHAT THE COLD NUMBER IS AND IS NOT
    It is real generation over real HTTP. It is NOT the README's "12.5s avg",
    which sits under a heading reading "Production workloads (GPT-4o /
    Claude)". Whatever model this gateway is configured with is recorded in the
    artifact; if that is a local Ollama then the number describes local
    inference on this machine and must not be quoted against that row.

    The SPEEDUP RATIO is computed and recorded because both of its terms are
    measured here — but it inherits the cold path's condition completely. A
    ratio against local inference is not a ratio against a hosted frontier
    model.

THREE CACHED PATHS, NOT ONE
    exact      byte-identical re-send; can return before the query is embedded
    semantic   a rephrasing; must embed, so it pays an embedding round trip

    They differ by orders of magnitude in-process and are never averaged
    together here. An "average cached latency" is a number whose value is set
    by the traffic mix rather than by the cache.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.benchmark.provenance import provenance  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Distinct enough that none is a paraphrase of another, so the cold pass really
# is 10 generations rather than 9 generations and a cache hit.
QUESTIONS = [
    "What is the process for requesting a refund on a damaged item?",
    "How do I change the shipping address on an order already placed?",
    "What payment methods are accepted for international orders?",
    "How long does a standard delivery take to arrive?",
    "What happens if I miss the delivery window twice?",
    "How do I cancel a subscription before the next billing date?",
    "What is the warranty period on electronics bought here?",
    "How do I apply a promotional discount code at checkout?",
    "What should I do if my package arrives with items missing?",
    "How do I update the email address on my account?",
]

# One rephrasing each, to exercise the semantic path rather than exact match.
REPHRASINGS = [
    "How can I get money back for something that arrived broken?",
    "Can I change where my order gets delivered after ordering?",
    "Which ways can I pay when ordering from abroad?",
    "How many days until normal shipping shows up?",
    "What if I am not home for delivery two times?",
    "How can I stop my subscription before I get charged again?",
    "How long are electronics covered if they break?",
    "Where do I enter a coupon when I am paying?",
    "My parcel came but some things were not inside, what now?",
    "How do I change the email on my profile?",
]


def summarise(samples: list[float]) -> dict:
    """Median beside mean. The README quotes an average, and an average over a
    long-tailed distribution is dragged by its tail."""
    if not samples:
        return {"n": 0}
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "mean_ms": round(statistics.fmean(ordered), 1),
        "median_ms": round(statistics.median(ordered), 1),
        "min_ms": round(ordered[0], 1),
        "max_ms": round(ordered[-1], 1),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
    }


def call(client: httpx.Client, url: str, message: str) -> tuple[float, bool, str]:
    started = time.perf_counter()
    response = client.post(url, json={"message": message, "stream": False})
    elapsed = (time.perf_counter() - started) * 1000
    if response.status_code in (401, 403):
        raise SystemExit(
            f"Gateway returned {response.status_code}. /v1/chat requires a read scope: set "
            "BITMOD_API_KEY to one of the gateway's BITMOD_API_KEYS before running this harness."
        )
    response.raise_for_status()
    body = response.json()
    answer = body.get("answer") or ""
    return elapsed, bool(body.get("cached", False)), answer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--calls", type=int, default=10, help="questions used; each is sent cold, exact, rephrased")
    parser.add_argument(
        "--provider",
        required=True,
        help=(
            "REQUIRED. The provider and model this gateway generates with, e.g. 'ollama/llama3.2 (local)' or "
            "'openai/gpt-4o'. Required rather than defaulted because the cold number and the speedup are "
            "meaningless without it, and a default would let it be omitted silently."
        ),
    )
    parser.add_argument(
        "--model-rationale",
        required=True,
        help=(
            "REQUIRED. Why THIS model. A cold-path figure is a statement about a model as much as about the "
            "product, and a 3B model makes generation look cheaper than any real deployment. Recording the "
            "reason stops a reader having to guess whether the model was chosen for realism or for the number."
        ),
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/v1/chat"
    questions = QUESTIONS[: args.calls]
    rephrasings = REPHRASINGS[: args.calls]

    cold: list[float] = []
    exact: list[float] = []
    semantic: list[float] = []
    semantic_served = 0

    # The gateway requires a read scope on /v1/chat. Set once on the client so
    # every call inherits it; unset BITMOD_API_KEY sends nothing, which keeps
    # this runnable against a gateway with auth disabled.
    import os

    _key = os.getenv("BITMOD_API_KEY", "")
    _auth = {"Authorization": f"ApiKey {_key}"} if _key else {}

    with httpx.Client(timeout=300, headers=_auth) as client:
        print(f"cold pass — {len(questions)} generations through {url}", flush=True)
        for index, question in enumerate(questions, 1):
            elapsed, cached, _ = call(client, url, question)
            if cached:
                print(f"  {index}: already cached, excluded from the cold set", flush=True)
                continue
            cold.append(elapsed)
            print(f"  {index}/{len(questions)}  {elapsed:.0f}ms", flush=True)

        print("exact pass — byte-identical re-sends", flush=True)
        for question in questions:
            elapsed, _, _ = call(client, url, question)
            exact.append(elapsed)

        print("semantic pass — rephrasings", flush=True)
        for rephrasing in rephrasings:
            elapsed, cached, _ = call(client, url, rephrasing)
            # ONLY timings that were actually served from cache. A rephrasing
            # that missed was generated, and its latency is a cold-path number
            # wearing a cached-path label — the first run of this script
            # reported a 3146ms "cached semantic" mean built entirely from
            # misses, which would have been a straightforwardly false figure.
            if cached:
                semantic.append(elapsed)
                semantic_served += 1

    cold_summary = summarise(cold)
    exact_summary = summarise(exact)
    semantic_summary = summarise(semantic)

    # Median over median is the headline, because every other figure this tool
    # prints and the README publishes is a median. The paragraph above the
    # README's latency table argues for medians on the grounds that a cold
    # mean is dragged by the first call loading the model, and then the speedup
    # silently used means anyway, which is how the README came to publish a
    # ratio no pair of its own numbers produces. The mean ratio is still
    # recorded in the artifact so the older figures remain traceable.
    speedup = None
    speedup_mean_basis = None
    if cold_summary.get("n") and exact_summary.get("n"):
        if exact_summary["median_ms"]:
            speedup = round(cold_summary["median_ms"] / exact_summary["median_ms"], 1)
        if exact_summary["mean_ms"]:
            speedup_mean_basis = round(cold_summary["mean_ms"] / exact_summary["mean_ms"], 1)

    report = {
        "harness": "HTTP through the running gateway (POST /v1/chat)",
        "measures": "what a client sees: cached latency, and generating latency for the configured provider",
        "base_url": args.base_url,
        "provider": args.provider,
        "model_rationale": args.model_rationale,
        "does_not_measure": [
            (
                "the README's '12.5s avg (GPT-4o / Claude)'. The cold figure describes whichever provider this "
                "gateway is configured with, recorded under 'provider' below."
            ),
            "any hosted provider unless 'provider' says so — check it before quoting the cold number or the speedup",
            "token savings; nothing here tokenizes",
        ],
        "cached_paths_are_not_one_number": (
            "exact and semantic are reported separately and never averaged. Exact can return before the query "
            "is embedded; semantic cannot. An average over them is set by the traffic mix, not by the cache."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance(),
        "cold_real_generation": cold_summary,
        "cold_per_call_ms": [round(x, 1) for x in cold],
        "cached_exact_per_call_ms": [round(x, 1) for x in exact],
        "cached_exact": exact_summary,
        "cached_semantic": semantic_summary,
        "cached_semantic_served": semantic_served,
        "cached_semantic_attempts": len(rephrasings),
        "speedup_cold_over_exact": speedup,
        "speedup_cold_over_exact_mean_basis": speedup_mean_basis,
        "speedup_condition": (
            "speedup_cold_over_exact is cold median over cached-exact median, matching every other "
            "figure here and in the README. speedup_cold_over_exact_mean_basis is the same ratio taken "
            "over means, which is what this field used to hold and what older artifacts report. Both "
            "inherit the cold path's provider condition entirely."
        ),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"latency_http_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2))

    print()
    for label, key in (
        ("cold (real generation)", "cold_real_generation"),
        ("cached — exact", "cached_exact"),
        ("cached — semantic", "cached_semantic"),
    ):
        s = report[key]
        if s["n"]:
            print(f"  {label:<24} n={s['n']:<3} mean {s['mean_ms']:>9.1f}ms  median {s['median_ms']:>9.1f}ms")
    note = "  <- bucket empty, nothing to report" if not semantic else ""
    print(f"  cached semantic served   {semantic_served}/{len(rephrasings)}{note}")
    if speedup:
        print(f"  speedup (cold / exact)   {speedup}x   (medians), provider-conditional, see artifact")
    if speedup_mean_basis:
        print(f"  speedup on means         {speedup_mean_basis}x   (recorded, not the headline)")
    print(f"\n  report written to {out_path}")


if __name__ == "__main__":
    main()
