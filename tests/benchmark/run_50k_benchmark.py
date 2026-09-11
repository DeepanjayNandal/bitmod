#!/usr/bin/env python3
"""BitMod 50K Production Benchmark — Two-Phase Cache Validation.

Phase A (Seeding): 50,000 queries sent slowly through the full pipeline.
  Every query hits the LLM, response is cached, facts decomposed, links learned.
  This builds the full knowledge graph. Expected: ~0% hit rate (cold start).

Phase B (Validation): 50,000 queries — heavily randomized mix designed to
  exercise ALL 9 cache layers simultaneously:
    - 20% exact repeats (Layer 1: exact match)
    - 20% paraphrased (Layer 2: semantic match)
    - 10% decomposable comparisons (Layer 3: composable cache)
    - 10% typo/fuzzy variants (Layer 4: fuzzy match)
    - 10% topic-adjacent queries (Layer 5: similarity links)
    - 10% fact-seeking queries (Layer 6: atomic facts)
    - 10% follow-up conversation turns (Layer 7: session cache)
    - 10% brand new queries (baseline — should mostly miss)

  Queries are shuffled randomly so layers are tested in interleaved order,
  not sequentially. This forces the Bayesian accumulation (Layer 9) to
  combine evidence from multiple layers on every query.

Progress updates every 100 queries. Full report saved to JSON.
Designed to run over a weekend if needed.

Usage:
    python tests/benchmark/run_50k_benchmark.py --proxy http://localhost:8000
    python tests/benchmark/run_50k_benchmark.py --proxy http://localhost:8000 --seed-queries 5000 --val-queries 5000
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
DATA_DIR = BENCHMARK_DIR / "data"
RESULTS_DIR = BENCHMARK_DIR / "results"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    query: str
    query_type: str
    phase: str  # "seed" or "validate"
    target_layers: str  # which layers this query is designed to test
    decision: str
    cache_hit: bool
    cache_layer: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


@dataclass
class PhaseReport:
    name: str
    total: int = 0
    hits: int = 0
    misses: int = 0
    errors: int = 0
    hit_rate: float = 0.0
    avg_latency_cached_ms: float = 0.0
    avg_latency_uncached_ms: float = 0.0
    by_type: dict = field(default_factory=dict)
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# Query generators for Phase B (each targets specific layers)
# ---------------------------------------------------------------------------

PARAPHRASE_PREFIXES = [
    "Can you explain ", "Tell me about ", "What do you know about ",
    "I'd like to understand ", "Please describe ", "Help me understand ",
    "Could you clarify ", "What exactly is ", "Break down ",
    "In simple terms, what is ", "Give me an overview of ",
    "What's the significance of ", "How would you define ",
]

PARAPHRASE_SUFFIXES = [
    "", " in simple terms", " briefly", " with examples",
    " and why it matters", " for a beginner", " in detail",
    " step by step", " from scratch", " and its implications",
]

COMPARISON_TEMPLATES = [
    "Compare {a} vs {b}",
    "What are the differences between {a} and {b}?",
    "{a} compared to {b} — which is better?",
    "How does {a} differ from {b}?",
    "{a} vs {b}: pros and cons",
]

FOLLOW_UP_TEMPLATES = [
    "Can you elaborate on that?",
    "What about the downsides?",
    "How does this apply in practice?",
    "Give me a specific example.",
    "What are the alternatives?",
    "Why is this important?",
    "Who uses this and why?",
    "What's the history behind this?",
    "How has this changed over time?",
    "What are common misconceptions about this?",
]

FACT_SEEKING_TEMPLATES = [
    "What is the definition of {topic}?",
    "List the key facts about {topic}.",
    "What are the main rules regarding {topic}?",
    "Give me statistics about {topic}.",
    "What procedures are involved in {topic}?",
]

RELATED_TEMPLATES = [
    "What are the alternatives to {topic}?",
    "What are the drawbacks of {topic}?",
    "What problems does {topic} solve?",
    "Is {topic} still relevant today?",
    "What's the future of {topic}?",
    "How do experts view {topic}?",
    "What are best practices for {topic}?",
    "What are the risks of {topic}?",
]


def _extract_topic(text: str) -> str:
    """Pull a topic phrase from a query."""
    text = re.sub(r"^(what is|explain|describe|tell me about|how does)\s+", "", text.lower().strip(), flags=re.IGNORECASE)
    text = text.rstrip("?.!").strip()
    words = text.split()[:6]
    return " ".join(words) if words else text[:50]


def _add_typos(text: str) -> str:
    """Add realistic typos to a query."""
    chars = list(text)
    n_typos = max(1, len(chars) // 20)  # ~5% character error rate
    for _ in range(n_typos):
        pos = random.randint(0, max(0, len(chars) - 2))
        action = random.choice(["swap", "drop", "double", "wrong"])
        if action == "swap" and pos < len(chars) - 1:
            chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
        elif action == "drop":
            chars.pop(pos)
        elif action == "double":
            chars.insert(pos, chars[pos])
        elif action == "wrong":
            chars[pos] = random.choice("abcdefghijklmnopqrstuvwxyz")
    return "".join(chars)


def generate_validation_queries(
    seed_queries: list[str],
    total: int = 50000,
) -> list[dict]:
    """Generate the Phase B validation corpus.

    Returns list of {"text": str, "type": str, "target_layers": str}
    """
    if not seed_queries:
        return []

    # Allocations
    n_exact = int(total * 0.20)
    n_paraphrase = int(total * 0.20)
    n_comparison = int(total * 0.10)
    n_fuzzy = int(total * 0.10)
    n_related = int(total * 0.10)
    n_facts = int(total * 0.10)
    n_followup = int(total * 0.10)
    n_new = total - n_exact - n_paraphrase - n_comparison - n_fuzzy - n_related - n_facts - n_followup

    queries = []

    # 20% exact repeats → Layer 1
    for _ in range(n_exact):
        q = random.choice(seed_queries)
        queries.append({"text": q, "type": "exact_repeat", "target_layers": "L1:exact"})

    # 20% paraphrased → Layer 2 (semantic) + Layer 4 (fuzzy)
    for _ in range(n_paraphrase):
        q = random.choice(seed_queries)
        topic = _extract_topic(q)
        prefix = random.choice(PARAPHRASE_PREFIXES)
        suffix = random.choice(PARAPHRASE_SUFFIXES)
        new_q = f"{prefix}{topic}{suffix}?"
        queries.append({"text": new_q, "type": "paraphrased", "target_layers": "L2:semantic+L4:fuzzy"})

    # 10% comparisons → Layer 3 (composable)
    for _ in range(n_comparison):
        q1, q2 = random.sample(seed_queries, min(2, len(seed_queries)))
        t1, t2 = _extract_topic(q1), _extract_topic(q2)
        template = random.choice(COMPARISON_TEMPLATES)
        new_q = template.format(a=t1, b=t2)
        queries.append({"text": new_q, "type": "comparison", "target_layers": "L3:composable"})

    # 10% typo/fuzzy → Layer 4 (fuzzy)
    for _ in range(n_fuzzy):
        q = random.choice(seed_queries)
        new_q = _add_typos(q)
        queries.append({"text": new_q, "type": "fuzzy_typo", "target_layers": "L4:fuzzy"})

    # 10% topic-adjacent → Layer 5 (similarity links)
    for _ in range(n_related):
        q = random.choice(seed_queries)
        topic = _extract_topic(q)
        template = random.choice(RELATED_TEMPLATES)
        new_q = template.format(topic=topic)
        queries.append({"text": new_q, "type": "related", "target_layers": "L5:similarity_links"})

    # 10% fact-seeking → Layer 6 (atomic facts)
    for _ in range(n_facts):
        q = random.choice(seed_queries)
        topic = _extract_topic(q)
        template = random.choice(FACT_SEEKING_TEMPLATES)
        new_q = template.format(topic=topic)
        queries.append({"text": new_q, "type": "fact_seeking", "target_layers": "L6:atomic_facts"})

    # 10% follow-ups → Layer 7 (session cache)
    for _ in range(n_followup):
        new_q = random.choice(FOLLOW_UP_TEMPLATES)
        queries.append({"text": new_q, "type": "followup", "target_layers": "L7:session"})

    # 10% brand new → baseline (should miss, tests L9 Bayesian with no evidence)
    for i in range(n_new):
        new_q = f"Novel question #{i}: What are the implications of {random.choice(seed_queries)[:30]} in a modern context?"
        queries.append({"text": new_q, "type": "novel", "target_layers": "L9:bayesian_baseline"})

    # Shuffle everything so layers are tested in random interleaved order
    random.shuffle(queries)
    return queries


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def send_query(client, text: str, query_type: str, phase: str, target_layers: str) -> QueryResult:
    """Send one query to the proxy."""
    start = time.perf_counter()
    try:
        resp = client.post(
            "/v1/chat",
            json={"message": text[:1500]},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        elapsed = (time.perf_counter() - start) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return QueryResult(
                query=text[:200], query_type=query_type, phase=phase,
                target_layers=target_layers,
                decision="SERVE" if data.get("cached") else "GENERATE",
                cache_hit=data.get("cached", False),
                cache_layer=data.get("cache_layer") or ("exact" if data.get("cached") else "llm"),
                latency_ms=elapsed,
                input_tokens=(data.get("token_usage") or {}).get("input_tokens", 0),
                output_tokens=(data.get("token_usage") or {}).get("output_tokens", 0),
            )
        return QueryResult(
            query=text[:200], query_type=query_type, phase=phase,
            target_layers=target_layers, decision="ERROR", cache_hit=False,
            cache_layer=f"http_{resp.status_code}", latency_ms=elapsed,
            error=resp.text[:200],
        )
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return QueryResult(
            query=text[:200], query_type=query_type, phase=phase,
            target_layers=target_layers, decision="ERROR", cache_hit=False,
            cache_layer="error", latency_ms=elapsed, error=str(e)[:200],
        )


def run_phase(
    client, queries: list[dict], phase_name: str, total_label: str,
    progress_interval: int = 100,
) -> tuple[list[QueryResult], PhaseReport]:
    """Run a batch of queries and produce a PhaseReport."""
    results = []
    t0 = time.perf_counter()

    for i, q in enumerate(queries):
        r = send_query(client, q["text"], q["type"], phase_name, q.get("target_layers", ""))
        results.append(r)

        if (i + 1) % progress_interval == 0 or (i + 1) == len(queries):
            hits = sum(1 for r in results if r.cache_hit)
            errors = sum(1 for r in results if r.decision == "ERROR")
            elapsed_s = time.perf_counter() - t0
            qps = (i + 1) / elapsed_s if elapsed_s > 0 else 0
            eta_s = (len(queries) - i - 1) / qps if qps > 0 else 0
            eta_h = eta_s / 3600
            print(f"    [{i + 1:,}/{len(queries):,}] "
                  f"Hit: {hits / (i + 1) * 100:.1f}% | "
                  f"Errors: {errors} | "
                  f"QPS: {qps:.1f} | "
                  f"ETA: {eta_h:.1f}h | "
                  f"{datetime.now().strftime('%H:%M:%S')}")

    duration = time.perf_counter() - t0

    # Compile report
    report = PhaseReport(name=phase_name)
    report.total = len(results)
    report.hits = sum(1 for r in results if r.cache_hit)
    report.misses = sum(1 for r in results if not r.cache_hit and r.decision != "ERROR")
    report.errors = sum(1 for r in results if r.decision == "ERROR")
    report.hit_rate = report.hits / max(report.total, 1)
    report.duration_s = duration

    cached_lats = [r.latency_ms for r in results if r.cache_hit]
    uncached_lats = [r.latency_ms for r in results if not r.cache_hit]
    report.avg_latency_cached_ms = sum(cached_lats) / max(len(cached_lats), 1) if cached_lats else 0
    report.avg_latency_uncached_ms = sum(uncached_lats) / max(len(uncached_lats), 1) if uncached_lats else 0

    # By type breakdown
    types = set(r.query_type for r in results)
    for t in sorted(types):
        type_results = [r for r in results if r.query_type == t]
        type_hits = sum(1 for r in type_results if r.cache_hit)
        report.by_type[t] = {
            "total": len(type_results),
            "hits": type_hits,
            "rate": type_hits / max(len(type_results), 1),
        }

    return results, report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BitMod 50K Production Benchmark")
    parser.add_argument("--proxy", required=True, help="Proxy URL (e.g., http://localhost:8000)")
    parser.add_argument("--seed-queries", type=int, default=50000, help="Phase A query count (default: 50000)")
    parser.add_argument("--val-queries", type=int, default=50000, help="Phase B query count (default: 50000)")
    parser.add_argument("--progress", type=int, default=100, help="Progress update interval (default: 100)")
    args = parser.parse_args()

    import httpx

    print("\n" + "=" * 65)
    print("  BITMOD 50K PRODUCTION BENCHMARK")
    print(f"  Phase A (Seed): {args.seed_queries:,} queries")
    print(f"  Phase B (Validate): {args.val_queries:,} queries")
    print(f"  Proxy: {args.proxy}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    client = httpx.Client(base_url=args.proxy, timeout=120.0)

    # Verify proxy
    try:
        health = client.get("/health")
        health.raise_for_status()
        print(f"\n  Proxy healthy: {health.json()}")
    except Exception as e:
        print(f"\n  ERROR: Proxy not reachable: {e}")
        return

    # Load query corpus from downloaded datasets
    project_root = BENCHMARK_DIR.parent.parent / "core"
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    print("\n  Loading datasets ...")
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("  ERROR: pyarrow required. pip install pyarrow")
        return

    # Collect raw queries from all available parquet files
    raw_queries = []
    for parquet_file in sorted(DATA_DIR.glob("*.parquet")):
        print(f"    Reading {parquet_file.name} ...")
        try:
            table = pq.read_table(parquet_file)
            rows = table.to_pylist()
            for row in rows:
                # Try various column names
                for col in ["instruction", "question", "text", "sentence1", "content"]:
                    val = row.get(col)
                    if val and isinstance(val, str) and 15 < len(val) < 500:
                        raw_queries.append(val.strip())
                        break
                # Also check nested conversation format
                conv = row.get("conversation")
                if isinstance(conv, list):
                    for msg in conv:
                        if isinstance(msg, dict) and msg.get("role") == "user":
                            c = str(msg.get("content", "")).strip()
                            if 15 < len(c) < 500:
                                raw_queries.append(c)
                # OASST2 format
                if row.get("role") == "prompter" and row.get("text"):
                    t = str(row["text"]).strip()
                    if 15 < len(t) < 500:
                        raw_queries.append(t)
        except Exception as e:
            print(f"      Error reading {parquet_file.name}: {e}")

    # Deduplicate
    raw_queries = list(dict.fromkeys(raw_queries))
    random.shuffle(raw_queries)
    print(f"  Loaded {len(raw_queries):,} unique queries from datasets")

    if len(raw_queries) < 100:
        print("  ERROR: Not enough queries. Download datasets first:")
        print("    python tests/benchmark/run_benchmark.py --download")
        return

    # Cap seed queries to available data (repeat if needed)
    seed_corpus = []
    while len(seed_corpus) < args.seed_queries:
        remaining = args.seed_queries - len(seed_corpus)
        seed_corpus.extend(raw_queries[:remaining])
    seed_corpus = seed_corpus[:args.seed_queries]

    # ══════════════════════════════════════════════════════════════
    # PHASE A: SEEDING (cold cache, every query hits LLM)
    # ══════════════════════════════════════════════════════════════

    print(f"\n  {'=' * 60}")
    print(f"  PHASE A: SEEDING — {len(seed_corpus):,} queries")
    print("  Building cache, decomposing facts, learning similarity links")
    print("  Expected hit rate: ~0% (cold start)")
    print(f"  {'=' * 60}")

    seed_batch = [{"text": q, "type": "seed", "target_layers": "all"} for q in seed_corpus]
    seed_results, seed_report = run_phase(client, seed_batch, "seed", f"{len(seed_corpus):,}", args.progress)

    print("\n  PHASE A COMPLETE:")
    print(f"    Queries:   {seed_report.total:,}")
    print(f"    Hits:      {seed_report.hits:,} ({seed_report.hit_rate * 100:.1f}%)")
    print(f"    Errors:    {seed_report.errors:,}")
    print(f"    Duration:  {seed_report.duration_s / 3600:.1f} hours")
    print(f"    Avg lat (cached):   {seed_report.avg_latency_cached_ms:.0f}ms")
    print(f"    Avg lat (uncached): {seed_report.avg_latency_uncached_ms:.0f}ms")

    # Save intermediate results
    _save_report("phase_a", seed_results, seed_report)

    # Collect queries that were successfully cached for Phase B
    cached_queries = [r.query for r in seed_results if not r.cache_hit and r.decision != "ERROR"]
    # Use original text (full length) for generating variants
    seeded_texts = seed_corpus[:len(cached_queries)] if cached_queries else seed_corpus

    # ══════════════════════════════════════════════════════════════
    # PHASE B: VALIDATION (warm cache, randomized multi-layer mix)
    # ══════════════════════════════════════════════════════════════

    print(f"\n  {'=' * 60}")
    print(f"  PHASE B: VALIDATION — {args.val_queries:,} queries")
    print("  Randomized mix testing all 9 layers simultaneously:")
    print("    20% exact repeats     → Layer 1 (exact match)")
    print("    20% paraphrased       → Layer 2 (semantic) + Layer 4 (fuzzy)")
    print("    10% comparisons       → Layer 3 (composable)")
    print("    10% typo variants     → Layer 4 (fuzzy)")
    print("    10% topic-adjacent    → Layer 5 (similarity links)")
    print("    10% fact-seeking      → Layer 6 (atomic facts)")
    print("    10% follow-ups        → Layer 7 (session cache)")
    print("    10% brand new         → Layer 9 (Bayesian baseline)")
    print(f"  {'=' * 60}")

    val_queries = generate_validation_queries(seeded_texts, total=args.val_queries)
    val_results, val_report = run_phase(client, val_queries, "validate", f"{len(val_queries):,}", args.progress)

    print("\n  PHASE B COMPLETE:")
    print(f"    Queries:   {val_report.total:,}")
    print(f"    Hits:      {val_report.hits:,} ({val_report.hit_rate * 100:.1f}%)")
    print(f"    Errors:    {val_report.errors:,}")
    print(f"    Duration:  {val_report.duration_s / 3600:.1f} hours")
    print(f"    Avg lat (cached):   {val_report.avg_latency_cached_ms:.0f}ms")
    print(f"    Avg lat (uncached): {val_report.avg_latency_uncached_ms:.0f}ms")
    print("\n    By query type:")
    for t, stats in sorted(val_report.by_type.items()):
        print(f"      {t:20s}  {stats['hits']:>5,}/{stats['total']:>5,}  ({stats['rate'] * 100:.1f}%)")

    _save_report("phase_b", val_results, val_report)

    # ══════════════════════════════════════════════════════════════
    # FINAL REPORT
    # ══════════════════════════════════════════════════════════════

    all_results = seed_results + val_results
    total_hits = sum(1 for r in all_results if r.cache_hit)
    total_queries = len(all_results)

    print(f"\n  {'=' * 60}")
    print("  FINAL RESULTS")
    print(f"  {'=' * 60}")
    print(f"  Total queries:        {total_queries:,}")
    print(f"  Total hits:           {total_hits:,}")
    print(f"  Overall hit rate:     {total_hits / max(total_queries, 1) * 100:.1f}%")
    print("")
    print(f"  Phase A (seed):       {seed_report.hit_rate * 100:.1f}% ({seed_report.hits:,}/{seed_report.total:,})")
    print(f"  Phase B (validate):   {val_report.hit_rate * 100:.1f}% ({val_report.hits:,}/{val_report.total:,})")
    print("")
    print(f"  Without BitMod cost:  ${total_queries * 0.006:.2f}")
    print(f"  With BitMod cost:     ${(total_queries - total_hits) * 0.006:.2f}")
    print(f"  Savings:              ${total_hits * 0.006:.2f} ({total_hits / max(total_queries, 1) * 100:.1f}%)")
    print("")
    print(f"  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  {'=' * 60}")

    # Save final combined report
    final = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed_queries": args.seed_queries,
        "val_queries": args.val_queries,
        "total_queries": total_queries,
        "total_hits": total_hits,
        "overall_hit_rate": total_hits / max(total_queries, 1),
        "phase_a": {
            "total": seed_report.total, "hits": seed_report.hits,
            "hit_rate": seed_report.hit_rate, "errors": seed_report.errors,
            "duration_s": seed_report.duration_s,
            "avg_latency_cached_ms": seed_report.avg_latency_cached_ms,
            "avg_latency_uncached_ms": seed_report.avg_latency_uncached_ms,
        },
        "phase_b": {
            "total": val_report.total, "hits": val_report.hits,
            "hit_rate": val_report.hit_rate, "errors": val_report.errors,
            "duration_s": val_report.duration_s,
            "avg_latency_cached_ms": val_report.avg_latency_cached_ms,
            "avg_latency_uncached_ms": val_report.avg_latency_uncached_ms,
            "by_type": val_report.by_type,
        },
    }
    report_path = RESULTS_DIR / f"50k_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(final, indent=2))
    print(f"\n  Report saved: {report_path}")

    client.close()


def _save_report(phase: str, results: list[QueryResult], report: PhaseReport):
    """Save intermediate results."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"50k_{phase}_{ts}.json"
    data = {
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": report.total, "hits": report.hits, "hit_rate": report.hit_rate,
            "errors": report.errors, "duration_s": report.duration_s,
            "by_type": report.by_type,
        },
        "results": [asdict(r) for r in results[-1000:]],  # last 1000 for detail
    }
    path.write_text(json.dumps(data, indent=2))
    print(f"    Saved: {path}")


if __name__ == "__main__":
    main()
