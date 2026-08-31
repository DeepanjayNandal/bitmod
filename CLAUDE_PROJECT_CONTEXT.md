# BITMOD — Complete Project Context for Claude

> This document was generated through a full deep-dive analysis of the BITMOD codebase.
> It is intended to give Claude (web) maximum context for decision-making without needing
> to read every file individually. Upload this FIRST before any other file.

---

## 1. What is BITMOD?

BITMOD is an **intelligent caching and retrieval engine for AI systems**.

The core problem it solves:
- Calling an LLM (like GPT-4 or Claude) is slow (200ms–2s) and expensive ($0.001–$0.05 per call)
- Many users ask the same or similar questions repeatedly
- BITMOD intercepts those questions, checks a cache first, and only calls the LLM when truly necessary
- It also ingests documents and enables semantic search over them

**In one sentence:** BITMOD makes AI applications faster and cheaper by caching intelligent answers, detecting user intent, and assembling responses from pre-computed content blocks.

**License:** Apache 2.0 (open source)
**Status:** Active development, v0.1.0

---

## 2. Primary Tech Stack

### Backend (Python)
- **Language:** Python 3.10+
- **Web Framework:** FastAPI + Uvicorn (for REST API services)
- **Data Validation:** Pydantic v2+
- **HTTP Client:** httpx (async-capable)
- **Config:** PyYAML + environment variables
- **Testing:** pytest, pytest-asyncio, pytest-cov

### Databases (4 pluggable backends)
- **SQLite** — default, zero-config, development use, has FTS5 full-text search
- **PostgreSQL** — production-grade, supports pgvector + BM25, asyncpg driver
- **MySQL** — FULLTEXT search, SQLAlchemy
- **MongoDB** — Atlas Search, document-oriented

### LLM Providers (12 integrations)
- Anthropic (Claude), OpenAI (GPT), Ollama (local), Google Gemini, xAI (Grok)
- Mistral, Perplexity, OpenRouter, HuggingFace, AWS Bedrock, Azure OpenAI
- OpenAI-Compatible (Groq, Together AI, etc.)

### Embedding Providers (4)
- Local (sentence-transformers, all-MiniLM-L6-v2) — no API cost
- Ollama (local), OpenAI, Cohere

### Vector Stores (3)
- ChromaDB (embedded, default), Qdrant, Pinecone

### Messaging Platforms (5)
- Slack, Discord, Telegram, WhatsApp, Matrix

### Frontend
- **Framework:** Next.js 15.3 + React 19
- **Styling:** TailwindCSS 4.1 + Radix UI components
- **Language:** TypeScript 5.9
- **Port:** 3000

### Deployment
- Docker + Docker Compose (local dev)
- Kubernetes with Helm charts (production)
- Redis (optional, for session caching)
- Prometheus (metrics), OpenTelemetry (tracing)

---

## 3. Full Directory Structure

```
bitmod/                                   ← Root of repo
├── core/bitmod/                          ← THE CORE LIBRARY (pip-installable Python package)
│   ├── __init__.py                       ← Package exports
│   ├── api.py                            ← Main Bitmod() class — public API
│   ├── cli.py                            ← CLI: bitmod init/ingest/query/serve/status
│   ├── config.py                         ← All configuration dataclasses (YAML + env)
│   ├── cache_engine.py                   ← 9-layer intelligent cache engine (CORE)
│   ├── cache_metrics.py                  ← Cache hit rates, cost tracking, analytics
│   ├── blocks.py                         ← Multi-compression content blocks
│   ├── intent.py                         ← Intent detection engine (3-tier)
│   ├── roles.py                          ← LLM role configuration loader
│   ├── router.py                         ← LLM provider routing + fallback logic
│   ├── tool_layer.py                     ← LLM function-calling tool definitions
│   ├── action_plans.py                   ← Agent plan caching + HMAC security
│   ├── invalidation.py                   ← Cache invalidation pipeline
│   ├── tags.py                           ← Auto-tagging system
│   ├── auth.py                           ← API key + JWT authentication
│   ├── security.py                       ← Input sanitization, rate limiting
│   ├── schemas.py                        ← Pydantic request/response models
│   ├── migrations.py                     ← Database schema migration runner
│   ├── backup.py                         ← Session backup/restore
│   ├── usage.py                          ← Token + cost tracking
│   ├── observability.py                  ← Logging, tracing, correlation IDs
│   ├── namespaces.py                     ← Multi-tenant isolation
│   ├── messaging_bridge.py               ← Messaging platform integration hub
│   ├── roles.yaml                        ← Role config: narrator/synthesizer/reasoner/agent
│   ├── intents/                          ← 14 intent YAML config files
│   │   ├── cite.yaml
│   │   ├── compare.yaml
│   │   ├── explain.yaml
│   │   ├── analyze.yaml
│   │   ├── think.yaml
│   │   ├── hypothesize.yaml
│   │   ├── summarize.yaml
│   │   ├── extract.yaml
│   │   ├── create.yaml
│   │   ├── execute.yaml
│   │   ├── list.yaml
│   │   ├── brainstorm.yaml
│   │   ├── convert.yaml
│   │   └── draft.yaml / write.yaml
│   ├── ingestion/                        ← Document processing pipeline
│   │   ├── pipeline.py                   ← Orchestrates parse→chunk→embed→store
│   │   ├── parser.py                     ← Multi-format: PDF, DOCX, HTML, MD, CSV, JSON, TXT
│   │   └── chunker.py                    ← Paragraph-aware chunking with overlap
│   ├── proxy/                            ← LLM API format translation
│   │   ├── base.py
│   │   ├── anthropic_format.py
│   │   ├── openai_format.py
│   │   └── gemini_format.py
│   ├── interfaces/                       ← Abstract base classes (contracts)
│   │   ├── llm.py                        ← LLMProvider ABC
│   │   ├── database.py                   ← DatabaseBackend ABC + data models
│   │   ├── embeddings.py                 ← Embeddings provider ABC
│   │   ├── vectors.py                    ← Vector store ABC
│   │   └── messaging.py                  ← Messaging platform ABC
│   └── adapters/                         ← Concrete implementations (25+ providers)
│       ├── llm_anthropic.py              ← Anthropic Claude
│       ├── llm_openai.py                 ← OpenAI GPT
│       ├── llm_ollama.py                 ← Local Ollama
│       ├── llm_gemini.py                 ← Google Gemini
│       ├── llm_openai_compat.py          ← OpenAI-compatible (Groq, Together, etc.)
│       ├── llm_xai.py                    ← xAI Grok
│       ├── llm_mistral.py
│       ├── llm_perplexity.py
│       ├── llm_openrouter.py
│       ├── llm_huggingface.py
│       ├── llm_azure_openai.py
│       ├── llm_bedrock.py                ← AWS Bedrock
│       ├── embed_local.py                ← sentence-transformers (no API)
│       ├── embed_ollama.py
│       ├── embed_openai.py
│       ├── embed_cohere.py
│       ├── db_sqlite.py                  ← SQLite with FTS5
│       ├── db_postgresql.py              ← PostgreSQL with pgvector
│       ├── db_mysql.py
│       ├── db_mongodb.py
│       ├── vec_chroma.py                 ← ChromaDB (default vector store)
│       ├── vec_qdrant.py
│       ├── vec_pinecone.py
│       ├── msg_slack.py
│       ├── msg_discord.py
│       ├── msg_telegram.py
│       ├── msg_whatsapp.py
│       └── msg_matrix.py
│
├── services/                             ← MICROSERVICES (deployable servers)
│   ├── gateway/                          ← Public API Gateway
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   └── main.py                   ← FastAPI app, port 8000
│   │   └── Dockerfile
│   ├── chat/                             ← Internal Chat Processor
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   └── main.py                   ← FastAPI app, port 8001 (internal only)
│   │   └── Dockerfile
│   └── frontend/                         ← Admin Dashboard
│       ├── package.json
│       ├── tsconfig.json
│       ├── tailwind.config.js
│       ├── app/
│       │   ├── cache-engine/             ← Cache stats, hit rates UI
│       │   ├── assembly-engine/          ← Block assembly visualization
│       │   ├── playground/               ← Interactive testing UI
│       │   ├── security/                 ← Auth + rate limit settings
│       │   ├── roadmap/
│       │   └── changelog/
│       └── Dockerfile
│
├── db/migrations/                        ← Database schema evolution
│   ├── 001_init.sql                      ← Initial schema, 20+ tables (13.6 KB)
│   ├── 002_add_content_blocks.py         ← content_blocks, section_tags, relationships
│   ├── 003_add_cache_embeddings.py       ← query_embeddings for semantic cache
│   ├── 004_add_proxy_metadata.py         ← Proxy request/response metadata
│   └── 005_add_usage_and_namespaces.py   ← Usage tracking + multi-tenant namespaces
│
├── tests/                                ← 35+ automated test files
│   ├── test_cache_engine.py
│   ├── test_cache_advanced.py
│   ├── test_intent.py
│   ├── test_blocks.py
│   ├── test_ingestion.py
│   ├── test_security.py
│   ├── test_action_plans.py
│   ├── test_auth.py
│   ├── test_router.py
│   ├── test_pipeline_integration.py
│   └── ... (25+ more)
│
├── deploy/                               ← Deployment infrastructure
│   ├── docker-compose.yaml               ← One-command local setup
│   ├── README.md                         ← Deployment guide
│   └── helm/bitmod/                      ← Kubernetes Helm chart
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── deployment-gateway.yaml
│           ├── deployment-chat.yaml
│           ├── service-gateway.yaml
│           ├── service-chat.yaml
│           ├── configmap.yaml
│           ├── secret.yaml
│           ├── ingress.yaml
│           ├── pvc.yaml
│           └── serviceaccount.yaml
│
├── sdk/python/                           ← Python client SDK for users of BITMOD
│   └── src/bitmod_client/
│       ├── client.py                     ← Sync + async HTTP client
│       ├── models.py
│       ├── exceptions.py
│       └── __init__.py
│
├── .github/workflows/
│   ├── ci.yml                            ← Continuous integration
│   └── publish.yml                       ← PyPI publish pipeline
│
├── pyproject.toml                        ← Root package config, all deps, CLI scripts
├── docker-compose.yml                    ← Main Docker Compose (profiles: ollama, postgres, full)
├── Makefile                              ← Dev shortcuts (make dev, make test, make migrate)
├── bitmod.yaml                           ← Default runtime configuration
├── .env.example                          ← All environment variables documented
├── README.md                             ← Main docs
├── ARCHITECTURE.md                       ← Deep system design + 31 subsystems
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE                               ← Apache 2.0
```

---

## 4. Entry Points — How to Start/Use BITMOD

### A. CLI (Terminal)
```bash
bitmod init              # Interactive setup wizard
bitmod ingest ./docs/    # Ingest a folder of documents
bitmod query "What is X?" # Query with cache stats printed
bitmod serve             # Start the API server
bitmod status            # System health check
bitmod migrate           # Run DB migrations
bitmod backup            # Session management
```
**File:** `core/bitmod/cli.py`

### B. Python Library (import in your code)
```python
from bitmod import Bitmod

bm = Bitmod()                        # reads bitmod.yaml automatically
bm.ingest("./docs/")                 # processes documents
result = bm.query("What is X?")      # returns cached or fresh answer
print(result.answer, result.cached)
```
**File:** `core/bitmod/api.py` → `Bitmod` class

### C. REST API (HTTP requests)
```bash
# Chat
POST http://localhost:8000/v1/chat
{"message": "What is the refund policy?", "stream": false}

# Search
POST http://localhost:8000/v1/search
{"query": "revenue growth", "limit": 10}

# Ingest text
POST http://localhost:8000/v1/ingest/text
{"text": "...", "title": "My Document"}

# Cache stats
GET http://localhost:8000/v1/cache/stats

# Admin metrics (auth required)
GET http://localhost:8000/v1/admin/metrics
```
**File:** `services/gateway/app/main.py`

### D. Python SDK (for external app developers)
```python
from bitmod_client import BitmodClient

client = BitmodClient(api_key="...", base_url="http://localhost:8000")
result = client.ask("What is the refund policy?", filters={"jurisdiction": "CA"})
print(result.answer, result.cached, result.generation_ms)
```
**File:** `sdk/python/src/bitmod_client/client.py`

---

## 5. Architectural Pattern

### Overall Style: Modular Library-First + Microservices Hybrid

**Library-First principle:**
- The entire system works as a single `from bitmod import Bitmod` Python import
- No server required for basic use
- When you need to scale, you deploy the services layer on top

**Adapter Pattern (dominant):**
- Every external dependency (LLM, DB, vector store, embedding, messaging) is hidden behind an abstract interface
- The rest of the code talks only to the interface — never to a specific provider
- Swapping OpenAI for Anthropic = one config line change

```
Interface (abstract contract)    Adapters (concrete implementations)
─────────────────────────────    ─────────────────────────────────────
interfaces/llm.py                adapters/llm_openai.py
  class LLMProvider(ABC):          class OpenAIAdapter(LLMProvider):
    async def complete(...)           async def complete(...): # real code
    async def stream(...)
                                 adapters/llm_anthropic.py
                                   class AnthropicAdapter(LLMProvider):
                                     async def complete(...): # real code
```

**Microservices (deployment layer only):**
- Gateway (8000) — auth, rate limiting, public routing
- Chat (8001) — internal, smart processing (intent → cache → LLM)
- Frontend (3000) — admin dashboard
- These services import and use the core library

### NOT:
- Not MVC (Model-View-Controller) — no server-rendered views
- Not pure DDD (Domain-Driven Design) — no explicit aggregates/entities
- Not pure Clean Architecture — borrows the interface/adapter concept but simplified

---

## 6. The 9-Layer Intelligent Cache Engine

**File:** `core/bitmod/cache_engine.py`

This is the primary innovation of BITMOD. When a query comes in, it passes through 9 layers before calling an LLM:

```
Query: "What is the company refund policy?"
           │
           ▼
Layer 1: NORMALIZE
  → lowercase, remove stopwords, sort tokens
  → "company refund policy"

Layer 2: BUILD COMPOSITE KEY
  → SHA-256(normalized_query + intent + filters + tenant + temporal + language)
  → "a3f92b1c..." (fingerprint)

Layer 3: EXACT LOOKUP  ← O(1), fastest
  → Check DB: does this exact key exist?
  → HIT → return cached answer immediately

Layer 4: DOUBLE VERIFY
  → Re-check source document hashes
  → If source changed since caching → skip this cache entry

Layer 5: TEMPORAL DETECTION
  → Is this a timeless question? ("What is Python?")
  → Yes → permanent cache, never expires
  → Is this time-sensitive? ("What is today's price?")
  → Yes → short TTL or no cache

Layer 6: FUZZY MATCHING  ← semantic similarity
  → Jaccard similarity + token overlap
  → "company return policy" ≈ "company refund policy" → 0.87 similarity
  → Above threshold → return cached answer

Layer 7: COMPOSABLE DECOMPOSITION
  → Complex query = multiple cached sub-queries
  → "Compare X and Y" → cached(X) + cached(Y) → assembled answer

Layer 8: CASCADE INVALIDATION
  → Source document updated → find all cache entries that used it → delete them
  → Ensures stale answers are never served

Layer 9: METRICS + TIERING
  → Track hit rates, generation costs, token usage
  → Hot entries (frequently hit) → keep in memory
  → Cold entries → disk or evict
           │
           ▼
       LLM CALL  ← only reaches here if all 9 layers miss
```

**Cache key formula:**
`SHA-256(normalized_query + "|" + intent + "|" + filters_hash + "|" + tenant_id + "|" + temporal_marker + "|" + language)`

---

## 7. Intent Detection System (3-Tier)

**File:** `core/bitmod/intent.py` + `core/bitmod/intents/*.yaml`

Detects WHAT the user wants to do with information — not just what they're asking about.

### 14 Intent Types
`cite`, `compare`, `explain`, `analyze`, `think`, `hypothesize`, `summarize`, `extract`, `create`, `execute`, `list`, `brainstorm`, `convert`, `draft/write`

### 3-Tier Detection (ordered by speed/cost)
```
Tier 1: RULE ENGINE (regex patterns)      → 70% of queries, 0ms, $0
  "compare X vs Y" → COMPARE intent
  "list all X" → LIST intent
  "explain X" → EXPLAIN intent

Tier 2: LIGHTWEIGHT ML CLASSIFIER         → 25% of queries, ~5ms, $0
  Trained on intent patterns
  Handles ambiguous phrasing

Tier 3: LLM FALLBACK                      → 5% of queries, ~200ms, ~$0.001
  Send query to LLM with classification prompt
  Most expensive but most accurate
```

### Why Intent Matters for Caching
- "Explain X" and "Summarize X" about the same topic → DIFFERENT cache entries
- "Compare X and Y" → triggers block assembly from cached X + cached Y
- "Execute X" → triggers action plan lookup, not just text lookup

---

## 8. Intent-Aware Content Assembly System

**Files:** `core/bitmod/blocks.py`, `core/bitmod/roles.py`, `core/bitmod/roles.yaml`

### Content Blocks (3 compression levels)
Every section of every document is pre-computed into 3 sizes:
```
FULL       → Complete text (used for: cite, explain, analyze)
STRUCTURED → Bullet points / key facts (used for: compare, list, extract)
HEADLINE   → One-sentence summary (used for: brainstorm, overview queries)
```
This means serving a response = assembling pre-computed blocks, not generating fresh text.

### 6 Roles (in roles.yaml)
Each intent maps to a role, each role has its own:
- System prompt
- Token budget
- Model tier preference (cheap vs powerful)
- Response format

| Role | Used for |
|---|---|
| narrator | explain, summarize |
| synthesizer | compare, analyze |
| structurer | list, extract, convert |
| reasoner | think, hypothesize |
| explorer | brainstorm |
| agent | execute, create |

### Assembly Flow
```
Query: "Compare PostgreSQL vs MySQL"
  │
  ▼
Intent: COMPARE
  │
  ▼
Role: SYNTHESIZER
  │
  ▼
Block retrieval:
  → PostgreSQL blocks (STRUCTURED compression) from cache
  → MySQL blocks (STRUCTURED compression) from cache
  │
  ▼
Assembly: combine blocks → format with synthesizer role prompt
  │
  ▼
Response (no LLM call needed if both blocks cached)
```

---

## 9. Document Ingestion Pipeline

**Files:** `core/bitmod/ingestion/pipeline.py`, `parser.py`, `chunker.py`

```
Input file (PDF/DOCX/HTML/MD/CSV/JSON/TXT)
    │
    ▼
parser.py: Extract raw text + metadata
    │
    ▼
chunker.py: Split into paragraph-aligned chunks
  → Configurable chunk size + overlap
  → Preserves paragraph boundaries (no mid-sentence cuts)
    │
    ▼
embeddings adapter: Convert each chunk to vector (384 dimensions)
  → Local (sentence-transformers) or API (OpenAI/Cohere)
    │
    ▼
Store to:
  → Database (SQLite/Postgres) — document, sections, chunks tables
  → Vector store (Chroma/Qdrant/Pinecone) — for semantic search
  → Content blocks table — pre-compute 3 compression levels
  → Section tags — auto-tag for faceted retrieval
```

---

## 10. Database Schema (Key Tables)

**File:** `db/migrations/001_init.sql`

### Hierarchy of stored data:
```
documents (top-level: title, source URL, metadata)
    └── sections (complete content units, versioned)
            └── chunks (vector search units, 384-dim embeddings)
            └── content_blocks (pre-compressed: full/structured/headline)
            └── section_tags (domain, topic, entity_type for faceted search)
            └── section_relationships (co-retrieval, citation, supersession)
```

### Cache tables:
```
answer_cache         ← cached LLM answers + source manifest
block_cache          ← cached block content per compression level
assembly_cache       ← assembled responses (query+intent+filters+tenant)
query_embeddings     ← cached query vectors for semantic matching
intent_log           ← classification history + confidence scores
```

### Agent/execution tables:
```
action_plans         ← cached agent execution plans + HMAC signature
plan_executions      ← immutable audit trail of every plan run
```

### Operations tables:
```
change_events        ← source document changes → triggers invalidation
source_monitors      ← external source polling configuration
data_gaps            ← demand-driven acquisition queue
answer_versions      ← version chains for differential display
expert_reviews       ← domain expert corrections to cached answers
cache_metrics        ← hit rates, generation costs, token accounting
subscriptions        ← user watch lists for change notifications
```

### Multi-tenant tables:
```
namespaces           ← tenant isolation boundaries
usage                ← per-tenant token + cost accounting
```

---

## 11. Service Architecture

### Gateway Service (`services/gateway/app/main.py`, port 8000)
**Role:** Public-facing entry point. Handles cross-cutting concerns.

Responsibilities:
- CORS (allows browser frontends to call it)
- Rate limiting (prevent abuse)
- API key / JWT authentication
- Request routing to Chat service (internal)
- Directly handles: ingest, search, cache stats, admin metrics

Key routes:
```
GET  /health
POST /v1/chat              → proxies to Chat service
POST /v1/search            → direct DB search
POST /v1/ingest/text       → ingestion pipeline
POST /v1/ingest/file       → file ingestion
GET  /v1/ingest/status
GET  /v1/cache/stats
GET  /v1/admin/metrics     ← requires auth
```

### Chat Service (`services/chat/app/main.py`, port 8001)
**Role:** Internal only. The smart brain. Never exposed publicly.

Security: requires `X-Internal-Token` header or must come from localhost.

Responsibilities:
- Intent detection (3-tier)
- 9-layer cache lookup
- Block retrieval + assembly
- LLM call (if cache miss)
- Streaming response support

Key routes:
```
GET  /health
POST /chat                 ← streaming supported
POST /search
```

### Frontend (`services/frontend/`, port 3000)
- Next.js 15.3 admin dashboard
- Calls Gateway on port 8000
- Pages: Cache Engine, Assembly Engine, Playground, Security, Roadmap, Changelog

### Internal Communication
```
Browser/Client
    │ HTTPS
    ▼
Gateway :8000          ← public
    │ HTTP + X-Internal-Token
    ▼
Chat :8001             ← private, internal only
    │
    ▼
Core Library + DB + LLM APIs
```

---

## 12. Configuration System

**File:** `core/bitmod/config.py`

Configuration sources (in priority order):
1. Environment variables (highest priority)
2. `bitmod.yaml` file (project-level config)
3. Defaults (in code)

### Key config dataclasses:
```python
BitmodConfig
├── DatabaseConfig        # backend, sqlite_path, postgres url, pool settings
├── RedisConfig           # host, port, db
├── LLMConfig             # primary, fallback, API keys for 12 providers
├── EmbeddingConfig       # provider, model, device (cpu/gpu), dimensions
├── VectorStoreConfig     # chroma/qdrant/pinecone URLs and API keys
├── CacheConfig           # TTL, fuzzy threshold, max_entries, eviction policy
├── BackupConfig          # enabled, path, compression
├── GatewayConfig         # port, CORS origins, chat service URL
├── RateLimitConfig       # enabled, requests_per_minute
├── AuthConfig            # api_key_header, jwt_secret, token_expiry
└── ObservabilityConfig   # log_level, enable_tracing, prometheus_port
```

Default `bitmod.yaml`:
```yaml
llm_primary: ollama
llm_primary_model: llama3.2
embedding_provider: ollama
embedding_model: nomic-embed-text
cors_origins:
  - http://localhost:3000
```

---

## 13. Security Model

**Files:** `core/bitmod/auth.py`, `core/bitmod/security.py`

### Authentication layers:
1. **API keys** — hashed in DB, sent as `X-API-Key` header
2. **JWT tokens** — for session-based auth, configurable expiry
3. **Internal token** — `X-Internal-Token` for service-to-service (Gateway → Chat)

### Security protections:
- Input sanitization (prevent prompt injection, SQL injection)
- Rate limiting per IP and per API key
- HMAC signing on action plans (prevent tampering with cached agent plans)
- Namespace isolation (multi-tenant: tenant A cannot see tenant B's data)

---

## 14. Multi-Tenancy (Namespaces)

**File:** `core/bitmod/namespaces.py`

- Every request can include a `tenant_id`
- Cache entries are scoped per tenant (tenant A's "What is our policy?" ≠ tenant B's)
- Cross-tenant cache federation is supported (opt-in): share common knowledge base entries
- Usage tracked per tenant for billing

---

## 15. Action Plans (Agent Caching)

**File:** `core/bitmod/action_plans.py`

For agentic AI use cases where the LLM decides on a multi-step plan:
- Plans are cached after first generation
- Plans are HMAC-signed (any modification invalidates them)
- Approval workflows: plans can require human approval before execution
- Immutable audit trail: every plan execution logged to `plan_executions` table
- Re-execution uses cached plan — no LLM call needed

---

## 16. Observability

**File:** `core/bitmod/observability.py`

- **Structured logging** — JSON format, correlation IDs per request
- **Tenant isolation in logs** — each log entry tagged with `tenant_id`
- **Prometheus metrics** — cache hit rates, LLM latency, token usage
- **OpenTelemetry tracing** (optional) — distributed traces across Gateway → Chat → DB
- **Cache metrics** — stored in DB (`cache_metrics` table), viewable in dashboard

---

## 17. Python SDK (for external developers)

**File:** `sdk/python/src/bitmod_client/client.py`

External developers who deploy BITMOD as a service use this SDK:
```python
from bitmod_client import BitmodClient

client = BitmodClient(
    api_key="bm_live_xxx",
    base_url="http://localhost:8000"
)

# Sync
result = client.ask("What is the refund policy?")

# Async
result = await client.ask_async("What is the refund policy?")

# With filters (faceted retrieval)
result = client.ask("Policy?", filters={"jurisdiction": "CA", "year": 2024})

# Search only (no LLM)
results = client.search("revenue growth", limit=10)

# Ingest
client.ingest_text("Full document text here...", title="Policy Doc v3")
```

---

## 18. Deployment Modes

### Mode 1: Local Library (development)
```python
from bitmod import Bitmod
bm = Bitmod()  # SQLite + local Ollama
```
No Docker, no servers, single process.

### Mode 2: Docker Compose (default)
```bash
docker compose up
```
Starts: Gateway (8000) + Chat (8001) + Frontend (3000). Uses SQLite + user-provided LLM API keys.

### Mode 3: Docker Compose with Ollama (local LLM)
```bash
docker compose --profile ollama up
```
Adds: Ollama container with llama3.2 — fully local, no API keys needed.

### Mode 4: Docker Compose Full Stack
```bash
docker compose --profile full up
```
Adds: PostgreSQL + pgvector + Redis — production-grade storage.

### Mode 5: Kubernetes (Helm)
```bash
helm install bitmod ./deploy/helm/bitmod -f values.yaml
```
Full production deployment with autoscaling, secrets management, persistent volumes.

---

## 19. CI/CD Pipeline

**Files:** `.github/workflows/ci.yml`, `.github/workflows/publish.yml`

- `ci.yml` — runs on every push/PR: lint + tests + coverage
- `publish.yml` — publishes to PyPI on version tag (`v*`)

---

## 20. Key Design Decisions & Why

| Decision | Why |
|---|---|
| Library-first, not service-first | Developer experience — works with `pip install bitmod`, no infra needed |
| 4 database backends | Enterprise customers have existing DBs; can't force them to migrate |
| 3-tier intent detection | Balance cost vs accuracy — 70% of queries solved with zero LLM cost |
| Content blocks (3 compressions) | Serve responses from pre-computed blocks — zero generation cost |
| HMAC on action plans | Agent plans must not be tampered with after approval |
| FTS5 in SQLite | Full-text search without needing Elasticsearch or external search service |
| 9-layer cache | Progressive fallback — always try cheaper layers first |
| Namespace isolation | Multi-tenant from day one — avoids costly refactoring later |
| Apache 2.0 license | Enterprise-friendly, allows commercial use |

---

## 21. File Count Summary

| Category | Count |
|---|---|
| Python source files | 116 |
| Intent YAML configs | 14 |
| Database migrations | 5 |
| Test files | 35+ |
| Docker/Helm configs | 12+ |
| Documentation files | 11 |
| Frontend (TS/JS) | Next.js app |
| SDK | 1 Python package |

---

## 22. Contribution Areas (for open-source contributors)

Based on the codebase structure, contribution opportunities exist in:

1. **New LLM adapters** — add a new provider in `adapters/llm_*.py`, implement `LLMProvider` interface
2. **New embedding adapters** — `adapters/embed_*.py`, implement `EmbeddingsProvider` interface
3. **New database backends** — `adapters/db_*.py`, implement `DatabaseBackend` interface
4. **New vector stores** — `adapters/vec_*.py`, implement `VectorStore` interface
5. **New messaging platforms** — `adapters/msg_*.py`, implement `MessagingPlatform` interface
6. **Intent YAML files** — add new intents in `intents/` directory
7. **New ingestion parsers** — add file format support in `ingestion/parser.py`
8. **Frontend pages** — new dashboard views in `services/frontend/app/`
9. **Tests** — new test files in `tests/`
10. **SDK methods** — extend `sdk/python/src/bitmod_client/client.py`

The **adapter pattern** makes contributions safe — you cannot break existing functionality by adding a new adapter.

---

## 23. Glossary

| Term | Meaning in BITMOD context |
|---|---|
| Cache hit | Query answered from cache, no LLM call made |
| Cache miss | No cached answer found, LLM called |
| Block | Pre-computed content unit at one of 3 compression levels |
| Intent | Classification of what a query wants (explain, compare, list, etc.) |
| Role | LLM persona with specific prompt, budget, model tier |
| Namespace | Tenant isolation boundary |
| Composite key | SHA-256 fingerprint used to look up cache entries |
| Fuzzy match | Similarity-based cache lookup (not exact match required) |
| Decomposition | Breaking a complex query into cached sub-answers |
| Invalidation | Deleting stale cache entries when source documents change |
| FTS5 | SQLite's built-in full-text search engine |
| pgvector | PostgreSQL extension for storing/querying embedding vectors |
| TTL | Time-To-Live — how long a cache entry is valid |
| HMAC | Hash-based Message Authentication Code — used to sign action plans |
| Adapter | Concrete implementation of an abstract interface |
| Interface/ABC | Abstract Base Class — defines the contract all adapters must follow |

---

*Generated from full codebase analysis. Last updated: 2026-03-25*
*For questions about this document, refer to ARCHITECTURE.md and README.md in the repo.*
