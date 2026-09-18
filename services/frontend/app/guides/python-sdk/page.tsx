import type { Metadata } from "next"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { CodeBlock } from "@/components/shared/code-block"
import { ArrowRight, Clock, Zap, Database, Shield, Terminal } from "lucide-react"

export const metadata: Metadata = {
  title: "Python SDK | Guides",
  description: "Complete guide to the BitMod Python SDK: sync and async clients, cache lookups, queries, search, ingestion, error handling, and provider proxies.",
}

export default function PythonSdkGuide() {
  return (
    <div className="relative">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
      </div>

      <article className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-12">
          <div className="flex items-center gap-3 mb-4">
            <Badge variant="accent">Guide</Badge>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>10 min read</span>
            </div>
            <Badge className="bg-yellow-500/15 text-yellow-400 border-yellow-500/30">Intermediate</Badge>
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            Python SDK
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Complete guide to the BitMod Python SDK — sync and async clients, cache lookups, queries, search, document ingestion, error handling, and drop-in provider proxies.
          </p>
        </div>

        <div className="space-y-12">
          {/* 1. Installation */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">1</div>
              <h2 className="text-xl font-semibold">Installation</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              The SDK is not published to PyPI. Install it from the repository; the base package has no dependencies beyond <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">httpx</code>.
            </p>
            <CodeBlock filename="terminal">
{`git clone https://github.com/DeepanjayNandal/bitmod.git\ncd bitmod/sdk/python\npip install -e .`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3 mb-3">
              To use the drop-in provider proxies, install the optional extras:
            </p>
            <CodeBlock filename="terminal">
{`# OpenAI proxy support
pip install -e ".[openai]"

# Anthropic proxy support
pip install -e ".[anthropic]"

# Both
pip install -e ".[openai,anthropic]"`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Requires Python 3.10 or newer.
            </p>
          </section>

          {/* 2. Quick Start */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">2</div>
              <h2 className="text-xl font-semibold">Quick Start</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Import the client, point it at your BitMod gateway, and start saving on LLM costs immediately:
            </p>
            <CodeBlock filename="python">
{`from bitmod_client import BitmodClient

client = BitmodClient(
    base_url="http://localhost:8000",
    api_key="bm_your_key_here",
)

# Check the cache first — no LLM call, no cost
result = client.lookup("What is semantic caching?")
if result.hit:
    print(result.answer)       # instant, free
    print(result.confidence)   # e.g. 0.94
    print(result.latency_ms)   # < 1ms

# Full query — cache check + LLM fallback
result = client.ask("What is semantic caching?", model="gpt-4o")
print(result.answer)
print(f"Cached: {result.cached}, Saved: \${result.cost_saved:.4f}")

client.close()`}
            </CodeBlock>
          </section>

          {/* 3. Configuration */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">3</div>
              <h2 className="text-xl font-semibold">Configuration</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              The client accepts four constructor parameters. All can be overridden with environment variables.
            </p>
            <CodeBlock filename="python">
{`client = BitmodClient(
    base_url="http://localhost:8000",  # or BITMOD_BASE_URL env var
    api_key="bm_your_key_here",        # or BITMOD_API_KEY env var
    timeout=60.0,                      # request timeout in seconds
    max_retries=2,                     # automatic retries on transient failures
)`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3 mb-3">
              Environment variable configuration:
            </p>
            <CodeBlock filename="terminal">
{`export BITMOD_BASE_URL="https://bitmod.example.com"
export BITMOD_API_KEY="bm_your_key_here"`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              When environment variables are set, you can instantiate the client with no arguments: <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BitmodClient()</code>.
              If no <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_BASE_URL</code> is set, it defaults to <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">http://localhost:8000</code>.
            </p>
          </section>

          {/* 4. Cache Lookup */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">4</div>
              <h2 className="text-xl font-semibold">Cache Lookup</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Check the cache without triggering an LLM call. Use this when you want zero cost and are okay with a miss returning no answer.
            </p>
            <CodeBlock filename="python">
{`result = client.lookup("What is HIPAA?", confidence=0.8)

if result.hit:
    print(result.answer)       # cached response text
    print(result.confidence)   # float, e.g. 0.92
    print(result.cache_layer)  # which cache layer matched, e.g. "semantic"
    print(result.latency_ms)   # sub-millisecond on hits
else:
    print("Cache miss — no answer above the confidence threshold")`}
            </CodeBlock>
            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">LookupResult fields</p>
                <div className="text-xs text-muted-foreground space-y-1 font-mono">
                  <p><span className="text-primary/80">hit</span>: bool — whether a cached answer was found</p>
                  <p><span className="text-primary/80">answer</span>: str | None — the cached response text</p>
                  <p><span className="text-primary/80">confidence</span>: float — match confidence (0.0-1.0)</p>
                  <p><span className="text-primary/80">cache_layer</span>: str | None — which cache layer matched</p>
                  <p><span className="text-primary/80">latency_ms</span>: float — round-trip time in milliseconds</p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 5. Ask */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">5</div>
              <h2 className="text-xl font-semibold">Ask</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Full query with automatic caching. BitMod checks the cache first and only calls the LLM on a miss. The response is cached for future queries.
            </p>
            <CodeBlock filename="python">
{`result = client.ask(
    "Explain the CAP theorem in distributed systems",
    model="gpt-4o",
    llm_key="sk-...",               # your upstream LLM key
    temperature=0.0,                 # deterministic for better cache hits
    system_prompt="You are a distributed systems expert.",
    metadata={"team": "backend"},    # arbitrary metadata for analytics
)

print(result.answer)          # the response text
print(result.cached)          # True if served from cache
print(result.cache_layer)     # e.g. "semantic" or None if LLM was called
print(result.model)           # "gpt-4o"
print(result.input_tokens)    # tokens consumed (0 on cache hit)
print(result.output_tokens)   # tokens generated (0 on cache hit)
print(result.cost_usd)        # cost of this query
print(result.cost_saved)      # savings vs. a fresh LLM call
print(result.latency_ms)      # total round-trip time`}
            </CodeBlock>
            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">AskResult fields</p>
                <div className="text-xs text-muted-foreground space-y-1 font-mono">
                  <p><span className="text-primary/80">answer</span>: str — the response text</p>
                  <p><span className="text-primary/80">cached</span>: bool — whether it was served from cache</p>
                  <p><span className="text-primary/80">cache_layer</span>: str | None — cache layer that matched</p>
                  <p><span className="text-primary/80">model</span>: str — LLM model used</p>
                  <p><span className="text-primary/80">input_tokens</span>: int — input tokens consumed</p>
                  <p><span className="text-primary/80">output_tokens</span>: int — output tokens generated</p>
                  <p><span className="text-primary/80">cost_usd</span>: float — cost of this query</p>
                  <p><span className="text-primary/80">cost_saved</span>: float — cost saved by caching</p>
                  <p><span className="text-primary/80">latency_ms</span>: float — round-trip time in milliseconds</p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 6. Search */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">6</div>
              <h2 className="text-xl font-semibold">Search</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Hybrid semantic + keyword search across all ingested content. Results are ranked by relevance.
            </p>
            <CodeBlock filename="python">
{`results = client.search("database migration strategies", limit=5, offset=0)

for result in results:
    print(result.id)         # document chunk ID
    print(result.text)       # matched text snippet
    print(result.score)      # relevance score (0.0-1.0)
    print(result.metadata)   # dict of associated metadata`}
            </CodeBlock>
            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">SearchResult fields</p>
                <div className="text-xs text-muted-foreground space-y-1 font-mono">
                  <p><span className="text-primary/80">id</span>: str — document chunk identifier</p>
                  <p><span className="text-primary/80">text</span>: str — matched text content</p>
                  <p><span className="text-primary/80">score</span>: float — relevance score (0.0-1.0)</p>
                  <p><span className="text-primary/80">metadata</span>: dict — associated key-value metadata</p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 7. Document Ingestion */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">7</div>
              <h2 className="text-xl font-semibold">Document Ingestion</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Ingest content into the BitMod knowledge store for search and retrieval. Supports raw text and file uploads (PDF, DOCX, TXT, MD, HTML, CSV).
            </p>

            <div className="space-y-4">
              <CodeBlock filename="python">
{`# Ingest raw text
result = client.ingest_text(
    "BitMod uses a 9-layer intelligent cache engine with Bayesian evidence accumulation.",
    title="Architecture Overview",
    tags=["architecture", "cache"],
)
print(result.id)       # document ID
print(result.chunks)   # number of chunks created
print(result.status)   # "ok"`}
              </CodeBlock>

              <CodeBlock filename="python">
{`# Ingest a file
result = client.ingest_file("/path/to/document.pdf")
print(f"Ingested {result.chunks} chunks (id: {result.id})")`}
              </CodeBlock>
            </div>

            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">IngestResult fields</p>
                <div className="text-xs text-muted-foreground space-y-1 font-mono">
                  <p><span className="text-primary/80">id</span>: str — unique document identifier</p>
                  <p><span className="text-primary/80">chunks</span>: int — number of chunks created</p>
                  <p><span className="text-primary/80">status</span>: str — ingestion status (&quot;ok&quot;)</p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 8. Usage Analytics */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">8</div>
              <h2 className="text-xl font-semibold">Usage Analytics</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Retrieve aggregated usage statistics and cost savings over a configurable time window.
            </p>
            <CodeBlock filename="python">
{`stats = client.usage(days=30, limit=100, offset=0)

print(f"Total queries:  {stats.total_queries}")
print(f"Cache hits:     {stats.cache_hits}")
print(f"Cache misses:   {stats.cache_misses}")
print(f"Hit rate:       {stats.hit_rate_pct}%")
print(f"Total cost:     \${stats.total_cost_usd:.2f}")
print(f"Total saved:    \${stats.total_savings_usd:.2f}")

# Daily breakdown
for day in stats.daily_breakdown:
    print(f"  {day['date']}: {day['queries']} queries, {day['hits']} hits")`}
            </CodeBlock>
            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">UsageStats fields</p>
                <div className="text-xs text-muted-foreground space-y-1 font-mono">
                  <p><span className="text-primary/80">total_queries</span>: int — total queries in the period</p>
                  <p><span className="text-primary/80">cache_hits</span>: int — queries served from cache</p>
                  <p><span className="text-primary/80">cache_misses</span>: int — queries that required an LLM call</p>
                  <p><span className="text-primary/80">hit_rate_pct</span>: float — cache hit rate as a percentage</p>
                  <p><span className="text-primary/80">total_cost_usd</span>: float — total LLM cost in USD</p>
                  <p><span className="text-primary/80">total_savings_usd</span>: float — total savings from cache hits</p>
                  <p><span className="text-primary/80">daily_breakdown</span>: list[dict] — per-day statistics</p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 9. Health Check */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">9</div>
              <h2 className="text-xl font-semibold">Health Check</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Verify the BitMod gateway is running and inspect its status.
            </p>
            <CodeBlock filename="python">
{`health = client.health()

print(health.status)          # "ok"
print(health.healthy)         # True (property: status == "ok")
print(health.version)         # e.g. "0.2.0"
print(health.cache_layers)    # 9
print(health.uptime_seconds)  # e.g. 86400.0`}
            </CodeBlock>
          </section>

          {/* 10. Async Client */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">10</div>
              <h2 className="text-xl font-semibold">Async Client</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              The <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">AsyncBitmodClient</code> provides the same API surface with <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">async</code>/<code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">await</code> support. Use it in FastAPI, aiohttp, or any async context.
            </p>
            <CodeBlock filename="python">
{`import asyncio
from bitmod_client import AsyncBitmodClient

async def main():
    async with AsyncBitmodClient(api_key="bm_...") as client:
        # All methods are awaitable
        result = await client.lookup("What is HIPAA?")
        if result.hit:
            print(result.answer)

        # Full query
        answer = await client.ask(
            "Explain zero-trust architecture",
            model="claude-sonnet-4-20250514",
            llm_key="sk-ant-...",
        )
        print(answer.answer)

        # Parallel queries
        lookup_a, lookup_b = await asyncio.gather(
            client.lookup("What is GDPR?"),
            client.lookup("What is SOC 2?"),
        )

asyncio.run(main())`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              The async client uses <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">httpx.AsyncClient</code> under the hood and supports the same constructor parameters as the sync client.
              File ingestion reads the file and sends it as bytes in the async HTTP request.
            </p>
          </section>

          {/* 11. OpenAI Proxy */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">11</div>
              <h2 className="text-xl font-semibold">OpenAI Proxy</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Get a standard <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">openai.OpenAI</code> client that routes all traffic through BitMod for automatic caching. Drop it into existing code with zero changes.
            </p>
            <CodeBlock filename="python">
{`# Sync client returns openai.OpenAI
bm = BitmodClient(api_key="bm_...")
oai = bm.openai_client(api_key="sk-...")

# Use exactly like the standard OpenAI SDK
response = oai.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is BitMod?"}],
)
print(response.choices[0].message.content)

# Async client returns openai.AsyncOpenAI
async_bm = AsyncBitmodClient(api_key="bm_...")
async_oai = async_bm.openai_client(api_key="sk-...")

response = await async_oai.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is BitMod?"}],
)`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Requires the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">openai</code> extra. The client sets <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">base_url</code> to the BitMod proxy endpoint and passes your BitMod key via the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">X-Bitmod-Key</code> header.
            </p>
          </section>

          {/* 12. Anthropic Proxy */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">12</div>
              <h2 className="text-xl font-semibold">Anthropic Proxy</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Same pattern for Anthropic. Get a standard <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">anthropic.Anthropic</code> client routed through BitMod.
            </p>
            <CodeBlock filename="python">
{`# Sync client returns anthropic.Anthropic
bm = BitmodClient(api_key="bm_...")
claude = bm.anthropic_client(api_key="sk-ant-...")

message = claude.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain cache invalidation"}],
)
print(message.content[0].text)

# Async client returns anthropic.AsyncAnthropic
async_bm = AsyncBitmodClient(api_key="bm_...")
async_claude = async_bm.anthropic_client(api_key="sk-ant-...")

message = await async_claude.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain cache invalidation"}],
)`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Requires the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">anthropic</code> extra.
            </p>
          </section>

          {/* 13. Error Handling */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">13</div>
              <h2 className="text-xl font-semibold">Error Handling</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              The SDK raises typed exceptions for every failure mode. All exceptions extend <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BitmodError</code>.
            </p>
            <CodeBlock filename="python">
{`from bitmod_client.exceptions import (
    BitmodError,            # base — catch-all for any SDK error
    BitmodAuthError,        # 401/403 — invalid or missing API key
    BitmodNotFoundError,    # 404 — resource not found
    BitmodValidationError,  # 422 — request payload failed validation
    BitmodRateLimitError,   # 429 — too many requests
    BitmodServerError,      # 5xx — server-side failure
    BitmodConnectionError,  # cannot reach the gateway
    BitmodTimeoutError,     # request timed out
)

try:
    result = client.ask("What is caching?", model="gpt-4o")
except BitmodAuthError as e:
    print(f"Auth failed: {e} (status: {e.status_code})")
except BitmodRateLimitError as e:
    print(f"Rate limited — retry after {e.retry_after}s")
except BitmodTimeoutError:
    print("Request timed out — increase timeout or check gateway")
except BitmodConnectionError:
    print("Cannot reach BitMod — is the gateway running?")
except BitmodValidationError as e:
    print(f"Invalid request: {e} (body: {e.body})")
except BitmodServerError:
    print("Server error — try again later")
except BitmodError as e:
    print(f"Unexpected error: {e} (status: {e.status_code})")`}
            </CodeBlock>
            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <p className="text-sm font-medium mb-2">All exceptions carry these attributes</p>
                <div className="text-xs text-muted-foreground space-y-1 font-mono">
                  <p><span className="text-primary/80">message</span>: str — human-readable error description</p>
                  <p><span className="text-primary/80">status_code</span>: int | None — HTTP status code</p>
                  <p><span className="text-primary/80">body</span>: dict — raw error response body</p>
                  <p><span className="text-primary/80">retry_after</span>: float | None — seconds to wait (BitmodRateLimitError only)</p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* 14. Context Manager */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">14</div>
              <h2 className="text-xl font-semibold">Context Manager</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Both clients support context managers to automatically close the underlying connection pool when you are done.
            </p>

            <div className="space-y-4">
              <CodeBlock filename="python">
{`# Sync — automatically closes on exit
with BitmodClient(api_key="bm_...") as client:
    result = client.ask("What is BitMod?", model="gpt-4o")
    print(result.answer)
# connection pool is closed here`}
              </CodeBlock>

              <CodeBlock filename="python">
{`# Async — automatically closes on exit
async with AsyncBitmodClient(api_key="bm_...") as client:
    result = await client.ask("What is BitMod?", model="gpt-4o")
    print(result.answer)
# async connection pool is closed here`}
              </CodeBlock>
            </div>
            <p className="text-sm text-muted-foreground mt-3">
              If you are not using a context manager, call <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">client.close()</code> (or <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">await client.close()</code>) when you are finished to release resources.
            </p>
          </section>

          {/* Summary card */}
          <Card className="border-border/40 bg-card/50">
            <CardContent className="p-6">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2">
                  <Zap className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold mb-1">Full API at a glance</h3>
                  <p className="text-sm text-muted-foreground">
                    The Python SDK wraps the entire BitMod REST API: cache lookups, LLM queries with automatic caching, semantic search, document ingestion, usage analytics, and health checks.
                    The drop-in OpenAI and Anthropic proxies let you add caching to existing code with a single line change.
                    Both sync and async clients share the same method signatures.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Next Steps */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Next Steps</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Link href="/guides/getting-started" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Terminal className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Getting Started</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Install, initialize, and see savings in 5 minutes</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
              <Link href="/guides/cache-setup" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Database className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Cache Configuration</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Fine-tune TTL, layers, and confidence thresholds</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
            </div>
          </section>
        </div>
      </article>
    </div>
  )
}
