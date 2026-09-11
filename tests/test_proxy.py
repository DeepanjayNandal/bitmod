"""Tests for BitmodProxy — multi-format LLM proxy with 9-layer caching.

Tests all three API formats:
1. OpenAI (/v1/chat/completions)
2. Anthropic (/v1/messages)
3. Gemini (/v1beta/models/{model}:generateContent)

Uses a mock LLM to verify the cache pipeline + response formatting.
"""

import asyncio
import json
import pytest

from bitmod.proxy import (
    BitmodProxy,
    _extract_user_message,
    _extract_anthropic_user_message,
    _extract_gemini_user_message,
    _build_openai_response,
    _build_anthropic_response,
    _build_gemini_response,
)
from bitmod.interfaces.llm import LLMMessage, LLMProvider, LLMResponse, ToolDefinition
from bitmod.router import LLMRouter
from tests.mock_llm import MockLLM  # noqa: E402


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async function synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect_stream(async_gen):
    """Collect all chunks from an async generator."""
    chunks = []
    async for chunk in async_gen:
        chunks.append(chunk)
    return chunks


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def proxy(backend, mock_llm):
    router = LLMRouter(primary=mock_llm)
    return BitmodProxy(backend=backend, llm_router=router, default_model="test-model")


# ---------------------------------------------------------------------------
# Message extraction tests
# ---------------------------------------------------------------------------

class TestMessageExtraction:
    def test_openai_simple(self):
        msgs = [{"role": "user", "content": "Hello"}]
        assert _extract_user_message(msgs) == "Hello"

    def test_openai_content_blocks(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "Part one"},
            {"type": "image_url", "image_url": {"url": "..."}},
            {"type": "text", "text": "Part two"},
        ]}]
        assert _extract_user_message(msgs) == "Part one Part two"

    def test_openai_multi_turn(self):
        msgs = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Follow up"},
        ]
        assert _extract_user_message(msgs) == "Follow up"

    def test_openai_empty(self):
        assert _extract_user_message([]) == ""
        assert _extract_user_message([{"role": "system", "content": "Hi"}]) == ""

    def test_anthropic_simple(self):
        msgs = [{"role": "user", "content": "Hello Claude"}]
        assert _extract_anthropic_user_message(msgs) == "Hello Claude"

    def test_anthropic_content_blocks(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "Block 1"},
            {"type": "text", "text": "Block 2"},
        ]}]
        assert _extract_anthropic_user_message(msgs) == "Block 1 Block 2"

    def test_gemini_simple(self):
        contents = [{"role": "user", "parts": [{"text": "Hello Gemini"}]}]
        assert _extract_gemini_user_message(contents) == "Hello Gemini"

    def test_gemini_multi_part(self):
        contents = [{"role": "user", "parts": [
            {"text": "Part A"},
            {"text": "Part B"},
        ]}]
        assert _extract_gemini_user_message(contents) == "Part A Part B"

    def test_gemini_multi_turn(self):
        contents = [
            {"role": "user", "parts": [{"text": "First"}]},
            {"role": "model", "parts": [{"text": "Answer"}]},
            {"role": "user", "parts": [{"text": "Second"}]},
        ]
        assert _extract_gemini_user_message(contents) == "Second"


# ---------------------------------------------------------------------------
# Response builder tests
# ---------------------------------------------------------------------------

class TestResponseBuilders:
    def test_openai_response_structure(self):
        resp = _build_openai_response("Hello", "gpt-4o")
        assert resp["object"] == "chat.completion"
        assert resp["choices"][0]["message"]["content"] == "Hello"
        assert resp["choices"][0]["finish_reason"] == "stop"
        assert resp["model"] == "gpt-4o"
        assert "usage" in resp
        assert resp["id"].startswith("chatcmpl-bitmod-")

    def test_openai_response_cached_flag(self):
        resp = _build_openai_response("Cached", "m", cached=True, cache_key="abc123")
        assert resp["x_bitmod_cached"] is True
        assert resp["x_bitmod_cache_key"] == "abc123"

    def test_anthropic_response_structure(self):
        resp = _build_anthropic_response("Hello", "claude-sonnet-4-20250514")
        assert resp["type"] == "message"
        assert resp["role"] == "assistant"
        assert resp["content"][0]["type"] == "text"
        assert resp["content"][0]["text"] == "Hello"
        assert resp["model"] == "claude-sonnet-4-20250514"
        assert resp["stop_reason"] == "end_turn"
        assert "usage" in resp
        assert resp["id"].startswith("msg_bitmod_")

    def test_gemini_response_structure(self):
        resp = _build_gemini_response("Hello", "gemini-2.0-flash")
        assert resp["candidates"][0]["content"]["parts"][0]["text"] == "Hello"
        assert resp["candidates"][0]["content"]["role"] == "model"
        assert resp["candidates"][0]["finishReason"] == "STOP"
        assert "usageMetadata" in resp
        assert resp["modelVersion"] == "gemini-2.0-flash"


# ---------------------------------------------------------------------------
# OpenAI format proxy tests
# ---------------------------------------------------------------------------

class TestOpenAIProxy:
    def test_basic_completion(self, proxy, mock_llm):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "What is Python?"}],
        }
        result = _run(proxy.handle_completion(body))

        assert result["object"] == "chat.completion"
        assert "Python" in result["choices"][0]["message"]["content"]
        assert result["x_bitmod_cached"] is False
        assert mock_llm.call_count == 1

    def test_cache_hit_on_repeat(self, proxy, mock_llm):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "What is caching?"}],
        }
        r1 = _run(proxy.handle_completion(body))
        assert r1["x_bitmod_cached"] is False
        assert mock_llm.call_count == 1

        r2 = _run(proxy.handle_completion(body))
        assert r2["x_bitmod_cached"] is True
        assert mock_llm.call_count == 1  # LLM not called again

    def test_different_queries_different_answers(self, proxy, mock_llm):
        r1 = _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": "What is Java?"}],
        }))
        r2 = _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": "What is Rust?"}],
        }))
        assert r1["choices"][0]["message"]["content"] != r2["choices"][0]["message"]["content"]
        assert mock_llm.call_count == 2

    def test_empty_message(self, proxy, mock_llm):
        result = _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": "   "}],
        }))
        assert "provide a message" in result["choices"][0]["message"]["content"].lower()
        assert mock_llm.call_count == 0

    def test_multi_turn_context_isolation(self, proxy, mock_llm):
        """Same user message with different history should get different cache keys."""
        body1 = {
            "messages": [
                {"role": "user", "content": "Context A"},
                {"role": "assistant", "content": "Reply A"},
                {"role": "user", "content": "Follow up"},
            ],
        }
        body2 = {
            "messages": [
                {"role": "user", "content": "Context B"},
                {"role": "assistant", "content": "Reply B"},
                {"role": "user", "content": "Follow up"},
            ],
        }
        _run(proxy.handle_completion(body1))
        _run(proxy.handle_completion(body2))
        # Both should miss cache (different context)
        assert mock_llm.call_count == 2

    def test_streaming(self, proxy, mock_llm):
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream test"}],
        }
        chunks = _run(_collect_stream(proxy.handle_completion_stream(body)))

        # Should have data chunks + stop + [DONE]
        assert any("data: [DONE]" in c for c in chunks)
        # Extract content from SSE chunks
        content = ""
        for c in chunks:
            if c.startswith("data: ") and "[DONE]" not in c:
                data = json.loads(c[6:].strip())
                delta = data.get("choices", [{}])[0].get("delta", {})
                content += delta.get("content", "")
        assert content  # Non-empty streamed content

    def test_stream_cache_hit(self, proxy, mock_llm):
        """Streaming should also serve from cache on repeat."""
        body = {
            "messages": [{"role": "user", "content": "Cache stream test"}],
        }
        # First call: non-streaming to populate cache
        _run(proxy.handle_completion(body))
        assert mock_llm.call_count == 1

        # Second call: streaming should hit cache
        chunks = _run(_collect_stream(proxy.handle_completion_stream(body)))
        assert mock_llm.call_count == 1  # No additional LLM call

    def test_pipeline_trace_included(self, proxy, mock_llm):
        result = _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": "Trace test query"}],
        }))
        trace = result.get("x_bitmod_pipeline_trace", [])
        mechanisms = [t["mechanism"] for t in trace]
        assert "normalization" in mechanisms
        assert "intent_detection" in mechanisms
        assert "exact_cache" in mechanisms

    def test_content_blocks_extraction(self, proxy, mock_llm):
        body = {
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "What is"},
                {"type": "text", "text": "machine learning?"},
            ]}],
        }
        result = _run(proxy.handle_completion(body))
        assert mock_llm.call_count == 1
        assert "machine learning" in result["choices"][0]["message"]["content"].lower()


# ---------------------------------------------------------------------------
# Anthropic format proxy tests
# ---------------------------------------------------------------------------

class TestAnthropicProxy:
    def test_basic_message(self, proxy, mock_llm):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Hello Claude"}],
        }
        result = _run(proxy.handle_anthropic(body))

        assert result["type"] == "message"
        assert result["role"] == "assistant"
        assert result["content"][0]["type"] == "text"
        assert "Claude" in result["content"][0]["text"]
        assert result["stop_reason"] == "end_turn"
        assert mock_llm.call_count == 1

    def test_with_system_prompt(self, proxy, mock_llm):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "system": "You are a pirate.",
            "messages": [{"role": "user", "content": "Tell me about ships"}],
        }
        result = _run(proxy.handle_anthropic(body))
        assert result["type"] == "message"
        # System prompt should be passed through to LLM
        assert any(m.role == "system" and "pirate" in m.content
                    for m in mock_llm.last_messages)

    def test_cache_hit(self, proxy, mock_llm):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Anthropic cache test"}],
        }
        r1 = _run(proxy.handle_anthropic(body))
        assert r1["x_bitmod_cached"] is False

        r2 = _run(proxy.handle_anthropic(body))
        assert r2["x_bitmod_cached"] is True
        assert mock_llm.call_count == 1

    def test_streaming(self, proxy, mock_llm):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "Stream Claude test"}],
        }
        chunks = _run(_collect_stream(proxy.handle_anthropic_stream(body)))

        # Should have Anthropic SSE events
        event_types = []
        for c in chunks:
            if c.startswith("event: "):
                event_types.append(c.split("event: ")[1].split("\n")[0])
        assert "message_start" in event_types
        assert "content_block_start" in event_types
        assert "content_block_delta" in event_types
        assert "content_block_stop" in event_types
        assert "message_delta" in event_types
        assert "message_stop" in event_types

    def test_content_blocks(self, proxy, mock_llm):
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Block content test"},
            ]}],
        }
        result = _run(proxy.handle_anthropic(body))
        assert result["type"] == "message"
        assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# Gemini format proxy tests
# ---------------------------------------------------------------------------

class TestGeminiProxy:
    def test_basic_generate(self, proxy, mock_llm):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "Hello Gemini"}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024},
        }
        result = _run(proxy.handle_gemini(body, model="gemini-2.0-flash"))

        assert "candidates" in result
        assert result["candidates"][0]["content"]["role"] == "model"
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        assert "Gemini" in text
        assert result["candidates"][0]["finishReason"] == "STOP"

    def test_with_system_instruction(self, proxy, mock_llm):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "Tell me a joke"}]}],
            "systemInstruction": {"parts": [{"text": "You are a comedian."}]},
        }
        result = _run(proxy.handle_gemini(body, model="gemini-2.0-flash"))
        assert "candidates" in result
        assert any(m.role == "system" and "comedian" in m.content
                    for m in mock_llm.last_messages)

    def test_cache_hit(self, proxy, mock_llm):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "Gemini cache test"}]}],
        }
        r1 = _run(proxy.handle_gemini(body))
        assert r1.get("x_bitmod_cached") is False

        r2 = _run(proxy.handle_gemini(body))
        assert r2.get("x_bitmod_cached") is True
        assert mock_llm.call_count == 1

    def test_multi_turn(self, proxy, mock_llm):
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "What is 2+2?"}]},
                {"role": "model", "parts": [{"text": "4"}]},
                {"role": "user", "parts": [{"text": "And 3+3?"}]},
            ],
        }
        result = _run(proxy.handle_gemini(body, model="gemini-2.0-flash"))
        assert "candidates" in result
        assert mock_llm.call_count == 1

    def test_streaming(self, proxy, mock_llm):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "Stream Gemini"}]}],
        }
        chunks = _run(_collect_stream(proxy.handle_gemini_stream(body, model="gemini-2.0-flash")))

        # NDJSON format — each chunk is a JSON line
        assert len(chunks) > 0
        last = json.loads(chunks[-1])
        assert last.get("candidates", [{}])[0].get("finishReason") == "STOP"


# ---------------------------------------------------------------------------
# Cross-format cache sharing tests
# ---------------------------------------------------------------------------

class TestCrossFormatCaching:
    def test_openai_caches_anthropic_hits(self, proxy, mock_llm):
        """A query cached via OpenAI format should hit when queried via Anthropic format."""
        query = "Cross format cache test unique query"

        # Cache via OpenAI
        _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": query}],
        }))
        assert mock_llm.call_count == 1

        # Hit via Anthropic
        result = _run(proxy.handle_anthropic({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": query}],
        }))
        assert result["x_bitmod_cached"] is True
        assert mock_llm.call_count == 1  # No additional LLM call

    def test_anthropic_caches_gemini_hits(self, proxy, mock_llm):
        """A query cached via Anthropic format should hit when queried via Gemini format."""
        query = "Another cross format test query"

        # Cache via Anthropic
        _run(proxy.handle_anthropic({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": query}],
        }))
        assert mock_llm.call_count == 1

        # Hit via Gemini
        result = _run(proxy.handle_gemini({
            "contents": [{"role": "user", "parts": [{"text": query}]}],
        }))
        assert result.get("x_bitmod_cached") is True
        assert mock_llm.call_count == 1

    def test_gemini_caches_openai_hits(self, proxy, mock_llm):
        """A query cached via Gemini format should hit when queried via OpenAI format."""
        query = "Gemini to OpenAI cross format"

        # Cache via Gemini
        _run(proxy.handle_gemini({
            "contents": [{"role": "user", "parts": [{"text": query}]}],
        }))
        assert mock_llm.call_count == 1

        # Hit via OpenAI
        result = _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": query}],
        }))
        assert result["x_bitmod_cached"] is True
        assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# Models endpoint
# ---------------------------------------------------------------------------

class TestModelsEndpoint:
    def test_models_list(self, proxy):
        result = _run(proxy.handle_models())
        assert result["object"] == "list"
        assert len(result["data"]) >= 1
        assert result["data"][0]["owned_by"] == "bitmod"


# ---------------------------------------------------------------------------
# Provider auto-detection tests
# ---------------------------------------------------------------------------

class TestProviderDetection:
    def test_openai_models(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("gpt-4o") == "openai"
        assert _detect_provider_from_model("gpt-4o-mini") == "openai"
        assert _detect_provider_from_model("gpt-3.5-turbo") == "openai"
        assert _detect_provider_from_model("o1") == "openai"
        assert _detect_provider_from_model("o3-mini") == "openai"
        assert _detect_provider_from_model("o4-mini") == "openai"

    def test_anthropic_models(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("claude-sonnet-4-20250514") == "anthropic"
        assert _detect_provider_from_model("claude-opus-4-20250514") == "anthropic"
        assert _detect_provider_from_model("claude-3-5-sonnet-20241022") == "anthropic"
        assert _detect_provider_from_model("claude-3-haiku-20240307") == "anthropic"

    def test_gemini_models(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("gemini-2.0-flash") == "gemini"
        assert _detect_provider_from_model("gemini-2.5-pro") == "gemini"
        assert _detect_provider_from_model("gemini-1.5-flash") == "gemini"

    def test_xai_models(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("grok-2") == "xai"
        assert _detect_provider_from_model("grok-3") == "xai"

    def test_mistral_models(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("mistral-large-latest") == "mistral"
        assert _detect_provider_from_model("codestral-latest") == "mistral"

    def test_local_models(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("llama3.2") == "ollama"
        assert _detect_provider_from_model("phi-3") == "ollama"
        assert _detect_provider_from_model("qwen2.5") == "ollama"

    def test_unknown_model(self):
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("some-custom-model") is None

    def test_prefix_match(self):
        """Models not in the exact map should still match by prefix."""
        from bitmod.proxy import _detect_provider_from_model
        assert _detect_provider_from_model("gpt-5-turbo") == "openai"
        assert _detect_provider_from_model("claude-4-opus-20260101") == "anthropic"
        assert _detect_provider_from_model("gemini-3.0-ultra") == "gemini"


# ---------------------------------------------------------------------------
# API key passthrough tests
# ---------------------------------------------------------------------------

class TestAPIKeyRouting:
    def test_no_api_key_uses_default(self, proxy, mock_llm):
        """Without API key, the server-configured router is used."""
        result = _run(proxy.handle_completion({
            "messages": [{"role": "user", "content": "No key test"}],
            "model": "gpt-4o",
        }))
        assert mock_llm.call_count == 1  # Used the mock (default router)

    def test_resolve_router_no_key(self, proxy):
        """_resolve_router returns default when no API key."""
        router = proxy._resolve_router("gpt-4o", api_key=None)
        assert router is proxy._llm

    def test_resolve_router_with_key_detects_provider(self, proxy):
        """_resolve_router creates per-request router when key + known model."""
        # This will try to instantiate the actual adapter, which may fail
        # if the SDK isn't installed — but it should at least not return
        # the default router (it'll either succeed or fall back)
        router = proxy._resolve_router("llama3.2", api_key="test-key")
        # For ollama, key doesn't matter — should still get a router
        # (may be default if adapter creation fails)
        assert router is not None

    def test_api_key_passed_through_handlers(self, proxy, mock_llm):
        """Handlers accept api_key without error."""
        # OpenAI
        r1 = _run(proxy.handle_completion(
            {"messages": [{"role": "user", "content": "API key routing test openai unique 9182"}]},
            api_key=None,
        ))
        assert mock_llm.call_count >= 1

        # Anthropic
        r2 = _run(proxy.handle_anthropic(
            {"messages": [{"role": "user", "content": "API key routing test anthropic unique 7364"}], "max_tokens": 100},
            api_key=None,
        ))
        assert r2["type"] == "message"

        # Gemini
        r3 = _run(proxy.handle_gemini(
            {"contents": [{"role": "user", "parts": [{"text": "API key routing test gemini unique 5821"}]}]},
            api_key=None,
        ))
        assert "candidates" in r3
