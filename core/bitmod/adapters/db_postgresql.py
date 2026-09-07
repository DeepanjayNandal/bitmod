"""PostgreSQL database backend — SQLAlchemy + pgvector + pg_trgm.

Production-grade backend with connection pooling, native JSONB operations,
trigram fuzzy search, and pgvector cosine similarity.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from bitmod.interfaces.database import (
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
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import (
        JSON,
        Boolean,
        Column,
        DateTime,
        Float,
        Integer,
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
    from sqlalchemy.orm import Session, sessionmaker
except ImportError as e:
    raise ImportError(
        "PostgreSQL backend requires: pip install bitmod[postgresql]  (sqlalchemy psycopg2-binary pgvector)"
    ) from e


class PostgreSQLBackend(DatabaseBackend):
    def __init__(self, url: str, pool_size: int = 5, max_overflow: int = 10):
        self._url = url
        self._engine = create_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
        self._Session = sessionmaker(bind=self._engine)
        self._meta = MetaData()
        self._tables_created = False

    def initialize(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.commit()

        # --- Core tables ---
        self._documents = Table(
            "documents",
            self._meta,
            Column("id", String, primary_key=True),
            Column("document_type", String, default=""),
            Column("source", String, default=""),
            Column("title", String, default=""),
            Column("jurisdiction", String, nullable=True),
            Column("source_format", String, default=""),
            Column("metadata", JSON, default={}),
            Column("tags", JSON, nullable=True),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )
        self._sections = Table(
            "sections",
            self._meta,
            Column("id", String, primary_key=True),
            Column("document_id", String, nullable=False),
            Column("text_content", Text, default=""),
            Column("version_hash", String, default=""),
            Column("citation", String, nullable=True),
            Column("section_number", String, nullable=True),
            Column("section_title", String, nullable=True),
            Column("hierarchy_path", String, nullable=True),
            Column("is_current", Boolean, default=True),
            Column("metadata", JSON, default={}),
            Column("tags", JSON, nullable=True),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )
        self._chunks = Table(
            "chunks",
            self._meta,
            Column("id", String, primary_key=True),
            Column("section_id", String, nullable=False),
            Column("chunk_index", Integer, default=0),
            Column("text_content", Text, default=""),
            Column("embedding", Vector(384), nullable=True),
            Column("document_type", String, default=""),
            Column("jurisdiction", String, nullable=True),
            Column("char_offset", Integer, default=0),
        )

        # --- Answer cache ---
        self._cache = Table(
            "answer_cache",
            self._meta,
            Column("id", String, primary_key=True),
            Column("answer_key", String, unique=True, nullable=False),
            Column("question_raw", Text, default=""),
            Column("question_normalized", Text, default=""),
            Column("filters", JSON, default={}),
            Column("answer_text", Text, default=""),
            Column("source_sections", JSON, default=[]),
            Column("model_used", String, default=""),
            Column("generation_ms", Integer, default=0),
            Column("confidence", Float, nullable=True),
            Column("is_valid", Boolean, default=True),
            Column("serve_count", Integer, default=0),
            Column("invalidated_at", DateTime, nullable=True),
            Column("invalidation_reason", Text, nullable=True),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )

        # --- Content blocks (multi-compression) ---
        self._blocks = Table(
            "content_blocks",
            self._meta,
            Column("id", String, primary_key=True),
            Column("section_id", String, nullable=False),
            Column("compression", String, default="full"),
            Column("content", Text, default=""),
            Column("version_hash", String, default=""),
            Column("token_count", Integer, default=0),
            Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
        )

        # --- Section tags ---
        self._tags = Table(
            "section_tags",
            self._meta,
            Column("section_id", String, nullable=False),
            Column("tag_key", String, nullable=False),
            Column("tag_value", String, nullable=False),
            Column("confidence", Float, default=1.0),
            Column("source", String, default="rule"),
            UniqueConstraint("section_id", "tag_key", "tag_value", name="uq_section_tag"),
        )

        # --- Section relationships ---
        self._relationships = Table(
            "section_relationships",
            self._meta,
            Column("section_a_id", String, nullable=False),
            Column("section_b_id", String, nullable=False),
            Column("relationship", String, nullable=False),
            Column("strength", Float, default=1.0),
            Column("source", String, default="co_retrieval"),
            Column("hit_count", Integer, default=1),
            UniqueConstraint("section_a_id", "section_b_id", "relationship", name="uq_section_rel"),
        )

        # --- Semantic cache embeddings ---
        self._cache_embeddings = Table(
            "cache_embeddings",
            self._meta,
            Column("cache_id", String, primary_key=True),
            Column("embedding", Vector(384), nullable=False),
        )

        self._meta.create_all(self._engine)

        # Create indexes that SQLAlchemy Table doesn't handle well
        with self._engine.connect() as conn:
            for stmt in [
                "CREATE INDEX IF NOT EXISTS idx_sections_document ON sections(document_id)",
                "CREATE INDEX IF NOT EXISTS idx_sections_current ON sections(is_current)",
                "CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_id)",
                "CREATE INDEX IF NOT EXISTS idx_cache_key ON answer_cache(answer_key)",
                "CREATE INDEX IF NOT EXISTS idx_cache_valid ON answer_cache(is_valid)",
                "CREATE INDEX IF NOT EXISTS idx_blocks_section ON content_blocks(section_id)",
                "CREATE INDEX IF NOT EXISTS idx_blocks_section_compression ON content_blocks(section_id, compression)",
                "CREATE INDEX IF NOT EXISTS idx_tags_section ON section_tags(section_id)",
                "CREATE INDEX IF NOT EXISTS idx_tags_key_value ON section_tags(tag_key, tag_value)",
                "CREATE INDEX IF NOT EXISTS idx_rels_a ON section_relationships(section_a_id)",
                "CREATE INDEX IF NOT EXISTS idx_rels_b ON section_relationships(section_b_id)",
                # Trigram index for fuzzy search
                "CREATE INDEX IF NOT EXISTS idx_cache_normalized_trgm ON answer_cache USING gin (question_normalized gin_trgm_ops)",  # noqa: E501
                # GIN index for JSONB containment queries on source_sections
                "CREATE INDEX IF NOT EXISTS idx_cache_sources_gin ON answer_cache USING gin (source_sections jsonb_path_ops)",  # noqa: E501
            ]:
                conn.execute(text(stmt))
            conn.commit()

        self._tables_created = True

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
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
                embedding=chunk.embedding,
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
        if embedding:
            # Build optional jurisdiction/doc_type filters
            extra_where = ""
            params: dict = {"query": query, "embedding": str(embedding), "limit": limit}
            if jurisdiction:
                extra_where += " AND s.jurisdiction = :jurisdiction"
                params["jurisdiction"] = jurisdiction
            if document_type:
                extra_where += " AND s.document_type = :document_type"
                params["document_type"] = document_type

            sql = text(f"""  # nosemgrep: avoid-sqlalchemy-text
                WITH text_scores AS (
                    SELECT s.id as section_id, s.citation,
                        s.section_title, s.text_content,
                        ts_rank(to_tsvector('english', s.text_content),
                            plainto_tsquery('english', :query)) as text_score
                    FROM sections s
                    WHERE s.is_current = true
                        AND to_tsvector('english', s.text_content) @@ plainto_tsquery('english', :query)
                        {extra_where}
                ),
                vector_scores AS (
                    SELECT c.section_id,
                        1 - (c.embedding <=> :embedding::vector) as vec_score
                    FROM chunks c
                    WHERE c.embedding IS NOT NULL
                )
                SELECT ts.section_id, ts.citation, ts.section_title, ts.text_content,
                    (COALESCE(ts.text_score, 0) * 0.4 + COALESCE(vs.vec_score, 0) * 0.6) as combined_score
                FROM text_scores ts
                LEFT JOIN vector_scores vs ON ts.section_id = vs.section_id
                ORDER BY combined_score DESC
                LIMIT :limit
            """)  # noqa: S608 — values parameterized; extra_where from controlled allowlist  # nosemgrep: avoid-sqlalchemy-text
            rows = session.execute(sql, params).fetchall()
        else:
            extra_where = ""
            params = {"query": query, "limit": limit}
            if jurisdiction:
                extra_where += " AND s.jurisdiction = :jurisdiction"
                params["jurisdiction"] = jurisdiction

            sql = text(f"""  # nosemgrep: avoid-sqlalchemy-text
                SELECT s.id as section_id, s.citation,
                    s.section_title, s.text_content,
                    ts_rank(to_tsvector('english', s.text_content),
                        plainto_tsquery('english', :query)) as combined_score
                FROM sections s
                WHERE s.is_current = true
                    AND to_tsvector('english', s.text_content) @@ plainto_tsquery('english', :query)
                    {extra_where}
                ORDER BY combined_score DESC
                LIMIT :limit
            """)  # noqa: S608 — values parameterized; extra_where from controlled allowlist  # nosemgrep: avoid-sqlalchemy-text
            rows = session.execute(sql, params).fetchall()

        return [
            SearchResult(
                section_id=row.section_id,
                citation=row.citation or "",
                title=row.section_title or "",
                snippet=row.text_content[:300],
                score=float(row.combined_score),
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
        # Must delete cache_embeddings first (FK constraint).
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
        sql = text("""
            UPDATE answer_cache SET is_valid = false, invalidated_at = NOW(),
                invalidation_reason = :reason
            WHERE is_valid = true AND source_sections @> :filter::jsonb
            RETURNING id
        """)
        result = session.execute(
            sql,
            {
                "reason": f"Source section {section_id} changed",
                "filter": json.dumps([{"section_id": section_id}]),
            },
        )
        return len(result.fetchall())

    def cache_increment_serve(self, session: Any, answer_id: str) -> None:
        session.execute(
            update(self._cache).where(self._cache.c.id == answer_id).values(serve_count=self._cache.c.serve_count + 1)
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
                text("SELECT COALESCE(SUM(generation_ms * serve_count), 0) FROM answer_cache WHERE is_valid = true")
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
            "avg_generation_ms": round(avg_ms, 1),
        }

    def cache_fuzzy_match(
        self,
        session: Any,
        normalized_query: str,
        filters: dict,
        threshold: float = 0.85,
        max_results: int = 5,
    ) -> list[AnswerCacheRecord]:
        sql = text("""
            SELECT *, similarity(question_normalized, :query) as sim_score
            FROM answer_cache WHERE is_valid = true
                AND similarity(question_normalized, :query) > :threshold
                AND filters::text = :filters
            ORDER BY sim_score DESC LIMIT :limit
        """)
        rows = session.execute(
            sql,
            {
                "query": normalized_query,
                "threshold": threshold,
                "filters": json.dumps(filters, sort_keys=True),
                "limit": max_results,
            },
        ).fetchall()
        return [self._row_to_cache(r) for r in rows]

    # --- Admin stats (matches SQLite parity) ---

    def recent_cached_queries(self, session: Any, limit: int = 20) -> list[dict]:
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
                "is_valid": row.is_valid,
                "model_used": row.model_used,
                "created_at": str(row.created_at) if row.created_at else None,
                "confidence": row.confidence,
                "answer_key": row.answer_key,
            }
            for row in rows
        ]

    def cache_model_comparison(self, session: Any) -> list[dict]:
        cached_serve_ms = 0.5
        sql = text("""
            SELECT question_raw, generation_ms, serve_count, model_used
            FROM answer_cache
            WHERE serve_count > 0 AND is_valid = true
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
        sql = text("""
            SELECT d.id, d.title, d.source_format, d.created_at, d.document_type,
                   d.source, d.jurisdiction,
                   COUNT(DISTINCT s.id) AS section_count,
                   COUNT(DISTINCT c.id) AS chunk_count
            FROM documents d
            LEFT JOIN sections s ON s.document_id = d.id AND s.is_current = true
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
        # Upsert: delete + insert (portable across PG versions)
        session.execute(
            text("""
            INSERT INTO section_tags (section_id, tag_key, tag_value, confidence, source)
            VALUES (:sid, :key, :val, :conf, :src)
            ON CONFLICT (section_id, tag_key, tag_value)
            DO UPDATE SET confidence = :conf, source = :src
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
            WHERE t.tag_key = :key AND t.tag_value = :val AND s.is_current = true
            LIMIT :limit
        """)
        rows = session.execute(sql, {"key": tag_key, "val": tag_value, "limit": limit}).fetchall()
        return [self._row_to_section(r) for r in rows]

    # --- Section Relationships ---

    def store_relationship(self, session: Any, rel: SectionRelationship) -> None:
        session.execute(
            text("""
            INSERT INTO section_relationships (section_a_id, section_b_id, relationship, strength, source, hit_count)
            VALUES (:a, :b, :rel, :str, :src, :hc)
            ON CONFLICT (section_a_id, section_b_id, relationship)
            DO UPDATE SET strength = :str, source = :src, hit_count = :hc
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
        session.execute(
            text("""
            INSERT INTO section_relationships (section_a_id, section_b_id, relationship, strength, source, hit_count)
            VALUES (:a, :b, :rel, 1.0, 'co_retrieval', 1)
            ON CONFLICT (section_a_id, section_b_id, relationship)
            DO UPDATE SET hit_count = section_relationships.hit_count + 1
        """),
            {"a": section_a_id, "b": section_b_id, "rel": relationship},
        )

    # --- Semantic Cache (embedding-based) ---

    def cache_store_embedding(self, session: Any, cache_id: str, embedding: list[float]) -> None:
        session.execute(
            text("""
            INSERT INTO cache_embeddings (cache_id, embedding)
            VALUES (:cid, :emb::vector)
            ON CONFLICT (cache_id)
            DO UPDATE SET embedding = :emb::vector
        """),
            {"cid": cache_id, "emb": str(embedding)},
        )

    def cache_get_embeddings(
        self, session: Any, limit: int = 2000, namespace_id: str | None = None
    ) -> list[tuple[str, list[float]]]:
        limit = min(max(1, limit), 5000)
        if namespace_id:
            sql = text("""
                SELECT ce.cache_id, ce.embedding::text FROM cache_embeddings ce
                INNER JOIN answer_cache ac ON ce.cache_id = ac.id
                WHERE ac.is_valid = true AND ac.namespace_id = :ns
                ORDER BY ac.created_at DESC
                LIMIT :lim
            """)
            rows = session.execute(sql, {"ns": namespace_id, "lim": limit}).fetchall()
        else:
            sql = text("""
                SELECT ce.cache_id, ce.embedding::text FROM cache_embeddings ce
                INNER JOIN answer_cache ac ON ce.cache_id = ac.id
                WHERE ac.is_valid = true
                ORDER BY ac.created_at DESC
                LIMIT :lim
            """)
            rows = session.execute(sql, {"lim": limit}).fetchall()
        results = []
        for row in rows:
            # pgvector returns embedding as text like "[0.1,0.2,...]"
            emb_str = row[1].strip("[]")
            if emb_str:
                emb = [float(x) for x in emb_str.split(",")]
                results.append((row[0], emb))
        return results

    def cache_lookup_by_id(self, session: Any, cache_id: str) -> AnswerCacheRecord | None:
        row = session.execute(
            select(self._cache).where(
                self._cache.c.id == cache_id,
                self._cache.c.is_valid.is_(True),
            )
        ).fetchone()
        return self._row_to_cache(row) if row else None

    # --- Re-ingestion support ---

    def get_sections_for_document(self, session: Any, document_id: str) -> list[SectionRecord]:
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
        session.execute(
            update(self._sections)
            .where(self._sections.c.id == section_id)
            .values(
                text_content=text_content,
                version_hash=version_hash,
            )
        )

    def mark_section_not_current(self, session: Any, section_id: str) -> None:
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
                "is_active": record["is_active"],
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
            "is_active": row.is_active,
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
                "is_active": r.is_active,
                "created_at": r.created_at,
                "last_used_at": r.last_used_at,
                "expires_at": r.expires_at,
                "email": getattr(r, "email", None),
            }
            for r in rows
        ]

    def revoke_api_key(self, session: Any, key_id: str) -> bool:
        result = session.execute(
            text("UPDATE api_keys SET is_active = false WHERE id = :kid AND is_active = true"),
            {"kid": key_id},
        )
        return result.rowcount > 0  # type: ignore[no-any-return]

    def touch_api_key(self, session: Any, key_id: str) -> None:
        session.execute(
            text("UPDATE api_keys SET last_used_at = NOW() WHERE id = :kid"),
            {"kid": key_id},
        )
