"""Prometheus metrics for Bitmod.

Provides request tracking, cache hit/miss counters, LLM call metrics,
and a FastAPI middleware for automatic instrumentation.

All metrics are optional — if prometheus_client is not installed,
the module exports no-op stubs so callers never need to guard imports.
"""

import logging
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import prometheus_client; fall back to no-op stubs
# ---------------------------------------------------------------------------

_PROMETHEUS_AVAILABLE = False

try:
    from prometheus_client import (  # noqa: F401
        CONTENT_TYPE_LATEST,
        REGISTRY,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    pass


def prometheus_available() -> bool:
    """Return True if prometheus_client is installed."""
    return _PROMETHEUS_AVAILABLE


# ---------------------------------------------------------------------------
# No-op stub — always defined so tests can import it regardless of whether
# prometheus_client is installed.
# ---------------------------------------------------------------------------


class _NoOpLabeled:
    """Stub that accepts .labels(...).inc() / .observe() etc."""

    def labels(self, *args, **kwargs):
        return self

    def inc(self, amount=1):
        pass

    def dec(self, amount=1):
        pass

    def observe(self, amount):
        pass

    def set(self, value):
        pass


# ---------------------------------------------------------------------------
# Metric definitions (real or no-op)
# ---------------------------------------------------------------------------

if _PROMETHEUS_AVAILABLE:
    REQUEST_COUNT = Counter(
        "bitmod_requests_total",
        "Total HTTP requests",
        ["endpoint", "method", "status_code"],
    )

    REQUEST_DURATION = Histogram(
        "bitmod_request_duration_seconds",
        "HTTP request latency in seconds",
        ["endpoint"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    CACHE_HIT_TOTAL = Counter(
        "bitmod_cache_hit_total",
        "Total cache hits by layer and tenant",
        ["layer", "tenant_id"],
    )

    # Keep legacy alias for backward compatibility
    CACHE_HITS = Counter(
        "bitmod_cache_hits_total",
        "Total cache hits (legacy)",
        ["cache_layer"],
    )

    CACHE_MISS_TOTAL = Counter(
        "bitmod_cache_miss_total",
        "Total cache misses by tenant",
        ["tenant_id"],
    )

    CACHE_MISSES = Counter(
        "bitmod_cache_misses_total",
        "Total cache misses (legacy)",
    )

    LLM_REQUEST_TOTAL = Counter(
        "bitmod_llm_request_total",
        "Total LLM requests by provider, model, and status",
        ["provider", "model", "status"],
    )

    LLM_CALLS = Counter(
        "bitmod_llm_calls_total",
        "Total LLM API calls (legacy)",
        ["provider", "model"],
    )

    LLM_LATENCY_SECONDS = Histogram(
        "bitmod_llm_latency_seconds",
        "LLM API call latency in seconds",
        ["provider", "model"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    )

    # Keep legacy alias
    LLM_LATENCY = Histogram(
        "bitmod_llm_latency_legacy_seconds",
        "LLM API call latency (legacy, by provider only)",
        ["provider"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    )

    COST_SAVED_USD = Counter(
        "bitmod_cost_saved_usd_total",
        "Estimated USD saved by cache hits",
        ["tenant_id"],
    )

    REQUEST_DURATION_SECONDS = Histogram(
        "bitmod_request_duration_detail_seconds",
        "HTTP request duration by method, path, and status code",
        ["method", "path", "status_code"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    CACHE_ENTRIES = Gauge(
        "bitmod_cache_entries",
        "Current number of cache entries",
    )

    DOCUMENTS_TOTAL = Gauge(
        "bitmod_documents_total",
        "Total ingested documents",
    )

    ACTIVE_CONNECTIONS = Gauge(
        "bitmod_active_connections",
        "Number of active HTTP connections",
    )

    SECURITY_EVENTS_TOTAL = Counter(
        "bitmod_security_events_total",
        "Total security events by type",
        ["event_type"],
    )

else:
    _noop = _NoOpLabeled()

    REQUEST_COUNT = _noop  # type: ignore[assignment]
    REQUEST_DURATION = _noop  # type: ignore[assignment]
    CACHE_HIT_TOTAL = _noop  # type: ignore[assignment]
    CACHE_HITS = _noop  # type: ignore[assignment]
    CACHE_MISS_TOTAL = _noop  # type: ignore[assignment]
    CACHE_MISSES = _noop  # type: ignore[assignment]
    LLM_REQUEST_TOTAL = _noop  # type: ignore[assignment]
    LLM_CALLS = _noop  # type: ignore[assignment]
    LLM_LATENCY_SECONDS = _noop  # type: ignore[assignment]
    LLM_LATENCY = _noop  # type: ignore[assignment]
    COST_SAVED_USD = _noop  # type: ignore[assignment]
    REQUEST_DURATION_SECONDS = _noop  # type: ignore[assignment]
    CACHE_ENTRIES = _noop  # type: ignore[assignment]
    DOCUMENTS_TOTAL = _noop  # type: ignore[assignment]
    ACTIVE_CONNECTIONS = _noop  # type: ignore[assignment]
    SECURITY_EVENTS_TOTAL = _noop  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Convenience helpers for recording cache and LLM events
# ---------------------------------------------------------------------------


def record_cache_hit(layer: str, tenant_id: str = "default") -> None:
    """Record a cache hit for the given layer.

    Args:
        layer: One of "exact", "semantic", "composable", "fuzzy".
        tenant_id: Tenant identifier for multi-tenant tracking.
    """
    CACHE_HIT_TOTAL.labels(layer=layer, tenant_id=tenant_id).inc()
    CACHE_HITS.labels(cache_layer=layer).inc()  # legacy


def record_cache_miss(tenant_id: str = "default") -> None:
    """Record a cache miss.

    Args:
        tenant_id: Tenant identifier for multi-tenant tracking.
    """
    CACHE_MISS_TOTAL.labels(tenant_id=tenant_id).inc()
    CACHE_MISSES.inc()  # legacy


def record_llm_call(
    provider: str,
    model: str,
    duration_seconds: float,
    status: str = "success",
) -> None:
    """Record an LLM API call with its latency.

    Args:
        provider: LLM provider name (e.g. "anthropic", "openai").
        model: Model identifier.
        duration_seconds: Call latency in seconds.
        status: "success" or "error".
    """
    LLM_REQUEST_TOTAL.labels(provider=provider, model=model, status=status).inc()
    LLM_LATENCY_SECONDS.labels(provider=provider, model=model).observe(duration_seconds)
    # Legacy counters
    LLM_CALLS.labels(provider=provider, model=model).inc()
    LLM_LATENCY.labels(provider=provider).observe(duration_seconds)


def record_cost_saved(amount_usd: float, tenant_id: str = "default") -> None:
    """Record estimated cost savings from a cache hit.

    Args:
        amount_usd: Estimated USD saved.
        tenant_id: Tenant identifier.
    """
    COST_SAVED_USD.labels(tenant_id=tenant_id).inc(amount_usd)


def record_security_event(event_type: str) -> None:
    """Increment the security events counter.

    Args:
        event_type: One of auth_failure, auth_success, rate_limited,
            injection_blocked, path_traversal_blocked, invalid_input,
            namespace_access_denied.
    """
    SECURITY_EVENTS_TOTAL.labels(event_type=event_type).inc()


def record_request_duration(
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record detailed HTTP request duration.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: Normalized request path.
        status_code: HTTP response status code.
        duration_seconds: Request duration in seconds.
    """
    REQUEST_DURATION_SECONDS.labels(
        method=method,
        path=path,
        status_code=str(status_code),
    ).observe(duration_seconds)


# ---------------------------------------------------------------------------
# FastAPI Metrics Middleware
# ---------------------------------------------------------------------------


def _normalize_path(path: str) -> str:
    """Collapse path parameters to reduce cardinality.

    /v1/chat/completions  -> /v1/chat/completions
    /v1beta/models/gemini-pro:generateContent -> /v1beta/models/:model:generateContent
    /v1/chat/some/deep/path -> /v1/chat/:path
    """
    # Known static endpoints — return as-is
    static = {
        "/health",
        "/metrics",
        "/v1/models",
        "/v1/search",
        "/v1/chat/completions",
        "/v1/messages",
        "/v1/reload",
        "/v1/ingest/text",
        "/v1/ingest/file",
        "/v1/ingest/status",
        "/v1/cache/stats",
        "/v1/admin/metrics",
        "/api/chat",
        "/api/tags",
    }
    if path in static:
        return path

    # Gemini model endpoints
    if path.startswith("/v1beta/models/"):
        if ":generateContent" in path:
            return "/v1beta/models/:model:generateContent"
        if ":streamGenerateContent" in path:
            return "/v1beta/models/:model:streamGenerateContent"
        return "/v1beta/models/:model"

    # /v1/chat/{path} catch-all
    if path.startswith("/v1/chat/"):
        return "/v1/chat/:path"

    return path


class MetricsMiddleware:
    """ASGI middleware that tracks request count, latency, and active connections.

    Usage:
        from bitmod.metrics import MetricsMiddleware
        app.add_middleware(MetricsMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET")
        normalized = _normalize_path(path)

        ACTIVE_CONNECTIONS.inc()
        start = time.perf_counter()

        status_code = 500  # default in case of unhandled error

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            ACTIVE_CONNECTIONS.dec()
            REQUEST_COUNT.labels(
                endpoint=normalized,
                method=method,
                status_code=str(status_code),
            ).inc()
            REQUEST_DURATION.labels(endpoint=normalized).observe(duration)
