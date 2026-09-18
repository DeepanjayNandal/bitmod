# bitmod-client

Official Python SDK for [BitMod](https://bitmod.io) — Intelligent AI Cache Infrastructure.

Drop BitMod in front of any LLM and get instant caching, cost tracking, and hybrid search with zero code changes to your existing OpenAI/Anthropic calls.

## Install

```bash
pip install bitmod-client

# With OpenAI proxy support
pip install bitmod-client[openai]

# With Anthropic proxy support
pip install bitmod-client[anthropic]

# Everything
pip install bitmod-client[all]
```

## Quick Start

```python
from bitmod_client import BitmodClient

bm = BitmodClient(api_key="bm_...")
```

### Pattern A: Cache-Only Lookup

Check the cache before making your own LLM call. Pay nothing for repeated questions.

```python
result = bm.lookup("What is HIPAA?")
if result.hit:
    print(result.answer)       # Instant, free
    print(result.cache_layer)  # e.g. "semantic_l2"
else:
    # Cache miss — call your LLM directly
    ...
```

### Pattern B: Full Query with Automatic Caching

Let BitMod handle everything: cache check, LLM fallback, and result storage.

```python
result = bm.ask(
    "What is HIPAA?",
    model="gpt-4o",
    llm_key="sk-...",
)
print(result.answer)
print(f"Cached: {result.cached}")
print(f"Cost: ${result.cost_usd:.4f}, Saved: ${result.cost_saved:.4f}")
```

### Pattern C: Drop-In OpenAI Proxy

Use your existing OpenAI code unchanged. BitMod intercepts, caches, and forwards.

```python
client = bm.openai_client(api_key="sk-...")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is HIPAA?"}],
)
print(response.choices[0].message.content)
```

### Pattern D: Drop-In Anthropic Proxy

Same idea, for Anthropic.

```python
client = bm.anthropic_client(api_key="sk-ant-...")

message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "What is HIPAA?"}],
)
print(message.content[0].text)
```

### Ingest Content

Feed your own documents into BitMod's knowledge store for retrieval and caching.

```python
# Text
bm.ingest_text("HIPAA requires...", title="HIPAA Overview", tags=["compliance"])

# File (PDF, DOCX, TXT, MD, HTML, CSV)
bm.ingest_file("docs/hipaa_guide.pdf")
```

### Search

Hybrid semantic + keyword search across all ingested content.

```python
results = bm.search("patient data requirements", limit=5)
for r in results:
    print(f"[{r.score:.2f}] {r.text[:100]}")
```

### Usage Stats

Track your savings.

```python
stats = bm.usage(days=30)
print(f"Queries: {stats.total_queries}")
print(f"Hit rate: {stats.hit_rate_pct:.1f}%")
print(f"Total saved: ${stats.total_savings_usd:.2f}")
```

## Async

Every method is available in async form via `AsyncBitmodClient`.

```python
import asyncio
from bitmod_client import AsyncBitmodClient

async def main():
    async with AsyncBitmodClient(api_key="bm_...") as bm:
        result = await bm.ask("What is HIPAA?", model="gpt-4o", llm_key="sk-...")
        print(result.answer)

asyncio.run(main())
```

## Configuration

| Parameter    | Env Variable      | Default                  |
|-------------|-------------------|--------------------------|
| `api_key`   | `BITMOD_API_KEY`  | *(required)*             |
| `base_url`  | `BITMOD_BASE_URL` | `http://localhost:8000`  |
| `timeout`   | —                 | `60.0` seconds           |
| `max_retries` | —              | `2`                      |

## Error Handling

All errors inherit from `BitmodError`:

```python
from bitmod_client import BitmodError, BitmodAuthError, BitmodRateLimitError

try:
    result = bm.ask("query")
except BitmodAuthError:
    print("Invalid API key")
except BitmodRateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except BitmodError as e:
    print(f"BitMod error: {e} (status={e.status_code})")
```

## License

MIT
