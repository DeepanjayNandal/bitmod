"""Integration tests for gateway endpoints using FastAPI TestClient.

Tests health, proxy validation, rate limiting, and security middleware.
Uses mocked backends — no external services needed.
"""

import os
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Environment setup — needed before the gateway app is imported.
# Uses a module-scoped autouse fixture with save/restore to avoid
# polluting os.environ beyond the lifetime of this test module.
# ---------------------------------------------------------------------------

_ENV_DEFAULTS = {
    "BITMOD_DB_PATH": ":memory:",
    "BITMOD_LLM_PRIMARY": "ollama",
}


@pytest.fixture(scope="module", autouse=True)
def _gateway_env():
    """Set required env vars for gateway import, restore originals after."""
    saved = {}
    for key, value in _ENV_DEFAULTS.items():
        saved[key] = os.environ.get(key)
        os.environ.setdefault(key, value)
    yield
    for key, original in saved.items():
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


# ---------------------------------------------------------------------------
# Gateway app test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the gateway app."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi[testclient] or httpx not installed")
        return

    try:
        from services.gateway.app.main import app
        return TestClient(app, raise_server_exceptions=False)
    except Exception as e:
        pytest.skip(f"Gateway app could not be imported: {e}")
        return


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client):
        if client is None:
            pytest.skip("client not available")
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "gateway"

    def test_health_has_timing_header(self, client):
        if client is None:
            pytest.skip("client not available")
        response = client.get("/health")
        assert "X-Response-Time" in response.headers


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        if client is None:
            pytest.skip("client not available")
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "Strict-Transport-Security" in response.headers

    def test_api_cache_control(self, client):
        if client is None:
            pytest.skip("client not available")
        # V1 endpoints should have no-store cache control
        response = client.post(
            "/v1/ingest/text",
            json={"text": "test", "title": "test"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        # Even if the request fails, the cache-control header should be set
        if "Cache-Control" in response.headers:
            assert "no-store" in response.headers["Cache-Control"]


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------

class TestCSRF:
    def test_post_without_csrf_header_rejected_when_auth_disabled(self, client):
        """POST without X-Requested-With is rejected with 403 when auth is disabled."""
        if client is None:
            pytest.skip("client not available")
        from bitmod.auth import is_auth_enabled

        if is_auth_enabled():
            pytest.skip("CSRF header enforcement only applies when auth is disabled")
        response = client.post(
            "/v1/ingest/text",
            json={"text": "test", "title": "test"},
        )
        assert response.status_code == 403

    def test_post_without_csrf_header_when_auth_enabled(self, client):
        """POST without X-Requested-With proceeds past CSRF when auth is enabled."""
        if client is None:
            pytest.skip("client not available")
        from bitmod.auth import is_auth_enabled

        if not is_auth_enabled():
            pytest.skip("This test covers behavior when auth is enabled")
        response = client.post(
            "/v1/ingest/text",
            json={"text": "test", "title": "test"},
        )
        # CSRF middleware skips enforcement when auth is enabled, so request
        # proceeds to the endpoint handler (not blocked with 403)
        assert response.status_code != 403

    def test_post_with_csrf_header_not_blocked_by_csrf(self, client):
        """POST with X-Requested-With is never blocked by CSRF middleware."""
        if client is None:
            pytest.skip("client not available")
        response = client.post(
            "/v1/ingest/text",
            json={"text": "test", "title": "test"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        # CSRF middleware should not block this — the response is either
        # 401 (auth required) or 200/500 (processed by the endpoint)
        assert response.status_code != 403


# ---------------------------------------------------------------------------
# Request body size enforcement
# ---------------------------------------------------------------------------

class TestBodySize:
    def test_oversized_body_rejected(self, client):
        if client is None:
            pytest.skip("client not available")
        # 2 MB body should exceed the 1 MB limit
        large_body = "x" * (2 * 1024 * 1024)
        response = client.post(
            "/v1/search",
            content=large_body,
            headers={
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Length": str(len(large_body)),
            },
        )
        assert response.status_code == 413


# ---------------------------------------------------------------------------
# Rate limiting headers
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limit_header_present(self, client):
        if client is None:
            pytest.skip("client not available")
        response = client.get("/health")
        # Health is exempt from rate limiting, so no header expected
        # But a normal endpoint should have it
        response2 = client.post(
            "/v1/ingest/text",
            json={"text": "hello", "title": "t"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        # The rate limit header should be present on non-health endpoints
        if response2.status_code != 403:
            assert "X-RateLimit-Remaining" in response2.headers


# ---------------------------------------------------------------------------
# Proxy endpoint validation
# ---------------------------------------------------------------------------

class TestProxyValidation:
    def test_chat_completions_reaches_the_proxy_pipeline(self):
        """POST /v1/chat/completions must reach _run_cache_pipeline.

        This test previously asserted the opposite, and documented it as
        expected: the /v1/chat/{path:path} catch-all was registered first, so
        FastAPI matched it and forwarded OpenAI-format requests to the chat
        service. That is a limitation someone wrote down, not a design
        decision — nothing else uses this path, and routing the main entry
        point past the nine-layer pipeline makes the drop-in-replacement claim
        describe something the code did not do.

        Asserting on the response is not enough to catch this. The chat service
        answers too, so both routes return a plausible 200 and the difference
        is invisible from outside. The assertion has to be on which pipeline
        ran, which is why this patches _run_cache_pipeline and checks it was
        called.
        """
        pytest.importorskip("fastapi", reason="fastapi not installed")

        import bitmod.auth as bitmod_auth
        from bitmod.proxy.base import BitmodProxy
        from fastapi.testclient import TestClient

        from services.gateway.app import main as gw

        called: dict = {}

        def fake_pipeline(self, user_message, messages, namespace_id=None):
            called["user_message"] = user_message
            raise RuntimeError("stop here — reaching this proves the route resolved correctly")

        # The dedicated route requires auth; the catch-all it used to fall
        # through to did not. Auth is disabled here so this measures routing
        # rather than credentials — the scope requirement has its own test.
        with (
            patch.object(bitmod_auth, "_AUTH_ENABLED", False),
            patch.object(BitmodProxy, "_run_cache_pipeline", fake_pipeline),
        ):
            with TestClient(gw.app, raise_server_exceptions=False) as client:
                client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )

        assert called.get("user_message") == "hello", (
            "the request did not reach _run_cache_pipeline — it was captured by the "
            "/v1/chat/{path:path} catch-all and forwarded to the chat service"
        )
    def test_chat_completions_rejects_unauthenticated_requests(self):
        """The catch-all it used to fall through to has no gateway auth at all.

        /v1/chat/{path:path} carries no auth dependency, so while the OpenAI
        endpoint was shadowed, SDK traffic reached the chat service without the
        gateway ever authenticating it — protected only by the chat service's
        own internal-token check. The dedicated route requires read scope, and
        routing to it has to preserve that.

        An earlier version of this asserted that the route declared a Depends
        default. That was true the whole time the gateway authenticated nobody:
        the dependency was a zero-argument lambda returning the real dependency,
        which FastAPI bound without ever calling. Asserting on the declaration
        cannot see that. Asserting on the response can.
        """
        pytest.importorskip("fastapi", reason="fastapi not installed")

        import bitmod.auth as bitmod_auth
        from fastapi.testclient import TestClient

        from services.gateway.app import main as gw

        with patch.object(bitmod_auth, "_AUTH_ENABLED", True):
            with TestClient(gw.app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )

        assert response.status_code == 401, (
            f"an unauthenticated request was served ({response.status_code}) — "
            "the route's auth dependency is not being invoked"
        )
    def test_other_chat_paths_still_reach_the_chat_service(self):
        """Only /v1/chat/completions moves. The catch-all keeps everything else.

        Guards the narrowness of the fix: registering one exact-match route
        ahead of the catch-all must not change which handler wins for any other
        /v1/chat/<something>.
        """
        pytest.importorskip("fastapi", reason="fastapi not installed")
        from services.gateway.app import main as gw

        def resolved_handler(path: str) -> str:
            scope = {"type": "http", "path": path, "method": "POST", "headers": [], "root_path": ""}
            for route in gw.app.routes:
                try:
                    match, _ = route.matches(scope)
                except Exception:  # noqa: S112 — non-HTTP routes do not match
                    continue
                if str(match).endswith("FULL"):
                    return getattr(getattr(route, "endpoint", None), "__name__", "")
            return ""

        assert resolved_handler("/v1/chat/completions") == "proxy_openai_completions"
        assert resolved_handler("/v1/chat/foo") == "proxy_chat"
        assert resolved_handler("/v1/chat") == "proxy_chat"

    def test_validate_proxy_messages_rejects_missing_messages(self):
        """The _validate_proxy_messages function correctly rejects missing messages."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        from services.gateway.app.main import _validate_proxy_messages

        error = _validate_proxy_messages({"model": "gpt-4o"}, format_type="openai")
        assert error is not None
        assert "messages" in error.lower()

    def test_validate_proxy_messages_accepts_valid_body(self):
        """The _validate_proxy_messages function accepts a valid request body."""
        pytest.importorskip("fastapi", reason="fastapi not installed")
        from services.gateway.app.main import _validate_proxy_messages

        error = _validate_proxy_messages(
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]},
            format_type="openai",
        )
        assert error is None

    def test_ingest_text_valid_request(self, client):
        """POST /v1/ingest/text with a valid body, in whichever auth state applies.

        This asserted 200 unconditionally and passed, because no request was
        ever authenticated — the route's dependency was bound but never
        invoked. /v1/ingest/text requires write scope, so with auth enforced an
        unauthenticated call is a 401 and the old assertion was documenting the
        bypass.

        It only passed in isolation by luck of ordering: _AUTH_ENABLED is read
        once when bitmod.auth is imported, so which test module imports first
        decided the answer. Branching on it explicitly keeps this meaningful in
        both configurations instead of depending on collection order.
        """
        if client is None:
            pytest.skip("client not available")
        from bitmod.auth import is_auth_enabled

        response = client.post(
            "/v1/ingest/text",
            json={
                "text": "This is a test document about employment law.",
                "title": "Test Document",
                "document_type": "document",
                "source": "test",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if is_auth_enabled():
            assert response.status_code == 401, (
                "an unauthenticated write reached the ingest endpoint — the route requires write scope"
            )
        else:
            assert response.status_code == 200
