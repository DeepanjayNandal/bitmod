"""Bitmod API Gateway.

Routes requests, enforces rate limits, handles CORS and security headers.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bitmod.auth import (
    APIKeyManager,
    AuthUser,
    create_jwt_token,
    hash_api_key,
    is_auth_enabled,
    require_auth_db,
    revoke_token,
    verify_jwt_token,
)
from bitmod.config import load_config
from bitmod.metrics import (
    MetricsMiddleware,
    prometheus_available,
)
from bitmod.observability import (
    configure_logging,
    get_correlation_id,
)
from bitmod.pricing import estimate_cost, get_updated_at, is_stale
from bitmod.proxy.debug import debug_enabled
from bitmod.schemas import (
    ContextRequest,
    ContextResponse,
    ConversationRateRequest,
    ConversationResponse,
    CorrectionRequest,
    CorrectionResponse,
    HealthResponse,
    IngestResponse,
    IngestTextRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectScanResponse,
)
from bitmod.security import ALLOWED_FILE_EXTENSIONS, get_rate_limiter
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

configure_logging()
logger = logging.getLogger(__name__)

config = load_config()

# Use Redis-backed rate limiter when REDIS_URL (or config.redis) is available
_redis_url = os.getenv("REDIS_URL") or (
    config.redis.url if config.redis.host != "localhost" or os.getenv("REDIS_HOST") else None
)
rate_limiter = get_rate_limiter(_redis_url)

# Maximum request body size (1 MB for API requests)
MAX_REQUEST_BODY_SIZE = 1 * 1024 * 1024

# Document limit per namespace (global when namespaces not used)
MAX_DOCUMENTS_PER_NAMESPACE = int(os.getenv("BITMOD_MAX_DOCUMENTS", "50000"))

# Allowed internal proxy targets — prevents SSRF via path manipulation
_ALLOWED_PROXY_HOSTS: set[str] = set()


def _init_allowed_hosts() -> None:
    """Parse allowed proxy target hosts from config."""
    try:
        parsed = urlparse(config.gateway.chat_service_url)
        if parsed.hostname:
            _ALLOWED_PROXY_HOSTS.add(parsed.hostname)
    except Exception:  # noqa: S110 — host parsing failure is non-fatal
        pass


_init_allowed_hosts()

# Shared httpx client for connection pooling across proxy requests
_http_client: httpx.AsyncClient | None = None

_disable_docs = os.getenv("BITMOD_DISABLE_DOCS", "").strip().lower() in ("1", "true", "yes")

app = FastAPI(
    title="BitMod API",
    description=(
        "Modular AI Data Infrastructure -- Compute once, serve forever.\n\n"
        "9-layer intelligent cache engine with universal LLM adapter, "
        "multi-tenant namespace isolation, and project knowledge indexing."
    ),
    version="0.2.1",
    docs_url=None if _disable_docs else "/docs",
    redoc_url=None if _disable_docs else "/redoc",
    openapi_url=None if _disable_docs else "/openapi.json",
    openapi_tags=[
        {"name": "health", "description": "Liveness, readiness, and metrics probes"},
        {"name": "chat", "description": "Chat completions and conversational AI"},
        {"name": "search", "description": "Semantic and keyword search"},
        {"name": "ingest", "description": "Document and text ingestion"},
        {"name": "cache", "description": "Cache statistics and management"},
        {"name": "auth", "description": "Authentication, API keys, and JWT tokens"},
        {"name": "admin", "description": "Administrative metrics and operations"},
        {"name": "proxy", "description": "LLM provider proxy (OpenAI, Anthropic, Google, Ollama)"},
        {"name": "usage", "description": "Usage tracking and cost reporting"},
        {"name": "namespaces", "description": "Multi-tenant namespace isolation"},
        {"name": "projects", "description": "Project knowledge indexing and context assembly"},
        {"name": "history", "description": "Conversation history, ratings, and corrections"},
    ],
)

# CORS -- validate origins are not wildcards in production
_cors_origins = config.gateway.cors_origins
_cors_strict = os.getenv("BITMOD_CORS_STRICT", "").lower() in ("1", "true", "yes")
if "*" in _cors_origins:
    if _cors_strict:
        logger.error(
            "BITMOD_CORS_STRICT=true but CORS_ORIGINS contains wildcard '*'. "
            "Refusing to start with wildcard CORS in strict mode. "
            "Set CORS_ORIGINS to specific domains."
        )
        _cors_origins = []  # Block all cross-origin in strict mode
    else:
        logger.warning(
            "CORS is configured with wildcard origin '*'. "
            "This is insecure for production. Set CORS_ORIGINS to specific domains. "
            "Set BITMOD_CORS_STRICT=true to reject wildcard CORS entirely."
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False if "*" in _cors_origins else True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Requested-With",
        "x-api-key",
        "X-Bitmod-Namespace",
        "X-Bitmod-Debug",
    ],
    expose_headers=[
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-Response-Time",
        "Retry-After",
        "X-Bitmod-Cache-Hit",
        "X-Bitmod-Cache-Layer",
        "X-Bitmod-Serve-Count",
        "X-Bitmod-Saved",
    ],
    max_age=600,
)


@app.on_event("startup")
async def _startup():
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    logger.info("Gateway started, shared HTTP client initialized")


@app.on_event("shutdown")
async def _shutdown():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None
    logger.info("Gateway shutting down, HTTP client closed")


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    """Standardize all HTTPException responses to use {"error": ...} format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


try:
    from pydantic import ValidationError as _PydanticValidationError

    @app.exception_handler(_PydanticValidationError)
    async def _validation_error_handler(request: Request, exc: _PydanticValidationError):
        """Return generic 422 for Pydantic validation errors -- no internal details."""
        return JSONResponse(
            status_code=422,
            content={"error": "Request validation failed. Check your request body."},
        )

except ImportError:
    pass


# Prometheus metrics middleware — auto-tracks request counts and latency
app.add_middleware(MetricsMiddleware)


# ---------------------------------------------------------------------------
# Correlation ID middleware — extract or generate, propagate via context var
# ---------------------------------------------------------------------------

from bitmod.middleware import correlation_id_middleware  # noqa: E402

app.middleware("http")(correlation_id_middleware)


# Request body size enforcement middleware
# Ingest endpoints allow larger uploads (50 MB)
MAX_INGEST_BODY_SIZE = 50 * 1024 * 1024


@app.middleware("http")
async def enforce_body_size(request: Request, call_next):
    max_size = MAX_INGEST_BODY_SIZE if request.url.path.startswith("/v1/ingest") else MAX_REQUEST_BODY_SIZE

    # Check Content-Length header first (fast reject)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_size:
                return JSONResponse(
                    status_code=413,
                    content={"error": "Request body too large."},
                )
        except (ValueError, OverflowError):
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid Content-Length header."},
            )

    # Also enforce on actual body bytes (Content-Length can be spoofed or absent)
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        if len(body) > max_size:
            return JSONResponse(
                status_code=413,
                content={"error": "Request body too large."},
            )

    return await call_next(request)


# CSRF protection: require X-Requested-With header on state-changing requests
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Exempt health, metrics, and OPTIONS preflight
        path = request.url.path
        if path not in ("/health", "/healthz", "/readyz", "/metrics"):
            # If auth is disabled, require X-Requested-With to prevent cross-origin form POSTs
            if not is_auth_enabled():
                xrw = request.headers.get("x-requested-with", "")
                if not xrw:
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Missing X-Requested-With header. This protects against CSRF."},
                    )
    return await call_next(request)


# Security headers middleware
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"  # Modern browsers: CSP is preferred
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Only set CSP on non-API responses (API JSON responses don't need CSP,
    # and restrictive connect-src blocks frontend cross-origin API calls)
    if not request.url.path.startswith("/v1/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    if request.url.path.startswith("/v1/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    # Remove server identification headers
    if "server" in response.headers:
        del response.headers["server"]
    return response


# Rate limiting middleware

# Tier-based rate limit overrides (requests per minute)
_TIER_RATE_LIMITS: dict[str, int] = {
    "free": 20,
    "pro": 120,
    "enterprise": 600,
    "": 60,  # default when no tier
}

# Lightweight in-memory tier cache to avoid per-request DB lookups
_tier_cache: dict[str, tuple[str, float]] = {}  # key_hash_prefix -> (tier, cached_at)
_TIER_CACHE_TTL = 300.0  # 5 minutes


def _lookup_cached_tier(key_hash_prefix: str) -> str | None:
    """Look up an API key's tier, using in-memory cache with DB fallback."""
    now = time.time()

    # Check cache first
    cached = _tier_cache.get(key_hash_prefix)
    if cached is not None:
        tier, cached_at = cached
        if now - cached_at < _TIER_CACHE_TTL:
            return tier

    # DB fallback -- lightweight query for tier column
    try:
        mgr = _get_key_manager()
        keys = mgr.list_keys()
        for k in keys:
            if k.key_hash.startswith(key_hash_prefix) and k.is_active:
                _tier_cache[key_hash_prefix] = (k.tier, now)
                return k.tier
    except Exception:  # noqa: S110 — tier lookup failure is non-fatal, falls back to default
        pass

    # Cache the miss so we don't retry every request
    _tier_cache[key_hash_prefix] = ("", now)
    return ""


def _extract_rate_limit_key(request: Request) -> str:
    """Determine the rate limit bucket key for a request.

    Authenticated requests (API key via x-api-key or Authorization: ApiKey headers)
    are rate-limited per key, giving each tenant its own independent bucket.
    Unauthenticated requests fall back to IP-based rate limiting.
    """
    # Check x-api-key header first (Anthropic-style)
    api_key = request.headers.get("x-api-key", "")
    if not api_key:
        # Check Authorization: ApiKey <key>
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("ApiKey "):
            api_key = auth_header[7:].strip()

    if api_key:
        key_hash_prefix = hash_api_key(api_key)[:12]
        return f"key:{key_hash_prefix}"

    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    rate_key = _extract_rate_limit_key(request)
    path = request.url.path

    if path == "/health":
        # Health checks are not rate limited
        return await call_next(request)
    elif path == "/metrics":
        max_req, window = 30, 60  # 30/min for metrics
    elif path == "/v1/auth/token":
        max_req, window = 10, 60  # 10/min — strict limit to prevent brute-force
    elif path.startswith("/v1/auth"):
        max_req, window = 20, 60  # 20/min for other auth endpoints
    elif (
        path.startswith("/v1/chat")
        or path.startswith("/v1/messages")
        or path.startswith("/v1beta/")
        or path.startswith("/api/chat")
    ):
        max_req, window = 60, 60  # 60/min for chat and proxy endpoints
    elif path.startswith("/v1/search"):
        max_req, window = 120, 60  # 120/min for search
    elif path.startswith("/v1/ingest") or path.startswith("/v1/projects"):
        max_req, window = 10, 60  # 10/min for ingest and project ops (expensive operations)
    elif path.startswith("/v1/admin") or path.startswith("/v1/cache"):
        max_req, window = 30, 60  # 30/min for admin and cache stats
    else:
        max_req, window = 60, 60

    # Tier-based override for API-key-authenticated requests
    if rate_key.startswith("key:"):
        key_prefix = rate_key[4:]
        tier = _lookup_cached_tier(key_prefix)
        if tier is not None and tier in _TIER_RATE_LIMITS:
            max_req = _TIER_RATE_LIMITS[tier]

    # Use async methods when available (RedisRateLimiter), sync otherwise
    if hasattr(rate_limiter, "is_allowed_async"):
        allowed = await rate_limiter.is_allowed_async(rate_key, max_req, window)
    else:
        allowed = rate_limiter.is_allowed(rate_key, max_req, window)

    if not allowed:
        if hasattr(rate_limiter, "reset_seconds_async"):
            reset = await rate_limiter.reset_seconds_async(rate_key, window)
        else:
            reset = rate_limiter.reset_seconds(rate_key, window)
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded. Try again later."},
            headers={
                "Retry-After": str(reset or window),
                "X-RateLimit-Limit": str(max_req),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset or window),
            },
        )

    response = await call_next(request)

    if hasattr(rate_limiter, "remaining_async"):
        rem = await rate_limiter.remaining_async(rate_key, max_req, window)
    else:
        rem = rate_limiter.remaining(rate_key, max_req, window)
    if hasattr(rate_limiter, "reset_seconds_async"):
        reset = await rate_limiter.reset_seconds_async(rate_key, window)
    else:
        reset = rate_limiter.reset_seconds(rate_key, window)
    response.headers["X-RateLimit-Limit"] = str(max_req)
    response.headers["X-RateLimit-Remaining"] = str(rem)
    response.headers["X-RateLimit-Reset"] = str(reset)
    return response


# Request timing middleware
@app.middleware("http")
async def timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
    return response


# Health check
@app.get("/health", tags=["health"])
async def health():
    return HealthResponse(status="ok", service="gateway", version="0.2.1")


# --- Deep health checks ---

# Cache chat service readiness result for 30s to avoid hammering
_readyz_cache_ts: float = 0.0
_readyz_cache_status: str = "unknown"
_readyz_cache_error: str = ""


@app.get("/healthz", tags=["health"])
async def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz():
    global _readyz_cache_ts, _readyz_cache_status, _readyz_cache_error  # noqa: PLW0603
    now = time.monotonic()
    if now - _readyz_cache_ts < 30:
        if _readyz_cache_status == "ready":
            return {"status": "ready", "chat_service": "reachable"}
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "chat_service": "unreachable", "error": _readyz_cache_error},
        )

    chat_url = config.gateway.chat_service_url.rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(chat_url)
            resp.raise_for_status()
        _readyz_cache_ts = now
        _readyz_cache_status = "ready"
        _readyz_cache_error = ""
        return {"status": "ready", "chat_service": "reachable"}
    except Exception as e:
        _readyz_cache_ts = now
        _readyz_cache_status = "unavailable"
        _readyz_cache_error = str(e)
        logger.warning("Readiness check failed — chat service unreachable: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "chat_service": "unreachable", "error": "Service unavailable."},
        )


# Prometheus metrics endpoint
@app.get("/metrics", tags=["health"])
async def metrics_endpoint(request: Request):
    """Return Prometheus exposition format metrics.

    When auth is enabled, requires a valid API key (x-api-key or Authorization header).
    Returns 501 if prometheus_client is not installed.
    """
    if is_auth_enabled():
        api_key = request.headers.get("x-api-key", "")
        if not api_key:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("ApiKey "):
                api_key = auth_header[7:].strip()
        if not api_key:
            return JSONResponse(
                status_code=401, content={"error": "API key required for /metrics when auth is enabled"}
            )
        # Actually validate the key — not just check presence
        from bitmod.auth import validate_api_key as _validate_key

        mgr = _get_key_manager()
        record = mgr.validate_key(api_key)
        if record is None and not _validate_key(api_key):
            return JSONResponse(status_code=401, content={"error": "Invalid API key."})
    else:
        # When auth is disabled, restrict metrics to localhost or require X-Requested-With header
        client_ip = request.client.host if request.client else ""
        has_csrf_header = request.headers.get("x-requested-with", "") != ""
        is_localhost = client_ip in ("127.0.0.1", "::1", "localhost")
        if not is_localhost and not has_csrf_header:
            return JSONResponse(
                status_code=403,
                content={"error": "Metrics requires X-Requested-With header or localhost access."},
            )

    if not prometheus_available():
        return JSONResponse(
            status_code=501,
            content={"error": "Metrics not available. Install prometheus_client: pip install prometheus-client"},
        )
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# Proxy to chat service
@app.api_route("/v1/chat", methods=["GET", "POST"])
@app.api_route("/v1/chat/{path:path}", methods=["GET", "POST"])
async def proxy_chat(request: Request, path: str = ""):
    chat_url = config.gateway.chat_service_url

    # SSRF prevention: only proxy to known internal service URLs
    parsed = urlparse(chat_url)
    if parsed.hostname not in _ALLOWED_PROXY_HOSTS:
        logger.error("SSRF attempt blocked: proxy target %s not in allowlist", chat_url)
        return JSONResponse(
            status_code=502,
            content={"error": "Service unavailable."},
        )

    # Sanitize the path segment to prevent path injection
    # Only allow alphanumeric, hyphens, underscores, and forward slashes
    import re

    if path and not re.match(r"^[a-zA-Z0-9/_-]*$", path):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid path."},
        )

    target = f"{chat_url}/v1/chat/{path}" if path else f"{chat_url}/v1/chat"

    body = await request.body()

    # Only forward safe headers -- strip sensitive ones
    safe_headers = {}
    for k, v in request.headers.items():
        lower_k = k.lower()
        if lower_k in (
            "host",
            "content-length",
            "transfer-encoding",
            "connection",
            "keep-alive",
            "proxy-authorization",
            "te",
            "trailers",
            "upgrade",
        ):
            continue
        safe_headers[k] = v

    # Add internal token so chat service accepts requests from gateway
    _internal_token = os.getenv("BITMOD_INTERNAL_TOKEN", "")
    if _internal_token:
        safe_headers["X-Internal-Token"] = _internal_token

    # Detect if the request wants streaming (SSE)
    is_stream_request = False
    if body and request.method == "POST":
        try:
            parsed_body = json.loads(body)
            is_stream_request = parsed_body.get("stream", False)
        except (json.JSONDecodeError, AttributeError):
            pass

    if is_stream_request:
        # Stream SSE chunks as they arrive instead of buffering
        from starlette.responses import StreamingResponse

        async def _stream_proxy():
            client = _http_client or httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            )
            try:
                async with client.stream("POST", target, content=body, headers=safe_headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            except httpx.TimeoutException:
                logger.warning("Upstream timeout during SSE stream")
            except httpx.ConnectError:
                logger.warning("Upstream connect error during SSE stream")
            except Exception:
                logger.exception("Proxy stream error")

        return StreamingResponse(
            _stream_proxy(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming: standard request/response
    client = _http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
    )
    try:
        if request.method == "POST":
            response = await client.post(target, content=body, headers=safe_headers)
        else:
            response = await client.get(target, headers=safe_headers)

        # Only forward safe response headers
        safe_response_headers = {}
        for k, v in response.headers.items():
            lower_k = k.lower()
            if lower_k in ("content-type", "content-length", "cache-control"):
                safe_response_headers[k] = v

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=safe_response_headers,
            media_type=response.headers.get("content-type"),
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "Upstream service timeout."},
        )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=502,
            content={"error": "Upstream service unavailable."},
        )
    except Exception:
        logger.exception("Proxy error")
        return JSONResponse(
            status_code=502,
            content={"error": "Service unavailable."},
        )


# Proxy to chat service — search endpoint
@app.api_route("/v1/search", methods=["GET", "POST"])
async def proxy_search(request: Request):
    chat_url = config.gateway.chat_service_url
    parsed = urlparse(chat_url)
    if parsed.hostname not in _ALLOWED_PROXY_HOSTS:
        return JSONResponse(status_code=502, content={"error": "Service unavailable."})

    target = f"{chat_url}/v1/search"
    client = _http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
    )
    try:
        body = await request.body()
        safe_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            not in (
                "host",
                "content-length",
                "transfer-encoding",
                "connection",
                "keep-alive",
                "proxy-authorization",
                "te",
                "trailers",
                "upgrade",
            )
        }
        # Add internal token so chat service accepts requests from gateway
        _internal_token = os.getenv("BITMOD_INTERNAL_TOKEN", "")
        if _internal_token:
            safe_headers["X-Internal-Token"] = _internal_token
        if request.method == "POST":
            response = await client.post(target, content=body, headers=safe_headers)
        else:
            response = await client.get(target, headers=safe_headers)

        try:
            _get_audit_logger().log_event(
                "search_executed",
                action="proxy_search",
                outcome="success" if response.status_code < 400 else "error",
                details={"status_code": response.status_code, "method": request.method},
            )
        except Exception:  # noqa: S110
            logger.debug("Audit log failed for search", exc_info=True)

        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": "Upstream service timeout."})
    except httpx.ConnectError:
        return JSONResponse(status_code=502, content={"error": "Upstream service unavailable."})
    except Exception:
        logger.exception("Search proxy error")
        return JSONResponse(status_code=502, content={"error": "Service unavailable."})


# ---------------------------------------------------------------------------
# Ingest endpoints — run directly on gateway (no proxy needed)
# ---------------------------------------------------------------------------

# Lazy-initialized shared resources for ingestion (thread-safe via locks)
_ingest_backend = None
_ingest_embedder = None
_ingest_embedder_checked = False
# Reentrant on purpose. Three lazy initialisers guarded by this lock —
# _get_proxy, _get_audit_logger and _get_key_manager — call
# _get_ingest_backend() from inside their critical section, and that function
# takes the same lock. With a plain Lock the thread deadlocks against itself.
#
# It only bites when the backend has not been built yet: _get_ingest_backend
# returns before acquiring anything once _ingest_backend is set, so whichever
# request touches the backend first is the one that hangs. Any earlier request
# that initialised it hides the bug completely.
_init_lock = threading.RLock()
_audit_logger = None


def _get_ingest_backend():
    global _ingest_backend
    if _ingest_backend is not None:
        return _ingest_backend
    with _init_lock:
        if _ingest_backend is None:
            from bitmod.adapters import get_backend

            _ingest_backend = get_backend(config.db)
            _ingest_backend.initialize()
    return _ingest_backend


def _get_ingest_embedder():
    global _ingest_embedder, _ingest_embedder_checked
    if _ingest_embedder_checked:
        return _ingest_embedder
    with _init_lock:
        if not _ingest_embedder_checked:
            try:
                from bitmod.adapters import get_embedder

                _ingest_embedder = get_embedder(config.embedding)
                logger.info(
                    "Embedder initialized: provider=%s, model=%s",
                    config.embedding.provider,
                    config.embedding.model,
                )
            except Exception as e:
                logger.warning("Embedder not available (%s): ingestion will skip embeddings", e)
                _ingest_embedder = None
            _ingest_embedder_checked = True
    return _ingest_embedder


def _get_audit_logger():
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger
    with _init_lock:
        if _audit_logger is None:
            from bitmod.audit import AuditLogger

            _audit_logger = AuditLogger(_get_ingest_backend())
    return _audit_logger


def _check_document_limit(backend, namespace_id: str | None = None) -> None:
    """Raise HTTPException(429) if document count has reached the limit."""
    if not hasattr(backend, "count_documents"):
        return
    with backend.session() as session:
        count = backend.count_documents(session, namespace_id=namespace_id)
    if count >= MAX_DOCUMENTS_PER_NAMESPACE:
        raise HTTPException(status_code=429, detail="Document limit reached for this namespace")
    if count > MAX_DOCUMENTS_PER_NAMESPACE * 0.8:
        logger.warning(
            "Approaching document limit: %d / %d (namespace=%s)",
            count,
            MAX_DOCUMENTS_PER_NAMESPACE,
            namespace_id,
        )


@app.post("/v1/ingest/text", tags=["ingest"])
async def ingest_text_endpoint(
    request: IngestTextRequest, _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["write"]))
):
    """Ingest raw text content into the data store. Requires write scope."""
    from bitmod.ingestion.chunker import ChunkConfig
    from bitmod.ingestion.pipeline import ingest_text

    backend = _get_ingest_backend()
    embedder = _get_ingest_embedder()

    _check_document_limit(backend)

    try:
        result = ingest_text(
            text=request.text,
            title=request.title,
            document_type=request.document_type,
            source=request.source,
            jurisdiction=request.jurisdiction,
            tags=request.tags or None,
            metadata=request.metadata or None,
            backend=backend,
            embedder=embedder,
            chunk_config=ChunkConfig(
                chunk_size=request.chunk_size,
                chunk_overlap=request.chunk_overlap,
            ),
        )

        # Cascade invalidation: invalidate cached answers for changed sections
        _cascade_invalidate_for_document(backend, result.get("document_id"), result)

        try:
            _get_audit_logger().log_event(
                "document_ingested",
                action="ingest_text",
                resource=result.get("document_id", ""),
                outcome="success",
                details={
                    "title": request.title[:200] if request.title else "",
                    "chunks": result.get("chunks_created", 0),
                    "document_type": request.document_type or "",
                },
            )
        except Exception:  # noqa: S110
            logger.debug("Audit log failed for text ingest", exc_info=True)

        return IngestResponse(**result)
    except Exception:
        logger.exception("Ingestion failed")
        return JSONResponse(
            status_code=500,
            content={"error": "Ingestion failed. Check server logs for details."},
        )


@app.post("/v1/ingest/file", tags=["ingest"])
async def ingest_file_endpoint(request: Request, _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["write"]))):
    """Ingest a file via multipart upload. Requires write scope."""
    import tempfile

    from bitmod.ingestion.chunker import ChunkConfig
    from bitmod.ingestion.pipeline import ingest_file

    backend = _get_ingest_backend()
    embedder = _get_ingest_embedder()

    _check_document_limit(backend)

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_raw = form.get("file")
        if uploaded_raw is None or not hasattr(uploaded_raw, "filename"):
            return JSONResponse(
                status_code=400, content={"error": "No file uploaded. Send as multipart form with 'file' field."}
            )
        from starlette.datastructures import UploadFile as StarletteUploadFile

        uploaded: StarletteUploadFile = uploaded_raw  # type: ignore[assignment]

        # Validate file extension before creating any temp file
        filename = str(uploaded.filename or "upload.txt")
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".txt"
        if suffix.lower() not in ALLOWED_FILE_EXTENSIONS:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"File extension '{suffix}' is not allowed. "
                    f"Allowed: {', '.join(sorted(ALLOWED_FILE_EXTENSIONS))}"
                },
            )

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await uploaded.read()
            if len(content) > 50 * 1024 * 1024:
                return JSONResponse(status_code=413, content={"error": "File too large (max 50MB)."})
            tmp.write(content)
            tmp_path = tmp.name

        title = str(form.get("title", uploaded.filename) or uploaded.filename)
        document_type = str(form.get("document_type", "document") or "document")
        source = str(form.get("source", "upload") or "upload")
        jurisdiction = str(form.get("jurisdiction")) if form.get("jurisdiction") else None
        tags_raw = str(form.get("tags", "") or "")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None
        try:
            chunk_size = int(str(form.get("chunk_size", "500")))
        except (ValueError, TypeError):
            chunk_size = 500
        try:
            chunk_overlap = int(str(form.get("chunk_overlap", "50")))
        except (ValueError, TypeError):
            chunk_overlap = 50
        chunk_size = max(50, min(chunk_size, 10000))
        chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))
    else:
        return JSONResponse(
            status_code=400,
            content={"error": "Send file as multipart/form-data with 'file' field."},
        )

    try:
        result = ingest_file(
            file_path=tmp_path,
            title=title,
            document_type=document_type,
            source=source,
            jurisdiction=jurisdiction,
            tags=tags,
            backend=backend,
            embedder=embedder,
            chunk_config=ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
        )

        # Cascade invalidation: invalidate cached answers for changed sections
        _cascade_invalidate_for_document(backend, result.get("document_id"), result)

        try:
            _get_audit_logger().log_event(
                "document_ingested",
                action="ingest_file",
                resource=result.get("document_id", ""),
                outcome="success",
                details={
                    "title": title[:200] if title else "",
                    "chunks": result.get("chunks_created", 0),
                    "document_type": document_type or "",
                },
            )
        except Exception:  # noqa: S110
            logger.debug("Audit log failed for file ingest", exc_info=True)

        return IngestResponse(**result)
    except Exception:
        logger.exception("File ingestion failed")
        return JSONResponse(
            status_code=500,
            content={"error": "Ingestion failed. Check server logs for details."},
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _cascade_invalidate_for_document(backend, document_id: str | None, ingest_result: dict | None = None) -> None:
    """After re-ingestion, invalidate cached answers referencing changed sections.

    Only runs on re-ingestion (when sections were updated). For first-time ingestion,
    there are no cached answers to invalidate, so this is a no-op.
    """
    if not document_id:
        return
    # Only meaningful for re-ingestion with actual changes
    if ingest_result and not ingest_result.get("is_reingest"):
        return
    if ingest_result and ingest_result.get("sections_updated", 0) == 0:
        return
    try:
        with backend.session() as session:
            # Get all current sections and check which ones have cached answers
            sections = backend.get_sections_for_document(session, document_id)
            total_invalidated = 0
            for section in sections:
                count = backend.cache_invalidate_by_section(session, section.id)
                total_invalidated += count
            if total_invalidated > 0:
                logger.info(
                    "Cascade invalidation: %d cached answers invalidated for document %s",
                    total_invalidated,
                    document_id[:16],
                )
    except Exception:
        logger.debug("Cascade invalidation skipped (non-critical): %s", document_id[:16] if document_id else "?")


# ---------------------------------------------------------------------------
# LLM Proxy endpoints — multi-format (OpenAI, Anthropic, Gemini)
# ---------------------------------------------------------------------------

_proxy_instance = None


def _get_proxy():
    """Lazy-initialize the BitmodProxy with configured backend, LLM, and embedder."""
    global _proxy_instance
    if _proxy_instance is not None:
        return _proxy_instance
    with _init_lock:
        if _proxy_instance is not None:
            return _proxy_instance
        from bitmod.adapters import make_llm
        from bitmod.proxy import BitmodProxy
        from bitmod.router import LLMRouter

        backend = _get_ingest_backend()  # Reuse the already-initialized backend

        # Build LLM router from config
        resolved_provider = config.llm.resolve_provider()
        primary_llm = make_llm(resolved_provider, config.llm)
        fallback_llm = None
        if config.llm.fallback and config.llm.fallback != resolved_provider:
            try:
                fallback_llm = make_llm(config.llm.fallback, config.llm)
            except Exception:
                logger.warning("Fallback LLM '%s' not available", config.llm.fallback)
        router = LLMRouter(primary=primary_llm, fallback=fallback_llm)

        embedder = _get_ingest_embedder()

        _proxy_instance = BitmodProxy(
            backend=backend,
            llm_router=router,
            embedder=embedder,
            default_model=config.llm.resolve_model(),
            ollama_url=config.llm.ollama_url,
        )
        logger.info(
            "BitmodProxy initialized: primary=%s, fallback=%s, embedder=%s",
            resolved_provider,
            config.llm.fallback,
            config.embedding.provider if embedder else "none",
        )
    return _proxy_instance


def _validate_proxy_messages(body: dict, format_type: str = "openai") -> str | None:
    """Validate proxy request body messages. Returns error string or None if valid.

    Enforces:
    - messages must exist and be a list
    - Max 100 messages per request
    - Each message content max 100,000 chars
    """
    if format_type == "gemini":
        contents = body.get("contents")
        if contents is None:
            return "Missing 'contents' field."
        if not isinstance(contents, list):
            return "'contents' must be a list."
        if len(contents) > 100:
            return "Too many content entries (max 100)."
        for c in contents:
            parts = c.get("parts", [])
            if isinstance(parts, list):
                for p in parts:
                    if isinstance(p, dict) and "text" in p:
                        if len(str(p["text"])) > 100_000:
                            return "Message content too long (max 100,000 characters)."
        return None

    # OpenAI, Anthropic, Ollama formats
    messages = body.get("messages")
    if messages is None:
        return "Missing 'messages' field."
    if not isinstance(messages, list):
        return "'messages' must be a list."
    if len(messages) > 100:
        return "Too many messages (max 100)."
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > 100_000:
            return "Message content too long (max 100,000 characters)."
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text", "")
                    if isinstance(text, str) and len(text) > 100_000:
                        return "Message content block too long (max 100,000 characters)."
    return None


def _extract_api_key(request: Request) -> str | None:
    """Extract API key from Authorization header.

    Supports:
    - Bearer token: "Authorization: Bearer sk-..."
    - Anthropic header: "x-api-key: sk-ant-..."
    - Raw key: "Authorization: sk-..."
    Returns None if no key found or key is a placeholder like "ignored".
    """
    # Anthropic-style header
    key: str = request.headers.get("x-api-key", "")
    if key and key.lower() not in ("ignored", "dummy", "test", "fake", "none", ""):
        return key

    auth: str = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:].strip()
    elif auth:
        key = auth.strip()

    if key and key.lower() not in ("ignored", "dummy", "test", "fake", "none"):
        return key
    return None


def _extract_namespace_id(request: Request, user: AuthUser | None = None) -> str | None:
    """Extract and resolve namespace from X-Bitmod-Namespace header.

    The header can contain a namespace ID (UUID) or a namespace name.
    Returns the resolved namespace ID, or None if not set or not found.

    When *user* is provided, enforces namespace access control:
    - Authenticated users must be the namespace owner or the namespace
      must have public_fallback enabled.
    - Anonymous users (auth disabled) may only access namespaces with
      public_fallback enabled.
    - If no namespace header is sent (None), no check is performed.

    Raises:
        HTTPException(403): if the user is not allowed to access the namespace.
    """
    header = request.headers.get("x-bitmod-namespace", "")
    if not header or not header.strip():
        return None
    from bitmod.namespaces import resolve_namespace_id

    backend = _get_ingest_backend()
    ns_id: str | None = resolve_namespace_id(header, backend)

    if ns_id is not None and user is not None:
        from bitmod.namespaces import NamespaceManager

        mgr = NamespaceManager(backend)
        key_id = user.subject if user.auth_method != "none" else ""
        if not mgr.is_accessible(ns_id, key_id):
            raise HTTPException(status_code=403, detail="Access denied to this namespace")

    return ns_id


# --- OpenAI format: /v1/chat/completions ---


@app.post("/v1/chat/completions", tags=["proxy"])
async def proxy_openai_completions(request: Request, _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"]))):
    """OpenAI-compatible /v1/chat/completions with Bitmod caching."""
    proxy = _get_proxy()
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    validation_error = _validate_proxy_messages(body, format_type="openai")
    if validation_error:
        return JSONResponse(status_code=422, content={"error": validation_error})

    api_key = _extract_api_key(request)
    namespace_id = _extract_namespace_id(request, _user)

    if body.get("stream"):
        from starlette.responses import StreamingResponse

        return StreamingResponse(
            proxy.handle_completion_stream(body, api_key=api_key, namespace_id=namespace_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    debug_sink: dict | None = {} if debug_enabled(request, authenticated=True) else None
    result = await proxy.handle_completion(body, api_key=api_key, namespace_id=namespace_id, debug_sink=debug_sink)
    response = JSONResponse(content=result)
    return _add_cache_headers(response, result, debug_sink)


@app.get("/v1/models", tags=["proxy"])
async def proxy_openai_models():
    """OpenAI-compatible /v1/models endpoint."""
    proxy = _get_proxy()
    return await proxy.handle_models()


# --- Anthropic format: /v1/messages ---


@app.post("/v1/messages", tags=["proxy"])
async def proxy_anthropic_messages(request: Request, _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"]))):
    """Anthropic-compatible /v1/messages with Bitmod caching."""
    proxy = _get_proxy()
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    validation_error = _validate_proxy_messages(body, format_type="anthropic")
    if validation_error:
        return JSONResponse(status_code=422, content={"error": validation_error})

    api_key = _extract_api_key(request)
    namespace_id = _extract_namespace_id(request, _user)

    if body.get("stream"):
        from starlette.responses import StreamingResponse

        return StreamingResponse(
            proxy.handle_anthropic_stream(body, api_key=api_key, namespace_id=namespace_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    debug_sink: dict | None = {} if debug_enabled(request, authenticated=True) else None
    result = await proxy.handle_anthropic(body, api_key=api_key, namespace_id=namespace_id, debug_sink=debug_sink)
    response = JSONResponse(content=result)
    return _add_cache_headers(response, result, debug_sink)


# --- Gemini format: /v1beta/models/{model}:generateContent ---


@app.post("/v1beta/models/{model_name}:generateContent", tags=["proxy"])
async def proxy_gemini_generate(
    request: Request,
    model_name: str,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """Gemini-compatible generateContent with Bitmod caching."""
    proxy = _get_proxy()
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    validation_error = _validate_proxy_messages(body, format_type="gemini")
    if validation_error:
        return JSONResponse(status_code=422, content={"error": validation_error})

    api_key = _extract_api_key(request)
    namespace_id = _extract_namespace_id(request, _user)

    debug_sink: dict | None = {} if debug_enabled(request, authenticated=True) else None
    result = await proxy.handle_gemini(
        body, model=model_name, api_key=api_key, namespace_id=namespace_id, debug_sink=debug_sink
    )
    response = JSONResponse(content=result)
    return _add_cache_headers(response, result, debug_sink)


@app.post("/v1beta/models/{model_name}:streamGenerateContent", tags=["proxy"])
async def proxy_gemini_stream(
    request: Request,
    model_name: str,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """Gemini-compatible streamGenerateContent with Bitmod caching."""
    proxy = _get_proxy()
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    validation_error = _validate_proxy_messages(body, format_type="gemini")
    if validation_error:
        return JSONResponse(status_code=422, content={"error": validation_error})

    api_key = _extract_api_key(request)
    namespace_id = _extract_namespace_id(request, _user)

    from starlette.responses import StreamingResponse

    return StreamingResponse(
        proxy.handle_gemini_stream(body, model=model_name, api_key=api_key, namespace_id=namespace_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Ollama native format: /api/chat (for direct Ollama SDK users) ---


@app.post("/api/chat", tags=["proxy"])
async def proxy_ollama_chat(
    request: Request,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """Ollama-native /api/chat with Bitmod caching."""
    proxy = _get_proxy()
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    validation_error = _validate_proxy_messages(body, format_type="ollama")
    if validation_error:
        return JSONResponse(status_code=422, content={"error": validation_error})

    # Ollama /api/chat uses the same message format as OpenAI
    # but wraps the response differently
    messages = body.get("messages", [])
    model = body.get("model", "bitmod")
    temperature = body.get("options", {}).get("temperature", 0.0)

    # Convert to OpenAI format for the proxy pipeline
    openai_body = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "max_tokens": body.get("options", {}).get("num_predict", 4096),
    }

    namespace_id = _extract_namespace_id(request, _user)

    if body.get("stream", True):  # Ollama streams by default
        from starlette.responses import StreamingResponse

        async def _ollama_stream():
            async for chunk in proxy.handle_completion_stream(openai_body, namespace_id=namespace_id):
                # Convert OpenAI SSE to Ollama NDJSON format
                if chunk.startswith("data: [DONE]"):
                    yield (
                        json.dumps({"model": model, "done": True, "message": {"role": "assistant", "content": ""}})
                        + "\n"
                    )
                elif chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:].strip())
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield (
                                json.dumps(
                                    {
                                        "model": model,
                                        "done": False,
                                        "message": {"role": "assistant", "content": content},
                                    }
                                )
                                + "\n"
                            )
                    except (json.JSONDecodeError, IndexError):
                        pass

        return StreamingResponse(
            _ollama_stream(),
            media_type="application/x-ndjson",
        )

    result = await proxy.handle_completion(openai_body, namespace_id=namespace_id)
    # Convert OpenAI response to Ollama format
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return JSONResponse(
        content={
            "model": model,
            "message": {"role": "assistant", "content": content},
            "done": True,
            "x_bitmod_cached": result.get("x_bitmod_cached", False),
            "x_bitmod_cache_key": result.get("x_bitmod_cache_key"),
        }
    )


@app.get("/api/tags", tags=["proxy"])
async def proxy_ollama_tags():
    """Ollama-native /api/tags — return available models in Ollama format."""
    proxy = _get_proxy()
    models = await proxy.handle_models()
    return JSONResponse(
        content={
            "models": [
                {
                    "name": m["id"],
                    "modified_at": "2024-01-01T00:00:00Z",
                    "size": 0,
                }
                for m in models.get("data", [])
            ],
        }
    )


@app.post("/v1/reload", tags=["admin"])
async def proxy_reload(request: Request, _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["admin"]))):
    """Proxy reload. Requires admin scope."""
    chat_url = config.gateway.chat_service_url
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(f"{chat_url}/v1/reload")
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )
    except Exception:
        return JSONResponse(status_code=502, content={"error": "Chat service unavailable."})


@app.get("/v1/ingest/status", tags=["ingest"])
async def ingest_status(_user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"]))):
    """Return document ingestion statistics. Requires read scope."""
    backend = _get_ingest_backend()
    with backend.session() as session:
        stats = backend.document_stats(session)
    return stats


# Cache stats endpoint
@app.get("/v1/cache/stats", tags=["cache"])
async def cache_stats(_user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"]))):
    from bitmod.cache_engine import get_cache_stats

    try:
        db = _get_ingest_backend()
        with db.session() as session:
            stats = get_cache_stats(db, session)

            return stats
    except Exception:
        logger.exception("Failed to get cache stats")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to retrieve cache statistics."},
        )


# Admin metrics endpoint — serves all data the admin dashboard needs
@app.get("/v1/admin/metrics", tags=["admin"])
async def admin_metrics(_user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["admin"]))):
    from bitmod.cache_engine import get_cache_stats

    try:
        db = _get_ingest_backend()

        with db.session() as session:
            # Cache statistics
            cache = get_cache_stats(db, session)

            # Recent queries and model comparison (SQLite-specific enrichments)
            recent_queries: list[dict] = []
            model_comparison: list[dict] = []
            documents_data: dict = {
                "documents": [],
                "totals": {"document_count": 0, "total_sections": 0, "total_chunks": 0},
            }

            if hasattr(db, "recent_cached_queries"):
                recent_queries = db.recent_cached_queries(session)
            if hasattr(db, "cache_model_comparison"):
                model_comparison = db.cache_model_comparison(session)
            if hasattr(db, "document_stats"):
                documents_data = db.document_stats(session)

        cache["recent_queries"] = recent_queries

        # Enrich comparison queries with token cost estimates
        for q in model_comparison:
            inp = q.get("input_tokens", 0)
            out = q.get("output_tokens", 0)
            model = q.get("model_used", "")
            serves = q.get("serves", 0)
            # Cost per LLM call for this query
            cost_per_call = estimate_cost(inp, out, model)
            q["input_tokens"] = inp
            q["output_tokens"] = out
            q["cost_per_call"] = cost_per_call
            # Without cache: every serve is a full LLM call
            q["total_cost_without"] = round(cost_per_call * (1 + serves), 6)
            # With cache: only the first call costs money
            q["total_cost_with"] = cost_per_call
            q["cost_saved"] = round(cost_per_call * serves, 6)

        # Build comparison summary
        total_without_ms = sum(q["total_without_cache_ms"] for q in model_comparison)
        total_with_ms = sum(q["total_with_cache_ms"] for q in model_comparison)
        total_cost_without = sum(q.get("total_cost_without", 0) for q in model_comparison)
        total_cost_with = sum(q.get("total_cost_with", 0) for q in model_comparison)
        total_tokens_without = sum(
            (q.get("input_tokens", 0) + q.get("output_tokens", 0)) * (1 + q.get("serves", 0)) for q in model_comparison
        )
        total_tokens_with = sum(q.get("input_tokens", 0) + q.get("output_tokens", 0) for q in model_comparison)
        comparison = {
            "queries": model_comparison,
            "total_without": {
                "total_ms": total_without_ms,
                "total_s": round(total_without_ms / 1000, 2),
            },
            "total_with": {
                "total_ms": total_with_ms,
                "total_s": round(total_with_ms / 1000, 2),
            },
            "savings_factor": round(total_without_ms / total_with_ms, 1) if total_with_ms > 0 else 0,
            "total_cost_without": round(total_cost_without, 4),
            "total_cost_with": round(total_cost_with, 4),
            "total_cost_saved": round(total_cost_without - total_cost_with, 4),
            "total_tokens_without": total_tokens_without,
            "total_tokens_with": total_tokens_with,
            "pricing_updated": get_updated_at(),
            "pricing_stale": is_stale(),
        }

        # Conversation session log — all recent interactions
        conversations: list[dict] = []
        try:
            memory = _get_project_memory()
            convs = memory.list_recent(limit=100)
            conversations = [
                {
                    "id": c.id,
                    "project_id": c.project_id,
                    "user_message": c.user_message,
                    "assistant_response": c.assistant_response[:200],
                    "model_used": c.model_used,
                    "cache_hit": c.cache_hit,
                    "generation_ms": c.generation_ms,
                    "rating": c.rating,
                    "created_at": str(c.created_at) if c.created_at else None,
                }
                for c in convs
            ]
        except Exception:
            logger.debug("Could not load conversations for admin metrics", exc_info=True)

        # Provider status detection (async to avoid blocking on Ollama check)
        providers = await _detect_providers()

        # Load accuracy metrics from test results if available
        accuracy = _load_accuracy_metrics()

        return {
            "cache": cache,
            "documents": documents_data,
            "providers": providers,
            "comparison": comparison,
            "accuracy": accuracy,
            "conversations": conversations,
        }

    except Exception:
        logger.exception("Failed to get admin metrics")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to retrieve admin metrics."},
        )


def _load_accuracy_metrics() -> dict:
    """Load accuracy metrics from the most recent test batch results."""
    import glob as g

    results_dir = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "overnight_results"
    batches = []
    overall_scores = []

    for fpath in sorted(g.glob(str(results_dir / "batch_*.json"))):
        try:
            data = json.loads(Path(fpath).read_text())
            acc = data.get("accuracy", {})
            if acc and acc.get("avg_score", 0) > 0:
                batches.append(
                    {
                        "batch": data.get("batch_num", 0),
                        "name": data.get("name", ""),
                        "accuracy": acc.get("avg_score", 0),
                        "relevance": acc.get("avg_relevance", 0),
                        "completeness": acc.get("avg_completeness", 0),
                        "coherence": acc.get("avg_coherence", 0),
                        "total": data.get("total", 0),
                    }
                )
                # Weight by number of results
                for _ in range(data.get("total", 1)):
                    overall_scores.append(acc.get("avg_score", 0))
        except Exception:  # noqa: S112 — project accuracy failure should not halt aggregation
            continue

    avg_overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0
    return {
        "overall_score": round(avg_overall, 3),
        "total_scored_batches": len(batches),
        "batches": batches,
    }


async def _detect_providers() -> dict:
    """Detect which providers are configured and their status."""
    # LLM providers
    llm_providers = []
    llm_checks = [
        ("anthropic", "ANTHROPIC_API_KEY", config.llm.anthropic_api_key),
        ("openai", "OPENAI_API_KEY", config.llm.openai_api_key),
        ("gemini", "GEMINI_API_KEY", config.llm.gemini_api_key),
        ("xai", "XAI_API_KEY", config.llm.xai_api_key),
        ("mistral", "MISTRAL_API_KEY", config.llm.mistral_api_key),
        ("perplexity", "PERPLEXITY_API_KEY", config.llm.perplexity_api_key),
        ("openrouter", "OPENROUTER_API_KEY", config.llm.openrouter_api_key),
        ("huggingface", "HF_API_KEY", config.llm.hf_api_key),
    ]
    resolved = config.llm.resolve_provider()
    resolved_model = config.llm.resolve_model()
    for name, env_var, key_value in llm_checks:
        is_primary = resolved == name
        is_fallback = config.llm.fallback == name
        role = "primary" if is_primary else ("fallback" if is_fallback else None)
        llm_providers.append(
            {
                "name": name,
                "configured": bool(key_value),
                "active": is_primary or is_fallback,
                "role": role,
                "model": resolved_model if is_primary else (config.llm.fallback_model if is_fallback else None),
            }
        )

    # Ollama (special — no API key, check connectivity)
    ollama_status = await _check_ollama_async(config.llm.ollama_url)
    is_ollama_primary = resolved == "ollama"
    is_ollama_fallback = config.llm.fallback == "ollama"
    ollama_role = "primary" if is_ollama_primary else ("fallback" if is_ollama_fallback else None)
    llm_providers.append(
        {
            "name": "ollama",
            "configured": True,
            "active": is_ollama_primary or is_ollama_fallback,
            "role": ollama_role,
            "model": resolved_model
            if is_ollama_primary
            else (config.llm.fallback_model if is_ollama_fallback else None),
            "status": ollama_status["status"],
            "models": ollama_status.get("models", []),
            "url": config.llm.ollama_url,
        }
    )

    # OpenAI-compatible (Groq, Together, etc.)
    if config.llm.openai_compatible_base_url or config.llm.url:
        is_compat_primary = resolved in ("openai_compatible", "auto")
        is_compat_fallback = config.llm.fallback == "openai_compatible"
        compat_role = "primary" if is_compat_primary else ("fallback" if is_compat_fallback else None)
        llm_providers.append(
            {
                "name": "openai_compatible",
                "configured": bool(config.llm.openai_compatible_api_key),
                "active": is_compat_primary or is_compat_fallback,
                "role": compat_role,
                "base_url": config.llm.openai_compatible_base_url,
            }
        )

    # Database backend
    database = [
        {
            "name": config.db.backend,
            "active": True,
            "details": _db_details(),
        }
    ]

    # Embedding provider
    embeddings = [
        {
            "name": config.embedding.provider,
            "active": True,
            "model": config.embedding.model,
            "dimensions": config.embedding.dimensions,
            "device": config.embedding.device,
        }
    ]

    # Vector store
    vector_store = []
    if config.vector_store.store:
        vector_store.append(
            {
                "name": config.vector_store.store,
                "active": True,
            }
        )
    else:
        vector_store.append(
            {
                "name": "database_builtin",
                "active": True,
                "note": "Using database backend for vector search (FTS5 in SQLite)",
            }
        )

    return {
        "llm": llm_providers,
        "database": database,
        "embeddings": embeddings,
        "vector_store": vector_store,
    }


def _db_details() -> dict:
    """Return database-specific connection details (non-sensitive)."""
    match config.db.backend:
        case "sqlite":
            return {"path": config.db.sqlite_path}
        case "postgresql" | "mysql":
            # Mask password in URL
            from urllib.parse import urlparse as _urlparse

            try:
                parsed = _urlparse(config.db.url)
                safe_url = f"{parsed.scheme}://{parsed.username}:****@{parsed.hostname}:{parsed.port}{parsed.path}"
                return {"url": safe_url}
            except Exception:
                return {"url": "****"}
        case "mongodb":
            return {"database": config.db.mongodb_db}
        case _:
            return {}


# ---------------------------------------------------------------------------
# Auth management endpoints
# ---------------------------------------------------------------------------

_key_manager = None


def _get_key_manager() -> APIKeyManager:
    global _key_manager
    if _key_manager is not None:
        return _key_manager
    with _init_lock:
        if _key_manager is None:
            backend = _get_ingest_backend()
            _key_manager = APIKeyManager(backend)
    return _key_manager


def _get_auth_dep(scopes: list[str] | None = None):
    """Build auth dependency using the database backend."""
    backend = _get_ingest_backend()
    return require_auth_db(backend=backend, scopes=scopes)


@app.get("/v1/auth/status", tags=["auth"])
async def auth_status():
    """Check if authentication is enabled."""
    return {"auth_enabled": is_auth_enabled()}


@app.post("/v1/auth/keys", tags=["auth"])
async def create_api_key_endpoint(request: Request):
    """Create a new API key. Requires admin scope and authentication to be enabled."""
    if not is_auth_enabled():
        return JSONResponse(
            status_code=403,
            content={"error": "API key management requires auth. Set BITMOD_AUTH_ENABLED=true."},
        )

    auth_dep = _get_auth_dep(scopes=["admin"])
    user = await auth_dep(
        authorization=request.headers.get("authorization"),
        x_api_key=request.headers.get("x-api-key"),
    )
    owner = user.subject

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})
    name = body.get("name", "Unnamed key")
    scopes = body.get("scopes", ["read", "write"])
    expires_in_days = body.get("expires_in_days")

    # Validate scopes
    allowed_scopes = {"read", "write", "admin", "ingest"}
    invalid = set(scopes) - allowed_scopes
    if invalid:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid scopes: {', '.join(invalid)}. Allowed: {', '.join(allowed_scopes)}"},
        )

    mgr = _get_key_manager()
    raw_key, record = mgr.create_key(
        name=name,
        owner=owner,
        scopes=scopes,
        expires_in_days=expires_in_days,
    )

    return JSONResponse(
        status_code=201,
        content={
            "key": raw_key,
            "id": record.id,
            "name": record.name,
            "scopes": record.scopes,
            "preview": record.key_preview,
            "expires_at": record.expires_at,
            "message": "Store this key securely. It will not be shown again.",
        },
    )


@app.get("/v1/auth/keys", tags=["auth"])
async def list_api_keys_endpoint(request: Request):
    """List all API keys (hashes only, not plaintext)."""
    if not is_auth_enabled():
        return JSONResponse(
            status_code=403,
            content={"error": "API key management requires auth. Set BITMOD_AUTH_ENABLED=true."},
        )

    auth_dep = _get_auth_dep(scopes=["admin"])
    await auth_dep(
        authorization=request.headers.get("authorization"),
        x_api_key=request.headers.get("x-api-key"),
    )
    mgr = _get_key_manager()
    keys = mgr.list_keys()
    return {
        "keys": [
            {
                "id": k.id,
                "name": k.name,
                "preview": k.key_preview,
                "scopes": k.scopes,
                "owner": k.owner,
                "is_active": k.is_active,
                "created_at": k.created_at,
                "last_used_at": k.last_used_at,
                "expires_at": k.expires_at,
            }
            for k in keys
        ],
    }


@app.delete("/v1/auth/keys/{key_id}", tags=["auth"])
async def revoke_api_key_endpoint(request: Request, key_id: str):
    """Revoke an API key."""
    if not is_auth_enabled():
        return JSONResponse(
            status_code=403,
            content={"error": "API key management requires auth. Set BITMOD_AUTH_ENABLED=true."},
        )

    auth_dep = _get_auth_dep(scopes=["admin"])
    await auth_dep(
        authorization=request.headers.get("authorization"),
        x_api_key=request.headers.get("x-api-key"),
    )
    mgr = _get_key_manager()
    revoked = mgr.revoke_key(key_id)
    if not revoked:
        return JSONResponse(status_code=404, content={"error": "Key not found or already revoked."})
    return {"status": "revoked", "key_id": key_id}


@app.post("/v1/auth/token", tags=["auth"])
async def create_token_endpoint(request: Request):
    """Create a JWT token from a valid API key. Token-exchange flow."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})
    api_key = body.get("api_key", "")
    requested_scopes = body.get("scopes")
    expiry = body.get("expiry_seconds")

    if not api_key:
        return JSONResponse(status_code=400, content={"error": "api_key is required."})

    mgr = _get_key_manager()
    record = mgr.validate_key(api_key)

    if record is None:
        # Try env-var keys
        from bitmod.auth import lookup_api_key_scopes, validate_api_key

        if not validate_api_key(api_key):
            return JSONResponse(status_code=401, content={"error": "Invalid API key."})
        allowed_scopes, _prefix = lookup_api_key_scopes(api_key)
        scopes = requested_scopes or allowed_scopes
        # Cannot escalate beyond the env-var key's scopes
        invalid = set(scopes) - set(allowed_scopes)
        if invalid:
            return JSONResponse(
                status_code=403,
                content={"error": f"Cannot grant scopes beyond key permissions: {', '.join(invalid)}"},
            )
        subject = "api_key_user"
    else:
        scopes = requested_scopes or record.scopes
        # Cannot escalate beyond key's scopes
        invalid = set(scopes) - set(record.scopes)
        if invalid:
            return JSONResponse(
                status_code=403,
                content={"error": f"Cannot grant scopes beyond key permissions: {', '.join(invalid)}"},
            )
        subject = record.owner

    try:
        token = create_jwt_token(subject=subject, scopes=scopes, expiry_seconds=expiry)
        return {"token": token, "subject": subject, "scopes": scopes}
    except RuntimeError as e:
        logger.error("JWT token creation failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "Token creation failed. Check server configuration."})
    except ImportError:
        return JSONResponse(status_code=501, content={"error": "JWT not available. Install PyJWT."})


@app.post("/v1/auth/refresh", tags=["auth"])
async def refresh_token_endpoint(request: Request):
    """Refresh a JWT token. Requires a valid, non-expired token with >5 min remaining."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Bearer token required."})

    token = auth_header[7:].strip()
    if not token:
        return JSONResponse(status_code=401, content={"error": "Empty bearer token."})

    user = verify_jwt_token(token)
    if user is None:
        return JSONResponse(status_code=401, content={"error": "Invalid or expired token."})

    # Ensure token has >5 min remaining (prevent refresh of nearly-expired tokens)
    exp = user.metadata.get("exp", 0)
    if exp - time.time() < 300:
        return JSONResponse(status_code=400, content={"error": "Token too close to expiry. Re-authenticate."})

    # Revoke old token
    old_jti = user.metadata.get("jti", "")
    if old_jti:
        revoke_token(old_jti, expires_at=exp)

    # Issue new token with same scopes
    try:
        new_token = create_jwt_token(subject=user.subject, scopes=user.scopes)
        return {"token": new_token, "subject": user.subject, "scopes": user.scopes}
    except RuntimeError as e:
        logger.error("Token refresh failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "Token refresh failed."})
    except ImportError:
        return JSONResponse(status_code=501, content={"error": "JWT not available."})


async def _check_ollama_async(base_url: str) -> dict:
    """Check Ollama connectivity and available models (async, non-blocking)."""
    import httpx as _httpx

    try:
        async with _httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return {"status": "online", "models": models}
            return {"status": "error", "models": []}
    except _httpx.ConnectError:
        return {"status": "offline", "models": []}
    except Exception:
        return {"status": "unknown", "models": []}


def _check_ollama(base_url: str) -> dict:
    """Check Ollama connectivity (sync fallback). Prefer _check_ollama_async."""
    import httpx as _httpx

    try:
        with _httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return {"status": "online", "models": models}
            return {"status": "error", "models": []}
    except _httpx.ConnectError:
        return {"status": "offline", "models": []}
    except Exception:
        return {"status": "unknown", "models": []}


# ---------------------------------------------------------------------------
# Phase 1: Public Shared Knowledge Cache
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cache metadata headers on proxy responses
# ---------------------------------------------------------------------------


def _add_cache_headers(response: JSONResponse, result: dict, debug: dict | None = None) -> JSONResponse:
    """Add X-Bitmod-* cache metadata headers to proxy responses.

    ``debug`` carries per-layer attribution from the pipeline and is only
    populated when debug output is enabled — see bitmod.proxy.debug. It is
    merged last so its values win: the layer it reports comes from the evidence
    that was actually served, while x_bitmod_cache_layer below defaults to
    "exact" whenever the trace has no HIT step, which is every serve decided on
    accumulated confidence.
    """
    cached = result.get("x_bitmod_cached", False)
    response.headers["X-Bitmod-Cache-Hit"] = str(cached).lower()

    if cached:
        layer = result.get("x_bitmod_cache_layer", "exact")
        serve_count = result.get("x_bitmod_serve_count", 0)
        saved = result.get("x_bitmod_saved", 0.0)

        response.headers["X-Bitmod-Cache-Layer"] = layer
        response.headers["X-Bitmod-Serve-Count"] = str(serve_count)
        response.headers["X-Bitmod-Saved"] = f"${saved:.4f}"

    for name, value in (debug or {}).items():
        response.headers[name] = value

    return response


# ---------------------------------------------------------------------------
# Usage tracking endpoints — enterprise cost justification
# ---------------------------------------------------------------------------


@app.get("/v1/usage", tags=["usage"])
async def usage_summary(request: Request, days: int = 30, tenant_id: str = "default"):
    """Return usage summary with cost savings for procurement dashboards.

    Requires auth with 'read' scope when authentication is enabled.

    Query params:
        days: Number of days to look back (default 30)
        tenant_id: Tenant identifier (default "default")
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["read"])
        await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )

    from bitmod.usage import UsageTracker

    backend = _get_ingest_backend()
    tracker = UsageTracker(backend)

    summary = tracker.get_summary(tenant_id=tenant_id, days=days)
    daily = tracker.get_daily_breakdown(tenant_id=tenant_id, days=days)

    return {
        "tenant_id": summary.tenant_id,
        "period_days": summary.days,
        "total_queries": summary.total_queries,
        "cache_hits": summary.cache_hits,
        "cache_misses": summary.cache_misses,
        "hit_rate_pct": summary.hit_rate_pct,
        "total_input_tokens": summary.total_input_tokens,
        "total_output_tokens": summary.total_output_tokens,
        "estimated_cost_usd": summary.estimated_cost_usd,
        "estimated_savings_usd": summary.estimated_savings_usd,
        "top_models": summary.top_models,
        "daily_breakdown": [
            {
                "date": d.date,
                "total_queries": d.total_queries,
                "cache_hits": d.cache_hits,
                "cache_misses": d.cache_misses,
                "hit_rate_pct": d.hit_rate_pct,
                "estimated_cost_usd": d.estimated_cost_usd,
                "estimated_savings_usd": d.estimated_savings_usd,
            }
            for d in daily
        ],
    }


@app.get("/v1/usage/export", tags=["usage"])
async def usage_export(request: Request, days: int = 30, tenant_id: str = "default"):
    """Export usage data as CSV for finance teams.

    Requires auth with 'read' scope when authentication is enabled.
    Returns text/csv with daily cost breakdown.
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["read"])
        await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )

    from bitmod.usage import UsageTracker

    backend = _get_ingest_backend()
    tracker = UsageTracker(backend)

    summary = tracker.get_summary(tenant_id=tenant_id, days=days)
    daily = tracker.get_daily_breakdown(tenant_id=tenant_id, days=days)

    lines = [
        "date,total_queries,cache_hits,cache_misses,hit_rate_pct,estimated_cost_usd,estimated_savings_usd",
    ]
    for d in daily:
        lines.append(
            f"{d.date},{d.total_queries},{d.cache_hits},{d.cache_misses},"
            f"{d.hit_rate_pct},{d.estimated_cost_usd:.6f},{d.estimated_savings_usd:.6f}"
        )

    # Summary row
    lines.append("")
    lines.append(f"# Summary for {tenant_id} (last {days} days)")
    lines.append(f"# Total queries: {summary.total_queries}")
    lines.append(f"# Cache hit rate: {summary.hit_rate_pct}%")
    lines.append(f"# Total cost: ${summary.estimated_cost_usd:.6f}")
    lines.append(f"# Total savings: ${summary.estimated_savings_usd:.6f}")

    csv_content = "\n".join(lines) + "\n"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=bitmod_usage_{tenant_id}_{days}d.csv",
        },
    )


# ---------------------------------------------------------------------------
# Namespace management endpoints (multi-tenant isolation)
# ---------------------------------------------------------------------------

_namespace_manager = None


def _get_namespace_manager():
    global _namespace_manager
    if _namespace_manager is None:
        from bitmod.namespaces import NamespaceManager

        backend = _get_ingest_backend()
        _namespace_manager = NamespaceManager(backend)
    return _namespace_manager


@app.post("/v1/namespaces", tags=["namespaces"])
async def create_namespace(request: Request):
    """Create a new namespace for cache isolation.

    Requires auth with 'admin' scope.

    Request body:
        {"name": "my-tenant", "isolation": "strict", "public_fallback": true}
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["admin"])
        user = await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )
        owner_key_id = user.subject
    else:
        owner_key_id = "system"

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Namespace 'name' is required."})

    isolation = body.get("isolation", "strict")
    public_fallback = body.get("public_fallback", True)

    mgr = _get_namespace_manager()
    try:
        ns = mgr.create(
            name=name,
            owner_key_id=owner_key_id,
            isolation=isolation,
            public_fallback=bool(public_fallback),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return JSONResponse(status_code=409, content={"error": f"Namespace '{name}' already exists."})
        logger.exception("Failed to create namespace")
        return JSONResponse(status_code=500, content={"error": "Failed to create namespace."})

    return JSONResponse(status_code=201, content=ns.to_dict())


@app.get("/v1/namespaces", tags=["namespaces"])
async def list_namespaces(request: Request):
    """List namespaces for the authenticated user.

    Requires auth with 'admin' scope.
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["admin"])
        user = await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )
        owner_key_id = user.subject
    else:
        owner_key_id = None  # List all when no auth

    mgr = _get_namespace_manager()
    if owner_key_id:
        namespaces = mgr.list_for_owner(owner_key_id)
    else:
        namespaces = mgr.list_all()

    return {"namespaces": [ns.to_dict() for ns in namespaces]}


@app.get("/v1/namespaces/{namespace_id}", tags=["namespaces"])
async def get_namespace(request: Request, namespace_id: str):
    """Get namespace details.

    Requires auth with 'admin' scope.
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["admin"])
        await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )

    mgr = _get_namespace_manager()
    ns = mgr.get(namespace_id)
    if ns is None:
        return JSONResponse(status_code=404, content={"error": "Namespace not found."})

    return ns.to_dict()


@app.delete("/v1/namespaces/{namespace_id}", tags=["namespaces"])
async def delete_namespace(request: Request, namespace_id: str):
    """Delete a namespace. Only the owner can delete.

    Requires auth with 'admin' scope.
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["admin"])
        user = await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )
        owner_key_id = user.subject
    else:
        owner_key_id = "system"

    mgr = _get_namespace_manager()
    deleted = mgr.delete(namespace_id, owner_key_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "Namespace not found or not authorized."})

    return {"status": "deleted", "namespace_id": namespace_id}


@app.get("/v1/namespaces/{namespace_id}/stats", tags=["namespaces"])
async def namespace_cache_stats(request: Request, namespace_id: str):
    """Get cache statistics scoped to a specific namespace.

    Requires auth with 'admin' scope.
    """
    if is_auth_enabled():
        auth_dep = _get_auth_dep(scopes=["admin"])
        await auth_dep(
            authorization=request.headers.get("authorization"),
            x_api_key=request.headers.get("x-api-key"),
        )

    mgr = _get_namespace_manager()
    ns = mgr.get(namespace_id)
    if ns is None:
        return JSONResponse(status_code=404, content={"error": "Namespace not found."})

    stats = mgr.get_cache_stats(namespace_id)
    stats["namespace"] = ns.to_dict()
    return stats


# ===========================================================================
# Project Knowledge System
# ===========================================================================

_project_indexer = None
_project_memory = None
_project_lock = threading.Lock()


def _get_project_indexer():
    """Lazy-init project indexer with shared backend and embedder."""
    global _project_indexer
    if _project_indexer is not None:
        return _project_indexer
    with _project_lock:
        if _project_indexer is None:
            from bitmod.project.indexer import ProjectIndexer

            backend = _get_ingest_backend()
            embedder = _get_ingest_embedder()
            embed_fn = embedder.embed_batch if embedder else None
            _project_indexer = ProjectIndexer(db=backend, embed_fn=embed_fn)
    return _project_indexer


def _get_project_memory():
    """Lazy-init conversation memory."""
    global _project_memory
    if _project_memory is not None:
        return _project_memory
    with _project_lock:
        if _project_memory is None:
            from bitmod.project.memory import ConversationMemory

            backend = _get_ingest_backend()
            embedder = _get_ingest_embedder()
            embed_fn = embedder.embed_batch if embedder else None
            _project_memory = ConversationMemory(db=backend, embed_fn=embed_fn)
    return _project_memory


@app.post("/v1/projects", tags=["projects"])
async def create_project(
    request: Request,
    body: ProjectCreateRequest,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["write"])),
):
    """Register a project directory for knowledge tracking."""
    # C2: Validate root_path against allowed base directories
    from bitmod.security import validate_file_path

    allowed_dirs_raw = os.getenv("BITMOD_PROJECT_ALLOWED_DIRS", "")
    allowed_dirs = (
        [d.strip() for d in allowed_dirs_raw.split(",") if d.strip()] if allowed_dirs_raw else [os.path.expanduser("~")]
    )
    try:
        resolved = validate_file_path(body.root_path, allowed_base_dirs=allowed_dirs)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid project path."})

    if not os.path.isdir(resolved):
        return JSONResponse(status_code=400, content={"error": "Path is not an existing directory."})

    # Resolve symlinks and re-check
    real_path = os.path.realpath(resolved)
    if not any(
        real_path.startswith(os.path.realpath(os.path.abspath(d)) + os.sep)
        or real_path == os.path.realpath(os.path.abspath(d))
        for d in allowed_dirs
    ):
        return JSONResponse(status_code=400, content={"error": "Invalid project path."})

    indexer = _get_project_indexer()
    try:
        project = indexer.register_project(
            root_path=real_path,
            name=body.name,
            description=body.description,
        )
        logger.info(
            "Project created: id=%s name=%s user=%s correlation_id=%s",
            project.id,
            project.name,
            _user.subject,
            get_correlation_id(),
        )
        return ProjectResponse(
            id=project.id,
            name=project.name,
            root_path=project.root_path,
            description=project.description,
            language=project.language,
            framework=project.framework,
            is_active=project.is_active,
            file_count=project.file_count,
            total_chunks=project.total_chunks,
            last_scanned_at=project.last_scanned_at,
        )
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid request."})
    except Exception:
        logger.exception("Failed to create project")
        return JSONResponse(status_code=500, content={"error": "Internal server error."})


@app.get("/v1/projects", tags=["projects"])
async def list_projects(
    request: Request,
    active_only: bool = True,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """List registered projects."""
    backend = _get_ingest_backend()
    with backend.session() as s:
        projects = backend.project_list(s, active_only=active_only)
    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            root_path=p.root_path,
            description=p.description,
            language=p.language,
            framework=p.framework,
            is_active=p.is_active,
            file_count=p.file_count,
            total_chunks=p.total_chunks,
            last_scanned_at=p.last_scanned_at,
        )
        for p in projects
    ]


@app.get("/v1/projects/{project_id}", tags=["projects"])
async def get_project(
    request: Request,
    project_id: str,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """Get a project by ID."""
    backend = _get_ingest_backend()
    with backend.session() as s:
        project = backend.project_get(s, project_id)
    if not project:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    return ProjectResponse(
        id=project.id,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
        language=project.language,
        framework=project.framework,
        is_active=project.is_active,
        file_count=project.file_count,
        total_chunks=project.total_chunks,
        last_scanned_at=project.last_scanned_at,
    )


@app.delete("/v1/projects/{project_id}", tags=["projects"])
async def delete_project(
    request: Request,
    project_id: str,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["admin"])),
):
    """Delete a project and all its indexed data."""
    indexer = _get_project_indexer()
    try:
        indexer.remove_project(project_id)
        logger.info("Project deleted: id=%s user=%s correlation_id=%s", project_id, _user.subject, get_correlation_id())
        return {"status": "deleted", "project_id": project_id}
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "Resource not found."})
    except Exception:
        logger.exception("Failed to delete project %s", project_id)
        return JSONResponse(status_code=500, content={"error": "Internal server error."})


@app.post("/v1/projects/{project_id}/scan", tags=["projects"])
async def scan_project(
    request: Request,
    project_id: str,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["write"])),
):
    """Scan/re-scan a project directory and index changed files."""
    indexer = _get_project_indexer()
    try:
        stats = indexer.scan(project_id)
        logger.info(
            "Project scanned: id=%s files=%d changed=%d user=%s correlation_id=%s",
            project_id,
            stats.get("files_scanned", 0),
            stats.get("files_changed", 0),
            _user.subject,
            get_correlation_id(),
        )
        return ProjectScanResponse(project_id=project_id, **stats)
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "Resource not found."})
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": "Resource not found."})
    except Exception:
        logger.exception("Failed to scan project %s", project_id)
        return JSONResponse(status_code=500, content={"error": "Internal server error."})


@app.get("/v1/history", tags=["history"])
async def list_conversations(
    request: Request,
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """List conversation history, optionally filtered by project."""
    memory = _get_project_memory()
    convs = memory.list_recent(project_id=project_id, limit=limit, offset=offset)
    return [
        ConversationResponse(
            id=c.id,
            project_id=c.project_id,
            user_message=c.user_message,
            assistant_response=c.assistant_response,
            model_used=c.model_used,
            cache_hit=c.cache_hit,
            rating=c.rating,
            feedback=c.feedback,
            generation_ms=c.generation_ms,
            created_at=str(c.created_at) if c.created_at else None,
        )
        for c in convs
    ]


@app.post("/v1/conversations/{conversation_id}/rate", tags=["history"])
async def rate_conversation(
    request: Request,
    conversation_id: str,
    body: ConversationRateRequest,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["write"])),
):
    """Rate a conversation (1-5) with optional feedback."""
    memory = _get_project_memory()
    try:
        memory.rate(conversation_id, body.rating, body.feedback)
        logger.info(
            "Conversation rated: id=%s rating=%d user=%s correlation_id=%s",
            conversation_id,
            body.rating,
            _user.subject,
            get_correlation_id(),
        )
        return {"status": "rated", "conversation_id": conversation_id, "rating": body.rating}
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "Resource not found."})


@app.post("/v1/conversations/{conversation_id}/correct", tags=["history"])
async def correct_conversation(
    request: Request,
    conversation_id: str,
    body: CorrectionRequest,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["write"])),
):
    """Submit a correction for an AI response."""
    memory = _get_project_memory()
    try:
        # H4: Auto-approve corrections from admin users, otherwise pending
        is_admin = "admin" in _user.scopes
        correction = memory.correct(
            conversation_id=conversation_id,
            corrected_answer=body.corrected_answer,
            correction_type=body.correction_type,
            status="approved" if is_admin else "pending",
        )
        logger.info(
            "Correction submitted: id=%s conversation=%s status=%s user=%s correlation_id=%s",
            correction.id,
            conversation_id,
            "approved" if is_admin else "pending",
            _user.subject,
            get_correlation_id(),
        )
        return CorrectionResponse(
            id=correction.id,
            conversation_id=correction.conversation_id,
            project_id=correction.project_id,
            original_question=correction.original_question,
            corrected_answer=correction.corrected_answer,
            correction_type=correction.correction_type,
            created_at=str(correction.created_at) if correction.created_at else None,
        )
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "Resource not found."})


@app.post("/v1/context", tags=["projects"])
async def assemble_context(
    request: Request,
    body: ContextRequest,
    _user: AuthUser = Depends(lambda: _get_auth_dep(scopes=["read"])),
):
    """Assemble project-aware context for a query.

    Returns relevant project code, past conversations, and corrections
    that can be injected into an LLM prompt.
    """
    from bitmod.project.context import ContextAssembler

    backend = _get_ingest_backend()
    embedder = _get_ingest_embedder()
    embed_fn = embedder.embed_batch if embedder else None

    assembler = ContextAssembler(
        db=backend,
        embed_fn=embed_fn,
        token_budget=body.token_budget,
    )
    ctx = assembler.assemble(
        query=body.query,
        project_id=body.project_id,
        include_history=body.include_history,
        include_corrections=body.include_corrections,
    )
    return ContextResponse(
        project_context=ctx.project_context,
        history_context=ctx.history_context,
        corrections_context=ctx.corrections_context,
        total_tokens=ctx.total_tokens,
        sources=ctx.sources,
    )
