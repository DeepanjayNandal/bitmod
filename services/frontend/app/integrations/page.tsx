import type { Metadata } from "next"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  ArrowRight, Brain, Database, Search, Cloud, Server, Code, Terminal, ExternalLink,
  Cpu, Globe, Boxes
} from "lucide-react"

export const metadata: Metadata = {
  title: "Integrations | BitMod",
  description: "Connect BitMod to any LLM provider, 4 databases, 3 vector stores, and 4 embedding providers. Universal, zero vendor lock-in.",
}

/* ------------------------------------------------------------------ */
/*  Data                                                               */
/* ------------------------------------------------------------------ */

const LLM_PROVIDERS = [
  { name: "Anthropic",        label: "Claude",              color: "bg-orange-500" },
  { name: "OpenAI",           label: "GPT-4o",             color: "bg-green-500" },
  { name: "Google Gemini",    label: "Gemini 2.5",         color: "bg-blue-500" },
  { name: "Ollama",           label: "Local models",       color: "bg-slate-400" },
  { name: "AWS Bedrock",      label: "Managed AWS",        color: "bg-amber-500" },
  { name: "Azure OpenAI",     label: "Enterprise Azure",   color: "bg-sky-500" },
  { name: "xAI (Grok)",      label: "Grok-2",             color: "bg-neutral-400" },
  { name: "Mistral",          label: "Mixtral / Large",    color: "bg-orange-400" },
  { name: "Perplexity",       label: "Perplexity models",   color: "bg-teal-500" },
  { name: "OpenRouter",       label: "Multi-provider",     color: "bg-violet-500" },
  { name: "HuggingFace",      label: "Inference API",      color: "bg-yellow-500" },
  { name: "OpenAI-Compatible",label: "Any compatible API", color: "bg-emerald-500" },
]

const DATABASE_BACKENDS = [
  {
    name: "SQLite",
    desc: "Zero-config default. Embedded, serverless, great for dev and small deployments. No setup required.",
    icon: Database,
    border: "border-green-500/30",
    bg: "bg-green-500/5",
    dot: "bg-green-500",
  },
  {
    name: "PostgreSQL",
    desc: "Production-grade with pgvector for native vector search. Full ACID, reliable single-node performance.",
    icon: Server,
    border: "border-blue-500/30",
    bg: "bg-blue-500/5",
    dot: "bg-blue-500",
  },
  {
    name: "MySQL / MariaDB",
    desc: "Enterprise standard, widely deployed. Drop-in support for existing MySQL infrastructure.",
    icon: Database,
    border: "border-orange-500/30",
    bg: "bg-orange-500/5",
    dot: "bg-orange-500",
  },
  {
    name: "MongoDB",
    desc: "Document-oriented, flexible schema. Great for unstructured data and rapid prototyping.",
    icon: Boxes,
    border: "border-emerald-500/30",
    bg: "bg-emerald-500/5",
    dot: "bg-emerald-500",
  },
]

const VECTOR_STORES = [
  {
    name: "ChromaDB",
    desc: "Open-source embedding database. Easy setup, great for local development and small-to-medium workloads.",
    border: "border-yellow-500/30",
    bg: "bg-yellow-500/5",
    dot: "bg-yellow-500",
  },
  {
    name: "Qdrant",
    desc: "High-performance vector search engine. Production-ready with filtering, sharding, and replication.",
    border: "border-red-500/30",
    bg: "bg-red-500/5",
    dot: "bg-red-500",
  },
  {
    name: "Pinecone",
    desc: "Fully managed, cloud-native vector database. Zero ops, automatic scaling, enterprise SLAs.",
    border: "border-blue-500/30",
    bg: "bg-blue-500/5",
    dot: "bg-blue-500",
  },
]

const EMBEDDING_PROVIDERS = [
  {
    name: "Ollama",
    model: "nomic-embed-text",
    desc: "Run locally, completely free. No API keys, no network calls, full privacy.",
    tag: "Local / Free",
    border: "border-slate-400/30",
    bg: "bg-slate-400/5",
  },
  {
    name: "Sentence Transformers",
    model: "all-MiniLM-L6-v2",
    desc: "Local inference with HuggingFace models. Zero cost, fast, no external dependencies.",
    tag: "Local / Free",
    border: "border-yellow-500/30",
    bg: "bg-yellow-500/5",
  },
  {
    name: "OpenAI",
    model: "text-embedding-3-small",
    desc: "Cloud-hosted, high-quality embeddings. Best-in-class accuracy for English text.",
    tag: "Cloud",
    border: "border-green-500/30",
    bg: "bg-green-500/5",
  },
  {
    name: "Cohere",
    model: "embed-v4.0",
    desc: "Cloud-hosted embedding provider with strong multilingual support. 100+ languages out of the box.",
    tag: "Cloud / Multilingual",
    border: "border-purple-500/30",
    bg: "bg-purple-500/5",
  },
]

const DEV_TOOLS = [
  {
    name: "LM Studio",
    filename: "config.yaml",
    code: `# Point LM Studio at BitMod
api_base: "http://localhost:8000/v1"
# All local models now cache through BitMod`,
  },
  {
    name: "Continue.dev (VS Code)",
    filename: "config.json",
    code: `{
  "models": [{
    "apiBase": "http://localhost:8000/v1",
    "provider": "openai",
    "model": "claude-3-5-sonnet"
  }]
}`,
  },
  {
    name: "Open WebUI",
    filename: "docker-compose.yml",
    code: `environment:
  OPENAI_API_BASE_URL: "http://bitmod:8000/v1"
  OPENAI_API_KEY: "your-bitmod-key"`,
  },
  {
    name: "LangChain",
    filename: "app.py",
    code: `from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    model="claude-3-5-sonnet"
)`,
  },
  {
    name: "LlamaIndex",
    filename: "app.py",
    code: `from llama_index.llms.openai import OpenAI

llm = OpenAI(
    api_base="http://localhost:8000/v1",
    model="gpt-4o"
)`,
  },
  {
    name: "OpenAI SDK",
    filename: "client.py",
    code: `from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1"
)  # That's it. Caching is automatic.`,
  },
  {
    name: "Jupyter Notebook",
    filename: "notebook.ipynb",
    code: `import openai
openai.api_base = "http://localhost:8000/v1"

# Every cell's LLM call is now cached
response = openai.chat.completions.create(
    model="claude-3-5-sonnet",
    messages=[{"role": "user", "content": "..."}]
)`,
  },
  {
    name: "cURL",
    filename: "terminal",
    code: `curl http://localhost:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $BITMOD_KEY" \\
  -d '{"model":"claude-3-5-sonnet",
       "messages":[{"role":"user",
       "content":"Hello"}]}'`,
  },
]

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function IntegrationsPage() {
  return (
    <div className="relative">
      {/* Gradient background effect */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-1/4 top-1/4 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[100px]" />
      </div>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-7xl px-4 pt-20 pb-16 sm:px-6 sm:pt-28 sm:pb-24 lg:px-8">
        <div className="text-center">
          <Badge variant="accent" className="mb-6 px-4 py-1.5 text-sm">
            Integrations
          </Badge>

          <h1 className="text-5xl font-extrabold tracking-tight sm:text-7xl">
            <span className="bg-gradient-to-r from-primary via-primary to-accent bg-clip-text text-transparent">
              Works With
            </span>
            <br />
            <span className="text-foreground">Everything</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Drop-in compatibility with every major LLM provider, database, vector store,
            and developer tool. Change one URL or one env var &mdash; BitMod handles the rest.
          </p>
        </div>
      </section>

      {/* ── How integration works ──────────────────────────────── */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              One URL.{" "}
              <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                Same engine.
              </span>
            </h2>
            <p className="mt-3 text-lg text-muted-foreground">
              BitMod is a transparent proxy. Point your existing SDK at it and caching happens underneath.
            </p>
          </div>

          <div className="mx-auto max-w-2xl">
            <Card className="group relative overflow-hidden border-primary/30 bg-primary/5 hover:border-primary/50 transition-all duration-300 hover:shadow-lg">
              <CardHeader>
                <div className="flex items-center gap-3 mb-2">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <Globe className="h-5 w-5 text-primary" />
                  </div>
                  <CardTitle className="text-xl">Proxy Mode</CardTitle>
                </div>
                <CardDescription>
                  Change one URL in your existing SDK. BitMod sits between your app and the LLM, caching responses transparently.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-3 text-sm text-muted-foreground">
                  <div className="flex items-start gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />
                    <span>Zero code changes &mdash; just swap <code className="text-xs bg-muted/30 px-1 py-0.5 rounded">base_url</code></span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />
                    <span>Works with OpenAI, Anthropic, and Gemini SDK formats</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />
                    <span>Auto-detects provider from model name</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary mt-1.5 shrink-0" />
                    <span>Your API key passed through &mdash; BitMod never stores it</span>
                  </div>
                </div>
                <div className="mt-4 rounded-lg border border-border/60 bg-[#0d1117] p-3">
                  <pre className="text-[11px] font-mono text-[#e6edf3]"><code>{`client = OpenAI(
  base_url="http://localhost:8000/v1"
)  # Done. Caching is automatic.`}</code></pre>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* ── LLM Providers ────────────────────────────────────────── */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Universal LLM Support</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Any provider.{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              One URL.
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Works with any OpenAI-compatible API. 200+ providers supported. Just set a URL.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {LLM_PROVIDERS.map((p) => (
            <div
              key={p.name}
              className="arch-node group rounded-xl border border-border/40 bg-card/50 p-4 hover:border-border/80 transition-all duration-300 hover:shadow-lg"
            >
              <div className="flex items-center gap-2.5 mb-1.5">
                <div className={`h-2.5 w-2.5 rounded-full ${p.color} shrink-0`} />
                <span className="text-sm font-semibold text-foreground truncate">{p.name}</span>
              </div>
              <div className="text-xs text-muted-foreground pl-5">{p.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Database Backends ────────────────────────────────────── */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Badge variant="accent" className="mb-4">Database Backends</Badge>
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Your data, your database
            </h2>
            <p className="mt-3 text-lg text-muted-foreground">
              Same interface, same code. Swap the backend with one env var.
            </p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {DATABASE_BACKENDS.map((db) => (
              <Card
                key={db.name}
                className={`arch-node group relative overflow-hidden ${db.border} ${db.bg} hover:border-border/80 transition-all duration-300 hover:shadow-lg`}
              >
                <CardHeader>
                  <div className="flex items-center gap-3 mb-1">
                    <div className={`h-3 w-3 rounded-full ${db.dot}`} />
                    <db.icon className="h-6 w-6 text-muted-foreground" />
                  </div>
                  <CardTitle className="text-lg">{db.name}</CardTitle>
                </CardHeader>
                <CardContent>
                  <CardDescription className="text-sm leading-relaxed">
                    {db.desc}
                  </CardDescription>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* ── Vector Stores ────────────────────────────────────────── */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Vector Stores</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Dedicated vector search
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Plug in a dedicated vector store for high-volume semantic search workloads.
          </p>
        </div>

        <div className="mx-auto max-w-4xl grid gap-6 sm:grid-cols-3">
          {VECTOR_STORES.map((vs) => (
            <Card
              key={vs.name}
              className={`arch-node group relative overflow-hidden ${vs.border} ${vs.bg} hover:border-border/80 transition-all duration-300 hover:shadow-lg`}
            >
              <CardHeader>
                <div className="flex items-center gap-2 mb-1">
                  <div className={`h-3 w-3 rounded-full ${vs.dot}`} />
                  <Search className="h-5 w-5 text-muted-foreground" />
                </div>
                <CardTitle className="text-lg">{vs.name}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-sm leading-relaxed">
                  {vs.desc}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* ── Embedding Providers ──────────────────────────────────── */}
      <section className="border-y border-border/40 bg-card/20">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <Badge variant="accent" className="mb-4">Embedding Providers</Badge>
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Local or cloud.{" "}
              <span className="text-muted-foreground">Your choice.</span>
            </h2>
            <p className="mt-3 text-lg text-muted-foreground">
              Run embeddings locally for free, or use a cloud provider for maximum quality.
            </p>
          </div>

          <div className="mx-auto max-w-5xl grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {EMBEDDING_PROVIDERS.map((ep) => (
              <Card
                key={ep.name}
                className={`arch-node group relative overflow-hidden ${ep.border} ${ep.bg} hover:border-border/80 transition-all duration-300 hover:shadow-lg`}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between mb-1">
                    <Cpu className="h-5 w-5 text-muted-foreground" />
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                      {ep.tag}
                    </span>
                  </div>
                  <CardTitle className="text-base">{ep.name}</CardTitle>
                  <div className="font-mono text-xs text-muted-foreground">{ep.model}</div>
                </CardHeader>
                <CardContent>
                  <CardDescription className="text-sm leading-relaxed">
                    {ep.desc}
                  </CardDescription>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* ── Developer Tools ──────────────────────────────────────── */}
      <section id="dev-tools" className="scroll-mt-20 mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <Badge variant="accent" className="mb-4">Developer Tools &middot; Proxy Mode</Badge>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Integrate in{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              one line
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            Point your existing tools at BitMod&apos;s proxy. No SDK changes, no wrapper libraries.
            Every tool below works by setting <code className="text-xs bg-muted/30 px-1 py-0.5 rounded">base_url</code> to <code className="text-xs bg-muted/30 px-1 py-0.5 rounded">http://localhost:8000/v1</code> &mdash; there is no BitMod adapter to install, because none is needed.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {DEV_TOOLS.map((tool) => (
            <div
              key={tool.name}
              className="arch-node group rounded-xl border border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg overflow-hidden"
            >
              <div className="flex items-center gap-2 px-4 pt-4 pb-2">
                <Code className="h-4 w-4 text-primary shrink-0" />
                <span className="text-sm font-semibold text-foreground">{tool.name}</span>
              </div>
              <div className="mx-3 mb-3 rounded-lg border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
                <div className="flex items-center gap-2 border-b border-border/20 px-3 py-2">
                  <div className="flex gap-1">
                    <div className="h-2 w-2 rounded-full bg-red-500/80" />
                    <div className="h-2 w-2 rounded-full bg-yellow-500/80" />
                    <div className="h-2 w-2 rounded-full bg-green-500/80" />
                  </div>
                  <span className="text-[10px] text-muted-foreground font-mono ml-1">{tool.filename}</span>
                </div>
                <pre className="p-3 text-[11px] font-mono leading-relaxed text-[#e6edf3] overflow-x-auto">
                  <code>{tool.code}</code>
                </pre>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Final CTA ────────────────────────────────────────────── */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Ready to{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            plug in
          </span>
          ?
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          Read the docs to connect your first provider in under five minutes.
          No vendor lock-in, no SDK rewrites.
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
