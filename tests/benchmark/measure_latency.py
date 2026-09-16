#!/usr/bin/env python3
"""Latency of the cached path and the generating path, with real generation.

WHAT THIS MEASURES
    Wall-clock time for a query that is served from cache, and for one that is
    not and therefore calls a model. Generation is REAL — an actual model
    producing actual tokens — which is what separates this from every other
    number in this directory.

WHAT IT DOES NOT MEASURE, AND THIS IS THE WHOLE CAVEAT
    A hosted provider over the internet. The generating side here is Ollama on
    localhost. That is real inference but it is not the deployment the README's
    "LLM latency (no cache) 12.5s avg" describes, and a local figure must not
    be substituted for it. Local inference on a developer machine and a hosted
    frontier model over a network are different quantities that happen to share
    a unit.

    Consequently the SPEEDUP RATIO IS NOT MEASURABLE HERE either, because its
    denominator is the hosted number.

WHY THE CACHED SIDE IS SPLIT IN TWO
    An exact-match hit can return before the query is ever embedded; a semantic
    hit cannot. Those are different code paths with different costs, and an
    average over a mix of them is a number whose value depends on the mix. They
    are reported separately and never combined.

    Both are measured against a LOCAL embedder. A deployment using a hosted
    embedding API adds a network round trip to the semantic path and nothing to
    the exact path, so the semantic figure here is a floor, not an estimate.

    python tests/benchmark/measure_latency.py --queries 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from bitmod.adapters.db_sqlite import SQLiteBackend  # noqa: E402
from bitmod.interfaces.llm import LLMMessage  # noqa: E402
from bitmod.proxy import BitmodProxy  # noqa: E402
from bitmod.router import LLMRouter  # noqa: E402

from tests.benchmark.dataset import fetch_support_corpus  # noqa: E402
from tests.benchmark.provenance import provenance  # noqa: E402
from tests.benchmark.run_inprocess_benchmark import _clear_scratch_db  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def summarise(samples: list[float]) -> dict:
    """Median alongside mean, because latency distributions are not symmetric.

    The README quotes an average. An average over a long-tailed distribution is
    dragged by its tail, so the median is carried beside it rather than instead
    of it — quoting only the friendlier of the two is the thing this file
    exists to avoid.
    """
    if not samples:
        return {"n": 0}
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "mean_ms": round(statistics.fmean(ordered), 1),
        "median_ms": round(statistics.median(ordered), 1),
        "min_ms": round(ordered[0], 1),
        "max_ms": round(ordered[-1], 1),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--queries", type=int, default=20, help="distinct intents to exercise")
    parser.add_argument("--gen-model", default="llama3.2", help="Ollama model used for REAL generation")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument(
        "--warm-phrasings",
        type=int,
        default=8,
        help=(
            "extra phrasings per intent stored before the semantic pass, reusing the already-generated "
            "answer. 0 reproduces the frozen cache, where the semantic pass records n=0 because nothing "
            "serves at 0.85."
        ),
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter
    from bitmod.adapters.llm_ollama import OllamaAdapter
    from bitmod.cache_engine import _get_config

    corpus = fetch_support_corpus()[: args.queries]
    print(f"{len(corpus)} intents; generation is REAL via ollama/{args.gen_model}", flush=True)

    db_path = RESULTS_DIR / "_latency_scratch.db"
    _clear_scratch_db(db_path)
    backend = SQLiteBackend(str(db_path))
    backend.initialize()

    llm = OllamaAdapter(model=args.gen_model, base_url=args.ollama_url)
    proxy = BitmodProxy(backend=backend, llm_router=LLMRouter(primary=llm), default_model=args.gen_model)
    proxy._embedder = OllamaEmbeddingAdapter(model=args.embed_model, base_url=args.ollama_url)

    # One loop, created before timing starts. OllamaAdapter.generate is async
    # and asyncio.run() would build and tear down a loop inside every measured
    # interval, charging loop setup to the model.
    loop = asyncio.new_event_loop()

    cfg = _get_config()
    provenance_info = provenance()

    cold: list[float] = []
    cached_answers: list[str] = []
    exact: list[float] = []
    semantic: list[float] = []
    generated_chars: list[int] = []

    # Pass 1 — cold. Every one of these calls the model for real.
    print("  cold pass (real generation, one model call each)", flush=True)
    for index, intent in enumerate(corpus, 1):
        question = intent.canonical_instruction
        messages = [{"role": "user", "content": question}]
        started = time.perf_counter()
        result = proxy._run_cache_pipeline(question, messages)
        if result.hit:
            continue  # should not happen on a clean db; excluded rather than mislabelled
        answer = loop.run_until_complete(
            llm.generate(messages=[LLMMessage(role="user", content=question)], model=args.gen_model)
        )
        text = answer.content
        elapsed = (time.perf_counter() - started) * 1000
        cold.append(elapsed)
        cached_answers.append(text)
        generated_chars.append(len(text))
        proxy._store_response(
            user_message=question,
            answer_text=text,
            model_used=args.gen_model,
            elapsed_ms=0,
            filters=result.filters or {},
            norm=result.norm,
            answer_key=result.answer_key,
            evidence=result.evidence,
            messages_for_context=messages,
        )
        print(f"    {index}/{len(corpus)}  {elapsed:.0f}ms", flush=True)

    # Pass 2 — exact. Byte-identical, so this can return before embedding.
    print("  exact pass (cached, no model call)", flush=True)
    for intent in corpus:
        question = intent.canonical_instruction
        started = time.perf_counter()
        result = proxy._run_cache_pipeline(question, [{"role": "user", "content": question}])
        elapsed = (time.perf_counter() - started) * 1000
        if result.hit:
            exact.append(elapsed)

    # Warming, before the semantic pass can measure anything.
    #
    # A cache holding ONE phrasing per intent serves almost no paraphrase at
    # serve_threshold 0.85 — support_frozen_1500.json puts it at 1.27%. The
    # first version of this file went straight from the cold pass to the
    # semantic pass and recorded n=0: not a fast path, no path at all.
    #
    # So additional phrasings are stored here, reusing the answer the cold pass
    # already generated. NO EXTRA GENERATION HAPPENS, and none is needed —
    # what is being timed is lookup, and the answer text is the same string
    # either way. This mirrors the benchmark's --warm arm.
    if args.warm_phrasings:
        print(f"  warming: {args.warm_phrasings} extra phrasings per intent (no generation)", flush=True)
        for intent, answer_text in zip(corpus, cached_answers):
            extras = [q for q in intent.queries if q.instruction != intent.canonical_instruction]
            for query in extras[: args.warm_phrasings]:
                messages = [{"role": "user", "content": query.instruction}]
                result = proxy._run_cache_pipeline(query.instruction, messages)
                if result.hit:
                    continue
                proxy._store_response(
                    user_message=query.instruction,
                    answer_text=answer_text,
                    model_used=args.gen_model,
                    elapsed_ms=0,
                    filters=result.filters or {},
                    norm=result.norm,
                    answer_key=result.answer_key,
                    evidence=result.evidence,
                    messages_for_context=messages,
                )

    # Pass 3 — semantic. A phrasing held out of both the cold and warming
    # passes, so the exact layer cannot serve it and the query must be embedded.
    print("  semantic pass (cached, one embedding call, no model call)", flush=True)
    semantic_attempts = 0
    for intent in corpus:
        alternates = [q for q in intent.queries if q.instruction != intent.canonical_instruction]
        held_out = alternates[args.warm_phrasings :]
        if not held_out:
            continue
        question = held_out[0].instruction
        semantic_attempts += 1
        started = time.perf_counter()
        result = proxy._run_cache_pipeline(question, [{"role": "user", "content": question}])
        elapsed = (time.perf_counter() - started) * 1000
        if result.hit:
            semantic.append(elapsed)

    report = {
        "measures": "wall-clock latency of the cached path and of the generating path",
        "generation": f"REAL — ollama/{args.gen_model} on {args.ollama_url}",
        "does_not_measure": [
            (
                "a hosted provider over a network. The generating figure here is LOCAL inference and is NOT "
                "comparable to the README's 12.5s, which describes a hosted model."
            ),
            "the speedup ratio, because its denominator is the hosted number this cannot produce",
            (
                "a deployment with a hosted embedder — that adds a round trip to the semantic path only, so "
                "the semantic figure here is a floor"
            ),
        ],
        "hardware_note": (
            "single developer machine, unloaded; no attempt made to control for thermal or background load"
        ),
        "embedder": f"ollama/{args.embed_model}",
        "run_config": {
            "serve_threshold": cfg.serve_threshold,
            "search_threshold": cfg.search_threshold,
            "accumulation_damping": cfg.accumulation_damping,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance_info,
        "cold_real_generation_local": summarise(cold),
        "cached_exact": summarise(exact),
        "cached_semantic": summarise(semantic),
        "cached_semantic_attempts": semantic_attempts,
        "cached_semantic_hit_rate": (round(len(semantic) / semantic_attempts, 4) if semantic_attempts else None),
        "warm_phrasings_per_intent": args.warm_phrasings,
        "generated_answer_chars": summarise([float(c) for c in generated_chars]),
    }

    loop.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"latency_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    _clear_scratch_db(db_path)

    print()
    for label, key in (
        ("cold (REAL gen, LOCAL)", "cold_real_generation_local"),
        ("cached — exact", "cached_exact"),
        ("cached — semantic", "cached_semantic"),
    ):
        s = report[key]
        if s["n"]:
            print(
                f"  {label:<24} n={s['n']:<3} mean {s['mean_ms']:>9.1f}ms  "
                f"median {s['median_ms']:>9.1f}ms  p95 {s['p95_ms']:>9.1f}ms"
            )
    print(f"\n  report written to {out_path}")


if __name__ == "__main__":
    main()
