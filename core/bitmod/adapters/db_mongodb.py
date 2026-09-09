"""MongoDB database backend — pymongo."""

from __future__ import annotations

import logging
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
    from pymongo import MongoClient  # noqa: E402
except ImportError as e:
    raise ImportError("MongoDB backend requires: pip install bitmod[mongodb]") from e


class MongoDBBackend(DatabaseBackend):
    def __init__(self, url: str = "mongodb://localhost:27017", db_name: str = "bitmod"):
        self._client: Any = MongoClient(url)
        self._db = self._client[db_name]

    def initialize(self) -> None:
        self._db.documents.create_index("id", unique=True)
        self._db.sections.create_index("id", unique=True)
        self._db.sections.create_index("document_id")
        self._db.sections.create_index([("text_content", "text")])
        self._db.chunks.create_index("id", unique=True)
        self._db.chunks.create_index("section_id")
        self._db.answer_cache.create_index("answer_key", unique=True)
        self._db.answer_cache.create_index("is_valid")
        self._db.answer_cache.create_index("created_at")

        # Content blocks
        self._db.content_blocks.create_index("id", unique=True)
        self._db.content_blocks.create_index("section_id")
        self._db.content_blocks.create_index([("section_id", 1), ("compression", 1)])

        # Section tags — compound unique on (section_id, tag_key, tag_value)
        self._db.section_tags.create_index(
            [("section_id", 1), ("tag_key", 1), ("tag_value", 1)],
            unique=True,
        )
        self._db.section_tags.create_index([("tag_key", 1), ("tag_value", 1)])

        # Section relationships — compound unique on (section_a_id, section_b_id, relationship)
        self._db.section_relationships.create_index(
            [("section_a_id", 1), ("section_b_id", 1), ("relationship", 1)],
            unique=True,
        )
        self._db.section_relationships.create_index("section_a_id")
        self._db.section_relationships.create_index("section_b_id")

        # Cache embeddings
        self._db.cache_embeddings.create_index("cache_id", unique=True)

    @contextmanager
    def session(self) -> Generator[Any, None, None]:
        # MongoDB doesn't require explicit sessions for single-doc ops
        yield self._db

    def store_document(self, session: Any, doc: DocumentRecord) -> None:
        session.documents.insert_one(
            {
                "id": doc.id,
                "document_type": doc.document_type,
                "source": doc.source,
                "title": doc.title,
                "jurisdiction": doc.jurisdiction,
                "source_format": doc.source_format,
                "metadata": doc.metadata,
                "tags": doc.tags,
                "created_at": datetime.now(timezone.utc),
            }
        )

    def store_section(self, session: Any, section: SectionRecord) -> None:
        session.sections.insert_one(
            {
                "id": section.id,
                "document_id": section.document_id,
                "text_content": section.text_content,
                "version_hash": section.version_hash,
                "citation": section.citation,
                "section_number": section.section_number,
                "section_title": section.section_title,
                "hierarchy_path": section.hierarchy_path,
                "is_current": section.is_current,
                "metadata": section.metadata,
                "tags": section.tags,
                "created_at": datetime.now(timezone.utc),
            }
        )

    def get_section(self, session: Any, section_id: str) -> SectionRecord | None:
        doc = session.sections.find_one({"id": section_id, "is_current": True})
        return self._doc_to_section(doc) if doc else None

    def get_section_by_citation(self, session: Any, citation: str) -> SectionRecord | None:
        doc = session.sections.find_one({"citation": citation, "is_current": True})
        return self._doc_to_section(doc) if doc else None

    def get_section_version_hashes(self, session: Any, section_ids: list[str]) -> dict[str, str]:
        if not section_ids:
            return {}
        docs = session.sections.find({"id": {"$in": section_ids}, "is_current": True}, {"id": 1, "version_hash": 1})
        return {d["id"]: d["version_hash"] for d in docs}

    def get_section_version_hash(self, session: Any, section_id: str) -> str | None:
        doc = session.sections.find_one({"id": section_id, "is_current": True}, {"version_hash": 1})
        return doc["version_hash"] if doc else None

    def store_chunk(self, session: Any, chunk: ChunkRecord) -> None:
        session.chunks.insert_one(
            {
                "id": chunk.id,
                "section_id": chunk.section_id,
                "chunk_index": chunk.chunk_index,
                "text_content": chunk.text_content,
                "embedding": chunk.embedding,
                "document_type": chunk.document_type,
                "jurisdiction": chunk.jurisdiction,
                "char_offset": chunk.char_offset,
            }
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
        if embedding is not None:
            # TODO: Implement vector search using MongoDB Atlas $vectorSearch or
            # a local cosine-similarity fallback over stored embeddings.
            logger.warning(
                "MongoDB hybrid_search: embedding parameter provided but vector "
                "search is not yet implemented. Falling back to text-only search."
            )

        pipeline: list[dict] = [{"$match": {"$text": {"$search": query}, "is_current": True}}]
        if jurisdiction:
            pipeline[0]["$match"]["jurisdiction"] = jurisdiction
        if document_type:
            pipeline[0]["$match"]["document_type"] = document_type
        pipeline.extend(
            [
                {"$addFields": {"score": {"$meta": "textScore"}}},
                {"$sort": {"score": -1}},
                {"$limit": limit},
            ]
        )
        results = []
        for doc in session.sections.aggregate(pipeline):
            results.append(
                SearchResult(
                    section_id=doc["id"],
                    citation=doc.get("citation", ""),
                    title=doc.get("section_title", ""),
                    snippet=doc["text_content"][:300],
                    score=doc.get("score", 0),
                    version_hash=doc.get("version_hash", ""),
                )
            )
        return results

    def cache_lookup(self, session: Any, answer_key: str) -> AnswerCacheRecord | None:
        doc = session.answer_cache.find_one({"answer_key": answer_key, "is_valid": True})
        return self._doc_to_cache(doc) if doc else None

    def cache_store(self, session: Any, record: AnswerCacheRecord) -> None:
        # Delete any existing row with the same answer_key (handles re-caching
        # after invalidation). Must also clean up cache_embeddings.
        old = session.answer_cache.find_one({"answer_key": record.answer_key}, {"id": 1})
        if old:
            session.cache_embeddings.delete_one({"cache_id": old["id"]})
            session.answer_cache.delete_one({"id": old["id"]})
        session.answer_cache.insert_one(
            {
                "id": record.id,
                "answer_key": record.answer_key,
                "question_raw": record.question_raw,
                "question_normalized": record.question_normalized,
                "filters": record.filters,
                "answer_text": record.answer_text,
                "source_sections": record.source_sections,
                "model_used": record.model_used,
                "generation_ms": record.generation_ms,
                "confidence": record.confidence,
                "is_valid": True,
                "serve_count": 0,
                "created_at": datetime.now(timezone.utc),
            }
        )

    def cache_invalidate(self, session: Any, answer_id: str, reason: str) -> None:
        session.answer_cache.update_one(
            {"id": answer_id},
            {"$set": {"is_valid": False, "invalidated_at": datetime.now(timezone.utc), "invalidation_reason": reason}},
        )

    def cache_clear_all(self, session: Any, reason: str = "Manual clear") -> int:
        result = session.answer_cache.update_many(
            {"is_valid": True},
            {"$set": {"is_valid": False, "invalidated_at": datetime.now(timezone.utc), "invalidation_reason": reason}},
        )
        return int(result.modified_count)

    def cache_invalidate_by_section(self, session: Any, section_id: str) -> int:
        result = session.answer_cache.update_many(
            {"is_valid": True, "source_sections.section_id": section_id},
            {
                "$set": {
                    "is_valid": False,
                    "invalidated_at": datetime.now(timezone.utc),
                    "invalidation_reason": f"Source section {section_id} changed",
                }
            },
        )
        return result.modified_count  # type: ignore[no-any-return]

    def cache_increment_serve(self, session: Any, answer_id: str) -> None:
        session.answer_cache.update_one({"id": answer_id}, {"$inc": {"serve_count": 1}})

    def cache_stats(self, session: Any) -> dict:
        total = session.answer_cache.count_documents({})
        valid = session.answer_cache.count_documents({"is_valid": True})
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "serves": {"$sum": "$serve_count"},
                    "avg_ms": {"$avg": "$generation_ms"},
                }
            }
        ]
        agg = list(session.answer_cache.aggregate(pipeline))
        serves = agg[0]["serves"] if agg else 0
        avg_ms = agg[0]["avg_ms"] if agg else 0

        # Total compute saved: generation_ms * serve_count for valid entries
        saved_pipeline = [
            {"$match": {"is_valid": True}},
            {
                "$group": {
                    "_id": None,
                    "saved": {
                        "$sum": {"$multiply": ["$generation_ms", "$serve_count"]},
                    },
                }
            },
        ]
        saved_agg = list(session.answer_cache.aggregate(saved_pipeline))
        total_saved_ms = saved_agg[0]["saved"] if saved_agg else 0

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
        # MongoDB Atlas Search has fuzzy; for standalone, use regex approximation
        docs = session.answer_cache.find(
            {"is_valid": True, "question_normalized": {"$regex": normalized_query[:20], "$options": "i"}},
        ).limit(max_results)
        return [self._doc_to_cache(d) for d in docs]

    def _doc_to_section(self, doc: dict) -> SectionRecord:
        return SectionRecord(
            id=doc["id"],
            document_id=doc["document_id"],
            text_content=doc["text_content"],
            version_hash=doc["version_hash"],
            citation=doc.get("citation"),
            section_number=doc.get("section_number"),
            section_title=doc.get("section_title"),
            hierarchy_path=doc.get("hierarchy_path"),
            is_current=doc.get("is_current", True),
            metadata=doc.get("metadata", {}),
            tags=doc.get("tags"),
        )

    def _doc_to_cache(self, doc: dict) -> AnswerCacheRecord:
        return AnswerCacheRecord(
            id=doc["id"],
            answer_key=doc["answer_key"],
            question_raw=doc["question_raw"],
            question_normalized=doc["question_normalized"],
            filters=doc.get("filters", {}),
            answer_text=doc["answer_text"],
            source_sections=doc.get("source_sections", []),
            model_used=doc["model_used"],
            generation_ms=doc["generation_ms"],
            confidence=doc.get("confidence"),
            is_valid=doc.get("is_valid", True),
            serve_count=doc.get("serve_count", 0),
        )

    def _doc_to_block(self, doc: dict) -> ContentBlock:
        return ContentBlock(
            id=doc["id"],
            section_id=doc["section_id"],
            compression=doc["compression"],
            content=doc["content"],
            version_hash=doc.get("version_hash", ""),
            token_count=doc.get("token_count", 0),
        )

    def _doc_to_tag(self, doc: dict) -> SectionTag:
        return SectionTag(
            section_id=doc["section_id"],
            tag_key=doc["tag_key"],
            tag_value=doc["tag_value"],
            confidence=doc.get("confidence", 1.0),
            source=doc.get("source", "rule"),
        )

    def _doc_to_relationship(self, doc: dict) -> SectionRelationship:
        return SectionRelationship(
            section_a_id=doc["section_a_id"],
            section_b_id=doc["section_b_id"],
            relationship=doc["relationship"],
            strength=doc.get("strength", 1.0),
            source=doc.get("source", "co_retrieval"),
            hit_count=doc.get("hit_count", 1),
        )

    def _doc_to_document(self, doc: dict) -> DocumentRecord:
        return DocumentRecord(
            id=doc["id"],
            document_type=doc.get("document_type", ""),
            source=doc.get("source", ""),
            title=doc.get("title", ""),
            jurisdiction=doc.get("jurisdiction"),
            source_format=doc.get("source_format", ""),
            metadata=doc.get("metadata", {}),
            tags=doc.get("tags"),
        )

    # --- Content Blocks ---

    def store_block(self, session: Any, block: ContentBlock) -> None:
        session.content_blocks.update_one(
            {"id": block.id},
            {
                "$set": {
                    "id": block.id,
                    "section_id": block.section_id,
                    "compression": block.compression,
                    "content": block.content,
                    "version_hash": block.version_hash,
                    "token_count": block.token_count,
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    def get_blocks(
        self,
        session: Any,
        section_id: str,
        compression: str | None = None,
    ) -> list[ContentBlock]:
        query: dict[str, Any] = {"section_id": section_id}
        if compression:
            query["compression"] = compression
        docs = session.content_blocks.find(query)
        return [self._doc_to_block(d) for d in docs]

    def delete_chunks_by_section(self, session: Any, section_id: str) -> int:
        result = session.chunks.delete_many({"section_id": section_id})
        return result.deleted_count  # type: ignore[no-any-return]

    def invalidate_blocks(self, session: Any, section_id: str) -> int:
        result = session.content_blocks.delete_many({"section_id": section_id})
        return result.deleted_count  # type: ignore[no-any-return]

    # --- Section Tags ---

    def store_tag(self, session: Any, tag: SectionTag) -> None:
        session.section_tags.update_one(
            {"section_id": tag.section_id, "tag_key": tag.tag_key, "tag_value": tag.tag_value},
            {
                "$set": {
                    "section_id": tag.section_id,
                    "tag_key": tag.tag_key,
                    "tag_value": tag.tag_value,
                    "confidence": tag.confidence,
                    "source": tag.source,
                }
            },
            upsert=True,
        )

    def get_tags(self, session: Any, section_id: str) -> list[SectionTag]:
        docs = session.section_tags.find({"section_id": section_id})
        return [self._doc_to_tag(d) for d in docs]

    def search_by_tag(
        self,
        session: Any,
        tag_key: str,
        tag_value: str,
        limit: int = 20,
    ) -> list[SectionRecord]:
        # Find section IDs matching the tag
        tag_docs = session.section_tags.find(
            {"tag_key": tag_key, "tag_value": tag_value},
            {"section_id": 1},
        ).limit(limit)
        section_ids = [d["section_id"] for d in tag_docs]
        if not section_ids:
            return []
        # Fetch the actual sections (current only)
        sections = session.sections.find(
            {"id": {"$in": section_ids}, "is_current": True},
        ).limit(limit)
        return [self._doc_to_section(s) for s in sections]

    # --- Section Relationships ---

    def store_relationship(self, session: Any, rel: SectionRelationship) -> None:
        session.section_relationships.update_one(
            {
                "section_a_id": rel.section_a_id,
                "section_b_id": rel.section_b_id,
                "relationship": rel.relationship,
            },
            {
                "$set": {
                    "section_a_id": rel.section_a_id,
                    "section_b_id": rel.section_b_id,
                    "relationship": rel.relationship,
                    "strength": rel.strength,
                    "source": rel.source,
                    "hit_count": rel.hit_count,
                }
            },
            upsert=True,
        )

    def get_relationships(self, session: Any, section_id: str) -> list[SectionRelationship]:
        docs = session.section_relationships.find(
            {
                "$or": [
                    {"section_a_id": section_id},
                    {"section_b_id": section_id},
                ],
            }
        )
        return [self._doc_to_relationship(d) for d in docs]

    def increment_relationship(
        self,
        session: Any,
        section_a_id: str,
        section_b_id: str,
        relationship: str,
    ) -> None:
        result = session.section_relationships.update_one(
            {
                "section_a_id": section_a_id,
                "section_b_id": section_b_id,
                "relationship": relationship,
            },
            {"$inc": {"hit_count": 1}},
        )
        if result.matched_count == 0:
            # Insert new relationship with hit_count=1
            session.section_relationships.insert_one(
                {
                    "section_a_id": section_a_id,
                    "section_b_id": section_b_id,
                    "relationship": relationship,
                    "strength": 1.0,
                    "source": "co_retrieval",
                    "hit_count": 1,
                }
            )

    # --- Semantic Cache (embedding-based) ---

    def cache_store_embedding(self, session: Any, cache_id: str, embedding: list[float]) -> None:
        """Store a query embedding alongside a cache entry."""
        session.cache_embeddings.update_one(
            {"cache_id": cache_id},
            {"$set": {"cache_id": cache_id, "embedding": embedding}},
            upsert=True,
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
        # Join with answer_cache to filter valid-only, ordered by created_at desc
        match_filter: dict[str, Any] = {"cache.is_valid": True}
        if namespace_id:
            match_filter["cache.namespace_id"] = namespace_id
        pipeline = [
            {
                "$lookup": {
                    "from": "answer_cache",
                    "localField": "cache_id",
                    "foreignField": "id",
                    "as": "cache",
                }
            },
            {"$unwind": "$cache"},
            {"$match": match_filter},
            {"$sort": {"cache.created_at": -1}},
            {"$limit": limit},
            {"$project": {"cache_id": 1, "embedding": 1}},
        ]
        results = []
        for doc in session.cache_embeddings.aggregate(pipeline):
            results.append((doc["cache_id"], doc["embedding"]))
        return results

    def cache_lookup_by_id(self, session: Any, cache_id: str) -> AnswerCacheRecord | None:
        """Look up a cached answer by its record ID."""
        doc = session.answer_cache.find_one({"id": cache_id, "is_valid": True})
        return self._doc_to_cache(doc) if doc else None

    # --- Re-ingestion support ---

    def get_sections_for_document(self, session: Any, document_id: str) -> list[SectionRecord]:
        """Get all current sections for a document."""
        docs = session.sections.find(
            {"document_id": document_id, "is_current": True},
        ).sort("section_number", 1)
        return [self._doc_to_section(d) for d in docs]

    def find_document_by_title_and_source(
        self,
        session: Any,
        title: str,
        source: str,
    ) -> DocumentRecord | None:
        """Find an existing document by title + source."""
        doc = session.documents.find_one({"title": title, "source": source})
        return self._doc_to_document(doc) if doc else None

    def update_section_content(
        self,
        session: Any,
        section_id: str,
        text_content: str,
        version_hash: str,
    ) -> None:
        """Update a section's text content and version hash in-place."""
        session.sections.update_one(
            {"id": section_id},
            {"$set": {"text_content": text_content, "version_hash": version_hash}},
        )

    def mark_section_not_current(self, session: Any, section_id: str) -> None:
        """Mark a section as no longer current."""
        session.sections.update_one(
            {"id": section_id},
            {"$set": {"is_current": False}},
        )

    # --- Admin dashboard / proxy parity ---

    def recent_cached_queries(self, session: Any, limit: int = 20) -> list[dict]:
        """Return the most recent cached queries with full detail."""
        docs = (
            session.answer_cache.find(
                {},
                {
                    "question_raw": 1,
                    "generation_ms": 1,
                    "serve_count": 1,
                    "is_valid": 1,
                    "model_used": 1,
                    "created_at": 1,
                    "confidence": 1,
                    "answer_key": 1,
                },
            )
            .sort("created_at", -1)
            .limit(limit)
        )
        return [
            {
                "question": doc["question_raw"],
                "generation_ms": doc["generation_ms"],
                "serve_count": doc.get("serve_count", 0),
                "is_valid": doc.get("is_valid", True),
                "model_used": doc["model_used"],
                "created_at": doc.get("created_at"),
                "confidence": doc.get("confidence"),
                "answer_key": doc["answer_key"],
            }
            for doc in docs
        ]

    def cache_model_comparison(self, session: Any) -> list[dict]:
        """Return cost comparison data for cached queries with serves > 0."""
        docs = (
            session.answer_cache.find(
                {"serve_count": {"$gt": 0}, "is_valid": True},
                {"question_raw": 1, "generation_ms": 1, "serve_count": 1, "model_used": 1},
            )
            .sort("serve_count", -1)
            .limit(50)
        )
        cached_serve_ms = 0.5
        return [
            {
                "query": doc["question_raw"],
                "first_gen_ms": doc["generation_ms"],
                "cached_serve_ms": cached_serve_ms,
                "serves": doc["serve_count"],
                "model_used": doc["model_used"],
                "total_without_cache_ms": doc["generation_ms"] * (1 + doc["serve_count"]),
                "total_with_cache_ms": doc["generation_ms"] + (cached_serve_ms * doc["serve_count"]),
                "savings_ms": doc["generation_ms"] * doc["serve_count"] - (cached_serve_ms * doc["serve_count"]),
            }
            for doc in docs
        ]

    def document_stats(self, session: Any) -> dict:
        """Return document-level statistics and listing."""
        pipeline = [
            {
                "$lookup": {
                    "from": "sections",
                    "let": {"doc_id": "$id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$document_id", "$$doc_id"]},
                                        {"$eq": ["$is_current", True]},
                                    ]
                                }
                            }
                        },
                    ],
                    "as": "secs",
                }
            },
            {
                "$lookup": {
                    "from": "chunks",
                    "let": {"sec_ids": "$secs.id"},
                    "pipeline": [
                        {"$match": {"$expr": {"$in": ["$section_id", "$$sec_ids"]}}},
                    ],
                    "as": "chnks",
                }
            },
            {
                "$addFields": {
                    "section_count": {"$size": "$secs"},
                    "chunk_count": {"$size": "$chnks"},
                }
            },
            {"$sort": {"created_at": -1}},
            {
                "$project": {
                    "id": 1,
                    "title": 1,
                    "source_format": 1,
                    "document_type": 1,
                    "source": 1,
                    "jurisdiction": 1,
                    "section_count": 1,
                    "chunk_count": 1,
                    "created_at": 1,
                }
            },
        ]

        documents = []
        total_sections = 0
        total_chunks = 0
        for doc in session.documents.aggregate(pipeline):
            sc = doc.get("section_count", 0)
            cc = doc.get("chunk_count", 0)
            total_sections += sc
            total_chunks += cc
            documents.append(
                {
                    "id": doc["id"],
                    "title": doc.get("title", ""),
                    "source_format": doc.get("source_format", ""),
                    "document_type": doc.get("document_type", ""),
                    "source": doc.get("source", ""),
                    "jurisdiction": doc.get("jurisdiction"),
                    "section_count": sc,
                    "chunk_count": cc,
                    "created_at": doc.get("created_at"),
                }
            )

        return {
            "documents": documents,
            "totals": {
                "document_count": len(documents),
                "total_sections": total_sections,
                "total_chunks": total_chunks,
            },
        }

    # --- Audit Events ---

    def store_audit_event(self, session: Any, record: dict) -> None:
        session.audit_events.insert_one(record)

    # --- API Key Management ---

    def store_api_key(self, session: Any, record: dict) -> None:
        session.api_keys.insert_one(
            {
                "id": record["id"],
                "key_hash": record["key_hash"],
                "key_preview": record["key_preview"],
                "name": record["name"],
                "scopes": record["scopes"],
                "owner": record["owner"],
                "is_active": record["is_active"],
                "created_at": record["created_at"],
                "last_used_at": None,
                "expires_at": record.get("expires_at"),
                "email": record.get("email"),
            }
        )

    def lookup_api_key(self, session: Any, key_hash: str) -> dict | None:
        doc = session.api_keys.find_one({"key_hash": key_hash})
        if doc is None:
            return None
        return {
            "id": doc["id"],
            "key_hash": doc["key_hash"],
            "key_preview": doc["key_preview"],
            "name": doc["name"],
            "scopes": doc["scopes"],
            "owner": doc["owner"],
            "is_active": doc.get("is_active", True),
            "created_at": doc["created_at"],
            "last_used_at": doc.get("last_used_at"),
            "expires_at": doc.get("expires_at"),
            "email": doc.get("email"),
        }

    def list_api_keys(self, session: Any, owner: str | None = None) -> list[dict]:
        query: dict = {}
        if owner:
            query["owner"] = owner
        docs = session.api_keys.find(query).sort("created_at", -1)
        return [
            {
                "id": d["id"],
                "key_hash": d["key_hash"],
                "key_preview": d["key_preview"],
                "name": d["name"],
                "scopes": d["scopes"],
                "owner": d["owner"],
                "is_active": d.get("is_active", True),
                "created_at": d["created_at"],
                "last_used_at": d.get("last_used_at"),
                "expires_at": d.get("expires_at"),
                "email": d.get("email"),
            }
            for d in docs
        ]

    def revoke_api_key(self, session: Any, key_id: str) -> bool:
        result = session.api_keys.update_one(
            {"id": key_id, "is_active": True},
            {"$set": {"is_active": False}},
        )
        return result.modified_count > 0  # type: ignore[no-any-return]

    def touch_api_key(self, session: Any, key_id: str) -> None:
        session.api_keys.update_one(
            {"id": key_id},
            {"$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}},
        )
