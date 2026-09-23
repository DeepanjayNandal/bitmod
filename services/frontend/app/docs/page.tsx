import type { Metadata } from "next"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export const metadata: Metadata = {
  title: "Documentation | BitMod",
  description: "Complete guide to BitMod: installation, configuration, API reference, cache engine internals, provider adapters, and database backends.",
}
import { Separator } from "@/components/ui/separator"
import {
  Terminal, Database, Brain, Search, FileText, Zap,
  Server, Cloud, Globe, Cpu, HardDrive, Repeat, CheckCircle, Play, Lock, ListChecks
} from "lucide-react"
import { CodeBlock } from "@/components/shared/code-block"
import { DocsSidebar } from "@/components/shared/docs-sidebar"

const docsSidebarSections = [
  {
    title: "On this page",
    links: [
      { href: "#architecture", label: "Architecture" },
      { href: "#quickstart", label: "Quick Start" },
      { href: "#proxy", label: "SDK Proxy" },
      { href: "#api", label: "API Reference" },
      { href: "#cli", label: "CLI Reference" },
      { href: "#auth", label: "Authentication" },
      { href: "#configuration", label: "Configuration" },
      { href: "#llm-providers", label: "LLM Providers" },
      { href: "#databases", label: "Database Backends" },
      { href: "#embeddings", label: "Embedding Providers" },
      { href: "#vector-stores", label: "Vector Stores" },
      { href: "#ingestion", label: "Document Ingestion" },
      { href: "#cache-engine", label: "Cache Engine" },
      { href: "#docker", label: "Docker Deployment" },
      { href: "#integrations", label: "Integrations" },
    ],
  },
  {
    title: "Guides",
    links: [
      { href: "/guides/api-reference", label: "Full API Reference" },
      { href: "/guides/python-sdk", label: "Python SDK" },
      { href: "/guides/docker", label: "Docker Deployment" },
      { href: "/guides/operations", label: "Operations" },
      { href: "/guides/troubleshooting", label: "Troubleshooting" },
    ],
  },
]

function SectionHeader({ id, title, description }: { id: string; title: string; description: string }) {
  return (
    <div id={id} className="scroll-mt-20 mb-8">
      <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h2>
      <p className="mt-2 text-muted-foreground">{description}</p>
    </div>
  )
}

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-12 lg:max-w-4xl">
        <Badge variant="accent" className="mb-4">Documentation</Badge>
        <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
          BitMod Docs
        </h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Everything you need to build with BitMod.
        </p>
      </div>

      <div className="lg:grid lg:grid-cols-[220px_1fr] lg:gap-10">
        {/* Left sidebar */}
        <DocsSidebar sections={docsSidebarSections} />

        {/* Main content */}
        <div className="max-w-4xl space-y-20">
        {/* Architecture */}
        <section>
          <SectionHeader
            id="architecture"
            title="Architecture"
            description="Two pipelines, one engine. The Answer Loop caches Q&A responses locally using the 9-layer intelligent pipeline. The Agent Loop caches entire action plans for deterministic replay."
          />

          {/* Chat Pipeline Label */}
          <div className="mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Brain className="h-5 w-5 text-primary" />
              Answer Loop (Chat Pipeline)
            </h3>
            <p className="text-xs text-muted-foreground mt-1">Ask a question, get a cached or generated answer with source citations.</p>
          </div>

          {/* Main flow diagram */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 overflow-hidden shadow-2xl mb-8">
            {/* Top: Query enters */}
            <div className="text-center mb-6">
              <div className="inline-flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/20 px-5 py-2.5 text-primary font-semibold arch-node">
                <Zap className="h-4 w-4" />
                Your App / SDK / cURL
              </div>
              <div className="mt-3 flex justify-center">
                <div className="w-px h-8 bg-gradient-to-b from-primary/60 to-primary/20 animate-flow-pulse" />
              </div>
            </div>

            {/* Format detection */}
            <div className="text-center mb-6">
              <div className="inline-flex flex-col sm:flex-row items-center gap-2 sm:gap-4">
                <div className="rounded-lg bg-muted/30 border border-border/30 px-3 py-1.5 text-xs font-mono text-[#79c0ff] arch-node">
                  /v1/chat/completions
                  <span className="block text-[10px] text-muted-foreground mt-0.5">OpenAI format</span>
                </div>
                <div className="rounded-lg bg-muted/30 border border-border/30 px-3 py-1.5 text-xs font-mono text-[#d2a8ff] arch-node">
                  /v1/messages
                  <span className="block text-[10px] text-muted-foreground mt-0.5">Anthropic format</span>
                </div>
                <div className="rounded-lg bg-muted/30 border border-border/30 px-3 py-1.5 text-xs font-mono text-[#ffa657] arch-node">
                  /v1beta/generateContent
                  <span className="block text-[10px] text-muted-foreground mt-0.5">Gemini format</span>
                </div>
              </div>
              <div className="mt-3 flex justify-center">
                <div className="w-px h-8 bg-gradient-to-b from-muted-foreground/40 to-primary/30 animate-flow-pulse" style={{ animationDelay: "0.3s" }} />
              </div>
            </div>

            {/* BitMod Proxy — the core */}
            <div className="relative rounded-xl border-2 border-primary/30 bg-primary/5 p-6 mb-6">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#0d1117] px-3">
                <span className="text-xs font-semibold text-primary uppercase tracking-wider">BitMod Proxy</span>
              </div>

              {/* Cache pipeline */}
              <div className="grid grid-cols-3 sm:grid-cols-9 gap-1.5 mb-6">
                {[
                  { num: "1", label: "Normalization", color: "text-[#79c0ff]" },
                  { num: "2", label: "Exact Cache", color: "text-[#79c0ff]" },
                  { num: "3", label: "Double Verify", color: "text-[#7ee787]" },
                  { num: "4", label: "TTL Check", color: "text-[#7ee787]" },
                  { num: "5", label: "Fuzzy Match", color: "text-[#7ee787]" },
                  { num: "6", label: "Semantic Cache", color: "text-[#ffa657]" },
                  { num: "7", label: "Composable", color: "text-[#d2a8ff]" },
                  { num: "8", label: "Temporal", color: "text-[#d2a8ff]" },
                  { num: "9", label: "LRU Eviction", color: "text-[#ff7b72]" },
                ].map((layer, i) => (
                  <div
                    key={layer.num}
                    className="rounded-md bg-muted/20 border border-border/20 p-1.5 text-center arch-node"
                    style={{ animationDelay: `${i * 0.1}s` }}
                  >
                    <div className={`text-[10px] font-bold ${layer.color}`}>{layer.num}</div>
                    <div className="text-[8px] sm:text-[9px] text-muted-foreground leading-tight mt-0.5">{layer.label}</div>
                  </div>
                ))}
              </div>

              {/* Decision split */}
              <div className="flex items-center justify-center gap-6 sm:gap-12">
                {/* Cache HIT */}
                <div className="text-center flex-1">
                  <div className="rounded-lg bg-green-500/10 border border-green-500/20 px-4 py-3 arch-node">
                    <div className="text-green-400 font-bold text-sm">CACHE HIT</div>
                    <div className="text-[10px] text-green-400/70 mt-1">68-82ms &middot; verified &middot; cited</div>
                  </div>
                  <div className="mt-2 text-[10px] text-muted-foreground">
                    Returns in native SDK format
                  </div>
                </div>

                <div className="text-muted-foreground text-xs font-mono shrink-0">or</div>

                {/* Cache MISS */}
                <div className="text-center flex-1">
                  <div className="rounded-lg bg-accent/10 border border-accent/20 px-4 py-3 arch-node">
                    <div className="text-accent font-bold text-sm">CACHE MISS</div>
                    <div className="text-[10px] text-accent/70 mt-1">Forward to LLM &darr;</div>
                  </div>
                </div>
              </div>
            </div>

            {/* On miss: route to LLM */}
            <div className="flex justify-end mr-[20%] mb-3">
              <div className="w-px h-6 bg-gradient-to-b from-accent/40 to-accent/20 animate-flow-pulse" style={{ animationDelay: "0.6s" }} />
            </div>

            {/* LLM + DB + Embedder row */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
              <div className="rounded-lg bg-[#161b22] border border-border/30 p-4 text-center arch-node">
                <Brain className="h-6 w-6 text-primary mx-auto mb-2" />
                <div className="text-sm font-semibold text-[#e6edf3]">LLM Router</div>
                <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                  <div>Anthropic &middot; OpenAI &middot; Gemini</div>
                  <div>Ollama &middot; xAI &middot; Mistral</div>
                  <div>Bedrock &middot; Azure &middot; Perplexity</div>
                  <div>OpenRouter &middot; HuggingFace &middot; Universal</div>
                </div>
                <div className="mt-2 text-[9px] text-primary/60">Auto-detects provider from model name</div>
              </div>

              <div className="rounded-lg bg-[#161b22] border border-border/30 p-4 text-center arch-node">
                <Search className="h-6 w-6 text-accent mx-auto mb-2" />
                <div className="text-sm font-semibold text-[#e6edf3]">Embedder</div>
                <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                  <div>Ollama (nomic-embed-text)</div>
                  <div>Local (all-MiniLM-L6-v2)</div>
                  <div>OpenAI &middot; Cohere</div>
                </div>
                <div className="mt-2 text-[9px] text-accent/60">Semantic search + cache matching</div>
              </div>

              <div className="rounded-lg bg-[#161b22] border border-border/30 p-4 text-center arch-node">
                <Database className="h-6 w-6 text-green-400 mx-auto mb-2" />
                <div className="text-sm font-semibold text-[#e6edf3]">Database</div>
                <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                  <div>SQLite (zero-config default)</div>
                  <div>PostgreSQL + pgvector</div>
                  <div>MySQL &middot; MongoDB</div>
                </div>
                <div className="mt-2 text-[9px] text-green-400/60">Cache, documents, embeddings, keys</div>
              </div>
            </div>

            {/* Response cached + returned */}
            <div className="flex justify-end mr-[20%] mb-3">
              <div className="w-px h-6 bg-gradient-to-b from-green-400/40 to-green-400/20 animate-flow-pulse" style={{ animationDelay: "0.9s" }} />
            </div>
            <div className="text-center">
              <div className="inline-flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-5 py-2.5 text-green-400 font-semibold text-sm arch-node">
                <Zap className="h-4 w-4" />
                Response cached + returned in native format
              </div>
              <p className="text-[10px] text-muted-foreground mt-2">
                Next identical query is served from cache in 68-82ms over HTTP
              </p>
            </div>
          </div>

          {/* Agent Pipeline Label */}
          <div className="mb-4 mt-12">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <ListChecks className="h-5 w-5 text-accent" />
              Agent Loop (Action Plan Pipeline)
            </h3>
            <p className="text-xs text-muted-foreground mt-1">Execute multi-step tasks. LLM reasons once, plan is cached with HMAC integrity for deterministic replay.</p>
          </div>

          {/* Agent flow diagram */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 overflow-hidden shadow-2xl mb-8">
            {/* Top: Task request */}
            <div className="text-center mb-6">
              <div className="inline-flex items-center gap-2 rounded-lg bg-accent/10 border border-accent/20 px-5 py-2.5 text-accent font-semibold arch-node">
                <Play className="h-4 w-4" />
                Agent Task Request
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground font-mono">&ldquo;Summarize all Q3 reports and email the team&rdquo;</div>
              <div className="mt-3 flex justify-center">
                <div className="w-px h-8 bg-gradient-to-b from-accent/60 to-accent/20 animate-flow-pulse" />
              </div>
            </div>

            {/* Plan cache check */}
            <div className="relative rounded-xl border-2 border-accent/30 bg-accent/5 p-6 mb-6">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#0d1117] px-3">
                <span className="text-xs font-semibold text-accent uppercase tracking-wider">Action Plan Cache</span>
              </div>

              {/* Cache pipeline for plans */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-6">
                {[
                  { num: "1", label: "Normalize Task", color: "text-[#79c0ff]" },
                  { num: "2", label: "Plan Lookup", color: "text-[#7ee787]" },
                  { num: "3", label: "HMAC Verify", color: "text-[#d2a8ff]" },
                  { num: "4", label: "Param Inject", color: "text-[#ffa657]" },
                ].map((layer, i) => (
                  <div
                    key={layer.num}
                    className="rounded-md bg-muted/20 border border-border/20 p-2 text-center arch-node"
                    style={{ animationDelay: `${i * 0.1}s` }}
                  >
                    <div className={`text-xs font-bold ${layer.color}`}>{layer.num}</div>
                    <div className="text-[9px] text-muted-foreground leading-tight mt-0.5">{layer.label}</div>
                  </div>
                ))}
              </div>

              {/* Decision split */}
              <div className="flex items-center justify-center gap-6 sm:gap-12">
                {/* Plan HIT */}
                <div className="text-center flex-1">
                  <div className="rounded-lg bg-green-500/10 border border-green-500/20 px-4 py-3 arch-node">
                    <div className="text-green-400 font-bold text-sm">PLAN HIT</div>
                    <div className="text-[10px] text-green-400/70 mt-1">HMAC valid &middot; replay steps</div>
                  </div>
                  <div className="mt-2 text-[10px] text-muted-foreground">
                    Deterministic execution, no LLM call
                  </div>
                </div>

                <div className="text-muted-foreground text-xs font-mono shrink-0">or</div>

                {/* Plan MISS */}
                <div className="text-center flex-1">
                  <div className="rounded-lg bg-accent/10 border border-accent/20 px-4 py-3 arch-node">
                    <div className="text-accent font-bold text-sm">PLAN MISS</div>
                    <div className="text-[10px] text-accent/70 mt-1">LLM generates plan &darr;</div>
                  </div>
                </div>
              </div>
            </div>

            {/* On miss: LLM generates action plan */}
            <div className="flex justify-end mr-[20%] mb-3">
              <div className="w-px h-6 bg-gradient-to-b from-accent/40 to-accent/20 animate-flow-pulse" style={{ animationDelay: "0.4s" }} />
            </div>

            {/* Plan generation + execution */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
              <div className="rounded-lg bg-[#161b22] border border-border/30 p-4 text-center arch-node">
                <Brain className="h-6 w-6 text-primary mx-auto mb-2" />
                <div className="text-sm font-semibold text-[#e6edf3]">LLM Reasoning</div>
                <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                  <div>Analyzes task &amp; context</div>
                  <div>Generates step-by-step plan</div>
                  <div>Assigns tools per step</div>
                </div>
              </div>

              <div className="rounded-lg bg-[#161b22] border border-border/30 p-4 text-center arch-node">
                <Lock className="h-6 w-6 text-[#d2a8ff] mx-auto mb-2" />
                <div className="text-sm font-semibold text-[#e6edf3]">HMAC Signing</div>
                <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                  <div>Plan steps cryptographically signed</div>
                  <div>Tamper-proof integrity</div>
                  <div>Versioned for invalidation</div>
                </div>
              </div>

              <div className="rounded-lg bg-[#161b22] border border-border/30 p-4 text-center arch-node">
                <CheckCircle className="h-6 w-6 text-green-400 mx-auto mb-2" />
                <div className="text-sm font-semibold text-[#e6edf3]">Execute &amp; Cache</div>
                <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                  <div>Run each step deterministically</div>
                  <div>Cache plan for future replay</div>
                  <div>Parameter slots for re-use</div>
                </div>
              </div>
            </div>

            {/* Replay flow */}
            <div className="flex justify-center mb-3">
              <div className="w-px h-6 bg-gradient-to-b from-green-400/40 to-green-400/20 animate-flow-pulse" style={{ animationDelay: "0.7s" }} />
            </div>
            <div className="text-center">
              <div className="inline-flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-5 py-2.5 text-green-400 font-semibold text-sm arch-node">
                <Repeat className="h-4 w-4" />
                Similar tasks replay cached plan instantly
              </div>
              <p className="text-[10px] text-muted-foreground mt-2">
                &ldquo;Summarize Q4 reports and email the team&rdquo; reuses the same plan with injected parameters
              </p>
            </div>
          </div>

          {/* Block compression diagram */}
          <div className="grid gap-6 sm:grid-cols-2 mb-8">
            <Card className="border-border/40 bg-card/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Block-Level Compression</CardTitle>
                <CardDescription className="text-xs">Every document section is stored at 3 compression levels simultaneously</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {[
                  { level: "Full", tokens: "~500 tokens", desc: "Complete text with all detail", color: "bg-primary/10 text-primary border-primary/20" },
                  { level: "Structured", tokens: "~80 tokens", desc: "Extracted entities, dates, amounts as JSON", color: "bg-accent/10 text-accent border-accent/20" },
                  { level: "Headline", tokens: "~15 tokens", desc: "Title or first sentence for quick scanning", color: "bg-green-500/10 text-green-400 border-green-500/20" },
                ].map((block) => (
                  <div key={block.level} className={`rounded-lg border px-4 py-2.5 ${block.color}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold">{block.level}</span>
                      <span className="text-[10px] font-mono opacity-70">{block.tokens}</span>
                    </div>
                    <p className="text-[11px] opacity-70 mt-0.5">{block.desc}</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-border/40 bg-card/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Cascade Invalidation</CardTitle>
                <CardDescription className="text-xs">When source data changes, dependent answers automatically invalidate</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {[
                    { step: "1", label: "Source document re-ingested", icon: "text-primary" },
                    { step: "2", label: "Content hash compared to stored version", icon: "text-primary" },
                    { step: "3", label: "Changed sections detected", icon: "text-accent" },
                    { step: "4", label: "All cached answers referencing those sections invalidated", icon: "text-accent" },
                    { step: "5", label: "Next query triggers fresh LLM generation", icon: "text-green-400" },
                    { step: "6", label: "New answer cached with updated source versions", icon: "text-green-400" },
                  ].map((s) => (
                    <div key={s.step} className="flex items-center gap-3">
                      <div className={`h-6 w-6 rounded-full bg-muted/30 flex items-center justify-center text-[10px] font-bold ${s.icon}`}>
                        {s.step}
                      </div>
                      <span className="text-xs text-muted-foreground">{s.label}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Services architecture */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Service Architecture</CardTitle>
              <CardDescription className="text-xs">Three services, one shared core library. Deploy with Docker or pip install.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-3 mb-4">
                {[
                  {
                    name: "Gateway",
                    port: ":8000",
                    desc: "API gateway — rate limiting, CORS, auth, ingest endpoints, admin metrics, proxy endpoints",
                    color: "border-primary/30 bg-primary/5",
                    textColor: "text-primary",
                  },
                  {
                    name: "Chat",
                    port: ":8001",
                    desc: "Chat service — SSE streaming, tool calling, 9-layer cache pipeline, source citations",
                    color: "border-accent/30 bg-accent/5",
                    textColor: "text-accent",
                  },
                  {
                    name: "Frontend",
                    port: ":3000",
                    desc: "Next.js dashboard — admin metrics, playground, docs, interactive API explorer",
                    color: "border-green-500/30 bg-green-500/5",
                    textColor: "text-green-400",
                  },
                ].map((svc) => (
                  <div key={svc.name} className={`rounded-lg border p-3 ${svc.color} arch-node`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-sm font-semibold ${svc.textColor}`}>{svc.name}</span>
                      <span className="text-[10px] font-mono text-muted-foreground">{svc.port}</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground leading-relaxed">{svc.desc}</p>
                  </div>
                ))}
              </div>
              <div className="rounded-lg border border-border/30 bg-muted/10 p-3 text-center">
                <span className="text-xs font-semibold text-muted-foreground">Core Library</span>
                <span className="text-[10px] text-muted-foreground ml-2 font-mono">pip install -e .</span>
                <div className="mt-2 flex flex-wrap justify-center gap-1.5">
                  {["cache_engine", "proxy", "router", "blocks", "intent", "roles", "tags", "auth", "tool_layer", "ingestion", "adapters"].map((mod) => (
                    <span key={mod} className="rounded-md bg-muted/30 border border-border/20 px-2 py-0.5 text-[9px] font-mono text-muted-foreground">
                      {mod}
                    </span>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <Separator />

        {/* Quick Start */}
        <section>
          <SectionHeader
            id="quickstart"
            title="Quick Start"
            description="Get up and running in under a minute."
          />

          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold mb-3">1. Install</h3>
              <CodeBlock filename="terminal">{`# Docker — the documented path
git clone https://github.com/DeepanjayNandal/bitmod.git
cd bitmod && cp .env.example .env
docker compose up

# Or from source
pip install -e .`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">2. Initialize</h3>
              <CodeBlock filename="quickstart.py">{`from bitmod import Bitmod

bm = Bitmod()

# Query with caching — 9-layer pipeline handles everything
result = bm.query("What is the refund policy?")
print(result.answer)       # answer text
print(result.cached)       # True if served from cache
print(result.cache_layer)  # "exact_cache", "semantic_cache", etc.
print(result.token_usage)  # {"tokens_saved": ..., "estimated_savings": ...}`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">3. Configure (optional)</h3>
              <CodeBlock filename=".env">{`# Switch providers with env vars — no code changes needed
BITMOD_DB_BACKEND=postgresql
DATABASE_URL=postgresql://user:pass@db.bitmod.io:5432/bitmod

BITMOD_LLM_PROVIDER=anthropic
BITMOD_LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...

BITMOD_EMBEDDING_PROVIDER=local
BITMOD_CACHE_SEMANTIC_THRESHOLD=0.88`}</CodeBlock>
            </div>
          </div>
        </section>

        <Separator />

        {/* SDK Proxy */}
        <section>
          <SectionHeader
            id="proxy"
            title="SDK Proxy — One-Line Integration"
            description="Point your existing OpenAI, Anthropic, Gemini, or Ollama SDK at BitMod. Change one line, get intelligent caching for free."
          />

          <Tabs defaultValue="openai-proxy" className="w-full">
            <TabsList className="grid w-full grid-cols-4 h-auto">
              <TabsTrigger value="openai-proxy" className="text-xs">OpenAI</TabsTrigger>
              <TabsTrigger value="anthropic-proxy" className="text-xs">Anthropic</TabsTrigger>
              <TabsTrigger value="gemini-proxy" className="text-xs">Gemini</TabsTrigger>
              <TabsTrigger value="ollama-proxy" className="text-xs">Ollama</TabsTrigger>
            </TabsList>

            <TabsContent value="openai-proxy" className="mt-4">
              <CodeBlock filename="your_app.py">{`from openai import OpenAI

# Before (direct to OpenAI):
# client = OpenAI()

# After (through BitMod — one line change):
client = OpenAI(base_url="https://api.bitmod.io/v1", api_key="your-key")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain quantum computing"}],
)
# First call: generates + caches (~2s)
# Second identical call: served from cache (~3ms)`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">
                Works with: OpenAI, Azure OpenAI, xAI/Grok, Mistral, Perplexity, OpenRouter, Groq, Together, vLLM, LM Studio — any OpenAI-compatible client.
              </p>
            </TabsContent>

            <TabsContent value="anthropic-proxy" className="mt-4">
              <CodeBlock filename="your_app.py">{`from anthropic import Anthropic

# Before:
# client = Anthropic()

# After:
client = Anthropic(base_url="https://api.bitmod.io", api_key="your-key")

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain quantum computing"}],
)
# Streaming works too:
with client.messages.stream(...) as stream:
    for text in stream.text_stream:
        print(text, end="")`}</CodeBlock>
            </TabsContent>

            <TabsContent value="gemini-proxy" className="mt-4">
              <CodeBlock filename="your_app.py">{`import google.generativeai as genai

genai.configure(
    api_key="your-key",
    transport="rest",
    client_options={"api_endpoint": "https://api.bitmod.io"},
)

model = genai.GenerativeModel("gemini-2.0-flash")
response = model.generate_content("Explain quantum computing")
print(response.text)`}</CodeBlock>
            </TabsContent>

            <TabsContent value="ollama-proxy" className="mt-4">
              <CodeBlock filename="your_app.py">{`import ollama

# Before:
# client = ollama.Client()

# After:
client = ollama.Client(host="https://api.bitmod.io")

response = client.chat(
    model="llama3.2",
    messages=[{"role": "user", "content": "Explain quantum computing"}],
)
# Also works with LM Studio and OpenClaw`}</CodeBlock>
            </TabsContent>
          </Tabs>

          <div className="mt-6 rounded-xl border border-primary/20 bg-primary/5 p-6">
            <h4 className="font-semibold text-sm mb-2">How it works</h4>
            <ol className="text-sm text-muted-foreground space-y-1.5 list-decimal list-inside">
              <li>BitMod receives your SDK request in its native format (OpenAI, Anthropic, Gemini, or Ollama)</li>
              <li>Extracts the user message and runs the 9-layer cache pipeline</li>
              <li>On cache hit: returns the cached answer in the same format your SDK expects (68-82ms measured over HTTP, exact match)</li>
              <li>On cache miss: forwards to the real LLM provider, caches the response, returns it</li>
              <li>Your API key is passed through to the upstream provider — BitMod never stores it</li>
            </ol>
          </div>
        </section>

        <Separator />

        {/* API Reference */}
        <section>
          <SectionHeader
            id="api"
            title="API Reference"
            description="Full REST API for ingestion, querying, search, cache management, and administration."
          />

          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold mb-3">Chat</h3>
              <CodeBlock filename="POST /v1/chat">{`# Request
{
  "message": "What are the key findings in the Q3 report?",
  "history": [
    {"role": "user", "content": "Show me revenue data"},
    {"role": "assistant", "content": "Revenue was $4.2M..."}
  ],
  "filters": {"jurisdiction": "US", "document_type": "financial"},
  "stream": true
}

# Response (non-streaming)
{
  "answer": "The key findings include...",
  "cached": true,
  "cache_key": "sha256_abc123...",
  "sources": [{"section_id": "doc_1:sec_3", "citation": "Q3 Report p.12", "score": 0.94}],
  "model_used": "claude-sonnet-4-20250514",
  "generation_ms": 0,
  "pipeline_trace": [{"mechanism": "exact_cache", "action": "HIT", "elapsed_ms": 0.3}]
}`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">Search</h3>
              <CodeBlock filename="POST /v1/search">{`# Request
{"query": "revenue growth trends", "limit": 10, "jurisdiction": "US"}

# Response
{
  "results": [
    {"section_id": "...", "citation": "Q3 Report", "title": "Revenue Analysis", "snippet": "...", "score": 0.92}
  ],
  "total": 5,
  "query": "revenue growth trends"
}`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">Ingest</h3>
              <CodeBlock filename="POST /v1/ingest/text">{`# Text ingestion
{"text": "Your content...", "title": "My Document", "document_type": "legal", "source": "api",
 "jurisdiction": "EU", "tags": ["gdpr", "privacy"], "chunk_size": 500, "chunk_overlap": 50}

# File upload
curl -X POST https://api.bitmod.io/v1/ingest/file \\
  -F "file=@report.pdf" -F "title=Q3 Report" -F "document_type=financial"

# Response
{"document_id": "uuid", "title": "Q3 Report", "source_format": "PDF",
 "sections": 24, "chunks": 87, "embedded": true}`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">Administration</h3>
              <CodeBlock filename="endpoints">{`GET  /health                  # Service health check
GET  /v1/ingest/status         # Document ingestion statistics
GET  /v1/cache/stats           # Cache performance metrics
GET  /v1/admin/metrics         # Full dashboard data (cache + docs + providers)
GET  /v1/models                # Available models (OpenAI format)
GET  /metrics                  # Prometheus exposition format
POST /v1/reload                # Hot-reload intent + role YAML configs`}</CodeBlock>
            </div>
          </div>
        </section>

        <Separator />

        {/* CLI Reference */}
        <section>
          <SectionHeader
            id="cli"
            title="CLI Reference"
            description="The bitmod command-line tool for setup, ingestion, querying, and server management."
          />

          <div className="space-y-6">
            <CodeBlock filename="terminal">{`# Interactive setup wizard — creates bitmod.yaml + .env
bitmod init

# Ingest documents (PDF, DOCX, HTML, Markdown, CSV, JSON, TXT)
bitmod ingest report.pdf
bitmod ingest ./documents/                    # Recursive directory
bitmod ingest data.csv -t "Sales Data" --document-type financial

# Query with caching
bitmod query "What is the refund policy?"
bitmod query "GDPR requirements" -j EU        # Filter by jurisdiction

# Start API server
bitmod serve                                  # Default: 127.0.0.1:8000
bitmod serve -p 9000 --host 0.0.0.0          # Custom port/host

# System status
bitmod status                                 # Config + cache + document stats

# Database migrations
bitmod migrate --status                       # Show current version + pending
bitmod migrate                                # Apply all pending migrations
bitmod migrate --target 3                     # Migrate to specific version`}</CodeBlock>
          </div>
        </section>

        <Separator />

        {/* Authentication */}
        <section>
          <SectionHeader
            id="auth"
            title="Authentication"
            description="API key management for your instance with tiered access, scopes, and JWT token exchange."
          />

          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold mb-3">Enable Authentication</h3>
              <CodeBlock filename=".env">{`BITMOD_AUTH_ENABLED=1
BITMOD_JWT_SECRET=your-256-bit-random-secret

# Optional: pre-configured API keys (comma-separated hashes)
# BITMOD_API_KEYS=key1,key2`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">API Key Management</h3>
              <CodeBlock filename="terminal">{`# Create an API key
curl -X POST https://api.bitmod.io/v1/auth/keys \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Production App", "scopes": ["read", "write"]}'

# Response: {"key": "bm_a1b2c3...", "id": "uuid", "message": "Store this key securely."}

# List all keys (previews only, never plaintext)
curl https://api.bitmod.io/v1/auth/keys

# Revoke a key
curl -X DELETE https://api.bitmod.io/v1/auth/keys/{key_id}

# Exchange API key for JWT token
curl -X POST https://api.bitmod.io/v1/auth/token \\
  -d '{"api_key": "bm_a1b2c3..."}'

# Use the JWT token
curl https://api.bitmod.io/v1/chat \\
  -H "Authorization: Bearer eyJhbG..."

# Or use the API key directly
curl https://api.bitmod.io/v1/chat \\
  -H "Authorization: ApiKey bm_a1b2c3..."`}</CodeBlock>
            </div>

            <div className="rounded-xl border border-border/40 bg-card/50 p-6">
              <h4 className="font-semibold text-sm mb-2">Scopes</h4>
              <div className="grid grid-cols-2 gap-2 text-sm text-muted-foreground">
                <div><code className="text-primary">read</code> — Query, search, view stats</div>
                <div><code className="text-primary">write</code> — Ingest documents, manage cache</div>
                <div><code className="text-primary">admin</code> — Manage keys, view metrics</div>
                <div><code className="text-primary">ingest</code> — Ingest documents only</div>
              </div>
            </div>
          </div>
        </section>

        <Separator />

        {/* Configuration */}
        <section>
          <SectionHeader
            id="configuration"
            title="Configuration"
            description="BitMod is configured entirely through environment variables. No config files needed."
          />

          <div className="grid gap-4 sm:grid-cols-2">
            {[
              { var: "BITMOD_DB_BACKEND", default: "sqlite", desc: "Database backend" },
              { var: "BITMOD_LLM_PROVIDER", default: "auto", desc: "LLM provider (auto, anthropic, openai, ollama, gemini, bedrock, azure_openai, xai, mistral, perplexity, openrouter, huggingface)" },
              { var: "BITMOD_LLM_MODEL", default: "(auto)", desc: "LLM model name" },
              { var: "BITMOD_EMBEDDING_PROVIDER", default: "local", desc: "Embedding provider" },
              { var: "BITMOD_CACHE_SEMANTIC_THRESHOLD", default: "0.88", desc: "Semantic cache similarity threshold" },
              { var: "BITMOD_VECTOR_STORE", default: "(none)", desc: "Optional vector store" },
              { var: "BITMOD_SQLITE_PATH", default: "bitmod.db", desc: "SQLite file path" },
            ].map((env) => (
              <Card key={env.var} className="border-border/40 bg-card/50">
                <CardContent className="pt-4 pb-4">
                  <code className="text-sm font-mono text-primary">{env.var}</code>
                  <p className="text-sm text-muted-foreground mt-1">{env.desc}</p>
                  <p className="text-xs text-muted-foreground mt-1">Default: <code className="text-accent">{env.default}</code></p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <Separator />

        {/* LLM Providers */}
        <section>
          <SectionHeader
            id="llm-providers"
            title="LLM Providers"
            description="Connect to any major LLM provider. All adapters implement the same LLMProvider interface."
          />

          <Tabs defaultValue="anthropic" className="w-full">
            <TabsList className="grid w-full grid-cols-4 lg:grid-cols-7 h-auto">
              <TabsTrigger value="anthropic" className="text-xs">Anthropic</TabsTrigger>
              <TabsTrigger value="openai" className="text-xs">OpenAI</TabsTrigger>
              <TabsTrigger value="ollama" className="text-xs">Ollama</TabsTrigger>
              <TabsTrigger value="gemini" className="text-xs">Gemini</TabsTrigger>
              <TabsTrigger value="bedrock" className="text-xs">Bedrock</TabsTrigger>
              <TabsTrigger value="azure" className="text-xs">Azure</TabsTrigger>
              <TabsTrigger value="compat" className="text-xs">Compatible</TabsTrigger>
            </TabsList>

            <TabsContent value="anthropic" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
BITMOD_LLM_MODEL=claude-sonnet-4-20250514`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[anthropic]</code></p>
            </TabsContent>

            <TabsContent value="openai" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
BITMOD_LLM_MODEL=gpt-4o`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[openai]</code></p>
            </TabsContent>

            <TabsContent value="ollama" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
BITMOD_LLM_MODEL=llama3.2`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">No extra install needed. Just run Ollama locally.</p>
            </TabsContent>

            <TabsContent value="gemini" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=gemini
GEMINI_API_KEY=...
BITMOD_LLM_MODEL=gemini-2.0-flash`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[gemini]</code></p>
            </TabsContent>

            <TabsContent value="bedrock" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
# Uses IAM credentials from AWS CLI / environment`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[bedrock]</code></p>
            </TabsContent>

            <TabsContent value="azure" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://myresource.openai.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4o`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[azure]</code></p>
            </TabsContent>

            <TabsContent value="compat" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_LLM_PROVIDER=openai_compatible
BITMOD_LLM_BASE_URL=https://api.groq.com/openai/v1
BITMOD_LLM_API_KEY=gsk_...

# Works with: Groq, Mistral, Together, Fireworks,
# vLLM, LM Studio, and any OpenAI-compatible API`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">No extra install needed. Uses httpx.</p>
            </TabsContent>
          </Tabs>
        </section>

        <Separator />

        {/* Databases */}
        <section>
          <SectionHeader
            id="databases"
            title="Database Backends"
            description="Four database backends, one interface. SQLite ships built-in."
          />

          <Tabs defaultValue="sqlite" className="w-full">
            <TabsList className="grid w-full grid-cols-4 h-auto">
              <TabsTrigger value="sqlite" className="text-xs">SQLite</TabsTrigger>
              <TabsTrigger value="postgresql" className="text-xs">PostgreSQL</TabsTrigger>
              <TabsTrigger value="mysql" className="text-xs">MySQL</TabsTrigger>
              <TabsTrigger value="mongodb" className="text-xs">MongoDB</TabsTrigger>
            </TabsList>

            <TabsContent value="sqlite" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_DB_BACKEND=sqlite
BITMOD_SQLITE_PATH=bitmod.db`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Built-in. Zero dependencies. FTS5 full-text search included.</p>
            </TabsContent>

            <TabsContent value="postgresql" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_DB_BACKEND=postgresql
DATABASE_URL=postgresql://bitmod:password@db.bitmod.io:5432/bitmod`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[postgresql]</code> — includes pgvector + pg_trgm for hybrid search and fuzzy matching.</p>
            </TabsContent>

            <TabsContent value="mysql" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_DB_BACKEND=mysql
BITMOD_MYSQL_URL=mysql+pymysql://bitmod:password@db.bitmod.io:3306/bitmod`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[mysql]</code></p>
            </TabsContent>

            <TabsContent value="mongodb" className="mt-4">
              <CodeBlock filename=".env">{`BITMOD_DB_BACKEND=mongodb
BITMOD_MONGODB_URL=mongodb://db.bitmod.io:27017
BITMOD_MONGODB_DB=bitmod`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Requires: <code className="text-primary">pip install bitmod[mongodb]</code></p>
            </TabsContent>
          </Tabs>
        </section>

        <Separator />

        {/* Embeddings */}
        <section>
          <SectionHeader
            id="embeddings"
            title="Embedding Providers"
            description="Generate embeddings for vector search. Local by default — no API needed."
          />

          <div className="grid gap-4 sm:grid-cols-2">
            {[
              { name: "Local (Sentence Transformers)", install: "pip install bitmod[embeddings-local]", env: "BITMOD_EMBEDDING_PROVIDER=local", default: true },
              { name: "OpenAI", install: "pip install bitmod[openai]", env: "BITMOD_EMBEDDING_PROVIDER=openai" },
              { name: "Cohere", install: "pip install bitmod[embeddings-cohere]", env: "BITMOD_EMBEDDING_PROVIDER=cohere" },
              { name: "Ollama", install: "No extra install", env: "BITMOD_EMBEDDING_PROVIDER=ollama" },
            ].map((provider) => (
              <Card key={provider.name} className="border-border/40 bg-card/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    {provider.name}
                    {provider.default && <Badge variant="accent" className="text-[10px]">Default</Badge>}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-1">
                  <code className="text-xs font-mono text-primary block">{provider.env}</code>
                  <p className="text-xs text-muted-foreground">{provider.install}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <Separator />

        {/* Vector Stores */}
        <section>
          <SectionHeader
            id="vector-stores"
            title="Vector Stores"
            description="Optional dedicated vector stores. The database backend includes built-in vector search by default."
          />

          <div className="grid gap-4 sm:grid-cols-3">
            {[
              { name: "ChromaDB", install: "pip install bitmod[chroma]", desc: "Embedded, great for local dev" },
              { name: "Qdrant", install: "pip install bitmod[qdrant]", desc: "High-performance, production-ready" },
              { name: "Pinecone", install: "pip install bitmod[pinecone]", desc: "Fully managed, serverless" },
            ].map((store) => (
              <Card key={store.name} className="border-border/40 bg-card/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{store.name}</CardTitle>
                  <CardDescription className="text-xs">{store.desc}</CardDescription>
                </CardHeader>
                <CardContent>
                  <code className="text-xs font-mono text-primary">{store.install}</code>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <Separator />

        {/* Ingestion */}
        <section>
          <SectionHeader
            id="ingestion"
            title="Document Ingestion"
            description="Parse, chunk, embed, and store documents in one call."
          />

          <CodeBlock filename="ingest_example.py">{`from bitmod.ingestion import ingest_file, ingest_text
from bitmod.ingestion.chunker import ChunkConfig
from bitmod.adapters import get_backend, get_embedder

backend = get_backend()
backend.initialize()
embedder = get_embedder()

# Ingest a PDF with custom chunking
result = ingest_file(
    "research.pdf",
    document_type="research",
    backend=backend,
    embedder=embedder,
    chunk_config=ChunkConfig(
        strategy="recursive",
        max_size=512,
        overlap=64,
    ),
)

# Supported formats: PDF, DOCX, HTML, Markdown, CSV, JSON, plain text
# Three chunking strategies: recursive (default), fixed-window, semantic`}</CodeBlock>
        </section>

        <Separator />

        {/* Cache Engine */}
        <section>
          <SectionHeader
            id="cache-engine"
            title="Cache Engine"
            description="Nine-layer intelligent cache. Exact match, semantic similarity, composable decomposition, fuzzy matching, source-aware invalidation."
          />

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
            {[
              { title: "Parameterized Keys", desc: "SHA-256 composite keys across query, filters, temporal scope, and language" },
              { title: "Double Verification", desc: "Every cached answer is verified against source data versions before serving" },
              { title: "Fuzzy Matching", desc: "Similar queries surface cached answers for user confirmation" },
              { title: "Query Decomposition", desc: "Complex queries decomposed into independently cacheable sub-queries" },
              { title: "Temporal Queries", desc: "Historical queries are permanently valid — exempt from invalidation" },
              { title: "Auto-Invalidation", desc: "When source data changes, dependent cached answers are automatically invalidated" },
              { title: "Cache Qualification", desc: "Detects context-dependent queries (anaphora, pronouns, continuations, short follow-ups) and routes them to the LLM with full conversation history instead of serving stale cached answers." },
            ].map((feature) => (
              <Card key={feature.title} className="border-border/40 bg-card/50">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{feature.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">{feature.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <CodeBlock filename="cache_example.py">{`from bitmod.cache_engine import try_cache, store_answer, compute_answer_key
from bitmod.adapters import get_backend

backend = get_backend()
backend.initialize()

with backend.session() as session:
    # Check cache first
    cached = try_cache(backend, session, "What is the capital of France?")
    if cached:
        print(f"Cache HIT: {cached.answer_text}")
        print(f"Served {cached.serve_count} times")
    else:
        # Generate and cache
        answer_key = compute_answer_key("What is the capital of France?")
        store_answer(
            backend, session,
            answer_key=answer_key,
            question_raw="What is the capital of France?",
            question_normalized="capital france",
            filters={},
            answer_text="The capital of France is Paris.",
            source_sections=[],
            model_used="claude-sonnet-4-20250514",
            generation_ms=1200,
        )`}</CodeBlock>
        </section>

        <Separator />

        {/* Docker Deployment */}
        <section>
          <SectionHeader
            id="docker"
            title="Docker Deployment"
            description="Four deployment profiles from minimal to full-stack. One command to start."
          />

          <Tabs defaultValue="minimal" className="w-full">
            <TabsList className="grid w-full grid-cols-4 h-auto">
              <TabsTrigger value="minimal" className="text-xs">Minimal</TabsTrigger>
              <TabsTrigger value="ollama" className="text-xs">+ Ollama</TabsTrigger>
              <TabsTrigger value="postgres" className="text-xs">+ PostgreSQL</TabsTrigger>
              <TabsTrigger value="full" className="text-xs">Full Stack</TabsTrigger>
            </TabsList>

            <TabsContent value="minimal" className="mt-4">
              <CodeBlock filename="terminal">{`docker compose up

# Starts: gateway (8000) + chat (8001) + frontend (3000)
# Database: SQLite (zero config)
# LLM: bring your own (set BITMOD_LLM_PROVIDER + API key in .env)
# Embeddings: local (sentence-transformers)`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Minimal footprint. SQLite, local embeddings, your cloud LLM API key.</p>
            </TabsContent>

            <TabsContent value="ollama" className="mt-4">
              <CodeBlock filename="terminal">{`docker compose --profile ollama up

# Adds: Ollama (11434) with 4GB memory reservation
# LLM: ollama/llama3.2 (no API keys needed)
# Embeddings: ollama/nomic-embed-text
# First run: docker exec bitmod-ollama ollama pull llama3.2`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Fully offline. No API keys, no cloud dependencies.</p>
            </TabsContent>

            <TabsContent value="postgres" className="mt-4">
              <CodeBlock filename="terminal">{`docker compose --profile postgres up

# Adds: PostgreSQL 16 + pgvector (5432) + Redis (6379)
# Database: postgresql with vector search + fuzzy matching
# Rate limiting: Redis-backed (distributed)
# Set POSTGRES_PASSWORD in .env for production`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Production-grade persistence with pgvector hybrid search.</p>
            </TabsContent>

            <TabsContent value="full" className="mt-4">
              <CodeBlock filename="terminal">{`docker compose --profile ollama --profile postgres up

# All services: gateway + chat + frontend + Ollama + PostgreSQL + Redis
# Complete standalone system — no external dependencies
# Perfect for air-gapped or self-hosted deployments`}</CodeBlock>
              <p className="mt-3 text-sm text-muted-foreground">Everything included. Ideal for self-hosted or air-gapped environments.</p>
            </TabsContent>
          </Tabs>
        </section>

        <Separator />

        {/* Plug-and-Play Integrations */}
        <section>
          <SectionHeader
            id="integrations"
            title="Plug-and-Play Integrations"
            description="Use BitMod as a drop-in caching layer with your existing LLM tools. No code changes required — just point your tool at BitMod's OpenAI-compatible proxy."
          />

          <div className="space-y-8">
            <Card className="border-primary/20 bg-primary/5">
              <CardContent className="py-6">
                <h3 className="text-lg font-semibold mb-2">How It Works</h3>
                <p className="text-muted-foreground text-sm">
                  BitMod exposes an OpenAI-compatible API at <code className="text-primary">/v1/chat/completions</code>.
                  Any tool that can talk to the OpenAI API can use BitMod as a drop-in replacement.
                  Your requests go through the 9-layer cache — identical or similar queries are served instantly instead of hitting the upstream LLM.
                </p>
              </CardContent>
            </Card>

            <div>
              <h3 className="text-lg font-semibold mb-3">LM Studio</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Point LM Studio at BitMod to cache all your local model responses. BitMod will forward requests to your LM Studio instance and cache the results.
              </p>
              <CodeBlock filename=".env">{`# In your bitmod .env or bitmod.yaml:
BITMOD_LLM_PROVIDER=openai_compat
BITMOD_LLM_API_BASE=http://localhost:1234/v1
BITMOD_LLM_API_KEY=not-needed

# Then point your apps at BitMod instead:
# Old: http://localhost:1234/v1/chat/completions
# New: http://localhost:8000/v1/chat/completions`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">VS Code (Continue.dev / Copilot alternatives)</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Use BitMod with Continue.dev or any VS Code extension that supports OpenAI-compatible endpoints.
              </p>
              <CodeBlock filename="~/.continue/config.json">{`{
  "models": [
    {
      "title": "BitMod (cached)",
      "provider": "openai",
      "model": "any-model",
      "apiBase": "http://localhost:8000/v1",
      "apiKey": "your-bitmod-api-key"
    }
  ]
}`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">Open WebUI / Ollama Web UI</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Set BitMod as the OpenAI-compatible endpoint in Open WebUI. All conversations get cached.
              </p>
              <CodeBlock filename="docker-compose.yml">{`services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    environment:
      OPENAI_API_BASE_URL: http://bitmod-gateway:8000/v1
      OPENAI_API_KEY: your-bitmod-api-key`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">LangChain</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Use BitMod as a drop-in LLM in your LangChain pipelines. All calls are cached automatically.
              </p>
              <CodeBlock filename="app.py">{`from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-bitmod-api-key",
    model="claude-sonnet-4-20250514",  # or any model
)

# All calls are cached automatically
response = llm.invoke("What is the capital of France?")
# Second identical call: served from cache (68-82ms over HTTP)`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">Python (OpenAI SDK)</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Any app using the OpenAI Python SDK works with a one-line change.
              </p>
              <CodeBlock filename="app.py">{`from openai import OpenAI

# Just change the base_url — everything else stays the same
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-bitmod-api-key",
)

# Works exactly like OpenAI, but with intelligent caching
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain quantum computing"}],
)`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">Anthropic SDK</h3>
              <p className="text-sm text-muted-foreground mb-3">
                BitMod natively supports the Anthropic <code className="text-primary">/v1/messages</code> format. No translation needed.
              </p>
              <CodeBlock filename="app.py">{`import anthropic

client = anthropic.Anthropic(
    base_url="http://localhost:8000",
    api_key="your-bitmod-api-key",
)

message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)
# Identical requests served from cache instantly`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">CrewAI</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Cache every agent call in your CrewAI workflows. Saves significant cost during development and iteration.
              </p>
              <CodeBlock filename="app.py">{`from crewai import Agent, LLM

llm = LLM(
    model="openai/gpt-4o",
    base_url="http://localhost:8000/v1",
    api_key="your-bitmod-api-key",
)

agent = Agent(role="Researcher", llm=llm, ...)
# Every LLM call the agent makes is cached`}</CodeBlock>
            </div>

            <div>
              <h3 className="text-lg font-semibold mb-3">cURL / Any HTTP Client</h3>
              <p className="text-sm text-muted-foreground mb-3">
                The proxy endpoint accepts standard OpenAI API format.
              </p>
              <CodeBlock filename="terminal">{`curl http://localhost:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer your-bitmod-api-key" \\
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`}</CodeBlock>
            </div>
          </div>
        </section>
        </div>
      </div>
    </div>
  )
}