# BITMOD — Deep Analysis: Patterns, Debt, APIs, Lifecycle

> This is the companion document to CLAUDE_PROJECT_CONTEXT.md.
> That file covers WHAT the system is. This file covers HOW it works internally —
> design patterns, technical debt, API reference, data model relationships,
> and the complete request lifecycle. Read this when making architectural decisions
> or debugging specific subsystems.
>
> Generated from full codebase deep-dive. Last updated: 2026-03-25
> Updated: Section 9 added — Project Knowledge System (commits 891cd54 + 4dfc4fb, Mar 25 2026)
> Also updated: Section 3 API reference (7 new endpoints), Section 4 DB schema (6 new tables),
> Section 5 request lifecycle (project_id now part of cache key + context injection)

---

## 1. Design Patterns — Where Each Lives in Code

### Adapter Pattern
**Files:** `core/bitmod/interfaces/llm.py` + `core/bitmod/adapters/llm_openai.py`

The interface defines the contract (abstract methods only). Each adapter implements it for one specific provider.

```
interfaces/llm.py       → abstract: generate(), stream(), count_tokens()
adapters/llm_openai.py  → OpenAIAdapter(LLMProvider): real openai API calls
adapters/llm_anthropic.py → AnthropicAdapter(LLMProvider): real anthropic calls
adapters/db_sqlite.py   → SQLiteBackend(DatabaseBackend): real SQL
adapters/db_postgresql.py → PostgreSQLBackend(DatabaseBackend): real SQL
```

`cache_engine.py` and all business logic call the interface only — never the adapter directly.
Swapping OpenAI for Anthropic = one config line change, zero code changes.

**All adapters:**
- 12 LLM: `adapters/llm_*.py`
- 4 DB: `adapters/db_*.py`
- 4 Embeddings: `adapters/embed_*.py`
- 3 Vector stores: `adapters/vec_*.py`
- 5 Messaging: `adapters/msg_*.py`

---

### Factory Pattern
**File:** `core/bitmod/adapters/__init__.py:13`

```python
def get_backend(config) -> DatabaseBackend:
    match config.backend:
        case "sqlite":     return SQLiteBackend(config.sqlite_path)
        case "postgresql": return PostgreSQLBackend(config.url)
        case "mysql":      return MySQLBackend(config.url)
        case "mongodb":    return MongoDBBackend(...)

def make_llm(provider: str, config) -> LLMProvider:
    match provider:
        case "anthropic":  return AnthropicAdapter(...)
        case "openai":     return OpenAIAdapter(...)
        case "ollama":     return OllamaAdapter(...)
        # 9 more providers

def get_embedder(config) -> EmbeddingProvider: ...
def get_vector_store(config) -> VectorStore: ...
def get_messaging_platform(platform, **kwargs) -> MessagingPlatform: ...
```

Callers never import a specific adapter class. One config value → correct object.
All imports are lazy (inside match cases) — only loads what's actually configured.

---

### Repository Pattern
**File:** `core/bitmod/interfaces/database.py:124` — `DatabaseBackend` ABC

Business logic calls named methods. Zero SQL anywhere outside adapters.

```python
# Business logic (cache_engine.py) — no SQL, no DB driver imports
backend.cache_lookup(session, answer_key)
backend.cache_store(session, record)
backend.cache_invalidate_by_section(session, section_id)
backend.hybrid_search(session, query, embedding, limit, ...)

# SQLite adapter (adapters/db_sqlite.py) — actual SQL here
# PostgreSQL adapter (adapters/db_postgresql.py) — different SQL here
```

---

### Strategy Pattern
**Files:** `core/bitmod/router.py` + `services/chat/app/main.py:49`

At startup, factory picks two strategies from config:
```python
primary = get_llm(config.llm)            # e.g. OllamaAdapter
fallback = make_llm(config.llm.fallback) # e.g. AnthropicAdapter
llm = LLMRouter(primary, fallback)
```

At runtime, router tries primary → retries → falls back to secondary:
```python
class LLMRouter:
    async def generate(self, messages):
        for attempt in range(self._max_retries):
            try: return await self._primary.generate(...)
            except: pass
        if self._fallback:
            return await self._fallback.generate(...)
        raise RuntimeError("All LLM providers failed")
```

Intent→role→model_tier selection is also Strategy:
`role_registry.resolve(detected)` picks different model tier, token budget,
system prompt based on detected intent. Same question, different intent = different strategy.

---

### Chain of Responsibility
**File:** `services/chat/app/main.py:317`

Each cache layer either handles the request (returns) or passes it down:

```
Layer 1: Exact cache    → HIT? return immediately. MISS? continue.
Layer 2: Semantic cache → HIT? return immediately. MISS? continue.
Layer 3: Composable     → FULL HIT? return. PARTIAL? generate missing only. MISS? continue.
Layer 4: Fuzzy match    → HIT? use as LLM context. MISS? continue.
Final:   LLM call       → always handles. end of chain.
```

The LLM call is the last-resort handler. Every layer above it exists to avoid reaching it.

---

### Decorator Pattern (Middleware Stack)
**File:** `services/gateway/app/main.py:123`

6 middleware functions wrap every request:
```
Request
  → correlation_id_middleware (assign/read X-Correlation-ID, log start/end)
  → enforce_body_size (1MB default, 50MB for /v1/ingest/*)
  → csrf_protection (require X-Requested-With on state-changing requests)
  → security_headers (X-Frame-Options, HSTS, CSP, Cache-Control)
  → rate_limit (60/min chat, 120/min search, 10/min ingest)
  → timing (X-Response-Time header)
  → actual handler
```

Each middleware calls `await call_next(request)` to pass through. Handlers have no
knowledge that any of this wrapping exists.

---

### Proxy Pattern
**File:** `services/gateway/app/main.py:324`

Gateway stands between clients and Chat service:
1. SSRF check — target hostname must be in `_ALLOWED_PROXY_HOSTS` whitelist
2. Strip dangerous headers (host, connection, proxy-authorization, te, trailers, upgrade)
3. Forward request via `httpx.AsyncClient`
4. Strip dangerous response headers
5. Return response to client

Gateway IS a security proxy. Clients think they're talking to the AI brain.
They're actually talking to a hardened firewall that enforces all security rules.

---

### Command Pattern
**File:** `core/bitmod/action_plans.py`

AI agent plans are serialized as data and stored for replay:
```python
@dataclass
class PlanStep:
    tool: str             # "search_database"
    parameters: dict      # {"query": "{jurisdiction} refund policy"}
    output_binding: str   # "search_results"

@dataclass
class ActionPlan:
    steps: list[PlanStep]     # serialized commands
    parameter_slots: dict     # typed slots filled at execution time
    allowed_tools: list[str]  # security boundary
    hmac_signature: str       # tamper-proof HMAC-SHA256 seal
```

LLM reasons through task ONCE → plan stored in DB → next invocation replays the plan
with new parameters, zero LLM call. HMAC signature ensures nobody tampers with stored steps.

---

### Observer Pattern (Event-Driven Cache Invalidation)
**File:** `core/bitmod/invalidation.py:19`

When source document content changes, all dependent cache entries auto-invalidate:
```python
def process_change_event(backend, session, section_id, new_content):
    old_hash = backend.get_section_version_hash(session, section_id)
    new_hash = sha256(new_content)
    if old_hash != new_hash:
        invalidated = backend.cache_invalidate_by_section(session, section_id)
        # → marks all answer_cache rows with this section_id as is_valid=false
```

The `source_sections` JSONB column in `answer_cache` is the subscription list —
"these are the sections I depend on." When any section changes, subscribers auto-invalidate.

---

## 2. Technical Debt & Brittle Areas (Ranked by Risk)

### 🔴 CRITICAL #1 — God Function: the entire pipeline in one 360-line function

**File:** `services/chat/app/main.py:220`

The `chat()` function handles 13 distinct concerns sequentially:
sanitize → normalize → detect_intent → resolve_role → deterministic_check →
exact_cache → semantic_cache → composable_cache → fuzzy_match →
hybrid_search → llm_generate → store_cache → record_conversation

Has 7 different early-return paths. Testing any one layer in isolation is nearly impossible.
A bug in one layer can silently return a wrong answer that looks like a cache hit.

**Impact:** The highest-risk file in the codebase. Any change to this function risks
breaking the entire request pipeline.

---

### 🔴 CRITICAL #2 — Tier 2 and Tier 3 Intent Detection Don't Exist

**File:** `core/bitmod/intent.py:1`

The docstring says:
```
Tier 2 — Classifier: lightweight local model (future)
Tier 3 — LLM: fallback for ambiguous queries (future)
```

Both are marked "future". The 3-tier system is actually 1 tier (regex only).

When no regex matches:
```python
# chat/main.py:253
detected = detect_intent(message)
if detected is None:
    detected = DetectedIntent(
        action=IntentAction.QA,   # ← hardcoded, QA not in the enum
        confidence=0.5,           # ← meaningless value
        skip_llm=False,
        cacheable=True,
    )
```

`IntentAction.QA` does not exist in the `IntentAction` enum — this is a phantom value.
Every non-matching query silently becomes QA/0.5, triggering wrong role, wrong model tier,
wrong token budget, wrong compression level. All silently wrong.

---

### 🔴 CRITICAL #3 — DatabaseBackend ABC Has Silent No-Op Default Implementations

**File:** `core/bitmod/interfaces/database.py:124`

The interface has two types of methods mixed:
```python
@abstractmethod
def cache_lookup(self, session, answer_key): ...    # must implement or fail at startup

def namespace_create(self, session, ns): ...        # default = silent no-op
def store_api_key(self, session, record): ...       # default = silent no-op
def track_usage(self, session, ...): ...            # default = silent no-op
def lookup_api_key(self, session, hash): return None # default = silent None
```

15+ methods have working (empty) defaults. If `db_mongodb.py` doesn't implement
`track_usage()`, it silently does nothing. No error, no warning, no test failure.
You discover this in production when usage stats are empty.

**Should be:** Split into multiple interfaces — `CacheBackend`, `AuthBackend`,
`UsageBackend`, `NamespaceBackend`. Each adapter only implements what it supports.

---

### 🟠 HIGH #4 — Gateway is 1700+ Lines, 11 Responsibilities in One File

**File:** `services/gateway/app/main.py`

Handles: CORS, 6 middleware functions, Prometheus, proxy (chat+search), ingestion,
4 compatibility proxy layers (OpenAI/Anthropic/Gemini/Ollama), auth (4 endpoints),
usage tracking (2 endpoints), namespace management (5 endpoints), admin metrics,
provider health detection.

Any merge conflict anywhere touches everything. Debugging a namespace issue
requires scrolling past proxy code.

---

### 🟠 HIGH #5 — `decompose_query()` Only Handles US States + Fragile Regex

**File:** `core/bitmod/cache_engine.py:234`

Composable decomposition — one of BITMOD's key patent claims — only works for:
1. Queries with 2+ valid US state codes ("compare CA vs NY policy")
2. "X and Y" / "X vs Y" pattern — with fragile edge cases:
   - Breaks on 3+ topics ("Python and Java and Go")
   - "find X and show Y" partially handled via heuristic (fragile)
   - Empty topic sides not fully guarded

The `and` keyword regex will match "find documents and show them" — a non-comparison —
potentially decomposing it incorrectly.

---

### 🟠 HIGH #6 — 5-6 Separate DB Sessions Per Request (Race Condition Risk)

**File:** `services/chat/app/main.py:320`

Each cache layer opens and closes its own DB session:
```
Session 1: exact cache lookup
Session 2: semantic cache lookup
Session 3: composable cache lookup
Session 4: fuzzy match
Session 5: store answer
```

Comments like "Eagerly extract all needed data before session closes" appear multiple times —
sign that session lifecycle is poorly understood. In SQLite (default), each session =
separate file lock acquisition. Under load = 5 lock acquisitions per request.
Race condition: a cache entry could be written between lookup and store sessions.

---

### 🟡 MEDIUM #7 — 23 of 30+ Intent Actions Have No YAML Config

**Files:** `core/bitmod/intents/*.yaml` (14 files) vs `core/bitmod/intent.py:29` (30+ enum values)

Intents with no YAML: QUOTE, REFERENCE, LOOKUP, FIND, SHOW, CONTRAST, PARAPHRASE,
TRANSLATE, THEORIZE, EVALUATE, DEBATE, PREDICT, BUILD, DEPLOY, TRANSFORM,
COUNT, CALCULATE, VALIDATE, WRITE, GENERATE, COMPOSE, CLARIFY, UNKNOWN

When `intent_registry.get_for_action(detected.action)` returns None:
```python
compression = intent_config.compression if intent_config else None
token_budget = intent_config.token_budget if intent_config and ... else 4096
```
Silent None fallbacks — no error, no log warning, just defaults applied silently.

---

### 🟡 MEDIUM #8 — Cache Threshold Order is Logically Inverted

**File:** `services/chat/app/main.py:356`

```python
# More accurate method — stricter gate:
semantic_cache_match(..., threshold=0.92)   # cosine embedding similarity

# Less accurate method — looser gate:
fuzzy_match(..., similarity_threshold=0.90) # Jaccard token overlap
```

Embedding similarity (more accurate) requires 0.92. Fuzzy/Jaccard (less accurate) requires 0.90.
A 0.90 Jaccard match is much noisier than a 0.90 cosine similarity match.
Means: mediocre fuzzy match can serve an answer that strong semantic match correctly rejected.

---

## 3. Complete API Reference

### Gateway Service (Port 8000, Public)

#### System
| Method | Endpoint | Auth | Handler |
|--------|----------|------|---------|
| GET | `/health` | None | Inline → `HealthResponse` |
| GET | `/metrics` | None | `prometheus_client.generate_latest()` |

#### Core AI (proxied to Chat service port 8001)
| Method | Endpoint | Auth | Handler |
|--------|----------|------|---------|
| GET/POST | `/v1/chat` | None | Proxy → Chat `/v1/chat` |
| GET/POST | `/v1/search` | None | Proxy → Chat `/v1/search` |

#### Ingestion (runs directly on Gateway, NOT proxied)
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| POST | `/v1/ingest/text` | `write` | `ingestion/pipeline.py → ingest_text()` |
| POST | `/v1/ingest/file` | `write` | `ingestion/pipeline.py → ingest_file()` |
| GET | `/v1/ingest/status` | `read` | `db.document_stats()` |

#### Compatibility Proxies (drop-in replacement for existing apps)
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| POST | `/v1/chat/completions` | `read` | `proxy/openai_format.py → handle_completion()` |
| GET | `/v1/models` | None | `proxy/openai_format.py → handle_models()` |
| POST | `/v1/messages` | `read` | `proxy/anthropic_format.py → handle_anthropic()` |
| POST | `/v1beta/models/{model}:generateContent` | `read` | `proxy/gemini_format.py → handle_gemini()` |
| POST | `/v1beta/models/{model}:streamGenerateContent` | `read` | `proxy/gemini_format.py → handle_gemini_stream()` |
| POST | `/api/chat` | `read` | Converts to OpenAI format → `proxy/openai_format.py` |
| GET | `/api/tags` | None | `proxy → handle_models()` in Ollama format |

#### Observability & Admin
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| GET | `/v1/cache/stats` | `read` | `cache_engine.get_cache_stats()` |
| GET | `/v1/admin/metrics` | `admin` | cache + document_stats + provider detection |
| POST | `/v1/reload` | `admin` | Proxy → Chat `/v1/reload` |

#### Auth & API Keys
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| GET | `/v1/auth/status` | None | `auth.is_auth_enabled()` |
| POST | `/v1/auth/keys` | `admin` | `auth.APIKeyManager.create_key()` |
| GET | `/v1/auth/keys` | `admin` | `auth.APIKeyManager.list_keys()` |
| DELETE | `/v1/auth/keys/{key_id}` | `admin` | `auth.APIKeyManager.revoke_key()` |
| POST | `/v1/auth/token` | None | `auth.create_jwt_token()` (token exchange) |

#### Usage & Billing
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| GET | `/v1/usage` | `read` | `usage.UsageTracker.get_summary()` |
| GET | `/v1/usage/export` | `read` | `usage.UsageTracker` export |

#### Multi-Tenancy
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| POST | `/v1/namespaces` | `admin` | `namespaces.NamespaceManager.create()` |
| GET | `/v1/namespaces` | `admin` | `namespaces.NamespaceManager.list_all()` |
| GET | `/v1/namespaces/{id}` | `admin` | `namespaces.NamespaceManager.get()` |
| DELETE | `/v1/namespaces/{id}` | `admin` | `namespaces.NamespaceManager.delete()` |
| GET | `/v1/namespaces/{id}/stats` | `admin` | `db.namespace_cache_stats()` |

#### Project Knowledge (added Mar 25 2026)
| Method | Endpoint | Auth Scope | Handler |
|--------|----------|------------|---------|
| POST | `/v1/projects` | `write` | Create project registration |
| GET | `/v1/projects` | `read` | List all projects |
| GET | `/v1/projects/{project_id}` | `read` | Get project details |
| DELETE | `/v1/projects/{project_id}` | `admin` | Delete project + all its data |
| POST | `/v1/projects/{project_id}/scan` | `write` | Trigger file scan + indexing |
| GET | `/v1/history` | `read` | Retrieve conversation history |
| POST | `/v1/conversations/{id}/rate` | `write` | Rate a conversation (1-5) |
| POST | `/v1/conversations/{id}/correct` | `write` | Submit correction for a response |
| POST | `/v1/context` | `read` | Assemble project context for a query |

### Chat Service (Port 8001, Internal Only)

Requires `X-Internal-Token` header OR must come from localhost.

| Method | Endpoint | Handler |
|--------|----------|---------|
| GET | `/health` | Inline `HealthResponse` |
| POST | `/v1/chat` | Full 9-layer pipeline (see Section 5) |
| POST | `/v1/search` | `db.hybrid_search()` FTS + vector |
| POST | `/v1/reload` | `intent_registry.reload()` + `role_registry.reload()` |

### Auth Scopes
| Scope | Allows |
|-------|--------|
| `read` | Query, search, cache stats, usage |
| `write` | Ingest documents |
| `ingest` | Ingest only (narrower than write) |
| `admin` | Everything — keys, namespaces, metrics, reload |

### OpenAPI/Swagger
Auto-generated by FastAPI. Access at `http://localhost:8000/docs`
Disable in production: set `BITMOD_DISABLE_DOCS=1`

---

## 4. Database Entity Relationships

### Full Relationship Map
```
namespaces
    └──► documents           (namespace_id → namespaces.id)
              └──► sections  (document_id → documents.id)
                        ├──► chunks              (section_id → sections.id)
                        │      └── embedding vector(384)
                        ├──► content_blocks      (section_id → sections.id)
                        │      └── compression: full/structured/headline
                        ├──► section_tags        (section_id → sections.id)
                        └──► section_relationships (section_a_id + section_b_id)

answer_cache
    └── source_sections JSONB → informal references to section IDs
    └── previous_version_id → answer_cache.id (self-referencing version chain)

action_plans
    └──► plan_approvals   (plan_id → action_plans.id)
    └──► plan_executions  (plan_id → action_plans.id)

source_monitors
    └──► change_events    (monitor_id → source_monitors.id)
              └──► notifications (change_event_id → change_events.id)

subscriptions
    └──► notifications    (subscription_id → subscriptions.id)

cache_metrics    — standalone append-only analytics log
data_gaps        — standalone unanswered query log
usage_tracking   — standalone per-API-key per-day billing
```

### New Tables Added Mar 25 2026 — Project Knowledge System (Migration 006)

```
projects             ← registered project roots (name, root_path, language, framework)
project_files        ← every indexed file (relative_path, file_hash, language, chunk_count)
project_chunks       ← code chunks with symbol info (symbol_name, symbol_type, start/end_line, embedding BLOB)
conversations        ← every Q&A recorded (user_message, assistant_response, cache_hit, rating, feedback)
conversation_embeddings ← embeddings for semantic conversation search (1:1 with conversations)
corrections          ← user-submitted corrections (original_question, corrected_answer, project_id)
```

These 6 tables form a separate knowledge graph alongside the document corpus.
`project_id` is now threaded through `documents`, `answer_cache`, and `conversations`
for full namespace-level scoping.

### The Center of the Data Model: `sections`

6 tables point to or reference `sections`:
- `chunks` → `sections.id`
- `content_blocks` → `sections.id`
- `section_tags` → `sections.id`
- `section_relationships` → `sections.id` (as both A and B)
- `answer_cache.source_sections` → section IDs informally
- `cache invalidation` → triggered BY section content changes
- `change_events.affected_sections` → section IDs

**Two centers by perspective:**
- Data model center → `sections` (everything points here)
- Product value center → `answer_cache` (this is what BITMOD delivers)

`sections` = raw material. `answer_cache` = finished product.

### Key Fields That Make the System Work
- `sections.version_hash` — SHA-256 of content. Changed = cache invalidated.
- `sections.is_current` — soft delete pattern. Old versions kept for audit.
- `answer_cache.answer_key` — SHA-256 composite key (query+filters+tenant+language)
- `answer_cache.source_sections` — JSON list of {section_id, version_hash} pairs
- `answer_cache.serve_count` — how many times this cached answer was served
- `answer_cache.storage_tier` — hot/warm/cold for tiered eviction
- `chunks.embedding` — vector(384) for cosine similarity search

---

## 5. End-to-End Request Lifecycle: POST /v1/chat

### What Happens When a User Asks a Question

```
POST http://localhost:8000/v1/chat
{"message": "What is the refund policy?", "filters": {"jurisdiction": "CA"}, "stream": false}
```

### Phase 0 — Gateway Middleware Chain (before any handler)

All 6 middleware run in sequence on EVERY request:

1. **CORS** — checks Origin header, blocks if not in `cors_origins`
2. **Prometheus** — wraps request for metrics recording
3. **Correlation ID** (`gateway/main.py:123`) — reads `X-Correlation-ID` or generates UUID, logs "Request started"
4. **Body Size** (`gateway/main.py:163`) — 1MB limit (50MB for `/v1/ingest/*`), returns 413 if exceeded
5. **CSRF** (`gateway/main.py:195`) — POST must have `X-Requested-With` header (when auth disabled), returns 403
6. **Security Headers** (`gateway/main.py:212`) — adds X-Frame-Options: DENY, HSTS, X-Content-Type-Options, Cache-Control: no-store
7. **Rate Limit** (`gateway/main.py:244`) — 60/min for `/v1/chat`, per IP. Returns 429 + Retry-After if exceeded
8. **Timing** — records start time, adds X-Response-Time to response

### Phase 1 — Gateway Handler (gateway/main.py:324)

- SSRF check: verifies Chat service hostname is in `_ALLOWED_PROXY_HOSTS`
- Path sanitization: regex `[a-zA-Z0-9/_-]` only
- Strip dangerous headers before forwarding
- Forward via `httpx.AsyncClient.post()` to `chat_service_url/v1/chat`

### Phase 2 — Chat Service Middleware (chat/main.py:79)

Single middleware: internal auth check.
- If `BITMOD_INTERNAL_TOKEN` set → require exact match in `X-Internal-Token` header
- If not set → only allow `127.0.0.1` / `localhost` / `::1`
- Returns 403 if check fails.

### Phase 3 — Pydantic Validation (automatic, before handler runs)

```python
class ChatRequest(BaseModel):
    message: str   # min_length=1, max_length=10000
    history: list[ChatMessage]  # max 50 items
    filters: dict
    stream: bool
    project_id: str | None
```

If JSON doesn't match → FastAPI returns 422 automatically, handler never called.

### Phase 4 — Sanitization & Normalization (chat/main.py:245)

```
"What is the refund policy?"
  → sanitize_input()     strip HTML, remove prompt injection patterns
  → normalize_query()    lowercase → remove punctuation → remove stopwords → sort tokens
                         result: "policy refund"
  → compute_answer_key() SHA-256("policy refund|jurisdiction:CA|proj:my-project")
                         result: "a3f92b1c8e4d..." (64-char hex)
```

NOTE (updated Mar 25 2026): `project_id` is now part of the cache key.
Same question asked in project A vs project B → different cache entries.
`ChatRequest.project_id` flows through: normalization → cache key → generate → record_conversation.

### Phase 5 — Intent Detection (chat/main.py:256)

```
Tier 1: regex patterns (intent.py PATTERNS list)
  "What is" → EXPLAIN intent, confidence 0.7, mode INFORMATIONAL
  → role_registry.resolve() → NARRATOR role
  → model_tier: primary, max_tokens: 4096, compression: full
```

PipelineStep recorded: mechanism="intent_detection", action="explain", elapsed_ms=1.2

### Phase 6 — Skip-LLM Check (chat/main.py:286)

`detected.skip_llm` = False for EXPLAIN intent → skip this path.
(Only EXTRACT/COUNT/CONVERT/CALCULATE/VALIDATE skip the LLM)

### Phase 7 — 4-Layer Cache Pipeline (all DB reads)

**Layer 1 — Exact Cache** (`cache_engine.try_cache()`):
```
DB READ: SELECT * FROM answer_cache WHERE answer_key = 'a3f92b1c...' AND is_valid = true
MISS → continue
(on HIT: double_verify() checks all source section hashes, then increment serve_count)
```

**Layer 2 — Semantic Cache** (`cache_engine.semantic_cache_match()`, only if embedder available):
```
embed("What is the refund policy?") → [0.23, -0.15, ...] (384 floats)
DB READ: query_embeddings table, cosine similarity threshold 0.92
MISS → continue
```

**Layer 3 — Composable Cache** (`cache_engine.try_composable_cache()`):
```
decompose_query("What is the refund policy?") → None (not decomposable)
SKIP → continue
```

**Layer 4 — Fuzzy Match** (`cache_engine.fuzzy_match()`):
```
DB READ: answer_cache WHERE similarity(question_normalized, 'policy refund') > 0.90
(PostgreSQL: pg_trgm index. SQLite: Jaccard overlap in Python)
MISS → continue (used as LLM context if HIT)
```

### Phase 8 — Hybrid Search (document retrieval)

```
db.hybrid_search(
    query="What is the refund policy?",
    embedding=[0.23, -0.15, ...],
    limit=10, jurisdiction="CA"
)
Runs TWO queries, merges results:
  1. FTS: sections WHERE search_vector @@ to_tsquery('refund & policy')
  2. Vector: chunks ORDER BY embedding <=> query_vector LIMIT 10
Returns: list[SearchResult] ranked by relevance
```

### Phase 8b — Project Context Injection (added Mar 25 2026)

Before the LLM call, if `project_id` is set, `ContextAssembler` runs:

```
ContextAssembler.assemble(query, project_id) → AssembledContext

Token budget: 8000 total, split as:
  50% → relevant project code chunks (project_chunks table, semantic search)
  25% → related past conversations (conversations + conversation_embeddings)
  10% → user corrections (corrections table)
  15% → cache-retrieved context

AssembledContext.full_context injected into system prompt:
  ## Relevant Project Code
  [matched code chunks with file path + line numbers]

  ## Previous Corrections
  [user-submitted corrections that match this query]

  ## Related Past Conversations
  [semantically similar past Q&A pairs]
```

This happens BEFORE the LLM call, AFTER cache miss — so project context
enriches the prompt when generating a fresh answer.

### Phase 9 — LLM Call (`router.py`)

```
Build messages: [
  {role: system, content: narrator_role_prompt},
  {role: user,   content: "Context:\n[retrieved sections]\n\nQuestion: ..."}
]
LLMRouter.generate(messages, max_tokens=4096):
  → primary.generate() (e.g. OpenAIAdapter → POST api.openai.com)
  → retry up to 2 times on failure
  → fallback.generate() if primary fails
→ LLMResponse(content="The refund policy states...", tokens_used=312)
```

### Phase 10 — Cache Store

```
embedder.embed(norm_query) → query_embedding (for future semantic lookups)
DB WRITE: INSERT INTO answer_cache (
    answer_key, question_raw, question_normalized, filters,
    answer_text, source_sections, model_used, generation_ms,
    serve_count=0, storage_tier='warm', is_valid=true
)
source_sections = [{"section_id": "abc...", "version_hash": "xyz..."}]
  ↑ This is what double_verify() checks on every future cache HIT
```

### Phase 11 — Response

```python
ChatResponse(
    answer="The refund policy states that...",
    cached=False,
    cache_key="a3f92b1c...",
    sources=[{"citation": "§4.2", "title": "Returns Policy"}],
    model_used="gpt-4",
    generation_ms=847,
    pipeline_trace=[
        PipelineStep(mechanism="normalization",    action="DONE",    elapsed_ms=0.3),
        PipelineStep(mechanism="intent_detection", action="explain", elapsed_ms=1.2),
        PipelineStep(mechanism="exact_cache",      action="MISS",    elapsed_ms=3.1),
        PipelineStep(mechanism="semantic_cache",   action="MISS",    elapsed_ms=12.0),
        PipelineStep(mechanism="fuzzy_match",      action="MISS",    elapsed_ms=14.2),
        PipelineStep(mechanism="llm_generation",   action="DONE",    elapsed_ms=861.0),
        PipelineStep(mechanism="cache_store",      action="STORED",  elapsed_ms=863.5),
    ]
)
```

Response travels back: Chat → Gateway (security headers + X-Response-Time added) → Client.

### Timeline Summary

```
t=0ms    Request arrives at Gateway
t=0.5ms  Correlation ID assigned
t=1ms    Body size + CSRF + rate limit checks pass
t=2ms    Forwarded to Chat service
t=2.5ms  Internal token verified
t=3ms    Pydantic validation passes
t=4ms    sanitize + normalize + compute_answer_key
t=5ms    detect_intent → EXPLAIN
t=6ms    DB session → exact cache → MISS
t=18ms   Semantic cache → MISS
t=20ms   Fuzzy match → MISS
t=22ms   hybrid_search → 8 sections retrieved
t=25ms   LLM messages assembled
t=872ms  LLM API returns answer
t=875ms  DB WRITE → answer cached
t=877ms  ChatResponse returned to Gateway
t=879ms  Security headers + timing header added
t=879ms  Delivered to client
```

**Second time same question asked: t=8ms total. Zero LLM cost.**

---

## 6. Chat vs Search — The Key Distinction

### `/v1/chat` (POST)
- **Input:** Natural language question
- **Output:** Full written answer (synthesized by LLM or from cache)
- **Calls LLM:** Yes (if cache miss)
- **Uses cache:** Yes, 4-layer cache
- **Intent detection:** Yes
- **Streaming:** Yes
- **Cost:** Can be expensive (LLM call on cache miss)
- **Handler:** Chat service full pipeline

### `/v1/search` (POST)
- **Input:** Search query / keywords
- **Output:** List of matching document sections with relevance scores
- **Calls LLM:** Never
- **Uses cache:** No
- **Intent detection:** No
- **Streaming:** No
- **Cost:** Always free (DB query only)
- **Handler:** `db.hybrid_search()` directly

### Mental Model
- **Search** = "show me the raw pages in the book that mention refunds"
- **Chat** = "read those pages and write me a proper answer"

Search is raw retrieval. Chat uses search internally as one step, then passes results to LLM.
`/v1/search` is literally a subset of what `/v1/chat` does — exposed separately for
when you want raw documents without AI synthesis.

---

## 7. The Intent System — Full Picture

### Intent Actions (30+ defined in IntentAction enum)
```
Passive retrieval:  CITE, LIST, QUOTE, REFERENCE, LOOKUP, FIND, SHOW
Synthesis:          SUMMARIZE, EXPLAIN, COMPARE, CONTRAST, PARAPHRASE, TRANSLATE
Reasoning:          THINK, HYPOTHESIZE, ANALYZE, THEORIZE, EVALUATE, DEBATE, PREDICT
Agentic:            EXECUTE, BUILD, DEPLOY, TRANSFORM
Deterministic:      EXTRACT, CONVERT, COUNT, CALCULATE, VALIDATE  ← skip LLM
Creative:           BRAINSTORM, CREATE, WRITE, DRAFT, GENERATE, COMPOSE  ← not cacheable
Meta:               CLARIFY, UNKNOWN
```

### What "skip_llm" means
5 intents (EXTRACT, CONVERT, COUNT, CALCULATE, VALIDATE) have `skip_llm=True`.
For these, `_handle_deterministic()` runs: does a DB search, extracts entities/counts
from results, returns an answer WITHOUT calling any LLM. Zero cost, zero latency.

### What "not cacheable" means
3 intents (BRAINSTORM, CREATE, COMPOSE) have `cacheable=False`.
Creative outputs are intentionally non-deterministic — caching them would defeat the purpose.

### YAML Config Files (14 exist, ~23 missing)
Each YAML defines: model_tier, token_budget, cache_ttl, compression, system_prompt.
Missing YAMLs → `intent_registry.get_for_action()` returns None → silent fallbacks.

### Regex Pattern Engine
`PATTERNS` list in `intent.py:227` — ~80+ regex patterns.
Ordered by specificity. First match at highest confidence wins.
Examples:
- `r"^list\b"` → LIST, confidence 1.0
- `r"\bhow many\b"` → COUNT, confidence 0.9
- `r"^what\s+(?:is|are|was|were)\b"` → EXPLAIN, confidence 0.7

---

## 8. Key Architectural Decisions (with Reasoning)

| Decision | Why |
|----------|-----|
| Library-first, not service-first | Works with `pip install bitmod`, no infra needed. Services layer is optional. |
| 4 database backends | Enterprise customers have existing DBs — can't force migration |
| 3-tier intent detection (planned) | Balance cost vs accuracy: 70% queries with $0 regex, 5% needing LLM |
| Content blocks (3 compressions) | Serve from pre-computed blocks = zero generation cost on hit |
| HMAC on action plans | Agent plans must not be tampered with after approval |
| FTS5 in SQLite | Full-text search without Elasticsearch dependency |
| 9-layer cache | Progressive fallback — always try cheapest layer first |
| Namespace isolation | Multi-tenant from day one — avoids costly refactoring later |
| Adapter pattern for everything | Contributors can add providers without touching business logic |
| Apache 2.0 license | Enterprise-friendly, allows commercial use |
| SHA-256 composite cache key | Same question asked differently → same key via normalization |
| `source_sections` manifest in cache | Enables precise invalidation — only stale entries removed |

---

---

## 9. Project Knowledge System (Added Mar 25 2026)

### What It Is

A new subsystem that makes BITMOD aware of your actual codebase.
Instead of only searching ingested documents, BITMOD can now:
- Index your project's source files (40+ languages)
- Remember every conversation it has had
- Learn from user corrections
- Inject relevant code + history + corrections into LLM prompts automatically

Commits: `891cd54` (system) + `4dfc4fb` (pipeline integration)

### New Module: `core/bitmod/project/`

```
project/__init__.py      ← module exports
project/indexer.py       ← scans files, extracts symbols, creates chunks
project/memory.py        ← ConversationMemory class: records + searches conversations
project/context.py       ← ContextAssembler class: builds token-budgeted context
project/watcher.py       ← watches filesystem for changes (watchdog + polling fallback)
project/language.py      ← detects language + framework for 40+ languages
```

### How Indexing Works (`project/indexer.py`)

```
1. Walk project root directory
2. For each file: detect_language() → should_index() → skip binaries/build dirs
3. Extract symbols via regex (no AST parser needed):
   - Python: def/class
   - TypeScript: function/class/interface/type
   - Go: func/struct/interface
   - Rust: fn/struct/trait/enum
   - Java, C, C++, Ruby, etc.
4. Chunk by lines (60 lines/chunk, 10 line overlap)
5. Store to: project_files table + project_chunks table
6. Embed each chunk (optional) → stored as BLOB in project_chunks.embedding
```

File change detection: SHA-256 hash of file contents. Re-indexes only changed files.

### How Context Assembly Works (`project/context.py`)

When `project_id` is in the request, `ContextAssembler.assemble()` runs before LLM call:

```
Token budget: 8000 (configurable)
  ├── 50% (4000 tokens) → project code chunks
  │     semantic search over project_chunks embeddings
  │     returns: file path, line range, symbol name, code snippet
  ├── 25% (2000 tokens) → past conversations
  │     semantic search over conversation_embeddings
  │     returns: similar Q&A pairs from history
  ├── 10% (800 tokens)  → corrections
  │     keyword match over corrections table
  │     returns: "user said this answer was wrong, correct answer is X"
  └── 15% (1200 tokens) → cache-retrieved context

Output: AssembledContext with .full_context string injected into system prompt
```

### How Conversation Memory Works (`project/memory.py`)

Every `/v1/chat` response is automatically recorded:
```python
ConversationMemory.record(
    user_message=message,
    assistant_response=answer_text,
    model_used=model_used,
    cache_hit=cached,
    generation_ms=elapsed_ms,
    project_id=project_id,
    context_used=[...]       # what context was used to generate the answer
)
```

If embedder available: embeds the user_message → stored in `conversation_embeddings`.
This enables semantic search ("find past conversations similar to this query").

### How Corrections Work

Users can correct a bad answer via `POST /v1/conversations/{id}/correct`:
```json
{"corrected_answer": "The actual correct answer is...", "note": "Model was wrong about X"}
```

Stored in `corrections` table with `project_id`. Future queries that semantically
match the original question get the correction injected into context:
```
## Previous Corrections
Q: [original question]
Original answer was incorrect. Correction: [corrected_answer]
Note: [user note]
```

### New `search_project` Tool (`core/bitmod/tool_layer.py`)

The LLM can now call `search_project` during its tool-calling loop:
```python
{
    "name": "search_project",
    "description": "Search project code, symbols, past conversations, and corrections",
    "parameters": {
        "query": str,
        "search_type": "code" | "conversations" | "corrections" | "all",
        "project_id": str,
        "limit": int
    }
}
```

This means the LLM itself can proactively search project knowledge mid-generation,
not just receive context passively. Added ~162 lines to `tool_layer.py`.

### Impact on Cache Key

`project_id` is now part of `compute_answer_key()`:
```python
# cache_engine.py
if project_id:
    parts.append(f"proj:{project_id}")
composite = "|".join(parts)
return hashlib.sha256(composite.encode()).hexdigest()
```

Same question in different projects → different cache entries.
Cross-project cache sharing requires explicit namespace federation (existing feature).

### New DB Tables (Migration 006)

| Table | Purpose | Key fields |
|-------|---------|-----------|
| `projects` | Registered project roots | root_path (unique), language, framework, last_scanned_at |
| `project_files` | Every indexed file | project_id, relative_path, file_hash, chunk_count |
| `project_chunks` | Code chunks with symbols | file_id, symbol_name, symbol_type, start/end_line, embedding BLOB |
| `conversations` | Every Q&A recorded | project_id, user_message, assistant_response, cache_hit, rating |
| `conversation_embeddings` | Embeddings for semantic search | 1:1 with conversations |
| `corrections` | User-submitted fixes | project_id, original_question, corrected_answer |

### New API Endpoints (Gateway, all added in this commit)

| Method | Endpoint | What it does |
|--------|----------|-------------|
| POST | `/v1/projects` | Register a new project root path |
| GET | `/v1/projects` | List all registered projects |
| GET | `/v1/projects/{id}` | Get project details + stats |
| DELETE | `/v1/projects/{id}` | Delete project + cascades all files/chunks |
| POST | `/v1/projects/{id}/scan` | Trigger file scan + re-index |
| GET | `/v1/history` | Retrieve conversation history (filterable by project) |
| POST | `/v1/conversations/{id}/rate` | Rate a response 1-5 |
| POST | `/v1/conversations/{id}/correct` | Submit a correction |
| POST | `/v1/context` | Assemble context for a query (debug/inspection endpoint) |

### How It Connects to the Existing System

```
BEFORE (original pipeline):
  query → intent → cache → hybrid_search(documents) → LLM → cache_store

AFTER (with project knowledge):
  query + project_id
    → intent
    → cache (key now includes project_id)
    → hybrid_search(documents)          ← still happens
    → ContextAssembler.assemble()       ← NEW: pulls code + history + corrections
    → LLM(prompt + assembled_context)  ← context-enriched prompt
    → cache_store
    → ConversationMemory.record()       ← NEW: saves Q&A for future retrieval
```

Document corpus (ingested PDFs/text) and project knowledge (code + conversations) are
two separate data sources that both contribute to the final LLM prompt.

---

*Companion to CLAUDE_PROJECT_CONTEXT.md*
*For architecture overview, tech stack, directory structure → read that file first.*
*This file: patterns, debt, APIs, DB relationships, request lifecycle, project knowledge system.*
