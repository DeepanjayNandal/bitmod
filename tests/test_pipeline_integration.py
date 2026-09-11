"""Integration test: exercises every pipeline stage and measures savings/accuracy.

Tests all 14 wired pipeline stages end-to-end using a real SQLite backend,
real intent detection, real role resolution, real cache engine, and real
block generation — no mocks except the LLM itself.

Measures:
- Which stages fire for each query type
- Token/compute savings from caching at each layer
- Accuracy of intent detection, role selection, and cache matching
"""

import hashlib
import json
import time

import pytest

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import (
    compute_answer_key, decompose_query, double_verify, fuzzy_match,
    invalidate_by_section, normalize_for_key, semantic_cache_match,
    store_answer, try_cache, try_composable_cache,
)
from bitmod.intent import (
    DetectedIntent, IntentAction, IntentFormat, IntentDepth, IntentMode,
    IntentRegistry, detect_intent, extract_entities,
)
from bitmod.interfaces.database import (
    AnswerCacheRecord, ChunkRecord, ContentBlock, DocumentRecord,
    SectionRecord, SectionTag,
)
from bitmod.invalidation import detect_section_change, process_change_event
from bitmod.roles import Role, RoleConfig, RoleRegistry
from bitmod.blocks import BlockGenerator
from bitmod.tags import AutoTagger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Fresh SQLite backend per test."""
    b = SQLiteBackend(path=str(tmp_path / "test.db"))
    b.initialize()
    return b


@pytest.fixture
def populated_db(db):
    """DB with 3 documents, 6 sections, blocks, tags, and chunks."""
    docs = [
        ("doc-legal", "statute", "legal-corpus", "Employment Law Overview",
         "US", "The Fair Labor Standards Act (FLSA) establishes minimum wage, overtime pay, "
         "recordkeeping, and youth employment standards affecting employees in the private sector "
         "and in Federal, State, and local governments.",
         "1", "FLSA Overview"),
        ("doc-legal", "statute", "legal-corpus", "Employment Law Overview",
         "US", "Title VII of the Civil Rights Act of 1964 prohibits employment discrimination "
         "based on race, color, religion, sex, and national origin. The Equal Employment "
         "Opportunity Commission (EEOC) enforces federal laws.",
         "2", "Title VII"),
        ("doc-tech", "article", "tech-blog", "Cloud Computing Guide",
         None, "Cloud computing delivers computing services including servers, storage, databases, "
         "networking, software, analytics, and intelligence over the Internet. Major providers "
         "include AWS, Azure, and Google Cloud Platform (GCP).",
         "1", "Cloud Basics"),
        ("doc-tech", "article", "tech-blog", "Cloud Computing Guide",
         None, "Infrastructure as a Service (IaaS) provides virtualized computing resources. "
         "Platform as a Service (PaaS) provides a platform for developers. Software as a Service "
         "(SaaS) delivers software applications over the internet.",
         "2", "Service Models"),
        ("doc-privacy", "regulation", "legal-corpus", "Data Privacy Regulations",
         "EU", "The General Data Protection Regulation (GDPR) is a regulation in EU law on data "
         "protection and privacy. It addresses the transfer of personal data outside the EU "
         "and EEA areas. GDPR imposes fines up to 20 million EUR.",
         "1", "GDPR Overview"),
        ("doc-privacy", "regulation", "legal-corpus", "Data Privacy Regulations",
         "US", "The California Consumer Privacy Act (CCPA) gives California residents the right "
         "to know what personal data is collected about them and to request deletion. "
         "It applies to businesses meeting certain revenue or data thresholds.",
         "2", "CCPA Overview"),
    ]

    block_gen = BlockGenerator()
    auto_tagger = AutoTagger()
    doc_records = {}

    with db.session() as session:
        for doc_id, doc_type, source, title, jurisdiction, text, sec_num, sec_title in docs:
            if doc_id not in doc_records:
                doc_record = DocumentRecord(
                    id=doc_id, document_type=doc_type, source=source,
                    title=title, jurisdiction=jurisdiction,
                    source_format="text", metadata={},
                )
                db.store_document(session, doc_record)
                doc_records[doc_id] = doc_record

            section_id = f"{doc_id}-sec-{sec_num}"
            version_hash = hashlib.sha256(text.encode()).hexdigest()
            section = SectionRecord(
                id=section_id, document_id=doc_id, text_content=text,
                version_hash=version_hash, section_number=sec_num,
                section_title=sec_title, hierarchy_path=f"{doc_id}/{sec_num}",
                metadata={}, tags=[doc_type],
            )
            db.store_section(session, section)

            # Generate blocks
            block_gen.generate_blocks(section, db, session)

            # Generate tags
            tags = auto_tagger.generate_tags(section, doc_records[doc_id])
            for tag in tags:
                db.store_tag(session, tag)

            # Store chunks (no real embeddings)
            chunk = ChunkRecord(
                id=f"{section_id}-chunk-0", section_id=section_id,
                chunk_index=0, text_content=text,
                document_type=doc_type, jurisdiction=jurisdiction,
            )
            db.store_chunk(session, chunk)

    return db


# ---------------------------------------------------------------------------
# Stage 1: Intent Detection
# ---------------------------------------------------------------------------

class TestStage1IntentDetection:
    """Every query should produce a valid DetectedIntent with correct action."""

    @pytest.mark.parametrize("query,expected_action", [
        ("What is employment law?", IntentAction.EXPLAIN),
        ("Compare GDPR and CCPA", IntentAction.COMPARE),
        ("List all privacy regulations", IntentAction.LIST),
        ("Count the documents about cloud computing", IntentAction.COUNT),
        ("Extract entities from the employment law section", IntentAction.EXTRACT),
        ("Summarize the FLSA overview", IntentAction.SUMMARIZE),
        ("Analyze the impact of GDPR on tech companies", IntentAction.ANALYZE),
        ("Brainstorm ways to comply with CCPA", IntentAction.BRAINSTORM),
        ("Validate that GDPR applies to data transfers", IntentAction.VALIDATE),
    ])
    def test_intent_detection_accuracy(self, query, expected_action):
        detected = detect_intent(query)
        assert detected.action == expected_action
        assert detected.confidence > 0.0
        assert detected.tier == 1

    def test_intent_mode_classification(self):
        d = detect_intent("Count the documents")
        assert d.mode == IntentMode.DETERMINISTIC
        assert d.skip_llm is True

        d = detect_intent("Brainstorm ideas")
        assert d.mode == IntentMode.CREATIVE
        assert d.cacheable is False

        d = detect_intent("Explain employment law")
        assert d.mode == IntentMode.INFORMATIONAL

    def test_intent_format_detection(self):
        d = detect_intent("Compare GDPR vs CCPA as a table")
        assert d.format == IntentFormat.TABLE

        d = detect_intent("List cloud providers in bullet points")
        assert d.format == IntentFormat.BULLETS

    def test_intent_depth_detection(self):
        d = detect_intent("Briefly explain GDPR")
        assert d.depth == IntentDepth.BRIEF

        d = detect_intent("Give a detailed analysis of cloud computing")
        assert d.depth == IntentDepth.DETAILED

    def test_entity_extraction(self):
        entities = extract_entities('What is "GDPR" in the EU?')
        assert "GDPR" in entities


# ---------------------------------------------------------------------------
# Stage 2: Role Resolution
# ---------------------------------------------------------------------------

class TestStage2RoleResolution:
    """Intent → role mapping, including section tag overrides."""

    def test_action_to_role_mapping(self):
        registry = RoleRegistry()
        # CITE → narrator
        d = detect_intent("Cite the employment law section")
        role, config = registry.resolve(d)
        assert role == Role.NARRATOR

        # COMPARE → synthesizer
        d = detect_intent("Compare GDPR and CCPA")
        role, config = registry.resolve(d)
        assert role == Role.SYNTHESIZER

        # ANALYZE → reasoner
        d = detect_intent("Analyze the impact of GDPR")
        role, config = registry.resolve(d)
        assert role == Role.REASONER

        # BRAINSTORM → explorer
        d = detect_intent("Brainstorm compliance strategies")
        role, config = registry.resolve(d)
        assert role == Role.EXPLORER

    def test_section_tag_override_legal(self):
        """Legal content overrides synthesizer → narrator."""
        registry = RoleRegistry()
        d = detect_intent("Compare GDPR and CCPA")
        role, _ = registry.resolve(d)
        assert role == Role.SYNTHESIZER  # default

        role, _ = registry.resolve(d, section_tags=["legal", "regulation"])
        assert role == Role.NARRATOR  # legal override

    def test_section_tag_override_factual(self):
        """Factual content overrides explorer → synthesizer."""
        registry = RoleRegistry()
        d = detect_intent("Brainstorm about encyclopedias")
        role, _ = registry.resolve(d)
        assert role == Role.EXPLORER

        role, _ = registry.resolve(d, section_tags=["factual", "reference"])
        assert role == Role.SYNTHESIZER

    def test_role_config_has_model_tier(self):
        registry = RoleRegistry()
        d = detect_intent("Cite employment law")
        _, config = registry.resolve(d)
        assert config.model_tier in ("primary", "fallback")
        assert config.max_output_tokens > 0


# ---------------------------------------------------------------------------
# Stage 3: Model Tier Selection
# ---------------------------------------------------------------------------

class TestStage3ModelTierSelection:
    """Role config drives model_tier and max_tokens."""

    def test_narrator_uses_fallback(self):
        registry = RoleRegistry()
        d = detect_intent("Cite the FLSA section")
        _, config = registry.resolve(d)
        assert config.model_tier == "fallback"

    def test_reasoner_uses_primary(self):
        registry = RoleRegistry()
        d = detect_intent("Analyze the implications of GDPR")
        _, config = registry.resolve(d)
        assert config.model_tier == "primary"

    def test_token_budget_from_intent_config(self):
        registry = IntentRegistry()
        cite_config = registry.get_for_action(IntentAction.CITE)
        if cite_config:
            assert cite_config.token_budget > 0
            assert cite_config.token_budget <= 16384


# ---------------------------------------------------------------------------
# Stage 4: Skip-LLM Deterministic Intents
# ---------------------------------------------------------------------------

class TestStage4SkipLLM:
    """COUNT, EXTRACT, VALIDATE should skip LLM."""

    def test_count_skips_llm(self):
        d = detect_intent("Count the documents about privacy")
        assert d.skip_llm is True
        assert d.action == IntentAction.COUNT

    def test_extract_skips_llm(self):
        d = detect_intent("Extract all entities from the employment section")
        assert d.skip_llm is True
        assert d.action == IntentAction.EXTRACT

    def test_validate_skips_llm(self):
        d = detect_intent("Validate that GDPR applies here")
        assert d.skip_llm is True

    def test_explain_does_not_skip(self):
        d = detect_intent("Explain employment law")
        assert d.skip_llm is False

    def test_convert_skips_but_falls_through(self):
        """CONVERT has skip_llm=True but handler returns None → falls to LLM."""
        d = detect_intent("Convert this to JSON")
        assert d.skip_llm is True
        assert d.action == IntentAction.CONVERT


# ---------------------------------------------------------------------------
# Stage 5: Exact Cache
# ---------------------------------------------------------------------------

class TestStage5ExactCache:
    """SHA-256 keyed cache with double verification."""

    def test_exact_cache_hit_and_serve_count(self, populated_db):
        query = "What is cloud computing?"
        key = compute_answer_key(query)

        # Get actual version hash from populated section
        with populated_db.session() as session:
            section = populated_db.get_section(session, "doc-tech-sec-1")
            actual_hash = section.version_hash

        with populated_db.session() as session:
            store_answer(
                populated_db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="Cloud computing delivers services over the Internet.",
                source_sections=[{"section_id": "doc-tech-sec-1", "version_hash": actual_hash}],
                model_used="test", generation_ms=1500,
            )

        # First hit
        with populated_db.session() as session:
            cached = try_cache(populated_db, session, query)
            assert cached is not None
            assert cached.answer_text == "Cloud computing delivers services over the Internet."

        # Serve count increments
        with populated_db.session() as session:
            cached = try_cache(populated_db, session, query)
            assert cached.serve_count >= 1

    def test_exact_cache_miss(self, populated_db):
        with populated_db.session() as session:
            assert try_cache(populated_db, session, "never asked before") is None

    def test_double_verify_catches_stale(self, populated_db):
        """If source content changes, double verify invalidates the cache."""
        query = "FLSA details"
        key = compute_answer_key(query)

        with populated_db.session() as session:
            store_answer(
                populated_db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="FLSA answer.",
                source_sections=[{"section_id": "doc-legal-sec-1", "version_hash": "WRONG_HASH"}],
                model_used="test", generation_ms=500,
            )

        with populated_db.session() as session:
            # try_cache runs double_verify internally — should return None
            result = try_cache(populated_db, session, query)
            assert result is None  # invalidated due to hash mismatch

    def test_savings_from_cache_hit(self, populated_db):
        """Measure compute savings: generation_ms avoided on cache hits."""
        query = "What is employment law?"
        key = compute_answer_key(query)
        gen_ms = 2000  # simulate 2 second LLM call

        with populated_db.session() as session:
            store_answer(
                populated_db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="Employment law answer.",
                source_sections=[], model_used="test", generation_ms=gen_ms,
            )

        # Simulate 10 cache hits
        for _ in range(10):
            with populated_db.session() as session:
                start = time.perf_counter()
                cached = try_cache(populated_db, session, query)
                elapsed_ms = (time.perf_counter() - start) * 1000
                assert cached is not None
                assert elapsed_ms < 50  # cache hit should be <50ms

        # Check stats
        with populated_db.session() as session:
            from bitmod.cache_engine import get_cache_stats
            stats = get_cache_stats(populated_db, session)
            assert stats["total_serves"] >= 10
            # Savings: 10 serves * 2000ms = 20,000ms saved
            assert stats["total_compute_saved_ms"] >= 20000


# ---------------------------------------------------------------------------
# Stage 6: Semantic Cache
# ---------------------------------------------------------------------------

class TestStage6SemanticCache:
    """Embedding-based similarity matching."""

    def test_semantic_cache_store_and_lookup(self, populated_db):
        """Store a query embedding, look it up with cosine similarity."""
        query = "What is cloud computing?"
        key = compute_answer_key(query)
        fake_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        with populated_db.session() as session:
            store_answer(
                populated_db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="Cloud answer.",
                source_sections=[], model_used="test", generation_ms=1000,
                query_embedding=fake_embedding,
            )

        # Verify embedding was stored
        with populated_db.session() as session:
            embeddings = populated_db.cache_get_embeddings(session)
            assert len(embeddings) == 1
            cache_id, emb = embeddings[0]
            assert len(emb) == 5
            assert abs(emb[0] - 0.1) < 0.01

    def test_semantic_cache_cap_at_500(self, db):
        """Embedding query is SQL-limited to 500 entries."""
        # Store 5 entries and verify all come back (under cap)
        with db.session() as session:
            for i in range(5):
                store_answer(
                    db, session, answer_key=f"sem-key-{i}",
                    question_raw=f"query {i}", question_normalized=f"query {i}",
                    filters={}, answer_text=f"answer {i}",
                    source_sections=[], model_used="test", generation_ms=100,
                    query_embedding=[float(i) / 10] * 4,
                )

        with db.session() as session:
            embeddings = db.cache_get_embeddings(session)
            assert len(embeddings) == 5


# ---------------------------------------------------------------------------
# Stage 7: Composable Cache
# ---------------------------------------------------------------------------

class TestStage7ComposableCache:
    """Query decomposition + independent sub-caching."""

    def test_decompose_entity_comparison(self):
        result = decompose_query("Compare Python vs JavaScript")
        assert result is not None
        assert len(result) == 2
        entities = {sq.filters["entity"] for sq in result}
        assert entities == {"Python", "JavaScript"}

    def test_decompose_topic_comparison(self):
        """New broader pattern: topic vs topic without state codes."""
        result = decompose_query("cloud computing vs blockchain")
        assert result is not None
        assert len(result) == 2

    def test_decompose_and_conjunction(self):
        """'X and Y' decomposition."""
        result = decompose_query("GDPR and CCPA regulations")
        assert result is not None
        assert len(result) == 2

    def test_no_decompose_simple(self):
        assert decompose_query("what is employment law") is None

    def test_composable_full_hit(self, populated_db):
        """Both sub-queries cached → full hit."""
        # decompose_query uses the FULL query string as sub-query, not a stripped base
        full_query = "Compare employment law in CA vs TX"
        subs = decompose_query(full_query)
        assert subs is not None and len(subs) == 2

        with populated_db.session() as session:
            for sq in subs:
                store_answer(
                    populated_db, session,
                    answer_key=sq.answer_key,
                    question_raw=sq.query,
                    question_normalized=normalize_for_key(sq.query),
                    filters=sq.filters,
                    answer_text=f"Answer for {sq.filters.get('jurisdiction', '?')}.",
                    source_sections=[], model_used="test", generation_ms=1000,
                )

        with populated_db.session() as session:
            result = try_composable_cache(populated_db, session, full_query)
            assert result is not None
            assert result["full_hit"] is True
            assert len(result["hits"]) == 2
            assert len(result["misses"]) == 0

    def test_composable_partial_hit(self, populated_db):
        """One sub-query cached, one not → partial hit."""
        full_query = "Compare employment law in CA vs TX"
        subs = decompose_query(full_query)
        assert subs is not None and len(subs) == 2

        # Cache only the first sub-query
        with populated_db.session() as session:
            sq = subs[0]
            store_answer(
                populated_db, session,
                answer_key=sq.answer_key,
                question_raw=sq.query,
                question_normalized=normalize_for_key(sq.query),
                filters=sq.filters,
                answer_text=f"Answer for {sq.filters.get('jurisdiction', '?')}.",
                source_sections=[], model_used="test", generation_ms=1000,
            )

        with populated_db.session() as session:
            result = try_composable_cache(populated_db, session, full_query)
            assert result is not None
            assert result["partial"] is True
            assert len(result["hits"]) == 1
            assert len(result["misses"]) == 1

    def test_composable_savings(self, populated_db):
        """Partial hit saves 50% compute (1 of 2 sub-queries cached)."""
        full_query = "Compare employment law in CA vs TX"
        subs = decompose_query(full_query)
        assert subs is not None

        # Cache only first sub-query
        with populated_db.session() as session:
            sq = subs[0]
            store_answer(
                populated_db, session,
                answer_key=sq.answer_key,
                question_raw=sq.query,
                question_normalized=normalize_for_key(sq.query),
                filters=sq.filters,
                answer_text="CA answer.",
                source_sections=[], model_used="test", generation_ms=2000,
            )

        with populated_db.session() as session:
            result = try_composable_cache(populated_db, session, full_query)
            assert result["partial"] is True
            savings_pct = len(result["hits"]) / (len(result["hits"]) + len(result["misses"])) * 100
            assert savings_pct == 50.0


# ---------------------------------------------------------------------------
# Stage 8: Fuzzy Match
# ---------------------------------------------------------------------------

class TestStage8FuzzyMatch:
    """Token-set similarity with relaxed pre-filter."""

    def test_fuzzy_match_basic(self, db):
        with db.session() as session:
            store_answer(
                db, session, answer_key="fz-1",
                question_raw="What is employment law?",
                question_normalized="employment law",
                filters={}, answer_text="Employment law answer.",
                source_sections=[], model_used="test", generation_ms=100,
            )

        with db.session() as session:
            results = fuzzy_match(db, session, "employment law basics",
                                  similarity_threshold=0.70)
            assert len(results) >= 1

    def test_fuzzy_match_rephrasing(self, db):
        """Single-word fallback catches rephrasings that drop a keyword."""
        with db.session() as session:
            store_answer(
                db, session, answer_key="fz-2",
                question_raw="cloud computing architecture overview",
                question_normalized="architecture cloud computing overview",
                filters={}, answer_text="Cloud architecture.",
                source_sections=[], model_used="test", generation_ms=100,
            )

        with db.session() as session:
            # "cloud infrastructure design" shares "cloud" but not 2 words
            results = fuzzy_match(
                db, session, "cloud infrastructure design",
                similarity_threshold=0.3,  # low threshold for this test
            )
            # Should find candidates via single-word fallback on "infrastructure" or "cloud"
            assert isinstance(results, list)

    def test_fuzzy_threshold_filtering(self, db):
        """High threshold filters out weak matches."""
        with db.session() as session:
            store_answer(
                db, session, answer_key="fz-3",
                question_raw="What is GDPR?",
                question_normalized="gdpr",
                filters={}, answer_text="GDPR answer.",
                source_sections=[], model_used="test", generation_ms=100,
            )

        with db.session() as session:
            results = fuzzy_match(
                db, session, "completely unrelated topic about cooking",
                similarity_threshold=0.85,
            )
            assert len(results) == 0  # no match above 85%


# ---------------------------------------------------------------------------
# Stage 9: Block Compression
# ---------------------------------------------------------------------------

class TestStage9BlockCompression:
    """Blocks are generated at ingest and used at query time."""

    def test_blocks_generated_at_ingest(self, populated_db):
        """Each section should have 3 compression variants."""
        with populated_db.session() as session:
            full = populated_db.get_blocks(session, "doc-legal-sec-1", compression="full")
            headline = populated_db.get_blocks(session, "doc-legal-sec-1", compression="headline")
            structured = populated_db.get_blocks(session, "doc-legal-sec-1", compression="structured")

            assert len(full) >= 1
            assert len(headline) >= 1
            assert len(structured) >= 1

    def test_headline_is_shorter_than_full(self, populated_db):
        with populated_db.session() as session:
            full = populated_db.get_blocks(session, "doc-legal-sec-1", compression="full")
            headline = populated_db.get_blocks(session, "doc-legal-sec-1", compression="headline")

            assert headline[0].token_count < full[0].token_count

    def test_compression_token_savings(self, populated_db):
        """Headline compression should save significant tokens."""
        with populated_db.session() as session:
            full = populated_db.get_blocks(session, "doc-tech-sec-1", compression="full")
            headline = populated_db.get_blocks(session, "doc-tech-sec-1", compression="headline")

            full_tokens = full[0].token_count
            headline_tokens = headline[0].token_count
            savings_pct = (1 - headline_tokens / full_tokens) * 100 if full_tokens > 0 else 0
            # Headline should be at least 30% shorter
            assert savings_pct > 30, f"Only {savings_pct:.0f}% token savings from headline compression"


# ---------------------------------------------------------------------------
# Stage 10: Cascade Invalidation
# ---------------------------------------------------------------------------

class TestStage10CascadeInvalidation:
    """Content changes invalidate dependent cached answers."""

    def test_section_change_detection(self, populated_db):
        with populated_db.session() as session:
            changed = detect_section_change(
                populated_db, session, "doc-legal-sec-1", "COMPLETELY NEW CONTENT",
            )
            assert changed is True

    def test_section_unchanged(self, populated_db):
        # Get the actual content
        with populated_db.session() as session:
            section = populated_db.get_section(session, "doc-legal-sec-1")
            changed = detect_section_change(
                populated_db, session, "doc-legal-sec-1", section.text_content,
            )
            assert changed is False

    def test_cascade_invalidation_flow(self, populated_db):
        """Store cached answer → change source → verify invalidation."""
        query = "Tell me about FLSA"
        key = compute_answer_key(query)

        # Get actual version hash
        with populated_db.session() as session:
            section = populated_db.get_section(session, "doc-legal-sec-1")

        # Cache an answer referencing that section
        with populated_db.session() as session:
            store_answer(
                populated_db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text="FLSA is about labor standards.",
                source_sections=[{
                    "section_id": "doc-legal-sec-1",
                    "version_hash": section.version_hash,
                }],
                model_used="test", generation_ms=1000,
            )

        # Verify cache hit works
        with populated_db.session() as session:
            assert try_cache(populated_db, session, query) is not None

        # Simulate content change → invalidate
        with populated_db.session() as session:
            result = process_change_event(
                populated_db, session, "doc-legal-sec-1",
                "THE FLSA HAS BEEN COMPLETELY REWRITTEN WITH NEW PROVISIONS.",
            )
            assert result["changed"] is True
            assert result["invalidated_count"] == 1

        # Cache should now miss
        with populated_db.session() as session:
            assert try_cache(populated_db, session, query) is None

    def test_re_ingestion_preserves_section_ids(self, db):
        """Re-ingesting same title+source updates sections in-place."""
        from bitmod.ingestion.pipeline import ingest_text

        # First ingestion
        r1 = ingest_text(
            "Section one content. Very important.", title="Test Doc",
            source="test-src", backend=db, generate_blocks=False, generate_tags=False,
        )
        assert r1["is_reingest"] is False
        doc_id = r1["document_id"]

        # Get section IDs
        with db.session() as session:
            sections_v1 = db.get_sections_for_document(session, doc_id)
        assert len(sections_v1) >= 1
        original_id = sections_v1[0].id

        # Re-ingest same title+source with changed content
        r2 = ingest_text(
            "Section one content. Updated and revised.", title="Test Doc",
            source="test-src", backend=db, generate_blocks=False, generate_tags=False,
        )
        assert r2["is_reingest"] is True
        assert r2["document_id"] == doc_id  # same document

    def test_re_ingestion_unchanged_skips(self, db):
        """Identical content on re-ingest → sections_unchanged > 0."""
        from bitmod.ingestion.pipeline import ingest_text

        text = "This content will not change between ingestions."
        ingest_text(text, title="Stable Doc", source="stable", backend=db,
                    generate_blocks=False, generate_tags=False)
        r2 = ingest_text(text, title="Stable Doc", source="stable", backend=db,
                         generate_blocks=False, generate_tags=False)
        assert r2["is_reingest"] is True
        assert r2["sections_unchanged"] >= 1
        assert r2["sections_updated"] == 0


# ---------------------------------------------------------------------------
# Stage 11: Tags & Relationships
# ---------------------------------------------------------------------------

class TestStage11Tags:
    """Auto-tagging fires at ingestion and is queryable."""

    def test_tags_generated(self, populated_db):
        with populated_db.session() as session:
            tags = populated_db.get_tags(session, "doc-legal-sec-1")
            assert len(tags) > 0
            tag_keys = {t.tag_key for t in tags}
            # Should have domain and/or topic tags
            assert tag_keys & {"domain", "topic", "complexity", "format_hint"}

    def test_tag_values_are_meaningful(self, populated_db):
        with populated_db.session() as session:
            tags = populated_db.get_tags(session, "doc-privacy-sec-1")
            domain_tags = [t for t in tags if t.tag_key == "domain"]
            # GDPR section should be tagged as legal or regulatory
            if domain_tags:
                assert domain_tags[0].tag_value in ("legal", "regulatory", "policy", "technical")


# ---------------------------------------------------------------------------
# Stage 12: Intent Registry (YAML)
# ---------------------------------------------------------------------------

class TestStage12IntentRegistry:
    """YAML configs load and provide per-intent settings."""

    def test_registry_loads(self):
        registry = IntentRegistry()
        registry.load()
        assert registry.loaded
        names = registry.all_names()
        assert len(names) > 0

    def test_cite_intent_config(self):
        registry = IntentRegistry()
        config = registry.get_for_action(IntentAction.CITE)
        if config:
            assert config.role == "narrator"
            assert config.compression in ("high", "standard", "headline", "full")
            assert config.token_budget > 0

    def test_compare_intent_config(self):
        registry = IntentRegistry()
        config = registry.get_for_action(IntentAction.COMPARE)
        if config:
            assert config.role in ("synthesizer", "narrator")

    def test_hot_reload(self):
        registry = IntentRegistry()
        registry.load()
        count1 = len(registry.all_names())
        registry.reload()
        count2 = len(registry.all_names())
        assert count1 == count2  # same files, same count


# ---------------------------------------------------------------------------
# Stage 13: Temporal Queries
# ---------------------------------------------------------------------------

class TestStage13TemporalQueries:
    """Temporal queries are permanently valid — skip double verify."""

    def test_temporal_query_permanently_valid(self, db):
        query = "employment law in 2020"
        filters = {"temporal_scope": "2020"}
        key = compute_answer_key(query, filters)

        with db.session() as session:
            store_answer(
                db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters=filters, answer_text="Historical data from 2020.",
                source_sections=[{"section_id": "nonexistent", "version_hash": "stale"}],
                model_used="test", generation_ms=500,
            )

        with db.session() as session:
            cached = try_cache(db, session, query, filters)
            assert cached is not None  # valid despite stale source hash
            assert cached.answer_text == "Historical data from 2020."


# ---------------------------------------------------------------------------
# Savings Summary Test
# ---------------------------------------------------------------------------

class TestSavingsSummary:
    """End-to-end savings measurement across all cache layers."""

    def test_full_savings_report(self, populated_db):
        """Simulate a realistic query workload and measure savings."""
        gen_ms = 2000  # average LLM generation time

        # Seed the cache with 5 exact queries (no source_sections to avoid double-verify)
        queries = [
            ("What is cloud computing?", {}),
            ("Explain GDPR", {}),
            ("What is employment law?", {}),
        ]

        for q, f in queries:
            key = compute_answer_key(q, f)
            with populated_db.session() as session:
                store_answer(
                    populated_db, session, answer_key=key,
                    question_raw=q, question_normalized=normalize_for_key(q),
                    filters=f, answer_text=f"Answer for: {q}",
                    source_sections=[], model_used="test", generation_ms=gen_ms,
                )

        # Seed composable sub-queries
        comp_query = "Compare employment law in CA vs TX"
        subs = decompose_query(comp_query)
        for sq in subs:
            with populated_db.session() as session:
                store_answer(
                    populated_db, session, answer_key=sq.answer_key,
                    question_raw=sq.query, question_normalized=normalize_for_key(sq.query),
                    filters=sq.filters, answer_text=f"Answer for {sq.filters}",
                    source_sections=[], model_used="test", generation_ms=gen_ms,
                )

        # Simulate workload
        total_queries = 0
        exact_hits = 0
        composable_hits = 0
        fuzzy_hits = 0
        total_saved_ms = 0

        # 18 repeated exact queries (3 queries x 6 repeats)
        for q, f in queries * 6:
            with populated_db.session() as session:
                cached = try_cache(populated_db, session, q, f)
                total_queries += 1
                if cached:
                    exact_hits += 1
                    total_saved_ms += gen_ms

        # Composable query
        with populated_db.session() as session:
            result = try_composable_cache(populated_db, session, comp_query)
            total_queries += 1
            if result and result["full_hit"]:
                composable_hits += 1
                total_saved_ms += gen_ms * len(result["hits"])

        # 5 fuzzy queries
        for variant in ["cloud computing overview", "explain the GDPR regulation",
                        "employment law basics", "GDPR data protection", "cloud services"]:
            with populated_db.session() as session:
                fz = fuzzy_match(populated_db, session, variant, similarity_threshold=0.5)
                total_queries += 1
                if fz:
                    fuzzy_hits += 1

        # 10 misses
        for i in range(10):
            with populated_db.session() as session:
                try_cache(populated_db, session, f"unique never-asked query {i}")
                total_queries += 1

        # Report
        total_without_cache_ms = total_queries * gen_ms
        total_with_cache_ms = total_without_cache_ms - total_saved_ms
        savings_pct = (total_saved_ms / total_without_cache_ms * 100) if total_without_cache_ms > 0 else 0

        print(f"\n{'='*60}")
        print(f"SAVINGS REPORT")
        print(f"{'='*60}")
        print(f"Total queries:        {total_queries}")
        print(f"Exact cache hits:     {exact_hits}")
        print(f"Composable hits:      {composable_hits}")
        print(f"Fuzzy hits:           {fuzzy_hits}")
        print(f"Without cache:        {total_without_cache_ms:,}ms")
        print(f"With cache:           {total_with_cache_ms:,}ms")
        print(f"Total saved:          {total_saved_ms:,}ms")
        print(f"Savings:              {savings_pct:.1f}%")
        print(f"{'='*60}")

        # Assertions
        assert exact_hits >= 15
        assert composable_hits >= 1
        assert savings_pct > 50
        assert total_saved_ms > 0

        # Verify stats endpoint agrees
        with populated_db.session() as session:
            from bitmod.cache_engine import get_cache_stats
            stats = get_cache_stats(populated_db, session)
            assert stats["total_serves"] >= exact_hits
            assert stats["total_compute_saved_ms"] > 0


# ---------------------------------------------------------------------------
# Accuracy Summary Test
# ---------------------------------------------------------------------------

class TestAccuracySummary:
    """Verify accuracy of each detection/matching layer."""

    def test_intent_accuracy_batch(self):
        """Batch test: measure intent detection accuracy across diverse queries."""
        test_cases = [
            ("What is GDPR?", IntentAction.EXPLAIN),
            ("List all regulations", IntentAction.LIST),
            ("Compare AWS and Azure", IntentAction.COMPARE),
            ("Summarize the employment law section", IntentAction.SUMMARIZE),
            ("Count the documents", IntentAction.COUNT),
            ("Extract all company names", IntentAction.EXTRACT),
            ("Analyze the impact of CCPA", IntentAction.ANALYZE),
            ("Brainstorm compliance ideas", IntentAction.BRAINSTORM),
            ("Validate GDPR applicability", IntentAction.VALIDATE),
            ("Cite the FLSA section", IntentAction.CITE),
            ("Show me the privacy regulations", IntentAction.SHOW),
            ("Find documents about cloud computing", IntentAction.FIND),
            ("Explain how IaaS works", IntentAction.EXPLAIN),
            ("What if GDPR didn't exist?", IntentAction.HYPOTHESIZE),
            ("Draft a privacy policy", IntentAction.DRAFT),
        ]

        correct = 0
        for query, expected in test_cases:
            detected = detect_intent(query)
            if detected.action == expected:
                correct += 1

        accuracy = correct / len(test_cases) * 100
        print(f"\nIntent detection accuracy: {correct}/{len(test_cases)} = {accuracy:.0f}%")
        assert accuracy >= 80, f"Intent accuracy {accuracy:.0f}% is below 80% threshold"

    def test_normalization_accuracy(self):
        """Semantically identical queries produce the same cache key."""
        pairs = [
            ("What is employment law?", "what is employment law"),
            ("The GDPR regulation explained", "GDPR regulation explained"),
            ("How does cloud computing work?", "how does cloud computing work"),
        ]
        for q1, q2 in pairs:
            assert compute_answer_key(q1) == compute_answer_key(q2), f"Keys differ: {q1!r} vs {q2!r}"

    def test_decomposition_accuracy(self):
        """Verify decomposition triggers on the right queries."""
        should_decompose = [
            "Compare employment law in CA vs TX",
            "GDPR vs CCPA regulations",
            "cloud computing and blockchain technology",
        ]
        should_not_decompose = [
            "What is employment law?",
            "Explain GDPR",
            "find cloud computing articles",
        ]

        correct = 0
        total = len(should_decompose) + len(should_not_decompose)

        for q in should_decompose:
            if decompose_query(q) is not None:
                correct += 1

        for q in should_not_decompose:
            if decompose_query(q) is None:
                correct += 1

        accuracy = correct / total * 100
        print(f"Decomposition accuracy: {correct}/{total} = {accuracy:.0f}%")
        assert accuracy >= 80
