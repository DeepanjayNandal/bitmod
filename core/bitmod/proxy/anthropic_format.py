"""Anthropic format request/response handling (/v1/messages).

Works with: Claude SDK (Python + TypeScript).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
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


def _extract_anthropic_user_message(messages: list[dict]) -> str:
    """Extract the last user message from Anthropic-format messages.

    Anthropic content can be a string or list of content blocks:
        {"role": "user", "content": "Hello"}
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return " ".join(parts)
    return ""


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_anthropic_response(
    content: str,
    model: str,
    cached: bool = False,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_key: str | None = None,
    pipeline_trace: list[dict] | None = None,
) -> dict:
    """Build an Anthropic Messages API response."""
    resp = {
        "id": f"msg_bitmod_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        # Approximate token count (len/4 ~ BPE); real counts come from provider usage
        "usage": {
            "input_tokens": input_tokens or 0,
            "output_tokens": output_tokens or len(content) // 4,
        },
        "x_bitmod_cached": cached,
    }
    if cache_key:
        resp["x_bitmod_cache_key"] = cache_key
    if pipeline_trace:
        resp["x_bitmod_pipeline_trace"] = pipeline_trace
    return resp


def _build_anthropic_error(message: str) -> dict:
    """Build an Anthropic-format error response. Internal details are logged, not returned."""
    logger.error("Anthropic proxy error: %s", message)
    return {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "Generation failed. Please try again.",
        },
    }


def _sse(event: str, data: dict) -> str:
    """Build an SSE line with event type (Anthropic streaming format)."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _anthropic_stream_text(text: str, model: str, msg_id: str) -> list[str]:
    """Build a complete Anthropic SSE stream for a cached text response."""
    chunks = []
    chunks.append(
        _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )
    )
    chunks.append(
        _sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
    )
    # Stream in 50-char chunks for consistent UX
    chunk_size = 50
    for i in range(0, len(text), chunk_size):
        chunks.append(
            _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text[i : i + chunk_size]},
                },
            )
        )
    chunks.append(_sse("content_block_stop", {"type": "content_block_stop", "index": 0}))
    chunks.append(
        _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                # Approximate token count (len/4 ~ BPE); real counts come from provider usage
                "usage": {"output_tokens": len(text) // 4},
            },
        )
    )
    chunks.append(_sse("message_stop", {"type": "message_stop"}))
    return chunks


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _end_user_id(request_body: dict) -> str | None:
    """The end-user identifier from Anthropic's metadata block.

    Not a conversation id, but it scopes the fallback session key so two users
    inside a namespace asking the same opening question do not share session
    state.
    """
    metadata = request_body.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("user_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def handle_anthropic(
    proxy: BitmodProxy,
    request_body: dict,
    api_key: str | None = None,
    namespace_id: str | None = None,
    debug_sink: dict | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Handle a /v1/messages request (Anthropic Claude SDK format)."""
    messages = request_body.get("messages", [])
    model = request_body.get("model", proxy._default_model)
    max_tokens = request_body.get("max_tokens", 4096)
    temperature = request_body.get("temperature", 0.0)
    system_prompt = request_body.get("system")

    user_message = _extract_anthropic_user_message(messages)
    if not user_message.strip():
        return _build_anthropic_response("Please provide a message.", model)

    # Build context messages for cache keying (include system if present)
    context_msgs = []
    if system_prompt:
        context_msgs.append({"role": "system", "content": system_prompt})
    context_msgs.extend(messages)

    start_time = time.perf_counter()
    cache = await asyncio.to_thread(
        proxy._run_cache_pipeline,
        user_message,
        context_msgs,
        namespace_id,
        conversation_id=conversation_id,
        user_id=_end_user_id(request_body),
    )
    if debug_sink is not None:
        debug_sink.update(cache_debug_headers(cache))

    if cache.hit:
        logger.info("Proxy cache HIT (Anthropic): %s in %dms", cache.cache_key[:16], cache.elapsed_ms)
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
        return _build_anthropic_response(
            cache.answer_text,
            model=cache.model_used or model,
            cached=True,
            cache_key=cache.cache_key,
            pipeline_trace=cache.trace,
        )

    # Forward to LLM
    fuzzy_context = cache.fuzzy_context
    llm_messages = []
    if system_prompt:
        llm_messages.append(LLMMessage(role="system", content=system_prompt))
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else str(b) for b in content
            )
        llm_messages.append(LLMMessage(role=msg.get("role", "user"), content=content))

    if fuzzy_context:
        llm_messages.insert(
            -1,
            LLMMessage(
                role="system",
                content=f"A similar question was previously answered. Use this as context "
                f"but adapt your answer to the exact question:\n\n{fuzzy_context}",
            ),
        )

    router = proxy._resolve_router(model, api_key, endpoint_hint="anthropic")
    try:
        response = await router.generate(
            llm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.error("Proxy LLM forward failed (Anthropic): %s", e)
        return _build_anthropic_error(str(e))  # str(e) logged server-side by _build_anthropic_error, not sent to client

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

    return _build_anthropic_response(
        response.content,
        model=response.model or model,
        input_tokens=_in_tokens,
        output_tokens=_out_tokens,
        cache_key=answer_key,
        pipeline_trace=cache.trace,
    )


async def handle_anthropic_stream(
    proxy: BitmodProxy,
    request_body: dict,
    api_key: str | None = None,
    namespace_id: str | None = None,
    debug_sink: dict | None = None,
    conversation_id: str | None = None,
) -> AsyncIterator[str]:
    """Handle a streaming /v1/messages request (Anthropic SSE format)."""
    messages = request_body.get("messages", [])
    model = request_body.get("model", proxy._default_model)
    max_tokens = request_body.get("max_tokens", 4096)
    temperature = request_body.get("temperature", 0.0)
    system_prompt = request_body.get("system")

    user_message = _extract_anthropic_user_message(messages)
    msg_id = f"msg_bitmod_{uuid.uuid4().hex[:16]}"

    if not user_message.strip():
        for chunk in _anthropic_stream_text("Please provide a message.", model, msg_id):
            yield chunk
        return

    context_msgs = []
    if system_prompt:
        context_msgs.append({"role": "system", "content": system_prompt})
    context_msgs.extend(messages)

    start_time = time.perf_counter()
    cache = await asyncio.to_thread(
        proxy._run_cache_pipeline,
        user_message,
        context_msgs,
        namespace_id,
        conversation_id=conversation_id,
        user_id=_end_user_id(request_body),
    )
    if debug_sink is not None:
        debug_sink.update(cache_debug_headers(cache))

    if cache.hit:
        for chunk in _anthropic_stream_text(cache.answer_text, cache.model_used or model, msg_id):
            yield chunk
        return

    # Forward to LLM
    fuzzy_context = cache.fuzzy_context
    llm_messages = []
    if system_prompt:
        llm_messages.append(LLMMessage(role="system", content=system_prompt))
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") if isinstance(b, dict) and b.get("type") == "text" else str(b) for b in content
            )
        llm_messages.append(LLMMessage(role=msg.get("role", "user"), content=content))

    if fuzzy_context:
        llm_messages.insert(
            -1,
            LLMMessage(
                role="system",
                content=f"A similar question was previously answered:\n\n{fuzzy_context}",
            ),
        )

    # message_start
    router = proxy._resolve_router(model, api_key, endpoint_hint="anthropic")
    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )
    # content_block_start
    yield _sse(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    )

    full_response: list[str] = []
    try:
        async for token in router.stream(
            llm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            full_response.append(token)
            yield _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": token},
                },
            )
    except Exception as e:
        logger.error("Proxy stream forward failed (Anthropic): %s", e)
        yield _sse(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Generation failed"},
            },
        )

    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            # Approximate token count: len/4 is closer to BPE than word count
            "usage": {"output_tokens": len("".join(full_response)) // 4},
        },
    )
    yield _sse("message_stop", {"type": "message_stop"})

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
            logger.exception("Failed to cache streamed Anthropic response")
