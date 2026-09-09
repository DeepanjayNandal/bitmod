"""Gemini format request/response handling (/v1beta/models/{model}:generateContent).

Works with: Google Generative AI SDK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from bitmod.interfaces.llm import LLMMessage

if TYPE_CHECKING:
    from bitmod.proxy.base import BitmodProxy
from bitmod.proxy.debug import cache_debug_headers

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------


def _extract_gemini_user_message(contents: list[dict]) -> str:
    """Extract the last user message from Gemini-format contents."""
    for c in reversed(contents):
        if c.get("role", "user") == "user":
            return _extract_gemini_parts_text(c.get("parts", []))
    return ""


def _extract_gemini_parts_text(parts: list[dict]) -> str:
    """Extract text from Gemini parts list."""
    texts = []
    for p in parts:
        if isinstance(p, dict) and "text" in p:
            texts.append(p["text"])
        elif isinstance(p, str):
            texts.append(p)
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_gemini_response(
    content: str,
    model: str,
    cached: bool = False,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_key: str | None = None,
    pipeline_trace: list[dict] | None = None,
) -> dict:
    """Build a Gemini generateContent response."""
    resp = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": content}],
                    "role": "model",
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        # Approximate token count (len/4 ~ BPE); real counts come from provider usage
        "usageMetadata": {
            "promptTokenCount": input_tokens,
            "candidatesTokenCount": output_tokens or len(content) // 4,
            "totalTokenCount": (input_tokens or 0) + (output_tokens or len(content) // 4),
        },
        "modelVersion": model,
        "x_bitmod_cached": cached,
    }
    if cache_key:
        resp["x_bitmod_cache_key"] = cache_key
    if pipeline_trace:
        resp["x_bitmod_pipeline_trace"] = pipeline_trace
    return resp


def _build_gemini_error(message: str) -> dict:
    """Build a Gemini-format error response. Internal details are logged, not returned."""
    logger.error("Gemini proxy error: %s", message)
    return {
        "error": {
            "code": 500,
            "message": "Generation failed. Please try again.",
            "status": "INTERNAL",
        },
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_gemini(
    proxy: BitmodProxy,
    request_body: dict,
    model: str = "",
    api_key: str | None = None,
    namespace_id: str | None = None,
    debug_sink: dict | None = None,
) -> dict:
    """Handle a Gemini generateContent request."""
    model = model or proxy._default_model
    contents = request_body.get("contents", [])
    gen_config = request_body.get("generationConfig", {})
    temperature = gen_config.get("temperature", 0.0)
    max_tokens = gen_config.get("maxOutputTokens", 4096)
    system_instruction = request_body.get("systemInstruction")

    user_message = _extract_gemini_user_message(contents)
    if not user_message.strip():
        return _build_gemini_response("Please provide a message.", model)

    # Build context for cache keying
    context_msgs = []
    if system_instruction:
        sys_text = _extract_gemini_parts_text(system_instruction.get("parts", []))
        context_msgs.append({"role": "system", "content": sys_text})
    for c in contents:
        role = c.get("role", "user")
        text = _extract_gemini_parts_text(c.get("parts", []))
        context_msgs.append({"role": role, "content": text})

    start_time = time.perf_counter()
    cache = await asyncio.to_thread(proxy._run_cache_pipeline, user_message, context_msgs, namespace_id)
    if debug_sink is not None:
        debug_sink.update(cache_debug_headers(cache))

    if cache.hit:
        logger.info("Proxy cache HIT (Gemini): %s in %dms", cache.cache_key[:16], cache.elapsed_ms)
        _approx_in = len(user_message) // 4
        _approx_out = len(cache.answer_text) // 4
        _hit_layer = "exact"
        for t in cache.trace:
            if t.get("action") in ("HIT", "FULL_HIT"):
                _hit_layer = t.get("mechanism", "exact")
        proxy._record_usage(
            query_hash=cache.cache_key,
            model=cache.model_used or model,
            provider="",
            input_tokens=_approx_in,
            output_tokens=_approx_out,
            cached=True,
            cache_layer=_hit_layer,
            latency_ms=cache.elapsed_ms,
        )
        return _build_gemini_response(
            cache.answer_text,
            model=cache.model_used or model,
            cached=True,
            cache_key=cache.cache_key,
            pipeline_trace=cache.trace,
        )

    # Forward to LLM
    fuzzy_context = cache.fuzzy_context
    llm_messages = []
    if system_instruction:
        sys_text = _extract_gemini_parts_text(system_instruction.get("parts", []))
        llm_messages.append(LLMMessage(role="system", content=sys_text))
    for c in contents:
        role_map = {"user": "user", "model": "assistant"}
        role = role_map.get(c.get("role", "user"), "user")
        text = _extract_gemini_parts_text(c.get("parts", []))
        llm_messages.append(LLMMessage(role=role, content=text))

    if fuzzy_context:
        llm_messages.insert(
            -1,
            LLMMessage(
                role="system",
                content=f"A similar question was previously answered:\n\n{fuzzy_context}",
            ),
        )

    router = proxy._resolve_router(model, api_key, endpoint_hint="gemini")
    try:
        response = await router.generate(
            llm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error("Proxy LLM forward failed (Gemini): %s", e)
        return _build_gemini_error(str(e))

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    answer_key = cache.answer_key
    norm = cache.norm
    filters = cache.filters

    proxy._store_response(
        user_message,
        response.content,
        response.model or model,
        elapsed_ms,
        filters,
        norm,
        answer_key,
        namespace_id=namespace_id,
        evidence=cache.evidence,
    )

    _in_tokens = response.usage.get("input_tokens", 0)
    _out_tokens = response.usage.get("output_tokens", 0)
    proxy._record_usage(
        query_hash=answer_key,
        model=response.model or model,
        provider="",
        input_tokens=_in_tokens,
        output_tokens=_out_tokens,
        cached=False,
        cache_layer="miss",
        latency_ms=elapsed_ms,
    )

    return _build_gemini_response(
        response.content,
        model=response.model or model,
        input_tokens=_in_tokens,
        output_tokens=_out_tokens,
        cache_key=answer_key,
        pipeline_trace=cache.trace,
    )


async def handle_gemini_stream(
    proxy: BitmodProxy,
    request_body: dict,
    model: str = "",
    api_key: str | None = None,
    namespace_id: str | None = None,
    debug_sink: dict | None = None,
) -> AsyncIterator[str]:
    """Handle a Gemini streamGenerateContent request (NDJSON chunks)."""
    model = model or proxy._default_model
    contents = request_body.get("contents", [])
    gen_config = request_body.get("generationConfig", {})
    temperature = gen_config.get("temperature", 0.0)
    max_tokens = gen_config.get("maxOutputTokens", 4096)
    system_instruction = request_body.get("systemInstruction")

    user_message = _extract_gemini_user_message(contents)
    if not user_message.strip():
        yield json.dumps(_build_gemini_response("Please provide a message.", model)) + "\n"
        return

    context_msgs = []
    if system_instruction:
        sys_text = _extract_gemini_parts_text(system_instruction.get("parts", []))
        context_msgs.append({"role": "system", "content": sys_text})
    for c in contents:
        text = _extract_gemini_parts_text(c.get("parts", []))
        context_msgs.append({"role": c.get("role", "user"), "content": text})

    start_time = time.perf_counter()
    cache = await asyncio.to_thread(proxy._run_cache_pipeline, user_message, context_msgs, namespace_id)
    if debug_sink is not None:
        debug_sink.update(cache_debug_headers(cache))

    if cache.hit:
        # Serve cached answer as a single Gemini response chunk
        yield (
            json.dumps(
                _build_gemini_response(
                    cache.answer_text,
                    model=cache.model_used or model,
                    cached=True,
                    cache_key=cache.cache_key,
                )
            )
            + "\n"
        )
        return

    # Forward to LLM
    fuzzy_context = cache.fuzzy_context
    llm_messages = []
    if system_instruction:
        sys_text = _extract_gemini_parts_text(system_instruction.get("parts", []))
        llm_messages.append(LLMMessage(role="system", content=sys_text))
    for c in contents:
        role_map = {"user": "user", "model": "assistant"}
        role = role_map.get(c.get("role", "user"), "user")
        text = _extract_gemini_parts_text(c.get("parts", []))
        llm_messages.append(LLMMessage(role=role, content=text))

    if fuzzy_context:
        llm_messages.insert(
            -1,
            LLMMessage(
                role="system",
                content=f"A similar question was previously answered:\n\n{fuzzy_context}",
            ),
        )

    router = proxy._resolve_router(model, api_key, endpoint_hint="gemini")
    full_response: list[str] = []
    try:
        async for token in router.stream(
            llm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            full_response.append(token)
            yield (
                json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {"parts": [{"text": token}], "role": "model"},
                                "finishReason": None,
                            }
                        ],
                    }
                )
                + "\n"
            )
    except Exception as e:
        logger.error("Proxy stream forward failed (Gemini): %s", e)
        yield json.dumps({"error": {"message": "Generation failed"}}) + "\n"
        return

    # Final chunk with finish reason
    yield (
        json.dumps(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": ""}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 0,
                    # Approximate token count: len/4 is closer to BPE than word count
                    "candidatesTokenCount": len("".join(full_response)) // 4,
                },
            }
        )
        + "\n"
    )

    answer_text = "".join(full_response)
    if answer_text.strip():
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        answer_key = cache.answer_key
        norm = cache.norm
        filters = cache.filters
        try:
            proxy._store_response(
                user_message,
                answer_text,
                model,
                elapsed_ms,
                filters,
                norm,
                answer_key,
                namespace_id=namespace_id,
                evidence=cache.evidence,
            )
        except Exception:
            logger.exception("Failed to cache streamed Gemini response")
