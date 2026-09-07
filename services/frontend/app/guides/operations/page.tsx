import type { Metadata } from "next"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { CodeBlock } from "@/components/shared/code-block"
import { ArrowRight, Clock, Activity, Database, HardDrive, Server, RefreshCw, HeartPulse, Wrench } from "lucide-react"

export const metadata: Metadata = {
  title: "Operations Guide | Guides",
  description: "Run BitMod in production: monitoring, backups, migrations, scaling, cache management, and maintenance.",
}

export default function OperationsGuide() {
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
              <span>15 min read</span>
            </div>
            <Badge className="bg-yellow-500/15 text-yellow-400 border-yellow-500/30">Intermediate</Badge>
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            Operations Guide
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Run BitMod in production: monitoring, backups, migrations, scaling, cache management, and maintenance.
          </p>
        </div>

        <div className="space-y-12">
          {/* Section 1: Monitoring */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">1</div>
              <h2 className="text-xl font-semibold">Monitoring</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              BitMod exposes several endpoints for observability. Use these to monitor cache performance, cost savings, and system health.
            </p>

            <div className="space-y-4">
              <CodeBlock filename="terminal">
{`# Prometheus metrics (requires API key when auth is enabled)
curl http://localhost:8000/metrics

# Cache hit rates and per-layer breakdown
curl http://localhost:8000/v1/cache/stats

# Cost savings and query volume
curl http://localhost:8000/v1/usage

# Admin dashboard data
curl http://localhost:8000/v1/admin/metrics`}
              </CodeBlock>

              <p className="text-sm text-muted-foreground">
                Every response includes diagnostic headers you can use for debugging and monitoring:
              </p>

              <CodeBlock filename="response headers">
{`X-Bitmod-Cache: HIT | MISS | PARTIAL
X-Bitmod-Latency: 2.3ms
X-Bitmod-Model: gpt-4o-mini`}
              </CodeBlock>
            </div>
          </section>

          {/* Section 2: Backups */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">2</div>
              <h2 className="text-xl font-semibold">Backups</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Backup is always-on by default (<code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">BITMOD_BACKUP_ENABLED=true</code>).
              Use the CLI to list, export, and restore backup sessions.
            </p>

            <CodeBlock filename="terminal">
{`# View backup sessions
bitmod backup list

# Export a session to a compressed file
bitmod backup export <session_id>

# Restore from a backup file
bitmod backup import --file backup.jsonl.gz`}
            </CodeBlock>
          </section>

          {/* Section 3: Database Migrations */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">3</div>
              <h2 className="text-xl font-semibold">Database Migrations</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              BitMod manages its own schema migrations. All migration commands are idempotent — safe to run multiple times.
            </p>

            <CodeBlock filename="terminal">
{`# Check current migration version
bitmod migrate --status

# Apply all pending migrations
bitmod migrate

# Migrate to a specific version
bitmod migrate --target N`}
            </CodeBlock>
          </section>

          {/* Section 4: Cache Management */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">4</div>
              <h2 className="text-xl font-semibold">Cache Management</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              View cache statistics, invalidate entries, and configure storage limits.
            </p>

            <div className="space-y-4">
              <CodeBlock filename="terminal">
{`# View cache stats and per-layer breakdown
curl http://localhost:8000/v1/cache/stats

# Clear all cached answers
bitmod cache clear

# Same, when running under Docker (the container has its own database)
docker compose exec bitmod-chat bitmod cache clear`}
              </CodeBlock>

              <p className="text-sm text-muted-foreground">
                Storage and retention limits are configured via environment variables:
              </p>

              <CodeBlock filename="environment">
{`BITMOD_MAX_ATOMIC_FACTS=500000
BITMOD_MAX_SIMILARITY_LINKS=1000000
BITMOD_MAX_ANSWER_LENGTH=100000
BITMOD_AUDIT_RETENTION_DAYS=90`}
              </CodeBlock>
            </div>
          </section>

          {/* Section 5: Scaling */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">5</div>
              <h2 className="text-xl font-semibold">Scaling</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              BitMod starts with SQLite for zero-config simplicity. As your workload grows, scale up the backing infrastructure.
            </p>

            <div className="space-y-4">
              <CodeBlock filename="terminal">
{`# Switch to PostgreSQL for concurrent access
export BITMOD_DB_BACKEND=postgresql
export DATABASE_URL="postgresql://user:pass@localhost:5432/bitmod"

# Add Redis for distributed rate limiting
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_PASSWORD=your_redis_password

# Start with Docker Compose (postgres profile)
docker compose --profile postgres up -d`}
              </CodeBlock>

              <p className="text-sm text-muted-foreground">
                To scale horizontally, increase replicas in Docker Compose:
              </p>

              <CodeBlock filename="terminal">
{`# Scale the BitMod service to 3 replicas
docker compose up -d --scale bitmod=3`}
              </CodeBlock>
            </div>
          </section>

          {/* Section 6: Hot Reload */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">6</div>
              <h2 className="text-xl font-semibold">Hot Reload</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Reload intent and role YAML configurations without restarting the server. Use this after modifying intent definitions or model routing rules.
            </p>

            <CodeBlock filename="terminal">
{`curl -X POST http://localhost:8000/v1/reload

# {
#   "status": "ok",
#   "reloaded": ["intents", "roles"]
# }`}
            </CodeBlock>
          </section>

          {/* Section 7: Health Checks */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">7</div>
              <h2 className="text-xl font-semibold">Health Checks</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              BitMod exposes three health endpoints for different use cases:
            </p>

            <CodeBlock filename="terminal">
{`# Lightweight liveness check (always responds)
curl http://localhost:8000/health

# Kubernetes liveness probe
curl http://localhost:8000/healthz

# Deep readiness check (validates chat service and DB)
curl http://localhost:8000/readyz`}
            </CodeBlock>

            <p className="text-sm text-muted-foreground mt-3">
              Use <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">/health</code> or <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">/healthz</code> for liveness probes and <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">/readyz</code> for readiness probes in your orchestrator.
            </p>
          </section>

          {/* Section 8: System Diagnostics */}
          <section>
            <div className="flex items-center gap-3 mb-4">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">8</div>
              <h2 className="text-xl font-semibold">System Diagnostics</h2>
            </div>
            <p className="text-muted-foreground mb-4">
              Use the CLI to inspect your BitMod installation, debug issues, and trace queries through the pipeline.
            </p>

            <CodeBlock filename="terminal">
{`# Check all dependencies and configuration
bitmod doctor

# View config, cache stats, and document count
bitmod status

# Show resolved configuration values
bitmod config

# Verbose pipeline trace for a test query
bitmod --debug query "test"`}
            </CodeBlock>
          </section>

          {/* Summary card */}
          <Card className="border-border/40 bg-card/50">
            <CardContent className="p-6">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2">
                  <Activity className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold mb-1">Production checklist</h3>
                  <p className="text-sm text-muted-foreground">
                    Before going live, verify health checks respond, backups are enabled, monitoring endpoints return data,
                    and your database migrations are current. Run <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod doctor</code> to
                    confirm everything is wired up correctly.
                  </p>
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
                      <Database className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Cache Setup Guide</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Configure layers, TTL, and eviction policies</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
              <Link href="/guides/getting-started" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Server className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Getting Started</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Install and run your first query in 5 minutes</p>
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
