"""SQLite database backend — built-in, zero external dependencies."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from bitmod.interfaces.database import (
    AnswerCacheRecord,
    AtomicFact,
    ChunkRecord,
    ContentBlock,
    ConversationRecord,
    CorrectionRecord,
    DatabaseBackend,
    DocumentRecord,
    ProjectChunkRecord,
    ProjectFileRecord,
    ProjectRecord,
    SearchResult,
    SectionRecord,
    SectionRelationship,
    SectionTag,
    SimilarityLink,
)


class SQLiteBackend(DatabaseBackend):
    def __init__(self, path: str = "bitmod.db"):
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._write_lock = threading.RLock()

    def initialize(self) -> None:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Bootstrap schema — must match migrations. See db/migrations/ for the source of truth.
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                document_type TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                jurisdiction TEXT,
                source_format TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                tags TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sections (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id),
                text_content TEXT NOT NULL DEFAULT '',
                version_hash TEXT NOT NULL DEFAULT '',
                citation TEXT,
                section_number TEXT,
                section_title TEXT,
                hierarchy_path TEXT,
                is_current INTEGER NOT NULL DEFAULT 1,
                metadata TEXT NOT NULL DEFAULT '{}',
                tags TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                section_id TEXT NOT NULL REFERENCES sections(id),
                chunk_index INTEGER NOT NULL DEFAULT 0,
                text_content TEXT NOT NULL DEFAULT '',
                embedding BLOB,
                document_type TEXT NOT NULL DEFAULT '',
                jurisdiction TEXT,
                char_offset INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS answer_cache (
                id TEXT PRIMARY KEY,
                answer_key TEXT NOT NULL UNIQUE,
                question_raw TEXT NOT NULL DEFAULT '',
                question_normalized TEXT NOT NULL DEFAULT '',
                filters TEXT NOT NULL DEFAULT '{}',
                answer_text TEXT NOT NULL DEFAULT '',
                source_sections TEXT NOT NULL DEFAULT '[]',
                model_used TEXT NOT NULL DEFAULT '',
                generation_ms INTEGER NOT NULL DEFAULT 0,
                confidence REAL,
                is_valid INTEGER NOT NULL DEFAULT 1,
                serve_count INTEGER NOT NULL DEFAULT 0,
                invalidated_at TEXT,
                invalidation_reason TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                namespace_id TEXT DEFAULT NULL,
                max_age_seconds INTEGER DEFAULT NULL,
                last_served_at TEXT DEFAULT NULL,
                estimated_cost REAL NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS content_blocks (
                id TEXT PRIMARY KEY,
                section_id TEXT NOT NULL REFERENCES sections(id),
                compression TEXT NOT NULL DEFAULT 'full',
                content TEXT NOT NULL DEFAULT '',
                version_hash TEXT NOT NULL DEFAULT '',
                token_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS section_tags (
                section_id TEXT NOT NULL REFERENCES sections(id),
                tag_key TEXT NOT NULL,
                tag_value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'rule',
                PRIMARY KEY (section_id, tag_key, tag_value)
            );

            CREATE TABLE IF NOT EXISTS section_relationships (
                section_a_id TEXT NOT NULL REFERENCES sections(id),
                section_b_id TEXT NOT NULL REFERENCES sections(id),
                relationship TEXT NOT NULL,
                strength REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'co_retrieval',
                hit_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (section_a_id, section_b_id, relationship)
            );

            CREATE INDEX IF NOT EXISTS idx_sections_document ON sections(document_id);
            CREATE INDEX IF NOT EXISTS idx_sections_current ON sections(is_current);
            CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_id);
            CREATE INDEX IF NOT EXISTS idx_cache_key ON answer_cache(answer_key);
            CREATE INDEX IF NOT EXISTS idx_cache_valid ON answer_cache(is_valid);

            CREATE TABLE IF NOT EXISTS cache_embeddings (
                cache_id TEXT PRIMARY KEY REFERENCES answer_cache(id),
                embedding BLOB NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL UNIQUE,
                key_preview TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                scopes TEXT NOT NULL DEFAULT '["read","write"]',
                owner TEXT NOT NULL DEFAULT 'system',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT,
                expires_at TEXT,
                email TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
            CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner);

            CREATE TABLE IF NOT EXISTS namespaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                owner_key_id TEXT NOT NULL,
                isolation TEXT NOT NULL DEFAULT 'strict',
                public_fallback INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_namespaces_owner ON namespaces(owner_key_id);
            CREATE INDEX IF NOT EXISTS idx_namespaces_name ON namespaces(name);
            CREATE INDEX IF NOT EXISTS idx_cache_namespace ON answer_cache(namespace_id);

            CREATE INDEX IF NOT EXISTS idx_blocks_section ON content_blocks(section_id);
            CREATE INDEX IF NOT EXISTS idx_blocks_section_compression ON content_blocks(section_id, compression);
            CREATE INDEX IF NOT EXISTS idx_tags_section ON section_tags(section_id);
            CREATE INDEX IF NOT EXISTS idx_tags_key_value ON section_tags(tag_key, tag_value);
            CREATE INDEX IF NOT EXISTS idx_rels_a ON section_relationships(section_a_id);
            CREATE INDEX IF NOT EXISTS idx_rels_b ON section_relationships(section_b_id);

            CREATE TABLE IF NOT EXISTS usage_tracking (
                id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                query_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cached INTEGER NOT NULL DEFAULT 0,
                cache_layer TEXT NOT NULL DEFAULT 'miss',
                latency_ms REAL NOT NULL DEFAULT 0,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                estimated_savings_usd REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_tracking(timestamp);
            CREATE INDEX IF NOT EXISTS idx_usage_tenant ON usage_tracking(tenant_id);

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                user_message TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                model_used TEXT NOT NULL DEFAULT '',
                cache_hit INTEGER NOT NULL DEFAULT 0,
                rating INTEGER,
                feedback TEXT,
                context_used TEXT NOT NULL DEFAULT '[]',
                generation_ms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);
            CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id);

            CREATE TABLE IF NOT EXISTS conversation_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                embedding BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_conv_embed_cid ON conversation_embeddings(conversation_id);

            CREATE TABLE IF NOT EXISTS corrections (
                id TEXT PRIMARY KEY,
                conversation_id TEXT REFERENCES conversations(id),
                project_id TEXT,
                original_question TEXT NOT NULL,
                original_answer TEXT NOT NULL DEFAULT '',
                corrected_answer TEXT NOT NULL,
                correction_type TEXT NOT NULL DEFAULT 'factual',
                is_applied INTEGER NOT NULL DEFAULT 0,
                embedding BLOB,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_corrections_conv ON corrections(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_corrections_project ON corrections(project_id);

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT '',
                framework TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                last_scanned_at TEXT,
                file_count INTEGER NOT NULL DEFAULT 0,
                total_chunks INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_projects_active ON projects(is_active);
            CREATE INDEX IF NOT EXISTS idx_projects_root ON projects(root_path);

            CREATE TABLE IF NOT EXISTS project_files (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL,
                file_hash TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                last_modified TEXT NOT NULL DEFAULT '',
                is_indexed INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(project_id, relative_path)
            );

            CREATE INDEX IF NOT EXISTS idx_pfiles_project ON project_files(project_id);
            CREATE INDEX IF NOT EXISTS idx_pfiles_hash ON project_files(file_hash);
            CREATE INDEX IF NOT EXISTS idx_pfiles_path ON project_files(project_id, relative_path);

            CREATE TABLE IF NOT EXISTS project_chunks (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL DEFAULT '',
                start_line INTEGER NOT NULL DEFAULT 0,
                end_line INTEGER NOT NULL DEFAULT 0,
                symbol_name TEXT,
                symbol_type TEXT,
                embedding BLOB,
                token_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_pchunks_file ON project_chunks(file_id);
            CREATE INDEX IF NOT EXISTS idx_pchunks_project ON project_chunks(project_id);
            CREATE INDEX IF NOT EXISTS idx_pchunks_symbol ON project_chunks(symbol_name);

            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT,
                source_ip TEXT,
                resource TEXT,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,
                details_json TEXT,
                correlation_id TEXT
            );

            CREATE INDEX IF NOT EXISTS ix_audit_events_timestamp ON audit_events(timestamp);
            CREATE INDEX IF NOT EXISTS ix_audit_events_event_type ON audit_events(event_type);

            CREATE TABLE IF NOT EXISTS similarity_links (
                id TEXT PRIMARY KEY,
                source_cache_id TEXT NOT NULL,
                target_cache_id TEXT NOT NULL,
                similarity REAL NOT NULL,
                source_query_norm TEXT NOT NULL,
                target_query_norm TEXT NOT NULL,
                strength INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_sim_links_source ON similarity_links(source_cache_id);
            CREATE INDEX IF NOT EXISTS idx_sim_links_target ON similarity_links(target_cache_id);

            CREATE TABLE IF NOT EXISTS atomic_facts (
                id TEXT PRIMARY KEY,
                source_cache_id TEXT NOT NULL,
                fact_text TEXT NOT NULL,
                entity TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                confidence REAL NOT NULL DEFAULT 1.0,
                quality_score REAL NOT NULL DEFAULT 0.5,
                serve_count INTEGER NOT NULL DEFAULT 0,
                namespace_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_atomic_facts_entity ON atomic_facts(entity);
            CREATE INDEX IF NOT EXISTS idx_atomic_facts_namespace ON atomic_facts(namespace_id);

            CREATE TABLE IF NOT EXISTS atomic_fact_embeddings (
                fact_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            );
        """)

        # FTS5 for full-text search (standalone, not external content)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
                section_id, text_content, section_title, citation
            )
        """)

        # Schema upgrades for existing databases (idempotent)
        for stmt in [
            "ALTER TABLE similarity_links ADD COLUMN strength INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE atomic_facts ADD COLUMN quality_score REAL NOT NULL DEFAULT 0.5",
            "ALTER TABLE answer_cache ADD COLUMN estimated_cost REAL NOT NULL DEFAULT 0.0",
            "ALTER TABLE answer_cache ADD COLUMN namespace_id TEXT DEFAULT NULL",
            "ALTER TABLE answer_cache ADD COLUMN max_age_seconds INTEGER DEFAULT NULL",
            "ALTER TABLE answer_cache ADD COLUMN last_served_at TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(stmt)
            except Exception:  # noqa: S110 — column already exists
                pass

        conn.commit()
        self._conn = conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.initialize()
        assert self._conn is not None  # noqa: S101 — type narrowing after None check
        return self._conn

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        self._write_lock.acquire()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._write_lock.release()

    def store_document(self, session: Any, doc: DocumentRecord) -> None:
        session.execute(
            "INSERT INTO documents (id, document_type, source, title, jurisdiction, source_format, metadata, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",  # noqa: E501
            (
                doc.id,
                doc.document_type,
                doc.source,
                doc.title,
                doc.jurisdiction,
                doc.source_format,
                json.dumps(doc.metadata),
                json.dumps(doc.tags),
            ),
        )

    def store_section(self, session: Any, section: SectionRecord) -> None:
        hierarchy = section.hierarchy_path
        if isinstance(hierarchy, list):
            hierarchy = json.dumps(hierarchy)
        session.execute(
            "INSERT INTO sections (id, document_id, text_content, version_hash, citation, section_number, section_title, hierarchy_path, is_current, metadata, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  # noqa: E501
            (
                section.id,
                section.document_id,
                section.text_content,
                section.version_hash,
                section.citation,
                section.section_number,
                section.section_title,
                hierarchy,
                int(section.is_current),
                json.dumps(section.metadata),
                json.dumps(section.tags),
            ),
        )
        # Update FTS index
        session.execute(
            "INSERT INTO sections_fts (section_id, text_content, section_title, citation) VALUES (?, ?, ?, ?)",
            (section.id, section.text_content, section.section_title or "", section.citation or ""),
        )

    def get_section(self, session: Any, section_id: str) -> SectionRecord | None:
        row = session.execute("SELECT * FROM sections WHERE id = ? AND is_current = 1", (section_id,)).fetchone()
        return self._row_to_section(row) if row else None

    def get_section_by_citation(self, session: Any, citation: str) -> SectionRecord | None:
        row = session.execute("SELECT * FROM sections WHERE citation = ? AND is_current = 1", (citation,)).fetchone()
        return self._row_to_section(row) if row else None

    def get_section_version_hash(self, session: Any, section_id: str) -> str | None:
        row = session.execute(
            "SELECT version_hash FROM sections WHERE id = ? AND is_current = 1", (section_id,)
        ).fetchone()
        return row["version_hash"] if row else None

    def store_chunk(self, session: Any, chunk: ChunkRecord) -> None:
        embedding_blob = None
        if chunk.embedding:
            import struct

            embedding_blob = struct.pack(f"{len(chunk.embedding)}f", *chunk.embedding)
        session.execute(
            "INSERT INTO chunks (id, section_id, chunk_index, text_content, embedding, document_type, jurisdiction, char_offset) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",  # noqa: E501
            (
                chunk.id,
                chunk.section_id,
                chunk.chunk_index,
                chunk.text_content,
                embedding_blob,
                chunk.document_type,
                chunk.jurisdiction,
                chunk.char_offset,
            ),
        )

    def hybrid_search(
        self,
        session: Any,
        query: str,
        embedding: list[float] | None = None,
        limit: int = 10,
        jurisdiction: str | None = None,
        document_type: str | None = None,
    ) -> list[SearchResult]:
        import math
        import struct

        fts_scores: dict[str, float] = {}  # section_id -> score
        vec_scores: dict[str, float] = {}  # section_id -> score

        # --- BM25 branch (FTS5) ---
        try:
            # Sanitize query for FTS5: wrap in quotes to force literal matching,
            # escape embedded quotes to prevent FTS5 operator injection
            import re

            safe_query = re.sub(r'["\*]', " ", query)  # strip FTS operators
            safe_query = '"' + safe_query.strip() + '"'
            fts_rows = session.execute(
                "SELECT section_id, rank FROM sections_fts WHERE sections_fts MATCH ? ORDER BY rank LIMIT ?",
                (safe_query, limit * 3),
            ).fetchall()
            for row in fts_rows:
                fts_scores[row["section_id"]] = abs(row["rank"])
        except Exception:  # noqa: S110 — FTS syntax error graceful degradation
            pass

        # --- Vector branch (cosine similarity on chunk embeddings) ---
        if embedding:
            # Build filter clause
            where_parts = ["c.embedding IS NOT NULL"]
            params: list[Any] = []
            if jurisdiction:
                where_parts.append("c.jurisdiction = ?")
                params.append(jurisdiction)
            if document_type:
                where_parts.append("c.document_type = ?")
                params.append(document_type)

            where_clause = " AND ".join(where_parts)
            chunk_rows = session.execute(
                f"SELECT c.section_id, c.embedding, c.text_content FROM chunks c WHERE {where_clause} LIMIT 5000",  # noqa: S608 — where_clause from allowlisted column names, values parameterized
                params,
            ).fetchall()

            # Compute cosine similarity in Python
            query_norm = math.sqrt(sum(x * x for x in embedding))
            if query_norm > 0:
                for crow in chunk_rows:
                    blob = crow["embedding"]
                    if not blob:
                        continue
                    dim = len(blob) // 4
                    candidate = struct.unpack(f"{dim}f", blob)
                    dot = sum(a * b for a, b in zip(embedding, candidate))
                    cand_norm = math.sqrt(sum(x * x for x in candidate))
                    if cand_norm > 0:
                        cosine_sim = dot / (query_norm * cand_norm)
                        sid = crow["section_id"]
                        # Keep best chunk score per section
                        if sid not in vec_scores or cosine_sim > vec_scores[sid]:
                            vec_scores[sid] = cosine_sim

        # --- Merge & rank ---
        all_section_ids = set(fts_scores) | set(vec_scores)
        if not all_section_ids:
            return []

        # Normalize scores to 0-1
        def _normalize(scores: dict[str, float]) -> dict[str, float]:
            if not scores:
                return {}
            mn, mx = min(scores.values()), max(scores.values())
            rng = mx - mn
            if rng == 0:
                return {k: 1.0 for k in scores}
            return {k: (v - mn) / rng for k, v in scores.items()}

        norm_fts = _normalize(fts_scores)
        norm_vec = _normalize(vec_scores)

        # Weighted fusion: 40% BM25 + 60% vector (matches Postgres adapter)
        weight_fts = 0.4 if vec_scores else 1.0
        weight_vec = 0.6 if vec_scores else 0.0

        merged: list[tuple[str, float]] = []
        for sid in all_section_ids:
            score = weight_fts * norm_fts.get(sid, 0.0) + weight_vec * norm_vec.get(sid, 0.0)
            merged.append((sid, score))

        merged.sort(key=lambda x: x[1], reverse=True)

        results = []
        for sid, score in merged[: limit * 2]:
            sec = self.get_section(session, sid)
            if sec is None:
                continue
            if jurisdiction:
                sec_jur = sec.metadata.get("jurisdiction") if isinstance(sec.metadata, dict) else None
                if sec_jur and sec_jur != jurisdiction:
                    continue
            results.append(
                SearchResult(
                    section_id=sec.id,
                    citation=sec.citation or "",
                    title=sec.section_title or "",
                    snippet=sec.text_content[:300],
                    score=round(score, 4),
                    version_hash=sec.version_hash or "",
                )
            )
            if len(results) >= limit:
                break
        return results

    def cache_lookup(self, session: Any, answer_key: str) -> AnswerCacheRecord | None:
        row = session.execute(
            "SELECT * FROM answer_cache WHERE answer_key = ? AND is_valid = 1", (answer_key,)
        ).fetchone()
        return self._row_to_cache(row) if row else None

    def cache_store(self, session: Any, record: AnswerCacheRecord) -> None:
        # DELETE any existing row with the same answer_key first (handles
        # re-caching after invalidation where the old row is is_valid=0).
        # Must delete cache_embeddings first (FK constraint).
        old_row = session.execute("SELECT id FROM answer_cache WHERE answer_key = ?", (record.answer_key,)).fetchone()
        if old_row:
            session.execute("DELETE FROM cache_embeddings WHERE cache_id = ?", (old_row["id"],))
            session.execute("DELETE FROM answer_cache WHERE id = ?", (old_row["id"],))
        session.execute(
            "INSERT INTO answer_cache (id, answer_key, question_raw, question_normalized, filters, answer_text, source_sections, model_used, generation_ms, confidence, namespace_id, max_age_seconds, estimated_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",  # noqa: E501
            (
                record.id,
                record.answer_key,
                record.question_raw,
                record.question_normalized,
                json.dumps(record.filters),
                record.answer_text,
                json.dumps(record.source_sections),
                record.model_used,
                record.generation_ms,
                record.confidence,
                record.namespace_id,
                record.max_age_seconds,
                record.estimated_cost,
            ),
        )

    def cache_invalidate(self, session: Any, answer_id: str, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        session.execute(
            "UPDATE answer_cache SET is_valid = 0, invalidated_at = ?, invalidation_reason = ? WHERE id = ?",
            (now, reason, answer_id),
        )

    def cache_invalidate_by_section(self, session: Any, section_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        reason = f"Source section {section_id} changed"
        # Pre-filter with LIKE to avoid full table scan + JSON parse on every row
        rows = session.execute(
            "SELECT id, source_sections FROM answer_cache WHERE is_valid = 1 AND source_sections LIKE ?",
            (f"%{section_id}%",),
        ).fetchall()
        count = 0
        for row in rows:
            sources = json.loads(row["source_sections"])
            if any(s.get("section_id") == section_id for s in sources):
                session.execute(
                    "UPDATE answer_cache SET is_valid = 0, invalidated_at = ?, invalidation_reason = ? WHERE id = ?",
                    (now, reason, row["id"]),
                )
                count += 1
        return count

    def cache_clear_all(self, session: Any, reason: str = "Manual clear") -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = session.execute(
            "UPDATE answer_cache SET is_valid = 0, invalidated_at = ?, invalidation_reason = ? WHERE is_valid = 1",
            (now, reason),
        )
        return int(cursor.rowcount or 0)

    def cache_increment_serve(self, session: Any, answer_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        session.execute(
            "UPDATE answer_cache SET serve_count = serve_count + 1, last_served_at = ? WHERE id = ?",
            (now, answer_id),
        )

    def cache_stats(self, session: Any) -> dict:
        total = session.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0]
        valid = session.execute("SELECT COUNT(*) FROM answer_cache WHERE is_valid = 1").fetchone()[0]
        total_serves = session.execute("SELECT COALESCE(SUM(serve_count), 0) FROM answer_cache").fetchone()[0]
        avg_ms = session.execute("SELECT COALESCE(AVG(generation_ms), 0) FROM answer_cache").fetchone()[0]

        # Total compute saved: for each cached answer, generation_ms * serve_count
        total_saved_ms = session.execute(
            "SELECT COALESCE(SUM(generation_ms * serve_count), 0) FROM answer_cache WHERE is_valid = 1"
        ).fetchone()[0]

        # Hit rate approximation: serves vs cache misses (entries that were never served).
        # This is an approximation — for precise hit/miss tracking, instrument the
        # lookup path with explicit hit/miss counters.
        cache_misses = session.execute("SELECT COUNT(*) FROM answer_cache WHERE serve_count = 0").fetchone()[0]
        total_lookups = total_serves + cache_misses
        hit_rate = round(min(total_serves / max(total_lookups, 1) * 100, 100.0), 1)

        return {
            "total_entries": total,
            "valid_entries": valid,
            "invalidated_entries": total - valid,
            "total_serves": total_serves,
            "hit_rate": hit_rate,
            "total_compute_saved_ms": total_saved_ms,
            "total_compute_saved_s": round(total_saved_ms / 1000, 2),
            "avg_generation_ms": round(avg_ms, 1),
        }

    def recent_cached_queries(self, session: Any, limit: int = 20) -> list[dict]:
        """Return the most recent cached queries with full detail."""
        rows = session.execute(
            """SELECT question_raw, generation_ms, serve_count, is_valid,
                      model_used, created_at, confidence, answer_key
               FROM answer_cache
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "question": row["question_raw"],
                "generation_ms": row["generation_ms"],
                "serve_count": row["serve_count"],
                "is_valid": bool(row["is_valid"]),
                "model_used": row["model_used"],
                "created_at": row["created_at"],
                "confidence": row["confidence"],
                "answer_key": row["answer_key"],
            }
            for row in rows
        ]

    def cache_model_comparison(self, session: Any) -> list[dict]:
        """Return cost comparison data for cached queries with serves > 0."""
        rows = session.execute(
            """SELECT question_raw, generation_ms, serve_count, model_used,
                      LENGTH(question_raw) AS question_len,
                      LENGTH(answer_text) AS answer_len
               FROM answer_cache
               WHERE serve_count > 0 AND is_valid = 1
               ORDER BY serve_count DESC
               LIMIT 50"""
        ).fetchall()
        cached_serve_ms = 0.5  # approximate time to serve from cache
        chars_per_token = 4  # rough estimate for tokenization
        return [
            {
                "query": row["question_raw"],
                "first_gen_ms": row["generation_ms"],
                "cached_serve_ms": cached_serve_ms,
                "serves": row["serve_count"],
                "model_used": row["model_used"],
                "total_without_cache_ms": row["generation_ms"] * (1 + row["serve_count"]),
                "total_with_cache_ms": row["generation_ms"] + (cached_serve_ms * row["serve_count"]),
                "savings_ms": row["generation_ms"] * row["serve_count"] - (cached_serve_ms * row["serve_count"]),
                "input_tokens": max(1, (row["question_len"] or 0) // chars_per_token),
                "output_tokens": max(1, (row["answer_len"] or 0) // chars_per_token),
            }
            for row in rows
        ]

    def document_stats(self, session: Any) -> dict:
        """Return document-level statistics and listing."""
        rows = session.execute(
            """SELECT d.id, d.title, d.source_format, d.created_at, d.document_type,
                      d.source, d.jurisdiction,
                      COUNT(DISTINCT s.id) AS section_count,
                      COUNT(DISTINCT c.id) AS chunk_count
               FROM documents d
               LEFT JOIN sections s ON s.document_id = d.id AND s.is_current = 1
               LEFT JOIN chunks c ON c.section_id = s.id
               GROUP BY d.id
               ORDER BY d.created_at DESC"""
        ).fetchall()

        documents = [
            {
                "id": row["id"],
                "title": row["title"],
                "source_format": row["source_format"],
                "document_type": row["document_type"],
                "source": row["source"],
                "jurisdiction": row["jurisdiction"],
                "section_count": row["section_count"],
                "chunk_count": row["chunk_count"],
                "created_at": row["created_at"],
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

    def cache_fuzzy_match(
        self,
        session: Any,
        normalized_query: str,
        filters: dict,
        threshold: float = 0.85,
        max_results: int = 5,
    ) -> list[AnswerCacheRecord]:
        """Find cached answers with similar normalized queries.

        SQLite has no pg_trgm, so candidates are pre-filtered with LIKE and then
        scored in Python by cache_engine.fuzzy_similarity.

        The pre-filter matches on token *prefixes*, not whole tokens. A
        whole-token filter cannot retrieve the row a typo is meant to find:
        '%pollicy%' never matches stored 'policy', so the candidate is never
        scored and the threshold never gets a say.
        """
        from bitmod.cache_engine import fuzzy_prefilter_terms, fuzzy_similarity

        if not normalized_query.split():
            return []

        prefixes = fuzzy_prefilter_terms(normalized_query)
        if not prefixes:
            return []

        # Two prefixes first for precision, one as a fallback for recall.
        if len(prefixes) >= 2:
            rows = session.execute(
                "SELECT * FROM answer_cache WHERE is_valid = 1 "
                "AND question_normalized LIKE ? AND question_normalized LIKE ? LIMIT 200",
                (f"%{prefixes[0]}%", f"%{prefixes[1]}%"),
            ).fetchall()
            if not rows:
                rows = session.execute(
                    "SELECT * FROM answer_cache WHERE is_valid = 1 AND question_normalized LIKE ? LIMIT 200",
                    (f"%{prefixes[0]}%",),
                ).fetchall()
        else:
            rows = session.execute(
                "SELECT * FROM answer_cache WHERE is_valid = 1 AND question_normalized LIKE ? LIMIT 200",
                (f"%{prefixes[0]}%",),
            ).fetchall()

        scored: list[tuple[float, AnswerCacheRecord]] = []
        for row in rows:
            candidate = row["question_normalized"]
            if not candidate:
                continue
            similarity = fuzzy_similarity(normalized_query, candidate)
            if similarity >= threshold:
                scored.append((similarity, self._row_to_cache(row)))

        # Sort by similarity descending, return top N
        scored.sort(key=lambda x: x[0], reverse=True)
        return [record for _, record in scored[:max_results]]

    # --- Usage Tracking ---

    def store_usage(
        self,
        session: Any,
        *,
        record_id: str,
        timestamp: float,
        query_hash: str,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cached: bool,
        cache_layer: str,
        latency_ms: float,
        tenant_id: str,
        estimated_cost_usd: float,
        estimated_savings_usd: float,
    ) -> None:
        """Store a usage tracking record."""
        session.execute(
            """INSERT INTO usage_tracking
               (id, timestamp, query_hash, model, provider, input_tokens,
                output_tokens, cached, cache_layer, latency_ms, tenant_id,
                estimated_cost_usd, estimated_savings_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                timestamp,
                query_hash,
                model,
                provider,
                input_tokens,
                output_tokens,
                int(cached),
                cache_layer,
                latency_ms,
                tenant_id,
                estimated_cost_usd,
                estimated_savings_usd,
            ),
        )

    def get_usage(  # type: ignore[override]
        self,
        session: Any,
        tenant_id: str = "default",
        since: float = 0,
    ) -> list[dict]:
        """Return usage records for a tenant since a given timestamp."""
        rows = session.execute(
            """SELECT timestamp, query_hash, model, provider, input_tokens,
                      output_tokens, cached, cache_layer, latency_ms,
                      tenant_id, estimated_cost_usd, estimated_savings_usd
               FROM usage_tracking
               WHERE tenant_id = ? AND timestamp >= ?
               ORDER BY timestamp DESC""",
            (tenant_id, since),
        ).fetchall()
        return [
            {
                "timestamp": row["timestamp"],
                "query_hash": row["query_hash"],
                "model": row["model"],
                "provider": row["provider"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cached": bool(row["cached"]),
                "cache_layer": row["cache_layer"],
                "latency_ms": row["latency_ms"],
                "tenant_id": row["tenant_id"],
                "estimated_cost_usd": row["estimated_cost_usd"],
                "estimated_savings_usd": row["estimated_savings_usd"],
            }
            for row in rows
        ]

    def _row_to_section(self, row: sqlite3.Row) -> SectionRecord:
        return SectionRecord(
            id=row["id"],
            document_id=row["document_id"],
            text_content=row["text_content"],
            version_hash=row["version_hash"],
            citation=row["citation"],
            section_number=row["section_number"],
            section_title=row["section_title"],
            hierarchy_path=row["hierarchy_path"],
            is_current=bool(row["is_current"]),
            metadata=json.loads(row["metadata"]),
            tags=json.loads(row["tags"]) if row["tags"] else None,
        )

    # --- Content Blocks ---

    def store_block(self, session: Any, block: ContentBlock) -> None:
        session.execute(
            "INSERT INTO content_blocks (id, section_id, compression, content, version_hash, token_count) VALUES (?, ?, ?, ?, ?, ?)",  # noqa: E501
            (block.id, block.section_id, block.compression, block.content, block.version_hash, block.token_count),
        )

    def get_blocks(
        self,
        session: Any,
        section_id: str,
        compression: str | None = None,
    ) -> list[ContentBlock]:
        if compression:
            rows = session.execute(
                "SELECT * FROM content_blocks WHERE section_id = ? AND compression = ?",
                (section_id, compression),
            ).fetchall()
        else:
            rows = session.execute(
                "SELECT * FROM content_blocks WHERE section_id = ?",
                (section_id,),
            ).fetchall()
        return [self._row_to_block(r) for r in rows]

    def delete_chunks_by_section(self, session: Any, section_id: str) -> int:
        cursor = session.execute(
            "DELETE FROM chunks WHERE section_id = ?",
            (section_id,),
        )
        return cursor.rowcount  # type: ignore[no-any-return]

    def invalidate_blocks(self, session: Any, section_id: str) -> int:
        cursor = session.execute(
            "DELETE FROM content_blocks WHERE section_id = ?",
            (section_id,),
        )
        return cursor.rowcount  # type: ignore[no-any-return]

    # --- Section Tags ---

    def store_tag(self, session: Any, tag: SectionTag) -> None:
        session.execute(
            "INSERT OR REPLACE INTO section_tags (section_id, tag_key, tag_value, confidence, source) VALUES (?, ?, ?, ?, ?)",  # noqa: E501
            (tag.section_id, tag.tag_key, tag.tag_value, tag.confidence, tag.source),
        )

    def get_tags(self, session: Any, section_id: str) -> list[SectionTag]:
        rows = session.execute(
            "SELECT * FROM section_tags WHERE section_id = ?",
            (section_id,),
        ).fetchall()
        return [self._row_to_tag(r) for r in rows]

    def search_by_tag(
        self,
        session: Any,
        tag_key: str,
        tag_value: str,
        limit: int = 20,
    ) -> list[SectionRecord]:
        rows = session.execute(
            """SELECT s.* FROM sections s
               INNER JOIN section_tags t ON s.id = t.section_id
               WHERE t.tag_key = ? AND t.tag_value = ? AND s.is_current = 1
               LIMIT ?""",
            (tag_key, tag_value, limit),
        ).fetchall()
        return [self._row_to_section(r) for r in rows]

    # --- Section Relationships ---

    def store_relationship(self, session: Any, rel: SectionRelationship) -> None:
        session.execute(
            "INSERT OR REPLACE INTO section_relationships (section_a_id, section_b_id, relationship, strength, source, hit_count) VALUES (?, ?, ?, ?, ?, ?)",  # noqa: E501
            (rel.section_a_id, rel.section_b_id, rel.relationship, rel.strength, rel.source, rel.hit_count),
        )

    def get_relationships(self, session: Any, section_id: str) -> list[SectionRelationship]:
        rows = session.execute(
            """SELECT * FROM section_relationships
               WHERE section_a_id = ? OR section_b_id = ?""",
            (section_id, section_id),
        ).fetchall()
        return [self._row_to_relationship(r) for r in rows]

    def increment_relationship(
        self,
        session: Any,
        section_a_id: str,
        section_b_id: str,
        relationship: str,
    ) -> None:
        # Try update first
        cursor = session.execute(
            """UPDATE section_relationships SET hit_count = hit_count + 1
               WHERE section_a_id = ? AND section_b_id = ? AND relationship = ?""",
            (section_a_id, section_b_id, relationship),
        )
        if cursor.rowcount == 0:
            # Insert new
            session.execute(
                "INSERT INTO section_relationships (section_a_id, section_b_id, relationship, strength, source, hit_count) VALUES (?, ?, ?, 1.0, 'co_retrieval', 1)",  # noqa: E501
                (section_a_id, section_b_id, relationship),
            )

    # --- Row converters ---

    def _row_to_block(self, row: sqlite3.Row) -> ContentBlock:
        return ContentBlock(
            id=row["id"],
            section_id=row["section_id"],
            compression=row["compression"],
            content=row["content"],
            version_hash=row["version_hash"],
            token_count=row["token_count"],
        )

    def _row_to_tag(self, row: sqlite3.Row) -> SectionTag:
        return SectionTag(
            section_id=row["section_id"],
            tag_key=row["tag_key"],
            tag_value=row["tag_value"],
            confidence=row["confidence"],
            source=row["source"],
        )

    def _row_to_relationship(self, row: sqlite3.Row) -> SectionRelationship:
        return SectionRelationship(
            section_a_id=row["section_a_id"],
            section_b_id=row["section_b_id"],
            relationship=row["relationship"],
            strength=row["strength"],
            source=row["source"],
            hit_count=row["hit_count"],
        )

    def _row_to_cache(self, row: sqlite3.Row) -> AnswerCacheRecord:
        # namespace_id / max_age_seconds / last_served_at may not exist in older DBs
        ns_id = None
        max_age = None
        last_served = None
        try:
            ns_id = row["namespace_id"]
        except (IndexError, KeyError):
            pass
        try:
            max_age = row["max_age_seconds"]
        except (IndexError, KeyError):
            pass
        try:
            last_served = row["last_served_at"]
        except (IndexError, KeyError):
            pass
        est_cost = 0.0
        try:
            est_cost = row["estimated_cost"] or 0.0
        except (IndexError, KeyError):
            pass
        return AnswerCacheRecord(
            id=row["id"],
            answer_key=row["answer_key"],
            question_raw=row["question_raw"],
            question_normalized=row["question_normalized"],
            filters=json.loads(row["filters"]),
            answer_text=row["answer_text"],
            source_sections=json.loads(row["source_sections"]),
            model_used=row["model_used"],
            generation_ms=row["generation_ms"],
            confidence=row["confidence"],
            is_valid=bool(row["is_valid"]),
            serve_count=row["serve_count"],
            created_at=row["created_at"],
            namespace_id=ns_id,
            max_age_seconds=max_age,
            last_served_at=last_served,
            estimated_cost=est_cost,
        )

    # --- Semantic Cache (embedding-based) ---

    def cache_store_embedding(self, session: Any, cache_id: str, embedding: list[float]) -> None:
        """Store a query embedding alongside a cache entry."""
        import struct

        blob = struct.pack(f"{len(embedding)}f", *embedding)
        session.execute(
            "INSERT OR REPLACE INTO cache_embeddings (cache_id, embedding) VALUES (?, ?)",
            (cache_id, blob),
        )

    def cache_get_embeddings(
        self, session: Any, limit: int = 2000, namespace_id: str | None = None
    ) -> list[tuple[str, list[float]]]:
        """Return valid cache embeddings as (cache_id, embedding) pairs.

        Args:
            limit: Maximum number of embeddings to return. Defaults to 2000.
            namespace_id: If set, only return embeddings for this namespace.

        The cache engine dynamically adjusts its scan limit based on
        whether numpy is available.
        """
        import struct

        # Clamp limit to a safe maximum to prevent resource exhaustion
        limit = min(max(1, limit), 5000)
        if namespace_id:
            rows = session.execute(
                """SELECT ce.cache_id, ce.embedding FROM cache_embeddings ce
                   INNER JOIN answer_cache ac ON ce.cache_id = ac.id
                   WHERE ac.is_valid = 1 AND ac.namespace_id = ?
                   ORDER BY ac.created_at DESC
                   LIMIT ?""",
                (namespace_id, limit),
            ).fetchall()
        else:
            rows = session.execute(
                """SELECT ce.cache_id, ce.embedding FROM cache_embeddings ce
                   INNER JOIN answer_cache ac ON ce.cache_id = ac.id
                   WHERE ac.is_valid = 1
                   ORDER BY ac.created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        results = []
        for row in rows:
            blob = row["embedding"]
            n = len(blob) // 4
            emb = list(struct.unpack(f"{n}f", blob))
            results.append((row["cache_id"], emb))
        return results

    def cache_lookup_by_id(self, session: Any, cache_id: str) -> AnswerCacheRecord | None:
        """Look up a cached answer by its record ID."""
        row = session.execute(
            "SELECT * FROM answer_cache WHERE id = ? AND is_valid = 1",
            (cache_id,),
        ).fetchone()
        return self._row_to_cache(row) if row else None

    # --- Cache eviction ---

    def cache_delete_expired(self, session: Any) -> int:
        """Delete cache entries whose TTL has elapsed. Returns count deleted."""
        # Find expired entries first, then delete (avoids RETURNING which needs SQLite 3.35+)
        rows = session.execute(
            """SELECT id FROM answer_cache
               WHERE max_age_seconds IS NOT NULL
                 AND datetime(created_at, '+' || max_age_seconds || ' seconds') < datetime('now')""",
        ).fetchall()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        session.execute(f"DELETE FROM cache_embeddings WHERE cache_id IN ({placeholders})", ids)  # noqa: S608 — placeholders are ? markers, values parameterized
        session.execute(f"DELETE FROM answer_cache WHERE id IN ({placeholders})", ids)  # noqa: S608 — placeholders are ? markers, values parameterized
        return len(ids)

    def cache_evict_lru(self, session: Any, max_entries: int) -> int:
        """Frequency-predicted cost-aware eviction. Returns count deleted.

        Scores each entry by predicted future value:
            predicted_value = predicted_future_hits * estimated_cost
        Entries with low predicted value are evicted first. This replaces the
        old backward-looking ``1/(serve_count+1) * 1/(cost+0.001)`` formula
        with a forward-looking prediction using exponential decay on recency.
        """
        from bitmod.cache_engine import predict_future_hits

        total = session.execute("SELECT COUNT(*) FROM answer_cache WHERE is_valid = 1").fetchone()[0]
        if total <= max_entries:
            return 0
        excess = total - max_entries
        # Fetch candidates — pull extra so we can score in Python
        candidates = session.execute(
            """SELECT id, serve_count, estimated_cost, last_served_at, created_at
               FROM answer_cache
               WHERE is_valid = 1
               ORDER BY last_served_at ASC NULLS FIRST, created_at ASC""",
        ).fetchall()
        if not candidates:
            return 0

        # Score each candidate using frequency prediction
        scored: list[tuple[str, float]] = []
        for row in candidates:
            from bitmod.interfaces.database import AnswerCacheRecord

            rec = AnswerCacheRecord(
                id=row["id"],
                serve_count=row["serve_count"] or 0,
                estimated_cost=row["estimated_cost"] or 0.0,
                last_served_at=row["last_served_at"],
                created_at=row["created_at"],
            )
            predicted_hits = predict_future_hits(rec)
            cost = rec.estimated_cost if rec.estimated_cost > 0 else 0.001
            predicted_value = predicted_hits * cost
            scored.append((rec.id, predicted_value))

        # Sort by predicted value ascending — lowest value evicted first
        scored.sort(key=lambda x: x[1])
        to_evict = [sid for sid, _ in scored[:excess]]

        if not to_evict:
            return 0
        placeholders = ",".join("?" for _ in to_evict)
        session.execute(f"DELETE FROM cache_embeddings WHERE cache_id IN ({placeholders})", to_evict)  # noqa: S608
        session.execute(f"DELETE FROM answer_cache WHERE id IN ({placeholders})", to_evict)  # noqa: S608
        return len(to_evict)

    def cache_count(self, session: Any) -> int:
        """Return total number of valid cache entries."""
        row = session.execute("SELECT COUNT(*) FROM answer_cache WHERE is_valid = 1").fetchone()
        return int(row[0]) if row else 0

    # --- Re-ingestion support ---

    def get_sections_for_document(self, session: Any, document_id: str) -> list[SectionRecord]:
        """Get all current sections for a document."""
        rows = session.execute(
            "SELECT * FROM sections WHERE document_id = ? AND is_current = 1 ORDER BY section_number",
            (document_id,),
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
            "SELECT * FROM documents WHERE title = ? AND source = ? LIMIT 1",
            (title, source),
        ).fetchone()
        if not row:
            return None
        return DocumentRecord(
            id=row["id"],
            document_type=row["document_type"],
            source=row["source"],
            title=row["title"],
            jurisdiction=row["jurisdiction"],
            source_format=row["source_format"],
            metadata=json.loads(row["metadata"]),
            tags=json.loads(row["tags"]) if row["tags"] else None,
        )

    def update_section_content(
        self,
        session: Any,
        section_id: str,
        text_content: str,
        version_hash: str,
    ) -> None:
        """Update a section's content and version hash, and update FTS."""
        session.execute(
            "UPDATE sections SET text_content = ?, version_hash = ? WHERE id = ?",
            (text_content, version_hash, section_id),
        )
        # Update FTS index
        session.execute(
            "DELETE FROM sections_fts WHERE section_id = ?",
            (section_id,),
        )
        row = session.execute(
            "SELECT section_title, citation FROM sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        session.execute(
            "INSERT INTO sections_fts (section_id, text_content, section_title, citation) VALUES (?, ?, ?, ?)",
            (section_id, text_content, row["section_title"] or "" if row else "", row["citation"] or "" if row else ""),
        )

    def mark_section_not_current(self, session: Any, section_id: str) -> None:
        """Mark a section as no longer current."""
        session.execute(
            "UPDATE sections SET is_current = 0 WHERE id = ?",
            (section_id,),
        )

    # --- Namespace CRUD ---

    def namespace_create(self, session: Any, ns: Any) -> None:
        """Create a namespace record."""
        session.execute(
            "INSERT INTO namespaces (id, name, owner_key_id, isolation, public_fallback, created_at) VALUES (?, ?, ?, ?, ?, ?)",  # noqa: E501
            (ns.id, ns.name, ns.owner_key_id, ns.isolation, int(ns.public_fallback), ns.created_at),
        )

    def namespace_get(self, session: Any, namespace_id: str) -> Any:
        """Get a namespace by ID."""
        from bitmod.namespaces import Namespace

        row = session.execute(
            "SELECT * FROM namespaces WHERE id = ?",
            (namespace_id,),
        ).fetchone()
        if not row:
            return None
        return Namespace(
            id=row["id"],
            name=row["name"],
            owner_key_id=row["owner_key_id"],
            isolation=row["isolation"],
            public_fallback=bool(row["public_fallback"]),
            created_at=row["created_at"],
        )

    def namespace_get_by_name(self, session: Any, name: str) -> Any:
        """Get a namespace by name."""
        from bitmod.namespaces import Namespace

        row = session.execute(
            "SELECT * FROM namespaces WHERE name = ?",
            (name,),
        ).fetchone()
        if not row:
            return None
        return Namespace(
            id=row["id"],
            name=row["name"],
            owner_key_id=row["owner_key_id"],
            isolation=row["isolation"],
            public_fallback=bool(row["public_fallback"]),
            created_at=row["created_at"],
        )

    def namespace_list_for_owner(self, session: Any, owner_key_id: str) -> list:
        """List namespaces for an owner."""
        from bitmod.namespaces import Namespace

        rows = session.execute(
            "SELECT * FROM namespaces WHERE owner_key_id = ? ORDER BY created_at DESC",
            (owner_key_id,),
        ).fetchall()
        return [
            Namespace(
                id=r["id"],
                name=r["name"],
                owner_key_id=r["owner_key_id"],
                isolation=r["isolation"],
                public_fallback=bool(r["public_fallback"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def namespace_list_all(self, session: Any) -> list:
        """List all namespaces."""
        from bitmod.namespaces import Namespace

        rows = session.execute(
            "SELECT * FROM namespaces ORDER BY created_at DESC",
        ).fetchall()
        return [
            Namespace(
                id=r["id"],
                name=r["name"],
                owner_key_id=r["owner_key_id"],
                isolation=r["isolation"],
                public_fallback=bool(r["public_fallback"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def namespace_delete(self, session: Any, namespace_id: str) -> None:
        """Delete a namespace by ID."""
        session.execute("DELETE FROM namespaces WHERE id = ?", (namespace_id,))

    def namespace_cache_stats(self, session: Any, namespace_id: str) -> dict:
        """Get cache stats scoped to a namespace."""
        total = session.execute("SELECT COUNT(*) FROM answer_cache WHERE namespace_id = ?", (namespace_id,)).fetchone()[
            0
        ]
        valid = session.execute(
            "SELECT COUNT(*) FROM answer_cache WHERE namespace_id = ? AND is_valid = 1", (namespace_id,)
        ).fetchone()[0]
        total_serves = session.execute(
            "SELECT COALESCE(SUM(serve_count), 0) FROM answer_cache WHERE namespace_id = ?", (namespace_id,)
        ).fetchone()[0]
        total_saved_ms = session.execute(
            "SELECT COALESCE(SUM(generation_ms * serve_count), 0) FROM answer_cache WHERE namespace_id = ? AND is_valid = 1",  # noqa: E501
            (namespace_id,),
        ).fetchone()[0]

        return {
            "namespace_id": namespace_id,
            "total_entries": total,
            "valid_entries": valid,
            "invalidated_entries": total - valid,
            "total_serves": total_serves,
            "total_compute_saved_ms": total_saved_ms,
            "total_compute_saved_s": round(total_saved_ms / 1000, 2),
        }

    # --- Audit Events ---

    def store_audit_event(self, session: Any, record: dict) -> None:
        session.execute(
            """INSERT INTO audit_events
               (id, timestamp, event_type, actor, source_ip, resource, action, outcome, details_json, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",  # noqa: E501
            (
                record["id"],
                record["timestamp"],
                record["event_type"],
                record.get("actor"),
                record.get("source_ip"),
                record.get("resource"),
                record["action"],
                record["outcome"],
                record.get("details_json"),
                record.get("correlation_id"),
            ),
        )

    # --- API Key Management ---

    def store_api_key(self, session: Any, record: dict) -> None:
        session.execute(
            """INSERT INTO api_keys (id, key_hash, key_preview, name, scopes, owner, is_active, created_at, expires_at, email)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",  # noqa: E501
            (
                record["id"],
                record["key_hash"],
                record["key_preview"],
                record["name"],
                record["scopes"],
                record["owner"],
                1 if record["is_active"] else 0,
                record["created_at"],
                record.get("expires_at"),
                record.get("email"),
            ),
        )

    def lookup_api_key(self, session: Any, key_hash: str) -> dict | None:
        row = session.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "key_hash": row["key_hash"],
            "key_preview": row["key_preview"],
            "name": row["name"],
            "scopes": row["scopes"],
            "owner": row["owner"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
            "expires_at": row["expires_at"],
            "email": row["email"] if "email" in row.keys() else None,
        }

    def list_api_keys(self, session: Any, owner: str | None = None) -> list[dict]:
        if owner:
            rows = session.execute(
                "SELECT * FROM api_keys WHERE owner = ? ORDER BY created_at DESC", (owner,)
            ).fetchall()
        else:
            rows = session.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [
            {
                "id": r["id"],
                "key_hash": r["key_hash"],
                "key_preview": r["key_preview"],
                "name": r["name"],
                "scopes": r["scopes"],
                "owner": r["owner"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "expires_at": r["expires_at"],
                "email": r["email"] if "email" in r.keys() else None,
            }
            for r in rows
        ]

    def revoke_api_key(self, session: Any, key_id: str) -> bool:
        cur = session.execute("UPDATE api_keys SET is_active = 0 WHERE id = ? AND is_active = 1", (key_id,))
        return cur.rowcount > 0  # type: ignore[no-any-return]

    def touch_api_key(self, session: Any, key_id: str) -> None:
        from datetime import datetime, timezone

        session.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), key_id),
        )

    # --- Project Knowledge System ---

    def _row_to_project(self, row: sqlite3.Row) -> ProjectRecord:
        from bitmod.interfaces.database import ProjectRecord

        return ProjectRecord(
            id=row["id"],
            name=row["name"],
            root_path=row["root_path"],
            description=row["description"],
            language=row["language"],
            framework=row["framework"],
            is_active=bool(row["is_active"]),
            last_scanned_at=row["last_scanned_at"],
            file_count=row["file_count"],
            total_chunks=row["total_chunks"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_project_file(self, row: sqlite3.Row) -> ProjectFileRecord:
        from bitmod.interfaces.database import ProjectFileRecord

        return ProjectFileRecord(
            id=row["id"],
            project_id=row["project_id"],
            relative_path=row["relative_path"],
            file_hash=row["file_hash"],
            language=row["language"],
            size_bytes=row["size_bytes"],
            last_modified=row["last_modified"],
            is_indexed=bool(row["is_indexed"]),
            chunk_count=row["chunk_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_project_chunk(self, row: sqlite3.Row) -> ProjectChunkRecord:
        import struct

        from bitmod.interfaces.database import ProjectChunkRecord

        emb = None
        if row["embedding"]:
            blob = row["embedding"]
            n = len(blob) // 4
            emb = list(struct.unpack(f"{n}f", blob))
        return ProjectChunkRecord(
            id=row["id"],
            file_id=row["file_id"],
            project_id=row["project_id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            symbol_name=row["symbol_name"],
            symbol_type=row["symbol_type"],
            embedding=emb,
            token_count=row["token_count"],
            created_at=row["created_at"],
        )

    def _row_to_conversation(self, row: sqlite3.Row) -> ConversationRecord:
        from bitmod.interfaces.database import ConversationRecord

        return ConversationRecord(
            id=row["id"],
            project_id=row["project_id"],
            user_message=row["user_message"],
            assistant_response=row["assistant_response"],
            model_used=row["model_used"],
            cache_hit=bool(row["cache_hit"]),
            rating=row["rating"],
            feedback=row["feedback"],
            context_used=json.loads(row["context_used"]),
            generation_ms=row["generation_ms"],
            created_at=row["created_at"],
        )

    def _row_to_correction(self, row: sqlite3.Row) -> CorrectionRecord:
        import struct

        from bitmod.interfaces.database import CorrectionRecord

        emb = None
        if row["embedding"]:
            blob = row["embedding"]
            n = len(blob) // 4
            emb = list(struct.unpack(f"{n}f", blob))
        # H4: Read status field, defaulting to 'approved' for pre-migration rows
        try:
            status = row["status"] if row["status"] else "approved"
        except (IndexError, KeyError):
            status = "approved"
        return CorrectionRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            project_id=row["project_id"],
            original_question=row["original_question"],
            original_answer=row["original_answer"],
            corrected_answer=row["corrected_answer"],
            correction_type=row["correction_type"],
            is_applied=bool(row["is_applied"]),
            embedding=emb,
            status=status,
            created_at=row["created_at"],
        )

    # --- Projects ---

    def project_create(self, session: Any, project: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        session.execute(
            """INSERT INTO projects (id, name, root_path, description, language, framework,
               is_active, last_scanned_at, file_count, total_chunks, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project.id,
                project.name,
                project.root_path,
                project.description,
                project.language,
                project.framework,
                int(project.is_active),
                project.last_scanned_at,
                project.file_count,
                project.total_chunks,
                json.dumps(project.metadata),
                now,
                now,
            ),
        )

    def project_get(self, session: Any, project_id: str) -> Any:
        row = session.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return self._row_to_project(row) if row else None

    def project_get_by_path(self, session: Any, root_path: str) -> Any:
        row = session.execute(
            "SELECT * FROM projects WHERE root_path = ?",
            (root_path,),
        ).fetchone()
        return self._row_to_project(row) if row else None

    def project_list(self, session: Any, active_only: bool = True) -> list:
        if active_only:
            rows = session.execute(
                "SELECT * FROM projects WHERE is_active = 1 ORDER BY updated_at DESC",
            ).fetchall()
        else:
            rows = session.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC",
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def project_update(self, session: Any, project_id: str, **kwargs: Any) -> None:
        allowed = {
            "name",
            "description",
            "language",
            "framework",
            "is_active",
            "last_scanned_at",
            "file_count",
            "total_chunks",
            "metadata",
        }
        updates = []
        values = []
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "metadata":
                v = json.dumps(v)
            elif k == "is_active":
                v = int(v)
            updates.append(f"{k} = ?")
            values.append(v)
        if not updates:
            return
        updates.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(project_id)
        session.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",  # noqa: S608 — column names from allowlist, values parameterized
            values,
        )

    def project_delete(self, session: Any, project_id: str) -> None:
        session.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # --- Project Files ---

    def project_file_upsert(self, session: Any, pf: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        session.execute(
            """INSERT INTO project_files (id, project_id, relative_path, file_hash, language,
               size_bytes, last_modified, is_indexed, chunk_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, relative_path) DO UPDATE SET
               file_hash=excluded.file_hash, language=excluded.language,
               size_bytes=excluded.size_bytes, last_modified=excluded.last_modified,
               is_indexed=excluded.is_indexed, chunk_count=excluded.chunk_count,
               updated_at=excluded.updated_at""",
            (
                pf.id,
                pf.project_id,
                pf.relative_path,
                pf.file_hash,
                pf.language,
                pf.size_bytes,
                pf.last_modified,
                int(pf.is_indexed),
                pf.chunk_count,
                now,
                now,
            ),
        )

    def project_file_get(self, session: Any, project_id: str, relative_path: str) -> Any:
        row = session.execute(
            "SELECT * FROM project_files WHERE project_id = ? AND relative_path = ?",
            (project_id, relative_path),
        ).fetchone()
        return self._row_to_project_file(row) if row else None

    def project_files_list(self, session: Any, project_id: str) -> list:
        rows = session.execute(
            "SELECT * FROM project_files WHERE project_id = ? ORDER BY relative_path",
            (project_id,),
        ).fetchall()
        return [self._row_to_project_file(r) for r in rows]

    def project_files_stale(self, session: Any, project_id: str, current_paths: set) -> list:
        rows = session.execute(
            "SELECT * FROM project_files WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        return [self._row_to_project_file(r) for r in rows if r["relative_path"] not in current_paths]

    def project_file_delete(self, session: Any, file_id: str) -> None:
        session.execute("DELETE FROM project_files WHERE id = ?", (file_id,))

    # --- Project Chunks ---

    def project_chunk_store(self, session: Any, chunk: Any) -> None:
        import struct

        blob = None
        if chunk.embedding:
            blob = struct.pack(f"{len(chunk.embedding)}f", *chunk.embedding)
        session.execute(
            """INSERT INTO project_chunks (id, file_id, project_id, chunk_index, content,
               start_line, end_line, symbol_name, symbol_type, embedding, token_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk.id,
                chunk.file_id,
                chunk.project_id,
                chunk.chunk_index,
                chunk.content,
                chunk.start_line,
                chunk.end_line,
                chunk.symbol_name,
                chunk.symbol_type,
                blob,
                chunk.token_count,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def project_chunks_delete_by_file(self, session: Any, file_id: str) -> int:
        cur = session.execute("DELETE FROM project_chunks WHERE file_id = ?", (file_id,))
        return cur.rowcount  # type: ignore[no-any-return]

    def project_chunks_search(
        self,
        session: Any,
        project_id: str,
        embedding: list[float],
        limit: int = 10,
    ) -> list:
        """Semantic search over project chunks using cosine similarity."""
        import struct

        rows = session.execute(
            "SELECT * FROM project_chunks WHERE project_id = ? AND embedding IS NOT NULL",
            (project_id,),
        ).fetchall()
        if not rows:
            return []

        # Compute cosine similarity
        scored = []
        try:
            import numpy as np

            query_vec = np.array(embedding, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = np.frombuffer(blob, dtype=np.float32, count=n)
                vec_norm = np.linalg.norm(vec)
                if vec_norm == 0:
                    continue
                sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
                scored.append((sim, row))
        except ImportError:
            # Pure Python fallback
            import math

            q = embedding
            q_norm = math.sqrt(sum(x * x for x in q))
            if q_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = list(struct.unpack(f"{n}f", blob))  # type: ignore[assignment]
                v_norm = math.sqrt(sum(x * x for x in vec))
                if v_norm == 0:
                    continue
                dot = sum(a * b for a, b in zip(q, vec))
                sim = dot / (q_norm * v_norm)
                scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._row_to_project_chunk(row) for _, row in scored[:limit]]

    def project_chunks_by_symbol(
        self,
        session: Any,
        project_id: str,
        symbol_name: str,
    ) -> list:
        rows = session.execute(
            "SELECT * FROM project_chunks WHERE project_id = ? AND symbol_name = ?",
            (project_id, symbol_name),
        ).fetchall()
        return [self._row_to_project_chunk(r) for r in rows]

    # --- Conversations ---

    def conversation_store(self, session: Any, conv: Any) -> None:
        session.execute(
            """INSERT INTO conversations (id, project_id, user_message, assistant_response,
               model_used, cache_hit, rating, feedback, context_used, generation_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conv.id,
                conv.project_id,
                conv.user_message,
                conv.assistant_response,
                conv.model_used,
                int(conv.cache_hit),
                conv.rating,
                conv.feedback,
                json.dumps(conv.context_used),
                conv.generation_ms,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def conversation_store_embedding(self, session: Any, conversation_id: str, embedding: list[float]) -> None:
        import struct

        blob = struct.pack(f"{len(embedding)}f", *embedding)
        session.execute(
            "INSERT OR REPLACE INTO conversation_embeddings (conversation_id, embedding) VALUES (?, ?)",
            (conversation_id, blob),
        )

    def conversation_get(self, session: Any, conversation_id: str) -> Any:
        row = session.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return self._row_to_conversation(row) if row else None

    def conversation_list(
        self,
        session: Any,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list:
        if project_id:
            rows = session.execute(
                "SELECT * FROM conversations WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            ).fetchall()
        else:
            rows = session.execute(
                "SELECT * FROM conversations ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def conversation_search(
        self,
        session: Any,
        embedding: list[float],
        project_id: str | None = None,
        limit: int = 5,
    ) -> list:
        """Semantic search over conversation embeddings."""
        import struct

        if project_id:
            rows = session.execute(
                """SELECT ce.conversation_id, ce.embedding FROM conversation_embeddings ce
                   INNER JOIN conversations c ON ce.conversation_id = c.id
                   WHERE c.project_id = ?""",
                (project_id,),
            ).fetchall()
        else:
            rows = session.execute(
                "SELECT conversation_id, embedding FROM conversation_embeddings",
            ).fetchall()

        if not rows:
            return []

        scored = []
        try:
            import numpy as np

            query_vec = np.array(embedding, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = np.frombuffer(blob, dtype=np.float32, count=n)
                vec_norm = np.linalg.norm(vec)
                if vec_norm == 0:
                    continue
                sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
                scored.append((sim, row["conversation_id"]))
        except ImportError:
            import math

            q = embedding
            q_norm = math.sqrt(sum(x * x for x in q))
            if q_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = list(struct.unpack(f"{n}f", blob))  # type: ignore[assignment]
                v_norm = math.sqrt(sum(x * x for x in vec))
                if v_norm == 0:
                    continue
                dot = sum(a * b for a, b in zip(q, vec))
                sim = dot / (q_norm * v_norm)
                scored.append((sim, row["conversation_id"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, conv_id in scored[:limit]:
            conv = self.conversation_get(session, conv_id)
            if conv:
                results.append(conv)
        return results

    def conversation_rate(
        self,
        session: Any,
        conversation_id: str,
        rating: int,
        feedback: str = "",
    ) -> None:
        session.execute(
            "UPDATE conversations SET rating = ?, feedback = ? WHERE id = ?",
            (rating, feedback, conversation_id),
        )

    # --- Corrections ---

    def correction_store(self, session: Any, correction: Any) -> None:
        import struct

        blob = None
        if correction.embedding:
            blob = struct.pack(f"{len(correction.embedding)}f", *correction.embedding)
        # H4: Ensure status column exists (graceful migration for existing DBs)
        try:
            session.execute("SELECT status FROM corrections LIMIT 0")
        except Exception:
            try:
                session.execute("ALTER TABLE corrections ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'")
            except Exception:  # noqa: S110 — ALTER TABLE idempotency check
                pass
        status = getattr(correction, "status", "pending")
        session.execute(
            """INSERT INTO corrections (id, conversation_id, project_id, original_question,
               original_answer, corrected_answer, correction_type, is_applied, embedding, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                correction.id,
                correction.conversation_id,
                correction.project_id,
                correction.original_question,
                correction.original_answer,
                correction.corrected_answer,
                correction.correction_type,
                int(correction.is_applied),
                blob,
                status,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def correction_list(
        self,
        session: Any,
        project_id: str | None = None,
        applied_only: bool = False,
        limit: int = 50,
    ) -> list:
        conditions = []
        params: list = []
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if applied_only:
            conditions.append("is_applied = 1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = session.execute(
            f"SELECT * FROM corrections {where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608 — where from allowlisted column names, values parameterized
            params + [limit],
        ).fetchall()
        return [self._row_to_correction(r) for r in rows]

    def correction_search(
        self,
        session: Any,
        embedding: list[float],
        project_id: str | None = None,
        limit: int = 5,
    ) -> list:
        """Find relevant corrections by embedding similarity."""
        import struct

        if project_id:
            rows = session.execute(
                "SELECT * FROM corrections WHERE project_id = ? AND embedding IS NOT NULL",
                (project_id,),
            ).fetchall()
        else:
            rows = session.execute(
                "SELECT * FROM corrections WHERE embedding IS NOT NULL",
            ).fetchall()

        if not rows:
            return []

        scored = []
        try:
            import numpy as np

            query_vec = np.array(embedding, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = np.frombuffer(blob, dtype=np.float32, count=n)
                vec_norm = np.linalg.norm(vec)
                if vec_norm == 0:
                    continue
                sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
                scored.append((sim, row))
        except ImportError:
            import math

            q = embedding
            q_norm = math.sqrt(sum(x * x for x in q))
            if q_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = list(struct.unpack(f"{n}f", blob))  # type: ignore[assignment]
                v_norm = math.sqrt(sum(x * x for x in vec))
                if v_norm == 0:
                    continue
                dot = sum(a * b for a, b in zip(q, vec))
                sim = dot / (q_norm * v_norm)
                scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._row_to_correction(row) for _, row in scored[:limit]]

    def correction_mark_applied(self, session: Any, correction_id: str) -> None:
        session.execute(
            "UPDATE corrections SET is_applied = 1 WHERE id = ?",
            (correction_id,),
        )

    # --- Cohesive Cache: Similarity Links ---

    def store_similarity_link(self, session: Any, link: SimilarityLink) -> None:
        session.execute(
            """INSERT OR REPLACE INTO similarity_links
               (id, source_cache_id, target_cache_id, similarity, source_query_norm, target_query_norm, strength)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                link.id,
                link.source_cache_id,
                link.target_cache_id,
                link.similarity,
                link.source_query_norm,
                link.target_query_norm,
                link.strength,
            ),
        )

    def get_similarity_links(self, session: Any, cache_id: str, limit: int = 5) -> list[SimilarityLink]:
        rows = session.execute(
            "SELECT * FROM similarity_links WHERE source_cache_id = ? ORDER BY similarity DESC LIMIT ?",
            (cache_id, limit),
        ).fetchall()
        return [self._row_to_similarity_link(row) for row in rows]

    def get_similarity_links_targeting(self, session: Any, cache_id: str, limit: int = 5) -> list[SimilarityLink]:
        rows = session.execute(
            "SELECT * FROM similarity_links WHERE target_cache_id = ? ORDER BY similarity DESC LIMIT ?",
            (cache_id, limit),
        ).fetchall()
        return [self._row_to_similarity_link(row) for row in rows]

    def increment_similarity_link_strength(self, session: Any, link_id: str) -> None:
        session.execute(
            "UPDATE similarity_links SET strength = strength + 1 WHERE id = ?",
            (link_id,),
        )

    def cleanup_weak_links(self, session: Any, max_age_days: int = 30) -> int:
        rows = session.execute(
            """SELECT id FROM similarity_links
               WHERE strength = 0
                 AND datetime(created_at, '+' || ? || ' days') < datetime('now')""",
            (max_age_days,),
        ).fetchall()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        session.execute(f"DELETE FROM similarity_links WHERE id IN ({placeholders})", ids)  # noqa: S608
        return len(ids)

    @staticmethod
    def _row_to_similarity_link(row: Any) -> SimilarityLink:
        strength = 0
        try:
            strength = row["strength"]
        except (IndexError, KeyError):
            pass
        return SimilarityLink(
            id=row["id"],
            source_cache_id=row["source_cache_id"],
            target_cache_id=row["target_cache_id"],
            similarity=row["similarity"],
            source_query_norm=row["source_query_norm"],
            target_query_norm=row["target_query_norm"],
            strength=strength,
            created_at=row["created_at"],
        )

    # --- Cohesive Cache: Atomic Facts ---

    def store_atomic_fact(self, session: Any, fact: AtomicFact) -> None:
        session.execute(
            """INSERT OR REPLACE INTO atomic_facts
               (id, source_cache_id, fact_text, entity, category, confidence, quality_score, serve_count, namespace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact.id,
                fact.source_cache_id,
                fact.fact_text,
                fact.entity,
                fact.category,
                fact.confidence,
                fact.quality_score,
                fact.serve_count,
                fact.namespace_id,
            ),
        )

    def store_atomic_fact_embedding(self, session: Any, fact_id: str, embedding: list[float]) -> None:
        import struct

        blob = struct.pack(f"{len(embedding)}f", *embedding)
        session.execute(
            "INSERT OR REPLACE INTO atomic_fact_embeddings (fact_id, embedding) VALUES (?, ?)",
            (fact_id, blob),
        )

    def search_atomic_facts(
        self,
        session: Any,
        embedding: list[float],
        limit: int = 5,
        namespace_id: str | None = None,
        vector_index: object | None = None,
    ) -> list[tuple[AtomicFact, float]]:
        import struct

        def _lookup_fact(fid: str) -> Any:
            if namespace_id is not None:
                return session.execute(
                    "SELECT * FROM atomic_facts WHERE id = ? AND namespace_id = ?",
                    (fid, namespace_id),
                ).fetchone()
            return session.execute("SELECT * FROM atomic_facts WHERE id = ?", (fid,)).fetchone()

        def _build_fact(fr: Any, s: float) -> tuple[AtomicFact, float]:
            qs = 0.5
            try:
                qs = fr["quality_score"]
            except (IndexError, KeyError):
                pass
            return (
                AtomicFact(
                    id=fr["id"],
                    source_cache_id=fr["source_cache_id"],
                    fact_text=fr["fact_text"],
                    entity=fr["entity"],
                    category=fr["category"],
                    confidence=fr["confidence"],
                    quality_score=qs,
                    serve_count=fr["serve_count"],
                    namespace_id=fr["namespace_id"],
                    created_at=fr["created_at"],
                ),
                s,
            )

        # Fast path: in-memory vector index
        if vector_index is not None and hasattr(vector_index, "search") and hasattr(vector_index, "count"):
            if vector_index.count() > 0:
                raw = vector_index.search(embedding, k=limit * 2)
                results: list[tuple[AtomicFact, float]] = []
                for fact_id, sim in raw:
                    fact_row = _lookup_fact(fact_id)
                    if fact_row:
                        results.append(_build_fact(fact_row, sim))
                    if len(results) >= limit:
                        break
                return results

        # Fallback: brute-force scan
        rows = session.execute("SELECT * FROM atomic_fact_embeddings").fetchall()
        if not rows:
            return []

        scored: list[tuple[float, str]] = []
        try:
            import numpy as np

            query_vec = np.array(embedding, dtype=np.float32)
            query_norm = float(np.linalg.norm(query_vec))
            if query_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                vec = np.frombuffer(blob, dtype=np.float32, count=n)
                vec_norm = float(np.linalg.norm(vec))
                if vec_norm == 0:
                    continue
                sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
                scored.append((sim, row["fact_id"]))
        except ImportError:
            import math

            q_norm = math.sqrt(sum(x * x for x in embedding))
            if q_norm == 0:
                return []
            for row in rows:
                blob = row["embedding"]
                n = len(blob) // 4
                fvec = list(struct.unpack(f"{n}f", blob))
                v_norm = math.sqrt(sum(x * x for x in fvec))
                if v_norm == 0:
                    continue
                dot = sum(a * b for a, b in zip(embedding, fvec))
                sim = dot / (q_norm * v_norm)
                scored.append((sim, row["fact_id"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        results = []
        for sim, fact_id in top:
            fact_row = _lookup_fact(fact_id)
            if fact_row:
                results.append(_build_fact(fact_row, sim))
        return results

    # --- Storage Limits & Eviction ---

    def evict_atomic_facts(self, session: Any, max_facts: int = 500_000) -> int:
        row = session.execute("SELECT COUNT(*) AS cnt FROM atomic_facts").fetchone()
        total = row["cnt"] if row else 0
        if total <= max_facts:
            return 0
        excess = total - max_facts
        session.execute(
            "DELETE FROM atomic_facts WHERE id IN ("
            "SELECT id FROM atomic_facts ORDER BY serve_count ASC, created_at ASC LIMIT ?)",
            (excess,),
        )
        # Orphan cleanup: remove embeddings for deleted facts
        session.execute("DELETE FROM atomic_fact_embeddings WHERE fact_id NOT IN (SELECT id FROM atomic_facts)")
        return excess

    def evict_similarity_links(self, session: Any, max_links: int = 1_000_000) -> int:
        row = session.execute("SELECT COUNT(*) AS cnt FROM similarity_links").fetchone()
        total = row["cnt"] if row else 0
        if total <= max_links:
            return 0
        excess = total - max_links
        session.execute(
            "DELETE FROM similarity_links WHERE id IN ("
            "SELECT id FROM similarity_links ORDER BY strength ASC, created_at ASC LIMIT ?)",
            (excess,),
        )
        return excess

    def cleanup_audit_events(self, session: Any, retention_days: int = 90) -> int:
        result = session.execute(
            "DELETE FROM audit_events WHERE timestamp < datetime('now', '-' || ? || ' days')",
            (retention_days,),
        )
        return result.rowcount if result.rowcount else 0

    def count_documents(self, session: Any, namespace_id: str | None = None) -> int:
        # Documents table does not have namespace_id yet; return global count
        row = session.execute("SELECT COUNT(*) AS cnt FROM documents").fetchone()
        return row["cnt"] if row else 0
