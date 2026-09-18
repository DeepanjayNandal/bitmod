import type { Metadata } from "next"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  ArrowRight, Terminal, Package, Globe, Container, Settings, Sparkles
} from "lucide-react"

export const metadata: Metadata = {
  title: "Developer Experience | BitMod",
  description: "pip install, one-line proxy config, Docker Compose deploy. BitMod is built for developers who want intelligent caching without complexity.",
}

export default function DeveloperExperiencePage() {
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
            Solutions
          </Badge>

          <h1 className="text-5xl font-extrabold tracking-tight sm:text-7xl">
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Developer Experience
            </span>
            <br />
            <span className="text-foreground">First</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            Zero-config defaults. <code className="text-accent font-mono">docker compose up</code> and you&apos;re
            running. SQLite backend, local embeddings, no server, no account, no API keys for local mode.
          </p>
        </div>
      </section>

      {/* Get Started in 3 Steps */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Get started in{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              3 steps
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            From install to cached, verified answers in under a minute.
          </p>
        </div>

        <div className="mx-auto max-w-2xl flex flex-col items-center">
          {/* Step 1 */}
          <div className="w-full rounded-xl border border-border/60 bg-[#0d1117] p-5 shadow-2xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex items-center justify-center h-7 w-7 rounded-full bg-primary/20 text-primary text-xs font-bold">1</div>
              <span className="text-sm font-semibold text-[#e6edf3]">Install</span>
            </div>
            <div className="font-mono text-sm">
              <span className="text-[#8b949e]">$</span>{" "}
              <span className="text-[#ff7b72] font-semibold">pip install</span>{" "}
              <span className="text-[#a5d6ff]">bitmod</span>
            </div>
            <div className="mt-2 text-xs text-[#8b949e]">Instant SQLite + local embeddings. No server needed.</div>
          </div>

          {/* Connector */}
          <div className="w-px h-8 bg-gradient-to-b from-primary/60 to-primary/20 animate-flow-pulse" />

          {/* Step 2 */}
          <div className="w-full rounded-xl border border-border/60 bg-[#0d1117] p-5 shadow-2xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex items-center justify-center h-7 w-7 rounded-full bg-accent/20 text-accent text-xs font-bold">2</div>
              <span className="text-sm font-semibold text-[#e6edf3]">Initialize</span>
            </div>
            <div className="font-mono text-sm">
              <span className="text-[#ff7b72] font-semibold">from</span>{" "}
              <span className="text-[#79c0ff]">bitmod.adapters</span>{" "}
              <span className="text-[#ff7b72] font-semibold">import</span>{" "}
              <span className="text-[#d2a8ff]">get_backend</span>{"\n"}
              <span className="text-[#e6edf3]">backend</span>{" "}
              <span className="text-[#ff7b72]">=</span>{" "}
              <span className="text-[#d2a8ff]">get_backend</span>()
            </div>
            <div className="mt-2 text-xs text-[#8b949e]">One function call. Auto-detects config from env vars.</div>
          </div>

          {/* Connector */}
          <div className="w-px h-8 bg-gradient-to-b from-accent/60 to-accent/20 animate-flow-pulse" style={{ animationDelay: "0.3s" }} />

          {/* Step 3 */}
          <div className="w-full rounded-xl border border-border/60 bg-[#0d1117] p-5 shadow-2xl">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex items-center justify-center h-7 w-7 rounded-full bg-green-500/20 text-green-400 text-xs font-bold">3</div>
              <span className="text-sm font-semibold text-[#e6edf3]">Query</span>
            </div>
            <div className="font-mono text-sm">
              <span className="text-[#e6edf3]">result</span>{" "}
              <span className="text-[#ff7b72]">=</span>{" "}
              <span className="text-[#e6edf3]">llm</span>.<span className="text-[#d2a8ff]">query</span>(<span className="text-[#a5d6ff]">&quot;What is BitMod?&quot;</span>)
            </div>
            <div className="mt-2 text-xs text-[#7ee787]">Auto-caching, verified, cited. First call generates, second call is instant.</div>
          </div>

          {/* Final connector */}
          <div className="w-px h-8 bg-gradient-to-b from-green-400/40 to-green-400/20 animate-flow-pulse" style={{ animationDelay: "0.6s" }} />

          <div className="inline-flex items-center gap-2 rounded-lg bg-green-500/10 border border-green-500/20 px-5 py-2.5 text-green-400 font-semibold text-sm arch-node">
            <Sparkles className="h-4 w-4" />
            Cached, verified, cited
          </div>
        </div>
      </section>

      {/* DX Feature Cards */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Built for developers who{" "}
            <span className="text-muted-foreground">ship fast</span>
          </h2>
        </div>

        <div className="grid gap-6 sm:grid-cols-2">
          <Card className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardHeader>
              <Settings className="h-10 w-10 text-yellow-500 mb-2" />
              <CardTitle className="text-lg">Zero Config</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                SQLite by default. No server to run, no account to create, no API keys needed for local mode.
                Everything works out of the box. Scale up later by setting env vars.
              </CardDescription>
            </CardContent>
          </Card>

          <Card className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardHeader>
              <Terminal className="h-10 w-10 text-primary mb-2" />
              <CardTitle className="text-lg">CLI Toolkit</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                <code className="text-accent">bitmod init</code> scaffolds your project.{" "}
                <code className="text-accent">bitmod serve</code> starts the gateway.{" "}
                <code className="text-accent">bitmod ingest</code> loads documents.{" "}
                <code className="text-accent">bitmod status</code> shows cache and system health.
              </CardDescription>
            </CardContent>
          </Card>

          <Card className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardHeader>
              <Globe className="h-10 w-10 text-accent mb-2" />
              <CardTitle className="text-lg">Drop-in Proxy</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                Change one URL in any SDK &mdash; OpenAI, Anthropic, Gemini &mdash; and get intelligent caching
                for free. Works with LM Studio, Continue.dev, LangChain, and Open WebUI.
              </CardDescription>
            </CardContent>
          </Card>

          <Card className="group relative overflow-hidden border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
            <CardHeader>
              <Container className="h-10 w-10 text-cyan-500 mb-2" />
              <CardTitle className="text-lg">Docker Ready</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-sm leading-relaxed">
                <code className="text-accent">docker compose up</code> for production. Gateway, chat service,
                and frontend come pre-configured. Add PostgreSQL and Redis via optional Compose profiles.
              </CardDescription>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* CLI Workflow Code Block */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            The full{" "}
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              CLI workflow
            </span>
          </h2>
          <p className="mt-3 text-lg text-muted-foreground">
            From zero to production in four commands.
          </p>
        </div>

        <div className="mx-auto max-w-3xl">
          <div className="rounded-xl border border-border/60 bg-[#0d1117] overflow-hidden shadow-2xl">
            <div className="flex items-center gap-2 border-b border-border/20 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <span className="text-xs text-muted-foreground ml-2 font-mono">terminal</span>
            </div>
            <pre className="p-6 text-sm font-mono leading-relaxed overflow-x-auto">
              <code>
                <span className="text-[#8b949e] italic"># Install</span>{"\n"}
                <span className="text-[#8b949e]">$</span> <span className="text-[#ff7b72] font-semibold">pip install</span> <span className="text-[#a5d6ff]">bitmod[recommended]</span>{"\n"}
                {"\n"}
                <span className="text-[#8b949e] italic"># Initialize configuration</span>{"\n"}
                <span className="text-[#8b949e]">$</span> <span className="text-[#ff7b72] font-semibold">bitmod init</span> <span className="text-[#a5d6ff]">--auto</span>{"\n"}
                <span className="text-[#7ee787]">Initialized BitMod with default config</span>{"\n"}
                {"\n"}
                <span className="text-[#8b949e] italic"># Ingest your documents</span>{"\n"}
                <span className="text-[#8b949e]">$</span> <span className="text-[#ff7b72] font-semibold">bitmod ingest</span> <span className="text-[#a5d6ff]">./docs/</span>{"\n"}
                <span className="text-[#7ee787]">Ingested 47 files (PDF, DOCX, MD)</span>{"\n"}
                <span className="text-[#7ee787]">Generated 1,284 chunks with embeddings</span>{"\n"}
                {"\n"}
                <span className="text-[#8b949e] italic"># Start the gateway</span>{"\n"}
                <span className="text-[#8b949e]">$</span> <span className="text-[#ff7b72] font-semibold">bitmod serve</span>{"\n"}
                <span className="text-[#7ee787]">Gateway running on http://localhost:8000</span>{"\n"}
                <span className="text-[#7ee787]">API ready at http://localhost:8000/v1/chat</span>{"\n"}
                {"\n"}
                <span className="text-[#8b949e] italic"># Check system status</span>{"\n"}
                <span className="text-[#8b949e]">$</span> <span className="text-[#ff7b72] font-semibold">bitmod status</span>{"\n"}
                <span className="text-[#e6edf3]">Backend:    </span><span className="text-[#7ee787]">SQLite (local)</span>{"\n"}
                <span className="text-[#e6edf3]">LLM:        </span><span className="text-[#7ee787]">Anthropic (Claude)</span>{"\n"}
                <span className="text-[#e6edf3]">Cache hits:  </span><span className="text-[#79c0ff]">847 / 912 (92.9%)</span>{"\n"}
                <span className="text-[#e6edf3]">Documents:  </span><span className="text-[#79c0ff]">47 files, 1,284 chunks</span>
              </code>
            </pre>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8 text-center">
        <h2 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Start building{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            in seconds
          </span>
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">
          No config. No boilerplate. Just install and go.
        </p>

        <div className="mx-auto mt-8 max-w-md">
          <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-card/50 px-4 py-3 font-mono text-sm backdrop-blur-sm">
            <Terminal className="h-4 w-4 text-muted-foreground shrink-0" />
            <code className="flex-1 text-left">
              <span className="text-accent">pip install</span>{" "}
              <span className="text-foreground font-semibold">bitmod</span>
            </code>
          </div>
        </div>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
          <Button size="xl" asChild>
            <Link href="/docs">
              Read the Docs <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
