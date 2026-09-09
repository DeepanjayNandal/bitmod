"""Bitmod Intelligent Cache Engine.

Implements Patent §VI-§VIII, §XII, §XV, §XIX, §XXII, §XXIV:
- Parameterized answer caching with composite SHA-256 keying
- Source-version locking via source-data manifests
- Serve-time double verification
- Fuzzy query matching (cache miss → similar cached query → user confirmation)
- Semantic cache matching (embedding-based similarity search)
- Composable query decomposition (complex queries → independent sub-caches)
- Temporal queries (point-in-time, permanently valid)
- Adaptive storage tiering (hot/warm/cold)
- Response versioning (version chains, differential display)
- Cache metrics tracking
- TTL-based expiration and LRU eviction

All database operations go through the DatabaseBackend interface —
no direct SQL or ORM coupling.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import struct
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from bitmod.crypto import decrypt_if_needed, encrypt_if_enabled
from bitmod.interfaces.database import AnswerCacheRecord, DatabaseBackend

if TYPE_CHECKING:
    from bitmod.config import CacheConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL / Eviction Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_CACHE_ENTRIES = 100_000
DEFAULT_EVICTION_INTERVAL = 100  # run eviction every N cache writes
MAX_ANSWER_LENGTH = 100_000  # max chars for cached answer text

# Module-level write counter for opportunistic eviction (thread-safe).
# Shared across all backend instances intentionally for global eviction
# coordination — ensures eviction runs at a consistent cadence regardless
# of which backend triggered the write.
_write_counter: int = 0
_write_counter_lock = threading.Lock()

# Module-level cache configuration. Set via configure() or left as defaults.
_cache_config: CacheConfig | None = None
_cache_config_lock = threading.Lock()


def configure(config: CacheConfig) -> None:
    """Set the module-level cache configuration. Call once at startup."""
    global _cache_config
    with _cache_config_lock:
        _cache_config = config


def _get_config():
    """Return the active CacheConfig, creating a default if none set."""
    global _cache_config
    if _cache_config is not None:
        return _cache_config
    with _cache_config_lock:
        if _cache_config is None:
            from bitmod.config import CacheConfig

            _cache_config = CacheConfig()
        return _cache_config


# Comparison keywords used for query decomposition
_COMPARISON_RE = re.compile(
    r"\b(?:compare|compared?\s+to|differences?\s+between|vs\.?|versus)\b",
    re.IGNORECASE,
)


def _extract_entities(text: str) -> list[tuple[str, str, str]]:
    """Extract named entities from text for query decomposition.

    Returns [(entity_value, entity_type, entity_label), ...]
    Entity types: "comparison_item", "proper_noun"

    Pattern-based (no NLP library needed):
    - Quoted strings
    - Items around comparison keywords ("X vs Y", "X compared to Y")
    - Capitalized multi-word phrases ("Machine Learning", "European Union")
    """
    entities: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def _add(value: str, etype: str, label: str) -> None:
        key = value.strip().lower()
        if key and key not in seen and len(key) >= 2:
            seen.add(key)
            entities.append((value.strip(), etype, label))

    # 1. Quoted strings
    for m in re.finditer(r'"([^"]+)"', text):
        _add(m.group(1), "comparison_item", m.group(1))
    for m in re.finditer(r"'([^']+)'", text):
        _add(m.group(1), "comparison_item", m.group(1))

    # 2. Items around comparison keywords
    comp_parts = re.split(
        r"\b(?:compare|compared?\s+to|differences?\s+between|vs\.?|versus)\b",
        text,
        flags=re.IGNORECASE,
    )
    if len(comp_parts) >= 2:
        for part in comp_parts:
            cleaned = re.sub(
                r"\b(?:how|does|do|what|are|is|the|for|in|and|or|between)\b",
                "",
                part,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"[?!.,]+", "", cleaned).strip()
            if cleaned and len(cleaned) >= 2:
                _add(cleaned, "comparison_item", cleaned)

    # 3. Capitalized multi-word phrases (proper nouns)
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        _add(m.group(1), "proper_noun", m.group(1))

    return entities


def _strip_comparison_terms(text: str, entities: list[tuple[str, str, str]]) -> str:
    """Strip comparison keywords and extracted entity values to get the base topic."""
    result = _COMPARISON_RE.sub("", text)
    for value, _etype, _label in entities:
        result = re.sub(re.escape(value), "", result, flags=re.IGNORECASE)
    result = re.sub(r"\b(?:and|or|between)\b", "", result, flags=re.IGNORECASE)
    result = re.sub(r"\bin\s+in\b", "in", result)
    result = re.sub(r"\bin\s*$", "", result)
    result = re.sub(r"^\s*in\b", "", result)
    result = re.sub(r"\bin\s+\?", "", result)
    result = re.sub(r"[?!]+$", "", result)
    result = re.sub(r"\s+", " ", result).strip(" ,.")
    return result


# ---------------------------------------------------------------------------
# Query Normalization
# ---------------------------------------------------------------------------

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "about",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "and",
        "or",
        "but",
        "not",
        "no",
        "if",
        "then",
        "than",
        "so",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "my",
        "your",
        "his",
        "her",
        "our",
        "their",
        "how",
        "when",
        "where",
        "why",
    ]
)


def normalize_query(query: str) -> str:
    """Normalize a query for cache key generation and embeddings.

    Lowercase, remove punctuation, strip stopwords — but PRESERVE word order.
    This ensures that phrase meaning is retained for exact cache keys and
    embedding inputs. For order-independent fuzzy matching, use
    ``normalize_query_fuzzy`` instead.

    .. note::
        Changed in v0.9: word order is now preserved. Existing caches will
        miss on first query after upgrade and be re-cached with the new key
        format. This is acceptable — no data is lost.
    """
    text = query.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()
    tokens = [t for t in tokens if t not in STOPWORDS]
    return " ".join(tokens)


def normalize_query_fuzzy(query: str) -> str:
    """Normalize a query for fuzzy (order-independent) matching.

    Same as ``normalize_query`` but tokens are sorted alphabetically so that
    different word orderings of the same query collapse to the same string.
    """
    text = query.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()
    tokens = [t for t in tokens if t not in STOPWORDS]
    tokens.sort()
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Levenshtein Distance (pure Python — no external deps)
# ---------------------------------------------------------------------------


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Pure Python Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if not s2:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Levenshtein similarity (0.0 to 1.0)."""
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein_distance(s1, s2) / max_len


def _get_embeddings_scoped(
    backend: DatabaseBackend,
    session,
    max_scan: int,
    namespace_id: str | None,
) -> list | None:
    """Read cached embeddings, scoped to a namespace, or refuse.

    Returns ``None`` — distinct from an empty list — when a namespace was
    requested and the backend cannot honour it. Callers must treat that as "no
    matches", never as "search everything".

    ``cache_get_embeddings`` is not part of the DatabaseBackend interface; it is
    reached through ``hasattr``, so a backend can legitimately lack the
    namespace_id or limit parameters. Retrying without namespace_id was the
    previous behaviour and it searched every tenant: the guard downstream reads
    ``if namespace_id and ...``, so passing None disabled the one check that
    would have caught the leak. An exception handler quietly became a
    cross-tenant read.

    Failing closed is the only safe response. A cache miss costs one
    generation; serving across a tenant boundary costs trust, and does so
    silently.
    """
    try:
        rows: list = backend.cache_get_embeddings(session, limit=max_scan, namespace_id=namespace_id)
        return rows
    except TypeError:
        # A conforming backend cannot reach here — cache_get_embeddings is on
        # the interface with this signature. This catches a duck-typed backend
        # that predates it.
        pass

    if namespace_id is not None:
        logger.warning(
            "Backend cannot scope cache_get_embeddings to namespace %s — "
            "returning no matches rather than searching every namespace",
            namespace_id,
        )
        return None

    # No namespace requested, so there is no boundary to cross. Keep older
    # backends working, preferring the scan cap if they accept it.
    try:
        rows = backend.cache_get_embeddings(session, limit=max_scan)
        return rows
    except TypeError:
        rows = backend.cache_get_embeddings(session)
        return rows


def fuzzy_similarity(query_normalized: str, candidate_normalized: str) -> float:
    """Similarity between two fuzzy-normalized queries, in [0.0, 1.0].

    Takes the **greater** of two measures rather than blending them:

    - token overlap, which catches rephrasing ("refund policy" / "policy for
      refunds") but reads a misspelled word as an entirely different one
    - edit distance, which catches typos ("policy" / "pollicy") but is dragged
      down by reordering and added words

    They answer different questions — "same words?" and "same spelling?" — and a
    query is similar if either says yes. Averaging them asserts that both must
    partly agree, which was never the claim, and no weighting satisfies both:
    any weight high enough to pass typos on edit distance pushes the rephrasing
    cases below threshold, because the two measures disagree in opposite
    directions on different inputs.

    Shared by the SQLite and MySQL adapters so the formula has one definition.
    PostgreSQL computes the same shape in SQL with GREATEST(similarity(),
    levenshtein()) to keep the work in the database.
    """
    query_tokens = set(query_normalized.split())
    candidate_tokens = set(candidate_normalized.split())
    if query_tokens and candidate_tokens:
        intersection = query_tokens & candidate_tokens
        union = query_tokens | candidate_tokens
        jaccard = len(intersection) / len(union) if union else 0.0
        # Overlap coefficient: high when one query is a subset of the other,
        # which is what a rephrasing that adds or drops a word looks like.
        overlap = len(intersection) / min(len(query_tokens), len(candidate_tokens))
        token_sim = 0.4 * jaccard + 0.6 * overlap
    else:
        token_sim = 0.0

    edit_sim = _levenshtein_similarity(query_normalized, candidate_normalized)
    return max(token_sim, edit_sim)


def fuzzy_prefilter_terms(query_normalized: str, prefix_length: int | None = None) -> list[str]:
    """Prefixes to pre-filter candidates on, longest token first.

    A whole-word LIKE cannot retrieve the row a typo is meant to find: searching
    for '%pollicy%' will never match stored 'policy', so the candidate is never
    scored and the weighting is irrelevant. Matching on a short prefix keeps
    both spellings in play ('pol') and leaves the decision to scoring.

    Ordering is by descending length then alphabetically. The alphabetical
    tiebreak matters: sorting a set by length alone leaves equal-length tokens
    in set-iteration order, which varies per process under hash randomisation,
    so the same query could retrieve different candidates on different runs.
    """
    if prefix_length is None:
        prefix_length = _get_config().fuzzy_prefix_length
    tokens = {t for t in query_normalized.split() if t}
    ordered = sorted(tokens, key=lambda t: (-len(t), t))
    return [t[:prefix_length] for t in ordered]


# ---------------------------------------------------------------------------
# Composite Key Generation (Patent §VII)
# ---------------------------------------------------------------------------


def compute_answer_key(
    query: str,
    filters: dict | None = None,
    temporal_scope: str | None = None,
    language: str | None = None,
    namespace_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Compute SHA-256 composite answer key.

    Key = SHA-256(normalized_query | filter1:value | ... | temporal | language | namespace | project)

    When namespace_id or project_id is set, it becomes part of the key so that
    the same query in different scopes produces different cache keys.
    """
    normalized = normalize_query(query)
    parts = [normalized]

    if filters:
        for key in sorted(filters.keys()):
            value = filters.get(key, "")
            if value:
                parts.append(f"{key}:{value}")

    if temporal_scope:
        parts.append(f"temporal:{temporal_scope}")

    if language and language != "en":
        parts.append(f"lang:{language}")

    if namespace_id:
        parts.append(f"ns:{namespace_id}")

    if project_id:
        parts.append(f"proj:{project_id}")

    composite = "|".join(parts)
    return hashlib.sha256(composite.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cache Lookup + Double Verification (Patent §VII, §VIII)
# ---------------------------------------------------------------------------


def cache_lookup(backend: DatabaseBackend, session, answer_key: str) -> AnswerCacheRecord | None:
    """Look up a cached answer by composite key. Returns None if not found or invalid."""
    return backend.cache_lookup(session, answer_key)


def double_verify(
    backend: DatabaseBackend,
    session,
    cached: AnswerCacheRecord,
    hash_cache: dict[str, str | None] | None = None,
) -> bool:
    """Serve-time double verification (Patent §VIII).

    Before serving ANY cached answer, verify that every source section's
    version_hash still matches. Returns True if all sources still valid.

    Three distinct outcomes, only one of which invalidates:

    - hash matches            -> verified, safe to serve
    - hash present but differs-> stale, invalidate and refuse
    - hash missing entirely   -> unverifiable, refuse but DO NOT invalidate

    The last case is not evidence of staleness, it is absence of evidence.
    Destroying a row we were unable to check would discard a possibly-valid
    answer, so we decline to serve it and leave it for a writer that records
    the hash.

    ``hash_cache`` is an optional per-request memo of section_id -> current
    hash. Scope it to one request: it is a snapshot, not a long-lived cache.

    Hashes are fetched in one batch per call, and the memo then serves any that
    a later candidate reuses. The two work on different cases and neither
    subsumes the other: candidates citing the same documents are collapsed by
    the memo, and candidates citing entirely different ones — where the memo
    never hits — are collapsed by the batch. Measured over four candidates with
    ten sections each, the memo alone takes 40 queries to 10 when they overlap
    and leaves it at 40 when they do not; batching holds it at one per call.
    """
    source_sections = cached.source_sections or []
    if not source_sections:
        return True

    # Fetch every hash this call needs in one query, minus whatever the memo
    # already holds from an earlier candidate.
    wanted: set[str] = set()
    for source in source_sections:
        section_id = source.get("section_id")
        if section_id and source.get("version_hash"):
            wanted.add(str(section_id))
    unknown = sorted(wanted - set(hash_cache)) if hash_cache is not None else sorted(wanted)
    if unknown and hasattr(backend, "get_section_version_hashes"):
        fetched = backend.get_section_version_hashes(session, unknown)
        resolved: dict[str, str | None] = {sid: fetched.get(sid) for sid in unknown}
        if hash_cache is None:
            hash_cache = resolved
        else:
            hash_cache.update(resolved)

    for source in source_sections:
        section_id = source.get("section_id")
        expected_hash = source.get("version_hash")
        if not section_id:
            continue
        if not expected_hash:
            # Unverifiable, not stale — decline to serve but leave the row intact.
            logger.warning(
                "Source section %s has no version_hash — cannot verify integrity, declining to serve",
                section_id,
            )
            return False

        if hash_cache is not None and section_id in hash_cache:
            current_hash = hash_cache[section_id]
        else:
            current_hash = backend.get_section_version_hash(session, section_id)
            if hash_cache is not None:
                hash_cache[section_id] = current_hash

        if current_hash is None or current_hash != expected_hash:
            backend.cache_invalidate(
                session,
                cached.id,
                reason=f"Double-verify failed: section {section_id} version changed",
            )
            return False

    return True


def is_temporal_query(cached: AnswerCacheRecord) -> bool:
    """Check if this is a temporal/historical query (Patent §XIX).

    Temporal queries are permanently valid — historical data doesn't change.
    """
    filters = cached.filters or {}
    return bool(filters.get("temporal_scope"))


# ---------------------------------------------------------------------------
# Full Cache Flow
# ---------------------------------------------------------------------------


def try_cache(
    backend: DatabaseBackend,
    session,
    query: str,
    filters: dict | None = None,
    namespace_id: str | None = None,
) -> AnswerCacheRecord | None:
    """Full cache lookup flow: key → lookup → double-verify → serve or invalidate.

    Returns the cached answer if valid, None if cache miss or stale.
    When namespace_id is set, the lookup is scoped to that namespace.
    """
    answer_key = compute_answer_key(query, filters, namespace_id=namespace_id)
    cached = backend.cache_lookup(session, answer_key)

    if cached is None:
        return None

    # TTL check: if max_age_seconds is set and the entry has expired, treat as miss
    if _is_expired(cached):
        logger.info("Cache entry expired (TTL): %s...", answer_key[:16])
        backend.cache_invalidate(session, cached.id, reason="TTL expired")
        return None

    # Temporal queries are permanently valid
    if is_temporal_query(cached):
        backend.cache_increment_serve(session, cached.id)
        cached.answer_text = decrypt_if_needed(cached.answer_text)
        return cached

    # Double-verify source versions
    if not double_verify(backend, session, cached):
        logger.info("Cache invalidated by double-verify: %s...", answer_key[:16])
        return None

    backend.cache_increment_serve(session, cached.id)
    cached.answer_text = decrypt_if_needed(cached.answer_text)
    return cached


# ---------------------------------------------------------------------------
# Fuzzy Query Matching (Patent §XII)
# ---------------------------------------------------------------------------


@dataclass
class FuzzyMatch:
    """A fuzzy cache match with its similarity score."""

    record: AnswerCacheRecord
    similarity: float


def fuzzy_match(
    backend: DatabaseBackend,
    session,
    query: str,
    filters: dict | None = None,
    similarity_threshold: float | None = None,
    max_candidates: int | None = None,
    namespace_id: str | None = None,
) -> list[FuzzyMatch]:
    """Find similar cached queries when exact match misses.

    Uses ``normalize_query_fuzzy`` (sorted tokens) so word order doesn't
    affect matching. When namespace_id is set, only matches within that
    namespace are returned.
    """
    cfg = _get_config()
    if similarity_threshold is None:
        similarity_threshold = cfg.fuzzy_threshold
    if max_candidates is None:
        max_candidates = cfg.fuzzy_max_candidates
    normalized = normalize_query_fuzzy(query)
    results = backend.cache_fuzzy_match(
        session,
        normalized,
        filters or {},
        threshold=similarity_threshold,
        max_results=max_candidates,
    )
    if namespace_id:
        results = [r for r in results if r.namespace_id == namespace_id]

    # The adapters score every candidate to apply the threshold and then return
    # bare records, dropping the number. Callers need it to tell a typo apart
    # from a loose token overlap, so it is recomputed here — one place, beside
    # the definition of the measure, rather than at each call site.
    #
    # On PostgreSQL the filtering happens in SQL via GREATEST(similarity(),
    # levenshtein()); this recompute is the Python equivalent of the same
    # formula, so the two can differ in the last decimal. Ordering and
    # threshold remain the database's; only the reported score is recomputed.
    return [
        FuzzyMatch(record=record, similarity=fuzzy_similarity(normalized, record.question_normalized or ""))
        for record in results
    ]


# ---------------------------------------------------------------------------
# Composable Query Decomposition (Patent §XV)
# ---------------------------------------------------------------------------


class SubQuery:
    """A decomposed sub-query that can be independently cached."""

    def __init__(self, query: str, filters: dict, role: str = "component"):
        self.query = query
        self.filters = filters
        self.role = role
        self.answer_key = compute_answer_key(query, filters)
        self.cached_answer: AnswerCacheRecord | None = None


def decompose_query(query: str, filters: dict | None = None) -> list[SubQuery] | None:
    """Decompose a complex query into independently cacheable sub-queries.

    Uses generic entity extraction -- no domain-specific knowledge.
    Returns None if the query is not decomposable (simple query).
    """
    filters = filters or {}

    # Pattern 1: explicit comparison keywords present
    if _COMPARISON_RE.search(query):
        entities = _extract_entities(query)
        comparison_items = [e for e in entities if e[1] == "comparison_item"]

        if len(comparison_items) >= 2:
            base_topic = _strip_comparison_terms(query, entities)

            if base_topic:
                return [
                    SubQuery(
                        f"{item[0]} {base_topic}",
                        {**filters, "entity": item[0]},
                    )
                    for item in comparison_items
                ]
            return [SubQuery(item[0], {**filters, "entity": item[0]}) for item in comparison_items]

    # Pattern 2: "X and Y" -- topic comparison (no explicit compare keyword)
    topic_match = re.match(
        r"^(.+?)\b(?:compare|compared?\s+to|differences?\s+between|vs\.?|versus|and)\b(.+)$",
        query,
        re.IGNORECASE,
    )
    if topic_match:
        topic_a = topic_match.group(1).strip().strip(",")
        topic_b = topic_match.group(2).strip().strip(",")
        if len(topic_a) >= 3 and len(topic_b) >= 3:
            action_words = {"find", "show", "list", "get", "give", "tell", "search"}
            first_word_a = topic_a.split()[0].lower() if topic_a.split() else ""
            if first_word_a not in action_words:
                return [
                    SubQuery(topic_a, filters, role="component"),
                    SubQuery(topic_b, filters, role="component"),
                ]

    return None


def try_composable_cache(
    backend: DatabaseBackend,
    session,
    query: str,
    filters: dict | None = None,
    namespace_id: str | None = None,
    embedder=None,
) -> dict | None:
    """Attempt composable cache lookup.

    Decomposes query → checks cache for each sub-query → returns partial results.
    Tries exact key match first, then semantic match as fallback.
    When namespace_id is set, sub-query lookups are scoped to that namespace.
    """
    sub_queries = decompose_query(query, filters)
    if sub_queries is None:
        return None

    hits = []
    misses = []

    for sq in sub_queries:
        # Try with filters first (exact scoped match), then without filters
        # (users often cache individual queries without entity filters)
        cached = try_cache(backend, session, sq.query, sq.filters, namespace_id=namespace_id)
        if not cached and sq.filters:
            cached = try_cache(backend, session, sq.query, namespace_id=namespace_id)

        # Semantic fallback: similar sub-queries should match
        # via embedding similarity even with different wording
        if not cached and embedder:
            cached = semantic_cache_match(
                backend,
                session,
                sq.query,
                sq.filters,
                embedder,
                threshold=_get_config().composable_threshold,
                namespace_id=namespace_id,
            )
            if not cached and sq.filters:
                cached = semantic_cache_match(
                    backend,
                    session,
                    sq.query,
                    None,
                    embedder,
                    threshold=_get_config().composable_threshold,
                    namespace_id=namespace_id,
                )

        if cached:
            sq.cached_answer = cached
            hits.append(sq)
        else:
            misses.append(sq)

    return {
        "sub_queries": sub_queries,
        "hits": hits,
        "misses": misses,
        "partial": len(hits) > 0 and len(misses) > 0,
        "full_hit": len(misses) == 0,
    }


# ---------------------------------------------------------------------------
# TTL Expiration Check
# ---------------------------------------------------------------------------


def _is_expired(cached: AnswerCacheRecord) -> bool:
    """Return True if a cache entry's TTL has elapsed.

    Entries with max_age_seconds=None never expire.
    """
    if cached.max_age_seconds is None:
        return False
    if cached.created_at is None:
        # Entry has a TTL but no creation timestamp — treat as expired (defensive)
        return True

    created = cached.created_at
    if isinstance(created, str):
        # SQLite stores as ISO string — parse it
        try:
            created = datetime.fromisoformat(created)
        except ValueError:
            return False
    # Ensure timezone-aware comparison
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    elapsed = (now - created).total_seconds()
    return elapsed > cached.max_age_seconds


# ---------------------------------------------------------------------------
# Cache Eviction
# ---------------------------------------------------------------------------


def predict_future_hits(record: AnswerCacheRecord) -> float:
    """Predict future hit probability based on access pattern.

    Uses exponential decay: recent accesses weight more than old ones.
    A record accessed 10 times in the last hour is more valuable than
    one accessed 10 times last month.

    Returns estimated hits in next 24 hours.
    """
    if not record.last_served_at:
        return 0.1  # Never served -> low prediction

    last_served = record.last_served_at
    if isinstance(last_served, str):
        try:
            last_served = datetime.fromisoformat(last_served)
        except ValueError:
            return 0.1
    if last_served.tzinfo is None:
        last_served = last_served.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    hours_since_last = max((now - last_served).total_seconds() / 3600, 0.001)

    # Exponential decay: half-life of 24 hours
    recency_weight = 2 ** (-hours_since_last / 24.0)

    # Scale by historical rate
    created = record.created_at
    if created:
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
            except ValueError:
                created = None
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = max((now - created).total_seconds() / 3600, 1)
            hourly_rate = record.serve_count / age_hours
        else:
            hourly_rate = 0.1
    else:
        hourly_rate = 0.1

    return hourly_rate * recency_weight * 24  # predicted hits in next 24h


def evict_expired_cache(backend: DatabaseBackend, session) -> int:
    """Delete cache entries whose TTL has elapsed. Returns count deleted."""
    if hasattr(backend, "cache_delete_expired"):
        count: int = backend.cache_delete_expired(session)
        if count > 0:
            logger.info("Evicted %d expired cache entries", count)
        return count
    return 0


def evict_lru_cache(
    backend: DatabaseBackend,
    session,
    max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
) -> int:
    """Evict least-recently-used entries when cache exceeds max_entries."""
    if hasattr(backend, "cache_evict_lru"):
        count: int = backend.cache_evict_lru(session, max_entries)
        if count > 0:
            logger.info("LRU-evicted %d cache entries (max=%d)", count, max_entries)
        return count
    return 0


def _maybe_evict(
    backend: DatabaseBackend,
    session,
    max_entries: int | None = None,
    eviction_interval: int | None = None,
) -> None:
    """Opportunistic eviction: runs every N cache writes."""
    cfg = _get_config()
    if max_entries is None:
        max_entries = cfg.max_entries
    if eviction_interval is None:
        eviction_interval = cfg.eviction_interval
    global _write_counter  # noqa: PLW0603
    with _write_counter_lock:
        _write_counter += 1
        should_evict = _write_counter % eviction_interval == 0
    if not should_evict:
        return
    try:
        evict_expired_cache(backend, session)
        evict_lru_cache(backend, session, max_entries)
        # Link decay: clean up weak similarity links
        if hasattr(backend, "cleanup_weak_links"):
            cleaned = backend.cleanup_weak_links(session, max_age_days=cfg.link_cleanup_days)
            if cleaned > 0:
                logger.info("Cleaned up %d weak similarity links", cleaned)
        # Audit event retention: purge entries older than retention period
        if hasattr(backend, "cleanup_audit_events"):
            purged = backend.cleanup_audit_events(session)
            if purged > 0:
                logger.info("Purged %d expired audit events", purged)
    except Exception:
        logger.debug("Opportunistic eviction failed", exc_info=True)


# ---------------------------------------------------------------------------
# Cache Storage
# ---------------------------------------------------------------------------


def store_answer(
    backend: DatabaseBackend,
    session,
    answer_key: str,
    question_raw: str,
    question_normalized: str,
    filters: dict,
    answer_text: str,
    source_sections: list[dict],
    model_used: str,
    generation_ms: int,
    confidence: float | None = None,
    query_embedding: list[float] | None = None,
    namespace_id: str | None = None,
    max_age_seconds: int | None = None,
    max_cache_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
    eviction_interval: int = DEFAULT_EVICTION_INTERVAL,
    estimated_cost: float = 0.0,
) -> AnswerCacheRecord:
    """Store a new answer in the cache, optionally with a query embedding for semantic lookup.

    When namespace_id is set, the cache entry is scoped to that namespace.
    max_age_seconds sets a TTL on this entry (None = no expiry).
    estimated_cost is the approximate USD cost of generating this answer.
    Triggers opportunistic eviction every eviction_interval writes.
    """
    if len(answer_text) > MAX_ANSWER_LENGTH:
        logger.warning(
            "Truncating answer_text from %d to %d chars for cache storage",
            len(answer_text),
            MAX_ANSWER_LENGTH,
        )
        answer_text = answer_text[:MAX_ANSWER_LENGTH]
    stored_text = encrypt_if_enabled(answer_text)
    record = AnswerCacheRecord(
        answer_key=answer_key,
        question_raw=question_raw,
        question_normalized=question_normalized,
        filters=filters,
        answer_text=stored_text,
        source_sections=source_sections,
        model_used=model_used,
        generation_ms=generation_ms,
        confidence=confidence,
        namespace_id=namespace_id,
        max_age_seconds=max_age_seconds,
        estimated_cost=estimated_cost,
    )
    backend.cache_store(session, record)

    # Opportunistic eviction
    _maybe_evict(backend, session, max_entries=max_cache_entries, eviction_interval=eviction_interval)

    # Store query embedding alongside cache entry for semantic lookup
    if query_embedding and hasattr(backend, "cache_store_embedding"):
        try:
            backend.cache_store_embedding(session, record.id, query_embedding)
        except Exception:
            logger.debug("Failed to store query embedding for cache entry %s", record.id[:8])

    return record


# ---------------------------------------------------------------------------
# Semantic Cache Matching (Patent §XII extension)
# ---------------------------------------------------------------------------

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Uses numpy when available for ~10-50x speedup on large vectors.
    Falls back to pure-Python math for zero-dependency environments.
    """
    if _HAS_NUMPY:
        a_arr, b_arr = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        if not (np.all(np.isfinite(a_arr)) and np.all(np.isfinite(b_arr))):
            return 0.0
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))

    if any(not math.isfinite(x) for x in a) or any(not math.isfinite(x) for x in b):
        return 0.0
    dot: float = sum(x * y for x, y in zip(a, b))
    na: float = math.sqrt(sum(x * x for x in a))
    nb: float = math.sqrt(sum(x * x for x in b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return dot / (na * nb)


def semantic_cache_match(
    backend: DatabaseBackend,
    session,
    query: str,
    filters: dict | None,
    embedder,
    threshold: float | None = None,
    namespace_id: str | None = None,
) -> AnswerCacheRecord | None:
    """Embedding-based semantic cache lookup.

    Generates a query embedding, then scans cached query embeddings for
    cosine similarity >= threshold. Returns the best match above threshold,
    or None. When namespace_id is set, only matches within that namespace
    are considered.
    """
    cfg = _get_config()
    if threshold is None:
        threshold = cfg.semantic_threshold
    if not hasattr(backend, "cache_get_embeddings"):
        return None

    try:
        query_emb = embedder.embed(normalize_query(query))
    except Exception:
        return None

    if not query_emb:
        return None

    # Get cached embeddings (capped to prevent memory issues at scale).
    # numpy handles 2000 vectors efficiently; pure-Python fallback is slower
    # but still acceptable for the brute-force scan.
    max_scan = cfg.max_scan_numpy if _HAS_NUMPY else cfg.max_scan_fallback
    # H2: Pass limit and namespace_id to backend to filter at the DB level
    cached_embeddings = _get_embeddings_scoped(backend, session, max_scan, namespace_id)
    if cached_embeddings is None:
        # Backend cannot scope to the requested namespace — refuse rather than
        # search every tenant. See _get_embeddings_scoped.
        return None
    if not cached_embeddings:
        return None
    if len(cached_embeddings) > max_scan:
        # Only scan the most recent entries (they appear first from the JOIN)
        cached_embeddings = cached_embeddings[:max_scan]

    best_id = None
    best_sim = 0.0

    for cache_id, emb in cached_embeddings:
        sim = _cosine_similarity(query_emb, emb)
        if sim > best_sim:
            best_sim = sim
            best_id = cache_id

    if best_sim >= threshold and best_id:
        # Look up the actual cache record
        record = backend.cache_lookup_by_id(session, best_id) if hasattr(backend, "cache_lookup_by_id") else None
        if record:
            # Defence in depth: re-check the namespace on the resolved record
            # rather than trusting that the backend filtered. semantic_cache_search
            # has always done this; this function did not, so it had nothing
            # standing between a mis-scoped query and another tenant's answer.
            if namespace_id is not None and record.namespace_id != namespace_id:
                logger.warning(
                    "Semantic match %s belongs to namespace %s, not %s — refusing to serve",
                    record.id[:12],
                    record.namespace_id,
                    namespace_id,
                )
                return None
            # Decrypt answer_text if encryption is enabled
            record.answer_text = decrypt_if_needed(record.answer_text)
            logger.info("Semantic cache match: %.3f similarity for '%s'", best_sim, query[:50])
            backend.cache_increment_serve(session, record.id)
            return record

    return None


# ---------------------------------------------------------------------------
# Cache Invalidation (Patent §VIII)
# ---------------------------------------------------------------------------


def invalidate_by_section(backend: DatabaseBackend, session, section_id: str) -> int:
    """Invalidate all cached answers that reference a changed section."""
    count = backend.cache_invalidate_by_section(session, section_id)
    if count > 0:
        logger.info("Invalidated %d cached answers referencing section %s", count, section_id)
    return count


# ---------------------------------------------------------------------------
# Cache Metrics
# ---------------------------------------------------------------------------


def get_cache_stats(backend: DatabaseBackend, session, namespace_id: str | None = None) -> dict:
    """Get cache performance statistics, optionally scoped to a namespace."""
    if namespace_id and hasattr(backend, "namespace_cache_stats"):
        return backend.namespace_cache_stats(session, namespace_id)
    return backend.cache_stats(session)


# ---------------------------------------------------------------------------
# Pipeline Evidence Accumulation (Patent §VI cohesive engine)
# ---------------------------------------------------------------------------


@dataclass
class CacheEvidence:
    """A single piece of evidence from one cache layer."""

    layer: str  # "exact", "semantic", "composable", "fuzzy", "similarity_link", "atomic_facts", "session"
    confidence: float  # -1.0 to 1.0 (negative = counter-evidence, e.g. stale source)
    answer_text: str
    record_id: str | None = None
    similarity: float = 0.0
    is_partial: bool = False
    sub_query: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineEvidence:
    """Accumulated evidence from all cache layers."""

    evidences: list[CacheEvidence] = field(default_factory=list)
    total_confidence: float = 0.0
    decision: str = "GENERATE"

    def add(self, evidence: CacheEvidence) -> None:
        self.evidences.append(evidence)
        self._recompute_confidence()

    def _recompute_confidence(self) -> None:
        """Recompute total confidence using Bayesian-style accumulation.

        Positive evidence (confidence > 0) is accumulated multiplicatively:
            total = 1 - product(1 - c_i) for all positive c_i

        Negative evidence (confidence < 0) is subtracted from the total,
        allowing layers to actively reduce confidence (e.g. stale source
        detected, invalidation signal).

        Result is clamped to [0.0, 1.0].
        """
        if not self.evidences:
            self.total_confidence = 0.0
            return

        positive = [e for e in self.evidences if e.confidence > 0]
        negative = [e for e in self.evidences if e.confidence < 0]

        # Accumulate positive evidence multiplicatively
        if positive:
            miss_product = 1.0
            for e in positive:
                miss_product *= 1.0 - e.confidence
            pos_total = 1.0 - miss_product
        else:
            pos_total = 0.0

        # Subtract negative evidence
        neg_total = sum(abs(e.confidence) for e in negative)

        self.total_confidence = max(0.0, min(1.0, pos_total - neg_total))

    def best_single_answer(self) -> CacheEvidence | None:
        candidates = [e for e in self.evidences if not e.is_partial]
        return max(candidates, key=lambda e: e.confidence) if candidates else None

    def context_for_llm(self) -> str:
        parts = []
        for e in sorted(self.evidences, key=lambda x: x.confidence, reverse=True):
            if not e.answer_text:
                continue
            label = f"[{e.layer}:{e.confidence:.2f}]"
            if e.sub_query:
                label += f" (re: {e.sub_query})"
            parts.append(f"{label}\n{e.answer_text}")
        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Semantic Search (multi-result variant)
# ---------------------------------------------------------------------------


@dataclass
class SemanticMatch:
    """A semantic cache match with its similarity score."""

    record: AnswerCacheRecord
    similarity: float


def _similarity_to_confidence(similarity: float, layer: str = "semantic") -> float:
    """Map raw similarity score to confidence value using non-linear curve.

    Always returns a value clamped to [0.0, 1.0].
    """
    if layer == "semantic":
        if similarity >= 0.98:
            result = 0.99
        elif similarity >= 0.92:
            result = 0.85 + (similarity - 0.92) * 1.5
        elif similarity >= 0.85:
            result = 0.55 + (similarity - 0.85) * 4.3
        elif similarity >= 0.75:
            result = 0.25 + (similarity - 0.75) * 3.0
        else:
            result = 0.0
    elif layer == "fuzzy":
        if similarity >= 0.95:
            result = 0.80
        elif similarity >= 0.90:
            result = 0.50 + (similarity - 0.90) * 4.0
        elif similarity >= 0.85:
            result = 0.30 + (similarity - 0.85) * 4.0
        else:
            result = 0.15
    else:
        result = similarity
    return min(1.0, max(0.0, result))


def semantic_cache_search(
    backend: DatabaseBackend,
    session,
    query: str,
    filters: dict | None,
    embedder,
    threshold: float | None = None,
    max_results: int | None = None,
    namespace_id: str | None = None,
    vector_index: object | None = None,
) -> list[SemanticMatch]:
    """Return ALL semantic matches above threshold, sorted by similarity descending.

    Unlike semantic_cache_match which returns only the best match above the
    semantic threshold, this returns multiple matches with their scores for
    evidence accumulation.

    When *vector_index* (a ``VectorIndex`` instance) is provided, it is used
    for the similarity search instead of the brute-force scan — O(1) matrix
    multiply vs O(N) row-by-row comparison.
    """
    cfg = _get_config()
    if threshold is None:
        threshold = cfg.search_threshold
    if max_results is None:
        max_results = cfg.search_max_results
    norm = normalize_query(query)
    try:
        query_embedding = embedder.embed(norm)
    except Exception:
        return []

    if not query_embedding:
        return []

    # Fast path: use the in-memory vector index when available
    if vector_index is not None and hasattr(vector_index, "search") and hasattr(vector_index, "count"):
        if vector_index.count() > 0:
            raw_matches = vector_index.search(query_embedding, k=max_results * 2)
            matches_vi = [(cid, sim) for cid, sim in raw_matches if sim >= threshold][:max_results]
            results: list[SemanticMatch] = []
            for cache_id, sim in matches_vi:
                record = (
                    backend.cache_lookup_by_id(session, cache_id) if hasattr(backend, "cache_lookup_by_id") else None
                )
                if record and record.is_valid:
                    if namespace_id and record.namespace_id != namespace_id:
                        continue
                    record.answer_text = decrypt_if_needed(record.answer_text)
                    results.append(SemanticMatch(record=record, similarity=sim))
            return results

    # Fallback: brute-force scan
    if not hasattr(backend, "cache_get_embeddings"):
        return []
    cached = _get_embeddings_scoped(backend, session, cfg.max_scan_numpy, namespace_id)
    if cached is None:
        # Backend cannot scope to the requested namespace — see the helper.
        return []
    if not cached:
        return []

    matches: list[tuple[str, float]] = []
    for cache_id, embedding_data in cached:
        if isinstance(embedding_data, bytes):
            n_floats = len(embedding_data) // 4
            emb = list(struct.unpack(f"{n_floats}f", embedding_data))
        elif isinstance(embedding_data, list):
            emb = embedding_data
        else:
            continue

        sim = _cosine_similarity(query_embedding, emb)
        if sim >= threshold:
            matches.append((cache_id, sim))

    matches.sort(key=lambda x: x[1], reverse=True)
    matches = matches[:max_results]

    results = []
    for cache_id, sim in matches:
        record = backend.cache_lookup_by_id(session, cache_id) if hasattr(backend, "cache_lookup_by_id") else None
        if record and record.is_valid:
            record.answer_text = decrypt_if_needed(record.answer_text)
            results.append(SemanticMatch(record=record, similarity=sim))

    return results


# ---------------------------------------------------------------------------
# Atomic Fact Decomposition
# ---------------------------------------------------------------------------


def decompose_answer(answer_text: str) -> list[dict]:
    """Break an answer into atomic reusable facts using heuristic rules.

    Rule-based decomposition -- no LLM call needed. Splits on sentence
    boundaries and filters filler sentences.
    """
    sentences = re.split(r"(?<=[.!?])\s+", answer_text.strip())

    filler_patterns = re.compile(
        r"^(however|additionally|moreover|furthermore|in conclusion|"
        r"to summarize|as mentioned|it is worth noting|please note|"
        r"i hope this helps|let me know)\b",
        re.IGNORECASE,
    )

    facts: list[dict] = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 30:
            continue
        if len(sent) > 500:
            continue
        if filler_patterns.match(sent):
            continue
        if sent.endswith("?"):
            continue

        # Match Title Case proper nouns AND ALLCAPS acronyms (GDPR, HIPAA, SOC2, etc.)
        entity_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", sent)
        if not entity_match:
            entity_match = re.search(r"\b([A-Z][A-Z0-9]{1,})\b", sent)
        entity = entity_match.group(1) if entity_match else ""

        category = "general"
        if re.search(r"\b(defined as|means|refers to|is a|is the)\b", sent, re.IGNORECASE):
            category = "definition"
        elif re.search(r"\b(must|shall|required|prohibited|allowed)\b", sent, re.IGNORECASE):
            category = "rule"
        elif re.search(r"\b(compared to|unlike|whereas|while|differs)\b", sent, re.IGNORECASE):
            category = "comparison"
        elif re.search(r"\b(step|first|then|next|finally|process)\b", sent, re.IGNORECASE):
            category = "procedure"
        elif re.search(r"\b(\d+%|\$\d|million|billion|percent)\b", sent, re.IGNORECASE):
            category = "statistic"

        # Quality scoring: longer facts, entities, numbers, and reusable categories score higher
        quality = 0.5 if len(sent) < 50 else 0.7
        if entity:
            quality += 0.1
        if re.search(r"\b\d+(?:\.\d+)?(?:%|\$|million|billion|percent)\b", sent, re.IGNORECASE):
            quality += 0.1
        if category in ("definition", "rule"):
            quality += 0.1
        quality = min(quality, 0.9)

        facts.append(
            {
                "fact_text": sent,
                "category": category,
                "entity": entity,
                "quality_score": round(quality, 2),
            }
        )

    return facts


# ---------------------------------------------------------------------------
# Cost Estimation
# ---------------------------------------------------------------------------

# Approximate cost per 1K tokens by model family: (input_cost, output_cost)
_MODEL_COST_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-opus-4": (0.015, 0.075),
    "claude-sonnet-4": (0.003, 0.015),
    "gemini-2.5-pro": (0.00125, 0.01),
    "gemini-2.0-flash": (0.0001, 0.001),
    "gemini-1.5-pro": (0.00125, 0.007),
}


def estimate_generation_cost(model_used: str, answer_text: str, input_text: str = "") -> float:
    """Estimate the USD cost of generating answer_text with model_used.

    Uses approximate token count (chars/4) and model pricing lookup.
    Includes both input and output token costs.
    Returns 0.0 for unknown models.
    """
    approx_output_tokens = len(answer_text) / 4.0
    approx_input_tokens = len(input_text) / 4.0 if input_text else 0.0
    # Find best matching model key
    model_lower = model_used.lower()
    input_cost_per_1k = 0.0
    output_cost_per_1k = 0.0
    for prefix, (in_cost, out_cost) in _MODEL_COST_PER_1K.items():
        if model_lower.startswith(prefix.lower()):
            input_cost_per_1k = in_cost
            output_cost_per_1k = out_cost
            break
    total = (approx_input_tokens * input_cost_per_1k + approx_output_tokens * output_cost_per_1k) / 1000.0
    return round(total, 6)
