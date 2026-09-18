"use client"

import { useState, useEffect } from "react"
import Image from "next/image"
import {
  Database,
  Brain,
  Cloud,
  Server,
  Box,
  Cpu,
  Search,
  Layers,
} from "lucide-react"

interface TickerItem {
  name: string
  icon?: React.ComponentType<{ className?: string }>
  logo?: string
}

const allProviders: TickerItem[] = [
  // LLM Providers
  { name: "Anthropic", icon: Brain, logo: "/logos/anthropic.svg" },
  { name: "OpenAI", icon: Brain, logo: "/logos/openai.svg" },
  { name: "Google Gemini", icon: Brain, logo: "/logos/google.svg" },
  { name: "Ollama", icon: Box, logo: "/logos/ollama.svg" },
  { name: "xAI / Grok", icon: Brain, logo: "/logos/xai.svg" },
  { name: "Mistral", icon: Brain, logo: "/logos/mistral.svg" },
  { name: "Perplexity", icon: Search, logo: "/logos/perplexity.svg" },
  { name: "AWS Bedrock", icon: Cloud, logo: "/logos/aws.svg" },
  { name: "Azure OpenAI", icon: Cloud, logo: "/logos/azure.svg" },
  { name: "HuggingFace", icon: Cpu, logo: "/logos/huggingface.svg" },
  { name: "OpenRouter", icon: Server, logo: "/logos/openrouter.svg" },
  // Databases & Vector Stores
  { name: "PostgreSQL", icon: Database, logo: "/logos/postgresql.svg" },
  { name: "MySQL", icon: Database, logo: "/logos/mysql.svg" },
  { name: "MongoDB", icon: Database, logo: "/logos/mongodb.svg" },
  { name: "SQLite", icon: Database, logo: "/logos/sqlite.svg" },
  { name: "ChromaDB", icon: Database, logo: "/logos/chromadb.svg" },
  { name: "Qdrant", icon: Database, logo: "/logos/qdrant.svg" },
  { name: "Pinecone", icon: Database, logo: "/logos/pinecone.svg" },
  { name: "Redis", icon: Database, logo: "/logos/redis.svg" },
  // Integrations
  { name: "LangChain", icon: Layers, logo: "/logos/langchain.svg" },
  { name: "LlamaIndex", icon: Layers, logo: "/logos/llamaindex.svg" },
  { name: "VS Code", icon: Cpu, logo: "/logos/vscode.svg" },
  { name: "LM Studio", icon: Box, logo: "/logos/lmstudio.svg" },
  { name: "Open WebUI", icon: Server, logo: "/logos/openwebui.svg" },
]

function TickerItemView({ item }: { item: TickerItem }) {
  const Icon = item.icon
  return (
    <div className="inline-flex items-center gap-3 px-6 py-3 text-muted-foreground/60 shrink-0">
      {item.logo ? (
        <Image
          src={item.logo}
          alt={item.name}
          width={24}
          height={24}
          className="h-6 w-6 opacity-60"
        />
      ) : (
        Icon && <Icon className="h-6 w-6" />
      )}
      <span className="text-base font-medium tracking-wide">{item.name}</span>
    </div>
  )
}

export function BrandTicker() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)")
    setPrefersReducedMotion(mql.matches)
    const handler = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches)
    mql.addEventListener("change", handler)
    return () => mql.removeEventListener("change", handler)
  }, [])

  return (
    <section className="border-y border-border/40 bg-card/20 py-12" aria-label="Supported integrations">
      <div className="text-center mb-8">
        <p className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
          Works with everything you already use
        </p>
      </div>

      <div className="overflow-hidden relative">
        {/* Fade edges */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-background to-transparent z-10" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-background to-transparent z-10" />

        <div
          className="flex whitespace-nowrap"
          style={{
            animation: prefersReducedMotion ? "none" : "ticker-scroll 60s linear infinite",
            width: "max-content",
          }}
        >
          {prefersReducedMotion ? (
            <div className="flex shrink-0">
              {allProviders.map((item) => (
                <TickerItemView key={item.name} item={item} />
              ))}
            </div>
          ) : (
            [0, 1].map((copy) => (
              <div key={copy} className="flex shrink-0">
                {allProviders.map((item) => (
                  <TickerItemView key={`${copy}-${item.name}`} item={item} />
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      <style jsx>{`
        @keyframes ticker-scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </section>
  )
}
