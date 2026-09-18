import type { Metadata } from "next"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import Link from "next/link"
import {
  ArrowRight, Book, Terminal, Database, Brain, Shield, Wrench,
  Zap, Globe, Server, FileText, Layers, Code, Repeat, Search, Activity, MessageSquare
} from "lucide-react"
import { DocsSidebar } from "@/components/shared/docs-sidebar"

const guidesSidebarSections = [
  {
    title: "Getting Started",
    links: [
      { href: "/guides/getting-started", label: "Quick Start Guide" },
      { href: "/guides/llm-providers", label: "Configuration Guide" },
      { href: "/guides/docker", label: "Docker Deployment" },
    ],
  },
  {
    title: "References",
    links: [
      { href: "/guides/api-reference", label: "API Reference" },
      { href: "/guides/python-sdk", label: "Python SDK" },
      { href: "/guides/cache-setup", label: "Cache Configuration" },
    ],
  },
  {
    title: "Core Features",
    links: [
      { href: "/cache-engine", label: "Cache Engine Deep Dive" },
      { href: "/docs#proxy", label: "Drop-in Proxy Setup" },
      { href: "/docs#cli", label: "CLI Reference" },
    ],
  },
  {
    title: "Operations",
    links: [
      { href: "/guides/operations", label: "Operations Guide" },
      { href: "/guides/troubleshooting", label: "Troubleshooting" },
      { href: "/security", label: "Security & Auth" },
    ],
  },
  {
    title: "Integrations",
    links: [
      { href: "/integrations#dev-tools", label: "LM Studio + BitMod" },
      { href: "/integrations#dev-tools", label: "LangChain Integration" },
      { href: "/integrations#dev-tools", label: "VS Code (Continue.dev)" },
    ],
  },
]

export const metadata: Metadata = {
  title: "Guides | BitMod",
  description: "Step-by-step guides for BitMod: quick start, Docker deployment, API reference, Python SDK, provider configuration, cache optimization, and more.",
}

const sections = [
  {
    title: "Getting Started",
    description: "Everything you need to install, configure, and deploy BitMod.",
    guides: [
      {
        icon: Terminal,
        title: "Quick Start Guide",
        description: "Install BitMod and run your first query in 60 seconds.",
        difficulty: "Beginner" as const,
        time: "5 min",
        href: "/guides/getting-started",
      },
      {
        icon: FileText,
        title: "Configuration Guide",
        description: "Customize providers, models, and database backends.",
        difficulty: "Beginner" as const,
        time: "5 min",
        href: "/guides/llm-providers",
      },
      {
        icon: Server,
        title: "Docker Deployment",
        description: "Deploy BitMod with Docker Compose: profiles, networking, and production hardening.",
        difficulty: "Intermediate" as const,
        time: "10 min",
        href: "/guides/docker",
      },
    ],
  },
  {
    title: "References",
    description: "Complete reference documentation for every API, SDK method, and CLI command.",
    guides: [
      {
        icon: Book,
        title: "API Reference",
        description: "Full REST API: chat, search, ingestion, auth, namespaces, and administration endpoints.",
        difficulty: "Intermediate" as const,
        time: "20 min",
        href: "/guides/api-reference",
      },
      {
        icon: Code,
        title: "Python SDK",
        description: "Sync and async clients, cache lookups, queries, ingestion, error handling, and provider proxies.",
        difficulty: "Intermediate" as const,
        time: "10 min",
        href: "/guides/python-sdk",
      },
      {
        icon: Globe,
        title: "Cache Configuration",
        description: "Tune cache layers, set TTLs, configure namespaces, and optimize hit rates for your workload.",
        difficulty: "Beginner" as const,
        time: "10 min",
        href: "/guides/cache-setup",
      },
    ],
  },
  {
    title: "Core Features",
    description: "Deep dives into the engine that powers BitMod.",
    guides: [
      {
        icon: Layers,
        title: "Cache Engine Deep Dive",
        description: "Understand all 9 cache layers and how Bayesian evidence accumulation works.",
        difficulty: "Intermediate" as const,
        time: "15 min",
        href: "/cache-engine",
      },
      {
        icon: Search,
        title: "Drop-in Proxy Setup",
        description: "Configure BitMod as a drop-in proxy for any OpenAI-compatible SDK. One URL change, instant caching.",
        difficulty: "Beginner" as const,
        time: "2 min",
        href: "/docs#proxy",
      },
      {
        icon: Terminal,
        title: "CLI Reference",
        description: "All 17 commands: init, query, ingest, serve, proxy, cache, backup, migrate, doctor, and more.",
        difficulty: "Beginner" as const,
        time: "10 min",
        href: "/docs#cli",
      },
    ],
  },
  {
    title: "Operations",
    description: "Run BitMod in production: monitoring, backups, scaling, and maintenance.",
    guides: [
      {
        icon: Activity,
        title: "Operations Guide",
        description: "Monitoring, backups, migrations, cache management, scaling, and diagnostics.",
        difficulty: "Intermediate" as const,
        time: "15 min",
        href: "/guides/operations",
      },
      {
        icon: Wrench,
        title: "Troubleshooting",
        description: "Solutions for installation, connection, cache, configuration, Docker, and performance issues.",
        difficulty: "Beginner" as const,
        time: "10 min",
        href: "/guides/troubleshooting",
      },
      {
        icon: Shield,
        title: "Security & Auth",
        description: "API key management, JWT tokens, encryption at rest, and rate limiting.",
        difficulty: "Intermediate" as const,
        time: "10 min",
        href: "/security",
      },
    ],
  },
  {
    title: "Integrations",
    description: "Connect BitMod to your existing tools and workflows.",
    guides: [
      {
        icon: Database,
        title: "LM Studio + BitMod",
        description: "Connect your local models through BitMod for caching.",
        difficulty: "Beginner" as const,
        time: "5 min",
        href: "/integrations#dev-tools",
      },
      {
        icon: Globe,
        title: "LangChain Integration",
        description: "Add BitMod caching to your LangChain pipelines.",
        difficulty: "Intermediate" as const,
        time: "8 min",
        href: "/integrations#dev-tools",
      },
      {
        icon: Code,
        title: "VS Code (Continue.dev)",
        description: "Configure Continue.dev to use BitMod as its backend.",
        difficulty: "Beginner" as const,
        time: "3 min",
        href: "/integrations#dev-tools",
      },
    ],
  },
]

const difficultyColor = {
  Beginner: "bg-green-500/15 text-green-400 border-green-500/30",
  Intermediate: "bg-primary/15 text-primary border-primary/30",
  Advanced: "bg-accent/15 text-accent border-accent/30",
}

export default function GuidesPage() {
  return (
    <div className="relative">
      {/* Gradient background effect */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-1/4 top-1/4 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[100px]" />
      </div>

      {/* Header */}
      <section className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <Badge variant="accent" className="mb-4">Guides</Badge>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Learn BitMod
            </span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
            Step-by-step tutorials from first install to advanced customization.
            Follow along at your own pace.
          </p>
        </div>

        <div className="lg:grid lg:grid-cols-[220px_1fr] lg:gap-10">
          {/* Left sidebar */}
          <DocsSidebar sections={guidesSidebarSections} />

          {/* Main content */}
          <div className="space-y-20">
            {sections.map((section) => (
              <div key={section.title}>
                <div className="mb-8">
                  <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
                    {section.title}
                  </h2>
                  <p className="mt-2 text-muted-foreground">{section.description}</p>
                </div>

                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                  {section.guides.map((guide) => (
                    <Link key={guide.title} href={"href" in guide ? (guide.href as string) : "/docs"} className="group">
                      <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300 hover:shadow-lg">
                        <CardHeader>
                          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                            <guide.icon className="h-5 w-5 text-primary" />
                          </div>
                          <CardTitle className="flex items-center gap-2 text-lg">
                            {guide.title}
                            <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="text-sm text-muted-foreground mb-4">
                            {guide.description}
                          </p>
                          <div className="flex items-center justify-between">
                            <Badge
                              className={difficultyColor[guide.difficulty]}
                            >
                              {guide.difficulty}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {guide.time}
                            </span>
                          </div>
                        </CardContent>
                      </Card>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
