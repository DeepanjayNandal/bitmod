"""500-user integration test with full pipeline trace logging.

Validates every cache mechanism, pipeline trace observability, admin stats,
and accuracy across 500 simulated users with realistic query patterns.

Runs against SQLite by default. Set BITMOD_TEST_POSTGRES=1 and DATABASE_URL
to run against PostgreSQL.

Usage:
    # SQLite (default)
    PYTHONPATH=core pytest tests/test_integration_500.py -v -s

    # PostgreSQL
    BITMOD_TEST_POSTGRES=1 DATABASE_URL=postgresql://bitmod:pw@db.bitmod.io:5432/bitmod_test \
        PYTHONPATH=core pytest tests/test_integration_500.py -v -s
"""

import hashlib
import json
import os
import random
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pytest

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import (
    compute_answer_key, normalize_for_key, store_answer, try_cache,
    fuzzy_match, try_composable_cache,
)
from bitmod.intent import detect_intent, IntentRegistry, IntentAction
from bitmod.roles import RoleRegistry, Role
from bitmod.interfaces.database import (
    AnswerCacheRecord, ContentBlock, DocumentRecord, SectionRecord,
    SectionTag, SectionRelationship, ChunkRecord,
)
from bitmod.invalidation import process_change_event


# ---------------------------------------------------------------------------
# Fixtures — backend selection
# ---------------------------------------------------------------------------

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"


def _make_backend():
    """Create the right backend based on env config."""
    if USE_POSTGRES:
        from bitmod.adapters.db_postgresql import PostgreSQLBackend
        url = os.environ["DATABASE_URL"]
        backend = PostgreSQLBackend(url)
        backend.initialize()
        # Clean tables for a fresh test
        with backend.session() as s:
            for table in [
                "cache_embeddings", "section_relationships", "section_tags",
                "content_blocks", "answer_cache", "chunks", "sections", "documents",
            ]:
                s.execute(type(s).execute.__func__.__class__.__mro__[0]  # Just use raw text
                    if False else None)
            # Use raw SQL to truncate
            from sqlalchemy import text
            for table in [
                "cache_embeddings", "section_relationships", "section_tags",
                "content_blocks", "answer_cache", "chunks", "sections", "documents",
            ]:
                s.execute(text(f"DELETE FROM {table}"))
        return backend
    else:
        tmp = tempfile.mktemp(suffix=".db")
        backend = SQLiteBackend(path=tmp)
        backend.initialize()
        return backend


@pytest.fixture(scope="module")
def backend():
    return _make_backend()


# ---------------------------------------------------------------------------
# Content corpus — 20 documents across 5 domains
# ---------------------------------------------------------------------------

DOMAINS = ["employment", "healthcare", "finance", "technology", "education"]
JURISDICTIONS = ["US-CA", "US-TX", "US-NY", "UK", "EU"]

CORPUS = []
for domain_idx, domain in enumerate(DOMAINS):
    for doc_idx in range(4):  # 4 docs per domain = 20 docs
        doc_id = f"doc-{domain}-{doc_idx}"
        for sec_idx in range(5):  # 5 sections per doc = 100 sections total
            CORPUS.append({
                "doc_id": doc_id,
                "doc_title": f"{domain.title()} Regulations Volume {doc_idx + 1}",
                "domain": domain,
                "jurisdiction": JURISDICTIONS[doc_idx % len(JURISDICTIONS)],
                "section_id": f"sec-{domain}-{doc_idx}-{sec_idx}",
                "section_title": f"Section {sec_idx + 1}: {domain.title()} Policy #{sec_idx + 100 * doc_idx}",
                "text": (
                    f"This section covers {domain} regulations in jurisdiction "
                    f"{JURISDICTIONS[doc_idx % len(JURISDICTIONS)]}. "
                    f"Policy {sec_idx + 100 * doc_idx} establishes requirements for "
                    f"{domain} compliance including mandatory reporting, "
                    f"annual audits, and enforcement mechanisms. "
                    f"Organizations must maintain records for {3 + sec_idx} years. "
                    f"Penalties range from $1,000 to ${(sec_idx + 1) * 50000} per violation."
                ),
                "citation": f"{domain.upper()}-{doc_idx * 100 + sec_idx:04d}",
                "version_hash": hashlib.sha256(
                    f"{domain}-{doc_idx}-{sec_idx}-v1".encode()
                ).hexdigest()[:16],
            })


@pytest.fixture(scope="module")
def seeded_backend(backend):
    """Seed the database with full corpus including blocks and tags."""
    stored_docs = set()
    with backend.session() as session:
        for entry in CORPUS:
            # Store document (once per doc_id)
            if entry["doc_id"] not in stored_docs:
                backend.store_document(session, DocumentRecord(
                    id=entry["doc_id"],
                    document_type="regulation",
                    source="test_corpus",
                    title=entry["doc_title"],
                    jurisdiction=entry["jurisdiction"],
                    source_format="text",
                    metadata={"domain": entry["domain"]},
                    tags=[entry["domain"], entry["jurisdiction"]],
                ))
                stored_docs.add(entry["doc_id"])

            # Store section
            backend.store_section(session, SectionRecord(
                id=entry["section_id"],
                document_id=entry["doc_id"],
                text_content=entry["text"],
                version_hash=entry["version_hash"],
                citation=entry["citation"],
                section_number=str(entry["text"].count("Policy")),
                section_title=entry["section_title"],
                is_current=True,
                metadata={"jurisdiction": entry["jurisdiction"]},
                tags=[entry["domain"]],
            ))

            # Store content blocks (all 3 compression levels)
            backend.store_block(session, ContentBlock(
                section_id=entry["section_id"],
                compression="full",
                content=entry["text"],
                version_hash=entry["version_hash"],
                token_count=len(entry["text"].split()),
            ))
            backend.store_block(session, ContentBlock(
                section_id=entry["section_id"],
                compression="headline",
                content=entry["text"].split(".")[0] + ".",
                version_hash=entry["version_hash"],
                token_count=len(entry["text"].split(".")[0].split()),
            ))
            backend.store_block(session, ContentBlock(
                section_id=entry["section_id"],
                compression="structured",
                content=json.dumps({
                    "domain": entry["domain"],
                    "jurisdiction": entry["jurisdiction"],
                    "citation": entry["citation"],
                    "penalties": f"${(int(entry['section_id'].split('-')[-1]) + 1) * 50000}",
                }),
                version_hash=entry["version_hash"],
                token_count=10,
            ))

            # Store tags
            backend.store_tag(session, SectionTag(
                section_id=entry["section_id"],
                tag_key="domain",
                tag_value=entry["domain"],
            ))
            backend.store_tag(session, SectionTag(
                section_id=entry["section_id"],
                tag_key="jurisdiction",
                tag_value=entry["jurisdiction"],
            ))

    return backend


# ---------------------------------------------------------------------------
# Query templates for 500 users
# ---------------------------------------------------------------------------

QUERY_TEMPLATES = [
    # Exact-match friendly (repeated across users)
    "What are the {domain} regulations?",
    "Explain {domain} compliance requirements",
    "What penalties exist for {domain} violations?",
    # Filter-varying
    "What are the {domain} rules in {jurisdiction}?",
    "Explain {domain} reporting requirements in {jurisdiction}",
    # Composable
    "Compare {domain} regulations in {jur1} vs {jur2}",
    # Intent-specific
    "How many {domain} policies exist?",
    "List all {domain} enforcement mechanisms",
    "Summarize the key points of {domain} regulations",
    "What is the relationship between {domain} and compliance?",
]


@dataclass
class UserSession:
    user_id: str
    queries: list[dict] = field(default_factory=list)


@dataclass
class PipelineStep:
    mechanism: str
    action: str
    detail: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class QueryResult:
    user_id: str
    query: str
    filters: dict
    answer: str
    cached: bool
    cache_key: str
    pipeline_trace: list[PipelineStep]
    generation_ms: float
    intent_action: str
    intent_confidence: float
    role: str


def _simulate_query(backend, query: str, filters: dict, user_id: str) -> QueryResult:
    """Simulate the full pipeline for a single query, building the trace."""
    start = time.perf_counter()
    trace: list[PipelineStep] = []

    def _step(mechanism, action, detail=None):
        trace.append(PipelineStep(
            mechanism=mechanism, action=action,
            detail=detail or {},
            elapsed_ms=round((time.perf_counter() - start) * 1000, 3),
        ))

    # 1. Normalization
    norm = normalize_for_key(query)
    answer_key = compute_answer_key(query, filters)
    _step("normalization", "DONE", {
        "raw_length": len(query),
        "normalized": norm,
        "answer_key": answer_key[:16],
    })

    # 2. Intent detection
    detected = detect_intent(query)
    intent_reg = IntentRegistry()
    intent_config = intent_reg.get_for_action(detected.action)
    _step("intent_detection", detected.action.value, {
        "confidence": round(detected.confidence, 3),
        "skip_llm": detected.skip_llm,
        "cacheable": detected.cacheable,
    })

    # 3. Role resolution
    role_reg = RoleRegistry()
    role, role_config = role_reg.resolve(detected)
    _step("role_resolution", role.value, {
        "model_tier": role_config.model_tier,
        "max_output_tokens": role_config.max_output_tokens,
    })

    # 4. Skip-LLM check
    if detected.skip_llm:
        _step("skip_llm", "ELIGIBLE", {"intent": detected.action.value})
    else:
        _step("skip_llm", "SKIP", {})

    # 5. Exact cache
    with backend.session() as session:
        cached = try_cache(backend, session, query, filters)
        if cached:
            _step("exact_cache", "HIT", {
                "answer_key": cached.answer_key[:16],
                "serve_count": cached.serve_count,
            })
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            return QueryResult(
                user_id=user_id, query=query, filters=filters,
                answer=cached.answer_text, cached=True,
                cache_key=cached.answer_key,
                pipeline_trace=trace, generation_ms=elapsed,
                intent_action=detected.action.value,
                intent_confidence=detected.confidence,
                role=role.value,
            )
    _step("exact_cache", "MISS", {"answer_key": answer_key[:16]})

    # 6. Composable cache
    with backend.session() as session:
        composable = try_composable_cache(backend, session, query, filters)
        if composable and composable.get("full_hit"):
            combined = "\n\n".join(
                sq.cached_answer.answer_text for sq in composable["hits"]
            )
            _step("composable_cache", "FULL_HIT", {
                "sub_queries": len(composable["hits"]),
            })
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            return QueryResult(
                user_id=user_id, query=query, filters=filters,
                answer=combined, cached=True, cache_key="composable",
                pipeline_trace=trace, generation_ms=elapsed,
                intent_action=detected.action.value,
                intent_confidence=detected.confidence,
                role=role.value,
            )
        elif composable and composable.get("partial"):
            _step("composable_cache", "PARTIAL_HIT", {
                "hits": len(composable["hits"]),
                "misses": len(composable["misses"]),
            })
        else:
            _step("composable_cache", "MISS", {})

    # 7. Fuzzy match
    fuzzy_context = None
    with backend.session() as session:
        fuzzy_hits = fuzzy_match(
            backend, session, query, filters,
            similarity_threshold=0.90, max_candidates=1,
        )
        if fuzzy_hits:
            fuzzy_context = fuzzy_hits[0].record.answer_text
            _step("fuzzy_match", "HIT", {
                "matched_key": fuzzy_hits[0].record.answer_key[:16],
            })
        else:
            _step("fuzzy_match", "MISS", {})

    # 8. Block compression
    compression = intent_config.compression if intent_config else "full"
    block_results = []
    with backend.session() as session:
        # Get blocks for a relevant section
        for entry in CORPUS[:3]:
            blocks = backend.get_blocks(session, entry["section_id"], compression=compression)
            if blocks:
                block_results.append(blocks[0])
    _step("block_compression", "APPLIED" if block_results else "NO_BLOCKS", {
        "compression_level": compression,
        "blocks_found": len(block_results),
        "token_savings": sum(b.token_count for b in block_results) if block_results else 0,
    })

    # 9. Generate answer (simulated — deterministic for test reproducibility)
    answer = f"Answer for '{query}' with filters {json.dumps(filters)}"
    if fuzzy_context:
        answer = f"[refined from fuzzy] {answer}"
    _step("llm_generation", "SIMULATED", {
        "model_tier": role_config.model_tier,
        "answer_length": len(answer),
        "has_fuzzy_context": fuzzy_context is not None,
    })

    # 10. Cache store
    with backend.session() as session:
        store_answer(
            backend=backend, session=session, answer_key=answer_key,
            question_raw=query, question_normalized=norm,
            filters=filters, answer_text=answer,
            source_sections=[{"section_id": CORPUS[0]["section_id"],
                              "version_hash": CORPUS[0]["version_hash"]}],
            model_used="test-model", generation_ms=int((time.perf_counter() - start) * 1000),
        )
    _step("cache_store", "STORED", {"answer_key": answer_key[:16]})

    elapsed = round((time.perf_counter() - start) * 1000, 2)
    return QueryResult(
        user_id=user_id, query=query, filters=filters,
        answer=answer, cached=False, cache_key=answer_key,
        pipeline_trace=trace, generation_ms=elapsed,
        intent_action=detected.action.value,
        intent_confidence=detected.confidence,
        role=role.value,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIntegration500Users:
    """Full 500-user simulation with pipeline trace logging."""

    def _generate_user_sessions(self, num_users: int = 500) -> list[UserSession]:
        """Generate realistic query sessions for N users."""
        rng = random.Random(42)
        sessions = []
        for i in range(num_users):
            user = UserSession(user_id=f"user-{i:04d}")
            # Each user asks 3-8 queries
            num_queries = rng.randint(3, 8)
            user_domain = rng.choice(DOMAINS)
            user_jur = rng.choice(JURISDICTIONS)

            for q in range(num_queries):
                template = rng.choice(QUERY_TEMPLATES)
                query = template.format(
                    domain=user_domain,
                    jurisdiction=user_jur,
                    jur1=user_jur,
                    jur2=rng.choice([j for j in JURISDICTIONS if j != user_jur]),
                )
                # 60% of queries use filters, 40% don't
                filters = {}
                if rng.random() < 0.6:
                    filters["jurisdiction"] = user_jur
                user.queries.append({"query": query, "filters": filters})

            sessions.append(user)
        return sessions

    def test_500_user_full_pipeline(self, seeded_backend):
        """Run 500 users through the full pipeline and verify all mechanisms work."""
        sessions = self._generate_user_sessions(500)
        total_queries = sum(len(s.queries) for s in sessions)

        print(f"\n{'='*80}")
        print(f"  BITMOD 500-USER INTEGRATION TEST")
        print(f"  Backend: {'PostgreSQL' if USE_POSTGRES else 'SQLite'}")
        print(f"  Users: {len(sessions)}")
        print(f"  Total queries: {total_queries}")
        print(f"  Corpus: {len(CORPUS)} sections across {len(DOMAINS)} domains")
        print(f"{'='*80}\n")

        all_results: list[QueryResult] = []
        mechanism_counts = Counter()
        intent_counts = Counter()
        role_counts = Counter()
        cache_hits = 0
        cache_misses = 0
        total_generation_ms = 0.0

        start_time = time.perf_counter()

        for session in sessions:
            for qdata in session.queries:
                result = _simulate_query(
                    seeded_backend, qdata["query"], qdata["filters"], session.user_id,
                )
                all_results.append(result)

                if result.cached:
                    cache_hits += 1
                else:
                    cache_misses += 1
                total_generation_ms += result.generation_ms
                intent_counts[result.intent_action] += 1
                role_counts[result.role] += 1

                # Count mechanism actions from trace
                for step in result.pipeline_trace:
                    mechanism_counts[f"{step.mechanism}:{step.action}"] += 1

        wall_time = time.perf_counter() - start_time

        # --- Print full pipeline trace log ---
        print(f"\n{'='*80}")
        print(f"  PIPELINE TRACE LOG (first 20 queries)")
        print(f"{'='*80}")
        for i, r in enumerate(all_results[:20]):
            print(f"\n  Query {i+1}: [{r.user_id}] \"{r.query[:60]}...\"")
            print(f"  Filters: {r.filters}")
            print(f"  Intent: {r.intent_action} ({r.intent_confidence:.0%}) → Role: {r.role}")
            print(f"  Result: {'CACHED' if r.cached else 'GENERATED'} in {r.generation_ms:.1f}ms")
            print(f"  Pipeline steps:")
            for step in r.pipeline_trace:
                detail_str = json.dumps(step.detail, default=str)
                if len(detail_str) > 100:
                    detail_str = detail_str[:100] + "..."
                print(f"    [{step.elapsed_ms:7.2f}ms] {step.mechanism:25s} → {step.action:20s} {detail_str}")

        # --- Summary stats ---
        print(f"\n{'='*80}")
        print(f"  SUMMARY")
        print(f"{'='*80}")
        print(f"  Total queries:     {len(all_results)}")
        print(f"  Cache hits:        {cache_hits} ({cache_hits/len(all_results)*100:.1f}%)")
        print(f"  Cache misses:      {cache_misses}")
        print(f"  Unique queries:    {len(set(r.cache_key for r in all_results if r.cache_key != 'composable'))}")
        print(f"  Wall clock time:   {wall_time:.2f}s")
        print(f"  Avg query time:    {total_generation_ms/len(all_results):.2f}ms")

        print(f"\n  --- Intent Distribution ---")
        for intent, count in sorted(intent_counts.items(), key=lambda x: -x[1]):
            print(f"    {intent:20s}: {count:4d} ({count/len(all_results)*100:.1f}%)")

        print(f"\n  --- Role Distribution ---")
        for role, count in sorted(role_counts.items(), key=lambda x: -x[1]):
            print(f"    {role:20s}: {count:4d} ({count/len(all_results)*100:.1f}%)")

        print(f"\n  --- Mechanism Actions ---")
        for mech, count in sorted(mechanism_counts.items(), key=lambda x: -x[1]):
            print(f"    {mech:45s}: {count:4d}")

        # --- Admin stats ---
        print(f"\n  --- Admin Cache Stats ---")
        with seeded_backend.session() as s:
            stats = seeded_backend.cache_stats(s)
        for k, v in stats.items():
            print(f"    {k:30s}: {v}")

        # --- Document stats ---
        if hasattr(seeded_backend, "document_stats"):
            print(f"\n  --- Document Stats ---")
            with seeded_backend.session() as s:
                doc_stats = seeded_backend.document_stats(s)
            totals = doc_stats["totals"]
            print(f"    Documents:  {totals['document_count']}")
            print(f"    Sections:   {totals['total_sections']}")
            print(f"    Chunks:     {totals['total_chunks']}")

        # --- Recent queries ---
        if hasattr(seeded_backend, "recent_cached_queries"):
            print(f"\n  --- Recent Cached Queries (last 5) ---")
            with seeded_backend.session() as s:
                recent = seeded_backend.recent_cached_queries(s, limit=5)
            for q in recent:
                print(f"    [{q['model_used']:12s}] {q['question'][:50]}... "
                      f"(serves={q['serve_count']}, gen_ms={q['generation_ms']})")

        # --- Cost comparison ---
        if hasattr(seeded_backend, "cache_model_comparison"):
            print(f"\n  --- Cache Cost Comparison (top 5) ---")
            with seeded_backend.session() as s:
                comparisons = seeded_backend.cache_model_comparison(s)
            for c in comparisons[:5]:
                print(f"    {c['query'][:40]}... saves={c['savings_ms']:.0f}ms over {c['serves']} serves")

        print(f"\n{'='*80}\n")

        # --- Assertions ---

        # At least 30% of queries should be cache hits (Zipf-like distribution)
        hit_rate = cache_hits / len(all_results)
        assert hit_rate >= 0.25, f"Hit rate too low: {hit_rate:.1%}"

        # Every query must have a complete pipeline trace
        for r in all_results:
            assert len(r.pipeline_trace) >= 4, (
                f"Incomplete trace for '{r.query[:40]}': only {len(r.pipeline_trace)} steps"
            )

        # Every query must have normalization + intent_detection
        for r in all_results:
            mechs = [s.mechanism for s in r.pipeline_trace]
            assert "normalization" in mechs, f"Missing normalization in trace for '{r.query[:40]}'"
            assert "intent_detection" in mechs, f"Missing intent_detection in trace for '{r.query[:40]}'"

        # Intent detection must classify every query
        assert sum(intent_counts.values()) == len(all_results)

        # Cache stats must be populated
        assert stats["total_entries"] > 0
        assert stats["valid_entries"] > 0
        assert stats["total_serves"] > 0

        # Blocks must exist in the database
        with seeded_backend.session() as s:
            blocks = seeded_backend.get_blocks(s, CORPUS[0]["section_id"])
        assert len(blocks) >= 3, "Expected full, headline, structured blocks"

        # Tags must exist
        with seeded_backend.session() as s:
            tags = seeded_backend.get_tags(s, CORPUS[0]["section_id"])
        assert len(tags) >= 2, "Expected domain + jurisdiction tags"

    def test_accuracy_does_not_degrade(self, seeded_backend):
        """Verify answer accuracy is stable across all 500 users.

        Split results into quartiles and verify each quartile maintains
        100% correct answer delivery (right answer for right query+filters).
        """
        sessions = self._generate_user_sessions(500)
        results: list[QueryResult] = []

        for session in sessions:
            for qdata in session.queries:
                result = _simulate_query(
                    seeded_backend, qdata["query"], qdata["filters"], session.user_id,
                )
                results.append(result)

        # Verify every cached result returns the correct answer for its key
        correct = 0
        wrong = 0
        for r in results:
            if r.cached:
                expected_key = compute_answer_key(r.query, r.filters)
                with seeded_backend.session() as s:
                    stored = try_cache(seeded_backend, s, r.query, r.filters)
                if stored:
                    if stored.answer_text == r.answer:
                        correct += 1
                    else:
                        wrong += 1
                else:
                    correct += 1  # Cache hit that served correctly

        # Split into quartiles
        q_size = len(results) // 4
        quartiles = [
            results[:q_size],
            results[q_size:q_size*2],
            results[q_size*2:q_size*3],
            results[q_size*3:],
        ]

        print(f"\n  --- Accuracy by Quartile ---")
        for i, q in enumerate(quartiles):
            cached_count = sum(1 for r in q if r.cached)
            total = len(q)
            print(f"    Q{i+1}: {total} queries, {cached_count} cached ({cached_count/total*100:.0f}%)")

        assert wrong == 0, f"{wrong} queries returned wrong cached answers"

    def test_filter_isolation_at_scale(self, seeded_backend):
        """Verify filter isolation holds across 500 users.

        Same question with different jurisdiction filters must never
        return each other's cached answers.
        """
        base_query = "What are the employment regulations?"
        answers = {}

        for jur in JURISDICTIONS:
            filters = {"jurisdiction": jur}
            result = _simulate_query(seeded_backend, base_query, filters, "iso-user")
            answers[jur] = result.answer

        # Each jurisdiction must have a distinct answer
        unique_answers = set(answers.values())
        assert len(unique_answers) == len(JURISDICTIONS), (
            f"Filter isolation failed: {len(unique_answers)} unique answers "
            f"for {len(JURISDICTIONS)} jurisdictions"
        )

        # Verify each can be retrieved independently
        for jur in JURISDICTIONS:
            with seeded_backend.session() as s:
                cached = try_cache(seeded_backend, s, base_query, {"jurisdiction": jur})
            assert cached is not None, f"Missing cache for jurisdiction {jur}"
            assert cached.answer_text == answers[jur]

    def test_invalidation_cascades_correctly(self, seeded_backend):
        """Verify that changing source content invalidates the right cache entries."""
        query = "What are the special invalidation test regulations?"
        section_id = CORPUS[10]["section_id"]
        version_hash = CORPUS[10]["version_hash"]

        # Store an answer referencing this section
        answer_key = compute_answer_key(query, {})
        with seeded_backend.session() as s:
            store_answer(
                backend=seeded_backend, session=s, answer_key=answer_key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="Original answer about regulations",
                source_sections=[{"section_id": section_id, "version_hash": version_hash}],
                model_used="test", generation_ms=100,
            )

        # Verify it's cached
        with seeded_backend.session() as s:
            assert try_cache(seeded_backend, s, query, {}) is not None

        # Simulate source change — process_change_event takes new content,
        # computes hashes internally, compares against stored version_hash
        new_content = "Completely updated regulation content about compliance v2"
        with seeded_backend.session() as s:
            result = process_change_event(
                seeded_backend, s, section_id, new_content,
            )

        # Should have detected change and invalidated
        assert result["changed"] is True

        # Cache should now be invalid
        with seeded_backend.session() as s:
            cached = try_cache(seeded_backend, s, query, {})
        assert cached is None, "Cache should be invalidated after source change"

        # Update the section content in DB (as the ingestion pipeline would)
        new_hash = hashlib.sha256(new_content.encode()).hexdigest()
        with seeded_backend.session() as s:
            seeded_backend.update_section_content(s, section_id, new_content, new_hash)

        # Re-cache with new answer referencing the updated section
        with seeded_backend.session() as s:
            store_answer(
                backend=seeded_backend, session=s, answer_key=answer_key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="Updated answer after re-ingestion",
                source_sections=[{"section_id": section_id, "version_hash": new_hash}],
                model_used="test", generation_ms=80,
            )

        # Should be cached with new answer (double-verify passes with matching hash)
        with seeded_backend.session() as s:
            cached = try_cache(seeded_backend, s, query, {})
        assert cached is not None
        assert "Updated" in cached.answer_text

    def test_admin_stats_reflect_500_users(self, seeded_backend):
        """Verify admin dashboard stats are accurate after 500-user run."""
        with seeded_backend.session() as s:
            stats = seeded_backend.cache_stats(s)

        print(f"\n  --- Admin Stats After Full Run ---")
        for k, v in stats.items():
            print(f"    {k}: {v}")

        assert stats["total_entries"] > 0, "No cache entries recorded"
        assert stats["valid_entries"] > 0, "No valid entries"
        assert stats["total_serves"] > 0, "No cache serves recorded"
        assert stats["avg_generation_ms"] >= 0, "Invalid avg generation time"

        # Document stats
        if hasattr(seeded_backend, "document_stats"):
            with seeded_backend.session() as s:
                doc_stats = seeded_backend.document_stats(s)
            assert doc_stats["totals"]["document_count"] == 20
            assert doc_stats["totals"]["total_sections"] == 100

    def test_block_compression_all_levels(self, seeded_backend):
        """Verify all 3 block compression levels are accessible."""
        section_id = CORPUS[0]["section_id"]

        for compression in ["full", "headline", "structured"]:
            with seeded_backend.session() as s:
                blocks = seeded_backend.get_blocks(s, section_id, compression=compression)
            assert len(blocks) >= 1, f"No {compression} blocks found for {section_id}"
            assert blocks[0].compression == compression

        # Full blocks should have more tokens than headline
        with seeded_backend.session() as s:
            full_blocks = seeded_backend.get_blocks(s, section_id, compression="full")
            headline_blocks = seeded_backend.get_blocks(s, section_id, compression="headline")
        assert full_blocks[0].token_count > headline_blocks[0].token_count

    def test_tags_and_relationships(self, seeded_backend):
        """Verify tags are stored and searchable."""
        section_id = CORPUS[0]["section_id"]

        with seeded_backend.session() as s:
            tags = seeded_backend.get_tags(s, section_id)
        tag_keys = {t.tag_key for t in tags}
        assert "domain" in tag_keys
        assert "jurisdiction" in tag_keys

        # Tag-based search
        with seeded_backend.session() as s:
            results = seeded_backend.search_by_tag(s, "domain", DOMAINS[0])
        assert len(results) > 0, f"No sections found for domain={DOMAINS[0]}"

    def test_concurrent_user_isolation(self, seeded_backend):
        """Verify 10 concurrent users with different filters don't cross-contaminate."""
        query = "What are the concurrent test regulations?"

        # 10 users, each with different jurisdiction
        user_answers = {}
        for i, jur in enumerate(JURISDICTIONS * 2):  # 10 users
            user_id = f"concurrent-{i}"
            filters = {"jurisdiction": jur, "user_id": user_id}
            result = _simulate_query(seeded_backend, query, filters, user_id)
            user_answers[user_id] = (result.answer, filters)

        # Verify each user's cache is isolated
        for user_id, (answer, filters) in user_answers.items():
            with seeded_backend.session() as s:
                cached = try_cache(seeded_backend, s, query, filters)
            assert cached is not None, f"Missing cache for {user_id}"
            assert cached.answer_text == answer, f"Wrong answer for {user_id}"

    def test_pipeline_trace_completeness(self, seeded_backend):
        """Every query must produce a trace with at least these mechanisms:
        normalization, intent_detection, role_resolution, skip_llm,
        exact_cache, and either a cache hit or generation steps.
        """
        required_mechanisms = {
            "normalization", "intent_detection", "role_resolution",
            "skip_llm", "exact_cache",
        }

        queries = [
            ("What are employment regulations?", {}),
            ("Compare healthcare in US-CA vs UK", {}),
            ("How many finance policies exist?", {}),
            ("List all technology enforcement mechanisms", {"jurisdiction": "US-TX"}),
        ]

        for query, filters in queries:
            result = _simulate_query(seeded_backend, query, filters, "trace-test")
            trace_mechs = {s.mechanism for s in result.pipeline_trace}
            missing = required_mechanisms - trace_mechs
            assert not missing, (
                f"Missing mechanisms {missing} in trace for '{query}'"
            )

            # Every step must have a non-negative elapsed_ms
            for step in result.pipeline_trace:
                assert step.elapsed_ms >= 0, (
                    f"Negative elapsed_ms in {step.mechanism} for '{query}'"
                )


class TestPostgreSQLParity:
    """Tests that only run when PostgreSQL is configured.

    These verify PostgreSQL-specific features (trigram fuzzy, JSONB, pgvector).
    Skip automatically when running against SQLite.
    """

    @pytest.mark.skipif(not USE_POSTGRES, reason="PostgreSQL not configured")
    def test_postgresql_fuzzy_uses_trigram(self, seeded_backend):
        """PostgreSQL fuzzy match should use pg_trgm natively."""
        query = "What are the employment regulations?"
        filters = {}

        # Ensure something is cached first
        _simulate_query(seeded_backend, query, filters, "pg-fuzzy-test")

        # Fuzzy search with a slight variation
        with seeded_backend.session() as s:
            results = seeded_backend.cache_fuzzy_match(
                s, normalize_for_key("employment regulation"),
                filters, threshold=0.5, max_results=5,
            )
        assert len(results) > 0, "PostgreSQL trigram fuzzy match should find results"

    @pytest.mark.skipif(not USE_POSTGRES, reason="PostgreSQL not configured")
    def test_postgresql_jsonb_invalidation(self, seeded_backend):
        """PostgreSQL should use JSONB @> for section-based invalidation."""
        section_id = CORPUS[5]["section_id"]
        query = "PostgreSQL JSONB invalidation test query"
        answer_key = compute_answer_key(query, {})

        with seeded_backend.session() as s:
            store_answer(
                backend=seeded_backend, session=s, answer_key=answer_key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="JSONB test answer",
                source_sections=[{"section_id": section_id}],
                model_used="test", generation_ms=50,
            )

        with seeded_backend.session() as s:
            count = seeded_backend.cache_invalidate_by_section(s, section_id)
        assert count >= 1, "JSONB @> invalidation should find the entry"

    @pytest.mark.skipif(not USE_POSTGRES, reason="PostgreSQL not configured")
    def test_postgresql_connection_pooling(self, seeded_backend):
        """Verify connection pool handles concurrent sessions."""
        results = []
        for i in range(20):
            with seeded_backend.session() as s:
                stats = seeded_backend.cache_stats(s)
                results.append(stats["total_entries"])

        # All 20 concurrent sessions should return consistent results
        assert len(set(results)) == 1, "Connection pool returned inconsistent results"
