import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "BitMod — Modular AI Data Infrastructure",
  description: "Compute once, serve forever. Open-source 9-layer intelligent cache for LLM apps. Universal provider support, 4 databases, zero lock-in. Run it with docker compose up.",
}
import { Button } from "@/components/ui/button"
import { HeroWordmark } from "@/components/hero-wordmark"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { CopyButton } from "@/components/copy-button"
import { BrandTicker } from "@/components/brand-ticker"
import {
  Zap, Database, Brain, FileText, Search, Package,
  ArrowRight, Terminal, Globe, Layers, Repeat, Shield, Lock
} from "lucide-react"
import { GithubIcon } from "@/components/icons"

export default function HomePage() {
  return (
    <div className="relative">
      {/* Gradient background effect */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-1/4 top-1/4 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[100px]" />
      </div>

      {/* Hero */}
      <section className="mx-auto max-w-7xl px-4 pt-20 pb-16 sm:px-6 sm:pt-28 sm:pb-24 lg:px-8">
        <div className="text-center">
          <HeroWordmark className="mb-8" />

          <Badge variant="secondary" className="relative z-20 mb-6 px-4 py-1.5 text-sm">
            Open Source &middot; MIT
          </Badge>

          <h1 className="text-5xl font-extrabold tracking-tight sm:text-7xl lg:text-8xl">
            <span className="bg-gradient-to-r from-primary via-primary to-accent bg-clip-text text-transparent">
              Compute Once.
            </span>
            <br />
            <span className="text-foreground">Serve Forever.</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Modular AI data infrastructure with a 9-layer intelligent cache.
            Connect any LLM, any database, zero lock-in. Self-host in minutes.
          </p>

          {/* Install command */}
          <div className="mx-auto mt-8 max-w-md">
            <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-card/50 px-4 py-3 font-mono text-sm backdrop-blur-sm">
              <Terminal className="h-4 w-4 text-muted-foreground shrink-0" />
              <code className="flex-1 text-left">
                <span className="text-accent">docker compose</span>{" "}
                <span className="text-foreground font-semibold">up</span>
              </code>
              <CopyButton text="docker compose up" />
            </div>
          </div>

          {/* CTAs */}
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Button size="xl" asChild>
              <Link href="/docs">
                Get Started <ArrowRight className="ml-2 h-5 w-5" />
              </Link>
            </Button>
            <Button size="xl" variant="outline" asChild>
              <a href="https://github.com/DeepanjayNandal/bitmod" target="_blank" rel="noopener noreferrer">
                <GithubIcon className="mr-2 h-5 w-5" /> View on GitHub
              </a>
            </Button>
          </div>
        </div>
      </section>

      {/* Stats Bar */}
      <section className="border-y border-border/40 bg-card/30 backdrop-blur-sm">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-5">
            {[
              { value: "9", label: "Cache Layers", icon: Layers },
              { value: "Any", label: "LLM Provider", icon: Brain },
              { value: "4", label: "DB Backends", icon: Database },
              { value: "<1ms", label: "Cache Latency", icon: Zap },
              { value: "100%", label: "Open Source", icon: Package },
            ].map((stat) => (
              <div key={stat.label} className="text-center">
                <stat.icon className="mx-auto h-6 w-6 text-primary mb-2" />
                <div className="text-3xl font-bold text-foreground">{stat.value}</div>
                <div className="text-sm text-muted-foreground">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Problem / Solution */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="grid md:grid-cols-2 gap-12 items-center">
          <div>
            <Badge variant="outline" className="mb-4">The Problem</Badge>
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Every LLM call costs money.{" "}
              <span className="text-muted-foreground">Most are redundant.</span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Your application asks the same questions over and over. Each call burns tokens,
              adds latency, and drains your budget. There&apos;s no intelligence between your
              app and the LLM.
            </p>
          </div>
          <div>
            <Badge variant="accent" className="mb-4">The Solution</Badge>
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              An intelligent cache{" "}
              <span className="text-accent">that understands meaning.</span>
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              <strong>9-layer pipeline:</strong> Exact match, semantic similarity, composable decomposition, and fuzzy matching — all before any LLM is called.
              <br />
              <strong>Drop-in proxy:</strong> Change one line of code. Your existing SDK just works.
              <br />
              <strong>Your infrastructure:</strong> Self-host with any database. Your data stays on your servers.
            </p>
          </div>
        </div>
      </section>

      {/* Brand Ticker */}
      <BrandTicker />

      {/* Code Example */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Three steps to start saving
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Install, initialize, query. See your savings immediately.
          </p>
        </div>

        <div className="mx-auto max-w-3xl space-y-6">
          {/* Step 1 */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border/20 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <span className="text-xs text-muted-foreground ml-2 font-mono">Step 1 — Install</span>
            </div>
            <pre className="p-6 text-sm font-mono leading-relaxed overflow-x-auto">
              <code>
                <span className="text-[#a5d6ff]">pip install</span> <span className="text-[#e6edf3] font-semibold">bitmod</span>
              </code>
            </pre>
          </div>

          {/* Step 2 */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border/20 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <span className="text-xs text-muted-foreground ml-2 font-mono">Step 2 — Initialize</span>
            </div>
            <pre className="p-6 text-sm font-mono leading-relaxed overflow-x-auto">
              <code>
                <span className="text-[#a5d6ff]">bitmod init --auto</span>  <span className="text-[#8b949e] italic"># auto-detects your LLM keys</span>
              </code>
            </pre>
          </div>

          {/* Step 3 */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border/20 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <span className="text-xs text-muted-foreground ml-2 font-mono">Step 3 — Query</span>
            </div>
            <pre className="p-6 text-sm font-mono leading-relaxed overflow-x-auto">
              <code>
                <span className="text-[#ff7b72] font-semibold">from</span> <span className="text-[#79c0ff] brightness-125">bitmod</span> <span className="text-[#ff7b72] font-semibold">import</span> <span className="text-[#d2a8ff]">Bitmod</span>{"\n"}
                {"\n"}
                <span className="text-[#e6edf3]">bm</span> <span className="text-[#ff7b72]">=</span> <span className="text-[#d2a8ff]">Bitmod</span>(){"\n"}
                <span className="text-[#e6edf3]">result</span> <span className="text-[#ff7b72]">=</span> <span className="text-[#e6edf3]">bm</span>.<span className="text-[#d2a8ff]">query</span>(<span className="text-[#a5d6ff]">&quot;What is HIPAA?&quot;</span>){"\n"}
                {"\n"}
                <span className="text-[#e6edf3]">result</span>.<span className="text-[#e6edf3]">answer</span>{"         "}<span className="text-[#8b949e] italic"># answer text</span>{"\n"}
                <span className="text-[#e6edf3]">result</span>.<span className="text-[#e6edf3]">cached</span>{"         "}<span className="text-[#8b949e] italic"># True on cache hit</span>{"\n"}
                <span className="text-[#e6edf3]">result</span>.<span className="text-[#e6edf3]">cache_layer</span>{"    "}<span className="text-[#8b949e] italic"># &quot;exact_cache&quot;, &quot;semantic_cache&quot;, etc.</span>{"\n"}
                <span className="text-[#e6edf3]">result</span>.<span className="text-[#e6edf3]">token_usage</span>{"    "}<span className="text-[#8b949e] italic"># tokens_saved, estimated_savings</span>
              </code>
            </pre>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section id="features" className="mx-auto max-w-7xl px-4 pb-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Everything you need.{" "}
            <span className="text-muted-foreground">Nothing you don&apos;t.</span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Modular by design. Use what you need, swap what you want.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              icon: Zap,
              title: "9-Layer Intelligent Cache",
              description: "Exact match, semantic similarity, composable decomposition, fuzzy matching — all running before any LLM is called. Patent-pending pipeline with SHA-256 keying and source verification.",
              color: "text-yellow-500",
            },
            {
              icon: Repeat,
              title: "Drop-in LLM Proxy",
              description: "Point your OpenAI, Anthropic, or Gemini SDK at BitMod. Cache hits skip the LLM entirely. Misses pass through to your provider transparently. Change one line of code.",
              color: "text-primary",
            },
            {
              icon: Brain,
              title: "Any LLM, Any Provider",
              description: "Universal — works with any OpenAI-compatible provider. Ollama, OpenAI, Anthropic, Groq, Together, Fireworks, vLLM, and 200+ more. Just set a URL.",
              color: "text-blue-400",
            },
            {
              icon: Database,
              title: "Any Database Backend",
              description: "SQLite for development, PostgreSQL for production, MySQL or MongoDB if that's your stack. Swap backends without changing application code.",
              color: "text-cyan-500",
            },
            {
              icon: Lock,
              title: "Your Data, Your Servers",
              description: "Self-host on your infrastructure. BitMod never phones home, never stores your API keys, never sees your data. Fully air-gappable.",
              color: "text-green-500",
            },
            {
              icon: Search,
              title: "Semantic Understanding",
              description: "BitMod knows that 'What is HIPAA?' and 'Explain HIPAA to me' are the same question. Embedding-based similarity matching across your entire cache.",
              color: "text-accent",
            },
            {
              icon: FileText,
              title: "Source Verification",
              description: "Every cached answer is locked to the SHA-256 hash of its source data. When sources change, stale answers are automatically invalidated.",
              color: "text-red-400",
            },
            {
              icon: Layers,
              title: "Composable Decomposition",
              description: "Complex questions are broken into sub-queries, each answered from cache independently, then reassembled. Maximizes hit rates on novel questions.",
              color: "text-purple-500",
            },
            {
              icon: Package,
              title: "docker compose up",
              description: "Run from source or the Docker image. Admin dashboard, cache analytics, and monitoring built in. MIT licensed.",
              color: "text-pink-500",
            },
          ].map((feature) => (
            <Card key={feature.title} className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
              <CardHeader>
                <feature.icon className={`h-10 w-10 ${feature.color} mb-2`} />
                <CardTitle className="text-lg">{feature.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">
                  {feature.description}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Complementary Savings */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <Badge variant="outline" className="mb-4">Works With Your Stack</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Provider caching cuts cost per call.
            <br />
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              BitMod eliminates the call entirely.
            </span>
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Anthropic and OpenAI cache your prompt prefix &mdash; you still pay for every response.
            BitMod serves the answer from your own infrastructure in under 5ms.
            Use both for maximum savings.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-4 text-sm">
            <div className="rounded-lg border border-border/40 bg-card/50 p-4">
              <div className="font-semibold text-foreground">BitMod</div>
              <div className="text-muted-foreground mt-1">Application layer</div>
              <div className="text-primary font-bold mt-2">Eliminates calls</div>
            </div>
            <div className="rounded-lg border border-border/40 bg-card/50 p-4">
              <div className="font-semibold text-foreground">Provider Cache</div>
              <div className="text-muted-foreground mt-1">API layer</div>
              <div className="text-primary font-bold mt-2">Reduces input cost</div>
            </div>
            <div className="rounded-lg border border-border/40 bg-card/50 p-4">
              <div className="font-semibold text-foreground">KV Compression</div>
              <div className="text-muted-foreground mt-1">Inference layer</div>
              <div className="text-primary font-bold mt-2">Faster generation</div>
            </div>
          </div>
        </div>
      </section>

      {/* Architecture */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              How it works
            </h2>
            <p className="mt-3 text-lg text-muted-foreground">
              BitMod sits between your app and the LLM. Every request hits the cache first.
            </p>
          </div>

          <div className="mx-auto max-w-4xl grid gap-6 lg:grid-cols-2">
            {/* Left: Cache pipeline */}
            <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 font-mono text-sm shadow-2xl">
              <div className="text-[#8b949e] mb-4">{"# 9-layer cache pipeline:"}</div>
              <div className="space-y-2">
                <div><span className="text-[#79c0ff]">1.</span> <span className="text-[#7ee787]">normalization</span> <span className="text-[#8b949e]">{"# lowercase, strip stopwords"}</span></div>
                <div><span className="text-[#79c0ff]">2.</span> <span className="text-[#7ee787]">exact_cache</span> <span className="text-[#8b949e]">{"# SHA-256 composite key lookup"}</span></div>
                <div><span className="text-[#79c0ff]">3.</span> <span className="text-[#7ee787]">double_verify</span> <span className="text-[#8b949e]">{"# source version validation"}</span></div>
                <div><span className="text-[#79c0ff]">4.</span> <span className="text-[#ffa657]">ttl_check</span> <span className="text-[#8b949e]">{"# max_age_seconds expiry"}</span></div>
                <div><span className="text-[#79c0ff]">5.</span> <span className="text-[#ffa657]">fuzzy_match</span> <span className="text-[#8b949e]">{"# order-independent tokens"}</span></div>
                <div><span className="text-[#79c0ff]">6.</span> <span className="text-[#ffa657]">semantic_cache</span> <span className="text-[#8b949e]">{"# embedding similarity"}</span></div>
                <div><span className="text-[#79c0ff]">7.</span> <span className="text-[#d2a8ff]">composable</span> <span className="text-[#8b949e]">{"# decompose & reassemble"}</span></div>
                <div><span className="text-[#79c0ff]">8.</span> <span className="text-[#d2a8ff]">temporal</span> <span className="text-[#8b949e]">{"# permanent historical queries"}</span></div>
                <div><span className="text-[#79c0ff]">9.</span> <span className="text-[#ff7b72]">lru_eviction</span> <span className="text-[#8b949e]">{"# evict least-recently-used"}</span></div>
              </div>
            </div>
            {/* Right: Multi-format proxy */}
            <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 font-mono text-sm shadow-2xl">
              <div className="text-[#8b949e] mb-4">{"# Drop-in proxy — any SDK format:"}</div>
              <div className="space-y-3">
                <div>
                  <div className="text-[#8b949e] text-xs mb-1">OpenAI format</div>
                  <div><span className="text-[#d2a8ff]">POST</span> <span className="text-[#a5d6ff]">/v1/chat/completions</span></div>
                </div>
                <div>
                  <div className="text-[#8b949e] text-xs mb-1">Anthropic format</div>
                  <div><span className="text-[#d2a8ff]">POST</span> <span className="text-[#a5d6ff]">/v1/messages</span></div>
                </div>
                <div>
                  <div className="text-[#8b949e] text-xs mb-1">Gemini format</div>
                  <div><span className="text-[#d2a8ff]">POST</span> <span className="text-[#a5d6ff]">{"/v1beta/models/{model}:generateContent"}</span></div>
                </div>
                <div>
                  <div className="text-[#8b949e] text-xs mb-1">Ollama format</div>
                  <div><span className="text-[#d2a8ff]">POST</span> <span className="text-[#a5d6ff]">/api/chat</span></div>
                </div>
                <div className="pt-2">
                  <div className="text-[#8b949e] text-xs mb-1">Cache headers on every response</div>
                  <div className="text-[#7ee787]">X-Bitmod-Cache-Hit: true</div>
                  <div className="text-[#7ee787]">X-Bitmod-Cache-Layer: semantic</div>
                  <div className="text-[#7ee787]">X-Bitmod-Serve-Count: 47</div>
                  <div className="text-[#7ee787]">X-Bitmod-Saved: $0.03</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          See it in action
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Explore the docs to understand the full pipeline, or jump straight into the playground and watch the cache work in real time.
        </p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button size="xl" asChild>
            <Link href="/docs">
              Read the Docs <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
          <Button size="xl" variant="outline" asChild>
            <Link href="/playground">
              Try the Playground
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
