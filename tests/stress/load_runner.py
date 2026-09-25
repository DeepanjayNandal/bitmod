"""Load runner — sends prompts through the BitMod API and logs results.

Usage:
    python tests/stress/load_runner.py [--start N] [--count N] [--concurrency N]

Reads prompts from prompts_100k.jsonl, sends each through POST /v1/chat,
and logs structured results to /tmp/bitmod-stress-results.jsonl.

Signals:
    - Writes /tmp/bitmod-stress-pause to pause (watchdog can trigger restarts)
    - Writes /tmp/bitmod-stress-stop to stop
    - Reads /tmp/bitmod-stress-restart to reset from a given offset
"""

import argparse
import asyncio
import json
import time
import os
from pathlib import Path
from datetime import datetime, timezone

import httpx


def _gateway_auth_headers() -> dict:
    """Credentials for the gateway, empty when BITMOD_API_KEY is unset.

    The gateway accepts one of its BITMOD_API_KEYS as `Authorization: ApiKey
    <key>`. Sending nothing when unset keeps this runnable against a gateway
    with auth disabled.
    """
    import os

    key = os.getenv("BITMOD_API_KEY", "")
    return {"Authorization": f"ApiKey {key}"} if key else {}


GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000")
RESULTS_LOG = Path("/tmp/bitmod-stress-results.jsonl")
PAUSE_SIGNAL = Path("/tmp/bitmod-stress-pause")
STOP_SIGNAL = Path("/tmp/bitmod-stress-stop")
RESTART_SIGNAL = Path("/tmp/bitmod-stress-restart")
STATUS_FILE = Path("/tmp/bitmod-stress-status.json")
PROMPTS_FILE = Path(__file__).parent / "prompts_100k.jsonl"

# Concurrency — keep it moderate to avoid overwhelming Ollama
DEFAULT_CONCURRENCY = 3
REQUEST_TIMEOUT = 120.0


def load_prompts(path: Path, start: int = 0, count: int | None = None) -> list[dict]:
    prompts = []
    with open(path) as f:
        for i, line in enumerate(f):
            if i < start:
                continue
            if count and len(prompts) >= count:
                break
            prompts.append(json.loads(line))
    return prompts


def _extract_metadata(data: dict, result: dict):
    """Extract cache metadata from a response dict into result."""
    result["cache_hit"] = data.get("cached", False)
    result["model_used"] = data.get("model_used", "unknown")
    result["cache_key"] = data.get("cache_key", "")
    result["answer_len"] = len(data.get("answer", ""))

    trace = data.get("pipeline_trace", [])
    if trace:
        result["pipeline_steps"] = [
            {"mechanism": s.get("mechanism", ""), "action": s.get("action", "")}
            for s in trace
        ]
        hit_layers = [
            s["mechanism"] for s in trace
            if s.get("action") in ("HIT", "PARTIAL", "COMPOSED")
        ]
        result["hit_layers"] = hit_layers
    else:
        result["hit_layers"] = []
    result["success"] = True


def _parse_sse_body(text: str) -> tuple[dict | None, str]:
    """Parse an SSE text body, return (done_data, answer_text)."""
    tokens = []
    done_data = None
    current_event = "message"
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
            if current_event == "done":
                try:
                    done_data = json.loads(data_str)
                except json.JSONDecodeError:
                    pass
            elif current_event == "message":
                try:
                    chunk = json.loads(data_str)
                    t = chunk.get("token", "")
                    if t:
                        tokens.append(t)
                except json.JSONDecodeError:
                    pass
    return done_data, "".join(tokens)


async def send_prompt(client: httpx.AsyncClient, prompt: dict) -> dict:
    """Send a single prompt and return structured result.

    The gateway proxies to the chat service. Depending on whether the response
    is a cache hit or LLM generation, the response may be:
    - JSON (application/json) with answer + pipeline_trace
    - SSE (text/event-stream) with token events + a final 'event: done'

    The gateway buffers the full response, so we read it all at once and
    detect the format from content-type.
    """
    start_time = time.monotonic()
    result = {
        "index": prompt["index"],
        "category": prompt["category"],
        "message": prompt["message"][:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/chat",
            json={
                "message": prompt["message"],
                "project_id": "stress-test",
                "stream": False,
            },
            headers={"X-Bitmod-Debug": "true", **_gateway_auth_headers()},
            timeout=REQUEST_TIMEOUT,
        )
        elapsed_ms = (time.monotonic() - start_time) * 1000
        result["status_code"] = resp.status_code
        result["elapsed_ms"] = round(elapsed_ms, 1)

        if resp.status_code != 200:
            result["success"] = False
            result["error"] = resp.text[:500]
            return result

        content_type = resp.headers.get("content-type", "")
        body = resp.text

        # Try JSON first (cache hits come back as JSON)
        if "application/json" in content_type:
            try:
                data = resp.json()
                _extract_metadata(data, result)
                return result
            except json.JSONDecodeError:
                pass

        # Try SSE parsing (LLM generation streams)
        if "text/event-stream" in content_type or body.startswith(":") or "event:" in body[:200]:
            done_data, answer_text = _parse_sse_body(body)
            if done_data:
                _extract_metadata(done_data, result)
                if not result.get("answer_len"):
                    result["answer_len"] = len(answer_text)
                return result

        # Fallback: try parsing body as JSON regardless of content-type
        try:
            data = json.loads(body)
            _extract_metadata(data, result)
            return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Last resort: SSE parse regardless of content-type
        done_data, answer_text = _parse_sse_body(body)
        if done_data:
            _extract_metadata(done_data, result)
            if not result.get("answer_len"):
                result["answer_len"] = len(answer_text)
            return result

        # Nothing worked
        result["success"] = False
        result["error"] = f"unparseable response (ct={content_type}): {body[:200]}"

    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        result["elapsed_ms"] = round(elapsed_ms, 1)
        result["success"] = False
        result["error"] = "timeout"
    except Exception as e:
        elapsed_ms = (time.monotonic() - start_time) * 1000
        result["elapsed_ms"] = round(elapsed_ms, 1)
        result["success"] = False
        result["error"] = str(e)[:500]

    return result


def write_status(completed: int, total: int, errors: int, start_time: float):
    """Write current status for metrics agent to read."""
    elapsed = time.monotonic() - start_time
    status = {
        "completed": completed,
        "total": total,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
        "prompts_per_second": round(completed / max(elapsed, 0.1), 2),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    STATUS_FILE.write_text(json.dumps(status))


async def run(start: int = 0, count: int | None = None, concurrency: int = DEFAULT_CONCURRENCY):
    """Main load generation loop."""
    # Clean signals
    for sig in [PAUSE_SIGNAL, STOP_SIGNAL, RESTART_SIGNAL]:
        sig.unlink(missing_ok=True)

    prompts = load_prompts(PROMPTS_FILE, start, count)
    total = len(prompts)
    print(f"Loaded {total} prompts (start={start})")

    completed = 0
    errors = 0
    run_start = time.monotonic()
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:
        # Open results log in append mode
        log_file = open(RESULTS_LOG, "a")

        async def process_one(prompt):
            nonlocal completed, errors
            async with semaphore:
                # Check signals
                if STOP_SIGNAL.exists():
                    return
                while PAUSE_SIGNAL.exists():
                    await asyncio.sleep(1)

                result = await send_prompt(client, prompt)
                log_file.write(json.dumps(result) + "\n")
                log_file.flush()

                completed += 1
                if not result.get("success"):
                    errors += 1

                if completed % 100 == 0:
                    write_status(completed, total, errors, run_start)
                    rate = completed / (time.monotonic() - run_start)
                    print(f"  [{completed}/{total}] {rate:.1f} req/s | errors: {errors}")

        # Process in batches to allow signal checking
        batch_size = 50
        for i in range(0, total, batch_size):
            if STOP_SIGNAL.exists():
                print("Stop signal received.")
                break

            batch = prompts[i:i + batch_size]
            tasks = [process_one(p) for p in batch]
            await asyncio.gather(*tasks)

            # Check for restart signal
            if RESTART_SIGNAL.exists():
                restart_data = json.loads(RESTART_SIGNAL.read_text())
                RESTART_SIGNAL.unlink()
                print(f"Restart signal: resuming from {restart_data.get('offset', 0)}")
                log_file.close()
                await run(
                    start=restart_data.get("offset", 0),
                    count=restart_data.get("count", count),
                    concurrency=concurrency,
                )
                return

        log_file.close()
        write_status(completed, total, errors, run_start)
        elapsed = time.monotonic() - run_start
        print(f"\nDone: {completed}/{total} in {elapsed:.1f}s ({completed/max(elapsed,0.1):.1f} req/s), {errors} errors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = parser.parse_args()
    asyncio.run(run(args.start, args.count, args.concurrency))
