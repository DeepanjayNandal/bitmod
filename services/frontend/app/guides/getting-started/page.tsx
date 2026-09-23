import type { Metadata } from "next"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { CodeBlock } from "@/components/shared/code-block"
import { ArrowRight, Clock, Terminal, Zap, Database } from "lucide-react"

export const metadata: Metadata = {
  title: "Getting Started with BitMod | Guides",
  description: "Install BitMod, run your first query, and see cache savings in under 5 minutes.",
}

export default function GettingStartedGuide() {
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
              <span>5 min read</span>
            </div>
            <Badge className="bg-green-500/15 text-green-400 border-green-500/30">Beginner</Badge>
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            Getting Started with BitMod
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Install BitMod, send your first query through the cache engine, and see your cost savings — all in under 5 minutes.
          </p>
        </div>

        <div className="space-y-12">
          {/* Step 1: Install */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">1</div>
              <h2 className="text-xl font-semibold">Install BitMod</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Clone the repository and start it with Docker Compose:
            </p>
            <CodeBlock filename="terminal">
{`git clone https://github.com/DeepanjayNandal/bitmod.git
cd bitmod
cp .env.example .env
docker compose up`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Requires Docker, or Python 3.10 or newer to run from source with <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">pip install -e .</code>.
            </p>
          </section>

          {/* Step 2: Initialize */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">2</div>
              <h2 className="text-xl font-semibold">Initialize Your Project</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Run <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod init</code> to generate a configuration file and set up your local cache database:
            </p>
            <CodeBlock filename="terminal">
{`bitmod init

# Output:
# Created bitmod.yaml
# Initialized SQLite cache at ~/.bitmod/bitmod.db
# Ready — run 'bitmod serve' to start the proxy`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              This creates a <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod.yaml</code> in your current directory with sensible defaults.
              You can also set your provider API key now:
            </p>
            <CodeBlock filename="terminal">
{`export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."`}
            </CodeBlock>
          </section>

          {/* Step 3: Start the proxy */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">3</div>
              <h2 className="text-xl font-semibold">Start the Proxy</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Start the BitMod gateway. It acts as a drop-in proxy for any OpenAI-compatible client:
            </p>
            <CodeBlock filename="terminal">
{`bitmod serve

# BitMod API server running at http://localhost:8000
# Cache engine: 9 layers active`}
            </CodeBlock>
          </section>

          {/* Step 4: Send a query */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">4</div>
              <h2 className="text-xl font-semibold">Send Your First Query</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Use the core library locally, the remote SDK, or just point any OpenAI-compatible client at BitMod:
            </p>

            <div className="space-y-4">
              <p className="text-sm text-muted-foreground font-medium">Core library (local, no server needed):</p>
              <CodeBlock filename="python">
{`from bitmod import Bitmod

bm = Bitmod()

result = bm.query("What is semantic caching?")
print(result.answer)
print(f"Cached: {result.cached}")       # False on first call
print(f"Latency: {result.generation_ms}ms")
print(f"Cache layer: {result.cache_layer}")`}
              </CodeBlock>

              <p className="text-sm text-muted-foreground font-medium">Remote SDK (connects to a running server):</p>
              <CodeBlock filename="python">
{`from bitmod_client import BitmodClient

client = BitmodClient(base_url="http://localhost:8000", api_key="bm_...")

result = client.ask("What is semantic caching?")
print(result.answer)
print(f"Cached: {result.cached}")       # False on first call
print(f"Latency: {result.latency_ms}ms")
print(f"Cost saved: {result.cost_saved}")`}
              </CodeBlock>

              <p className="text-sm text-muted-foreground">Or with curl:</p>

              <CodeBlock filename="terminal">
{`curl -X POST http://localhost:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "What is semantic caching?"}
    ]
  }'`}
              </CodeBlock>
            </div>
          </section>

          {/* Step 5: See the savings */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">5</div>
              <h2 className="text-xl font-semibold">See Your Cache Savings</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Send the same query again. This time it hits the cache — zero tokens consumed, and because this runs in-process rather than over HTTP, a sub-millisecond lookup:
            </p>
            <CodeBlock filename="python">
{`result = bm.query("What is semantic caching?")
print(f"Cached: {result.cached}")              # True
print(f"Generation: {result.generation_ms}ms") # 0 on a hit: nothing was generated
print(f"Tokens saved: {result.token_usage['tokens_saved']}")`}
            </CodeBlock>

            <p className="text-muted-foreground mt-4 mb-4">
              Check your cumulative savings at any time:
            </p>
            <CodeBlock filename="terminal">
{`curl http://localhost:8000/v1/usage

# {
#   "total_queries": 47,
#   "cache_hits": 31,
#   "hit_rate_pct": "65.9%",
#   "tokens_saved": 24850,
#   "estimated_cost_saved": "$0.0372"
# }`}
            </CodeBlock>
          </section>

          {/* Summary card */}
          <Card className="border-border/40 bg-card/50">
            <CardContent className="p-6">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2">
                  <Zap className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold mb-1">What just happened?</h3>
                  <p className="text-sm text-muted-foreground">
                    BitMod ran your query through a 9-layer intelligent cache pipeline. The first call hit your LLM provider and stored the result.
                    The second call was byte-identical, so it matched on the exact-match layer and returned in 0.2ms in-process — saving you tokens and money. A semantic match costs more, 42ms in-process, because the query has to be embedded first.
                    As your usage grows, the savings compound.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Next Steps */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Next Steps</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Link href="/guides/cache-setup" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Database className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Setting Up Your First Cache</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Configure TTL, layers, and monitoring</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
              <Link href="/guides/llm-providers" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Terminal className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Connecting Your LLM Provider</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Anthropic, OpenAI, Ollama, and more</p>
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
