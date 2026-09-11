"""Bitmod programmatic API — the main entry point for using Bitmod as a library.

Usage:
    from bitmod import Bitmod

    bm = Bitmod()                          # Auto-configures from bitmod.yaml / env vars
    bm = Bitmod(config_path="my.yaml")     # Explicit config file
    bm = Bitmod(db_backend="postgresql", db_url="postgresql://...")  # Kwargs override

    # Ingest data
    result = bm.ingest("./documents/")
    result = bm.ingest("Some raw text", title="My Note")

    # Query with intelligent caching
    result = bm.query("What is the refund policy?")
    print(result.answer)
    print(result.cached)         # True if served from cache
    print(result.generation_ms)  # 0 if cached, else LLM generation time

    # Status
    status = bm.status()
    print(status.documents, status.cache_stats)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bitmod.config import _apply_overrides

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """Result of an ingestion operation."""

    document_id: str = ""
    title: str = ""
    source_format: str = ""
    sections: int = 0
    chunks: int = 0
    embedded: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class QueryResult:
    """Result of a query operation."""

    answer: str = ""
    cached: bool = False
    cache_key: str | None = None
    sources: list[dict] = field(default_factory=list)
    model_used: str | None = None
    generation_ms: int = 0
    confidence: float | None = None
    pipeline_trace: list[dict] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    cache_layer: str = ""


@dataclass
class StatusResult:
    """System status snapshot."""

    documents: int = 0
    sections: int = 0
    chunks: int = 0
    cache_stats: dict = field(default_factory=dict)
    db_backend: str = ""
    llm_provider: str = ""
    embedding_provider: str = ""
    vector_store: str = ""


# ---------------------------------------------------------------------------
# Token estimation helpers
# ---------------------------------------------------------------------------


def _estimate_token_usage_cached(answer: str, question: str, model: str = "") -> dict:
    """Token usage estimate for a cache hit (no LLM called)."""
    cached_tokens = max(1, len(answer) // 4)
    est_input = max(1, len(question) // 4)
    tokens_saved = est_input + cached_tokens
    try:
        from bitmod.pricing import estimate_cost, get_updated_at, is_stale

        savings = estimate_cost(est_input, cached_tokens, model)
        updated = get_updated_at()
        stale = is_stale()
    except Exception:
        savings = round(tokens_saved * 0.000003, 6)
        updated = ""
        stale = False
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": cached_tokens,
        "tokens_saved": tokens_saved,
        "estimated_cost": 0.0,
        "estimated_savings": savings,
        "model_priced": model or "",
        "pricing_updated": updated,
        "pricing_stale": stale,
    }


def _estimate_token_usage_generated(
    question: str,
    context: str,
    answer: str,
    model: str = "",
) -> dict:
    """Token usage estimate for an LLM-generated response."""
    input_tokens = max(1, (len(question) + len(context)) // 4)
    output_tokens = max(1, len(answer) // 4)
    total = input_tokens + output_tokens
    try:
        from bitmod.pricing import estimate_cost, get_updated_at, is_stale

        cost = estimate_cost(input_tokens, output_tokens, model)
        updated = get_updated_at()
        stale = is_stale()
    except Exception:
        cost = round(total * 0.000003, 6)
        updated = ""
        stale = False
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "cached_tokens": 0,
        "tokens_saved": 0,
        "estimated_cost": cost,
        "estimated_savings": 0.0,
        "model_priced": model or "",
        "pricing_updated": updated,
        "pricing_stale": stale,
    }


# ---------------------------------------------------------------------------
# Config loading from YAML
# ---------------------------------------------------------------------------


def _load_yaml_config(config_path: str) -> dict[str, Any]:
    """Load a bitmod.yaml config file into a flat dict of overrides."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not installed; cannot load %s", config_path)
        return {}

    path = Path(config_path)
    if not path.is_file():
        return {}

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return {}

    return data


# ---------------------------------------------------------------------------
# Main Bitmod class
# ---------------------------------------------------------------------------


class Bitmod:
    """Main Bitmod interface — ingest, query, and manage your data.

    Automatically configures from (in priority order):
    1. Explicit kwargs passed to __init__
    2. bitmod.yaml in the current directory (or config_path)
    3. Environment variables (BITMOD_*, DATABASE_URL, etc.)

    The database backend defaults to SQLite if nothing is configured,
    so Bitmod works out of the box with zero setup.
    """

    def __init__(self, config_path: str | None = None, **kwargs: Any) -> None:
        from bitmod.config import BitmodConfig

        self._config = BitmodConfig()

        # Layer 1: YAML config file
        yaml_path = config_path or "bitmod.yaml"
        yaml_overrides = _load_yaml_config(yaml_path)
        if yaml_overrides:
            _apply_overrides(self._config, yaml_overrides)

        # Layer 2: Explicit kwargs (highest priority)
        if kwargs:
            _apply_overrides(self._config, kwargs)

        # Lazy-initialized components
        self._backend: Any = None
        self._embedder: Any = None
        self._llm: Any = None
        self._router: Any = None
        self._backup: Any = None
        self._backup_session_id: str | None = None

    @property
    def config(self) -> Any:
        """Access the resolved BitmodConfig."""
        return self._config

    # -- Lazy component initialization --

    def _get_backend(self) -> Any:
        if self._backend is None:
            from bitmod.adapters import get_backend

            self._backend = get_backend(self._config.db)
            self._backend.initialize()
        return self._backend

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            try:
                from bitmod.adapters import get_embedder

                self._embedder = get_embedder(self._config.embedding)
            except Exception as e:
                logger.debug("Embedding provider not available: %s", e)
                self._embedder = None
        return self._embedder

    def _get_llm(self) -> Any:
        if self._llm is None:
            from bitmod.adapters import get_llm

            self._llm = get_llm(self._config.llm)
        return self._llm

    def _get_backup(self) -> Any:
        if self._backup is None:
            from bitmod.backup import BackupManager

            self._backup = BackupManager(
                path=self._config.backup.path,
                compress=self._config.backup.compress,
                max_sessions=self._config.backup.max_sessions,
            )
            self._backup_session_id = self._backup.new_session("auto")
        return self._backup

    def _get_router(self) -> Any:
        if self._router is None:
            from bitmod.router import LLMRouter

            primary = self._get_llm()
            fallback = None
            if self._config.llm.fallback and self._config.llm.fallback != self._config.llm.resolve_provider():
                try:
                    from bitmod.adapters import make_llm

                    fallback = make_llm(self._config.llm.fallback, self._config.llm)
                except Exception:  # noqa: S110 — fallback LLM creation is optional
                    pass
            self._router = LLMRouter(primary, fallback)
        return self._router

    # -------------------------------------------------------------------
    # Ingest
    # -------------------------------------------------------------------

    def ingest(self, path_or_text: str, **kwargs: Any) -> IngestResult:
        """Ingest a file, directory, or raw text into Bitmod.

        Args:
            path_or_text: A file path, directory path, or raw text string.
            **kwargs: Passed to ingest_file/ingest_text (title, document_type,
                      source, jurisdiction, tags, metadata, chunk_config).

        Returns:
            IngestResult with document_id, section/chunk counts, etc.
        """
        from bitmod.ingestion.pipeline import ingest_file, ingest_text

        backend = self._get_backend()
        embedder = self._get_embedder()

        target = Path(path_or_text)

        # Directory: ingest all supported files
        if target.is_dir():
            return self._ingest_directory(target, backend, embedder, **kwargs)

        # File
        if target.is_file():
            result = ingest_file(
                str(target),
                backend=backend,
                embedder=embedder,
                **kwargs,
            )
            ir = IngestResult(
                document_id=result["document_id"],
                title=result["title"],
                source_format=result["source_format"],
                sections=result["sections"],
                chunks=result["chunks"],
                embedded=result["embedded"],
            )
            self._backup_record_ingest(ir)
            return ir

        # Raw text
        title = kwargs.pop("title", "Untitled")
        result = ingest_text(
            path_or_text,
            title=title,
            backend=backend,
            embedder=embedder,
            **kwargs,
        )
        ir = IngestResult(
            document_id=result["document_id"],
            title=result["title"],
            source_format=result["source_format"],
            sections=result["sections"],
            chunks=result["chunks"],
            embedded=result["embedded"],
        )
        self._backup_record_ingest(ir)
        return ir

    def _ingest_directory(
        self,
        directory: Path,
        backend: Any,
        embedder: Any,
        **kwargs: Any,
    ) -> IngestResult:
        """Recursively ingest all supported files in a directory."""
        from bitmod.ingestion.pipeline import ingest_file

        supported_extensions = {
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".html",
            ".htm",
            ".pdf",
            ".docx",
            ".doc",
        }

        total_sections = 0
        total_chunks = 0
        errors: list[str] = []
        count = 0

        for file_path in sorted(directory.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in supported_extensions:
                continue

            try:
                result = ingest_file(
                    str(file_path),
                    backend=backend,
                    embedder=embedder,
                    **kwargs,
                )
                total_sections += result["sections"]
                total_chunks += result["chunks"]
                count += 1
            except Exception as e:
                errors.append(f"{file_path.name}: {e}")

        return IngestResult(
            document_id=f"batch:{count}",
            title=str(directory),
            source_format="directory",
            sections=total_sections,
            chunks=total_chunks,
            embedded=embedder is not None,
            errors=errors,
        )

    # -------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------

    def query(self, question: str, filters: dict | None = None, **kwargs: Any) -> QueryResult:
        """Query Bitmod with intelligent caching.

        Flow:
        1. Compute composite cache key from question + filters
        2. Check cache (exact match with double-verification)
        3. On cache miss: search for relevant context, generate via LLM, store in cache
        4. Return answer with cache status and sources

        Args:
            question: Natural language question.
            filters: Optional filters (jurisdiction, document_type, etc.).
            **kwargs: Additional options (temperature, max_tokens, etc.).

        Returns:
            QueryResult with answer, cache status, sources, and timing.
        """
        from bitmod.cache_engine import (
            compute_answer_key,
            normalize_for_key,
            store_answer,
            try_cache,
        )

        backend = self._get_backend()
        filters = filters or {}

        # Step 1: Try cache
        t0 = time.monotonic_ns() // 1_000_000
        with backend.session() as session:
            cached = try_cache(backend, session, question, filters)
        cache_ms = (time.monotonic_ns() // 1_000_000) - t0

        if cached is not None:
            trace = [
                {"mechanism": "normalization", "action": "DONE", "detail": {}, "elapsed_ms": 0},
                {
                    "mechanism": "exact_cache",
                    "action": "HIT",
                    "detail": {"key": cached.answer_key[:12]},
                    "elapsed_ms": cache_ms,
                },
            ]
            token_usage = _estimate_token_usage_cached(
                cached.answer_text,
                question,
                cached.model_used or "",
            )
            result = QueryResult(
                answer=cached.answer_text,
                cached=True,
                cache_key=cached.answer_key,
                sources=cached.source_sections,
                model_used=cached.model_used,
                generation_ms=0,
                confidence=cached.confidence,
                pipeline_trace=trace,
                token_usage=token_usage,
                cache_layer="exact_cache",
            )
            self._backup_record_query(question, result)
            return result

        # Step 2: Search for relevant context
        search_results = []
        t1 = time.monotonic_ns() // 1_000_000
        with backend.session() as session:
            search_results = backend.hybrid_search(
                session,
                question,
                limit=kwargs.get("limit", 10),
                jurisdiction=filters.get("jurisdiction"),
                document_type=filters.get("document_type"),
            )
        search_ms = (time.monotonic_ns() // 1_000_000) - t1

        # Step 3: Build context and generate via LLM
        context_parts = []
        source_sections = []
        for result in search_results:
            context_parts.append(f"[{result.citation or result.title}]\n{result.snippet}")
            source_sections.append(
                {
                    "section_id": result.section_id,
                    "citation": result.citation,
                    "title": result.title,
                    "score": result.score,
                    # Required by double_verify at serve time; without it the
                    # entry is unverifiable and can never be served.
                    "version_hash": result.version_hash,
                }
            )

        context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        # Generate answer
        start_ms = time.monotonic_ns() // 1_000_000
        answer_text, model_used = self._generate_answer(question, context, **kwargs)
        end_ms = time.monotonic_ns() // 1_000_000
        generation_ms = end_ms - start_ms

        # Step 4: Store in cache
        answer_key = compute_answer_key(question, filters)
        normalized = normalize_for_key(question)

        with backend.session() as session:
            store_answer(
                backend,
                session,
                answer_key=answer_key,
                question_raw=question,
                question_normalized=normalized,
                filters=filters,
                answer_text=answer_text,
                source_sections=source_sections,
                model_used=model_used,
                generation_ms=generation_ms,
            )

        trace = [
            {"mechanism": "normalization", "action": "DONE", "detail": {}, "elapsed_ms": 0},
            {"mechanism": "exact_cache", "action": "MISS", "detail": {}, "elapsed_ms": cache_ms},
            {
                "mechanism": "search",
                "action": "DONE",
                "detail": {"results": len(search_results)},
                "elapsed_ms": search_ms,
            },
            {
                "mechanism": "llm_generation",
                "action": "DONE",
                "detail": {"model": model_used},
                "elapsed_ms": generation_ms,
            },
            {"mechanism": "cache_store", "action": "STORED", "detail": {"key": answer_key[:12]}, "elapsed_ms": 0},
        ]
        token_usage = _estimate_token_usage_generated(question, context, answer_text, model_used or "")

        result = QueryResult(
            answer=answer_text,
            cached=False,
            cache_key=answer_key,
            sources=source_sections,
            model_used=model_used,
            generation_ms=generation_ms,
            pipeline_trace=trace,
            token_usage=token_usage,
            cache_layer="llm_generation",
        )
        self._backup_record_query(question, result)
        return result

    async def aquery(self, question: str, filters: dict | None = None, **kwargs: Any) -> QueryResult:
        """Async version of query() — the primary async entry point.

        Avoids creating a new thread+event loop per call. Use this from
        async contexts (FastAPI, aiohttp, etc.) instead of query().
        """
        import asyncio

        from bitmod.cache_engine import (
            compute_answer_key,
            normalize_for_key,
            store_answer,
            try_cache,
        )

        backend = self._get_backend()
        filters = filters or {}

        # Step 1: Try cache (runs sync DB in thread to avoid blocking)
        t0 = time.monotonic_ns() // 1_000_000

        def _check_cache():
            with backend.session() as session:
                return try_cache(backend, session, question, filters)

        cached = await asyncio.to_thread(_check_cache)
        cache_ms = (time.monotonic_ns() // 1_000_000) - t0

        if cached is not None:
            trace = [
                {"mechanism": "normalization", "action": "DONE", "detail": {}, "elapsed_ms": 0},
                {
                    "mechanism": "exact_cache",
                    "action": "HIT",
                    "detail": {"key": cached.answer_key[:12]},
                    "elapsed_ms": cache_ms,
                },
            ]
            token_usage = _estimate_token_usage_cached(
                cached.answer_text,
                question,
                cached.model_used or "",
            )
            result = QueryResult(
                answer=cached.answer_text,
                cached=True,
                cache_key=cached.answer_key,
                sources=cached.source_sections,
                model_used=cached.model_used,
                generation_ms=0,
                confidence=cached.confidence,
                pipeline_trace=trace,
                token_usage=token_usage,
                cache_layer="exact_cache",
            )
            self._backup_record_query(question, result)
            return result

        # Step 2: Search for relevant context (sync DB in thread)
        t1 = time.monotonic_ns() // 1_000_000

        def _search():
            with backend.session() as session:
                return backend.hybrid_search(
                    session,
                    question,
                    limit=kwargs.get("limit", 10),
                    jurisdiction=filters.get("jurisdiction"),
                    document_type=filters.get("document_type"),
                )

        search_results = await asyncio.to_thread(_search)
        search_ms = (time.monotonic_ns() // 1_000_000) - t1

        # Step 3: Build context and generate via LLM
        context_parts = []
        source_sections = []
        for sr in search_results:
            context_parts.append(f"[{sr.citation or sr.title}]\n{sr.snippet}")
            source_sections.append(
                {
                    "section_id": sr.section_id,
                    "citation": sr.citation,
                    "title": sr.title,
                    "score": sr.score,
                    # Required by double_verify at serve time; without it the
                    # entry is unverifiable and can never be served.
                    "version_hash": sr.version_hash,
                }
            )

        context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        # Generate answer (async — no thread needed)
        start_ms = time.monotonic_ns() // 1_000_000
        answer_text, model_used = await self._agenerate_answer(question, context, **kwargs)
        end_ms = time.monotonic_ns() // 1_000_000
        generation_ms = end_ms - start_ms

        # Step 4: Store in cache (sync DB in thread)
        answer_key = compute_answer_key(question, filters)
        normalized = normalize_for_key(question)

        def _store():
            with backend.session() as session:
                store_answer(
                    backend,
                    session,
                    answer_key=answer_key,
                    question_raw=question,
                    question_normalized=normalized,
                    filters=filters,
                    answer_text=answer_text,
                    source_sections=source_sections,
                    model_used=model_used,
                    generation_ms=generation_ms,
                )

        await asyncio.to_thread(_store)

        trace = [
            {"mechanism": "normalization", "action": "DONE", "detail": {}, "elapsed_ms": 0},
            {"mechanism": "exact_cache", "action": "MISS", "detail": {}, "elapsed_ms": cache_ms},
            {
                "mechanism": "search",
                "action": "DONE",
                "detail": {"results": len(search_results)},
                "elapsed_ms": search_ms,
            },
            {
                "mechanism": "llm_generation",
                "action": "DONE",
                "detail": {"model": model_used},
                "elapsed_ms": generation_ms,
            },
            {"mechanism": "cache_store", "action": "STORED", "detail": {"key": answer_key[:12]}, "elapsed_ms": 0},
        ]
        token_usage = _estimate_token_usage_generated(question, context, answer_text, model_used or "")

        result = QueryResult(
            answer=answer_text,
            cached=False,
            cache_key=answer_key,
            sources=source_sections,
            model_used=model_used,
            generation_ms=generation_ms,
            pipeline_trace=trace,
            token_usage=token_usage,
            cache_layer="llm_generation",
        )
        self._backup_record_query(question, result)
        return result

    async def _agenerate_answer(self, question: str, context: str, **kwargs: Any) -> tuple[str, str]:
        """Generate an answer using the configured LLM provider (async).

        This is the primary async entry point. Returns (answer_text, model_used).
        """
        from bitmod.interfaces.llm import LLMMessage

        system_prompt = (
            "You are a helpful assistant powered by Bitmod. "
            "Answer the user's question based on the provided context. "
            "If the context doesn't contain relevant information, say so clearly. "
            "Cite your sources when possible."
        )

        messages = [LLMMessage(role="system", content=system_prompt)]

        if context:
            messages.append(
                LLMMessage(
                    role="user",
                    content=f"Context:\n{context}\n\nQuestion: {question}",
                )
            )
        else:
            messages.append(LLMMessage(role="user", content=question))

        try:
            router = self._get_router()
            temperature = kwargs.get("temperature", 0.0)
            max_tokens = kwargs.get("max_tokens", 4096)

            response = await router.generate(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.content, response.model or self._config.llm.primary_model

        except Exception as e:
            logger.error("LLM generation failed: %s: %s", type(e).__name__, e)
            if context:
                return (
                    "I found relevant information but could not generate a full answer "
                    "(LLM temporarily unavailable). "
                    f"Here are the relevant excerpts:\n\n{context}",
                    "fallback:context-only",
                )
            return (
                "Unable to generate an answer (LLM temporarily unavailable). Please try again later.",
                "fallback:none",
            )

    def _generate_answer(self, question: str, context: str, **kwargs: Any) -> tuple[str, str]:
        """Generate an answer using the configured LLM provider (sync wrapper).

        Prefers _agenerate_answer in async contexts. Falls back to asyncio.run
        when called from a synchronous context.
        """
        import asyncio

        try:
            asyncio.get_running_loop()
            # We're in an async context — caller should use aquery() instead.
            # Bridge via a background thread to avoid blocking the event loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self._agenerate_answer(question, context, **kwargs),
                ).result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run directly
            return asyncio.run(self._agenerate_answer(question, context, **kwargs))

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> StatusResult:
        """Get system status: document counts, cache stats, provider config.

        Returns:
            StatusResult with all relevant system information.
        """
        backend = self._get_backend()

        with backend.session() as session:
            cache_stats = backend.cache_stats(session)

            # Get document counts
            doc_stats = {}
            if hasattr(backend, "document_stats"):
                doc_stats = backend.document_stats(session)

        totals = doc_stats.get("totals", {})

        return StatusResult(
            documents=totals.get("document_count", 0),
            sections=totals.get("total_sections", 0),
            chunks=totals.get("total_chunks", 0),
            cache_stats=cache_stats,
            db_backend=self._config.db.backend,
            llm_provider=self._config.llm.resolve_provider(),
            embedding_provider=self._config.embedding.provider,
            vector_store=self._config.vector_store.store or "(using db backend)",
        )

    # -------------------------------------------------------------------
    # Cache Stats
    # -------------------------------------------------------------------

    def get_cache_stats(self) -> dict:
        """Get cache performance statistics.

        Returns:
            Dict with total_entries, valid_entries, hit_rate,
            total_compute_saved_ms, avg_generation_ms, etc.
        """
        backend = self._get_backend()
        with backend.session() as session:
            return backend.cache_stats(session)  # type: ignore[no-any-return]

    # -------------------------------------------------------------------
    # Admin Metrics
    # -------------------------------------------------------------------

    def admin_metrics(self) -> dict:
        """Get comprehensive admin metrics for the dashboard.

        Returns:
            Dict with cache, documents, comparison, providers, accuracy sections.
        """
        backend = self._get_backend()

        with backend.session() as session:
            cache_stats = backend.cache_stats(session)

            # Recent queries
            recent = []
            if hasattr(backend, "recent_cached_queries"):
                recent = backend.recent_cached_queries(session, limit=20)

            # Documents
            doc_stats = {}
            if hasattr(backend, "document_stats"):
                doc_stats = backend.document_stats(session)

            # Comparison data
            comparison_queries = []
            if hasattr(backend, "cache_model_comparison"):
                comparison_queries = backend.cache_model_comparison(session)

        # Build cache section
        cache = {**cache_stats, "recent_queries": recent}

        # Build documents section
        raw_docs = doc_stats.get("documents", [])
        documents = {
            "documents": [
                {
                    "title": d.get("title", "Untitled"),
                    "format": d.get("source_format", "text"),
                    "sections": d.get("section_count", 0),
                    "chunks": d.get("chunk_count", 0),
                    "created_at": d.get("created_at", ""),
                }
                for d in raw_docs
            ],
            "totals": doc_stats.get(
                "totals",
                {
                    "document_count": len(raw_docs),
                    "total_sections": 0,
                    "total_chunks": 0,
                },
            ),
        }

        # Build comparison section (cache_model_comparison already returns the right shape)
        total_without = sum(q.get("total_without_cache_ms", 0) for q in comparison_queries)
        total_with = sum(q.get("total_with_cache_ms", 0) for q in comparison_queries)

        comparison = {
            "queries": comparison_queries,
            "total_without": total_without,
            "total_with": total_with,
            "savings_factor": round(total_without / total_with, 1) if total_with > 0 else 1,
        }

        # Providers — list every integration, mark active ones
        active_llm = self._config.llm.resolve_provider()
        fallback_llm = self._config.llm.fallback
        active_db = self._config.db.backend
        active_embed = self._config.embedding.provider
        active_vec = self._config.vector_store.store

        all_llms = [
            ("anthropic", "Claude"),
            ("openai", "GPT-4 / ChatGPT"),
            ("azure_openai", "Azure OpenAI"),
            ("gemini", "Google Gemini"),
            ("ollama", "Ollama (local)"),
            ("bedrock", "AWS Bedrock"),
            ("openai_compatible", "OpenAI-Compatible"),
            ("xai", "Grok (xAI)"),
            ("mistral", "Mistral"),
            ("perplexity", "Perplexity"),
            ("openrouter", "OpenRouter"),
            ("huggingface", "HuggingFace"),
        ]
        all_dbs = [
            ("sqlite", "SQLite"),
            ("postgresql", "PostgreSQL + pgvector"),
            ("mysql", "MySQL"),
            ("mongodb", "MongoDB"),
        ]
        all_embeds = [
            ("ollama", "Ollama (local)"),
            ("local", "Sentence Transformers"),
            ("openai", "OpenAI Embeddings"),
            ("cohere", "Cohere Embed"),
        ]
        all_vecs = [
            ("chroma", "ChromaDB"),
            ("qdrant", "Qdrant"),
            ("pinecone", "Pinecone"),
        ]

        def _provider_list(all_items: list, active: str, label: str = "active", fallback: str | None = None) -> list:
            out = []
            for key, display in all_items:
                status = "available"
                if key == active:
                    status = label
                elif fallback and key == fallback:
                    status = "fallback"
                out.append({"name": key, "display": display, "status": status})
            return out

        providers = {
            "llm": _provider_list(all_llms, active_llm, "active", fallback_llm),
            "database": _provider_list(all_dbs, active_db),
            "embeddings": _provider_list(all_embeds, active_embed),
            "vector_store": _provider_list(all_vecs, active_vec or ""),
        }

        # Accuracy (placeholder — populated when scoring tests are run)
        accuracy = {
            "overall_score": 0,
            "total_scored_batches": 0,
            "batches": [],
        }

        return {
            "cache": cache,
            "documents": documents,
            "comparison": comparison,
            "providers": providers,
            "accuracy": accuracy,
        }

    # -------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------

    # -------------------------------------------------------------------
    # Backup helpers
    # -------------------------------------------------------------------

    def _backup_record_query(self, question: str, result: QueryResult) -> None:
        """Record a query to the backup journal."""
        backup = self._get_backup()
        if backup is None or self._backup_session_id is None:
            return
        try:
            backup.record_query(
                self._backup_session_id,
                question=question,
                answer=result.answer,
                cached=result.cached,
                model_used=result.model_used or "",
                generation_ms=result.generation_ms,
                sources=result.sources,
                cache_layer=result.cache_layer,
                pipeline_trace=result.pipeline_trace,
                token_usage=result.token_usage,
                confidence=result.confidence,
            )
        except Exception as e:
            logger.debug("Backup record failed: %s", e)

    def _backup_record_ingest(self, result: IngestResult) -> None:
        """Record an ingestion to the backup journal if backup is enabled."""
        backup = self._get_backup()
        if backup is None or self._backup_session_id is None:
            return
        try:
            backup.record_ingest(
                self._backup_session_id,
                document_id=result.document_id,
                title=result.title,
                sections=result.sections,
                chunks=result.chunks,
            )
        except Exception as e:
            logger.debug("Backup record failed: %s", e)

    def get_backup_context(self, limit: int = 50, include_sources: bool = False) -> str:
        """Get the backup context string for the current session.

        This returns a formatted Q&A history that can be fed into an LLM
        prompt as persistent context.
        """
        backup = self._get_backup()
        if backup is None or self._backup_session_id is None:
            return ""
        return backup.build_context(  # type: ignore[no-any-return]
            self._backup_session_id,
            limit=limit,
            include_sources=include_sources,
        )

    def close(self) -> None:
        """Release resources (database connections, etc.)."""
        if self._backend is not None:
            conn = getattr(self._backend, "_conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: S110 — best-effort connection cleanup
                    pass
            self._backend = None
        self._embedder = None
        self._llm = None
        self._router = None

    def __enter__(self) -> Bitmod:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"Bitmod(db={self._config.db.backend!r}, "
            f"llm={self._config.llm.resolve_provider()!r}, "
            f"embedding={self._config.embedding.provider!r})"
        )
