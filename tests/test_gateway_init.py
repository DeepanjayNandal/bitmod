"""Lazy initialisation of the gateway's shared resources.

Three initialisers — _get_proxy, _get_audit_logger and _get_key_manager — take
_init_lock and then call _get_ingest_backend() from inside that critical
section. _get_ingest_backend takes the same lock, so with a plain
threading.Lock the calling thread deadlocked against itself.

It only bit on a cold backend. _get_ingest_backend returns before acquiring
anything once _ingest_backend is set, so any earlier request that touched the
backend hid the bug entirely, and whichever endpoint needed it first was the one
that hung.

These tests reset the module globals so each initialiser is exercised cold,
which is the only state in which the deadlock is reachable.
"""

from __future__ import annotations

import os
import tempfile
import threading

import pytest

os.environ.setdefault("BITMOD_AUTH_ENABLED", "false")

gateway = pytest.importorskip("services.gateway.app.main")


@pytest.fixture
def cold_gateway(monkeypatch):
    """Reset the lazily-built singletons so the next call builds them."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    monkeypatch.setattr(gateway.config.db, "sqlite_path", db_path, raising=False)
    monkeypatch.setattr(gateway.config.db, "backend", "sqlite", raising=False)
    monkeypatch.setattr(gateway, "_ingest_backend", None, raising=False)
    monkeypatch.setattr(gateway, "_proxy_instance", None, raising=False)
    monkeypatch.setattr(gateway, "_audit_logger", None, raising=False)
    monkeypatch.setattr(gateway, "_key_manager", None, raising=False)
    yield
    if os.path.exists(db_path):
        os.unlink(db_path)


def _with_timeout(fn, seconds=8):
    """Call fn on a worker thread; report whether it finished.

    A deadlock does not raise — it simply never returns — so asserting on
    completion is the only way to catch it. Without a bound the test would hang
    the suite rather than fail it.
    """
    outcome: dict = {}

    def run():
        try:
            outcome["value"] = fn()
        except Exception as exc:  # noqa: BLE001 — recorded and re-raised below
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return False, None
    if "error" in outcome:
        raise outcome["error"]
    return True, outcome.get("value")


def test_init_lock_is_reentrant():
    """The direct cause. A plain Lock here self-deadlocks."""
    assert isinstance(gateway._init_lock, type(threading.RLock())), (
        "_init_lock must be reentrant: three initialisers call _get_ingest_backend() "
        "while already holding it"
    )


def test_get_proxy_completes_on_a_cold_backend(cold_gateway):
    """REGRESSION GUARD — this hung indefinitely.

    _get_proxy takes _init_lock, then calls _get_ingest_backend() which takes it
    again. The comment there reads "reuse the already-initialized backend",
    which is the assumption that made it look safe: when the backend already
    exists that call returns early and never touches the lock.
    """
    finished, proxy = _with_timeout(gateway._get_proxy)
    assert finished, "_get_proxy deadlocked on a cold backend"
    assert proxy is not None


def test_get_audit_logger_completes_on_a_cold_backend(cold_gateway):
    finished, logger = _with_timeout(gateway._get_audit_logger)
    assert finished, "_get_audit_logger deadlocked on a cold backend"
    assert logger is not None


def test_get_key_manager_completes_on_a_cold_backend(cold_gateway):
    finished, manager = _with_timeout(gateway._get_key_manager)
    assert finished, "_get_key_manager deadlocked on a cold backend"
    assert manager is not None


def test_initialisers_are_idempotent(cold_gateway):
    """Second call returns the same instance without rebuilding."""
    finished, first = _with_timeout(gateway._get_proxy)
    assert finished
    finished, second = _with_timeout(gateway._get_proxy)
    assert finished
    assert first is second


def test_concurrent_cold_initialisation_is_safe(cold_gateway):
    """Reentrancy must not cost mutual exclusion between threads.

    An RLock is still exclusive across threads; it only relaxes re-acquisition
    by the thread that already holds it. Several threads racing on a cold
    backend should still end up with one instance.
    """
    results: list = []
    errors: list = []

    def build():
        try:
            results.append(gateway._get_proxy())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=build, daemon=True) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert not any(t.is_alive() for t in threads), "concurrent initialisation deadlocked"
    assert not errors, f"initialisation raised: {errors}"
    assert len(results) == 6
    assert len({id(r) for r in results}) == 1, "built more than one proxy instance"
