import type { Metadata } from "next"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import Link from "next/link"
import {
  CheckCircle2, Circle, Heart, ArrowRight,
  Database, Brain, Zap, Shield, Globe, Package, Plug,
  Server, DollarSign, Users, Rocket, Layers, Building2
} from "lucide-react"
import { GithubIcon } from "@/components/icons"

export const metadata: Metadata = {
  title: "Roadmap | BitMod",
  description: "See what is built, in progress, and planned for BitMod. Six phases from core engine to enterprise scale, driven by the open-source community.",
}

const phases = [
  {
    title: "Phase 1 — Core Engine",
    status: "complete" as const,
    icon: Brain,
    color: "text-green-400",
    borderColor: "border-green-500/30",
    bgColor: "bg-green-500/5",
    fundingNote: null,
    items: [
      { label: "9-layer intelligent cache engine (normalization, exact match, double verification, TTL expiration, fuzzy matching, semantic matching, composable decomposition, temporal handling, LRU eviction)", done: true },
      { label: "11 native LLM adapters + OpenAI-compatible universal adapter (12 total) — Anthropic, OpenAI, Ollama, Gemini, AWS Bedrock, Azure OpenAI, xAI, Mistral, Perplexity, OpenRouter, HuggingFace, plus any OpenAI-compatible provider (Groq, Together, vLLM, LM Studio, Jan.ai, and 200+ more)", done: true },
      { label: "Multi-format LLM proxy — OpenAI, Anthropic, and Gemini native format endpoints with automatic cross-format translation", done: true },
      { label: "4 database backends (SQLite, PostgreSQL, MySQL, MongoDB)", done: true },
      { label: "4 embedding providers (Ollama, local sentence-transformers, OpenAI, Cohere)", done: true },
      { label: "3 vector store integrations (ChromaDB, Qdrant, Pinecone)", done: true },
      { label: "Document ingestion for 7 formats (PDF, DOCX, HTML, Markdown, CSV, JSON, plain text)", done: true },
      { label: "CLI — init, ingest, query, serve, status", done: true },
      { label: "Block-level caching at 3 compression levels (full, headline, structured)", done: true },
      { label: "Intent detection with role-based routing and model tier selection", done: true },
      { label: "Cascade invalidation on content re-ingestion", done: true },
      { label: "Query normalization, composite keying (SHA-256), and double verification", done: true },
    ],
  },
  {
    title: "Phase 2 — Services & Operations",
    status: "complete" as const,
    icon: Server,
    color: "text-green-400",
    borderColor: "border-green-500/30",
    bgColor: "bg-green-500/5",
    fundingNote: null,
    items: [
      { label: "API gateway with rate limiting, CORS, and security headers", done: true },
      { label: "Chat service with SSE streaming, tool calling, and source citations", done: true },
      { label: "Database-backed API key management with SHA-256 hashing", done: true },
      { label: "JWT token exchange with scope escalation prevention", done: true },
      { label: "Database migration system", done: true },
      { label: "Prometheus metrics endpoint + Redis caching layer", done: true },
      { label: "Docker Compose with profiles (default, ollama, postgres, full)", done: true },
      { label: "Next.js admin dashboard with live metrics + interactive playground", done: true },
      { label: "5 messaging platform integrations (Slack, Discord, Telegram, WhatsApp, Matrix)", done: true },
      { label: "PyPI packaging with optional dependency groups", done: false },
      { label: "GitHub Actions CI/CD + trusted OIDC publishing", done: true },
    ],
  },
  {
    title: "Phase 3 — Open-Source Polish",
    status: "in-progress" as const,
    icon: Package,
    color: "text-yellow-400",
    borderColor: "border-yellow-500/30",
    bgColor: "bg-yellow-500/5",
    fundingNote: "Funding helps us finish the developer experience polish — one-click deploys, self-update, and tier-based rate limiting so every user gets a smooth onboarding.",
    description: "Frictionless CLI-first experience. A developer should go from pip install to seeing cache savings in under 5 minutes.",
    items: [
      { label: "Bayesian evidence accumulation — all 9 layers contribute graded confidence scores composed probabilistically", done: true },
      { label: "Universal LLM adapter — 200+ providers via 3 env vars (BITMOD_LLM_URL, BITMOD_LLM_API_KEY, BITMOD_LLM_MODEL)", done: true },
      { label: "Similarity link traversal — learned near-miss graph of related queries (new cache layer)", done: true },
      { label: "Atomic fact search — reusable facts decomposed from prior answers (new cache layer)", done: true },
      { label: "Streamlined ingest with progress bars and auto-detection", done: true },
      { label: "bitmod init --auto for zero-config setup", done: true },
      { label: "Python SDK (bitmod-client) with sync + async support", done: true },
      { label: "Security hardening — AES-256-GCM encryption at rest, RS256 JWT, token revocation, audit logging", done: true },
      { label: "Helm charts for Kubernetes deployment", done: true },
      { label: "bitmod update command — fetch latest from PyPI, self-update", done: false },
      { label: "Tier-based rate limiting — handle burst traffic gracefully", done: false },
      { label: "One-click deploy configs (Railway, Render, Vercel)", done: false },
    ],
  },
  {
    title: "Cache Engine Hardening",
    status: "planned" as const,
    icon: Layers,
    color: "text-[#79c0ff]",
    borderColor: "border-[#79c0ff]/30",
    bgColor: "bg-[#79c0ff]/5",
    fundingNote: "This phase requires dedicated engineering time for HNSW indexing, LLM-assisted decomposition, and cost-aware eviction — the features that take BitMod from good to untouchable.",
    description: "Harden every cache layer from working to untouchable. No competitor has multi-layer scored caching — this phase ensures nobody catches up.",
    items: [
      { label: "HNSW indexing for semantic cache — scale from thousands to millions of entries", done: false },
      { label: "Configurable embedding models — support domain-tuned embeddings for 92-97% precision", done: false },
      { label: "LLM-assisted query decomposition — generalize composable cache to any query type", done: false },
      { label: "Edit distance + phonetic fuzzy matching (Levenshtein, Soundex)", done: false },
      { label: "Atomic fact quality scoring + deduplication", done: false },
      { label: "2-hop bidirectional similarity links with time-based decay", done: false },
      { label: "Session/conversation cache layer", done: false },
      { label: "Cost-aware cache eviction — weight by LLM generation cost", done: false },
      { label: "Negative evidence — layers can subtract confidence on stale/contradicting data", done: false },
      { label: "Correlation-aware Bayesian accumulation", done: false },
      { label: "Circuit breaker for upstream LLMs with exponential backoff", done: false },
      { label: "Cache profiler CLI — bitmod cache-profile to identify optimization opportunities", done: false },
      { label: "Custom cache layer ordering — user-configurable priority per deployment", done: false },
      { label: "Cache analytics API — per-layer hit rates, confidence distributions, cost savings", done: false },
    ],
  },
  {
    title: "Phase 4 — Enterprise Features",
    status: "planned" as const,
    icon: Building2,
    color: "text-[#d2a8ff]",
    borderColor: "border-[#d2a8ff]/30",
    bgColor: "bg-[#d2a8ff]/5",
    fundingNote: "Enterprise features require billing infrastructure, legal review for compliance, and dedicated support engineering. Funding here directly enables sustainable revenue.",
    description: "Revenue-generating features. Gated by billing, not by removing open-source capabilities.",
    items: [
      { label: "Stripe billing integration", done: false },
      { label: "Private cache namespaces — isolated cache scoping per organization", done: false },
      { label: "Namespace-scoped ingestion — private documents within namespace boundary", done: false },
      { label: "Cross-namespace cache promotion — selectively share cached results", done: false },
      { label: "SSO / SAML / OAuth2 enterprise authentication", done: false },
      { label: "Granular RBAC with permission policies", done: false },
      { label: "Full audit logging with configurable retention policies", done: false },
      { label: "White-label deployment for enterprise customers", done: false },
      { label: "SLA-backed support tier", done: false },
    ],
  },
  {
    title: "Phase 5 — Agent Action Plans",
    status: "planned" as const,
    icon: Brain,
    color: "text-[#ffa657]",
    borderColor: "border-[#ffa657]/30",
    bgColor: "bg-[#ffa657]/5",
    fundingNote: "Agent plan caching is net-new R&D — cryptographic integrity, typed parameter validation, and a marketplace require sustained engineering investment.",
    description: "Cached execution plans that eliminate redundant LLM reasoning.",
    items: [
      { label: "Agentic action plan generation — LLM reasons once, plan is cached", done: false },
      { label: "Deterministic plan replay with parameter injection (zero LLM calls)", done: false },
      { label: "Cryptographic plan integrity (SHA-256 + HMAC verification)", done: false },
      { label: "Typed parameter validation with regex constraints", done: false },
      { label: "Tool scope enforcement — allowlist/denylist per plan", done: false },
      { label: "Composable sub-plans with independent caching", done: false },
      { label: "Agent workflow marketplace — pre-built cached action plans per industry", done: false },
    ],
  },
  {
    title: "Phase 6 — Scale & Federation",
    status: "planned" as const,
    icon: Globe,
    color: "text-[#ff7b72]",
    borderColor: "border-[#ff7b72]/30",
    bgColor: "bg-[#ff7b72]/5",
    fundingNote: "Federation and compliance require multi-region infrastructure, third-party audits (SOC 2, HIPAA), and Terraform module maintenance across three clouds.",
    description: "Multi-instance deployment and enterprise-grade infrastructure.",
    items: [
      { label: "Multi-instance cache federation — sync between your own BitMod deployments", done: false },
      { label: "Cross-instance cache warming — new instances inherit from existing ones", done: false },
      { label: "Fleet-wide analytics — unified dashboard across all instances", done: false },
      { label: "Cache replication protocol — efficient geo-distributed sync", done: false },
      { label: "Horizontal scaling with Redis cluster + read replicas", done: false },
      { label: "Terraform modules for AWS / GCP / Azure", done: false },
      { label: "Industry compliance bundles (HIPAA, SOC 2, GDPR, FedRAMP)", done: false },
      { label: "High-availability mode with automatic failover", done: false },
      { label: "Predictive cache warming — pattern analysis to pre-generate answers", done: false },
    ],
  },
  {
    title: "Phase 7 — BitMod Cloud",
    status: "planned" as const,
    icon: Zap,
    color: "text-primary",
    borderColor: "border-primary/30",
    bgColor: "bg-primary/5",
    fundingNote: "BitMod Cloud is the long-term sustainability model — a hosted management plane that funds open-source development indefinitely while keeping the engine free.",
    description: "Optional hosted management plane. The engine always runs on your infrastructure — BitMod Cloud provides analytics and fleet management. Think Grafana Cloud, not Grafana.",
    items: [
      { label: "bitmod.io cloud dashboard — opt-in, telemetry-free by default", done: false },
      { label: "Hosted cache analytics — hit rates, cost savings, layer performance over time", done: false },
      { label: "Fleet management — connect and monitor multiple self-hosted instances", done: false },
      { label: "Alerting — cache hit rate drops, cost anomalies, layer degradation", done: false },
      { label: "Team management — invite collaborators, shared dashboards", done: false },
      { label: "No data leaves your infrastructure — cloud sees metrics only, never queries or answers", done: false },
    ],
  },
]

function getPhaseProgress(phase: typeof phases[number]) {
  const total = phase.items.length
  const done = phase.items.filter((i) => i.done).length
  return { total, done, percent: Math.round((done / total) * 100) }
}

function StatusBadge({ status }: { status: "complete" | "in-progress" | "planned" }) {
  if (status === "complete") {
    return <Badge className="bg-green-500/10 text-green-500 border-green-500/20">Complete</Badge>
  }
  if (status === "in-progress") {
    return <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">In Progress</Badge>
  }
  return <Badge variant="outline">Planned</Badge>
}

export default function RoadmapPage() {
  // Calculate overall progress
  const allItems = phases.flatMap((p) => p.items)
  const totalDone = allItems.filter((i) => i.done).length
  const totalItems = allItems.length
  const overallPercent = Math.round((totalDone / totalItems) * 100)

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
            Roadmap
          </Badge>

          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Where BitMod
            </span>
            <br />
            <span className="text-foreground">is headed.</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Built in the open, driven by the community. Every feature below is either shipped,
            in progress, or planned — and your support determines the pace.
          </p>
        </div>
      </section>

      {/* Overall Progress */}
      <section className="mx-auto max-w-4xl px-4 pb-16 sm:px-6 lg:px-8">
        <Card className="border-border/40 bg-card/50">
          <CardContent className="py-8 px-6 sm:px-8">
            <div className="flex flex-col sm:flex-row items-center gap-6">
              <div className="flex-1 w-full">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-foreground">Overall Progress</span>
                  <span className="text-sm text-muted-foreground">{totalDone} / {totalItems} items</span>
                </div>
                <div className="w-full h-3 rounded-full bg-muted/30 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-all duration-500"
                    style={{ width: `${overallPercent}%` }}
                  />
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  {overallPercent}% complete across all {phases.length} phases
                </p>
              </div>
              <div className="grid grid-cols-3 gap-4 text-center shrink-0">
                <div>
                  <div className="text-2xl font-bold text-green-400">{phases.filter((p) => p.status === "complete").length}</div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Complete</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-yellow-400">{phases.filter((p) => p.status === "in-progress").length}</div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">In Progress</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-muted-foreground">{phases.filter((p) => p.status === "planned").length}</div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Planned</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Sponsor CTA */}
      <section className="mx-auto max-w-4xl px-4 pb-16 sm:px-6 lg:px-8">
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="flex flex-col sm:flex-row items-center gap-6 py-8 px-6 sm:px-8">
            <Heart className="h-12 w-12 text-primary shrink-0" />
            <div className="flex-1 text-center sm:text-left">
              <h2 className="text-xl font-bold">Your support determines the pace</h2>
              <p className="mt-1 text-muted-foreground">
                BitMod is free, open-source software built by a small team.
                Funding goes directly toward engineering time, infrastructure,
                security audits, and supporting more users on more platforms.
              </p>
            </div>
            <div className="flex flex-col gap-2 shrink-0">
              <Button asChild>
                <a href="https://github.com/sponsors/BitModerator" target="_blank" rel="noopener noreferrer">
                  <Heart className="mr-2 h-4 w-4" /> Sponsor on GitHub
                </a>
              </Button>
              <Button variant="outline" asChild>
                <Link href="/contact">
                  Contact Us
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>

      <Separator />

      {/* Phases */}
      <section className="mx-auto max-w-4xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="space-y-10">
          {phases.map((phase) => {
            const progress = getPhaseProgress(phase)
            const Icon = phase.icon
            return (
              <Card key={phase.title} className={`${phase.borderColor} ${phase.bgColor} overflow-hidden`}>
                <CardHeader className="pb-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className={`flex items-center justify-center h-10 w-10 rounded-lg bg-muted/20 border border-border/20 shrink-0`}>
                        <Icon className={`h-5 w-5 ${phase.color}`} />
                      </div>
                      <div>
                        <CardTitle className="text-xl">{phase.title}</CardTitle>
                        {"description" in phase && phase.description && (
                          <p className="text-sm text-muted-foreground mt-1">{phase.description}</p>
                        )}
                      </div>
                    </div>
                    <StatusBadge status={phase.status} />
                  </div>

                  {/* Progress bar */}
                  <div className="mt-4">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs text-muted-foreground">
                        {progress.done} / {progress.total} complete
                      </span>
                      <span className="text-xs font-medium text-foreground">{progress.percent}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-muted/20 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          phase.status === "complete"
                            ? "bg-green-500"
                            : phase.status === "in-progress"
                            ? "bg-yellow-500"
                            : "bg-muted-foreground/30"
                        }`}
                        style={{ width: `${progress.percent}%` }}
                      />
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-4">
                  <ul className="space-y-2">
                    {phase.items.map((item) => (
                      <li key={item.label} className="flex items-start gap-3">
                        {item.done ? (
                          <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0 mt-0.5" />
                        ) : (
                          <Circle className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />
                        )}
                        <span className={item.done ? "text-muted-foreground" : "text-foreground"}>
                          {item.label}
                        </span>
                      </li>
                    ))}
                  </ul>

                  {/* Funding note */}
                  {phase.fundingNote && (
                    <div className="mt-4 rounded-lg bg-muted/10 border border-border/20 p-4 flex items-start gap-3">
                      <DollarSign className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        <span className="font-medium text-foreground">Where funding helps: </span>
                        {phase.fundingNote}
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </section>

      <Separator />

      {/* What Funding Supports */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Impact</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Where your{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              support goes.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Every dollar goes directly toward building and maintaining BitMod.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              icon: Rocket,
              title: "Engineering Time",
              desc: "Full-time development on the cache engine, new adapters, performance optimization, and the features you see on this roadmap.",
              color: "text-primary",
            },
            {
              icon: Server,
              title: "Infrastructure",
              desc: "CI/CD pipelines, testing infrastructure, staging environments, PyPI publishing, and the hosted documentation site.",
              color: "text-[#79c0ff]",
            },
            {
              icon: Shield,
              title: "Security & Audits",
              desc: "Third-party penetration testing, dependency auditing, and the compliance certifications (SOC 2, HIPAA) our enterprise users need.",
              color: "text-[#7ee787]",
            },
            {
              icon: Users,
              title: "Community & Support",
              desc: "Documentation, tutorials, issue triage, community support channels, and helping new users get started with BitMod.",
              color: "text-[#ffa657]",
            },
            {
              icon: Database,
              title: "New Integrations",
              desc: "More database backends, vector stores, embedding providers, and messaging platform adapters — driven by what the community requests.",
              color: "text-[#d2a8ff]",
            },
            {
              icon: Globe,
              title: "Open Source Mission",
              desc: "Keeping the core engine free and open forever. No paywalls on existing features. Enterprise revenue funds open-source development, not the other way around.",
              color: "text-[#ff7b72]",
            },
          ].map((item) => (
            <Card key={item.title} className="border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
              <CardHeader className="pb-2">
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-muted/20 border border-border/20 shrink-0">
                    <item.icon className={`h-5 w-5 ${item.color}`} />
                  </div>
                  <CardTitle className="text-lg">{item.title}</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground leading-relaxed">{item.desc}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Separator />

      {/* Bottom CTA */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Help build the{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            future of BitMod
          </span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Sponsor development, open an issue, or contribute code.
          Every contribution moves the roadmap forward.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button size="xl" asChild>
            <Link href="/contact">
              Contact Us <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
          <Button size="xl" variant="outline" asChild>
            <a href="https://github.com/sponsors/BitModerator" target="_blank" rel="noopener noreferrer">
              <Heart className="mr-2 h-5 w-5" /> Sponsor on GitHub
            </a>
          </Button>
          <Button size="xl" variant="outline" asChild>
            <Link href="/docs">
              Read the Docs
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
