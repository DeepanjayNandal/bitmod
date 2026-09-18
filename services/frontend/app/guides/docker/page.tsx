import type { Metadata } from "next"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { CodeBlock } from "@/components/shared/code-block"
import {
  ArrowRight,
  Clock,
  Globe,
  HardDrive,
  Network,
  Server,
  ShieldCheck,
  TriangleAlert,
  Zap,
} from "lucide-react"

export const metadata: Metadata = {
  title: "Docker Deployment | Guides",
  description:
    "Deploy BitMod with Docker Compose: profiles for SQLite, PostgreSQL, Redis, and Ollama. Production configuration, networking, and health checks.",
}

export default function DockerDeploymentGuide() {
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
              <span>10 min read</span>
            </div>
            <Badge className="bg-yellow-500/15 text-yellow-400 border-yellow-500/30">Intermediate</Badge>
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            Docker Deployment
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Deploy BitMod with Docker Compose in one command. Choose your profile — from a minimal SQLite setup to a full production stack with PostgreSQL, Redis, and local LLM.
          </p>
        </div>

        <div className="space-y-12">
          {/* 1. Prerequisites */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">1</div>
              <h2 className="text-xl font-semibold">Prerequisites</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              You need Docker Engine 24+ and Docker Compose v2 installed. Verify with:
            </p>
            <CodeBlock filename="terminal">
{`docker --version        # Docker Engine 24.0+
docker compose version  # Docker Compose v2.20+`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Clone the repository and create your environment file before starting any services:
            </p>
            <CodeBlock filename="terminal">
{`git clone https://github.com/BitModerator/bitmod.git
cd bitmod
cp .env.example .env`}
            </CodeBlock>
          </section>

          {/* 2. Quick Start */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">2</div>
              <h2 className="text-xl font-semibold">Quick Start</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Edit the essentials in <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code>, then bring everything up:
            </p>
            <CodeBlock filename="terminal">
{`# 1. Set your LLM provider (any OpenAI-compatible API)
#    Edit .env and set BITMOD_LLM_URL, BITMOD_LLM_API_KEY, BITMOD_LLM_MODEL

# 2. Generate the internal service token
python3 -c "import secrets; print('BITMOD_INTERNAL_TOKEN=' + secrets.token_hex(32))" >> .env

# 3. Start BitMod
docker compose up -d

# 4. Verify
curl http://localhost:8000/health`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              That launches the gateway on port 8000, the chat service internally on 8001, and the frontend on port 3000 — all backed by SQLite with zero external dependencies.
            </p>
          </section>

          {/* 3. Compose Profiles */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">3</div>
              <h2 className="text-xl font-semibold">Compose Profiles</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              BitMod uses Docker Compose profiles to progressively add infrastructure. Start minimal and scale up as needed.
            </p>

            <div className="space-y-4">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <h3 className="font-semibold mb-1">Default — Gateway + Chat + Frontend (SQLite)</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The simplest deployment. No external databases, no local LLM server. Just point <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_LLM_URL</code> at any provider API.
                  </p>
                  <CodeBlock filename="terminal">
{`docker compose up -d`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <h3 className="font-semibold mb-1">ollama — Add Local LLM</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    Adds an Ollama container for running models locally. No API keys needed. Reserves 4 GB of memory.
                  </p>
                  <CodeBlock filename="terminal">
{`docker compose --profile ollama up -d

# Pull a model after Ollama starts
docker exec bitmod-ollama ollama pull llama3.2`}
                  </CodeBlock>
                  <p className="text-sm text-muted-foreground mt-2">
                    Set <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_LLM_URL=http://bitmod-ollama:11434/v1</code> in your <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code> to route through the internal network.
                  </p>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <h3 className="font-semibold mb-1">postgres — Add PostgreSQL + Redis</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    Production-grade storage with pgvector for embeddings and Redis for rate limiting. Requires <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">POSTGRES_PASSWORD</code> and <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">REDIS_PASSWORD</code> in your <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code>.
                  </p>
                  <CodeBlock filename="terminal">
{`docker compose --profile postgres up -d`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <h3 className="font-semibold mb-1">full — Everything</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    All services: gateway, chat, frontend, Ollama, PostgreSQL, and Redis.
                  </p>
                  <CodeBlock filename="terminal">
{`docker compose --profile ollama --profile postgres up -d`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* 4. Essential Configuration */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">4</div>
              <h2 className="text-xl font-semibold">Essential Configuration</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              At minimum, set these variables in your <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code> file:
            </p>
            <CodeBlock filename=".env">
{`# LLM Provider (any OpenAI-compatible API)
BITMOD_LLM_URL=http://bitmod-ollama:11434/v1   # or https://api.openai.com/v1
BITMOD_LLM_API_KEY=sk-...                       # leave empty for Ollama
BITMOD_LLM_MODEL=llama3.2                       # or gpt-4o-mini, etc.

# Internal auth between gateway and chat service (required for Docker)
BITMOD_INTERNAL_TOKEN=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">

# Only needed with --profile postgres
POSTGRES_PASSWORD=<generate with: python3 -c "import secrets; print(secrets.token_hex(16))">
REDIS_PASSWORD=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">

# Database backend (switch from sqlite to postgresql when using postgres profile)
BITMOD_DB_BACKEND=sqlite
# BITMOD_DB_BACKEND=postgresql
# DATABASE_URL=postgresql://bitmod:<password>@bitmod-postgres:5432/bitmod`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              The <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env.example</code> file documents every available option with examples for Ollama, OpenAI, Groq, Together, Fireworks, OpenRouter, and more.
            </p>
          </section>

          {/* 5. Network Architecture */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">5</div>
              <h2 className="text-xl font-semibold">Network Architecture</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              BitMod uses three isolated Docker networks to enforce least-privilege access between services:
            </p>

            <div className="space-y-3">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Globe className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">bitmod-public</h3>
                      <p className="text-sm text-muted-foreground">
                        Internet-facing. Only the gateway (port 8000) and frontend (port 3000) are attached. This is the only network with published ports.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Network className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">bitmod-internal</h3>
                      <p className="text-sm text-muted-foreground">
                        Service-to-service communication. The gateway talks to the chat service and Ollama here. No ports are published. Secured by the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_INTERNAL_TOKEN</code>.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <HardDrive className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">bitmod-data</h3>
                      <p className="text-sm text-muted-foreground">
                        Data layer only. The chat service connects to PostgreSQL and Redis here. Neither database publishes ports externally — they are completely unreachable from outside this network.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* 6. Health Checks */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">6</div>
              <h2 className="text-xl font-semibold">Health Checks</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Every service has a built-in health check. Docker uses these to manage startup ordering and restart unhealthy containers.
            </p>
            <CodeBlock filename="terminal">
{`# Check all service statuses
docker compose ps

# Gateway health (includes downstream readiness)
curl http://localhost:8000/health
# {"status": "ok"}

# Full readiness check (verifies DB, cache, LLM connectivity)
curl http://localhost:8000/readyz

# Individual container health
docker inspect --format='{{.State.Health.Status}}' bitmod-gateway
docker inspect --format='{{.State.Health.Status}}' bitmod-chat

# View logs if something is unhealthy
docker compose logs gateway --tail 50
docker compose logs chat --tail 50`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Health checks run every 10 seconds with a 15-second start period. The gateway waits for the chat service to be healthy before starting, and PostgreSQL/Redis are checked at 5-second intervals.
            </p>
          </section>

          {/* 7. Adding PostgreSQL */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">7</div>
              <h2 className="text-xl font-semibold">Adding PostgreSQL</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              SQLite is fine for development and small deployments. Switch to PostgreSQL with pgvector when you need concurrent writes, more than 50,000 embeddings, or production reliability.
            </p>
            <CodeBlock filename=".env">
{`# Generate a strong password
POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(16))")

# Switch the database backend
BITMOD_DB_BACKEND=postgresql
DATABASE_URL=postgresql://bitmod:$POSTGRES_PASSWORD@bitmod-postgres:5432/bitmod

# PostgreSQL credentials (used by the postgres container)
POSTGRES_USER=bitmod
POSTGRES_DB=bitmod`}
            </CodeBlock>
            <CodeBlock filename="terminal">
{`# Start with the postgres profile
docker compose --profile postgres up -d

# Verify PostgreSQL is accepting connections
docker exec bitmod-postgres pg_isready -U bitmod`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              The <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">pgvector/pgvector:pg16</code> image includes the pgvector extension. BitMod enables it automatically on first connection.
            </p>
          </section>

          {/* 8. Adding Redis */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">8</div>
              <h2 className="text-xl font-semibold">Adding Redis</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Redis is included in the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">postgres</code> profile and provides rate limiting, session storage, and response caching.
            </p>
            <CodeBlock filename=".env">
{`# Redis password (required — Compose will fail without it)
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
REDIS_HOST=bitmod-redis
REDIS_PORT=6379`}
            </CodeBlock>
            <p className="text-sm text-muted-foreground mt-3">
              Redis is configured with append-only persistence, a 256 MB memory limit, and an LRU eviction policy. Data is stored in the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod_redis_data</code> volume.
            </p>
          </section>

          {/* 9. Persistent Storage */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">9</div>
              <h2 className="text-xl font-semibold">Persistent Storage</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              All stateful data is stored in named Docker volumes that survive container restarts and upgrades:
            </p>
            <CodeBlock filename="volumes">
{`bitmod_data          # SQLite database, uploads, application state
bitmod_postgres_data # PostgreSQL data directory
bitmod_redis_data    # Redis AOF persistence
bitmod_ollama_data   # Downloaded LLM models (~2-8 GB per model)`}
            </CodeBlock>
            <CodeBlock filename="terminal">
{`# List volumes and their sizes
docker system df -v | grep bitmod

# Back up the SQLite database
docker cp bitmod-chat:/app/data/bitmod.db ./bitmod-backup.db

# Back up PostgreSQL
docker exec bitmod-postgres pg_dump -U bitmod bitmod > backup.sql`}
            </CodeBlock>
          </section>

          {/* 10. Production Hardening */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">10</div>
              <h2 className="text-xl font-semibold">Production Hardening</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Before exposing BitMod to the internet, lock down these settings:
            </p>
            <CodeBlock filename=".env">
{`# 1. Set real passwords (never use defaults in production)
POSTGRES_PASSWORD=<strong-random-password>
REDIS_PASSWORD=<strong-random-password>
BITMOD_INTERNAL_TOKEN=<strong-random-token>

# 2. Restrict CORS to your actual domains
CORS_ORIGINS=https://yourdomain.com

# 3. Enable authentication
BITMOD_AUTH_ENABLED=true
BITMOD_JWT_SECRET=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
BITMOD_API_KEYS=your-api-key-here

# 4. Use RS256 for JWT in multi-service setups
BITMOD_JWT_ALGORITHM=RS256`}
            </CodeBlock>
            <p className="text-muted-foreground mt-4 mb-4">
              For TLS, place a reverse proxy (nginx, Caddy, or Traefik) in front of the gateway:
            </p>
            <CodeBlock filename="terminal">
{`# Example with Caddy (automatic HTTPS)
# Caddyfile:
#   api.yourdomain.com {
#       reverse_proxy localhost:8000
#   }
#   app.yourdomain.com {
#       reverse_proxy localhost:3000
#   }`}
            </CodeBlock>
          </section>

          {/* 11. Kubernetes */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">11</div>
              <h2 className="text-xl font-semibold">Kubernetes</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              There is no Kubernetes deployment guide or Helm chart. Docker Compose is the only supported deployment method.
            </p>
          </section>

          {/* 12. Common Issues */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">12</div>
              <h2 className="text-xl font-semibold">Common Issues</h2>
            </div>

            <div className="space-y-4">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-destructive/10 p-2 shrink-0">
                      <TriangleAlert className="h-5 w-5 text-destructive" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">Chat service returns 403 Forbidden</h3>
                      <p className="text-sm text-muted-foreground">
                        The chat service only accepts requests from localhost unless <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_INTERNAL_TOKEN</code> is set. In Docker, the gateway IP is not localhost. Generate a token and add it to your <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code>.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-destructive/10 p-2 shrink-0">
                      <TriangleAlert className="h-5 w-5 text-destructive" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">Port conflict on 8000 or 3000</h3>
                      <p className="text-sm text-muted-foreground">
                        Another process is using the port. Change it in <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code> with <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">GATEWAY_PORT=8080</code> or <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">FRONTEND_PORT=3001</code>, then restart.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-destructive/10 p-2 shrink-0">
                      <TriangleAlert className="h-5 w-5 text-destructive" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">POSTGRES_PASSWORD or REDIS_PASSWORD not set</h3>
                      <p className="text-sm text-muted-foreground">
                        The <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">postgres</code> profile requires both passwords. Docker Compose will refuse to start with a clear error message. Generate them with <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">python3 -c &quot;import secrets; print(secrets.token_hex(16))&quot;</code>.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="rounded-lg bg-destructive/10 p-2 shrink-0">
                      <TriangleAlert className="h-5 w-5 text-destructive" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">Changes to .env not taking effect</h3>
                      <p className="text-sm text-muted-foreground">
                        <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">docker compose restart</code> does not re-read the <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code> file. Use <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">docker compose up -d</code> instead to recreate containers with the new environment.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Summary card */}
          <Card className="border-border/40 bg-card/50">
            <CardContent className="p-6">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2">
                  <Zap className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold mb-1">Deployment checklist</h3>
                  <p className="text-sm text-muted-foreground">
                    Copy <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env.example</code> to <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">.env</code>. Set your LLM provider and <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_INTERNAL_TOKEN</code>. Run <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">docker compose up -d</code>. Verify with <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">curl localhost:8000/health</code>. Add profiles as you need more infrastructure. Set real passwords and enable auth before going to production.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Next Steps */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Next Steps</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Link href="/guides/llm-providers" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Server className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Connecting Your LLM Provider</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Anthropic, OpenAI, Ollama, and more</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
              <Link href="/guides/cache-setup" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <ShieldCheck className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Setting Up Your First Cache</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Configure TTL, layers, and monitoring</p>
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
