import type { Metadata } from "next"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { CodeBlock } from "@/components/shared/code-block"
import { ArrowRight, Clock, AlertTriangle, Terminal, Wrench, Database, Container, Gauge, LifeBuoy } from "lucide-react"

export const metadata: Metadata = {
  title: "Troubleshooting | Guides",
  description: "Solutions for common BitMod issues: installation problems, connection errors, cache misses, provider configuration, and deployment debugging.",
}

export default function TroubleshootingGuide() {
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
            <Badge className="bg-green-500/15 text-green-400 border-green-500/30">Beginner</Badge>
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl lg:text-5xl">
            Troubleshooting
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Solutions for common BitMod issues — installation failures, connection errors, cache misses, configuration conflicts, and deployment debugging.
          </p>
        </div>

        <div className="space-y-12">
          {/* Section 1: Installation Issues */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <Terminal className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Installation Issues</h2>
            </div>

            <div className="space-y-6">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">
                    <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">pip install -e .</code> fails
                  </h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    BitMod requires Python 3.10 or newer. Check your version and upgrade if needed:
                  </p>
                  <CodeBlock filename="terminal">
{`python --version
# If below 3.10, upgrade Python first

# On macOS:
brew install python@3.12

# On Ubuntu/Debian:
sudo apt update && sudo apt install python3.12 python3.12-venv

# If you see "error: can't find Rust compiler" or missing build tools:
pip install --upgrade pip setuptools wheel`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">
                    <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod</code> command not found after install
                  </h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The CLI binary is installed to your Python scripts directory, which may not be on your PATH:
                  </p>
                  <CodeBlock filename="terminal">
{`# Check where pip installed it:
python -m site --user-base
# Typically ~/.local/bin on Linux, ~/Library/Python/3.x/bin on macOS

# Add to PATH (add to your .bashrc or .zshrc):
export PATH="$HOME/.local/bin:$PATH"

# Or run directly via Python module:
python -m bitmod --help`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Optional dependency errors</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    Some features require optional dependencies. Install them as needed:
                  </p>
                  <CodeBlock filename="terminal">
{`# Embedding support (vector embeddings):
pip install "bitmod[embeddings]"
# Installs: sentence-transformers, chromadb

# All optional dependencies:
pip install "bitmod[all]"

# If sentence-transformers fails on Apple Silicon:
pip install --no-binary :all: tokenizers
pip install "bitmod[embeddings]"`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Section 2: Connection Errors */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <AlertTriangle className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Connection Errors</h2>
            </div>

            <div className="space-y-6">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">&ldquo;Could not connect to LLM provider&rdquo;</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    BitMod can&apos;t reach the configured LLM backend. If you&apos;re using Ollama, make sure it&apos;s running:
                  </p>
                  <CodeBlock filename="terminal">
{`# Check if Ollama is running:
curl http://localhost:11434/api/tags

# If not running, start it:
ollama serve

# If using a custom URL, verify your bitmod.yaml:
# provider:
#   type: ollama
#   base_url: http://localhost:11434

# For cloud providers, verify your API key is set:
echo $OPENAI_API_KEY
echo $ANTHROPIC_API_KEY`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">&ldquo;Server not reachable — using offline mode&rdquo;</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The BitMod SDK can&apos;t connect to the gateway. This usually means <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod serve</code> isn&apos;t running:
                  </p>
                  <CodeBlock filename="terminal">
{`# Start the gateway:
bitmod serve

# Verify it's running:
curl http://localhost:8000/health

# If the port is different, specify it in your SDK client:
# client = BitmodClient(base_url="http://localhost:9000", api_key="bm_...")`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Database connection failures</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    SQLite is the default and usually works out of the box. If you see permission errors or PostgreSQL connection issues:
                  </p>
                  <CodeBlock filename="terminal">
{`# SQLite permission error — check the cache directory exists and is writable:
ls -la ~/.bitmod/
mkdir -p ~/.bitmod && chmod 755 ~/.bitmod

# PostgreSQL connection — set via environment variable:
# DATABASE_URL=postgresql://user:password@localhost:5432/bitmod

# Test PostgreSQL connectivity:
psql "postgresql://user:password@localhost:5432/bitmod" -c "SELECT 1"

# Common issue: password contains special characters — URL-encode them
# ! → %21, @ → %40, # → %23`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Section 3: Cache Not Working */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <Database className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Cache Not Working</h2>
            </div>

            <div className="space-y-6">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Cache hit rate is 0%</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    This is expected on your first query. The cache needs to see a query once to store it — the second identical or similar query will hit the cache:
                  </p>
                  <CodeBlock filename="python">
{`from bitmod import Bitmod

bm = Bitmod()

# First call — always a MISS (generates and caches the response)
r1 = bm.query("What is Python?")
print(r1.cached)  # False

# Second call — should be a HIT
r2 = bm.query("What is Python?")
print(r2.cached)  # True

# Check cache stats via CLI:
# bitmod cache stats`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Semantic cache not matching similar queries</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The semantic similarity threshold may be too strict, or embeddings may not be installed:
                  </p>
                  <CodeBlock filename="yaml" >
{`# Lower the semantic threshold to match more aggressively.
# Default is 0.88 — lower = more matches.
# Set via environment variable:
# BITMOD_CACHE_SEMANTIC_THRESHOLD=0.85
#
# Or in bitmod.yaml as a flat key:
# cache_semantic_threshold: 0.85`}
                  </CodeBlock>
                  <CodeBlock filename="terminal">
{`# Verify semantic dependencies are installed:
python -c "from sentence_transformers import SentenceTransformer; print('OK')"

# If not installed:
pip install "bitmod[embeddings]"`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Cache invalidated unexpectedly</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    Re-ingesting documents triggers a cascade invalidation of cache entries that reference those documents. This is by design — stale data shouldn&apos;t be served from cache:
                  </p>
                  <CodeBlock filename="terminal">
{`# Check what triggered invalidation:
bitmod status

# Re-ingest documents (cache entries referencing changed sources are invalidated):
bitmod ingest ./docs/

# Check current cache statistics:
bitmod cache stats`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Section 4: Configuration Problems */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <Wrench className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Configuration Problems</h2>
            </div>

            <div className="space-y-6">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Two config files found</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    BitMod checks for config in this order. The first one found wins:
                  </p>
                  <CodeBlock filename="terminal">
{`# Priority order:
# 1. ./bitmod.yaml          (project-local — highest priority)
# 2. ~/.bitmod/bitmod.yaml   (user-global — fallback)

# See which config file is active:
bitmod doctor

# Remove the one you don't want:
rm ./bitmod.yaml           # use global config
# or
rm ~/.bitmod/bitmod.yaml   # use project config`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Environment variables not taking effect</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    Environment variables override config file values, but require a restart of the gateway:
                  </p>
                  <CodeBlock filename="terminal">
{`# 1. Make sure the variable is exported (not just set):
export BITMOD_CACHE_TTL=3600  # not just BITMOD_CACHE_TTL=3600

# 2. If using a .env file, BitMod loads it from the working directory:
cat .env
# BITMOD_CACHE_TTL=3600
# OPENAI_API_KEY=sk-...

# 3. Restart the gateway to pick up changes:
# Ctrl+C the running process, then:
bitmod serve

# 4. Verify the value was loaded:
bitmod doctor`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">
                    <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod doctor</code> shows warnings
                  </h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">doctor</code> command runs diagnostics and reports anything misconfigured:
                  </p>
                  <CodeBlock filename="terminal">
{`bitmod doctor

# Example output:
# [OK] Python 3.12.3
# [OK] bitmod 0.2.0
# [OK] Config loaded from ./bitmod.yaml
# [WARN] No API key set — cloud providers won't work
# [WARN] sentence-transformers not installed — semantic cache disabled
# [OK] SQLite cache at ~/.bitmod/bitmod.db (4.2 MB, 312 entries)
# [OK] Gateway reachable at http://localhost:8000

# Fix warnings by installing optional deps or setting keys:
export OPENAI_API_KEY="sk-..."
pip install "bitmod[embeddings]"`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Section 5: Docker Issues */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <Container className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Docker Issues</h2>
            </div>

            <div className="space-y-6">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Gateway can&apos;t reach chat service</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The gateway authenticates to the chat service using an internal token. If it&apos;s not set, requests between services will fail:
                  </p>
                  <CodeBlock filename="terminal">
{`# Set the shared token in your .env:
echo 'BITMOD_INTERNAL_TOKEN=your-secret-token-here' >> .env

# Make sure both services have the same value:
docker compose exec gateway env | grep BITMOD_INTERNAL_TOKEN
docker compose exec chat env | grep BITMOD_INTERNAL_TOKEN

# Restart to pick up .env changes (restart alone won't re-read .env):
docker compose up -d`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Port 8000 already in use</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    Another process is bound to the gateway port:
                  </p>
                  <CodeBlock filename="terminal">
{`# Find what's using the port:
lsof -i :8000

# Kill it if safe to do so:
kill -9 <PID>

# Or change the BitMod port in docker-compose.yml:
# ports:
#   - "9000:8000"

# Then access at http://localhost:9000`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">PostgreSQL &ldquo;password authentication failed&rdquo;</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The database password must be set before the first <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">docker compose up</code>. Changing it after the volume is created requires a volume reset:
                  </p>
                  <CodeBlock filename="terminal">
{`# Set the password in .env:
echo 'POSTGRES_PASSWORD=your-password' >> .env

# If you changed the password after initial setup, reset the volume:
docker compose down -v  # WARNING: deletes all data
docker compose up -d

# Verify connection:
docker compose exec postgres psql -U bitmod -d bitmod -c "SELECT 1"`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Redis connection refused</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The Redis password in your app config must match the one Redis was started with:
                  </p>
                  <CodeBlock filename="terminal">
{`# Check Redis is running and healthy:
docker compose ps redis

# Test connection with the configured password:
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" ping
# Expected: PONG

# If password mismatch, update .env and restart:
# REDIS_PASSWORD=your-redis-password
docker compose up -d redis`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Section 6: Performance */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <Gauge className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Performance</h2>
            </div>

            <div className="space-y-6">
              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">Slow first query</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The first query for any new input is expected to be slow — it makes a full round-trip to your LLM provider. Subsequent identical queries return from cache in 68-82ms over HTTP:
                  </p>
                  <CodeBlock filename="terminal">
{`# First query: 800-2000ms (LLM generation)
# Second query: 68-82ms (cache hit, over HTTP)
# This is by design — the cache needs to see a query once to store it`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">High memory usage</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    The in-memory vector index grows with cache size. Reduce it by limiting the maximum number of entries:
                  </p>
                  <CodeBlock filename="yaml">
{`# bitmod.yaml
cache:
  max_entries: 10000   # default is 100000
  eviction: lru        # least-recently-used eviction

  semantic:
    max_entries: 5000  # vector index entries (most memory-intensive)

# Monitor memory usage:
# bitmod status --verbose shows memory breakdown per layer`}
                  </CodeBlock>
                </CardContent>
              </Card>

              <Card className="border-border/40 bg-card/50">
                <CardContent className="p-6">
                  <h3 className="font-semibold mb-2">SQLite &ldquo;database is locked&rdquo; under load</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    SQLite supports one writer at a time. Under concurrent load, switch to PostgreSQL:
                  </p>
                  <CodeBlock filename="yaml">
{`# Switch to PostgreSQL for production — set via environment variable:
# DATABASE_URL=postgresql://bitmod:password@localhost:5432/bitmod
#
# Or in bitmod.yaml as a flat key:
# db_backend: postgresql`}
                  </CodeBlock>
                  <p className="text-sm text-muted-foreground mt-3">
                    If you need to stay on SQLite temporarily, enable WAL mode for better concurrency:
                  </p>
                  <CodeBlock filename="terminal">
{`sqlite3 ~/.bitmod/bitmod.db "PRAGMA journal_mode=WAL;"`}
                  </CodeBlock>
                </CardContent>
              </Card>
            </div>
          </section>

          {/* Section 7: Getting Help */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="rounded-lg bg-primary/10 p-2">
                <LifeBuoy className="h-5 w-5 text-primary" />
              </div>
              <h2 className="text-xl font-semibold">Getting Help</h2>
            </div>

            <p className="text-muted-foreground mb-4">
              BitMod includes built-in diagnostic tools. Run these before opening an issue:
            </p>

            <div className="space-y-4 mb-6">
              <CodeBlock filename="terminal">
{`# Run built-in diagnostics — checks config, deps, connectivity:
bitmod doctor

# Show system state — cache stats, active layers, connections:
bitmod status

# Verbose logging — shows every cache layer decision:
bitmod --debug serve

# Or set the environment variable:
export BITMOD_LOG_LEVEL=debug
bitmod serve`}
              </CodeBlock>
            </div>

            <Card className="border-border/40 bg-card/50">
              <CardContent className="p-6">
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-primary/10 p-2">
                    <LifeBuoy className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-semibold mb-1">Still stuck?</h3>
                    <p className="text-sm text-muted-foreground">
                      Include the output of <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod doctor</code> and <code className="text-primary/80 bg-primary/10 px-1.5 py-0.5 rounded text-xs font-mono">bitmod status</code> when{" "}
                      <a href="https://github.com/DeepanjayNandal/bitmod/issues" className="text-primary hover:underline">opening a GitHub issue</a>.
                      This gives maintainers the full picture of your environment.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </section>

          {/* Next Steps */}
          <section>
            <h2 className="text-xl font-semibold mb-4">Related Guides</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Link href="/guides/getting-started" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Terminal className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Getting Started</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Install, first query, and cache savings</p>
                    </div>
                    <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                  </CardContent>
                </Card>
              </Link>
              <Link href="/guides/docker" className="group">
                <Card className="h-full border-border/40 bg-card/50 hover:border-border/80 transition-all duration-300">
                  <CardContent className="p-5 flex items-center gap-4">
                    <div className="rounded-lg bg-primary/10 p-2 shrink-0">
                      <Container className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">Docker Deployment</p>
                      <p className="text-xs text-muted-foreground mt-0.5">Container setup and orchestration</p>
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
