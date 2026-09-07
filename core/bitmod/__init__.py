"""Bitmod — Modular AI Data Infrastructure. Compute once, serve forever.

Install:
    pip install bitmod              # SQLite + local mode (works everywhere)
    pip install bitmod[anthropic]   # + Anthropic Claude
    pip install bitmod[recommended] # Anthropic + PostgreSQL + local embeddings + ingestion
    pip install bitmod[all]         # Everything

Quick start:
    from bitmod import Bitmod

    bm = Bitmod()
    bm.ingest("./docs/")
    result = bm.query("What is the refund policy?")
    print(result.answer)
"""

__version__ = "0.2.1"

from bitmod.config import BitmodConfig


def __getattr__(name: str):
    """Lazy imports to keep `import bitmod` fast."""
    if name == "Bitmod":
        from bitmod.api import Bitmod

        return Bitmod
    if name == "IngestResult":
        from bitmod.api import IngestResult

        return IngestResult
    if name == "QueryResult":
        from bitmod.api import QueryResult

        return QueryResult
    if name == "StatusResult":
        from bitmod.api import StatusResult

        return StatusResult
    raise AttributeError(f"module 'bitmod' has no attribute {name!r}")


__all__ = [
    "__version__",
    "Bitmod",
    "BitmodConfig",
    "IngestResult",
    "QueryResult",
    "StatusResult",
]
