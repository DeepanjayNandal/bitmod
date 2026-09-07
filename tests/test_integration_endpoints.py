"""Integration tests: start gateway, hit real HTTP endpoints."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

# Repo root: tests/ is one level down from the project root
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

GATEWAY_PORT = 19876
GATEWAY_URL = f"http://127.0.0.1:{GATEWAY_PORT}"


@pytest.fixture(scope="module")
def gateway_process():
    """Start the gateway in a subprocess and wait for it to become healthy."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "services.gateway.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(GATEWAY_PORT),
        ],
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "BITMOD_LOG_LEVEL": "WARNING",
        },
    )

    # Wait for health
    healthy = False
    for _ in range(30):
        try:
            r = httpx.get(f"{GATEWAY_URL}/health", timeout=2)
            if r.status_code == 200:
                healthy = True
                break
        except httpx.ConnectError:
            pass
        time.sleep(0.5)

    if not healthy:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        pytest.fail(f"Gateway did not start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield proc

    proc.terminate()
    proc.wait(timeout=10)


@pytest.mark.e2e
class TestGatewayEndpoints:
    def test_health(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "gateway"

    def test_healthz(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/healthz", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_readyz(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/readyz", timeout=5)
        # readyz may return 200 or 503 depending on chat service availability
        assert r.status_code in (200, 503)
        assert "status" in r.json()

    def test_auth_status(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/v1/auth/status", timeout=5)
        assert r.status_code == 200
        assert "auth_enabled" in r.json()

    def test_chat_without_auth(self, gateway_process):
        r = httpx.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}], "model": "test"},
            timeout=5,
        )
        # Chat service may not be running in CI — accept any non-5xx except 502 (proxy error is expected)
        assert r.status_code < 500 or r.status_code == 502

    def test_openapi_json(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/openapi.json", timeout=5)
        assert r.status_code == 200
        spec = r.json()
        assert spec["info"]["title"] == "BitMod API"
        assert spec["info"]["version"] == "0.2.1"
        assert "paths" in spec
        # Verify tags exist
        tag_names = {t["name"] for t in spec.get("tags", [])}
        for expected in ("health", "auth", "proxy", "ingest", "cache", "admin"):
            assert expected in tag_names, f"Missing tag: {expected}"

    def test_docs_page(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/docs", timeout=5)
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()

    def test_redoc_page(self, gateway_process):
        r = httpx.get(f"{GATEWAY_URL}/redoc", timeout=5)
        assert r.status_code == 200
