"""Lightweight proxy app for pip-installed bitmod.

This creates a minimal FastAPI application that wraps the BitmodProxy
for use with `bitmod proxy`. It's a simplified version of the full
gateway service (services/gateway/app/main.py) that works without
the gateway service module being installed.

Usage:
    uvicorn bitmod.proxy.app:app --port 8001
    # or via CLI: bitmod proxy
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

# Import FastAPI types at module level so annotation resolution works
# with ``from __future__ import annotations``.
try:
    from fastapi import Depends, FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory rate limiter (per-IP, sliding window)
# ---------------------------------------------------------------------------

_RATE_LIMIT = int(os.getenv("BITMOD_RATE_LIMIT", "60"))  # requests per minute
_RATE_WINDOW = 60  # seconds

_rate_buckets: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def _check_rate_limit(ip: str) -> tuple[bool, int, int]:
    """Check if IP is within rate limit. Returns (allowed, remaining, reset_seconds)."""
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW

    with _rate_lock:
        hits = _rate_buckets.get(ip, [])
        # Prune expired entries
        hits = [t for t in hits if t > cutoff]

        # Periodic cleanup: drop stale IPs when bucket count is high
        if len(_rate_buckets) > 500:
            stale = [k for k, v in _rate_buckets.items() if not v or v[-1] < cutoff]
            for k in stale:
                del _rate_buckets[k]

        if len(hits) >= _RATE_LIMIT:
            reset = int(hits[0] - cutoff) + 1
            _rate_buckets[ip] = hits
            return False, 0, reset
        hits.append(now)
        _rate_buckets[ip] = hits
        remaining = _RATE_LIMIT - len(hits)
        return True, remaining, _RATE_WINDOW


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB


def create_proxy_app():
    """Create and return a FastAPI app with BitMod proxy endpoints."""
    if not _HAS_FASTAPI:
        raise ImportError("FastAPI is required for the proxy. Install with: pip install bitmod[server]")

    from bitmod.auth import is_auth_enabled, require_auth
    from bitmod.config import load_config

    config = load_config()

    _debug = os.getenv("BITMOD_DEBUG", "").lower() in ("1", "true", "yes")

    _app = FastAPI(
        title="BitMod Proxy",
        description="Intelligent LLM cache proxy — drop in, save tokens.",
        version="0.2.1",
        docs_url="/docs" if _debug else None,
        redoc_url="/redoc" if _debug else None,
        openapi_url="/openapi.json" if _debug else None,
    )

    # CORS — restrict methods and headers
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-API-Key"],
        expose_headers=["X-Response-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
        max_age=600,
    )

    # --- Middleware stack (executed bottom-to-top, declare in reverse order) ---

    # 1. Security headers
    @_app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        if "server" in response.headers:
            del response.headers["server"]
        return response

    # 2. Response time header
    @_app.middleware("http")
    async def response_time(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        return response

    # 3. Rate limiting
    @_app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        allowed, remaining, reset = _check_rate_limit(ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Try again later."},
                headers={
                    "Retry-After": str(reset),
                    "X-RateLimit-Limit": str(_RATE_LIMIT),
                    "X-RateLimit-Remaining": "0",
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    # 4. Body size enforcement
    @_app.middleware("http")
    async def enforce_body_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_BODY_SIZE:
                    return JSONResponse(status_code=413, content={"error": "Request body too large."})
            except (ValueError, OverflowError):
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length header."})

        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > MAX_BODY_SIZE:
                return JSONResponse(status_code=413, content={"error": "Request body too large."})

        return await call_next(request)

    # 5. CSRF protection (when auth is disabled)
    @_app.middleware("http")
    async def csrf_protection(request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            path = request.url.path
            if path not in ("/health", "/healthz"):
                if not is_auth_enabled():
                    xrw = request.headers.get("x-requested-with", "")
                    if not xrw:
                        return JSONResponse(
                            status_code=403,
                            content={"error": "Missing X-Requested-With header."},
                        )
        return await call_next(request)

    # --- Auth dependency ---
    auth_dep = require_auth(scopes=["read"])

    # --- Initialize proxy ---
    _proxy = None
    try:
        from bitmod.adapters import get_backend, get_embedder, get_llm
        from bitmod.proxy.base import BitmodProxy

        backend = get_backend(config.db)
        backend.initialize()
        llm = get_llm(config.llm)
        try:
            embedder = get_embedder(config.embedding)
        except Exception:
            embedder = None
        _proxy = BitmodProxy(backend, llm, embedder=embedder)  # type: ignore[arg-type]
        logger.info("BitMod proxy initialized successfully")
    except Exception as e:
        logger.warning("Proxy initialization incomplete: %s", e)

    # --- Routes ---

    @_app.get("/health")
    async def health():
        return {"status": "ok", "service": "bitmod-proxy", "version": "0.2.1"}

    @_app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @_app.post("/v1/chat/completions")
    async def chat_completions(request: Request, _user=Depends(auth_dep)):
        if _proxy is None:
            return JSONResponse(status_code=503, content={"error": "Proxy not initialized."})
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})
        try:
            result = await _proxy.handle_completion(body)
            return JSONResponse(content=result)
        except Exception:
            logger.exception("Proxy error handling chat completion")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error."},
            )

    @_app.get("/v1/models")
    async def list_models(_user=Depends(auth_dep)):
        return {"object": "list", "data": []}

    return _app


# Module-level app for uvicorn
app = create_proxy_app()
