"""Cache attribution for proxy responses.

Which layer served a cache hit was not observable from outside the process.
The pipeline computes it — every contributing layer with its own confidence,
and an accumulated total — and then discarded all of it: one derived label went
to usage_tracking and nothing reached the caller. There was no way to debug a
surprising hit, and no way to tell whether a layer was earning its place.

Attribution is returned as response **headers** rather than in the body. The
OpenAI, Anthropic and Gemini formats are drop-in replacements for their
upstreams, so an extra top-level key would break strict clients that reject
unknown fields. Headers are invisible to clients that do not look for them.

Enabled by the ``BITMOD_DEBUG`` environment variable or, per request, by the
``X-Bitmod-Debug`` header — the same convention the chat service already uses
(``services/chat/app/main.py``). The header is only honoured on requests that
have already authenticated: the proxy's format endpoints are customer-facing,
and an unauthenticated caller should not be able to probe cache internals.
"""

from __future__ import annotations

import os
from typing import Any

# Header names are lowercase by convention; clients match case-insensitively.
HEADER_CACHE = "x-bitmod-cache"
HEADER_SERVED_BY = "x-bitmod-cache-served-by"
HEADER_CONFIDENCE = "x-bitmod-cache-confidence"
HEADER_LAYERS = "x-bitmod-cache-layers"
HEADER_DECISION = "x-bitmod-cache-decision"


def _env_debug_enabled() -> bool:
    return os.getenv("BITMOD_DEBUG", "").lower() in ("1", "true", "yes")


def debug_enabled(request: Any = None, authenticated: bool = False) -> bool:
    """Whether to attach cache attribution to this response.

    The environment variable enables it everywhere, which is what a local or
    staging deployment wants. The header enables it for a single request, which
    is what debugging a specific surprising hit in production wants — flipping
    the env var would instead expose internals on every response, including
    other tenants'.

    ``authenticated`` gates only the header. Route handlers pass True once their
    auth dependency has run.
    """
    if _env_debug_enabled():
        return True
    if request is None or not authenticated:
        return False
    headers = getattr(request, "headers", None)
    if headers is None:
        return False
    return str(headers.get("x-bitmod-debug", "")).lower() in ("1", "true", "yes")


def _sanitise(value: str) -> str:
    """Header values must be single-line ASCII."""
    return "".join(c for c in value if c.isprintable() and c not in "\r\n")[:512]


def cache_debug_headers(cache_result: Any) -> dict[str, str]:
    """Build attribution headers from a pipeline result.

    ``served_by`` comes from ``evidence.best_single_answer().layer`` — the entry
    that was actually returned. It is not derived by scanning the trace for a
    HIT action: only exact match and composable emit those, so every other layer
    reported as "exact" by default and an accumulated-confidence serve credited
    a layer that had missed.
    """
    headers: dict[str, str] = {
        HEADER_CACHE: "hit" if getattr(cache_result, "hit", False) else "miss",
    }

    evidence = getattr(cache_result, "evidence", None)
    if evidence is None:
        return headers

    total = getattr(evidence, "total_confidence", 0.0)
    headers[HEADER_CONFIDENCE] = f"{total:.4f}"

    contributions = []
    for item in getattr(evidence, "evidences", []) or []:
        layer = getattr(item, "layer", "")
        confidence = getattr(item, "confidence", 0.0)
        if layer:
            contributions.append(f"{layer}:{confidence:.3f}")
    if contributions:
        headers[HEADER_LAYERS] = _sanitise(",".join(contributions))

    if getattr(cache_result, "hit", False):
        best: Any = None
        if hasattr(evidence, "best_single_answer"):
            try:
                best = evidence.best_single_answer()
            except Exception:  # noqa: S110 — attribution must never break a response
                best = None
        served_layer = str(getattr(best, "layer", "") or "") if best is not None else ""
        if served_layer:
            headers[HEADER_SERVED_BY] = _sanitise(served_layer)
        else:
            # A hit with no single best answer came from an early return —
            # exact match or a full composable assembly.
            for step in getattr(cache_result, "trace", []) or []:
                if step.get("action") in ("HIT", "FULL_HIT"):
                    headers[HEADER_SERVED_BY] = _sanitise(str(step.get("mechanism", "")))

    for step in reversed(getattr(cache_result, "trace", []) or []):
        if step.get("mechanism") == "decision":
            headers[HEADER_DECISION] = _sanitise(str(step.get("action", "")))
            break

    return headers
