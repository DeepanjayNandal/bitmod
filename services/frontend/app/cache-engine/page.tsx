import type { Metadata } from "next"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Zap, ArrowRight, Hash, Key, Search, Puzzle, SpellCheck,
  ShieldCheck, Clock, BarChart3, CheckCircle, XCircle,
  Brain, RefreshCw, FileText, Database, Layers, ScanEye,
  MessageSquare
} from "lucide-react"

export const metadata: Metadata = {
  title: "9-Layer Cache Engine | BitMod",
  description: "Nine-layer intelligent cache pipeline: exact match, semantic similarity, composable decomposition, fuzzy matching, and source-aware invalidation.",
}

const CACHE_LAYERS = [
  {
    num: 1,
    name: "Normalization",
    desc: "Lowercase, strip stopwords, SHA-256 composite key",
    icon: FileText,
    color: "text-[#79c0ff]", borderColor: "border-[#79c0ff]/20", bgColor: "bg-[#79c0ff]/5",
  },
  {
    num: 2,
    name: "Exact Match",
    desc: "O(1) key lookup against the normalized composite key",
    icon: Hash,
    color: "text-[#ffa657]", borderColor: "border-[#ffa657]/20", bgColor: "bg-[#ffa657]/5",
  },
  {
    num: 3,
    name: "Source Verification",
    desc: "Per-section SHA-256 check; any mismatch invalidates the answer",
    icon: ShieldCheck,
    color: "text-[#7ee787]", borderColor: "border-[#7ee787]/20", bgColor: "bg-[#7ee787]/5",
  },
  {
    num: 4,
    name: "Semantic Similarity",
    desc: "Embedding cosine search, threshold >= 0.88",
    icon: Search,
    color: "text-[#d2a8ff]", borderColor: "border-[#d2a8ff]/20", bgColor: "bg-[#d2a8ff]/5",
  },
  {
    num: 5,
    name: "Composable Decomposition",
    desc: "Break complex queries into sub-caches, reassemble answers",
    icon: Puzzle,
    color: "text-[#ff7b72]", borderColor: "border-[#ff7b72]/20", bgColor: "bg-[#ff7b72]/5",
  },
  {
    num: 6,
    name: "Fuzzy Match",
    desc: "Order-independent token overlap and edit distance, >= 0.85",
    icon: SpellCheck,
    color: "text-[#79c0ff]", borderColor: "border-[#79c0ff]/20", bgColor: "bg-[#79c0ff]/5",
  },
  {
    num: 7,
    name: "Similarity Link Traversal",
    desc: "Two-hop graph of near-misses learned across earlier queries",
    icon: RefreshCw,
    color: "text-[#ffa657]", borderColor: "border-[#ffa657]/20", bgColor: "bg-[#ffa657]/5",
  },
  {
    num: 8,
    name: "Atomic Fact Search",
    desc: "Embedding search over facts extracted from cached answers",
    icon: ScanEye,
    color: "text-[#7ee787]", borderColor: "border-[#7ee787]/20", bgColor: "bg-[#7ee787]/5",
  },
  {
    num: 9,
    name: "Session Context",
    desc: "Prior turns of the same conversation injected as partial evidence. Semantic retrieval is scoped to the conversation that wrote the entry, so a follow-up in one conversation cannot be answered from another's cached reply.",
    icon: MessageSquare,
    color: "text-[#d2a8ff]", borderColor: "border-[#d2a8ff]/20", bgColor: "bg-[#d2a8ff]/5",
  },
]

// Not pipeline layers. These run around the cache rather than inside the
// lookup path, and were previously listed among the nine — which both
// overstated the pipeline and pushed three real layers off the page.
const CACHE_MANAGEMENT = [
  {
    name: "TTL Expiration",
    desc: "Entries carry an optional max_age_seconds and expire on read. No global default is configured, so entries written by the proxy and chat service never expire.",
    icon: Clock,
  },
  {
    name: "Temporal Queries",
    desc: "Answers about a fixed point in time stay valid and are exempt from invalidation.",
    icon: Clock,
  },
  {
    name: "LRU Eviction",
    desc: "Least-recently-used entries are dropped once max_entries is exceeded. Implemented on SQLite only — the PostgreSQL, MySQL and MongoDB backends do not evict.",
    icon: Database,
  },
]

export default function CacheEnginePage() {
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
          <Badge variant="accent" className="mb-6 px-4 py-1.5 text-sm">
            Product
          </Badge>

          <h1 className="text-5xl font-extrabold tracking-tight sm:text-7xl">
            <span className="bg-gradient-to-r from-primary via-primary to-accent bg-clip-text text-transparent">
              9-Layer
            </span>
            <br />
            <span className="text-foreground">Intelligent Cache Engine</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Eliminates redundant LLM calls through nine cascading cache layers
            &mdash; from exact hash matching to semantic similarity, composable
            decomposition, and automatic source-aware invalidation.
          </p>
        </div>
      </section>

      {/* Stats Bar */}
      <section className="border-y border-border/40 bg-card/30 backdrop-blur-sm">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            {[
              { value: "68-82ms", label: "Cached, over HTTP", icon: Zap },
              { value: "9", label: "Cache Layers", icon: Layers },
              { value: "Fail-Closed", label: "Source Verification", icon: ShieldCheck },
              { value: "3", label: "Compression Levels", icon: Database },
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

      {/* 9-Layer Flow Diagram */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Architecture</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Nine layers.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              One pipeline.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Every query passes through all nine layers in sequence.
            A hit at any layer short-circuits the rest.
          </p>
        </div>

        <div className="mx-auto max-w-2xl">
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 overflow-hidden shadow-2xl">
            {/* Incoming query */}
            <div className="text-center mb-4">
              <div className="inline-flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/20 px-5 py-2.5 text-primary font-semibold text-sm arch-node">
                <Brain className="h-4 w-4" />
                Incoming Query
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground font-mono">
                &ldquo;What were Q3 revenue numbers?&rdquo;
              </div>
            </div>

            {/* Layer cards with pulse connectors */}
            {CACHE_LAYERS.map((layer, i) => (
              <div key={layer.num}>
                {/* Animated connector */}
                <div className="flex justify-center">
                  <div
                    className="w-px h-8 bg-gradient-to-b from-primary/60 to-primary/20 animate-flow-pulse"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                </div>

                {/* Layer node */}
                <div className={`rounded-lg ${layer.bgColor} border ${layer.borderColor} p-4 arch-node`}>
                  <div className="flex items-center gap-3">
                    <div className={`flex items-center justify-center h-8 w-8 rounded-full bg-muted/20 border border-border/20 shrink-0`}>
                      <span className={`text-xs font-bold ${layer.color}`}>{layer.num}</span>
                    </div>
                    <layer.icon className={`h-5 w-5 ${layer.color} shrink-0`} />
                    <div className="min-w-0">
                      <div className={`text-sm font-semibold ${layer.color}`}>{layer.name}</div>
                      <div className="text-[11px] text-muted-foreground leading-tight">{layer.desc}</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Final connector */}
            <div className="flex justify-center">
              <div
                className="w-px h-8 bg-gradient-to-b from-green-400/60 to-green-400/20 animate-flow-pulse"
                style={{ animationDelay: "1.5s" }}
              />
            </div>

            {/* Response */}
            <div className="text-center">
              <div className="inline-flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-5 py-2.5 text-green-400 font-semibold text-sm arch-node">
                <Zap className="h-4 w-4" />
                Verified Response
              </div>
              <p className="text-[10px] text-muted-foreground mt-2">
                Cached, verified, and served with source citations
              </p>
            </div>
          </div>
        </div>
      </section>

      <Separator />

      {/* Cache management — deliberately not counted among the nine */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="secondary" className="mb-4">Cache Management</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Around the pipeline, not in it
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            These run alongside the lookup path. They are not cache layers and are not counted among the nine.
          </p>
        </div>

        <div className="mx-auto max-w-5xl grid gap-6 sm:grid-cols-3">
          {CACHE_MANAGEMENT.map((m) => (
            <Card key={m.name} className="border-border/40 bg-card/50">
              <CardHeader>
                <m.icon className="h-8 w-8 text-muted-foreground mb-2" />
                <CardTitle className="text-lg">{m.name}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">{m.desc}</CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Separator />

      {/* Cache Hit vs Cache Miss */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Flow</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Cache Hit vs Cache Miss
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Two paths, both end in a cached answer. The second request is always instant.
          </p>
        </div>

        <div className="grid gap-8 md:grid-cols-2">
          {/* Cache HIT */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 shadow-2xl">
            <div className="text-center mb-6">
              <div className="inline-flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-5 py-2.5 text-green-400 font-semibold arch-node">
                <CheckCircle className="h-5 w-5" />
                Cache HIT
              </div>
            </div>

            <div className="space-y-3">
              {[
                { step: "1", label: "Query arrives at cache engine", color: "text-[#79c0ff]" },
                { step: "2", label: "Matched at any of 9 layers", color: "text-[#7ee787]" },
                { step: "3", label: "Source versions verified current", color: "text-[#ffa657]" },
                { step: "4", label: "TTL validated, entry still fresh", color: "text-[#d2a8ff]" },
                { step: "5", label: "Response returned instantly", color: "text-green-400" },
              ].map((s, i) => (
                <div key={s.step}>
                  <div className="flex items-center gap-3 arch-node">
                    <div className={`h-6 w-6 rounded-full bg-muted/20 flex items-center justify-center text-[10px] font-bold ${s.color}`}>
                      {s.step}
                    </div>
                    <span className="text-xs text-muted-foreground">{s.label}</span>
                  </div>
                  {i < 4 && (
                    <div className="flex ml-3 justify-start">
                      <div className="w-px h-3 bg-gradient-to-b from-green-400/40 to-green-400/10 animate-flow-pulse" style={{ animationDelay: `${i * 0.1}s` }} />
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-lg bg-green-500/5 border border-green-500/20 px-4 py-3 text-center">
              <div className="text-green-400 text-2xl font-bold">~80ms</div>
              <div className="text-[10px] text-green-400/70 mt-1">Zero LLM calls &middot; Zero cost &middot; Exact match over HTTP</div>
            </div>
          </div>

          {/* Cache MISS */}
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 shadow-2xl">
            <div className="text-center mb-6">
              <div className="inline-flex items-center gap-2 rounded-lg bg-accent/10 border border-accent/20 px-5 py-2.5 text-accent font-semibold arch-node">
                <XCircle className="h-5 w-5" />
                Cache MISS
              </div>
            </div>

            <div className="space-y-3">
              {[
                { step: "1", label: "Query arrives, no match in any layer", color: "text-[#79c0ff]" },
                { step: "2", label: "Query forwarded to LLM provider", color: "text-[#ffa657]" },
                { step: "3", label: "LLM generates answer with sources", color: "text-[#d2a8ff]" },
                { step: "4", label: "Response cached with composite key", color: "text-[#7ee787]" },
                { step: "5", label: "Source versions locked for invalidation", color: "text-green-400" },
              ].map((s, i) => (
                <div key={s.step}>
                  <div className="flex items-center gap-3 arch-node">
                    <div className={`h-6 w-6 rounded-full bg-muted/20 flex items-center justify-center text-[10px] font-bold ${s.color}`}>
                      {s.step}
                    </div>
                    <span className="text-xs text-muted-foreground">{s.label}</span>
                  </div>
                  {i < 4 && (
                    <div className="flex ml-3 justify-start">
                      <div className="w-px h-3 bg-gradient-to-b from-accent/40 to-accent/10 animate-flow-pulse" style={{ animationDelay: `${i * 0.1}s` }} />
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-lg bg-accent/5 border border-accent/20 px-4 py-3 text-center">
              <div className="text-accent text-sm font-semibold">Auto-Cached</div>
              <div className="text-[10px] text-accent/70 mt-1">Next identical or similar query returns instantly from cache</div>
            </div>
          </div>
        </div>
      </section>

      <Separator />

      {/* Cache Qualification Layer */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Quality Gate</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Cache Qualification Layer.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Context-aware routing.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground max-w-2xl mx-auto">
            Each user has their own individual cache, so model and role settings are always consistent.
            The one thing that can make a cache hit stale is conversation context.
          </p>
        </div>

        <div className="mx-auto max-w-3xl">
          <div className="rounded-lg bg-[#79c0ff]/5 border border-[#79c0ff]/20 p-5">
            <div className="flex items-start gap-3">
              <MessageSquare className="h-5 w-5 text-[#79c0ff] shrink-0 mt-0.5" />
              <div>
                <div className="text-sm font-semibold text-[#79c0ff]">Context-Dependent Query Detection</div>
                <div className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
                  Detects queries that depend on conversation history &mdash; anaphora (&ldquo;tell me more about that&rdquo;),
                  pronouns (&ldquo;what does it cost?&rdquo;), continuations (&ldquo;and the next step?&rdquo;), and short follow-ups
                  (&ldquo;yes&rdquo;, &ldquo;go on&rdquo;). These are routed to the LLM with full conversation context instead of
                  being served from cache, where a generic cached answer would be meaningless.
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mx-auto max-w-3xl mt-8">
          <div className="rounded-lg bg-muted/10 border border-border/40 px-5 py-4">
            <div className="flex items-center gap-2 mb-2">
              <ScanEye className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold text-foreground">Pipeline Trace</span>
            </div>
            <p className="text-xs text-muted-foreground mb-3">
              When a cache hit is disqualified, the pipeline trace shows the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-[10px] font-mono">SKIP_QUALIFIED</code> action:
            </p>
            <div className="rounded-md bg-[#0d1117] border border-border/30 px-4 py-3 font-mono text-[11px] text-muted-foreground overflow-x-auto">
              semantic:HIT(0.4ms) &gt; qualify:SKIP_QUALIFIED(context_dependent) &gt; llm:GENERATED(1.2s)
            </div>
          </div>
        </div>
      </section>

      <Separator />

      {/* Block-Level Compression */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Compression</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Three compression levels.{" "}
            <span className="text-muted-foreground">One document.</span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Every cached block is stored at three fidelity levels simultaneously.
            The cache engine selects the optimal level based on the query.
          </p>
        </div>

        <div className="mx-auto max-w-3xl grid gap-6 sm:grid-cols-3">
          {[
            {
              level: "Full",
              tokens: "~500 tokens",
              desc: "Complete text with all detail preserved. Used for deep analysis and citation.",
              color: "border-primary/30 bg-primary/5",
              textColor: "text-primary",
              tokenColor: "text-primary/60",
            },
            {
              level: "Structured",
              tokens: "~80 tokens",
              desc: "Extracted entities, dates, and amounts as JSON. Used for comparison queries.",
              color: "border-accent/30 bg-accent/5",
              textColor: "text-accent",
              tokenColor: "text-accent/60",
            },
            {
              level: "Headline",
              tokens: "~15 tokens",
              desc: "Title or first sentence. Used for quick scanning and summarization.",
              color: "border-green-500/30 bg-green-500/5",
              textColor: "text-green-400",
              tokenColor: "text-green-400/60",
            },
          ].map((block) => (
            <Card key={block.level} className={`border ${block.color} hover:border-border/80 transition-all duration-300 hover:shadow-lg`}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className={`text-lg ${block.textColor}`}>{block.level}</CardTitle>
                  <span className={`text-xs font-mono ${block.tokenColor}`}>{block.tokens}</span>
                </div>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">{block.desc}</CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Separator />

      {/* Cascade Invalidation */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Invalidation</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Cascade invalidation.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Zero stale answers.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            When source data changes, every cached answer that referenced the changed
            sections is automatically invalidated. No manual purging, no stale data.
          </p>
        </div>

        <div className="mx-auto max-w-2xl">
          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 overflow-hidden shadow-2xl">
            {[
              {
                step: "1",
                label: "Source document re-ingested",
                detail: "New version of research.pdf uploaded",
                color: "text-primary",
                bgColor: "bg-primary/5",
                borderColor: "border-primary/20",
                icon: FileText,
              },
              {
                step: "2",
                label: "Content hash compared",
                detail: "SHA-256 of each block compared to stored version",
                color: "text-primary",
                bgColor: "bg-primary/5",
                borderColor: "border-primary/20",
                icon: Hash,
              },
              {
                step: "3",
                label: "Changed sections detected",
                detail: "3 of 47 blocks have new content hashes",
                color: "text-accent",
                bgColor: "bg-accent/5",
                borderColor: "border-accent/20",
                icon: Search,
              },
              {
                step: "4",
                label: "Dependent answers invalidated",
                detail: "12 cached answers referenced those 3 blocks",
                color: "text-accent",
                bgColor: "bg-accent/5",
                borderColor: "border-accent/20",
                icon: RefreshCw,
              },
              {
                step: "5",
                label: "Next query triggers fresh generation",
                detail: "LLM called with updated source context",
                color: "text-[#ffa657]",
                bgColor: "bg-[#ffa657]/5",
                borderColor: "border-[#ffa657]/20",
                icon: Brain,
              },
              {
                step: "6",
                label: "New answer cached with updated versions",
                detail: "Source version locks updated to latest hashes",
                color: "text-green-400",
                bgColor: "bg-green-500/5",
                borderColor: "border-green-500/20",
                icon: CheckCircle,
              },
            ].map((s, i) => (
              <div key={s.step}>
                {i > 0 && (
                  <div className="flex justify-center">
                    <div
                      className="w-px h-8 bg-gradient-to-b from-primary/60 to-primary/20 animate-flow-pulse"
                      style={{ animationDelay: `${i * 0.2}s` }}
                    />
                  </div>
                )}
                <div className={`rounded-lg ${s.bgColor} border ${s.borderColor} p-4 arch-node`}>
                  <div className="flex items-center gap-3">
                    <div className={`h-7 w-7 rounded-full bg-muted/20 flex items-center justify-center text-xs font-bold ${s.color} shrink-0`}>
                      {s.step}
                    </div>
                    <s.icon className={`h-4 w-4 ${s.color} shrink-0`} />
                    <div className="min-w-0">
                      <div className={`text-sm font-semibold ${s.color}`}>{s.label}</div>
                      <div className="text-[11px] text-muted-foreground">{s.detail}</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          See how it works{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            in practice
          </span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Read the full documentation, explore the API, or jump straight into the playground.
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
