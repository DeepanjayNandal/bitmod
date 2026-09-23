import type { Metadata } from "next"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { CodeBlock } from "@/components/shared/code-block"
import { ArrowRight, Clock, Database, Layers, Zap } from "lucide-react"

export const metadata: Metadata = {
  title: "Connecting Your LLM Provider | Guides | BitMod",
  description: "Configure Anthropic, OpenAI, Ollama, and other LLM providers with BitMod in minutes.",
}

export default function LLMProvidersGuide() {
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
            Connecting Your LLM Provider
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            BitMod ships with 11 native LLM adapters plus 1 universal OpenAI-compatible adapter (12 total), so any provider speaking the OpenAI API works. Just set a provider and go.
          </p>
        </div>

        <div className="space-y-12">
          {/* Overview */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Supported Providers</h2>
            <p className="text-muted-foreground mb-4">
              Set your provider via environment variables or in <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod.yaml</code> (flat keys, not nested).
              BitMod uses a single LLM provider at a time, configured via <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_LLM_PROVIDER</code>. The gateway proxy supports routing by API format (OpenAI, Anthropic, Gemini endpoints).
            </p>
            <p className="text-sm text-muted-foreground mb-2">
              <strong className="text-foreground">11 native adapters:</strong> Anthropic, OpenAI, Ollama, Gemini, Bedrock, Azure OpenAI, xAI, Mistral, Perplexity, OpenRouter, HuggingFace.
              <br />
              <strong className="text-foreground">Universal adapter:</strong> Any OpenAI-compatible API (Groq, Together, vLLM, LM Studio, Jan.ai, etc.) via <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">llm_openai_compat.py</code>.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[
                "OpenAI", "Anthropic", "Google Gemini", "Ollama",
                "Mistral", "Bedrock", "Azure OpenAI", "xAI",
                "Perplexity", "OpenRouter", "HuggingFace", "OpenAI-Compatible",
              ].map((provider) => (
                <Card key={provider} className="border-border/40 bg-card/50">
                  <CardContent className="p-3 text-center">
                    <p className="text-sm font-medium">{provider}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>

          {/* OpenAI */}
          <section>
            <h2 className="text-xl font-semibold mb-4">OpenAI</h2>
            <p className="text-muted-foreground mb-4">
              Set your API key and optionally specify a default model:
            </p>
            <CodeBlock filename=".env">
{`BITMOD_LLM_PROVIDER=openai
BITMOD_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-proj-...`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3 mb-4">Or configure in YAML (flat keys):</p>
            <CodeBlock filename="bitmod.yaml">
{`llm_provider: openai
llm_model: gpt-4o-mini
# API key set via OPENAI_API_KEY env var`}
            </CodeBlock>
          </section>

          {/* Anthropic */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Anthropic</h2>
            <p className="text-muted-foreground mb-4">
              BitMod translates requests to Anthropic's Messages API format automatically:
            </p>
            <CodeBlock filename=".env">
{`BITMOD_LLM_PROVIDER=anthropic
BITMOD_LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...`}
            </CodeBlock>
            <CodeBlock filename="bitmod.yaml">
{`llm_provider: anthropic
llm_model: claude-sonnet-4-20250514
# API key set via ANTHROPIC_API_KEY env var`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              You can still use OpenAI-compatible request format. BitMod handles the translation.
            </p>
          </section>

          {/* Ollama */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Ollama (Local Models)</h2>
            <p className="text-muted-foreground mb-4">
              Run models locally with Ollama and cache through BitMod. No API key required:
            </p>
            <CodeBlock filename=".env">
{`BITMOD_LLM_PROVIDER=ollama
BITMOD_LLM_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434`}
            </CodeBlock>
            <CodeBlock filename="bitmod.yaml">
{`llm_provider: ollama
llm_model: llama3.2
# OLLAMA_URL defaults to http://localhost:11434`}
            </CodeBlock>
            <Card className="border-border/40 bg-card/50 mt-4">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-primary/10 p-1.5 shrink-0">
                    <Zap className="h-4 w-4 text-primary" />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Local models benefit massively from caching. A 7B model that takes seconds to generate a response is served from cache in 68-82ms over HTTP, or 0.2ms in-process.
                  </p>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* OpenAI-Compatible Providers */}
          <section>
            <h2 className="text-xl font-semibold mb-4">OpenAI-Compatible Providers</h2>
            <p className="text-muted-foreground mb-4">
              For providers not listed above (Groq, Together, vLLM, LM Studio, Jan.ai, etc.), use the universal OpenAI-compatible adapter by setting the provider URL:
            </p>
            <CodeBlock filename=".env">
{`BITMOD_LLM_PROVIDER=auto
BITMOD_LLM_MODEL=llama-3.3-70b-versatile
BITMOD_LLM_URL=https://api.groq.com/openai/v1
BITMOD_LLM_API_KEY=gsk_...`}
            </CodeBlock>
            <CodeBlock filename="bitmod.yaml">
{`llm_provider: auto
llm_model: llama-3.3-70b-versatile
llm_url: https://api.groq.com/openai/v1
llm_api_key: gsk_...`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Cache hits work across providers. If a query was answered by one provider and the same query comes in later,
              BitMod serves the cached response regardless of the current provider configuration.
            </p>
          </section>

          {/* Verifying */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Verifying Your Configuration</h2>
            <p className="text-muted-foreground mb-4">
              Check which providers are active:
            </p>
            <CodeBlock filename="terminal">
{`# Check current configuration
bitmod config

# Verify your provider is working
bitmod status`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              The <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod status</code> command shows your active provider, model, cache stats, and database connection.
            </p>
          </section>

          {/* Summary */}
          <Card className="border-border/40 bg-card/50">
            <CardContent className="p-6">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2">
                  <Zap className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold mb-1">Key Takeaways</h3>
                  <ul className="text-sm text-muted-foreground space-y-1">
                    <li>Set provider credentials via environment variables or <code className="text-primary/80 bg-primary/10 px-1 py-0.5 rounded text-xs font-mono">bitmod.yaml</code>.</li>
                    <li>BitMod auto-translates between API formats — use OpenAI-compatible requests for any provider.</li>
                    <li>11 native adapters + 1 universal OpenAI-compatible adapter, which covers anything speaking that API.</li>
                    <li>Cache hits are shared across providers by default.</li>
                  </ul>
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
                      <Layers className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Setting Up Your First Cache</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Configure TTL, layers, and monitoring</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
              <Link href="/guides/getting-started" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Database className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Getting Started with BitMod</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Install and send your first query</p>
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
