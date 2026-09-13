"""MySQL/MariaDB database backend — SQLAlchemy + PyMySQL."""

from __future__ import annotations

import logging
import struct
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from bitmod.interfaces.database import (  # noqa: E402
    AnswerCacheRecord,
    ChunkRecord,
    ContentBlock,
    DatabaseBackend,
    DocumentRecord,
    SearchResult,
    SectionRecord,
    SectionRelationship,
    SectionTag,
)

try:
    from sqlalchemy import (  # noqa: E402
        JSON,
        Boolean,
        Column,
        DateTime,
        Float,
        Integer,
        LargeBinary,
        MetaData,
        String,
        Table,
        Text,
        UniqueConstraint,
        create_engine,
        delete,
        func,
        select,
        text,
        update,
    )
    from sqlalchemy.orm import sessionmaker  # noqa: E402
except ImportError as e:
    raise ImportError("MySQL backend requires: pip install bitmod[mysql]") from e


class MySQLBackend(DatabaseBackend):
    def __init__(self, url: str):
        self._engine = create_engine(url, pool_size=5, max_overflow=10, pool_recycle=3600)
        self._Session = sessionmaker(bind=self._engine)
        self._meta = MetaData()

    def initialize(self) -> None:
        # --- Core tables ---
        self._documents = Table(
            "documents",
            self._meta,
            Column("id", String(36), primary_key=True),
            Column("document_type", String(100), default=""),
            Column("source", String(255), default=""),
            Column("title", String(500), default=""),
            Column("jurisdiction", String(50), nullable=True),
            Column("source_format", String(50), default=""),
            Column("metadata", JSON, default={}),
            Column("tags", JSON, nullable=True),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )
        self._sections = Table(
            "sections",
            self._meta,
            Column("id", String(36), primary_key=True),
            Column("document_id", String(36), nullable=False),
            Column("text_content", Text, default=""),
            Column("version_hash", String(64), default=""),
            Column("citation", String(500), nullable=True),
            Column("section_number", String(50), nullable=True),
            Column("section_title", String(500), nullable=True),
            Column("hierarchy_path", String(1000), nullable=True),
            Column("is_current", Boolean, default=True),
            Column("metadata", JSON, default={}),
            Column("tags", JSON, nullable=True),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )
        self._chunks = Table(
            "chunks",
            self._meta,
            Column("id", String(36), primary_key=True),
            Column("section_id", String(36), nullable=False),
            Column("chunk_index", Integer, default=0),
            Column("text_content", Text, default=""),
            Column("document_type", String(100), default=""),
            Column("jurisdiction", String(50), nullable=True),
            Column("char_offset", Integer, default=0),
        )

        # --- Answer cache ---
        self._cache = Table(
            "answer_cache",
            self._meta,
            Column("id", String(36), primary_key=True),
            Column("answer_key", String(64), unique=True, nullable=False),
            Column("question_raw", Text, default=""),
            Column("question_normalized", Text, default=""),
            Column("filters", JSON, default={}),
            Column("answer_text", Text, default=""),
            Column("source_sections", JSON, default=[]),
            Column("model_used", String(100), default=""),
            Column("generation_ms", Integer, default=0),
            Column("confidence", Float, nullable=True),
            Column("is_valid", Boolean, default=True),
            Column("serve_count", Integer, default=0),
            Column("invalidated_at", DateTime, nullable=True),
            Column("invalidation_reason", Text, nullable=True),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
            # These four existed only on SQLite. Their absence here was silent:
            # store_answer wrote them, SQLAlchemy dropped them, and they read
            # back as None — so namespace isolation, TTL expiry and both
            # eviction strategies were inert on this backend while the code
            # that used them looked correct.
            # Retrieval scoping only — never part of the answer key. See
            # AnswerCacheRecord.conversation_id.
            Column("conversation_id", String(64), nullable=True),
            Column("namespace_id", String(64), nullable=True),
            Column("max_age_seconds", Integer, nullable=True),
            Column("last_served_at", DateTime, nullable=True),
            Column("estimated_cost", Float, default=0.0),
        )

        # --- Content blocks (multi-compression) ---
        self._blocks = Table(
            "content_blocks",
            self._meta,
            Column("id", String(36), primary_key=True),
            Column("section_id", String(36), nullable=False),
            Column("compression", String(50), default="full"),
            Column("content", Text, default=""),
            Column("version_hash", String(64), default=""),
            Column("token_count", Integer, default=0),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )

        # --- Section tags ---
        self._tags = Table(
            "section_tags",
            self._meta,
            Column("section_id", String(36), nullable=False),
            Column("tag_key", String(100), nullable=False),
            Column("tag_value", String(500), nullable=False),
            Column("confidence", Float, default=1.0),
            Column("source", String(50), default="rule"),
            UniqueConstraint("section_id", "tag_key", "tag_value", name="uq_section_tag"),
        )

        # --- Section relationships ---
        self._relationships = Table(
            "section_relationships",
            self._meta,
            Column("section_a_id", String(36), nullable=False),
            Column("section_b_id", String(36), nullable=False),
            Column("relationship", String(100), nullable=False),
            Column("strength", Float, default=1.0),
            Column("source", String(50), default="co_retrieval"),
            Column("hit_count", Integer, default=1),
            UniqueConstraint("section_a_id", "section_b_id", "relationship", name="uq_section_rel"),
        )

        # --- Semantic cache embeddings (stored as BLOB) ---
        self._cache_embeddings = Table(
            "cache_embeddings",
            self._meta,
            Column("cache_id", String(36), primary_key=True),
            Column("embedding", LargeBinary, nullable=False),
        )

        self._meta.create_all(self._engine)

        # Schema upgrades for existing databases. create_all() creates missing
        # TABLES and never alters an existing one. MySQL 8.4.11 rejects
        # ADD COLUMN IF NOT EXISTS with a syntax error (1064) and raises 1060
        # "Duplicate column name" on a repeat, so idempotency is try/except
        # here rather than native as on Postgres. Both verified by execution.
        with self._engine.connect() as conn:
            for stmt in [
                "ALTER TABLE answer_cache ADD COLUMN conversation_id VARCHAR(64) NULL",
            ]:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:  # noqa: S110 — column already exists (MySQL 1060)
                    conn.rollback()

        # Add FULLTEXT index for search + additional indexes
        with self._engine.connect() as conn:
            for stmt in [
                "ALTER TABLE sections ADD FULLTEXT INDEX ft_text (text_content)",
                "CREATE INDEX idx_sections_document ON sections(document_id)",
                "CREATE INDEX idx_sections_current ON sections(is_current)",
                "CREATE INDEX idx_chunks_section ON chunks(section_id)",
                "CREATE INDEX idx_cache_key ON answer_cache(answer_key)",
                "CREATE INDEX idx_cache_valid ON answer_cache(is_valid)",
                "CREATE INDEX idx_cache_namespace ON answer_cache(namespace_id)",
                "CREATE INDEX idx_blocks_section ON content_blocks(section_id)",
                "CREATE INDEX idx_blocks_section_compression ON content_blocks(section_id, compression)",
                "CREATE INDEX idx_tags_section ON section_tags(section_id)",
                "CREATE INDEX idx_tags_key_value ON section_tags(tag_key, tag_value)",
                "CREATE INDEX idx_rels_a ON section_relationships(section_a_id)",
                "CREATE INDEX idx_rels_b ON section_relationships(section_b_id)",
            ]:
                try:
                    conn.execute(text(stmt))
                except Exception:  # noqa: S110 — index-already-exists check, safe to ignore
                    pass
            conn.commit()

    @contextmanager
    def session(self) -> Generator[Any, None, None]:
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # --- Documents ---

    def store_document(self, session: Any, doc: DocumentRecord) -> None:
        session.execute(
            self._documents.insert().values(
                id=doc.id,
                document_type=doc.document_type,
                source=doc.source,
                title=doc.title,
                jurisdiction=doc.jurisdiction,
                source_format=doc.source_format,
                metadata=doc.metadata,
                tags=doc.tags,
            )
        )

    # --- Sections ---

    def store_section(self, session: Any, section: SectionRecord) -> None:
        session.execute(
            self._sections.insert().values(
                id=section.id,
                document_id=section.document_id,
                text_content=section.text_content,
                version_hash=section.version_hash,
                citation=section.citation,
                section_number=section.section_number,
                section_title=section.section_title,
                hierarchy_path=section.hierarchy_path,
                is_current=section.is_current,
                metadata=section.metadata,
                tags=section.tags,
            )
        )

    def get_section(self, session: Any, section_id: str) -> SectionRecord | None:
        row = session.execute(
            select(self._sections).where(
                self._sections.c.id == section_id,
                self._sections.c.is_current.is_(True),
            )
        ).fetchone()
        return self._row_to_section(row) if row else None

    def get_section_by_citation(self, session: Any, citation: str) -> SectionRecord | None:
        row = session.execute(
            select(self._sections).where(
                self._sections.c.citation == citation,
                self._sections.c.is_current.is_(True),
            )
        ).fetchone()
        return self._row_to_section(row) if row else None

    def get_section_version_hashes(self, session: Any, section_ids: list[str]) -> dict[str, str]:
        if not section_ids:
            return {}
        rows = session.execute(
            select(self._sections.c.id, self._sections.c.version_hash).where(self._sections.c.id.in_(section_ids))
        ).fetchall()
        return {r.id: r.version_hash for r in rows}

    def get_section_version_hash(self, session: Any, section_id: str) -> str | None:
        row = session.execute(
            select(self._sections.c.version_hash).where(
                self._sections.c.id == section_id,
                self._sections.c.is_current.is_(True),
            )
        ).fetchone()
        return row[0] if row else None

    # --- Chunks ---

    def store_chunk(self, session: Any, chunk: ChunkRecord) -> None:
        session.execute(
            self._chunks.insert().values(
                id=chunk.id,
                section_id=chunk.section_id,
                chunk_index=chunk.chunk_index,
                text_content=chunk.text_content,
                document_type=chunk.document_type,
                jurisdiction=chunk.jurisdiction,
                char_offset=chunk.char_offset,
            )
        )

    # --- Search ---

    def hybrid_search(
        self,
        session: Any,
        query: str,
        embedding: list[float] | None = None,
        limit: int = 10,
        jurisdiction: str | None = None,
        document_type: str | None = None,
    ) -> list[SearchResult]:
        if embedding is not None:
            # TODO: MySQL does not support native vector search.
            # Consider using a dedicated vector store adapter alongside MySQL.
            logger.warning(
                "MySQL hybrid_search: embedding parameter provided but vector "
                "search is not supported in MySQL. Falling back to text-only search."
            )

        sql = text("""
            SELECT id as section_id, citation, section_title, text_content, version_hash,
                MATCH(text_content) AGAINST(:query IN NATURAL LANGUAGE MODE) as score
            FROM sections WHERE is_current = 1
                AND MATCH(text_content) AGAINST(:query IN NATURAL LANGUAGE MODE)
            ORDER BY score DESC LIMIT :limit
        """)
        rows = session.execute(sql, {"query": query, "limit": limit}).fetchall()
        return [
            SearchResult(
                section_id=row.section_id,
                citation=row.citation or "",
                title=row.section_title or "",
                snippet=row.text_content[:300],
                score=float(row.score),
                version_hash=row.version_hash or "",
            )
            for row in rows
        ]

    # --- Answer Cache ---

    def cache_lookup(self, session: Any, answer_key: str) -> AnswerCacheRecord | None:
        row = session.execute(
            select(self._cache).where(
                self._cache.c.answer_key == answer_key,
                self._cache.c.is_valid.is_(True),
            )
        ).fetchone()
        return self._row_to_cache(row) if row else None

    def cache_store(self, session: Any, record: AnswerCacheRecord) -> None:
        # DELETE any existing row with the same answer_key first (handles
        # re-caching after invalidation where the old row has is_valid=false).
        # Must delete cache_embeddings first (FK-like constraint).
        old_row = session.execute(
            select(self._cache.c.id).where(self._cache.c.answer_key == record.answer_key)
        ).fetchone()
        if old_row:
            session.execute(delete(self._cache_embeddings).where(self._cache_embeddings.c.cache_id == old_row[0]))
            session.execute(delete(self._cache).where(self._cache.c.id == old_row[0]))
        session.execute(
            self._cache.insert().values(
                id=record.id,
                answer_key=record.answer_key,
                question_raw=record.question_raw,
                question_normalized=record.question_normalized,
                filters=record.filters,
                answer_text=record.answer_text,
                source_sections=record.source_sections,
                model_used=record.model_used,
                generation_ms=record.generation_ms,
                confidence=record.confidence,
                namespace_id=record.namespace_id,
                conversation_id=record.conversation_id,
                max_age_seconds=record.max_age_seconds,
                last_served_at=record.last_served_at,
                estimated_cost=record.estimated_cost,
            )
        )

    def cache_invalidate(self, session: Any, answer_id: str, reason: str) -> None:
        session.execute(
            update(self._cache)
            .where(self._cache.c.id == answer_id)
            .values(
                is_valid=False,
                invalidated_at=datetime.now(timezone.utc),
                invalidation_reason=reason,
            )
        )

    def cache_clear_all(self, session: Any, reason: str = "Manual clear") -> int:
        result = session.execute(
            update(self._cache)
            .where(self._cache.c.is_valid.is_(True))
            .values(
                is_valid=False,
                invalidated_at=datetime.now(timezone.utc),
                invalidation_reason=reason,
            )
        )
        return int(result.rowcount or 0)

    def cache_invalidate_by_section(self, session: Any, section_id: str) -> int:
        # MySQL doesn't have JSONB containment — scan and filter in Python
        rows = session.execute(
            select(self._cache.c.id, self._cache.c.source_sections).where(
                self._cache.c.is_valid.is_(True),
            )
        ).fetchall()
        count = 0
        for row in rows:
            sources = row.source_sections or []
            if any(s.get("section_id") == section_id for s in sources):
                self.cache_invalidate(session, row.id, f"Source section {section_id} changed")
                count += 1
        return count

    def cache_increment_serve(self, session: Any, answer_id: str) -> None:
        session.execute(
            update(self._cache)
            .where(self._cache.c.id == answer_id)
            .values(
                serve_count=self._cache.c.serve_count + 1,
                # LRU eviction sorts on this; SQLite set it and this backend did not.
                last_served_at=datetime.now(timezone.utc),
            )
        )

    def cache_stats(self, session: Any) -> dict:
        total = session.execute(select(func.count()).select_from(self._cache)).scalar() or 0
        valid = (
            session.execute(
                select(func.count()).select_from(self._cache).where(self._cache.c.is_valid.is_(True))
            ).scalar()
            or 0
        )
        serves = session.execute(select(func.sum(self._cache.c.serve_count)).select_from(self._cache)).scalar() or 0
        avg_ms = session.execute(select(func.avg(self._cache.c.generation_ms)).select_from(self._cache)).scalar() or 0

        total_saved_ms = (
            session.execute(
                text("SELECT COALESCE(SUM(generation_ms * serve_count), 0) FROM answer_cache WHERE is_valid = 1")
            ).scalar()
            or 0
        )

        total_requests = serves + total
        hit_rate = round((serves / total_requests * 100), 1) if total_requests > 0 else 0.0

        return {
            "total_entries": total,
            "valid_entries": valid,
            "invalidated_entries": total - valid,
            "total_serves": serves,
            "hit_rate": hit_rate,
            "total_compute_saved_ms": total_saved_ms,
            "total_compute_saved_s": round(total_saved_ms / 1000, 2),
            "avg_generation_ms": round(avg_ms or 0, 1),
        }

    def cache_fuzzy_match(
        self,
        session: Any,
        normalized_query: str,
        filters: dict,
        threshold: float = 0.85,
        max_results: int = 5,
    ) -> list[AnswerCacheRecord]:
        # MySQL lacks pg_trgm — pre-filter with LIKE, then score in Python using
        # the same cache_engine.fuzzy_similarity the SQLite adapter uses.
        #
        # The filter matches token *prefixes*, not whole tokens: '%pollicy%'
        # never matches stored 'policy', so a whole-token filter would never
        # retrieve the row a typo is meant to find, and scoring would never run.
        from bitmod.cache_engine import fuzzy_prefilter_terms, fuzzy_similarity

        if not normalized_query.split():
            return []

        prefixes = fuzzy_prefilter_terms(normalized_query)
        if not prefixes:
            return []

        if len(prefixes) >= 2:
            rows = session.execute(
                select(self._cache)
                .where(
                    self._cache.c.is_valid.is_(True),
                    self._cache.c.question_normalized.like(f"%{prefixes[0]}%"),
                    self._cache.c.question_normalized.like(f"%{prefixes[1]}%"),
                )
                .limit(200)
            ).fetchall()
            if not rows:
                rows = session.execute(
                    select(self._cache)
                    .where(
                        self._cache.c.is_valid.is_(True),
                        self._cache.c.question_normalized.like(f"%{prefixes[0]}%"),
                    )
                    .limit(200)
                ).fetchall()
        else:
            rows = session.execute(
                select(self._cache)
                .where(
                    self._cache.c.is_valid.is_(True),
                    self._cache.c.question_normalized.like(f"%{prefixes[0]}%"),
                )
                .limit(200)
            ).fetchall()

        scored: list[tuple[float, AnswerCacheRecord]] = []
        for row in rows:
            if not row.question_normalized:
                continue
            similarity = fuzzy_similarity(normalized_query, row.question_normalized)
            if similarity >= threshold:
                scored.append((similarity, self._row_to_cache(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [record for _, record in scored[:max_results]]

    # --- Content Blocks ---

    def store_block(self, session: Any, block: ContentBlock) -> None:
        session.execute(
            self._blocks.insert().values(
                id=block.id,
                section_id=block.section_id,
                compression=block.compression,
                content=block.content,
                version_hash=block.version_hash,
                token_count=block.token_count,
            )
        )

    def get_blocks(
        self,
        session: Any,
        section_id: str,
        compression: str | None = None,
    ) -> list[ContentBlock]:
        q = select(self._blocks).where(self._blocks.c.section_id == section_id)
        if compression:
            q = q.where(self._blocks.c.compression == compression)
        rows = session.execute(q).fetchall()
        return [self._row_to_block(r) for r in rows]

    def delete_chunks_by_section(self, session: Any, section_id: str) -> int:
        result = session.execute(delete(self._chunks).where(self._chunks.c.section_id == section_id))
        return result.rowcount  # type: ignore[no-any-return]

    def invalidate_blocks(self, session: Any, section_id: str) -> int:
        result = session.execute(delete(self._blocks).where(self._blocks.c.section_id == section_id))
        return result.rowcount  # type: ignore[no-any-return]

    # --- Section Tags ---

    def store_tag(self, session: Any, tag: SectionTag) -> None:
        # MySQL upsert: INSERT ... ON DUPLICATE KEY UPDATE
        session.execute(
            text("""
            INSERT INTO section_tags (section_id, tag_key, tag_value, confidence, source)
            VALUES (:sid, :key, :val, :conf, :src)
            ON DUPLICATE KEY UPDATE confidence = :conf, source = :src
        """),
            {
                "sid": tag.section_id,
                "key": tag.tag_key,
                "val": tag.tag_value,
                "conf": tag.confidence,
                "src": tag.source,
            },
        )

    def get_tags(self, session: Any, section_id: str) -> list[SectionTag]:
        rows = session.execute(select(self._tags).where(self._tags.c.section_id == section_id)).fetchall()
        return [
            SectionTag(
                section_id=r.section_id,
                tag_key=r.tag_key,
                tag_value=r.tag_value,
                confidence=r.confidence,
                source=r.source,
            )
            for r in rows
        ]

    def search_by_tag(
        self,
        session: Any,
        tag_key: str,
        tag_value: str,
        limit: int = 20,
    ) -> list[SectionRecord]:
        sql = text("""
            SELECT s.* FROM sections s
            INNER JOIN section_tags t ON s.id = t.section_id
            WHERE t.tag_key = :key AND t.tag_value = :val AND s.is_current = 1
            LIMIT :limit
        """)
        rows = session.execute(sql, {"key": tag_key, "val": tag_value, "limit": limit}).fetchall()
        return [self._row_to_section(r) for r in rows]

    # --- Section Relationships ---

    def store_relationship(self, session: Any, rel: SectionRelationship) -> None:
        # MySQL upsert: INSERT ... ON DUPLICATE KEY UPDATE
        session.execute(
            text("""
            INSERT INTO section_relationships
                (section_a_id, section_b_id, relationship, strength, source, hit_count)
            VALUES (:a, :b, :rel, :str, :src, :hc)
            ON DUPLICATE KEY UPDATE strength = :str, source = :src, hit_count = :hc
        """),
            {
                "a": rel.section_a_id,
                "b": rel.section_b_id,
                "rel": rel.relationship,
                "str": rel.strength,
                "src": rel.source,
                "hc": rel.hit_count,
            },
        )

    def get_relationships(self, session: Any, section_id: str) -> list[SectionRelationship]:
        sql = text("""
            SELECT * FROM section_relationships
            WHERE section_a_id = :sid OR section_b_id = :sid
        """)
        rows = session.execute(sql, {"sid": section_id}).fetchall()
        return [
            SectionRelationship(
                section_a_id=r.section_a_id,
                section_b_id=r.section_b_id,
                relationship=r.relationship,
                strength=r.strength,
                source=r.source,
                hit_count=r.hit_count,
            )
            for r in rows
        ]

    def increment_relationship(
        self,
        session: Any,
        section_a_id: str,
        section_b_id: str,
        relationship: str,
    ) -> None:
        # MySQL upsert: INSERT ... ON DUPLICATE KEY UPDATE
        session.execute(
            text("""
            INSERT INTO section_relationships
                (section_a_id, section_b_id, relationship, strength, source, hit_count)
            VALUES (:a, :b, :rel, 1.0, 'co_retrieval', 1)
            ON DUPLICATE KEY UPDATE hit_count = hit_count + 1
        """),
            {"a": section_a_id, "b": section_b_id, "rel": relationship},
        )

    # --- Semantic Cache (embedding-based, stored as BLOB) ---

    def cache_store_embedding(self, session: Any, cache_id: str, embedding: list[float]) -> None:
        """Store a query embedding alongside a cache entry."""
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        # MySQL upsert: INSERT ... ON DUPLICATE KEY UPDATE
        session.execute(
            text("""
            INSERT INTO cache_embeddings (cache_id, embedding)
            VALUES (:cid, :emb)
            ON DUPLICATE KEY UPDATE embedding = :emb
        """),
            {"cid": cache_id, "emb": blob},
        )

    def cache_get_embeddings(
        self, session: Any, limit: int = 2000, namespace_id: str | None = None
    ) -> list[tuple[str, list[float]]]:
        """Return valid cache embeddings as (cache_id, embedding) pairs.

        Args:
            limit: Maximum number of embeddings to return. Defaults to 2000.
            namespace_id: If set, only return embeddings for this namespace.
        """
        limit = min(max(1, limit), 5000)
        if namespace_id:
            sql = text("""
                SELECT ce.cache_id, ce.embedding FROM cache_embeddings ce
                INNER JOIN answer_cache ac ON ce.cache_id = ac.id
                WHERE ac.is_valid = 1 AND ac.namespace_id = :ns
                ORDER BY ac.created_at DESC
                LIMIT :lim
            """)
            rows = session.execute(sql, {"ns": namespace_id, "lim": limit}).fetchall()
        else:
            sql = text("""
                SELECT ce.cache_id, ce.embedding FROM cache_embeddings ce
                INNER JOIN answer_cache ac ON ce.cache_id = ac.id
                WHERE ac.is_valid = 1
                ORDER BY ac.created_at DESC
                LIMIT :lim
            """)
            rows = session.execute(sql, {"lim": limit}).fetchall()
        results = []
        for row in rows:
            blob = row.embedding
            n = len(blob) // 4
            emb = list(struct.unpack(f"{n}f", blob))
            results.append((row.cache_id, emb))
        return results

    def cache_lookup_by_id(self, session: Any, cache_id: str) -> AnswerCacheRecord | None:
        """Look up a cached answer by its record ID."""
        row = session.execute(
            select(self._cache).where(
                self._cache.c.id == cache_id,
                self._cache.c.is_valid.is_(True),
            )
        ).fetchone()
        return self._row_to_cache(row) if row else None

    # --- Admin dashboard stats ---

    def recent_cached_queries(self, session: Any, limit: int = 20) -> list[dict]:
        """Return the most recent cached queries with full detail."""
        sql = text("""
            SELECT question_raw, generation_ms, serve_count, is_valid,
                   model_used, created_at, confidence, answer_key
            FROM answer_cache ORDER BY created_at DESC LIMIT :limit
        """)
        rows = session.execute(sql, {"limit": limit}).fetchall()
        return [
            {
                "question": row.question_raw,
                "generation_ms": row.generation_ms,
                "serve_count": row.serve_count,
                "is_valid": bool(row.is_valid),
                "model_used": row.model_used,
                "created_at": str(row.created_at) if row.created_at else None,
                "confidence": row.confidence,
                "answer_key": row.answer_key,
            }
            for row in rows
        ]

    def cache_model_comparison(self, session: Any) -> list[dict]:
        """Return cost comparison data for cached queries with serves > 0."""
        cached_serve_ms = 0.5
        sql = text("""
            SELECT question_raw, generation_ms, serve_count, model_used
            FROM answer_cache
            WHERE serve_count > 0 AND is_valid = 1
            ORDER BY serve_count DESC LIMIT 50
        """)
        rows = session.execute(sql).fetchall()
        return [
            {
                "query": row.question_raw,
                "first_gen_ms": row.generation_ms,
                "cached_serve_ms": cached_serve_ms,
                "serves": row.serve_count,
                "model_used": row.model_used,
                "total_without_cache_ms": row.generation_ms * (1 + row.serve_count),
                "total_with_cache_ms": row.generation_ms + (cached_serve_ms * row.serve_count),
                "savings_ms": row.generation_ms * row.serve_count - (cached_serve_ms * row.serve_count),
            }
            for row in rows
        ]

    def document_stats(self, session: Any) -> dict:
        """Return document-level statistics and listing."""
        sql = text("""
            SELECT d.id, d.title, d.source_format, d.created_at, d.document_type,
                   d.source, d.jurisdiction,
                   COUNT(DISTINCT s.id) AS section_count,
                   COUNT(DISTINCT c.id) AS chunk_count
            FROM documents d
            LEFT JOIN sections s ON s.document_id = d.id AND s.is_current = 1
            LEFT JOIN chunks c ON c.section_id = s.id
            GROUP BY d.id, d.title, d.source_format, d.created_at,
                     d.document_type, d.source, d.jurisdiction
            ORDER BY d.created_at DESC
        """)
        rows = session.execute(sql).fetchall()
        documents = [
            {
                "id": row.id,
                "title": row.title,
                "source_format": row.source_format,
                "document_type": row.document_type,
                "source": row.source,
                "jurisdiction": row.jurisdiction,
                "section_count": row.section_count,
                "chunk_count": row.chunk_count,
                "created_at": str(row.created_at) if row.created_at else None,
            }
            for row in rows
        ]
        total_sections = sum(d["section_count"] for d in documents)
        total_chunks = sum(d["chunk_count"] for d in documents)
        return {
            "documents": documents,
            "totals": {
                "document_count": len(documents),
                "total_sections": total_sections,
                "total_chunks": total_chunks,
            },
        }

    # --- Re-ingestion support ---

    def get_sections_for_document(self, session: Any, document_id: str) -> list[SectionRecord]:
        """Get all current sections for a document."""
        rows = session.execute(
            select(self._sections)
            .where(
                self._sections.c.document_id == document_id,
                self._sections.c.is_current.is_(True),
            )
            .order_by(self._sections.c.section_number)
        ).fetchall()
        return [self._row_to_section(r) for r in rows]

    def find_document_by_title_and_source(
        self,
        session: Any,
        title: str,
        source: str,
    ) -> DocumentRecord | None:
        """Find an existing document by title + source."""
        row = session.execute(
            select(self._documents)
            .where(
                self._documents.c.title == title,
                self._documents.c.source == source,
            )
            .limit(1)
        ).fetchone()
        if not row:
            return None
        return DocumentRecord(
            id=row.id,
            document_type=row.document_type,
            source=row.source,
            title=row.title,
            jurisdiction=row.jurisdiction,
            source_format=row.source_format,
            metadata=row.metadata or {},
            tags=row.tags,
        )

    def update_section_content(
        self,
        session: Any,
        section_id: str,
        text_content: str,
        version_hash: str,
    ) -> None:
        """Update a section's content and version hash."""
        session.execute(
            update(self._sections)
            .where(self._sections.c.id == section_id)
            .values(
                text_content=text_content,
                version_hash=version_hash,
            )
        )

    def mark_section_not_current(self, session: Any, section_id: str) -> None:
        """Mark a section as no longer current."""
        session.execute(
            update(self._sections)
            .where(self._sections.c.id == section_id)
            .values(
                is_current=False,
            )
        )

    # --- Row converters ---

    def _row_to_section(self, row) -> SectionRecord:
        return SectionRecord(
            id=row.id,
            document_id=row.document_id,
            text_content=row.text_content,
            version_hash=row.version_hash,
            citation=row.citation,
            section_number=row.section_number,
            section_title=row.section_title,
            hierarchy_path=row.hierarchy_path,
            is_current=row.is_current,
            metadata=row.metadata or {},
            tags=row.tags,
        )

    def _row_to_cache(self, row) -> AnswerCacheRecord:
        return AnswerCacheRecord(
            id=row.id,
            answer_key=row.answer_key,
            question_raw=row.question_raw,
            question_normalized=row.question_normalized,
            filters=row.filters or {},
            answer_text=row.answer_text,
            source_sections=row.source_sections or [],
            model_used=row.model_used,
            generation_ms=row.generation_ms,
            confidence=row.confidence,
            is_valid=row.is_valid,
            serve_count=row.serve_count,
            namespace_id=row.namespace_id,
            conversation_id=row.conversation_id,
            max_age_seconds=row.max_age_seconds,
            last_served_at=row.last_served_at,
            estimated_cost=row.estimated_cost or 0.0,
        )

    def _row_to_block(self, row) -> ContentBlock:
        return ContentBlock(
            id=row.id,
            section_id=row.section_id,
            compression=row.compression,
            content=row.content,
            version_hash=row.version_hash,
            token_count=row.token_count,
        )

    # --- Audit Events ---

    def store_audit_event(self, session: Any, record: dict) -> None:
        session.execute(
            text("""
            INSERT INTO audit_events
                (id, timestamp, event_type, actor, source_ip, resource, action, outcome, details_json, correlation_id)
            VALUES
                (:id, :timestamp, :event_type, :actor, :source_ip,
                 :resource, :action, :outcome, :details_json, :correlation_id)
        """),
            {
                "id": record["id"],
                "timestamp": record["timestamp"],
                "event_type": record["event_type"],
                "actor": record.get("actor"),
                "source_ip": record.get("source_ip"),
                "resource": record.get("resource"),
                "action": record["action"],
                "outcome": record["outcome"],
                "details_json": record.get("details_json"),
                "correlation_id": record.get("correlation_id"),
            },
        )

    # --- API Key Management ---

    def store_api_key(self, session: Any, record: dict) -> None:
        session.execute(
            text("""
            INSERT INTO api_keys
                (id, key_hash, key_preview, name, scopes, owner, is_active, created_at, expires_at, email)
            VALUES
                (:id, :key_hash, :key_preview, :name, :scopes, :owner, :is_active, :created_at, :expires_at, :email)
        """),
            {
                "id": record["id"],
                "key_hash": record["key_hash"],
                "key_preview": record["key_preview"],
                "name": record["name"],
                "scopes": record["scopes"],
                "owner": record["owner"],
                "is_active": 1 if record["is_active"] else 0,
                "created_at": record["created_at"],
                "expires_at": record.get("expires_at"),
                "email": record.get("email"),
            },
        )

    def lookup_api_key(self, session: Any, key_hash: str) -> dict | None:
        row = session.execute(text("SELECT * FROM api_keys WHERE key_hash = :kh"), {"kh": key_hash}).fetchone()
        if row is None:
            return None
        return {
            "id": row.id,
            "key_hash": row.key_hash,
            "key_preview": row.key_preview,
            "name": row.name,
            "scopes": row.scopes,
            "owner": row.owner,
            "is_active": bool(row.is_active),
            "created_at": row.created_at,
            "last_used_at": row.last_used_at,
            "expires_at": row.expires_at,
            "email": getattr(row, "email", None),
        }

    def list_api_keys(self, session: Any, owner: str | None = None) -> list[dict]:
        if owner:
            rows = session.execute(
                text("SELECT * FROM api_keys WHERE owner = :owner ORDER BY created_at DESC"),
                {"owner": owner},
            ).fetchall()
        else:
            rows = session.execute(text("SELECT * FROM api_keys ORDER BY created_at DESC")).fetchall()
        return [
            {
                "id": r.id,
                "key_hash": r.key_hash,
                "key_preview": r.key_preview,
                "name": r.name,
                "scopes": r.scopes,
                "owner": r.owner,
                "is_active": bool(r.is_active),
                "created_at": r.created_at,
                "last_used_at": r.last_used_at,
                "expires_at": r.expires_at,
                "email": getattr(r, "email", None),
            }
            for r in rows
        ]

    def revoke_api_key(self, session: Any, key_id: str) -> bool:
        result = session.execute(
            text("UPDATE api_keys SET is_active = 0 WHERE id = :kid AND is_active = 1"),
            {"kid": key_id},
        )
        return result.rowcount > 0  # type: ignore[no-any-return]

    def touch_api_key(self, session: Any, key_id: str) -> None:
        session.execute(
            text("UPDATE api_keys SET last_used_at = NOW() WHERE id = :kid"),
            {"kid": key_id},
        )
