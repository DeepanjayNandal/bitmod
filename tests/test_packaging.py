"""Packaging — the extras have to declare what the code imports.

Two adapters imported modules that appeared in no dependency group, so a clean
install produced code that could not be imported, and the error message pointed
at an extra that did not exist.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Packaging — extras must declare what the code imports
# ---------------------------------------------------------------------------


def _pyproject() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()


def test_postgres_extra_declares_pgvector():
    """db_postgresql imports pgvector unconditionally at module scope.

    Without it declared, `pip install bitmod[postgres]` produced a backend that
    could not be imported at all.
    """
    text = _pyproject()
    block = text.split("postgres = [")[1].split("]")[0]
    assert "pgvector" in block


def test_security_extra_declares_cryptography_and_jwt():
    """crypto.py and auth.py import cryptography; it was declared nowhere.

    The crypto and JWT test modules use a module-level pytest.importorskip, so
    when it was missing those modules vanished from collection entirely — 47
    tests disappeared rather than reporting as skipped.
    """
    text = _pyproject()
    block = text.split("security = [")[1].split("]")[0]
    assert "cryptography" in block
    assert "PyJWT" in block


def test_install_hint_names_an_extra_that_exists():
    """The error message told users to install an extra that was never defined."""
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1] / "core" / "bitmod" / "adapters" / "db_postgresql.py"
    ).read_text()
    assert "bitmod[postgresql]" not in src, "names a non-existent extra; the extra is 'postgres'"
    assert "bitmod[postgres]" in src
