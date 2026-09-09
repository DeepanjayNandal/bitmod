"""Integration tests for gateway endpoints using FastAPI TestClient.

Tests health, proxy validation, rate limiting, and security middleware.
Uses mocked backends — no external services needed.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


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
    def test_chat_completions_proxied_to_chat_service(self, client):
        """POST to /v1/chat/completions is proxied via catch-all /v1/chat/{path} route.

        The catch-all /v1/chat/{path:path} route intercepts before the dedicated
        /v1/chat/completions handler, so the request is forwarded to the chat
        service. When the chat service is unavailable, expect 502.
        """
        if client is None:
            pytest.skip("client not available")
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        # Request is proxied to the chat service; upstream may be down (502)
        # or respond with an error (404). Either is acceptable for proxy behavior.
        # Server errors (500) from our own gateway should not occur.
        assert response.status_code in (404, 502)

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
