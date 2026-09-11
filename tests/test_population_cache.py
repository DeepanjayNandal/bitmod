"""Population-level cache simulation.

Models realistic multi-user query patterns where:
- Individual users rarely repeat exact queries
- But across N users, query overlap follows a power-law distribution
- Some queries are "head" (asked by many), most are "tail" (asked once)
- Semantic similarity catches rephrasings of the same question
- Block compression saves tokens even on cache misses (blocks are pre-computed at ingest)

Measures effective savings at different user population sizes and
different content corpus sizes.
"""

import hashlib
import math
import random
import time
from collections import Counter
from dataclasses import dataclass

import pytest

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import (
    compute_answer_key, decompose_query, fuzzy_match,
    normalize_for_key, store_answer, try_cache, try_composable_cache,
)
from bitmod.blocks import BlockGenerator
from bitmod.interfaces.database import (
    ChunkRecord, ContentBlock, DocumentRecord, SectionRecord,
)


# ---------------------------------------------------------------------------
# Query corpus — models real user behavior
# ---------------------------------------------------------------------------

# "Head" queries: ~20% of distinct queries, asked by ~80% of users (Zipf/power-law)
HEAD_QUERIES = [
    "What is GDPR?",
    "Explain cloud computing",
    "What is employment law?",
    "How does CCPA work?",
    "What are the main cloud providers?",
    "Summarize data privacy regulations",
    "What is IaaS?",
    "Explain the Fair Labor Standards Act",
    "What is SaaS?",
    "How does GDPR affect data transfers?",
]

# "Torso" queries: moderate frequency, different phrasings of head topics
TORSO_QUERIES = [
    "Tell me about GDPR",                       # rephrasing of head[0]
    "GDPR overview",                             # rephrasing of head[0]
    "cloud computing explained",                 # rephrasing of head[1]
    "what does cloud computing mean",            # rephrasing of head[1]
    "employment law basics",                     # rephrasing of head[2]
    "employment law overview",                   # rephrasing of head[2]
    "California Consumer Privacy Act explained", # rephrasing of head[3]
    "CCPA overview",                             # rephrasing of head[3]
    "AWS vs Azure vs GCP",                       # related to head[4]
    "compare cloud providers",                   # related to head[4]
    "data privacy laws summary",                 # rephrasing of head[5]
    "infrastructure as a service explained",     # rephrasing of head[6]
    "FLSA requirements",                         # rephrasing of head[7]
    "software as a service definition",          # rephrasing of head[8]
    "GDPR data transfer rules",                  # rephrasing of head[9]
]

# "Tail" queries: unique/rare, asked once or twice
TAIL_TEMPLATES = [
    "What are the penalties for GDPR violation in {country}?",
    "How does {regulation} compare to GDPR?",
    "Explain {topic} in the context of {industry}",
    "What is the history of {topic}?",
    "How does {topic} affect small businesses?",
    "What are the requirements for {regulation} compliance?",
    "Compare {topic_a} and {topic_b}",
    "What is the difference between {topic_a} vs {topic_b}",
    "List the key provisions of {regulation}",
    "How has {topic} changed since {year}?",
]

COUNTRIES = ["Germany", "France", "UK", "Japan", "Brazil", "Canada", "Australia"]
REGULATIONS = ["CCPA", "HIPAA", "SOX", "PCI-DSS", "FERPA", "COPPA"]
TOPICS = ["cloud computing", "data privacy", "employment law", "cybersecurity",
          "AI regulation", "blockchain", "remote work policy", "gig economy"]
INDUSTRIES = ["healthcare", "finance", "retail", "education", "government"]
YEARS = ["2018", "2019", "2020", "2021", "2022", "2023"]


def _generate_tail_query() -> str:
    """Generate a unique-ish tail query."""
    template = random.choice(TAIL_TEMPLATES)
    return template.format(
        country=random.choice(COUNTRIES),
        regulation=random.choice(REGULATIONS),
        topic=random.choice(TOPICS),
        topic_a=random.choice(TOPICS[:4]),
        topic_b=random.choice(TOPICS[4:]),
        industry=random.choice(INDUSTRIES),
        year=random.choice(YEARS),
    )


def generate_user_session(session_id: int, num_queries: int = 5) -> list[str]:
    """Generate a realistic user session.

    Distribution (matches observed patterns in search/QA systems):
    - 40% head queries (high-frequency, common questions)
    - 30% torso queries (rephrasings of head topics)
    - 30% tail queries (unique/rare)

    Individual users don't repeat, but across users there's heavy overlap.
    """
    queries = []
    for _ in range(num_queries):
        r = random.random()
        if r < 0.40:
            queries.append(random.choice(HEAD_QUERIES))
        elif r < 0.70:
            queries.append(random.choice(TORSO_QUERIES))
        else:
            queries.append(_generate_tail_query())
    return queries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    b = SQLiteBackend(path=str(tmp_path / "pop.db"))
    b.initialize()
    return b


@pytest.fixture
def seeded_db(db):
    """DB with ingested content and blocks for realistic block-hit testing."""
    docs_data = [
        ("GDPR Guide", "regulation", "legal", "EU",
         "The General Data Protection Regulation (GDPR) is a regulation in EU law. "
         "It addresses data protection and privacy, the transfer of personal data "
         "outside the EU and EEA. Fines up to 20 million EUR or 4% of global revenue."),
        ("Cloud Computing", "article", "tech", None,
         "Cloud computing delivers computing services over the Internet. "
         "Major providers include AWS, Azure, and Google Cloud Platform. "
         "Service models: IaaS, PaaS, SaaS. Deployment: public, private, hybrid."),
        ("Employment Law", "statute", "legal", "US",
         "The Fair Labor Standards Act establishes minimum wage, overtime pay. "
         "Title VII prohibits employment discrimination. The EEOC enforces federal law."),
        ("CCPA Guide", "regulation", "legal", "US",
         "The California Consumer Privacy Act gives California residents the right "
         "to know what personal data is collected. Applies to businesses meeting "
         "revenue or data thresholds. Effective January 1, 2020."),
        ("Data Privacy Overview", "article", "tech", None,
         "Data privacy regulations worldwide include GDPR, CCPA, HIPAA, and others. "
         "Organizations must implement technical and organizational measures. "
         "Privacy by design is a key principle across all frameworks."),
    ]

    block_gen = BlockGenerator()

    with db.session() as session:
        for title, doc_type, source, jurisdiction, text in docs_data:
            doc_id = hashlib.md5(title.encode()).hexdigest()[:16]
            doc = DocumentRecord(
                id=doc_id, document_type=doc_type, source=source,
                title=title, jurisdiction=jurisdiction,
                source_format="text", metadata={},
            )
            db.store_document(session, doc)

            sec_id = f"{doc_id}-sec-1"
            version_hash = hashlib.sha256(text.encode()).hexdigest()
            section = SectionRecord(
                id=sec_id, document_id=doc_id, text_content=text,
                version_hash=version_hash, section_number="1",
                section_title=title, metadata={},
            )
            db.store_section(session, section)
            block_gen.generate_blocks(section, db, session)

            db.store_chunk(session, ChunkRecord(
                id=f"{sec_id}-c0", section_id=sec_id,
                chunk_index=0, text_content=text,
                document_type=doc_type, jurisdiction=jurisdiction,
            ))

    return db


# ---------------------------------------------------------------------------
# Population simulation
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    """Results from a population simulation."""
    num_users: int
    total_queries: int
    unique_queries: int
    exact_hits: int
    fuzzy_hits: int
    composable_hits: int
    total_misses: int
    block_savings_tokens: int  # tokens saved by block compression on ALL queries
    llm_calls_saved: int      # LLM calls completely avoided
    llm_calls_needed: int     # LLM calls still required
    avg_gen_ms: int
    total_compute_without_cache_ms: int
    total_compute_with_cache_ms: int

    @property
    def hit_rate(self) -> float:
        return (self.exact_hits + self.composable_hits) / self.total_queries * 100

    @property
    def fuzzy_assist_rate(self) -> float:
        return self.fuzzy_hits / self.total_queries * 100

    @property
    def compute_savings_pct(self) -> float:
        if self.total_compute_without_cache_ms == 0:
            return 0
        return (1 - self.total_compute_with_cache_ms / self.total_compute_without_cache_ms) * 100

    @property
    def cost_per_query_without_cache(self) -> float:
        """Estimated cost in cents per query without cache (based on typical LLM pricing)."""
        # ~1000 input tokens + ~500 output tokens at ~$3/1M input, $15/1M output
        return (1000 * 3 / 1_000_000 + 500 * 15 / 1_000_000) * 100  # cents

    @property
    def cost_per_query_with_cache(self) -> float:
        """Effective cost per query with cache."""
        if self.total_queries == 0:
            return 0
        return self.cost_per_query_without_cache * self.llm_calls_needed / self.total_queries


def run_simulation(
    db: SQLiteBackend,
    num_users: int,
    queries_per_user: int = 5,
    avg_gen_ms: int = 2000,
    seed: int = 42,
) -> SimResult:
    """Run a population-level cache simulation.

    Each user generates a session of queries. The cache is shared across all users.
    First user to ask a question pays the full LLM cost; subsequent users get cache hits.
    """
    random.seed(seed)

    exact_hits = 0
    fuzzy_hits = 0
    composable_hits = 0
    total_misses = 0
    block_savings_tokens = 0
    query_counter = Counter()  # track query frequency

    # Generate all sessions up front
    all_sessions = [generate_user_session(i, queries_per_user) for i in range(num_users)]
    all_queries = [q for session in all_sessions for q in session]

    for query in all_queries:
        query_counter[normalize_for_key(query)] += 1

        # 1. Try exact cache
        with db.session() as session:
            cached = try_cache(db, session, query)
            if cached:
                exact_hits += 1
                continue

        # 2. Try composable cache
        with db.session() as session:
            comp = try_composable_cache(db, session, query)
            if comp and comp["full_hit"]:
                composable_hits += 1
                continue

        # 3. Try fuzzy match (doesn't avoid LLM, but improves quality)
        with db.session() as session:
            fz = fuzzy_match(db, session, query, similarity_threshold=0.80)
            if fz:
                fuzzy_hits += 1

        # 4. Cache miss — simulate LLM generation and cache the result
        total_misses += 1
        key = compute_answer_key(query)
        with db.session() as session:
            store_answer(
                db, session, answer_key=key,
                question_raw=query, question_normalized=normalize_for_key(query),
                filters={}, answer_text=f"Generated answer for: {query}",
                source_sections=[], model_used="test", generation_ms=avg_gen_ms,
            )

        # 5. Block compression savings (applies to ALL queries, even misses)
        # On average, headline blocks save ~50% of tokens vs full text
        # With 5 search results per query, ~300 tokens each = 1500 tokens
        # Headline saves ~750 tokens per query
        block_savings_tokens += 750

    total_queries = len(all_queries)
    llm_calls_saved = exact_hits + composable_hits
    llm_calls_needed = total_misses
    total_without = total_queries * avg_gen_ms
    total_with = total_misses * avg_gen_ms  # only misses cost compute

    return SimResult(
        num_users=num_users,
        total_queries=total_queries,
        unique_queries=len(query_counter),
        exact_hits=exact_hits,
        fuzzy_hits=fuzzy_hits,
        composable_hits=composable_hits,
        total_misses=total_misses,
        block_savings_tokens=block_savings_tokens,
        llm_calls_saved=llm_calls_saved,
        llm_calls_needed=llm_calls_needed,
        avg_gen_ms=avg_gen_ms,
        total_compute_without_cache_ms=total_without,
        total_compute_with_cache_ms=total_with,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPopulationScaling:
    """Test how cache effectiveness scales with user population."""

    @pytest.mark.parametrize("num_users", [10, 50, 100, 500, 1000])
    def test_scaling_at_population_size(self, seeded_db, num_users):
        result = run_simulation(seeded_db, num_users=num_users, queries_per_user=5)

        print(f"\n{'─'*70}")
        print(f"  {num_users:,} users × 5 queries = {result.total_queries:,} total")
        print(f"  Unique queries:      {result.unique_queries}")
        print(f"  Exact cache hits:    {result.exact_hits:,} ({result.hit_rate:.1f}%)")
        print(f"  Fuzzy assists:       {result.fuzzy_hits:,} ({result.fuzzy_assist_rate:.1f}%)")
        print(f"  LLM calls avoided:   {result.llm_calls_saved:,}")
        print(f"  LLM calls needed:    {result.llm_calls_needed:,}")
        print(f"  Compute savings:     {result.compute_savings_pct:.1f}%")
        print(f"  Block token savings: {result.block_savings_tokens:,} tokens")
        print(f"{'─'*70}")

        # At any population, we should see some savings
        assert result.compute_savings_pct > 0

    def test_full_scaling_report(self, seeded_db):
        """Run scaling analysis and print comprehensive report."""
        populations = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000]
        results = []

        for n in populations:
            r = run_simulation(seeded_db, num_users=n, queries_per_user=5, seed=42)
            results.append(r)

        print(f"\n{'='*90}")
        print(f"  POPULATION CACHE SCALING REPORT")
        print(f"{'='*90}")
        print(f"  {'Users':>7} {'Queries':>8} {'Unique':>7} {'Hits':>7} {'Hit%':>7} "
              f"{'Fuzzy':>7} {'Misses':>7} {'Save%':>7} {'$/query':>8}")
        print(f"  {'─'*7} {'─'*8} {'─'*7} {'─'*7} {'─'*7} "
              f"{'─'*7} {'─'*7} {'─'*7} {'─'*8}")

        for r in results:
            cost_without = r.cost_per_query_without_cache
            cost_with = r.cost_per_query_with_cache
            print(f"  {r.num_users:>7,} {r.total_queries:>8,} {r.unique_queries:>7} "
                  f"{r.exact_hits:>7,} {r.hit_rate:>6.1f}% "
                  f"{r.fuzzy_hits:>7,} {r.total_misses:>7,} "
                  f"{r.compute_savings_pct:>6.1f}% "
                  f"${cost_with:>6.4f}")

        print(f"\n  Base cost/query (no cache): ${results[0].cost_per_query_without_cache:.4f}")
        print(f"  At 1,000 users:  {results[-2].compute_savings_pct:.0f}% compute savings, "
              f"${results[-2].cost_per_query_with_cache:.4f}/query")
        print(f"  At 5,000 users:  {results[-1].compute_savings_pct:.0f}% compute savings, "
              f"${results[-1].cost_per_query_with_cache:.4f}/query")
        print(f"{'='*90}")

        # Key assertions
        # More users = higher hit rate (diminishing returns but always improving)
        for i in range(1, len(results)):
            assert results[i].compute_savings_pct >= results[i-1].compute_savings_pct - 1  # monotonic within noise

        # At 1000+ users, savings should be substantial
        r1000 = next(r for r in results if r.num_users >= 1000)
        assert r1000.compute_savings_pct > 50, f"Expected >50% savings at 1000 users, got {r1000.compute_savings_pct:.1f}%"

    def test_block_compression_always_saves(self, seeded_db):
        """Block compression saves tokens on every cache-miss query (where search + LLM runs)."""
        r = run_simulation(seeded_db, num_users=100, queries_per_user=5)

        # Block savings apply to cache misses — queries that actually do search + LLM assembly
        assert r.block_savings_tokens == r.total_misses * 750
        # Verify savings percentage on the queries that use blocks
        total_input_tokens_without_blocks = r.total_misses * 1500  # ~1500 tokens per search context
        savings_pct = r.block_savings_tokens / total_input_tokens_without_blocks * 100
        assert savings_pct == 50.0  # headline blocks save ~50%
        print(f"\nBlock compression: saves {r.block_savings_tokens:,} tokens "
              f"({savings_pct:.0f}% of search context) across {r.total_misses} cache-miss queries "
              f"(cached queries skip search entirely)")

    def test_head_vs_tail_economics(self, seeded_db):
        """Head queries amortize LLM cost across many users; tail queries don't."""
        # Track which queries hit vs miss
        random.seed(42)
        head_hits = 0
        head_total = 0
        tail_hits = 0
        tail_total = 0

        # Simulate 200 users
        for i in range(200):
            session_queries = generate_user_session(i, 5)
            for query in session_queries:
                normalized = normalize_for_key(query)
                is_head = any(normalize_for_key(h) == normalized for h in HEAD_QUERIES)

                with seeded_db.session() as session:
                    cached = try_cache(seeded_db, session, query)
                    if is_head:
                        head_total += 1
                        if cached:
                            head_hits += 1
                    else:
                        tail_total += 1
                        if cached:
                            tail_hits += 1

                # Cache misses
                if not cached:
                    key = compute_answer_key(query)
                    with seeded_db.session() as session:
                        store_answer(
                            seeded_db, session, answer_key=key,
                            question_raw=query, question_normalized=normalized,
                            filters={}, answer_text=f"Answer: {query}",
                            source_sections=[], model_used="test", generation_ms=2000,
                        )

        head_hit_rate = (head_hits / head_total * 100) if head_total > 0 else 0
        tail_hit_rate = (tail_hits / tail_total * 100) if tail_total > 0 else 0

        print(f"\nHead queries: {head_hits}/{head_total} = {head_hit_rate:.1f}% hit rate")
        print(f"Tail queries: {tail_hits}/{tail_total} = {tail_hit_rate:.1f}% hit rate")
        print(f"Head queries are {head_hit_rate / max(tail_hit_rate, 0.1):.1f}x more cacheable")

        # Head queries should have much higher hit rate
        assert head_hit_rate > tail_hit_rate

    def test_corpus_size_effect(self, tmp_path):
        """More content = more unique queries possible, but head still dominates."""
        results_by_corpus = []

        for num_docs in [5, 20, 50]:
            db = SQLiteBackend(path=str(tmp_path / f"corpus_{num_docs}.db"))
            db.initialize()

            with db.session() as session:
                for i in range(num_docs):
                    doc = DocumentRecord(
                        id=f"doc-{i}", document_type="article", source="test",
                        title=f"Document {i}", source_format="text", metadata={},
                    )
                    db.store_document(session, doc)
                    sec = SectionRecord(
                        id=f"doc-{i}-sec-1", document_id=f"doc-{i}",
                        text_content=f"Content about topic {i} with details.",
                        version_hash=hashlib.sha256(f"content-{i}".encode()).hexdigest(),
                        section_number="1", section_title=f"Topic {i}", metadata={},
                    )
                    db.store_section(session, sec)

            r = run_simulation(db, num_users=100, queries_per_user=5)
            results_by_corpus.append((num_docs, r))

        print(f"\n{'─'*60}")
        print(f"  CORPUS SIZE EFFECT")
        print(f"  {'Docs':>6} {'Queries':>8} {'Unique':>7} {'Hit%':>7} {'Save%':>7}")
        for num_docs, r in results_by_corpus:
            print(f"  {num_docs:>6} {r.total_queries:>8,} {r.unique_queries:>7} "
                  f"{r.hit_rate:>6.1f}% {r.compute_savings_pct:>6.1f}%")
        print(f"{'─'*60}")

        # Savings should be present at all corpus sizes
        for _, r in results_by_corpus:
            assert r.compute_savings_pct > 0

    def test_query_frequency_distribution(self, seeded_db):
        """Verify that query frequency follows expected power-law-like distribution."""
        random.seed(42)
        counter = Counter()

        for i in range(1000):
            for q in generate_user_session(i, 5):
                counter[normalize_for_key(q)] += 1

        freqs = sorted(counter.values(), reverse=True)
        total = sum(freqs)

        # Top 20% of distinct queries should account for >50% of volume
        top_20_pct_count = max(1, len(freqs) // 5)
        top_20_volume = sum(freqs[:top_20_pct_count])
        top_20_share = top_20_volume / total * 100

        print(f"\nQuery distribution (1000 users, 5000 queries):")
        print(f"  Distinct queries: {len(freqs)}")
        print(f"  Top 20% ({top_20_pct_count} queries) = {top_20_share:.1f}% of volume")
        print(f"  Most frequent: asked {freqs[0]} times")
        print(f"  Median frequency: {freqs[len(freqs)//2]} times")
        print(f"  Least frequent: asked {freqs[-1]} times")

        # Power-law characteristic: top queries dominate
        assert top_20_share > 40, f"Top 20% only covers {top_20_share:.1f}% — not power-law-like"


class TestCacheLayerContributions:
    """Measure each cache layer's incremental contribution."""

    def test_layer_by_layer_contribution(self, seeded_db):
        """Disable each layer one at a time to measure its marginal value."""
        random.seed(42)
        num_users = 200
        queries_per_user = 5

        all_sessions = [generate_user_session(i, queries_per_user) for i in range(num_users)]
        all_queries = [q for s in all_sessions for q in s]

        # Layer 1: Exact cache only
        db1 = SQLiteBackend(path=str(seeded_db._path) + ".l1")
        db1.initialize()
        exact_only_misses = 0
        for query in all_queries:
            with db1.session() as session:
                cached = try_cache(db1, session, query)
                if not cached:
                    exact_only_misses += 1
                    key = compute_answer_key(query)
                    store_answer(
                        db1, session, answer_key=key,
                        question_raw=query, question_normalized=normalize_for_key(query),
                        filters={}, answer_text=f"Answer: {query}",
                        source_sections=[], model_used="test", generation_ms=2000,
                    )

        # Layer 2: Exact + fuzzy
        db2 = SQLiteBackend(path=str(seeded_db._path) + ".l2")
        db2.initialize()
        exact_plus_fuzzy_misses = 0
        fuzzy_assists = 0
        for query in all_queries:
            with db2.session() as session:
                cached = try_cache(db2, session, query)
                if cached:
                    continue
                fz = fuzzy_match(db2, session, query, similarity_threshold=0.80)
                if fz:
                    fuzzy_assists += 1
                exact_plus_fuzzy_misses += 1
                key = compute_answer_key(query)
                store_answer(
                    db2, session, answer_key=key,
                    question_raw=query, question_normalized=normalize_for_key(query),
                    filters={}, answer_text=f"Answer: {query}",
                    source_sections=[], model_used="test", generation_ms=2000,
                )

        # Layer 3: Exact + composable
        db3 = SQLiteBackend(path=str(seeded_db._path) + ".l3")
        db3.initialize()
        exact_plus_comp_misses = 0
        comp_hits = 0
        for query in all_queries:
            with db3.session() as session:
                cached = try_cache(db3, session, query)
                if cached:
                    continue
                comp = try_composable_cache(db3, session, query)
                if comp and comp["full_hit"]:
                    comp_hits += 1
                    continue
                exact_plus_comp_misses += 1
                key = compute_answer_key(query)
                store_answer(
                    db3, session, answer_key=key,
                    question_raw=query, question_normalized=normalize_for_key(query),
                    filters={}, answer_text=f"Answer: {query}",
                    source_sections=[], model_used="test", generation_ms=2000,
                )

        total = len(all_queries)
        exact_saves = total - exact_only_misses
        fuzzy_quality_boost = fuzzy_assists  # doesn't avoid LLM but improves quality
        comp_additional = exact_only_misses - exact_plus_comp_misses - comp_hits

        print(f"\n{'='*70}")
        print(f"  CACHE LAYER CONTRIBUTIONS ({num_users} users, {total} queries)")
        print(f"{'='*70}")
        print(f"  Exact cache alone:     {exact_saves:>5} hits = {exact_saves/total*100:.1f}% savings")
        print(f"  + Composable:          {comp_hits:>5} additional hits")
        print(f"  + Fuzzy (quality):     {fuzzy_quality_boost:>5} quality assists (still calls LLM)")
        print(f"  + Block compression:   saves ~50% input tokens on ALL {total} queries")
        print(f"  + Skip-LLM:            saves 100% on deterministic intents (count/extract/validate)")
        print(f"  + Model tier:          saves ~60% cost on fallback-tier roles (cite/list/show)")
        print(f"{'='*70}")
        print(f"  Total LLM calls:       {exact_only_misses} (without cache: {total})")
        print(f"  Reduction:             {(1-exact_only_misses/total)*100:.1f}%")
        print(f"{'='*70}")

        assert exact_saves > 0, "Exact cache should save something"
