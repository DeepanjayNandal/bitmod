#!/usr/bin/env python3
"""An OpenAI-compatible endpoint that returns canned completions.

The HTTP benchmark drives the proxy over the wire, and the proxy reaches its
LLM over HTTP via BITMOD_LLM_URL. Pointing that at a real model would make
every cache miss cost a real generation — pass 1 is all misses by design, so a
few thousand queries becomes hours — and would mean the two runners differed in
whether generation is real, not only in transport. A disagreement between them
could then not be attributed.

This serves the same answers as tests.mock_llm.MockLLM, from the same
definition, so generation is identical on both sides.

    python tests/benchmark/stub_llm_server.py --port 11500
    BITMOD_LLM_URL=http://localhost:11500/v1 bitmod serve
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from tests.mock_llm import (  # noqa: E402
    MOCK_INPUT_TOKENS,
    MOCK_MODEL,
    MOCK_OUTPUT_TOKENS,
    STREAM_WORDS,
    answer_book_size,
    canned_answer,
    last_user_text,
    load_answer_book,
)

app = FastAPI(title="Bitmod stub LLM")

# Counted so a benchmark run can assert the cache actually avoided generations
# rather than inferring it from timing.
STATS = {"completions": 0, "streamed": 0}


def _completion_body(content: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or MOCK_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": MOCK_INPUT_TOKENS,
            "completion_tokens": MOCK_OUTPUT_TOKENS,
            "total_tokens": MOCK_INPUT_TOKENS + MOCK_OUTPUT_TOKENS,
        },
    }


def _stream_chunks(model: str):
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    for word in STREAM_WORDS:
        yield "data: " + json.dumps(
            {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model or MOCK_MODEL,
                "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}],
            }
        ) + "\n\n"
    yield "data: " + json.dumps(
        {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model or MOCK_MODEL,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    ) + "\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", MOCK_MODEL)
    messages = body.get("messages", [])

    if body.get("stream"):
        STATS["streamed"] += 1
        return StreamingResponse(_stream_chunks(model), media_type="text/event-stream")

    STATS["completions"] += 1
    return _completion_body(canned_answer(last_user_text(messages)), model)


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": MOCK_MODEL, "object": "model"}]}


@app.get("/health")
async def health():
    return {"status": "ok", "stub": True, "answers_loaded": answer_book_size(), **STATS}


@app.post("/reset")
async def reset():
    STATS.update(completions=0, streamed=0)
    return dict(STATS)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI-compatible stub LLM for benchmarking")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11500)
    parser.add_argument(
        "--answers",
        default="",
        help="JSON {question: answer} written by the in-process runner. Both runners must "
        "generate identical text, so the HTTP side reads the same book rather than "
        "re-fetching the corpus and risking a different sample.",
    )
    args = parser.parse_args()

    if args.answers:
        book = json.loads(Path(args.answers).read_text())
        load_answer_book(book)
        print(f"loaded {answer_book_size()} answers from {args.answers}", flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
