"""The gateway actually enforces authentication and scopes.

Two defects hid each other here, which is why this went unnoticed for so long.

Every route declared its dependency as
``Depends(lambda: _get_auth_dep(scopes=[...]))``. _get_auth_dep is a factory:
FastAPI called the zero-argument lambda, took the dependency callable it
returned as the resolved value, bound that function object to the parameter and
never invoked it. No request was authenticated, on any route, including the
admin ones.

The endpoints that authenticate imperatively had the opposite bug — they called
the dependency without its required ``request`` positional, so they raised
TypeError and returned 500. That family is all of /v1/auth/keys, so with auth
enabled no key could be issued, so nobody made an authenticated request, so
nobody noticed unauthenticated ones sailed through.

These tests run against a live gateway with BITMOD_AUTH_ENABLED=true, because
the bypass was invisible to anything that only inspected route declarations —
the old test asserted a Depends default existed, which stayed true throughout.

Keys are seeded straight through APIKeyManager rather than the admin endpoint:
a test for authentication should not depend on an authenticated endpoint to set
itself up.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Scope required by each of these routes, as declared in the gateway.
READ_ROUTE = "/v1/cache/stats"
WRITE_ROUTE = "/v1/ingest/text"
ADMIN_ROUTE = "/v1/admin/metrics"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def authed_gateway():
    """A gateway with auth on, and one API key per scope."""
    pytest.importorskip("fastapi")

    tmpdir = tempfile.mkdtemp(prefix="bitmod-auth-test-")
    db_path = os.path.join(tmpdir, "auth.db")

    from bitmod.adapters.db_sqlite import SQLiteBackend
    from bitmod.auth import APIKeyManager

    backend = SQLiteBackend(db_path)
    backend.initialize()
    manager = APIKeyManager(backend)
    keys = {
        scope: manager.create_key(name=f"{scope}-key", owner=f"{scope}-owner", scopes=[scope])[0]
        for scope in ("read", "write", "admin")
    }

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.gateway.app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "BITMOD_AUTH_ENABLED": "true",
            "BITMOD_DB_BACKEND": "sqlite",
            "BITMOD_SQLITE_PATH": db_path,
            "BITMOD_LOG_LEVEL": "WARNING",
        },
    )

    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            pytest.fail(f"gateway exited early:\n{stdout.decode()}\n{stderr.decode()}")
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("gateway did not become healthy")

    # If this is not on, every assertion below passes for the wrong reason:
    # require_auth_db returns an anonymous user with read scope when auth is
    # disabled, so nothing would be rejected and the suite would still be green.
    status = httpx.get(f"{base}/v1/auth/status", timeout=5).json()
    assert status["auth_enabled"] is True, "auth must be enabled or these tests prove nothing"

    yield base, keys

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _write_body() -> dict:
    return {"text": "a document about employment law", "title": "t"}


class TestAuthenticationIsEnforced:
    def test_unauthenticated_request_to_a_read_route_is_rejected(self, authed_gateway):
        """The bypass, stated directly. This returned 200 with no credentials."""
        base, _ = authed_gateway
        response = httpx.get(base + READ_ROUTE, timeout=15)
        assert response.status_code == 401, (
            f"{READ_ROUTE} served an unauthenticated request ({response.status_code}) — "
            "the auth dependency is being bound but not invoked"
        )

    def test_unauthenticated_request_to_an_admin_route_is_rejected(self, authed_gateway):
        base, _ = authed_gateway
        response = httpx.get(base + ADMIN_ROUTE, timeout=15)
        assert response.status_code == 401, f"{ADMIN_ROUTE} served an unauthenticated request"

    def test_invalid_key_is_rejected(self, authed_gateway):
        base, _ = authed_gateway
        response = httpx.get(base + READ_ROUTE, headers={"x-api-key": "not-a-real-key"}, timeout=15)
        assert response.status_code == 401


class TestScopesAreEnforced:
    def test_read_key_cannot_reach_a_write_route(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.post(
            base + WRITE_ROUTE,
            json=_write_body(),
            headers={"x-api-key": keys["read"], "X-Requested-With": "XMLHttpRequest"},
            timeout=15,
        )
        assert response.status_code == 403, f"a read-scoped key reached {WRITE_ROUTE} ({response.status_code})"

    def test_non_admin_key_cannot_reach_an_admin_route(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.get(base + ADMIN_ROUTE, headers={"x-api-key": keys["write"]}, timeout=15)
        assert response.status_code == 403, f"a write-scoped key reached {ADMIN_ROUTE} ({response.status_code})"


class TestCorrectlyScopedKeysStillWork:
    """The positive control.

    Everything above passes if the gateway rejects every request, which is a
    plausible way to break it while "fixing" the bypass. These fail in that
    case.
    """

    def test_read_key_reaches_a_read_route(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.get(base + READ_ROUTE, headers={"x-api-key": keys["read"]}, timeout=15)
        assert response.status_code == 200, response.text[:300]

    def test_write_key_reaches_a_write_route(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.post(
            base + WRITE_ROUTE,
            json=_write_body(),
            headers={"x-api-key": keys["write"], "X-Requested-With": "XMLHttpRequest"},
            timeout=30,
        )
        assert response.status_code == 200, response.text[:300]

    def test_admin_key_reaches_an_admin_route(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.get(base + ADMIN_ROUTE, headers={"x-api-key": keys["admin"]}, timeout=15)
        assert response.status_code == 200, response.text[:300]


class TestImperativeAuthRoutesAreReachable:
    """The second family: these returned 500, not 401/403.

    The call omitted the dependency's required `request` argument, so the
    failure was a TypeError before any credential was examined. An admin key
    getting 500 here is the regression this guards.
    """

    def test_listing_keys_with_an_admin_key_succeeds(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.get(base + "/v1/auth/keys", headers={"x-api-key": keys["admin"]}, timeout=15)
        assert response.status_code != 500, f"still raising TypeError: {response.text[:300]}"
        assert response.status_code == 200, response.text[:300]

    def test_listing_keys_without_credentials_is_rejected_not_crashed(self, authed_gateway):
        base, _ = authed_gateway
        response = httpx.get(base + "/v1/auth/keys", timeout=15)
        assert response.status_code == 401, response.text[:300]

    def test_creating_a_key_requires_admin_scope(self, authed_gateway):
        base, keys = authed_gateway
        response = httpx.post(
            base + "/v1/auth/keys",
            json={"name": "from-test", "owner": "test", "scopes": ["read"]},
            headers={"x-api-key": keys["read"], "X-Requested-With": "XMLHttpRequest"},
            timeout=15,
        )
        assert response.status_code == 403, response.text[:300]


def test_openapi_documents_the_auth_requirement(authed_gateway):
    """/docs showing no auth on any route is how this stayed invisible.

    The lambda declared no parameters, so FastAPI saw no security scheme and
    the published spec described a gateway that needed no credentials.
    """
    base, _ = authed_gateway
    spec = httpx.get(base + "/openapi.json", timeout=15).json()

    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert schemes, "no security schemes published — the spec claims every route is open"

    protected = spec["paths"][READ_ROUTE]["get"]
    assert protected.get("security"), f"{READ_ROUTE} is not marked as requiring credentials"
