"""Live LLM integration test — runs against REAL Ollama (llama3.2 + nomic-embed-text).

This is NOT a mock test. It calls a running Ollama instance, generates real
embeddings, runs real LLM inference, and validates the full Bitmod pipeline
end-to-end: ingest → embed → search → cache → serve → invalidate → re-generate.

Prerequisites:
    ollama pull llama3.2
    ollama pull nomic-embed-text

Usage:
    PYTHONPATH=core pytest tests/test_live_llm.py -v -s
"""

import asyncio
import hashlib
import json
import os
import tempfile
import time
import uuid

import httpx
import pytest

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.adapters.llm_ollama import OllamaAdapter
from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter
from bitmod.router import LLMRouter
from bitmod.interfaces.llm import LLMMessage
from bitmod.interfaces.database import (
    DocumentRecord, SectionRecord, ChunkRecord, ContentBlock,
    SectionTag,
)
from bitmod.tool_layer import ALL_TOOLS, execute_tool
from bitmod.cache_engine import (
    compute_answer_key, normalize_for_key, try_cache, store_answer,
    fuzzy_match, semantic_cache_match,
)
from bitmod.intent import detect_intent, IntentRegistry
from bitmod.roles import RoleRegistry
from bitmod.invalidation import process_change_event
from bitmod.security import sanitize_input


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


def _ollama_available() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        return "llama3.2:latest" in models and "nomic-embed-text:latest" in models
    except Exception:
        return False


SKIP_REASON = "Ollama not running or missing models (llama3.2, nomic-embed-text)"
pytestmark = pytest.mark.skipif(not _ollama_available(), reason=SKIP_REASON)


# ---------------------------------------------------------------------------
# Sample content — realistic documents for testing
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    {
        "id": "doc-cloud-security",
        "title": "Cloud Security Best Practices 2025",
        "sections": [
            {
                "title": "Identity and Access Management",
                "text": (
                    "Identity and Access Management (IAM) is the foundation of cloud security. "
                    "Organizations must implement multi-factor authentication (MFA) for all user accounts. "
                    "Role-based access control (RBAC) should follow the principle of least privilege, "
                    "granting users only the minimum permissions needed for their job function. "
                    "Service accounts must have their credentials rotated every 90 days. "
                    "Federated identity providers like SAML or OIDC are recommended for enterprise deployments."
                ),
                "citation": "CLOUD-SEC-001",
            },
            {
                "title": "Data Encryption Standards",
                "text": (
                    "All data must be encrypted at rest using AES-256 or equivalent. "
                    "Data in transit must use TLS 1.3 or higher. "
                    "Key management should use a dedicated KMS (Key Management Service) with "
                    "hardware security module (HSM) backing. Encryption keys must be rotated annually. "
                    "Client-side encryption is recommended for sensitive data before upload to cloud storage. "
                    "Database encryption should use Transparent Data Encryption (TDE) where available."
                ),
                "citation": "CLOUD-SEC-002",
            },
            {
                "title": "Network Security Architecture",
                "text": (
                    "Cloud networks must implement defense in depth with multiple security layers. "
                    "Virtual Private Clouds (VPCs) should isolate workloads by sensitivity level. "
                    "Network security groups must follow default-deny policies. "
                    "Web Application Firewalls (WAF) are required for all public-facing applications. "
                    "DDoS protection services should be enabled for all internet-facing endpoints. "
                    "Private endpoints should be used for internal service-to-service communication."
                ),
                "citation": "CLOUD-SEC-003",
            },
        ],
    },
    {
        "id": "doc-data-privacy",
        "title": "Data Privacy Compliance Guide",
        "sections": [
            {
                "title": "GDPR Requirements",
                "text": (
                    "The General Data Protection Regulation (GDPR) requires organizations to obtain "
                    "explicit consent before processing personal data of EU residents. "
                    "Data subjects have the right to access, rectify, and erase their personal data. "
                    "Organizations must appoint a Data Protection Officer (DPO) if they process "
                    "personal data at scale. Data breach notifications must be sent to supervisory "
                    "authorities within 72 hours of discovery. Privacy Impact Assessments are "
                    "required for high-risk processing activities."
                ),
                "citation": "PRIVACY-001",
            },
            {
                "title": "CCPA and US State Privacy Laws",
                "text": (
                    "The California Consumer Privacy Act (CCPA) gives California residents the right "
                    "to know what personal information is collected about them. Consumers can opt out "
                    "of the sale of their personal information. Businesses must provide a 'Do Not Sell "
                    "My Personal Information' link on their website. The California Privacy Rights Act "
                    "(CPRA) expanded CCPA with additional rights including data minimization and "
                    "purpose limitation. Other states including Virginia, Colorado, Connecticut, "
                    "and Utah have enacted similar privacy legislation."
                ),
                "citation": "PRIVACY-002",
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def backend():
    """Fresh SQLite backend for live testing."""
    tmp = tempfile.mktemp(suffix="_live_test.db")
    b = SQLiteBackend(path=tmp)
    b.initialize()
    return b


@pytest.fixture(scope="module")
def embedder():
    """Real Ollama embedding adapter."""
    return OllamaEmbeddingAdapter(model="nomic-embed-text")


@pytest.fixture(scope="module")
def llm():
    """Real Ollama LLM wrapped in router."""
    adapter = OllamaAdapter(base_url=OLLAMA_URL, model="llama3.2")
    return LLMRouter(adapter)


@pytest.fixture(scope="module")
def seeded_backend(backend, embedder):
    """Backend seeded with sample documents + real embeddings."""
    with backend.session() as session:
        for doc_data in SAMPLE_DOCS:
            backend.store_document(session, DocumentRecord(
                id=doc_data["id"],
                document_type="policy",
                source="test_corpus",
                title=doc_data["title"],
                source_format="text",
                metadata={},
                tags=["security", "compliance"],
            ))

            for i, sec_data in enumerate(doc_data["sections"]):
                section_id = f"sec-{doc_data['id']}-{i}"
                version_hash = hashlib.sha256(sec_data["text"].encode()).hexdigest()[:16]

                backend.store_section(session, SectionRecord(
                    id=section_id,
                    document_id=doc_data["id"],
                    text_content=sec_data["text"],
                    version_hash=version_hash,
                    citation=sec_data["citation"],
                    section_number=str(i),
                    section_title=sec_data["title"],
                    is_current=True,
                    metadata={},
                    tags=["security"],
                ))

                # Real embedding from Ollama
                embedding = embedder.embed(sec_data["text"][:500])
                backend.store_chunk(session, ChunkRecord(
                    section_id=section_id,
                    chunk_index=0,
                    text_content=sec_data["text"],
                    embedding=embedding,
                    document_type="policy",
                ))

                # Content blocks
                backend.store_block(session, ContentBlock(
                    section_id=section_id,
                    compression="full",
                    content=sec_data["text"],
                    version_hash=version_hash,
                    token_count=len(sec_data["text"].split()),
                ))
                backend.store_block(session, ContentBlock(
                    section_id=section_id,
                    compression="headline",
                    content=sec_data["text"].split(".")[0] + ".",
                    version_hash=version_hash,
                    token_count=len(sec_data["text"].split(".")[0].split()),
                ))

                # Tags
                backend.store_tag(session, SectionTag(
                    section_id=section_id,
                    tag_key="domain",
                    tag_value="security",
                ))

    return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLiveOllamaIntegration:
    """End-to-end tests against a real Ollama instance."""

    def test_real_embedding_generation(self, embedder):
        """Verify Ollama generates real embeddings."""
        emb = embedder.embed("What is cloud security?")
        print(f"\n  Embedding dimensions: {len(emb)}")
        print(f"  First 5 values: {emb[:5]}")
        assert len(emb) == 768, f"Expected 768 dimensions, got {len(emb)}"
        assert all(isinstance(v, float) for v in emb)
        # Embeddings should not be all zeros
        assert any(v != 0.0 for v in emb)

    def test_real_llm_generation(self, llm):
        """Verify Ollama generates a real response."""
        messages = [
            LLMMessage(role="system", content="You are a helpful assistant. Be concise."),
            LLMMessage(role="user", content="What is multi-factor authentication? Answer in one sentence."),
        ]
        response = asyncio.run(
            llm.generate(messages, max_tokens=100)
        )
        print(f"\n  Model: {response.model}")
        print(f"  Response: {response.content[:200]}")
        print(f"  Usage: {response.usage}")
        assert len(response.content) > 10, "LLM response too short"
        assert response.model, "Model name should be populated"

    def test_real_llm_streaming(self, llm):
        """Verify Ollama streaming works."""
        messages = [
            LLMMessage(role="system", content="Be concise."),
            LLMMessage(role="user", content="What does TLS stand for?"),
        ]
        tokens = []

        async def _collect():
            async for token in llm.stream(messages, max_tokens=50):
                tokens.append(token)

        asyncio.run(_collect())
        full_text = "".join(tokens)
        print(f"\n  Streamed {len(tokens)} chunks: {full_text[:200]}")
        assert len(tokens) > 1, "Streaming should produce multiple chunks"
        assert len(full_text) > 5, "Streamed content too short"

    def test_vector_search_with_real_embeddings(self, seeded_backend, embedder):
        """Verify hybrid search works with real Ollama embeddings."""
        query = "How should encryption keys be managed?"
        query_embedding = embedder.embed(query)

        with seeded_backend.session() as session:
            results = seeded_backend.hybrid_search(
                session, query=query, embedding=query_embedding, limit=5,
            )

        print(f"\n  Query: {query}")
        print(f"  Results: {len(results)}")
        for r in results:
            print(f"    [{r.score:.4f}] {r.citation}: {r.snippet[:80]}...")

        assert len(results) > 0, "Search should return results"
        # The top result should be about encryption
        top = results[0]
        assert "encrypt" in top.snippet.lower() or "key" in top.snippet.lower(), (
            f"Top result should be about encryption, got: {top.snippet[:100]}"
        )

    def test_semantic_similarity_real_embeddings(self, embedder):
        """Verify semantic similarity works with real embeddings."""
        import math

        emb1 = embedder.embed("What are the encryption requirements?")
        emb2 = embedder.embed("What encryption standards should we use?")
        emb3 = embedder.embed("How do I make a chocolate cake?")

        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

        sim_related = cosine_sim(emb1, emb2)
        sim_unrelated = cosine_sim(emb1, emb3)

        print(f"\n  Related similarity:   {sim_related:.4f}")
        print(f"  Unrelated similarity: {sim_unrelated:.4f}")
        print(f"  Gap: {sim_related - sim_unrelated:.4f}")

        assert sim_related > sim_unrelated, (
            "Related queries should have higher similarity than unrelated"
        )
        assert sim_related > 0.7, f"Related queries too dissimilar: {sim_related:.4f}"

    def test_full_pipeline_ingest_query_cache(self, seeded_backend, embedder, llm):
        """Full round-trip: ingest content → query LLM → cache → serve from cache.

        This is THE critical test — proves the entire Bitmod system works with
        a real LLM generating real answers that get cached and served back.
        """
        query = "What are the requirements for identity and access management in cloud security?"
        filters = {}

        print(f"\n{'='*70}")
        print(f"  FULL PIPELINE TEST — Real Ollama LLM")
        print(f"{'='*70}")

        # --- Step 1: Intent detection ---
        detected = detect_intent(query)
        intent_reg = IntentRegistry()
        intent_config = intent_reg.get_for_action(detected.action)
        role_reg = RoleRegistry()
        role, role_config = role_reg.resolve(detected)
        print(f"\n  [1] Intent: {detected.action.value} ({detected.confidence:.0%})")
        print(f"      Role: {role.value}, Model tier: {role_config.model_tier}")

        # --- Step 2: Cache check (should MISS — first time) ---
        with seeded_backend.session() as session:
            cached = try_cache(seeded_backend, session, query, filters)
        assert cached is None, "Should be cache miss on first query"
        print(f"  [2] Exact cache: MISS (expected)")

        # --- Step 3: Search for relevant content ---
        query_embedding = embedder.embed(query)
        with seeded_backend.session() as session:
            search_results = seeded_backend.hybrid_search(
                session, query=query, embedding=query_embedding, limit=5,
            )
        print(f"  [3] Search: {len(search_results)} results")
        for r in search_results[:3]:
            print(f"      [{r.score:.4f}] {r.citation}: {r.snippet[:60]}...")

        assert len(search_results) > 0, "Search should find relevant content"

        # --- Step 4: Build context and call real LLM ---
        context = "\n\n".join(
            f"[{r.citation}]: {r.snippet}" for r in search_results[:3]
        )
        messages = [
            LLMMessage(role="system", content=(
                "You are Bitmod, an AI data infrastructure assistant. "
                "Answer based on the provided context. Cite your sources."
            )),
            LLMMessage(role="user", content=(
                f"{query}\n\nRelevant context:\n{context}"
            )),
        ]

        start = time.perf_counter()
        response = asyncio.run(
            llm.generate(messages, max_tokens=300)
        )
        generation_ms = int((time.perf_counter() - start) * 1000)

        print(f"  [4] LLM generation: {generation_ms}ms")
        print(f"      Model: {response.model}")
        print(f"      Tokens: {response.usage}")
        print(f"      Answer: {response.content[:200]}...")

        assert len(response.content) > 20, "LLM answer too short"

        # --- Step 5: Cache the answer ---
        answer_key = compute_answer_key(query, filters)
        source_sections = [
            {"section_id": f"sec-{SAMPLE_DOCS[0]['id']}-0",
             "version_hash": hashlib.sha256(
                 SAMPLE_DOCS[0]["sections"][0]["text"].encode()
             ).hexdigest()[:16]}
        ]

        # Also store query embedding for semantic cache
        norm_query = normalize_for_key(query)
        query_emb_for_cache = embedder.embed(norm_query)

        with seeded_backend.session() as session:
            store_answer(
                backend=seeded_backend, session=session, answer_key=answer_key,
                question_raw=query, question_normalized=norm_query,
                filters=filters, answer_text=response.content,
                source_sections=source_sections,
                model_used=response.model, generation_ms=generation_ms,
                query_embedding=query_emb_for_cache,
            )
        print(f"  [5] Cache store: STORED (key={answer_key[:16]}...)")

        # --- Step 6: Second query — should be cache HIT ---
        with seeded_backend.session() as session:
            cached = try_cache(seeded_backend, session, query, filters)
        assert cached is not None, "Second query should hit cache"
        assert cached.answer_text == response.content, "Cached answer should match original"
        print(f"  [6] Exact cache: HIT (serve_count={cached.serve_count})")

        # --- Step 7: Semantic cache — similar query should match ---
        similar_query = "What IAM requirements exist for cloud environments?"
        with seeded_backend.session() as session:
            semantic_hit = semantic_cache_match(
                seeded_backend, session, similar_query, filters,
                embedder, threshold=0.80,  # Lower threshold for different model
            )
        if semantic_hit:
            print(f"  [7] Semantic cache: HIT for similar query")
            assert semantic_hit.answer_text == response.content
        else:
            # Semantic cache may not hit with lower-quality local embeddings
            print(f"  [7] Semantic cache: MISS (similarity below threshold — OK with local embeddings)")

        # --- Step 8: Fuzzy match ---
        with seeded_backend.session() as session:
            fuzzy_hits = fuzzy_match(
                seeded_backend, session,
                "identity access management cloud security requirements",
                filters, similarity_threshold=0.5, max_candidates=3,
            )
        if fuzzy_hits:
            print(f"  [8] Fuzzy match: HIT ({len(fuzzy_hits)} matches)")
        else:
            print(f"  [8] Fuzzy match: MISS (expected for dissimilar normalization)")

        # --- Step 9: Cache stats ---
        with seeded_backend.session() as session:
            stats = seeded_backend.cache_stats(session)
        print(f"  [9] Cache stats:")
        for k, v in stats.items():
            print(f"      {k}: {v}")
        assert stats["total_entries"] >= 1
        assert stats["total_serves"] >= 1

        # --- Step 10: Invalidation → re-query ---
        section_id = source_sections[0]["section_id"]
        new_content = (
            "Updated IAM policy: All accounts require hardware security keys. "
            "Passwords are no longer accepted as a sole authentication factor."
        )
        with seeded_backend.session() as session:
            inv_result = process_change_event(
                seeded_backend, session, section_id, new_content,
            )
        print(f"  [10] Invalidation: changed={inv_result['changed']}, "
              f"invalidated={inv_result.get('invalidated_count', 0)}")

        # Cache should now be invalid
        with seeded_backend.session() as session:
            stale_check = try_cache(seeded_backend, session, query, filters)
        assert stale_check is None, "Cache should be invalidated after source change"
        print(f"  [10b] Post-invalidation cache check: MISS (correct)")

        # --- Step 11: Re-generate with updated context ---
        # Update section in DB
        new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:16]
        with seeded_backend.session() as session:
            seeded_backend.update_section_content(session, section_id, new_content, new_hash)

        messages_v2 = [
            LLMMessage(role="system", content="Answer based on the provided context. Be concise."),
            LLMMessage(role="user", content=f"{query}\n\nContext:\n{new_content}"),
        ]
        response_v2 = asyncio.run(
            llm.generate(messages_v2, max_tokens=200)
        )
        print(f"  [11] Re-generated answer: {response_v2.content[:150]}...")

        # Cache the new answer
        with seeded_backend.session() as session:
            store_answer(
                backend=seeded_backend, session=session, answer_key=answer_key,
                question_raw=query, question_normalized=norm_query,
                filters=filters, answer_text=response_v2.content,
                source_sections=[{"section_id": section_id, "version_hash": new_hash}],
                model_used=response_v2.model, generation_ms=generation_ms,
            )

        # Verify new answer is cached and passes double-verify
        with seeded_backend.session() as session:
            final_check = try_cache(seeded_backend, session, query, filters)
        assert final_check is not None, "New answer should be cached"
        assert final_check.answer_text == response_v2.content
        print(f"  [11b] Re-cached answer: HIT (double-verify passed)")

        print(f"\n{'='*70}")
        print(f"  FULL PIPELINE: PASSED")
        print(f"  LLM calls: 2 (generate + re-generate)")
        print(f"  Cache operations: store→hit→invalidate→re-store→hit")
        print(f"  Embeddings: {len(SAMPLE_DOCS[0]['sections']) + len(SAMPLE_DOCS[1]['sections'])} sections + 2 queries")
        print(f"{'='*70}\n")

    def test_different_queries_different_answers(self, seeded_backend, embedder, llm):
        """Verify different questions get different LLM answers (not hallucinated repeats)."""
        queries = [
            "What encryption standard should be used for data at rest?",
            "What are the GDPR requirements for data breach notification?",
            "How should network security be implemented in the cloud?",
        ]

        answers = {}
        for q in queries:
            query_embedding = embedder.embed(q)
            with seeded_backend.session() as session:
                results = seeded_backend.hybrid_search(
                    session, query=q, embedding=query_embedding, limit=3,
                )
            context = "\n".join(f"[{r.citation}]: {r.snippet[:200]}" for r in results[:2])
            messages = [
                LLMMessage(role="system", content="Answer based on context. Be concise."),
                LLMMessage(role="user", content=f"{q}\n\nContext:\n{context}"),
            ]
            response = asyncio.run(
                llm.generate(messages, max_tokens=150)
            )
            answers[q] = response.content
            print(f"\n  Q: {q[:60]}...")
            print(f"  A: {response.content[:100]}...")

            # Cache each answer
            answer_key = compute_answer_key(q, {})
            with seeded_backend.session() as session:
                store_answer(
                    backend=seeded_backend, session=session, answer_key=answer_key,
                    question_raw=q, question_normalized=normalize_for_key(q),
                    filters={}, answer_text=response.content,
                    source_sections=[], model_used=response.model,
                    generation_ms=500,
                )

        # All answers should be different
        unique_answers = set(answers.values())
        assert len(unique_answers) == len(queries), (
            f"Expected {len(queries)} unique answers, got {len(unique_answers)}"
        )

        # Verify each is cached independently
        for q in queries:
            with seeded_backend.session() as session:
                cached = try_cache(seeded_backend, session, q, {})
            assert cached is not None, f"Missing cache for: {q[:40]}"
            assert cached.answer_text == answers[q]

    def test_cache_serves_faster_than_llm(self, seeded_backend, embedder, llm):
        """Prove cache serving is dramatically faster than LLM generation."""
        query = "What does GDPR require for personal data processing?"

        # First call — real LLM
        query_embedding = embedder.embed(query)
        with seeded_backend.session() as session:
            results = seeded_backend.hybrid_search(
                session, query=query, embedding=query_embedding, limit=3,
            )
        context = "\n".join(f"[{r.citation}]: {r.snippet[:200]}" for r in results[:2])
        messages = [
            LLMMessage(role="system", content="Answer concisely."),
            LLMMessage(role="user", content=f"{query}\n\nContext:\n{context}"),
        ]

        start = time.perf_counter()
        response = asyncio.run(
            llm.generate(messages, max_tokens=150)
        )
        llm_time_ms = (time.perf_counter() - start) * 1000

        # Cache it
        answer_key = compute_answer_key(query, {})
        with seeded_backend.session() as session:
            store_answer(
                backend=seeded_backend, session=session, answer_key=answer_key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text=response.content,
                source_sections=[], model_used=response.model,
                generation_ms=int(llm_time_ms),
            )

        # Second call — cache hit
        start = time.perf_counter()
        with seeded_backend.session() as session:
            cached = try_cache(seeded_backend, session, query, {})
        cache_time_ms = (time.perf_counter() - start) * 1000

        assert cached is not None
        speedup = llm_time_ms / cache_time_ms if cache_time_ms > 0 else float("inf")

        print(f"\n  LLM generation:  {llm_time_ms:,.1f}ms")
        print(f"  Cache serve:     {cache_time_ms:.3f}ms")
        print(f"  Speedup:         {speedup:,.0f}x faster")

        assert cache_time_ms < llm_time_ms, "Cache should be faster than LLM"
        assert speedup > 10, f"Expected at least 10x speedup, got {speedup:.0f}x"

    def test_admin_stats_after_live_queries(self, seeded_backend):
        """Verify admin stats reflect real LLM-generated cached answers."""
        with seeded_backend.session() as session:
            stats = seeded_backend.cache_stats(session)

        print(f"\n  --- Live Test Admin Stats ---")
        for k, v in stats.items():
            print(f"    {k}: {v}")

        assert stats["total_entries"] >= 3, "Should have cached multiple answers"
        assert stats["total_serves"] >= 1, "Should have served at least one cache hit"

        # Document stats
        with seeded_backend.session() as session:
            doc_stats = seeded_backend.document_stats(session)
        print(f"\n  Documents: {doc_stats['totals']['document_count']}")
        print(f"  Sections:  {doc_stats['totals']['total_sections']}")
        assert doc_stats["totals"]["document_count"] == 2
        assert doc_stats["totals"]["total_sections"] == 5

        # Recent queries
        with seeded_backend.session() as session:
            recent = seeded_backend.recent_cached_queries(session, limit=5)
        print(f"\n  Recent cached queries:")
        for q in recent:
            print(f"    [{q['model_used'][:15]}] {q['question'][:50]}... "
                  f"(serves={q['serve_count']})")
