#!/usr/bin/env python3
"""Bitmod cache benchmark — real dataset ingestion and performance measurement.

Downloads real conversational datasets, ingests them into the cache engine,
and runs queries to measure hit rates, token savings, and latency.

Usage:
    python tests/benchmark/run_benchmark.py --all
    python tests/benchmark/run_benchmark.py --download
    python tests/benchmark/run_benchmark.py --parse --queries 5000
    python tests/benchmark/run_benchmark.py --ingest --run
    python tests/benchmark/run_benchmark.py --all --skip-download --queries 1000
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BENCHMARK_DIR = Path(__file__).resolve().parent
DATA_DIR = BENCHMARK_DIR / "data"
RESULTS_DIR = BENCHMARK_DIR / "results"

# The repo root, so `tests.benchmark.dataset` imports when this runs as a
# script. Only core/ was added, and that happens further down inside main().
_REPO_ROOT = str(BENCHMARK_DIR.parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DATASETS = [
    {
        "name": "quora_question_pairs",
        "url": "https://huggingface.co/datasets/sentence-transformers/quora-duplicates/resolve/main/pair-class/train-00000-of-00001.parquet",
        "size_mb": 35,
        "format": "parquet",
        "description": "Question pairs with is_duplicate labels -- ground truth for semantic match",
    },
    {
        "name": "oasst2",
        "url": "https://huggingface.co/datasets/OpenAssistant/oasst2/resolve/main/data/train-00000-of-00001-88ba0162028a73fc.parquet",
        "size_mb": 63,
        "format": "parquet",
        "description": "135K messages in 13.8K conversation trees -- session-aware caching",
    },
    {
        "name": "alpaca",
        "url": "https://huggingface.co/datasets/tatsu-lab/alpaca/resolve/main/data/train-00000-of-00001-a09b74b3ef9c3b56.parquet",
        "size_mb": 24,
        "format": "parquet",
        "description": "52K instruction-following examples -- diverse query patterns",
    },
]

# Cost model (Claude Sonnet pricing per 1K tokens)
_INPUT_COST_PER_1K = 0.003
_OUTPUT_COST_PER_1K = 0.015
_AVG_INPUT_TOKENS = 500
_AVG_OUTPUT_TOKENS = 300


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkQuery:
    text: str
    query_type: str  # "exact_duplicate", "semantic_duplicate", "comparison", "multi_turn", "unique", "fuzzy"
    source: str
    conversation_id: str | None = None
    turn_number: int = 0
    duplicate_of: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class QueryResult:
    query: str
    query_type: str
    decision: str  # "SERVE", "GENERATE_WITH_CONTEXT", "GENERATE"
    cache_hit: bool
    layers_contributed: list[str]
    total_confidence: float
    input_tokens: int
    output_tokens: int
    latency_ms: float


# ---------------------------------------------------------------------------
# Phase 1: Download
# ---------------------------------------------------------------------------


def _progress_bar(current: int, total: int, width: int = 40) -> str:
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {pct:.0%} ({current / 1_048_576:.1f}/{total / 1_048_576:.1f} MB)"


def download_datasets(skip: bool = False) -> dict[str, Path]:
    """Download benchmark datasets to DATA_DIR. Returns {name: path}."""
    if skip:
        print("\n  [DOWNLOAD] Skipped (--skip-download)")
        paths = {}
        for ds in DATASETS:
            p = DATA_DIR / f"{ds['name']}.parquet"
            if p.exists():
                paths[ds["name"]] = p
                print(f"    Using cached: {ds['name']} ({p.stat().st_size / 1_048_576:.1f} MB)")
        return paths

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import httpx
    except ImportError:
        print("  ERROR: httpx is required. Install with: pip install httpx")
        return {}

    paths: dict[str, Path] = {}

    for ds in DATASETS:
        dest = DATA_DIR / f"{ds['name']}.parquet"

        if dest.exists():
            size_mb = dest.stat().st_size / 1_048_576
            print(f"    {ds['name']}: already downloaded ({size_mb:.1f} MB)")
            paths[ds["name"]] = dest
            continue

        print(f"    {ds['name']}: downloading (~{ds['size_mb']} MB) ...")
        print(f"      {ds['description']}")

        try:
            with httpx.stream("GET", ds["url"], follow_redirects=True, timeout=300.0) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(dest, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=131_072):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and downloaded % (1_048_576 * 5) < 131_072:
                            print(f"      {_progress_bar(downloaded, total)}", end="\r")

                size_mb = dest.stat().st_size / 1_048_576
                print(f"      Done: {size_mb:.1f} MB" + " " * 40)
                paths[ds["name"]] = dest

        except Exception as e:
            print(f"      FAILED: {e}")
            if dest.exists():
                dest.unlink()

    return paths


# ---------------------------------------------------------------------------
# Phase 2: Parse and extract queries
# ---------------------------------------------------------------------------


def _read_parquet(path: Path) -> list[dict]:
    """Read a parquet file into a list of dicts using pyarrow."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print(f"    WARNING: pyarrow not installed, cannot read {path.name}")
        print("    Install with: pip install pyarrow")
        return []

    table = pq.read_table(str(path))
    columns = table.column_names
    rows = []
    # Convert column-by-column for memory efficiency
    col_data = {col: table.column(col).to_pylist() for col in columns}
    n_rows = table.num_rows
    for i in range(n_rows):
        rows.append({col: col_data[col][i] for col in columns})
    return rows


def _add_typos(text: str) -> str:
    """Add realistic typos to a query string."""
    rng = random.Random()  # noqa: S311 -- benchmark generation
    chars = list(text)
    n_mutations = max(1, len(chars) // 20)

    for _ in range(n_mutations):
        if not chars:
            break
        op = rng.choice(["swap", "drop", "case"])
        idx = rng.randint(0, len(chars) - 1)
        if op == "swap" and idx < len(chars) - 1:
            chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
        elif op == "drop":
            chars.pop(idx)
        elif op == "case":
            chars[idx] = chars[idx].swapcase()

    return "".join(chars)


def parse_quora(path: Path, max_queries: int) -> tuple[list[BenchmarkQuery], list[dict]]:
    """Parse Quora question pairs. Returns (queries, knowledge_items)."""
    print(f"    Parsing {path.name} ...")
    rows = _read_parquet(path)
    if not rows:
        return [], []

    queries: list[BenchmarkQuery] = []
    knowledge: list[dict] = []
    seen_questions: set[str] = set()

    # The quora dataset has 'questions' column with nested dict structure
    # and 'is_duplicate' column
    limit = min(len(rows), max_queries * 3)  # oversample then trim

    for row in rows[:limit]:
        is_dup = row.get("is_duplicate")

        # Handle different column formats (quora, sentence-transformers, etc.)
        questions = row.get("questions")
        if isinstance(questions, dict):
            q1_text = questions.get("text", ["", ""])
            if isinstance(q1_text, list) and len(q1_text) >= 2:
                q1, q2 = q1_text[0], q1_text[1]
            else:
                continue
        elif "question1" in row and "question2" in row:
            q1, q2 = row["question1"], row["question2"]
        elif "sentence1" in row and "sentence2" in row:
            q1, q2 = row["sentence1"], row["sentence2"]
            if is_dup is None:
                is_dup = row.get("label", 0)
        else:
            continue

        if not q1 or not q2:
            continue
        q1, q2 = str(q1).strip(), str(q2).strip()
        if len(q1) < 10 or len(q2) < 10:
            continue

        # First question as unique
        if q1 not in seen_questions:
            seen_questions.add(q1)
            queries.append(BenchmarkQuery(
                text=q1,
                query_type="unique",
                source="quora_question_pairs",
            ))
            # Use q1 as knowledge content too (the question itself serves as content)
            knowledge.append({"question": q1, "answer": f"This is a question about: {q1}"})

        # Second question
        if is_dup and q2 not in seen_questions:
            seen_questions.add(q2)
            queries.append(BenchmarkQuery(
                text=q2,
                query_type="semantic_duplicate",
                source="quora_question_pairs",
                duplicate_of=q1,
            ))
        elif q2 not in seen_questions:
            seen_questions.add(q2)
            queries.append(BenchmarkQuery(
                text=q2,
                query_type="unique",
                source="quora_question_pairs",
            ))

        if len(queries) >= max_queries:
            break

    print(f"      Extracted {len(queries)} queries, {len(knowledge)} knowledge items")
    return queries, knowledge


def parse_oasst2(path: Path, max_queries: int) -> tuple[list[BenchmarkQuery], list[dict]]:
    """Parse OASST2 conversation trees. Returns (queries, knowledge_items)."""
    print(f"    Parsing {path.name} ...")
    rows = _read_parquet(path)
    if not rows:
        return [], []

    queries: list[BenchmarkQuery] = []
    knowledge: list[dict] = []

    # Build conversation tree: parent_id -> children
    by_id: dict[str, dict] = {}
    children_of: dict[str | None, list[str]] = {}

    for row in rows:
        msg_id = row.get("message_id", "")
        parent_id = row.get("parent_id")
        by_id[msg_id] = row
        children_of.setdefault(parent_id, []).append(msg_id)

    # Walk trees: root messages have parent_id = None
    roots = children_of.get(None, [])
    turn_counter: dict[str, int] = {}

    for root_id in roots:
        # BFS through conversation tree
        stack = [(root_id, 0)]
        tree_id = by_id.get(root_id, {}).get("message_tree_id", root_id)

        while stack:
            msg_id, depth = stack.pop(0)
            msg = by_id.get(msg_id)
            if msg is None:
                continue

            role = msg.get("role", "")
            text = str(msg.get("text", "")).strip()

            if not text or len(text) < 10:
                for child_id in children_of.get(msg_id, []):
                    stack.append((child_id, depth + 1))
                continue

            if role == "prompter":
                turn = turn_counter.get(tree_id, 0)
                turn_counter[tree_id] = turn + 1
                queries.append(BenchmarkQuery(
                    text=text,
                    query_type="multi_turn" if turn > 0 else "unique",
                    source="oasst2",
                    conversation_id=tree_id,
                    turn_number=turn,
                ))
            elif role == "assistant":
                # Store assistant responses as knowledge
                parent = by_id.get(msg.get("parent_id", ""))
                parent_text = str(parent.get("text", "")) if parent else ""
                if parent_text and len(text) > 20:
                    knowledge.append({
                        "question": parent_text[:200],
                        "answer": text[:2000],
                    })

            for child_id in children_of.get(msg_id, []):
                stack.append((child_id, depth + 1))

        if len(queries) >= max_queries:
            break

    queries = queries[:max_queries]
    print(f"      Extracted {len(queries)} queries, {len(knowledge)} knowledge items")
    return queries, knowledge


def parse_alpaca(path: Path, max_queries: int) -> tuple[list[BenchmarkQuery], list[dict]]:
    """Parse Alpaca instruction-following dataset. Returns (queries, knowledge_items)."""
    print(f"    Parsing {path.name} ...")
    rows = _read_parquet(path)
    if not rows:
        return [], []

    queries: list[BenchmarkQuery] = []
    knowledge: list[dict] = []

    for i, row in enumerate(rows):
        instruction = str(row.get("instruction", "")).strip()
        inp = str(row.get("input", "")).strip()
        output = str(row.get("output", "")).strip()

        if not instruction or len(instruction) < 10:
            continue

        # Combine instruction + input as the query
        query_text = f"{instruction} {inp}".strip() if inp else instruction
        query_text = query_text[:500]

        queries.append(BenchmarkQuery(
            text=query_text,
            query_type="unique",
            source="alpaca",
        ))

        if output and len(output) > 20:
            knowledge.append({
                "question": instruction[:200],
                "answer": output[:2000],
            })

        if len(queries) >= max_queries:
            break

    queries = queries[:max_queries]
    print(f"      Extracted {len(queries)} queries, {len(knowledge)} knowledge items")
    return queries, knowledge


def generate_synthetic(
    unique_queries: list[BenchmarkQuery],
    n_comparison: int = 500,
    n_exact_dup: int = 200,
    n_fuzzy: int = 300,
) -> list[BenchmarkQuery]:
    """Generate synthetic queries from the extracted unique queries."""
    rng = random.Random(42)  # noqa: S311
    synthetic: list[BenchmarkQuery] = []

    if not unique_queries:
        return synthetic

    unique_texts = [q.text for q in unique_queries if len(q.text) > 15]
    if not unique_texts:
        return synthetic

    # Comparison queries: "Compare {X} vs {Y}"
    for _ in range(min(n_comparison, len(unique_texts) // 2)):
        a, b = rng.sample(unique_texts, 2)
        # Extract topic from question (first 60 chars, strip question marks)
        topic_a = a[:60].rstrip("?").strip()
        topic_b = b[:60].rstrip("?").strip()
        synthetic.append(BenchmarkQuery(
            text=f"Compare {topic_a} vs {topic_b}",
            query_type="comparison",
            source="synthetic",
        ))

    # Exact duplicates
    for _ in range(n_exact_dup):
        q = rng.choice(unique_texts)
        synthetic.append(BenchmarkQuery(
            text=q,
            query_type="exact_duplicate",
            source="synthetic",
            duplicate_of=q,
        ))

    # Fuzzy queries (with typos)
    for _ in range(n_fuzzy):
        q = rng.choice(unique_texts)
        synthetic.append(BenchmarkQuery(
            text=_add_typos(q),
            query_type="fuzzy",
            source="synthetic",
            duplicate_of=q,
        ))

    print(f"      Generated {len(synthetic)} synthetic queries "
          f"({n_comparison} comparison, {n_exact_dup} exact_dup, {n_fuzzy} fuzzy)")
    return synthetic


def parse_datasets(
    dataset_paths: dict[str, Path],
    max_queries: int = 50000,
) -> tuple[list[BenchmarkQuery], list[dict]]:
    """Parse all downloaded datasets and generate synthetic queries."""
    print("\n  [PARSE] Extracting queries from datasets ...")

    all_queries: list[BenchmarkQuery] = []
    all_knowledge: list[dict] = []

    # Budget allocation per dataset
    n_datasets = len(dataset_paths)
    if n_datasets == 0:
        print("    No datasets available. Cannot parse.")
        return [], []

    per_dataset = max_queries // (n_datasets + 1)  # +1 for synthetic budget

    parsers = {
        "quora_question_pairs": parse_quora,
        "oasst2": parse_oasst2,
        "alpaca": parse_alpaca,
    }

    for name, path in dataset_paths.items():
        parser = parsers.get(name)
        if parser is None:
            print(f"    No parser for {name}, skipping")
            continue
        try:
            queries, knowledge = parser(path, per_dataset)
            all_queries.extend(queries)
            all_knowledge.extend(knowledge)
        except Exception as e:
            print(f"    ERROR parsing {name}: {e}")

    # Generate synthetic queries from unique ones
    unique_queries = [q for q in all_queries if q.query_type == "unique"]
    remaining = max_queries - len(all_queries)
    n_syn_comparison = min(500, remaining // 3)
    n_syn_exact = min(200, remaining // 4)
    n_syn_fuzzy = min(300, remaining // 4)

    print("    Generating synthetic queries ...")
    synthetic = generate_synthetic(
        unique_queries,
        n_comparison=n_syn_comparison,
        n_exact_dup=n_syn_exact,
        n_fuzzy=n_syn_fuzzy,
    )
    all_queries.extend(synthetic)

    # Shuffle to interleave query types
    rng = random.Random(42)  # noqa: S311
    rng.shuffle(all_queries)

    # Trim to max
    all_queries = all_queries[:max_queries]

    # Print summary
    type_counts: dict[str, int] = {}
    for q in all_queries:
        type_counts[q.query_type] = type_counts.get(q.query_type, 0) + 1
    print(f"\n    Total queries: {len(all_queries)}")
    for qt, count in sorted(type_counts.items()):
        print(f"      {qt:<22s} {count:>6d}")
    print(f"    Knowledge items: {len(all_knowledge)}")

    return all_queries, all_knowledge


# ---------------------------------------------------------------------------
# Phase 3: Ingest knowledge base
# ---------------------------------------------------------------------------


def ingest_knowledge(
    bm: Bitmod,
    knowledge: list[dict],
    max_items: int = 5000,
) -> int:
    """Ingest knowledge items into Bitmod so the cache has content to serve."""
    print(f"\n  [INGEST] Ingesting up to {max_items} knowledge items ...")

    count = 0
    errors = 0
    t0 = time.perf_counter()

    # Deduplicate and limit
    seen: set[str] = set()
    items = []
    for item in knowledge:
        key = item["question"][:100]
        if key not in seen:
            seen.add(key)
            items.append(item)
        if len(items) >= max_items:
            break

    for i, item in enumerate(items):
        try:
            bm.ingest(
                item["answer"],
                title=item["question"][:100],
            )
            count += 1
        except Exception:
            errors += 1

        if (i + 1) % 500 == 0:
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"    [{i + 1}/{len(items)}] {rate:.0f} items/sec | {errors} errors")

    elapsed = time.perf_counter() - t0
    print(f"    Done: {count} ingested, {errors} errors in {elapsed:.1f}s")
    return count


# ---------------------------------------------------------------------------
# Phase 4: Run benchmark
# ---------------------------------------------------------------------------


def _seed_cache_for_query(bm: Bitmod, query: BenchmarkQuery, knowledge: list[dict]) -> None:
    """For exact_duplicate queries, ensure the original is in the cache first."""
    if query.duplicate_of:
        # Simulate: store the original query's answer in cache so duplicates can hit
        from bitmod.cache_engine import compute_answer_key, normalize_for_key, store_answer

        backend = bm._get_backend()
        answer_key = compute_answer_key(query.duplicate_of, {})
        normalized = normalize_for_key(query.duplicate_of)

        # Find a knowledge item that matches, or generate a stub
        answer_text = f"Answer for: {query.duplicate_of}"
        for k in knowledge[:100]:
            if k["question"][:50] in query.duplicate_of or query.duplicate_of[:50] in k["question"]:
                answer_text = k["answer"]
                break

        with backend.session() as session:
            # Only store if not already cached
            from bitmod.cache_engine import try_cache

            existing = try_cache(backend, session, query.duplicate_of, {})
            if existing is None:
                store_answer(
                    backend,
                    session,
                    answer_key=answer_key,
                    question_raw=query.duplicate_of,
                    question_normalized=normalized,
                    filters={},
                    answer_text=answer_text,
                    source_sections=[],
                    model_used="benchmark-seed",
                    generation_ms=0,
                )


def run_benchmark(
    queries: list[BenchmarkQuery],
    knowledge: list[dict],
    db_path: str,
) -> list[QueryResult]:
    """Run all queries through the Bitmod cache engine."""
    print(f"\n  [BENCHMARK] Running {len(queries)} queries ...")

    # Add project root to path for imports
    project_root = BENCHMARK_DIR.parent.parent / "core"
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import os

    from bitmod.api import Bitmod
    os.environ["BITMOD_SQLITE_PATH"] = str(db_path)
    bm = Bitmod()
    # Ensure backend is initialized with full schema
    backend = bm._get_backend()

    # Pre-seed cache for exact duplicates so they can actually hit
    print("    Pre-seeding cache for duplicate detection ...")
    seed_count = 0
    dup_queries = [q for q in queries if q.query_type == "exact_duplicate" and q.duplicate_of]
    seen_originals: set[str] = set()
    for q in dup_queries:
        if q.duplicate_of and q.duplicate_of not in seen_originals:
            seen_originals.add(q.duplicate_of)
            _seed_cache_for_query(bm, q, knowledge)
            seed_count += 1
    print(f"    Seeded {seed_count} cache entries for duplicate testing")

    # Full 9-layer pipeline — uses bm.query() which runs all cache layers + LLM fallback
    results: list[QueryResult] = []
    t0 = time.perf_counter()

    for i, query in enumerate(queries):
        start = time.perf_counter()

        try:
            result = bm.query(query.text, timeout=30)
            elapsed = (time.perf_counter() - start) * 1000

            cache_hit = getattr(result, "cached", False)
            cache_layer = getattr(result, "cache_layer", None) or ("cache" if cache_hit else "llm")
            answer = getattr(result, "answer", "") or ""
            token_usage = getattr(result, "token_usage", {}) or {}

            results.append(QueryResult(
                query=query.text[:200],
                query_type=query.query_type,
                decision="SERVE" if cache_hit else "GENERATE",
                cache_hit=cache_hit,
                layers_contributed=[cache_layer],
                total_confidence=1.0 if cache_hit else 0.0,
                input_tokens=token_usage.get("input_tokens", 0) if not cache_hit else 0,
                output_tokens=token_usage.get("output_tokens", 0) if not cache_hit else 0,
                latency_ms=elapsed,
            ))
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            results.append(QueryResult(
                query=query.text[:200],
                query_type=query.query_type,
                decision="ERROR",
                cache_hit=False,
                layers_contributed=["error"],
                total_confidence=0.0,
                input_tokens=max(1, len(query.text) // 4),
                output_tokens=0,
                latency_ms=elapsed,
            ))

        if (i + 1) % 100 == 0:
            hit_rate = sum(1 for r in results if r.cache_hit) / len(results) * 100
            avg_lat = sum(r.latency_ms for r in results) / len(results)
            wall = time.perf_counter() - t0
            qps = (i + 1) / wall if wall > 0 else 0
            print(f"    [{i + 1}/{len(queries)}] "
                  f"Hit: {hit_rate:.1f}% | "
                  f"Avg lat: {avg_lat:.1f}ms | "
                  f"QPS: {qps:.0f}")

    bm.close()
    total_time = time.perf_counter() - t0
    print(f"    Completed {len(results)} queries in {total_time:.1f}s "
          f"({len(results) / total_time:.0f} queries/sec)")

    return results


def _send_query(client, query: BenchmarkQuery, pass_name: str) -> QueryResult:
    """Send a single query through the nine-layer pipeline and record what served it.

    Posts to /v1/chat/completions, not /v1/chat. The latter proxies to the chat
    service, which has its own simpler cache path — _run_cache_pipeline, and
    therefore layers 7, 8 and 9, is reached only through the OpenAI, Anthropic
    and Gemini format endpoints. Measuring /v1/chat would have reported those
    layers as contributing nothing because they were never invoked.

    Attribution comes from the X-Bitmod-Cache-* response headers, which the
    proxy emits when debug output is enabled. It was previously inferred from
    the body: a single layer label that defaulted to "exact" whenever the trace
    carried no HIT step, which is every serve decided on accumulated confidence.
    """
    start = time.perf_counter()
    try:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": query.text[:1000]}],
            },
            headers={
                "X-Bitmod-Debug": "true",
                # The CSRF middleware rejects a POST without this whenever auth
                # is disabled, which is how the benchmark runs the gateway.
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        elapsed = (time.perf_counter() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            headers = resp.headers
            cache_hit = str(headers.get("x-bitmod-cache", "")).lower() == "hit"
            if not cache_hit:
                cache_hit = str(headers.get("x-bitmod-cache-hit", "")).lower() == "true"

            layers = []
            raw_layers = headers.get("x-bitmod-cache-layers", "")
            for entry in raw_layers.split(",") if raw_layers else []:
                name, _, _conf = entry.partition(":")
                if name:
                    layers.append(name)
            served_by = headers.get("x-bitmod-cache-served-by", "")
            if served_by and served_by not in layers:
                layers.append(served_by)
            if not layers:
                layers = [served_by or ("llm" if not cache_hit else "unknown")]

            try:
                confidence = float(headers.get("x-bitmod-cache-confidence", "0") or 0)
            except ValueError:
                confidence = 0.0

            usage = data.get("usage", {}) or {}
            return QueryResult(
                query=query.text[:200],
                query_type=f"{pass_name}:{query.query_type}",
                decision=headers.get("x-bitmod-cache-decision", "SERVE" if cache_hit else "GENERATE"),
                cache_hit=cache_hit,
                layers_contributed=layers,
                total_confidence=confidence,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=elapsed,
            )
        else:
            elapsed = (time.perf_counter() - start) * 1000
            return QueryResult(
                query=query.text[:200], query_type=f"{pass_name}:{query.query_type}",
                decision="ERROR", cache_hit=False,
                layers_contributed=[f"http_{resp.status_code}"],
                total_confidence=0.0, input_tokens=max(1, len(query.text) // 4),
                output_tokens=0, latency_ms=elapsed,
            )
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return QueryResult(
            query=query.text[:200], query_type=f"{pass_name}:{query.query_type}",
            decision="ERROR", cache_hit=False, layers_contributed=["error"],
            total_confidence=0.0, input_tokens=max(1, len(query.text) // 4),
            output_tokens=0, latency_ms=elapsed,
        )


def _generate_paraphrases(queries: list[BenchmarkQuery]) -> list[BenchmarkQuery]:
    """Generate paraphrased versions of queries for Pass 2."""
    import random as _rnd

    prefixes = [
        "Can you explain ", "Tell me about ", "What do you know about ",
        "I'd like to understand ", "Please describe ", "Help me understand ",
        "What's the deal with ", "Could you clarify ",
    ]
    suffixes = [
        "", " in simple terms", " briefly", " with examples",
        " and why it matters", " for a beginner",
    ]
    paraphrased = []
    for q in queries:
        text = q.text.strip().rstrip("?").rstrip(".")
        # Strip existing question prefixes
        for strip in ["what is ", "what are ", "how does ", "explain ", "describe "]:
            if text.lower().startswith(strip):
                text = text[len(strip):]
                break
        new_text = _rnd.choice(prefixes) + text + _rnd.choice(suffixes) + "?"
        paraphrased.append(BenchmarkQuery(
            text=new_text, query_type="paraphrased",
            source=q.source, conversation_id=q.conversation_id,
        ))
    return paraphrased


def _generate_related(queries: list[BenchmarkQuery]) -> list[BenchmarkQuery]:
    """Generate related but different queries for Pass 3."""
    import random as _rnd

    follow_ups = [
        "What are the alternatives to {topic}?",
        "What are the drawbacks of {topic}?",
        "How does {topic} compare to its competitors?",
        "What's the history of {topic}?",
        "Who uses {topic} and why?",
        "What are best practices for {topic}?",
        "Is {topic} still relevant?",
        "What problems does {topic} solve?",
    ]
    related = []
    for q in queries:
        # Extract a topic from the query (first 3-5 meaningful words)
        words = [w for w in q.text.split() if len(w) > 2][:5]
        topic = " ".join(words) if words else q.text[:50]
        template = _rnd.choice(follow_ups)
        new_text = template.format(topic=topic)
        related.append(BenchmarkQuery(
            text=new_text, query_type="related",
            source=q.source, conversation_id=q.conversation_id,
        ))
    return related


def run_benchmark_proxy(
    queries: list[BenchmarkQuery],
    proxy_url: str = "http://localhost:8000",
) -> list[QueryResult]:
    """Multi-pass benchmark through proxy — tests all 9 cache layers.

    Pass 1: Original queries (cold cache — warms it up, builds similarity links, decomposes facts)
    Pass 2: Paraphrased versions of same queries (tests semantic match, fuzzy match)
    Pass 3: Related but different queries (tests similarity links, atomic facts, session cache)

    Requires the gateway to be running (bitmod serve or bitmod proxy).
    """
    import random as _rnd

    import httpx

    print(f"\n  [BENCHMARK] Multi-pass benchmark via {proxy_url}")
    print("    Testing ALL 9 cache layers across 3 passes:")
    print("      Pass 1: Original queries (cache warmup)")
    print("      Pass 2: Paraphrased queries (semantic + fuzzy)")
    print("      Pass 3: Related queries (similarity links + atomic facts)")

    client = httpx.Client(base_url=proxy_url, timeout=120.0)

    # Verify proxy is up
    try:
        health = client.get("/health")
        health.raise_for_status()
        print(f"    Proxy healthy: {health.json()}")
    except Exception as e:
        print(f"    ERROR: Proxy not reachable at {proxy_url}: {e}")
        print("    Start with: bitmod serve  OR  bitmod proxy")
        return []

    all_results: list[QueryResult] = []
    t0 = time.perf_counter()

    # --- PASS 1: Original queries (cache warmup) ---
    print(f"\n    ── Pass 1: Cache Warmup ({len(queries)} queries) ──")
    print("    Expected: ~0% hit rate (cold cache)")
    pass1_results = []
    for i, q in enumerate(queries):
        r = _send_query(client, q, "pass1")
        pass1_results.append(r)
        all_results.append(r)
        if (i + 1) % 10 == 0 or (i + 1) == len(queries):
            hits = sum(1 for r in pass1_results if r.cache_hit)
            errors = sum(1 for r in pass1_results if r.decision == "ERROR")
            print(f"      [{i + 1}/{len(queries)}] Hits: {hits} | Errors: {errors}")

    p1_hits = sum(1 for r in pass1_results if r.cache_hit)
    p1_total = len(pass1_results)
    print(f"    Pass 1 complete: {p1_hits}/{p1_total} hits ({p1_hits / max(p1_total, 1) * 100:.1f}%)")

    # --- PASS 2: Exact repeats + paraphrased (tests exact + semantic + fuzzy) ---
    # Mix: 40% exact repeats, 60% paraphrased
    n_exact_repeat = max(1, len(queries) * 2 // 5)
    n_paraphrased = len(queries) - n_exact_repeat

    repeat_queries = [BenchmarkQuery(text=q.text, query_type="exact_repeat", source=q.source)
                      for q in _rnd.sample(queries, min(n_exact_repeat, len(queries)))]
    paraphrased_queries = _generate_paraphrases(
        _rnd.sample(queries, min(n_paraphrased, len(queries)))
    )
    pass2_queries = repeat_queries + paraphrased_queries
    _rnd.shuffle(pass2_queries)

    print(f"\n    ── Pass 2: Repeats + Paraphrases ({len(pass2_queries)} queries) ──")
    print(f"    {len(repeat_queries)} exact repeats + {len(paraphrased_queries)} paraphrased")
    print("    Expected: ~40-80% hit rate (exact hits + semantic matches)")
    pass2_results = []
    for i, q in enumerate(pass2_queries):
        r = _send_query(client, q, "pass2")
        pass2_results.append(r)
        all_results.append(r)
        if (i + 1) % 10 == 0 or (i + 1) == len(pass2_queries):
            hits = sum(1 for r in pass2_results if r.cache_hit)
            errors = sum(1 for r in pass2_results if r.decision == "ERROR")
            print(f"      [{i + 1}/{len(pass2_queries)}] Hits: {hits} | Errors: {errors}")

    p2_hits = sum(1 for r in pass2_results if r.cache_hit)
    p2_total = len(pass2_results)
    p2_repeat_hits = sum(1 for r in pass2_results if r.cache_hit and "exact_repeat" in r.query_type)
    p2_para_hits = sum(1 for r in pass2_results if r.cache_hit and "paraphrased" in r.query_type)
    print(f"    Pass 2 complete: {p2_hits}/{p2_total} hits ({p2_hits / max(p2_total, 1) * 100:.1f}%)")
    print(f"      Exact repeats: {p2_repeat_hits}/{len(repeat_queries)} ({p2_repeat_hits / max(len(repeat_queries), 1) * 100:.1f}%)")
    print(f"      Paraphrased:   {p2_para_hits}/{len(paraphrased_queries)} ({p2_para_hits / max(len(paraphrased_queries), 1) * 100:.1f}%)")

    # --- PASS 3: Related queries (tests similarity links, atomic facts) ---
    related_queries = _generate_related(
        _rnd.sample(queries, min(len(queries), len(queries)))
    )

    print(f"\n    ── Pass 3: Related Queries ({len(related_queries)} queries) ──")
    print("    Expected: ~10-30% hit rate (similarity links + atomic facts)")
    pass3_results = []
    for i, q in enumerate(related_queries):
        r = _send_query(client, q, "pass3")
        pass3_results.append(r)
        all_results.append(r)
        if (i + 1) % 10 == 0 or (i + 1) == len(related_queries):
            hits = sum(1 for r in pass3_results if r.cache_hit)
            errors = sum(1 for r in pass3_results if r.decision == "ERROR")
            print(f"      [{i + 1}/{len(related_queries)}] Hits: {hits} | Errors: {errors}")

    p3_hits = sum(1 for r in pass3_results if r.cache_hit)
    p3_total = len(pass3_results)
    print(f"    Pass 3 complete: {p3_hits}/{p3_total} hits ({p3_hits / max(p3_total, 1) * 100:.1f}%)")

    # --- Summary ---
    total_hits = sum(1 for r in all_results if r.cache_hit)
    total = len(all_results)
    total_time = time.perf_counter() - t0
    print("\n    ── SUMMARY ──")
    print(f"    Total: {total_hits}/{total} hits ({total_hits / max(total, 1) * 100:.1f}%)")
    print(f"    Pass 1 (warmup):     {p1_hits / max(p1_total, 1) * 100:.1f}%")
    print(f"    Pass 2 (repeat+para): {p2_hits / max(p2_total, 1) * 100:.1f}%")
    print(f"    Pass 3 (related):    {p3_hits / max(p3_total, 1) * 100:.1f}%")
    print(f"    Duration: {total_time:.1f}s")

    client.close()
    return all_results


# ---------------------------------------------------------------------------
# Phase 5: Report
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], pct: int) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[-1]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def compile_report(results: list[QueryResult], duration_s: float) -> dict:
    """Compile results into a structured report."""
    total = len(results)
    if total == 0:
        return {"error": "No results"}

    hits = [r for r in results if r.cache_hit]
    misses = [r for r in results if not r.cache_hit]
    hit_rate = len(hits) / total

    # Hits by query type
    type_totals: dict[str, int] = {}
    type_hits: dict[str, int] = {}
    for r in results:
        type_totals[r.query_type] = type_totals.get(r.query_type, 0) + 1
        if r.cache_hit:
            type_hits[r.query_type] = type_hits.get(r.query_type, 0) + 1

    # Hits by layer
    layer_counts: dict[str, int] = {}
    for r in hits:
        for layer in r.layers_contributed:
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

    # Token savings
    total_tokens_no_cache = total * (_AVG_INPUT_TOKENS + _AVG_OUTPUT_TOKENS)
    actual_tokens = sum(r.input_tokens + r.output_tokens for r in results)
    token_savings_pct = (
        (total_tokens_no_cache - actual_tokens) / total_tokens_no_cache if total_tokens_no_cache > 0 else 0.0
    )

    # Cost savings
    cost_per_query = (_AVG_INPUT_TOKENS / 1000) * _INPUT_COST_PER_1K + (_AVG_OUTPUT_TOKENS / 1000) * _OUTPUT_COST_PER_1K
    cost_no_cache = total * cost_per_query
    cost_actual = sum(
        (r.input_tokens / 1000) * _INPUT_COST_PER_1K + (r.output_tokens / 1000) * _OUTPUT_COST_PER_1K
        for r in results
    )
    cost_savings = cost_no_cache - cost_actual

    # Latency percentiles
    cached_latencies = sorted(r.latency_ms for r in hits) if hits else [0.0]
    uncached_latencies = sorted(r.latency_ms for r in misses) if misses else [0.0]
    all_latencies = sorted(r.latency_ms for r in results)

    # Monthly projection (100K queries/day)
    daily_queries = 100_000
    monthly_no_cache = daily_queries * 30 * cost_per_query
    monthly_with_cache = monthly_no_cache * (1.0 - token_savings_pct)
    monthly_savings = monthly_no_cache - monthly_with_cache

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_queries": total,
        "duration_s": round(duration_s, 1),
        "cache_hit_rate": round(hit_rate, 4),
        "cache_hits": len(hits),
        "cache_misses": len(misses),
        "token_savings_pct": round(token_savings_pct, 4),
        "cost_savings_per_10k": round(cost_savings * (10_000 / total), 2),
        "hit_rate_by_type": {
            qt: {
                "total": type_totals[qt],
                "hits": type_hits.get(qt, 0),
                "rate": round(type_hits.get(qt, 0) / type_totals[qt], 4) if type_totals[qt] else 0,
            }
            for qt in sorted(type_totals.keys())
        },
        "hit_rate_by_layer": {
            layer: {
                "count": count,
                "pct": round(count / total, 4),
            }
            for layer, count in sorted(layer_counts.items(), key=lambda x: -x[1])
        },
        "latency": {
            "cached": {
                "p50": round(_percentile(cached_latencies, 50), 2),
                "p95": round(_percentile(cached_latencies, 95), 2),
                "p99": round(_percentile(cached_latencies, 99), 2),
            },
            "uncached": {
                "p50": round(_percentile(uncached_latencies, 50), 2),
                "p95": round(_percentile(uncached_latencies, 95), 2),
                "p99": round(_percentile(uncached_latencies, 99), 2),
            },
            "overall": {
                "avg": round(sum(all_latencies) / len(all_latencies), 2),
                "p50": round(_percentile(all_latencies, 50), 2),
                "p95": round(_percentile(all_latencies, 95), 2),
                "p99": round(_percentile(all_latencies, 99), 2),
            },
        },
        "monthly_projection": {
            "daily_queries": daily_queries,
            "without_cache": round(monthly_no_cache, 2),
            "with_cache": round(monthly_with_cache, 2),
            "savings": round(monthly_savings, 2),
            "savings_pct": round(token_savings_pct * 100, 1),
        },
    }

    return report


def print_report(report: dict) -> None:
    """Print the benchmark report as an ASCII table."""
    print()
    print("=" * 55)
    print("  BITMOD CACHE BENCHMARK RESULTS")
    total = report["total_queries"]
    dur = report["duration_s"]
    print(f"  Queries: {total:,} | Duration: {dur:.1f}s")
    print("=" * 55)

    hr = report["cache_hit_rate"] * 100
    ts = report["token_savings_pct"] * 100
    cs = report["cost_savings_per_10k"]
    print(f"\n  Cache Hit Rate:       {hr:.1f}%")
    print(f"  Token Savings:        {ts:.1f}%")
    print(f"  Cost Savings:         ${cs:.2f} per 10K queries")

    print("\n  Hit Rate by Query Type:")
    for qt, info in report["hit_rate_by_type"].items():
        rate = info["rate"] * 100
        count = info["total"]
        hits = info["hits"]
        print(f"    {qt:<22s} {rate:>5.1f}% ({hits}/{count})")

    print("\n  Hit Rate by Layer:")
    for layer, info in report["hit_rate_by_layer"].items():
        pct = info["pct"] * 100
        count = info["count"]
        print(f"    {layer:<22s} {pct:>5.1f}% ({count})")

    lat = report["latency"]
    print("\n  Latency:")
    cl = lat["cached"]
    ul = lat["uncached"]
    print(f"    P50:  {cl['p50']:.1f}ms (cached) | {ul['p50']:.1f}ms (uncached)")
    print(f"    P95:  {cl['p95']:.1f}ms (cached) | {ul['p95']:.1f}ms (uncached)")
    print(f"    P99:  {cl['p99']:.1f}ms (cached) | {ul['p99']:.1f}ms (uncached)")

    proj = report["monthly_projection"]
    print(f"\n  Savings Projection (monthly, {proj['daily_queries']:,} queries/day):")
    print(f"    Without BitMod:  ${proj['without_cache']:,.2f}/month")
    print(f"    With BitMod:     ${proj['with_cache']:,.2f}/month")
    print(f"    Monthly Savings: ${proj['savings']:,.2f} ({proj['savings_pct']:.1f}%)")

    print("=" * 55)


def save_report(report: dict) -> Path:
    """Save JSON report to results directory."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"report_{ts}.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved to: {path}")
    return path


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Quora four-pass run — the cross-check against run_inprocess_benchmark.py
# ---------------------------------------------------------------------------


def run_quora_passes(proxy_url: str, pairs: int, rps: float = 0.0) -> dict:
    """Same corpus and same four passes as the in-process runner, over HTTP.

    The two runners are meant to differ in transport and nothing else — same
    dataset loader, same stubbed generation, same pass structure. If their
    numbers disagree, the disagreement is attributable.
    """
    import httpx

    from tests.benchmark.dataset import CONFIG, DATASET, SPLIT, fetch_pairs

    # The gateway limits /v1/chat to 60 requests per minute, and that limit is
    # hardcoded in its middleware rather than read from RateLimitConfig, so it
    # cannot be turned off by configuration. Pacing the client is the honest way
    # to stay under it: a run that trips the limiter measures the limiter.
    min_interval = 1.0 / rps if rps > 0 else 0.0

    duplicates, non_duplicates = fetch_pairs(pairs)
    print(f"  got {len(duplicates)} duplicate, {len(non_duplicates)} non-duplicate pairs", flush=True)

    client = httpx.Client(base_url=proxy_url, timeout=120.0)
    try:
        client.get("/health").raise_for_status()
    except Exception as exc:
        print(f"  ERROR: proxy not reachable at {proxy_url}: {exc}")
        return {}

    passes = [
        ("1_cold", [a for a, _ in duplicates], False),
        ("2_repeat", [a for a, _ in duplicates], True),
        ("3_paraphrase", [b for _, b in duplicates], True),
        ("4_unrelated", [b for _, b in non_duplicates], False),
    ]

    rows: list[dict] = []
    last_sent = [0.0]
    for name, queries, expected in passes:
        print(f"  pass {name}: {len(queries)} queries", flush=True)
        for index, text in enumerate(queries, 1):
            if min_interval:
                slack = min_interval - (time.perf_counter() - last_sent[0])
                if slack > 0:
                    time.sleep(slack)
                last_sent[0] = time.perf_counter()
            r = _send_query(client, BenchmarkQuery(text=text, query_type=name, source=DATASET), name)
            rows.append(
                {
                    "pass": name,
                    "query": text[:160],
                    "hit": r.cache_hit,
                    "expected_hit": expected,
                    "served_by": r.layers_contributed[-1] if r.layers_contributed else "",
                    "total_confidence": r.total_confidence,
                    "contributions": [{"layer": lay, "confidence": 0.0} for lay in r.layers_contributed],
                    "lookup_ms": r.latency_ms,
                    "error": r.decision == "ERROR",
                }
            )
            if index % 200 == 0:
                print(f"    {index}/{len(queries)}", flush=True)

    # A rejected request is not a cache miss. Counting it as one produces a
    # plausible-looking hit rate from a run where the gateway answered almost
    # nothing — the first attempt at this reported 0.0% across 2000 queries and
    # the real story was 1940 responses of 429.
    errors = [r for r in rows if r.get("error")]
    if errors:
        by_status: dict[str, int] = {}
        for row in errors:
            status = row["served_by"] or "error"
            by_status[status] = by_status.get(status, 0) + 1
        print()
        print(f"  ABORTED: {len(errors)} of {len(rows)} requests failed — {by_status}")
        print("  A failed request is not a cache miss, so no hit rate is reported.")
        if any(k.endswith("429") for k in by_status):
            print("  Rate limited. Re-run the gateway with BITMOD_RATE_LIMIT_ENABLED=false.")
        return {}

    by_pass: dict = {}
    for row in rows:
        entry = by_pass.setdefault(row["pass"], {"total": 0, "hits": 0})
        entry["total"] += 1
        entry["hits"] += 1 if row["hit"] else 0
    for entry in by_pass.values():
        entry["hit_rate"] = round(entry["hits"] / entry["total"], 4) if entry["total"] else 0.0

    layer_counts: dict = {}
    for row in rows:
        for c in row["contributions"]:
            layer_counts[c["layer"]] = layer_counts.get(c["layer"], 0) + 1

    return {
        "harness": "http (POST /v1/chat/completions through the gateway)",
        "dataset": {"name": DATASET, "config": CONFIG, "split": SPLIT,
                    "duplicate_pairs": len(duplicates), "non_duplicate_pairs": len(non_duplicates)},
        "queries": len(rows),
        "hits": sum(1 for r in rows if r["hit"]),
        "hit_rate": round(sum(1 for r in rows if r["hit"]) / len(rows), 4) if rows else 0.0,
        "by_pass": by_pass,
        "false_positives": sum(1 for r in rows if r["expected_hit"] is False and r["hit"]),
        "false_negatives": sum(1 for r in rows if r["expected_hit"] is True and not r["hit"]),
        "layers_seen": layer_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bitmod cache benchmark with real datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--download", action="store_true", help="Download datasets only")
    parser.add_argument("--parse", action="store_true", help="Parse and extract queries")
    parser.add_argument("--ingest", action="store_true", help="Ingest knowledge base")
    parser.add_argument("--run", action="store_true", help="Run benchmark")
    parser.add_argument("--all", action="store_true", help="Do everything")
    parser.add_argument("--queries", type=int, default=10000, help="Max query count (default: 10000)")
    parser.add_argument("--skip-download", action="store_true", help="Skip download step")
    parser.add_argument("--db-path", type=str, default="", help="Database path (default: temp dir)")
    parser.add_argument("--rps", type=float, default=0.0,
                        help="cap requests per second; the gateway allows 60/min on /v1/chat")
    parser.add_argument("--quora-pairs", type=int, default=0,
                        help="Run the four-pass quora benchmark via --proxy (cross-check for the in-process runner)")
    parser.add_argument("--proxy", type=str, default="", help="Run via proxy HTTP endpoint (e.g., http://localhost:8000) — tests all 9 layers")

    args = parser.parse_args()

    if args.quora_pairs:
        if not args.proxy:
            print("--quora-pairs requires --proxy http://host:port")
            return
        import json as _json
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        report = run_quora_passes(args.proxy, args.quora_pairs, rps=args.rps)
        if report:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
            out = RESULTS_DIR / f"http_{stamp}.json"
            report["timestamp"] = _dt.now(_tz.utc).isoformat()
            out.write_text(_json.dumps(report, indent=2))
            print()
            print(f"  overall hit rate : {report['hit_rate']:.1%}  ({report['hits']}/{report['queries']})")
            for name in sorted(report["by_pass"]):
                pdata = report["by_pass"][name]
                print(f"    {name:<14} {pdata['hit_rate']:>7.1%}  ({pdata['hits']}/{pdata['total']})")
            print(f"  false positives  : {report['false_positives']}")
            print(f"  false negatives  : {report['false_negatives']}")
            print(f"\n  report written to {out}")
        return


    # If no specific phase selected, default to --all
    if not any([args.download, args.parse, args.ingest, args.run, args.all]):
        args.all = True

    do_download = args.all or args.download
    do_parse = args.all or args.parse
    do_ingest = args.all or args.ingest
    do_run = args.all or args.run

    # Add project root to sys.path
    project_root = BENCHMARK_DIR.parent.parent / "core"
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    print("\n" + "=" * 55)
    print("  BITMOD CACHE BENCHMARK")
    print(f"  Max queries: {args.queries:,}")
    print("=" * 55)

    # Phase 1: Download
    dataset_paths: dict[str, Path] = {}
    if do_download:
        print("\n  [PHASE 1] Downloading datasets ...")
        dataset_paths = download_datasets(skip=args.skip_download)
    else:
        # Check for existing files
        for ds in DATASETS:
            p = DATA_DIR / f"{ds['name']}.parquet"
            if p.exists():
                dataset_paths[ds["name"]] = p

    if not dataset_paths and (do_parse or do_ingest or do_run):
        print("\n  WARNING: No datasets available. Download first with --download")
        print("  Or place parquet files in tests/benchmark/data/")
        sys.exit(1)

    # Phase 2: Parse
    queries: list[BenchmarkQuery] = []
    knowledge: list[dict] = []
    if do_parse or do_ingest or do_run:
        print("\n  [PHASE 2] Parsing datasets ...")
        queries, knowledge = parse_datasets(dataset_paths, max_queries=args.queries)

    if not queries and (do_ingest or do_run):
        print("\n  ERROR: No queries extracted. Check dataset files.")
        sys.exit(1)

    # Set up database
    if args.db_path:
        db_path = args.db_path
    else:
        tmp_dir = tempfile.mkdtemp(prefix="bitmod_bench_")
        db_path = os.path.join(tmp_dir, "benchmark.db")

    print(f"\n  Database: {db_path}")

    # Phase 3: Ingest
    if do_ingest and knowledge:
        from bitmod.api import Bitmod

        print("\n  [PHASE 3] Ingesting knowledge base ...")
        bm = Bitmod(db_path=db_path)
        # Ensure backend is initialized with full schema
        backend = bm._get_backend()
        backend.initialize()
        ingest_knowledge(bm, knowledge, max_items=min(5000, len(knowledge)))
        bm.close()

    # Phase 4: Run
    if do_run and queries:
        t_start = time.perf_counter()
        if args.proxy:
            # Full 9-layer benchmark via HTTP proxy
            print(f"\n  [PHASE 4] Running benchmark via proxy ({args.proxy}) ...")
            results = run_benchmark_proxy(queries, proxy_url=args.proxy)
        else:
            # Direct API benchmark (Layer 1 only without proxy)
            print("\n  [PHASE 4] Running benchmark (direct API) ...")
            results = run_benchmark(queries, knowledge, db_path)
        duration = time.perf_counter() - t_start

        # Phase 5: Report
        print("\n  [PHASE 5] Generating report ...")
        report = compile_report(results, duration)
        print_report(report)
        save_report(report)

    print("\n  Done.")


if __name__ == "__main__":
    main()
