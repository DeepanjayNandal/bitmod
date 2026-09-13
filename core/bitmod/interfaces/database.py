"""Database backend interface."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Content Blocks — multi-compression representations of section content
# ---------------------------------------------------------------------------


@dataclass
class ContentBlock:
    """A single compression variant of a section's content.

    Each section can have multiple blocks: full text, headline summary,
    and structured key-value extraction.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    section_id: str = ""
    compression: str = "full"  # 'full', 'structured', 'headline'
    content: str = ""  # text for full/headline, JSON string for structured
    version_hash: str = ""  # matches parent section's version_hash
    token_count: int = 0
    created_at: datetime | None = None


@dataclass
class SectionTag:
    """A structured tag attached to a section for faceted retrieval."""

    section_id: str = ""
    tag_key: str = ""  # 'domain', 'topic', 'entity_type', 'entities', 'complexity', 'volatility', 'format_hint'
    tag_value: str = ""
    confidence: float = 1.0
    source: str = "rule"  # 'rule', 'ner', 'llm', 'user'


@dataclass
class SectionRelationship:
    """A directional relationship between two sections."""

    section_a_id: str = ""
    section_b_id: str = ""
    relationship: str = ""  # 'co_retrieval', 'citation', 'supersedes', 'related'
    strength: float = 1.0
    source: str = "co_retrieval"
    hit_count: int = 1


@dataclass
class DocumentRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_type: str = ""
    source: str = ""
    title: str = ""
    jurisdiction: str | None = None
    source_format: str = ""
    metadata: dict = field(default_factory=dict)
    tags: list[str] | None = None
    created_at: datetime | None = None


@dataclass
class SectionRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    text_content: str = ""
    version_hash: str = ""
    citation: str | None = None
    section_number: str | None = None
    section_title: str | None = None
    hierarchy_path: str | None = None
    is_current: bool = True
    metadata: dict = field(default_factory=dict)
    tags: list[str] | None = None
    created_at: datetime | None = None


@dataclass
class ChunkRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    section_id: str = ""
    chunk_index: int = 0
    text_content: str = ""
    embedding: list[float] | None = None
    document_type: str = ""
    jurisdiction: str | None = None
    char_offset: int = 0


@dataclass
class AnswerCacheRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    answer_key: str = ""
    question_raw: str = ""
    question_normalized: str = ""
    filters: dict = field(default_factory=dict)
    answer_text: str = ""
    source_sections: list[dict] = field(default_factory=list)
    model_used: str = ""
    generation_ms: int = 0
    confidence: float | None = None
    is_valid: bool = True
    serve_count: int = 0
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    created_at: datetime | None = None
    namespace_id: str | None = None  # Multi-tenant namespace isolation
    # Which conversation wrote this entry. FOR RETRIEVAL SCOPING ONLY.
    #
    # THIS MUST NEVER ENTER compute_answer_key. Adding it to the key by analogy
    # with namespace_id would fragment the exact key per conversation, which is
    # the filters["_context"] behaviour measured as harmful: it makes the exact
    # path miss entries the cache stored itself, pushing traffic to the semantic
    # layer, which is where cross-conversation collisions happen.
    #
    # None means "we do not know which conversation wrote this" — every entry
    # cached before this column existed. The retrieval filter treats None as a
    # MATCH, not a mismatch: excluding on absence of evidence would make the
    # whole pre-upgrade cache unreachable via semantic in a single deploy.
    conversation_id: str | None = None
    max_age_seconds: int | None = None  # TTL — None means no expiry
    last_served_at: datetime | None = None  # LRU eviction tracking
    estimated_cost: float = 0.0  # Estimated generation cost in USD for cost-aware eviction


@dataclass
class SearchResult:
    section_id: str
    citation: str
    title: str
    snippet: str
    score: float
    # Version hash of the source section, carried so cache writers can record it
    # in source_sections for serve-time double_verify. Defaults to "" for
    # backends that cannot supply it; an empty hash makes an entry unverifiable
    # rather than stale (see cache_engine.double_verify).
    version_hash: str = ""


# ---------------------------------------------------------------------------
# Cohesive Cache — similarity links and atomic facts
# ---------------------------------------------------------------------------


@dataclass
class SimilarityLink:
    """A learned relationship between two near-miss cache entries."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_cache_id: str = ""
    target_cache_id: str = ""
    similarity: float = 0.0
    source_query_norm: str = ""
    target_query_norm: str = ""
    strength: int = 0
    created_at: datetime | None = None


@dataclass
class AtomicFact:
    """A reusable fact decomposed from an LLM-generated answer."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_cache_id: str = ""
    fact_text: str = ""
    entity: str = ""
    category: str = "general"
    confidence: float = 1.0
    quality_score: float = 0.5
    serve_count: int = 0
    namespace_id: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Project Knowledge System — local project indexing & conversation memory
# ---------------------------------------------------------------------------


@dataclass
class ProjectRecord:
    """A locally-tracked project directory."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    root_path: str = ""
    description: str = ""
    language: str = ""
    framework: str = ""
    is_active: bool = True
    last_scanned_at: datetime | None = None
    file_count: int = 0
    total_chunks: int = 0
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ProjectFileRecord:
    """A file tracked within a project."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    relative_path: str = ""
    file_hash: str = ""
    language: str = ""
    size_bytes: int = 0
    last_modified: str = ""
    is_indexed: bool = False
    chunk_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ProjectChunkRecord:
    """A code/text chunk from a project file, with optional embedding."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    file_id: str = ""
    project_id: str = ""
    chunk_index: int = 0
    content: str = ""
    start_line: int = 0
    end_line: int = 0
    symbol_name: str | None = None
    symbol_type: str | None = None
    embedding: list[float] | None = None
    token_count: int = 0
    created_at: datetime | None = None


@dataclass
class ConversationRecord:
    """A recorded conversation exchange for knowledge memory."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str | None = None
    user_message: str = ""
    assistant_response: str = ""
    model_used: str = ""
    cache_hit: bool = False
    rating: int | None = None
    feedback: str | None = None
    context_used: list[dict] = field(default_factory=list)
    generation_ms: int = 0
    created_at: datetime | None = None


@dataclass
class CorrectionRecord:
    """A user correction to an AI response, for learning."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str | None = None
    project_id: str | None = None
    original_question: str = ""
    original_answer: str = ""
    corrected_answer: str = ""
    correction_type: str = "factual"  # factual, incomplete, outdated, wrong_context
    is_applied: bool = False
    embedding: list[float] | None = None
    status: str = "pending"  # pending, approved, rejected — only approved corrections are used in context
    created_at: datetime | None = None


class DatabaseBackend(ABC):
    """Abstract interface for all database backends.

    Implementations: SQLite (built-in), PostgreSQL, MySQL, MongoDB.
    """

    @abstractmethod
    def initialize(self) -> None:
        """Create tables/collections if they don't exist."""

    @abstractmethod
    @contextmanager
    def session(self) -> Generator[Any, None, None]:
        """Yield a session/transaction context. Commits on success, rolls back on error."""

    # --- Documents ---

    @abstractmethod
    def store_document(self, session: Any, doc: DocumentRecord) -> None:
        """Insert a document record."""

    # --- Sections ---

    @abstractmethod
    def store_section(self, session: Any, section: SectionRecord) -> None:
        """Insert a section record."""

    @abstractmethod
    def get_section(self, session: Any, section_id: str) -> SectionRecord | None:
        """Get a section by ID (current version only)."""

    @abstractmethod
    def get_section_by_citation(self, session: Any, citation: str) -> SectionRecord | None:
        """Get a section by citation string."""

    @abstractmethod
    def get_section_version_hashes(self, session: Any, section_ids: list[str]) -> dict[str, str]:
        """Return {section_id: version_hash} for the ids that exist.

        Batch form of get_section_version_hash. double_verify needs one hash per
        source section, so verifying a handful of candidates issued a query per
        section per candidate; a per-request memo collapses that only when the
        candidates happen to cite the same documents.
        """

    @abstractmethod
    def get_section_version_hash(self, session: Any, section_id: str) -> str | None:
        """Get just the version_hash for a current section. Used by cache double-verify."""

    # --- Chunks ---

    @abstractmethod
    def store_chunk(self, session: Any, chunk: ChunkRecord) -> None:
        """Insert a chunk record."""

    @abstractmethod
    def delete_chunks_by_section(self, session: Any, section_id: str) -> int:
        """Delete all chunks for a given section. Returns count deleted."""

    # --- Search ---

    @abstractmethod
    def hybrid_search(
        self,
        session: Any,
        query: str,
        embedding: list[float] | None = None,
        limit: int = 10,
        jurisdiction: str | None = None,
        document_type: str | None = None,
    ) -> list[SearchResult]:
        """Full-text + vector hybrid search. Returns ranked results."""

    # --- Answer Cache ---

    @abstractmethod
    def cache_lookup(self, session: Any, answer_key: str) -> AnswerCacheRecord | None:
        """Look up a valid cached answer by composite key."""

    @abstractmethod
    def cache_store(self, session: Any, record: AnswerCacheRecord) -> None:
        """Store a new cached answer."""

    @abstractmethod
    def cache_invalidate(self, session: Any, answer_id: str, reason: str) -> None:
        """Invalidate a cached answer by ID."""

    @abstractmethod
    def cache_invalidate_by_section(self, session: Any, section_id: str) -> int:
        """Invalidate all cached answers referencing a section. Returns count."""

    @abstractmethod
    def cache_clear_all(self, session: Any, reason: str = "Manual clear") -> int:
        """Invalidate every valid cached answer. Returns count."""

    @abstractmethod
    def cache_increment_serve(self, session: Any, answer_id: str) -> None:
        """Increment the serve count for a cache hit."""

    @abstractmethod
    def cache_stats(self, session: Any) -> dict:
        """Return cache performance statistics."""

    @abstractmethod
    def cache_fuzzy_match(
        self,
        session: Any,
        normalized_query: str,
        filters: dict,
        threshold: float = 0.85,
        max_results: int = 5,
    ) -> list[AnswerCacheRecord]:
        """Find similar cached queries for fuzzy matching."""

    @abstractmethod
    def cache_get_embeddings(
        self,
        session: Any,
        limit: int = 2000,
        namespace_id: str | None = None,
    ) -> list[tuple[str, Any]]:
        """Return (cache_id, embedding) pairs for valid entries, newest first.

        Declared here deliberately. This was previously reached through
        ``hasattr`` and was therefore free to omit ``namespace_id`` — which one
        backend effectively did, and callers "handled" by retrying without the
        argument, turning a tenant boundary into an exception handler. A method
        that carries a namespace belongs on the interface, where a backend that
        cannot scope fails to instantiate rather than failing quietly at
        runtime.

        Implementations must filter to ``namespace_id`` when it is given, and
        must not widen the result set when they cannot.
        """

    # --- Content Blocks ---

    @abstractmethod
    def store_block(self, session: Any, block: ContentBlock) -> None:
        """Insert a content block for a section."""

    @abstractmethod
    def get_blocks(
        self,
        session: Any,
        section_id: str,
        compression: str | None = None,
    ) -> list[ContentBlock]:
        """Get content blocks for a section, optionally filtered by compression type."""

    @abstractmethod
    def invalidate_blocks(self, session: Any, section_id: str) -> int:
        """Delete all content blocks for a section. Returns count deleted."""

    # --- Section Tags ---

    @abstractmethod
    def store_tag(self, session: Any, tag: SectionTag) -> None:
        """Insert a structured tag for a section."""

    @abstractmethod
    def get_tags(self, session: Any, section_id: str) -> list[SectionTag]:
        """Get all tags for a section."""

    @abstractmethod
    def search_by_tag(
        self,
        session: Any,
        tag_key: str,
        tag_value: str,
        limit: int = 20,
    ) -> list[SectionRecord]:
        """Find sections matching a tag key-value pair."""

    # --- Section Relationships ---

    @abstractmethod
    def store_relationship(self, session: Any, rel: SectionRelationship) -> None:
        """Insert a relationship between two sections."""

    @abstractmethod
    def get_relationships(self, session: Any, section_id: str) -> list[SectionRelationship]:
        """Get all relationships involving a section (either side)."""

    @abstractmethod
    def increment_relationship(
        self,
        session: Any,
        section_a_id: str,
        section_b_id: str,
        relationship: str,
    ) -> None:
        """Increment hit_count for an existing relationship, or create with hit_count=1."""

    # --- Re-ingestion support ---

    def get_sections_for_document(self, session: Any, document_id: str) -> list[SectionRecord]:
        """Get all current sections for a document. Used for re-ingestion matching."""
        return []

    def find_document_by_title_and_source(
        self,
        session: Any,
        title: str,
        source: str,
    ) -> DocumentRecord | None:
        """Find an existing document by title + source. Returns None if not found."""
        return None

    def update_section_content(
        self,
        session: Any,
        section_id: str,
        text_content: str,
        version_hash: str,
    ) -> None:
        """Update a section's text content and version hash in-place."""

    def mark_section_not_current(self, session: Any, section_id: str) -> None:
        """Mark a section as no longer current (soft delete)."""

    # --- Namespaces (Multi-tenant isolation) ---

    def namespace_create(self, session: Any, ns: Any) -> None:
        """Create a namespace record."""

    def namespace_get(self, session: Any, namespace_id: str) -> Any:
        """Get a namespace by ID."""
        return None

    def namespace_get_by_name(self, session: Any, name: str) -> Any:
        """Get a namespace by name."""
        return None

    def namespace_list_for_owner(self, session: Any, owner_key_id: str) -> list:
        """List namespaces for an owner."""
        return []

    def namespace_list_all(self, session: Any) -> list:
        """List all namespaces."""
        return []

    def namespace_delete(self, session: Any, namespace_id: str) -> None:
        """Delete a namespace by ID."""

    def namespace_cache_stats(self, session: Any, namespace_id: str) -> dict:
        """Get cache stats scoped to a namespace."""
        return {"total_entries": 0, "valid_entries": 0, "total_serves": 0}

    # --- API Key Management ---

    def store_api_key(self, session: Any, record: dict) -> None:
        """Store an API key record. *record* is a dict with keys:
        id, key_hash, key_preview, name, scopes (JSON str), owner,
        is_active, created_at, expires_at, email.
        """

    def lookup_api_key(self, session: Any, key_hash: str) -> dict | None:
        """Look up an API key by its SHA-256 hash. Returns dict or None."""
        return None

    def list_api_keys(self, session: Any, owner: str | None = None) -> list[dict]:
        """List all API keys, optionally filtered by owner."""
        return []

    def revoke_api_key(self, session: Any, key_id: str) -> bool:
        """Revoke (deactivate) an API key by ID. Returns True if updated."""
        return False

    def touch_api_key(self, session: Any, key_id: str) -> None:
        """Update last_used_at timestamp for an API key."""

    # --- Audit Events ---

    def store_audit_event(self, session: Any, record: dict) -> None:
        """Store an audit event. *record* keys: id, timestamp, event_type,
        actor, source_ip, resource, action, outcome, details_json, correlation_id.
        """

    # --- Submissions (Phase 1) ---

    def store_submission(
        self,
        session: Any,
        submission_id: str,
        type: str,
        content: str,
        title: str = "",
        tags: list[str] | None = None,
        submitted_by: str = "",
    ) -> None:
        """Store a user-submitted content item for moderation."""

    # --- Usage Tracking ---

    def track_usage(
        self,
        session: Any,
        api_key_hash: str,
        endpoint: str,
        cache_hit: bool,
        estimated_savings: float = 0.0,
    ) -> None:
        """Track a single API usage event."""

    def get_usage(self, session: Any, api_key_hash: str) -> dict:
        """Get aggregated usage stats for an API key."""
        return {"total_queries": 0, "cache_hits": 0, "cache_misses": 0, "hit_rate": 0.0, "estimated_savings_usd": 0.0}

    # --- Project Knowledge System ---

    def project_create(self, session: Any, project: ProjectRecord) -> None:
        """Create a project record."""

    def project_get(self, session: Any, project_id: str) -> ProjectRecord | None:
        """Get a project by ID."""
        return None

    def project_get_by_path(self, session: Any, root_path: str) -> ProjectRecord | None:
        """Get a project by its root path."""
        return None

    def project_list(self, session: Any, active_only: bool = True) -> list[ProjectRecord]:
        """List all projects."""
        return []

    def project_update(self, session: Any, project_id: str, **kwargs: Any) -> None:
        """Update project fields."""

    def project_delete(self, session: Any, project_id: str) -> None:
        """Delete a project and all associated data (cascade)."""

    # --- Project Files ---

    def project_file_upsert(self, session: Any, pf: ProjectFileRecord) -> None:
        """Insert or update a project file record."""

    def project_file_get(self, session: Any, project_id: str, relative_path: str) -> ProjectFileRecord | None:
        """Get a file by project + path."""
        return None

    def project_files_list(self, session: Any, project_id: str) -> list[ProjectFileRecord]:
        """List all files in a project."""
        return []

    def project_files_stale(self, session: Any, project_id: str, current_paths: set[str]) -> list[ProjectFileRecord]:
        """Find files in DB that are no longer in current_paths (deleted from disk)."""
        return []

    def project_file_delete(self, session: Any, file_id: str) -> None:
        """Delete a file and its chunks (cascade)."""

    # --- Project Chunks ---

    def project_chunk_store(self, session: Any, chunk: ProjectChunkRecord) -> None:
        """Store a project chunk."""

    def project_chunks_delete_by_file(self, session: Any, file_id: str) -> int:
        """Delete all chunks for a file. Returns count."""
        return 0

    def project_chunks_search(
        self,
        session: Any,
        project_id: str,
        embedding: list[float],
        limit: int = 10,
    ) -> list[ProjectChunkRecord]:
        """Semantic search over project chunks by embedding similarity."""
        return []

    def project_chunks_by_symbol(
        self,
        session: Any,
        project_id: str,
        symbol_name: str,
    ) -> list[ProjectChunkRecord]:
        """Find chunks by symbol name (function, class, etc.)."""
        return []

    # --- Conversations ---

    def conversation_store(self, session: Any, conv: ConversationRecord) -> None:
        """Store a conversation record."""

    def conversation_store_embedding(self, session: Any, conversation_id: str, embedding: list[float]) -> None:
        """Store an embedding for a conversation."""

    def conversation_get(self, session: Any, conversation_id: str) -> ConversationRecord | None:
        """Get a conversation by ID."""
        return None

    def conversation_list(
        self,
        session: Any,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationRecord]:
        """List conversations, optionally filtered by project."""
        return []

    def conversation_search(
        self,
        session: Any,
        embedding: list[float],
        project_id: str | None = None,
        limit: int = 5,
    ) -> list[ConversationRecord]:
        """Semantic search over past conversations."""
        return []

    def conversation_rate(
        self,
        session: Any,
        conversation_id: str,
        rating: int,
        feedback: str = "",
    ) -> None:
        """Rate a conversation (1-5) with optional feedback."""

    # --- Corrections ---

    def correction_store(self, session: Any, correction: CorrectionRecord) -> None:
        """Store a correction."""

    def correction_list(
        self,
        session: Any,
        project_id: str | None = None,
        applied_only: bool = False,
        limit: int = 50,
    ) -> list[CorrectionRecord]:
        """List corrections, optionally filtered."""
        return []

    def correction_search(
        self,
        session: Any,
        embedding: list[float],
        project_id: str | None = None,
        limit: int = 5,
    ) -> list[CorrectionRecord]:
        """Find relevant corrections by semantic similarity."""
        return []

    def correction_mark_applied(self, session: Any, correction_id: str) -> None:
        """Mark a correction as applied."""

    # --- Storage Limits & Eviction ---

    def evict_atomic_facts(self, session: Any, max_facts: int = 500_000) -> int:
        """Evict lowest-value atomic facts when count exceeds max_facts. Returns count deleted."""
        return 0

    def evict_similarity_links(self, session: Any, max_links: int = 1_000_000) -> int:
        """Evict lowest-strength similarity links when count exceeds max_links. Returns count deleted."""
        return 0

    def cleanup_audit_events(self, session: Any, retention_days: int = 90) -> int:
        """Delete audit events older than retention_days. Returns count deleted."""
        return 0

    def count_documents(self, session: Any, namespace_id: str | None = None) -> int:
        """Count documents, optionally filtered by namespace. Returns count."""
        return 0

    # --- Cache Lookup by ID ---

    def cache_lookup_by_id(self, session: Any, cache_id: str) -> AnswerCacheRecord | None:
        """Look up a cached answer by its record ID."""
        return None

    # --- Similarity Links ---

    def store_similarity_link(self, session: Any, link: SimilarityLink) -> None:
        """Store a similarity link between two cache entries."""

    def get_similarity_links(self, session: Any, cache_id: str, limit: int = 5) -> list[SimilarityLink]:
        """Get similarity links originating from a cache entry."""
        return []

    def get_similarity_links_targeting(self, session: Any, cache_id: str, limit: int = 5) -> list[SimilarityLink]:
        """Get similarity links where cache_id is the target (reverse direction)."""
        return []

    def increment_similarity_link_strength(self, session: Any, link_id: str) -> None:
        """Increment the strength counter on a similarity link (successful serve)."""

    def cleanup_weak_links(self, session: Any, max_age_days: int = 30) -> int:
        """Delete similarity links older than max_age_days with strength=0. Returns count."""
        return 0

    # --- Atomic Facts ---

    def store_atomic_fact(self, session: Any, fact: AtomicFact) -> None:
        """Store an atomic fact extracted from a cached answer."""

    def store_atomic_fact_embedding(self, session: Any, fact_id: str, embedding: list[float]) -> None:
        """Store an embedding vector for an atomic fact."""

    def search_atomic_facts(
        self,
        session: Any,
        embedding: list[float],
        limit: int = 5,
        namespace_id: str | None = None,
        vector_index: object | None = None,
    ) -> list[tuple[AtomicFact, float]]:
        """Search atomic facts by embedding similarity. Returns (fact, score) tuples.

        When *vector_index* is provided, implementations should use it for
        fast batch similarity instead of a brute-force scan.
        """
        return []
