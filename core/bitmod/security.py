"""Security utilities: input sanitization, rate limiting, injection prevention.

Provides defense-in-depth for:
- XSS prevention via HTML entity encoding
- SQL injection pattern detection
- Path traversal prevention for file ingestion
- Rate limiting with stale entry cleanup
- Content length enforcement
"""

from __future__ import annotations

import html
import logging
import os
import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable

from bitmod.metrics import record_security_event
from bitmod.observability import log_security_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL injection patterns (used as an additional defense layer;
# parameterized queries are the primary defense)
# ---------------------------------------------------------------------------

_SQL_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"(\b(UNION|SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC|EXECUTE)\b\s)",
        r"(--\s|;\s*DROP|;\s*DELETE|;\s*UPDATE|;\s*INSERT)",
        r"(\b(OR|AND)\b\s+\d+\s*=\s*\d+)",
        r"(\bOR\b\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+['\"]?)",
        r"(SLEEP\s*\(|BENCHMARK\s*\(|WAITFOR\s+DELAY)",
        r"(LOAD_FILE\s*\(|INTO\s+OUTFILE|INTO\s+DUMPFILE)",
        r"(CHAR\s*\(\d+\)|0x[0-9a-fA-F]+)",
    ]
]

# Maximum input length for user-facing text fields
MAX_INPUT_LENGTH = 10_000

# Maximum file size for ingestion (50 MB)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Allowed file extensions for ingestion
ALLOWED_FILE_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".html",
        ".htm",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".txt",
        ".text",
        ".log",
        ".rst",
    }
)


def sanitize_input(text: str) -> str:
    """Sanitize user input for LLM/cache/internal processing.

    - Strips null bytes (prevents null-byte injection)
    - Enforces maximum length
    - Does NOT HTML-encode (preserves query semantics for LLM and cache)
    - Does NOT strip SQL keywords (parameterized queries handle that)

    For HTML rendering contexts, use ``sanitize_for_html()`` instead.
    """
    if not isinstance(text, str):
        return ""
    # Remove null bytes
    text = text.replace("\x00", "")
    # Enforce length limit
    return text[:MAX_INPUT_LENGTH]


def sanitize_for_html(text: str) -> str:
    """Sanitize user input for rendering in HTML/web responses.

    - Strips null bytes
    - HTML-encodes special characters (prevents stored/reflected XSS)
    - Enforces maximum length
    """
    if not isinstance(text, str):
        return ""
    text = text.replace("\x00", "")
    text = html.escape(text, quote=True)
    return text[:MAX_INPUT_LENGTH]


def sanitize_html(text: str) -> str:
    """Strip all HTML tags from text, then entity-encode the result."""
    if not isinstance(text, str):
        return ""
    stripped = re.sub(r"<[^>]+>", "", text)
    return html.escape(stripped, quote=True)


def detect_sql_injection(text: str) -> bool:
    """Check if text contains common SQL injection patterns.

    This is a defense-in-depth measure. Parameterized queries are the
    primary protection. Returns True if suspicious patterns detected.
    """
    if not isinstance(text, str):
        return False
    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning("SQL injection pattern detected in input (blocked)")
            record_security_event("injection_blocked")
            log_security_event("injection_blocked", pattern=pattern.pattern)
            return True
    return False


def validate_file_path(file_path: str, allowed_base_dirs: list[str] | None = None) -> str:
    """Validate and resolve a file path, preventing path traversal attacks.

    Args:
        file_path: The file path to validate.
        allowed_base_dirs: Optional list of allowed base directories.
            If provided, the resolved path must be under one of these.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If the path is invalid, contains traversal sequences,
            or is outside allowed directories.
    """
    if not file_path or not isinstance(file_path, str):
        raise ValueError("File path must be a non-empty string")

    # Strip null bytes
    file_path = file_path.replace("\x00", "")

    # Reject obvious traversal patterns before resolving
    if ".." in file_path:
        raise ValueError("Path traversal detected: '..' is not allowed in file paths")

    # Resolve to absolute path (resolves symlinks too)
    resolved = os.path.realpath(os.path.abspath(file_path))

    # Check against allowed base directories
    if allowed_base_dirs:
        allowed = False
        for base_dir in allowed_base_dirs:
            base_resolved = os.path.realpath(os.path.abspath(base_dir))
            if resolved.startswith(base_resolved + os.sep) or resolved == base_resolved:
                allowed = True
                break
        if not allowed:
            raise ValueError(f"File path is outside allowed directories. Resolved path: {resolved}")

    return resolved


def validate_file_for_ingestion(file_path: str, allowed_base_dirs: list[str] | None = None) -> str:
    """Validate a file path for the ingestion pipeline.

    Checks: path traversal, file existence, extension allowlist, file size.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If validation fails.
        FileNotFoundError: If file does not exist.
    """
    resolved = validate_file_path(file_path, allowed_base_dirs)

    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")

    # Check extension
    _, ext = os.path.splitext(resolved)
    ext = ext.lower()
    if ext not in ALLOWED_FILE_EXTENSIONS:
        raise ValueError(
            f"File extension '{ext}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_FILE_EXTENSIONS))}"
        )

    # Check file size
    file_size = os.path.getsize(resolved)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File size ({file_size:,} bytes) exceeds maximum ({MAX_FILE_SIZE_BYTES:,} bytes)")

    if file_size == 0:
        raise ValueError("File is empty")

    return resolved


def mask_sensitive_value(value: str, visible_chars: int = 4) -> str:
    """Mask a sensitive value (API key, password, etc.) for safe logging.

    Shows first N characters, masks the rest with asterisks.
    """
    if not value or len(value) <= visible_chars:
        return "****"
    return value[:visible_chars] + "*" * (len(value) - visible_chars)


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------


class InMemoryRateLimiter:
    """Thread-safe in-memory rate limiter per client ID.

    For production, use Redis-backed rate limiting.

    Includes periodic cleanup of stale entries to prevent memory leaks.

    Args:
        cleanup_interval: Seconds between stale-entry cleanup sweeps.
        max_clients: Maximum tracked clients before oldest are pruned.
        clock: Callable returning current time as a float. Defaults to
            ``time.monotonic``. Inject a controllable clock for testing.
    """

    def __init__(
        self,
        cleanup_interval: int = 300,
        max_clients: int = 10_000,
        clock: Callable[[], float] | None = None,
    ):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic
        self._last_cleanup = self._clock()
        self._cleanup_interval = cleanup_interval
        self._max_clients = max_clients

    def is_allowed(self, client_id: str, max_requests: int, window_seconds: int) -> bool:
        """Check if a request is allowed under the rate limit.

        Uses the injected clock (monotonic by default) to avoid issues
        with clock skew or NTP adjustments.
        """
        now = self._clock()

        with self._lock:
            self._maybe_cleanup(now, window_seconds)

            cutoff = now - window_seconds
            # Clean old entries for this client
            self._requests[client_id] = [t for t in self._requests[client_id] if t > cutoff]

            if len(self._requests[client_id]) >= max_requests:
                record_security_event("rate_limited")
                log_security_event("rate_limited", client_id=client_id)
                return False

            self._requests[client_id].append(now)
            return True

    def remaining(self, client_id: str, max_requests: int, window_seconds: int) -> int:
        """Get remaining requests in the current window."""
        now = self._clock()
        with self._lock:
            cutoff = now - window_seconds
            recent = [t for t in self._requests[client_id] if t > cutoff]
            return max(0, max_requests - len(recent))

    def reset_seconds(self, client_id: str, window_seconds: int) -> int:
        """Seconds until the oldest request in the current window expires."""
        now = self._clock()
        with self._lock:
            cutoff = now - window_seconds
            recent = [t for t in self._requests[client_id] if t > cutoff]
            if not recent:
                return 0
            oldest = min(recent)
            return max(0, int((oldest + window_seconds) - now))

    def _maybe_cleanup(self, now: float, window_seconds: int) -> None:
        """Periodically remove stale client entries to prevent memory leaks.

        Also enforces max_clients to prevent memory exhaustion from
        distributed attacks with many unique IPs.
        """
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        cutoff = now - window_seconds

        # Remove clients with no recent requests
        stale_clients = [
            client_id
            for client_id, timestamps in self._requests.items()
            if not timestamps or all(t <= cutoff for t in timestamps)
        ]
        for client_id in stale_clients:
            del self._requests[client_id]

        # If still too many clients, remove oldest entries
        if len(self._requests) > self._max_clients:
            sorted_clients = sorted(
                self._requests.items(),
                key=lambda item: max(item[1]) if item[1] else 0,
            )
            excess = len(self._requests) - self._max_clients
            for client_id, _ in sorted_clients[:excess]:
                del self._requests[client_id]

            logger.warning(
                "Rate limiter pruned %d stale client entries (max_clients=%d)",
                excess,
                self._max_clients,
            )


# ---------------------------------------------------------------------------
# Redis-Backed Rate Limiter
# ---------------------------------------------------------------------------


class RedisRateLimiter:
    """Redis-backed sliding-window rate limiter.

    Uses INCR + EXPIRE on window-bucketed keys for distributed rate limiting.
    Falls back to InMemoryRateLimiter if Redis becomes unavailable.

    Key format: ``bitmod:ratelimit:{client_id}:{window_bucket}``

    The async Redis client is used internally. Sync wrappers (``is_allowed``
    and ``remaining``) are provided for compatibility with sync middleware.
    """

    def __init__(self, redis_url: str, fallback: InMemoryRateLimiter | None = None):
        self._redis_url = redis_url
        self._fallback = fallback or InMemoryRateLimiter()
        self._redis = None  # lazy-initialized async Redis client
        self._redis_available = True
        self._bg_loop = None  # Persistent event loop for sync wrappers
        import asyncio

        self._asyncio = asyncio

    # -- async Redis connection (lazy) --

    async def _get_redis(self):
        """Lazily connect to Redis. Returns None if unavailable."""
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(  # type: ignore[assignment]
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
            )
            # Verify connectivity
            await self._redis.ping()  # type: ignore[attr-defined]
            self._redis_available = True
            logger.info("Redis rate limiter connected: %s", self._redis_url)
            return self._redis
        except Exception as exc:
            logger.warning("Redis unavailable for rate limiting (%s), using in-memory fallback", exc)
            self._redis = None
            self._redis_available = False
            return None

    # -- key helpers --

    @staticmethod
    def _key(client_id: str, window_seconds: int) -> str:
        """Build the Redis key for the current window bucket."""
        bucket = int(time.time()) // window_seconds
        return f"bitmod:ratelimit:{client_id}:{bucket}"

    # -- async API --

    async def is_allowed_async(self, client_id: str, max_requests: int, window_seconds: int) -> bool:
        """Check if a request is allowed (async)."""
        r = await self._get_redis()
        if r is None:
            return self._fallback.is_allowed(client_id, max_requests, window_seconds)

        key = self._key(client_id, window_seconds)
        try:
            pipe = r.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            results = await pipe.execute()
            current_count = results[0]
            return current_count <= max_requests  # type: ignore[no-any-return]
        except Exception as exc:
            logger.debug("Redis rate limit check failed (%s), falling back to in-memory", exc)
            self._redis_available = False
            self._redis = None
            return self._fallback.is_allowed(client_id, max_requests, window_seconds)

    async def remaining_async(self, client_id: str, max_requests: int, window_seconds: int) -> int:
        """Get remaining requests in the current window (async)."""
        r = await self._get_redis()
        if r is None:
            return self._fallback.remaining(client_id, max_requests, window_seconds)

        key = self._key(client_id, window_seconds)
        try:
            current = await r.get(key)
            count = int(current) if current else 0
            return max(0, max_requests - count)
        except Exception:
            return self._fallback.remaining(client_id, max_requests, window_seconds)

    async def reset_seconds_async(self, client_id: str, window_seconds: int) -> int:
        """Seconds until the current rate-limit window resets (async)."""
        r = await self._get_redis()
        if r is None:
            return self._fallback.reset_seconds(client_id, window_seconds)

        key = self._key(client_id, window_seconds)
        try:
            ttl = await r.ttl(key)
            # ttl returns -2 if key doesn't exist, -1 if no expiry
            return max(0, ttl) if isinstance(ttl, int) and ttl > 0 else window_seconds
        except Exception:
            return self._fallback.reset_seconds(client_id, window_seconds)

    # -- sync wrappers (for non-async callers) --

    def _run_async(self, coro):
        """Run an async coroutine from synchronous context.

        Uses a single persistent thread+event loop to avoid creating a new
        ThreadPoolExecutor on every call.
        """
        try:
            loop = self._asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an async context — schedule on our persistent loop.
            # Prefer calling is_allowed_async/remaining_async directly from
            # async middleware instead of going through this sync wrapper.
            if self._bg_loop is None:
                self._start_bg_loop()
            future = self._asyncio.run_coroutine_threadsafe(coro, self._bg_loop)
            return future.result(timeout=3.0)
        else:
            return self._asyncio.run(coro)

    def _start_bg_loop(self):
        """Start a persistent background event loop for sync-to-async bridging."""
        import threading

        self._bg_loop = self._asyncio.new_event_loop()

        def _run():
            self._asyncio.set_event_loop(self._bg_loop)
            self._bg_loop.run_forever()  # type: ignore[attr-defined]

        t = threading.Thread(target=_run, daemon=True, name="redis-ratelimit-loop")
        t.start()

    def is_allowed(self, client_id: str, max_requests: int, window_seconds: int) -> bool:
        """Check if a request is allowed (sync wrapper).

        In async contexts (FastAPI middleware), call ``is_allowed_async``
        directly instead to avoid the sync-to-async bridge overhead.
        """
        try:
            return self._run_async(  # type: ignore[no-any-return]
                self.is_allowed_async(client_id, max_requests, window_seconds),
            )
        except Exception:
            return self._fallback.is_allowed(client_id, max_requests, window_seconds)

    def remaining(self, client_id: str, max_requests: int, window_seconds: int) -> int:
        """Get remaining requests (sync wrapper)."""
        try:
            return self._run_async(  # type: ignore[no-any-return]
                self.remaining_async(client_id, max_requests, window_seconds),
            )
        except Exception:
            return self._fallback.remaining(client_id, max_requests, window_seconds)

    def reset_seconds(self, client_id: str, window_seconds: int) -> int:
        """Seconds until window resets (sync wrapper)."""
        try:
            return self._run_async(  # type: ignore[no-any-return]
                self.reset_seconds_async(client_id, window_seconds),
            )
        except Exception:
            return self._fallback.reset_seconds(client_id, window_seconds)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_rate_limiter(redis_url: str | None = None) -> InMemoryRateLimiter | RedisRateLimiter:
    """Create the best available rate limiter.

    If *redis_url* is provided and the ``redis`` package is installed,
    returns a :class:`RedisRateLimiter` (which itself falls back to
    in-memory if Redis is unreachable at runtime).

    Otherwise returns an :class:`InMemoryRateLimiter`.
    """
    if redis_url:
        try:
            import redis.asyncio  # noqa: F401 — availability check

            return RedisRateLimiter(redis_url)
        except ImportError:
            logger.info("redis package not installed; using in-memory rate limiter. Install with: pip install redis")
    return InMemoryRateLimiter()
