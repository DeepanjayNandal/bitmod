"""OpenAI format request/response handling (/v1/chat/completions).

Works with: OpenAI, Azure OpenAI, xAI/Grok, Mistral, Perplexity,
OpenRouter, Ollama, LM Studio, OpenClaw, Groq, Together, and any
OpenAI-compatible client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bitmod.proxy.base import BitmodProxy
from bitmod.proxy.debug import cache_debug_headers

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------


def _extract_user_message(messages: list[dict]) -> str:
    """Extract the last user message from OpenAI-format messages."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                return " ".join(parts)
            return content  # type: ignore[no-any-return]
    return ""


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_openai_response(
    content: str,
    model: str,
    cached: bool = False,
    usage: dict | None = None,
    cache_key: str | None = None,
    generation_ms: int = 0,
    pipeline_trace: list[dict] | None = None,
) -> dict:
    """Build an OpenAI-compatible chat completion response."""
    resp = {
        "id": f"chatcmpl-bitmod-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        # Approximate token count (len/4 ~ BPE); real counts come from provider usage
        "usage": usage
        or {
            "prompt_tokens": 0,
            "completion_tokens": len(content) // 4,
            "total_tokens": len(content) // 4,
        },
        "x_bitmod_cached": cached,
        "x_bitmod_generation_ms": generation_ms,
    }
    if cache_key:
        resp["x_bitmod_cache_key"] = cache_key
    if pipeline_trace:
        resp["x_bitmod_pipeline_trace"] = pipeline_trace
    return resp


def _build_stream_chunk(
    content: str,
    model: str,
    chunk_id: str,
    finish_reason: str | None = None,
) -> str:
    """Build an OpenAI-compatible streaming chunk (SSE data line)."""
    chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _end_user_id(request_body: dict) -> str | None:
    """The end-user identifier OpenAI clients send for abuse monitoring.

    Not a conversation id — one user may hold several conversations — but it
    scopes the fallback session key so two users inside a namespace asking the
    same opening question do not share session state.
    """
    for field in ("user", "safety_identifier"):
        value = request_body.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def handle_completion(
    proxy: BitmodProxy,
    request_body: dict,
    api_key: str | None = None,
    namespace_id: str | None = None,
    debug_sink: dict | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Handle a /v1/chat/completions request (non-streaming)."""
    messages = request_body.get("messages", [])
    model = request_body.get("model", proxy._default_model)
    temperature = request_body.get("temperature", 0.0)
    max_tokens = request_body.get("max_tokens") or request_body.get("max_completion_tokens") or 4096

    user_message = _extract_user_message(messages)
    if not user_message.strip():
        return _build_openai_response("Please provide a message.", model)

    start_time = time.perf_counter()
    cache = await asyncio.to_thread(
        proxy._run_cache_pipeline,
        user_message,
        messages,
        namespace_id,
        conversation_id=conversation_id,
        user_id=_end_user_id(request_body),
    )
    if debug_sink is not None:
        debug_sink.update(cache_debug_headers(cache))

    if cache.hit:
        logger.info("Proxy cache HIT (OpenAI): %s in %dms", cache.cache_key[:16], cache.elapsed_ms)
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
        return _build_openai_response(
            cache.answer_text,
            model=cache.model_used or model,
            cached=True,
            cache_key=cache.cache_key,
            generation_ms=cache.elapsed_ms,
            pipeline_trace=cache.trace,
        )

    # Forward to LLM
    router = proxy._resolve_router(model, api_key, endpoint_hint=None)
    fuzzy_context = cache.fuzzy_context
    llm_messages = proxy._build_llm_messages(messages, fuzzy_context)

    try:
        response = await router.generate(
            llm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error("Proxy LLM forward failed: %s: %s", type(e).__name__, e)
        return _build_openai_response(
            "Generation failed. Please try again.",
            model=model,
        )

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
        conversation_id=conversation_id,
        user_id=_end_user_id(request_body),
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

    return _build_openai_response(
        response.content,
        model=response.model or model,
        cached=False,
        cache_key=answer_key,
        usage={
            "prompt_tokens": _in_tokens,
            "completion_tokens": _out_tokens,
            "total_tokens": _in_tokens + _out_tokens,
        },
        generation_ms=elapsed_ms,
        pipeline_trace=cache.trace,
    )


async def handle_completion_stream(
    proxy: BitmodProxy,
    request_body: dict,
    api_key: str | None = None,
    namespace_id: str | None = None,
    debug_sink: dict | None = None,
    conversation_id: str | None = None,
) -> AsyncIterator[str]:
    """Handle a streaming /v1/chat/completions request (SSE)."""
    messages = request_body.get("messages", [])
    model = request_body.get("model", proxy._default_model)
    temperature = request_body.get("temperature", 0.0)
    max_tokens = request_body.get("max_tokens") or request_body.get("max_completion_tokens") or 4096

    user_message = _extract_user_message(messages)
    chunk_id = f"chatcmpl-bitmod-{uuid.uuid4().hex[:12]}"

    if not user_message.strip():
        yield _build_stream_chunk("Please provide a message.", model, chunk_id, "stop")
        yield "data: [DONE]\n\n"
        return

    start_time = time.perf_counter()
    cache = await asyncio.to_thread(
        proxy._run_cache_pipeline,
        user_message,
        messages,
        namespace_id,
        conversation_id=conversation_id,
        user_id=_end_user_id(request_body),
    )
    if debug_sink is not None:
        debug_sink.update(cache_debug_headers(cache))

    if cache.hit:
        text = cache.answer_text
        chunk_size = 50
        for i in range(0, len(text), chunk_size):
            yield _build_stream_chunk(text[i : i + chunk_size], model, chunk_id)
        yield _build_stream_chunk("", model, chunk_id, "stop")
        yield "data: [DONE]\n\n"
        return

    router = proxy._resolve_router(model, api_key, endpoint_hint=None)
    fuzzy_context = cache.fuzzy_context
    llm_messages = proxy._build_llm_messages(messages, fuzzy_context)

    full_response: list[str] = []
    try:
        async for token in router.stream(
            llm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            full_response.append(token)
            yield _build_stream_chunk(token, model, chunk_id)
    except Exception as e:
        logger.error("Proxy stream forward failed: %s: %s", type(e).__name__, e)
        yield _build_stream_chunk("Generation failed", model, chunk_id, "stop")
        yield "data: [DONE]\n\n"
        return

    yield _build_stream_chunk("", model, chunk_id, "stop")
    yield "data: [DONE]\n\n"

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
                conversation_id=conversation_id,
                user_id=_end_user_id(request_body),
            )
        except Exception:
            logger.exception("Failed to cache streamed proxy response")
