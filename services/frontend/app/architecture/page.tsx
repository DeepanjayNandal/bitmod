import type { Metadata } from "next"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import {
  ArrowRight, ArrowDown, Database, Brain, Server, Globe, Shield,
  Layers, Zap, FileText, Search, Package, Cpu, HardDrive, Lock, Cloud, Box, Terminal
} from "lucide-react"

export const metadata: Metadata = {
  title: "Architecture — Where BitMod Fits | BitMod",
  description: "See exactly where BitMod sits in your AI application stack. Architecture diagrams for individual developers, startups, and enterprise deployments.",
}

function StackLayer({ label, items, color, accent, description, highlight }: {
  label: string
  items: string[]
  color: string
  accent: string
  description: string
  highlight?: boolean
}) {
  return (
    <div className={`relative rounded-xl border ${highlight ? "border-primary/60 ring-1 ring-primary/30 bg-primary/5" : "border-border/40 bg-card/50"} p-5 transition-all`}>
      {highlight && (
        <Badge variant="accent" className="absolute -top-3 left-4 text-xs">This is BitMod</Badge>
      )}
      <div className="flex items-start gap-4">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${color}`}>
          <span className="text-lg font-bold">{label.charAt(0)}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className={`font-semibold ${accent}`}>{label}</h3>
          </div>
          <p className="text-sm text-muted-foreground mb-3">{description}</p>
          <div className="flex flex-wrap gap-2">
            {items.map((item) => (
              <span key={item} className="inline-flex items-center rounded-md border border-border/40 bg-background/50 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                {item}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function ArrowConnector() {
  return (
    <div className="flex justify-center py-1">
      <ArrowDown className="h-5 w-5 text-muted-foreground/40" />
    </div>
  )
}

export default function ArchitecturePage() {
  return (
    <div className="relative">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[500px] w-[500px] rounded-full bg-primary/8 blur-[120px]" />
      </div>

      {/* Header */}
      <section className="mx-auto max-w-5xl px-4 pt-20 pb-12 sm:px-6 lg:px-8">
        <div className="text-center">
          <Badge variant="secondary" className="mb-4">Architecture</Badge>
          <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
            Where BitMod fits in{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              your stack
            </span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
            BitMod is an intelligent caching layer that sits between your application and your LLM provider.
            It intercepts requests, serves cached answers when possible, and only forwards to the LLM when necessary.
          </p>
        </div>
      </section>

      {/* Full Stack Diagram */}
      <section className="mx-auto max-w-4xl px-4 pb-16 sm:px-6 lg:px-8">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">The AI Application Stack</h2>
          <p className="mt-2 text-muted-foreground">A typical production AI deployment, top to bottom</p>
        </div>

        <div className="space-y-1">
          <StackLayer
            label="Application"
            color="bg-blue-500/10 text-blue-400"
            accent="text-blue-400"
            description="Your product — the code your users interact with. Web app, API, chatbot, agent, or internal tool."
            items={["Next.js", "FastAPI", "Django", "Express", "Slack Bot", "Discord Bot", "CLI Tool", "Mobile App"]}
          />
          <ArrowConnector />
          <StackLayer
            label="LLM SDK"
            color="bg-purple-500/10 text-purple-400"
            accent="text-purple-400"
            description="The client library you use to call LLMs. OpenAI SDK, Anthropic SDK, or any OpenAI-compatible client."
            items={["openai Python/JS", "anthropic Python/JS", "google-generativeai", "LangChain", "LlamaIndex", "Custom HTTP"]}
          />
          <ArrowConnector />
          <StackLayer
            label="BitMod — Intelligent Cache Layer"
            color="bg-primary/10 text-primary"
            accent="text-primary"
            description="Drop-in proxy + 9-layer cache engine. Intercepts every LLM request. Cache hits are served in 68-82ms over HTTP without touching the LLM — the cache lookup itself is under 1ms, the rest is the HTTP stack. Misses pass through transparently. Your SDK doesn't know it's there."
            items={[
              "9-Layer Cache Pipeline",
              "Multi-Format Proxy",
              "Semantic Matching",
              "Composable Decomposition",
              "Source Verification",
              "Document Ingestion",
              "Embedding Engine",
              "Usage Analytics",
            ]}
            highlight
          />
          <ArrowConnector />
          <StackLayer
            label="LLM Provider"
            color="bg-orange-500/10 text-orange-400"
            accent="text-orange-400"
            description="The AI model that generates responses. BitMod only forwards cache misses — everything else is served locally."
            items={["OpenAI", "Anthropic", "Google Gemini", "Ollama (local)", "AWS Bedrock", "Azure OpenAI", "xAI", "Mistral", "Any OpenAI-compatible, via universal adapter"]}
          />
          <ArrowConnector />
          <StackLayer
            label="Data Layer"
            color="bg-cyan-500/10 text-cyan-400"
            accent="text-cyan-400"
            description="Where BitMod stores its cache, embeddings, and ingested documents. Use whatever you already run."
            items={["SQLite (default)", "PostgreSQL", "MySQL", "MongoDB", "ChromaDB", "Qdrant", "Pinecone", "Redis"]}
          />
        </div>
      </section>

      {/* What BitMod Replaces vs Complements */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">BitMod doesn&apos;t replace your tools. It makes them cheaper.</h2>
            <p className="mt-2 text-muted-foreground">BitMod is complementary to everything in your stack</p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            <Card className="border-border/40 bg-card/50">
              <CardHeader>
                <CardTitle className="text-lg text-green-400 flex items-center gap-2">
                  <Zap className="h-5 w-5" /> Works alongside
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  <span className="font-medium text-foreground">Provider prompt caching</span>
                  <span className="text-muted-foreground"> — Anthropic and OpenAI cache your prompt prefix to reduce input token costs. BitMod eliminates the call entirely for repeated questions. Use both for maximum savings.</span>
                </div>
                <div>
                  <span className="font-medium text-foreground">LangChain / LlamaIndex</span>
                  <span className="text-muted-foreground"> — BitMod sits behind these frameworks. They orchestrate chains; BitMod caches the LLM calls within them.</span>
                </div>
                <div>
                  <span className="font-medium text-foreground">Vector databases</span>
                  <span className="text-muted-foreground"> — BitMod uses vector stores (Chroma, Qdrant, Pinecone) for semantic search. It doesn&apos;t replace them — it leverages them.</span>
                </div>
                <div>
                  <span className="font-medium text-foreground">API gateways</span>
                  <span className="text-muted-foreground"> — BitMod can sit behind Kong, Nginx, or your existing gateway. It handles LLM-specific caching; your gateway handles auth and routing.</span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/40 bg-card/50">
              <CardHeader>
                <CardTitle className="text-lg text-primary flex items-center gap-2">
                  <Shield className="h-5 w-5" /> What BitMod provides
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  <span className="font-medium text-foreground">Intelligent caching</span>
                  <span className="text-muted-foreground"> — Not just exact string matching. Semantic similarity, fuzzy matching, composable decomposition, and temporal awareness across 9 layers.</span>
                </div>
                <div>
                  <span className="font-medium text-foreground">Multi-format proxy</span>
                  <span className="text-muted-foreground"> — OpenAI, Anthropic, Gemini, and Ollama formats all supported. Change one line in your SDK config.</span>
                </div>
                <div>
                  <span className="font-medium text-foreground">Document ingestion</span>
                  <span className="text-muted-foreground"> — PDF, DOCX, HTML, Markdown, CSV, JSON. Auto-chunk, auto-embed, auto-tag. Feed it your knowledge base.</span>
                </div>
                <div>
                  <span className="font-medium text-foreground">Cost analytics</span>
                  <span className="text-muted-foreground"> — Track tokens saved, cache hit rates, and estimated cost reduction per query, per day, per namespace.</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Deployment Patterns */}
      <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="text-center mb-10">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Deployment Patterns</h2>
          <p className="mt-2 text-muted-foreground">BitMod scales from a single pip install to multi-region enterprise</p>
        </div>

        <div className="grid gap-8 lg:grid-cols-3">
          {/* Solo / Prototype */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader>
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="h-5 w-5 text-green-400" />
                <Badge variant="outline" className="text-xs">Individual Developer</Badge>
              </div>
              <CardTitle className="text-lg">Local Development</CardTitle>
              <CardDescription>Prototype or personal project</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg bg-[#0d1117] p-4 font-mono text-xs mb-4 space-y-1">
                <div><span className="text-[#7ee787]">pip install</span> bitmod</div>
                <div><span className="text-[#7ee787]">bitmod init</span> --auto</div>
                <div><span className="text-[#7ee787]">bitmod serve</span></div>
              </div>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> SQLite — zero config</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Local embeddings (CPU)</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Any LLM (Ollama for free)</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Single process, no dependencies</li>
              </ul>
            </CardContent>
          </Card>

          {/* Startup */}
          <Card className="border-primary/40 bg-card/50 ring-1 ring-primary/20">
            <CardHeader>
              <div className="flex items-center gap-2 mb-2">
                <Server className="h-5 w-5 text-primary" />
                <Badge variant="accent" className="text-xs">Startup / Team</Badge>
              </div>
              <CardTitle className="text-lg">Docker Compose</CardTitle>
              <CardDescription>Production-ready in minutes</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg bg-[#0d1117] p-4 font-mono text-xs mb-4 space-y-1">
                <div><span className="text-[#7ee787]">git clone</span> bitmod && cd bitmod</div>
                <div><span className="text-[#7ee787]">cp</span> .env.example .env</div>
                <div><span className="text-[#7ee787]">docker compose</span> up -d</div>
              </div>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> PostgreSQL for durability</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Redis for session cache</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Gateway + chat service</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> API keys + rate limiting</li>
              </ul>
            </CardContent>
          </Card>

          {/* Enterprise */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader>
              <div className="flex items-center gap-2 mb-2">
                <Globe className="h-5 w-5 text-accent" />
                <Badge variant="outline" className="text-xs">Enterprise</Badge>
              </div>
              <CardTitle className="text-lg">Cloud / On-Prem</CardTitle>
              <CardDescription>Multi-team, multi-region</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg bg-[#0d1117] p-4 font-mono text-xs mb-4 space-y-1">
                <div className="text-[#8b949e]"># Your existing infra +</div>
                <div><span className="text-[#7ee787]">docker compose</span> --profile full up</div>
                <div className="text-[#8b949e]"># or deploy to Kubernetes</div>
              </div>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Namespace isolation per team</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Qdrant/Pinecone for scale</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> JWT auth + key rotation</li>
                <li className="flex items-start gap-2"><Zap className="h-4 w-4 text-primary mt-0.5 shrink-0" /> Prometheus + OpenTelemetry</li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Enterprise Stack Breakdown */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Enterprise Stack Breakdown</h2>
            <p className="mt-2 text-muted-foreground">How BitMod integrates into a full enterprise AI platform</p>
          </div>

          <div className="rounded-xl border border-border/60 bg-[#0d1117] p-6 sm:p-8 font-mono text-sm shadow-2xl overflow-x-auto">
            <div className="min-w-[600px]">
              {/* Row 1: Users */}
              <div className="text-center mb-4">
                <span className="text-[#8b949e]">{"─── Users & Applications ───"}</span>
              </div>
              <div className="flex justify-center gap-3 mb-4">
                {["Web App", "Mobile", "Slack Bot", "Internal API", "Agents"].map((item) => (
                  <span key={item} className="rounded border border-[#30363d] bg-[#161b22] px-3 py-1.5 text-xs text-[#e6edf3]">{item}</span>
                ))}
              </div>

              <div className="text-center text-[#30363d] mb-4">{"│"}</div>

              {/* Row 2: API Gateway */}
              <div className="flex justify-center mb-4">
                <span className="rounded border border-[#30363d] bg-[#161b22] px-4 py-2 text-xs text-[#8b949e]">
                  API Gateway / Load Balancer <span className="text-[#484f58]">(Kong, Nginx, AWS ALB)</span>
                </span>
              </div>

              <div className="text-center text-[#30363d] mb-4">{"│"}</div>

              {/* Row 3: BitMod */}
              <div className="flex justify-center mb-4">
                <div className="rounded-lg border-2 border-primary/50 bg-primary/5 px-6 py-3 text-center">
                  <div className="text-primary font-bold text-base mb-1">BitMod</div>
                  <div className="text-[#8b949e] text-xs space-y-0.5">
                    <div>Multi-format proxy (OpenAI / Anthropic / Gemini / Ollama)</div>
                    <div>9-layer intelligent cache engine</div>
                    <div>Document ingestion + semantic search</div>
                    <div>API key auth + rate limiting + usage analytics</div>
                  </div>
                </div>
              </div>

              {/* Arrows out from BitMod */}
              <div className="flex justify-center gap-16 text-[#30363d] mb-4">
                <span>{"│"}</span>
                <span>{"│"}</span>
                <span>{"│"}</span>
              </div>

              {/* Row 4: Downstream */}
              <div className="grid grid-cols-3 gap-4 mb-4">
                <div className="rounded border border-[#30363d] bg-[#161b22] p-3 text-center">
                  <div className="text-[#ffa657] font-semibold text-xs mb-1">LLM Providers</div>
                  <div className="text-[#8b949e] text-xs space-y-0.5">
                    <div>OpenAI / Anthropic</div>
                    <div>Ollama / vLLM (self-hosted)</div>
                    <div>Bedrock / Azure / OpenAI-compat</div>
                  </div>
                </div>
                <div className="rounded border border-[#30363d] bg-[#161b22] p-3 text-center">
                  <div className="text-[#79c0ff] font-semibold text-xs mb-1">Database</div>
                  <div className="text-[#8b949e] text-xs space-y-0.5">
                    <div>PostgreSQL / MySQL</div>
                    <div>MongoDB / SQLite</div>
                    <div>Redis (session cache)</div>
                  </div>
                </div>
                <div className="rounded border border-[#30363d] bg-[#161b22] p-3 text-center">
                  <div className="text-[#d2a8ff] font-semibold text-xs mb-1">Vector Store</div>
                  <div className="text-[#8b949e] text-xs space-y-0.5">
                    <div>ChromaDB (local)</div>
                    <div>Qdrant (self-hosted)</div>
                    <div>Pinecone (managed)</div>
                  </div>
                </div>
              </div>

              {/* Row 5: Observability */}
              <div className="text-center text-[#30363d] mb-4">{"─── Observability ───"}</div>
              <div className="flex justify-center gap-3">
                {["Prometheus", "OpenTelemetry", "Structured Logs", "Usage Dashboard"].map((item) => (
                  <span key={item} className="rounded border border-[#30363d] bg-[#161b22] px-3 py-1.5 text-xs text-[#8b949e]">{item}</span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Request Flow */}
      <section className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="text-center mb-10">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Request Flow</h2>
          <p className="mt-2 text-muted-foreground">What happens when a request hits BitMod</p>
        </div>

        <div className="space-y-4">
          {[
            {
              step: "1",
              title: "Request arrives",
              detail: "Your app sends a standard OpenAI/Anthropic/Gemini API call to BitMod's proxy endpoint instead of directly to the provider.",
              color: "text-blue-400",
              bg: "bg-blue-500/10",
            },
            {
              step: "2",
              title: "9-layer cache check",
              detail: "BitMod normalizes the query, checks exact match (SHA-256), validates sources, checks TTL, then tries fuzzy, semantic, and composable matching. Each layer accumulates evidence.",
              color: "text-primary",
              bg: "bg-primary/10",
            },
            {
              step: "3a",
              title: "Cache hit — serve immediately",
              detail: "If confidence exceeds the threshold, the cached answer is returned in 68-82ms over HTTP; the lookup itself is 0.2ms. Response headers show X-Bitmod-Cache-Hit: true and the estimated savings.",
              color: "text-green-400",
              bg: "bg-green-500/10",
            },
            {
              step: "3b",
              title: "Partial hit — composable decomposition",
              detail: "For complex queries, BitMod may answer parts from cache and only call the LLM for the missing pieces. Sub-queries are resolved independently, then reassembled into a complete response. You pay only for what the cache couldn't cover.",
              color: "text-yellow-400",
              bg: "bg-yellow-500/10",
            },
            {
              step: "3c",
              title: "Cache miss — forward to LLM",
              detail: "No cache layers matched. The full request passes through to your configured LLM provider. The response is cached for future queries, with source hashes locked for verification.",
              color: "text-orange-400",
              bg: "bg-orange-500/10",
            },
            {
              step: "4",
              title: "Response returned",
              detail: "Your app receives a standard API response — same format as if it came directly from the provider. No code changes needed beyond the base_url.",
              color: "text-purple-400",
              bg: "bg-purple-500/10",
            },
          ].map((item) => (
            <div key={item.step} className="flex items-start gap-4 rounded-xl border border-border/40 bg-card/50 p-5">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${item.bg}`}>
                <span className={`font-bold ${item.color}`}>{item.step}</span>
              </div>
              <div>
                <h3 className={`font-semibold ${item.color}`}>{item.title}</h3>
                <p className="text-sm text-muted-foreground mt-1">{item.detail}</p>
              </div>
            </div>
          ))}
        </div>

        <p className="mx-auto mt-8 max-w-3xl text-center text-xs text-muted-foreground">
          Latency figures measured over HTTP through the gateway, n=10, against self-hosted
          ollama/llama3.1:8b &mdash;{" "}
          <a
            href="https://github.com/DeepanjayNandal/bitmod/blob/main/tests/benchmark/results/latency_http_llama31_8b.json"
            className="text-primary hover:underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            latency_http_llama31_8b.json
          </a>
          . Semantic retrieval is scoped to the conversation that wrote the entry, so a follow-up in
          one conversation cannot be answered from another&apos;s cached reply.
        </p>
      </section>

      {/* Modules Breakdown */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Module Breakdown</h2>
            <p className="mt-2 text-muted-foreground">Every component of BitMod and what it connects to</p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                icon: Layers,
                title: "Cache Engine",
                count: "9 layers",
                items: ["Normalization", "Exact Match", "Source Verification", "Semantic Similarity", "Composable Decomposition", "Fuzzy Match", "Similarity Links", "Atomic Facts", "Session Context"],
                color: "text-primary",
              },
              {
                icon: Brain,
                title: "LLM Adapters",
                count: "12 adapters",
                items: ["Anthropic", "OpenAI", "Ollama", "Gemini", "AWS Bedrock", "Azure OpenAI", "xAI", "Mistral", "Perplexity", "OpenRouter", "HuggingFace", "Universal (OpenAI-compatible)"],
                color: "text-blue-400",
              },
              {
                icon: Database,
                title: "Database Backends",
                count: "4 backends",
                items: ["SQLite (default)", "PostgreSQL + pgvector", "MySQL + FULLTEXT", "MongoDB"],
                color: "text-cyan-400",
              },
              {
                icon: Search,
                title: "Embedding Providers",
                count: "4 providers",
                items: ["Local (sentence-transformers)", "OpenAI Embeddings", "Cohere Embed", "Ollama Embeddings"],
                color: "text-green-400",
              },
              {
                icon: HardDrive,
                title: "Vector Stores",
                count: "3 stores",
                items: ["ChromaDB (local file)", "Qdrant (self-hosted/cloud)", "Pinecone (managed cloud)"],
                color: "text-purple-400",
              },
              {
                icon: FileText,
                title: "Document Ingestion",
                count: "7 formats",
                items: ["PDF", "DOCX", "HTML", "Markdown", "CSV", "JSON", "Plain Text"],
                color: "text-orange-400",
              },
              {
                icon: Shield,
                title: "Security",
                count: "Built-in",
                items: ["AES-256-GCM encryption", "RS256 JWT auth", "API key management", "Token revocation", "Rate limiting", "CORS"],
                color: "text-red-400",
              },
              {
                icon: Globe,
                title: "Proxy Formats",
                count: "4 formats",
                items: ["OpenAI (/v1/chat/completions)", "Anthropic (/v1/messages)", "Gemini (/v1beta/.../generateContent)", "Ollama (/api/chat)"],
                color: "text-yellow-400",
              },
            ].map((module) => (
              <Card key={module.title} className="border-border/40 bg-card/50">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <module.icon className={`h-5 w-5 ${module.color}`} />
                    <CardTitle className="text-base">{module.title}</CardTitle>
                  </div>
                  <Badge variant="outline" className="w-fit text-xs">{module.count}</Badge>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {module.items.map((item) => (
                      <span key={item} className="text-xs text-muted-foreground bg-background/50 border border-border/30 rounded px-2 py-0.5">
                        {item}
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8 text-center">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Ready to add BitMod to your stack?
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Two lines of code. Zero vendor lock-in. Start saving on LLM costs today.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button size="xl" asChild>
            <Link href="/guides/getting-started">
              Get Started <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
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
