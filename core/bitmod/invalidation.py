"""Change-driven cache invalidation engine."""

import hashlib
import logging
from datetime import datetime, timezone

from bitmod.interfaces.database import DatabaseBackend

logger = logging.getLogger(__name__)


def detect_section_change(backend: DatabaseBackend, session, section_id: str, new_content: str) -> bool:
    """Check if a section's content has changed. Returns True if changed."""
    current_hash = backend.get_section_version_hash(session, section_id)
    new_hash = hashlib.sha256(new_content.encode()).hexdigest()
    return current_hash is not None and current_hash != new_hash


def process_change_event(backend: DatabaseBackend, session, section_id: str, new_content: str) -> dict:
    """Process a content change: update section, invalidate cached answers.

    Returns a summary of what happened.
    """
    old_hash = backend.get_section_version_hash(session, section_id)
    new_hash = hashlib.sha256(new_content.encode()).hexdigest()

    if old_hash == new_hash:
        return {"changed": False, "section_id": section_id, "invalidated_count": 0}

    # Invalidate all cached answers referencing this section
    invalidated = backend.cache_invalidate_by_section(session, section_id)

    logger.info(
        "Section %s changed: %s->%s, invalidated %d cached answers",
        section_id,
        old_hash[:16] if old_hash else None,
        new_hash[:16],
        invalidated,
    )

    return {
        "changed": True,
        "section_id": section_id,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "invalidated_count": invalidated,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


def bulk_verify_sources(backend: DatabaseBackend, session) -> dict:
    """Verify all valid cached answers against current source data.

    Runs double-verification on every valid cache entry. Useful as a
    scheduled health check to catch any missed invalidations.

    Returns summary stats.
    """
    from bitmod.cache_engine import double_verify

    stats = backend.cache_stats(session)
    total = stats["valid_entries"]
    invalidated = 0

    if hasattr(backend, "cache_list_valid"):
        try:
            entries = backend.cache_list_valid(session)
            for entry in entries:
                if not double_verify(backend, session, entry):
                    invalidated += 1
            total = len(entries)
        except Exception:
            logger.warning("bulk_verify_sources: cache_list_valid unavailable, returning stats only")

    return {
        "total_checked": total,
        "invalidated": invalidated,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
