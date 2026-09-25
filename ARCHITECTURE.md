# Bitmod Architecture

**Modular AI data infrastructure. Compute once, serve forever.**

---

## What Bitmod Is

Bitmod is a reverse proxy and semantic cache for LLM APIs. It sits between an application and
its model provider, serves repeated and rephrased queries from cache, and passes everything
else through. Optionally it also ingests documents, version-tracks them, and binds cached
answers to the source sections they came from so an answer is invalidated when its source
changes.

What follows describes the system that exists in this
repository. Anything not implemented is not described here.

---

## Services

Three deployables, plus a library.

| Component | Path | What it is |
|---|---|---|
| Gateway | `services/gateway/` | FastAPI reverse proxy. OpenAI, Anthropic and Gemini wire formats. Auth, rate limiting, CORS. |
| Chat | `services/chat/` | FastAPI SSE chat service with the full pipeline and document retrieval. |
| Frontend | `services/frontend/` | Next.js 15 admin dashboard, cache stats, playground. |
| Core library | `core/bitmod/` | Cache engine, adapters, interfaces, ingestion, CLI. Embeddable without any service. |

The cache engine is a library first. Both services embed it; neither owns it.

---

## The Answer Loop

```
Query → normalize → nine-layer lookup → accumulate confidence
  ↳ at or above serve_threshold: serve from cache, no LLM call
  ↳ below, with evidence: pass cached context to the LLM
  ↳ below, with none: generate, then store
```

Ingested documents add a second loop: a section's SHA-256 changes, the answers derived from
it are invalidated, and the next query regenerates. This is one hop, not a dependency-graph
walk.

---

## The Nine-Layer Cache Pipeline

Layers run in cost order: O(1) hash lookups first, embeddings second, scanning last. Each
contributes graded confidence rather than a hit or miss verdict, and a query can be served on
the combined evidence of several layers that none of them would carry alone.

| # | Layer | Method | Threshold |
|---|---|---|---|
| 1 | Normalization | Lowercase, stopword removal, SHA-256 composite key | always runs |
| 2 | Exact match | O(1) key lookup | exact |
| 3 | Source verification | SHA-256 hash per source section | any mismatch invalidates |
| 4 | Semantic similarity | Cosine on query embeddings | ≥ 0.88 serve, ≥ 0.60 retrieve |
| 5 | Composable decomposition | Sub-query splitting and partial reassembly | any sub-hit counts |
| 6 | Fuzzy match | Greater of token overlap and edit distance | ≥ 0.85 |
| 7 | Similarity link traversal | Learned near-miss graph, 2 hops | configurable strength |
| 8 | Atomic fact search | Embedding search over facts extracted from prior answers | ≥ 0.65 |
| 9 | Session context | Prior-turn injection from the session tracker | turn_count > 0 |

Composite key inputs: normalized query, model, namespace, role, and arbitrary sorted filter
key-value pairs. Sorting means `{a:1, b:2}` and `{b:2, a:1}` produce the same key.

### Evidence accumulation

```
pos_total = 1 - ∏(1 - cᵢ)
total_confidence = best + (pos_total - best) × damping     # damping ships at 0.50
```

Plain noisy-OR overstates when layers agree. Measured overstatement was +0.126 at two
contributing layers and +0.386 at three, against −0.006 at one, which is the control. Damping
corrects the combination step rather than any layer's own confidence. See
[ADR-004](docs/adr/004-damped-evidence-accumulation.md) and
`tests/benchmark/results/accumulation_fit.json`.

Negative evidence, such as a stale source hash or a context-dependent query signal, subtracts.

### Shipping thresholds

| Setting | Value | Env |
|---|---|---|
| `serve_threshold` | 0.85 | `BITMOD_CACHE_SERVE_THRESHOLD` |
| `semantic_threshold` | 0.88 | `BITMOD_CACHE_SEMANTIC_THRESHOLD` |
| `fuzzy_threshold` | 0.85 | `BITMOD_CACHE_FUZZY_THRESHOLD` |
| `search_threshold` | 0.60 | `BITMOD_CACHE_SEARCH_THRESHOLD` |
| `fact_min_similarity` | 0.65 | (config only) |
| `accumulation_damping` | 0.50 | `BITMOD_CACHE_ACCUMULATION_DAMPING` |

0.85 is a settled decision, not a default. At 0.80 the same corpus over-serves 158 of 375
questions that have nothing cached, against 0 at 0.85. Live sweep in
`tests/benchmark/results/support_heldout_warm_1500_at{085,080,075}.json`.

### Qualification gate

Before layers 2 and 5 may serve, and on the accumulated-confidence path, a gate rejects
context-dependent queries: bare acknowledgements, known anaphoric phrases, and short queries
that open with a pronoun and carry no subject of their own. Those route to the LLM instead.

### Post-generation learning

Every generation decomposes its answer into atomic facts and builds similarity links to
near-miss queries. Links weaken unless reinforced by successful serves. This is why layers 7
and 8 have anything to search.

---

## Source-Version Locking

Answers generated from ingested documents carry a manifest of the sections consulted, each
with its SHA-256 version hash. At serve time every hash is re-checked against the current
section; any mismatch invalidates the answer and falls through to generation.

**This does not cover every cached answer.** Answers cached by the reverse proxy have no
manifest: `proxy/base.py:1350` and `services/chat/app/main.py:471` store an empty
`source_sections`, and `double_verify` returns true immediately on an empty list. Those
answers were never derived from a document and have nothing to go stale against, but the
guarantee above is not what protects them. The paths that populate a manifest are
`api.py:520`, `api.py:671`, `main.py:1053` and `main.py:1680`.

---

## Intent, Roles and Blocks

Intent detection classifies how the user wants to be answered, not only what they asked, and
that classification selects the content compression level and the model tier. Intents are YAML
config in `core/bitmod/intents/`, so adding one is a config change. See
[ADR-003](docs/adr/003-yaml-driven-intents.md).

Roles scope the LLM's job and its token budget. A role carries a prompt, a budget and a model
tier, so a cheap model can do structuring while an expensive one does synthesis.

Content blocks are pre-computed per section at three compression levels: `full` for reasoning,
`structured` for comparison and citation, `headline` for listing. Blocks are regenerated when
their parent section changes.

---

## Data Model

Three tiers, plus blocks.

| Tier | Table | Purpose |
|---|---|---|
| 1 | `documents` | Top-level containers, any domain |
| 2 | `sections` | Coherent content units, full text intact, BM25 indexed, SHA-256 versioned |
| 3 | `chunks` | Paragraph splits for vector retrieval only; rendering always uses tier 2 |
| 3b | `content_blocks` | Pre-compressed content per section at three levels |

Cache tables in active use: `answer_cache`, `content_blocks`, `query_embeddings`, and the
namespace and audit tables.

`db/migrations/001_init.sql` also defines `action_plans`, `plan_executions`, `change_events`,
`source_monitors`, `data_gaps`, `subscriptions` and `cache_metrics`. **No Python reads or
writes any of them.** They are schema for features that were never built and are documented
here so nobody mistakes their presence for an implementation.

---

## Pluggable Providers

Hexagonal architecture: every external dependency sits behind an interface in
`core/bitmod/interfaces/`. See [ADR-001](docs/adr/001-hexagonal-architecture.md).

| Port | Adapters |
|---|---|
| LLM | 11 native (OpenAI, Anthropic, Gemini, Ollama, Bedrock, Azure, xAI, Mistral, Perplexity, OpenRouter, HuggingFace) plus 1 universal OpenAI-compatible |
| Database | SQLite (default), PostgreSQL, MySQL, MongoDB |
| Embeddings | Ollama, OpenAI, Cohere, local |
| Vector store | Qdrant, Chroma, Pinecone |

SQLite is the default so the project runs with no server. See
[ADR-002](docs/adr/002-sqlite-default-backend.md).

**Five capabilities are SQLite-only**, reached through `hasattr` so their absence is silent:
`cache_evict_lru`, `cache_delete_expired`, `store_atomic_fact`,
`increment_similarity_link_strength` and `namespace_cache_stats`. On PostgreSQL, MySQL and
MongoDB, layer 8 stores nothing, links are never reinforced, expired entries are never swept,
and `answer_cache` grows without bound. Expiry itself still works everywhere, because
`try_cache` checks on read. Every measurement in this repo was taken on SQLite.

---

## Search

Hybrid retrieval over ingested documents:

- **BM25** full-text over tier-2 sections
- **Vector** cosine over tier-3 chunks
- **Fusion** by configurable weight, re-ranked on the blended score
- Abbreviation expansion and filter scoping

`core/bitmod/vector_index.py` organises vectors by cluster centroid so a search compares
against centroids before candidates, rather than scanning every vector.

---

## Cache Maintenance

- **TTL**: entries carry an optional `max_age_seconds` and expire on read. The global default
  is `BITMOD_CACHE_DEFAULT_TTL`, which ships as `0`, meaning never expire. Every write path
  inherits it.
- **LRU eviction**: cost-aware, so expensive-to-regenerate entries resist eviction. Triggered
  every `BITMOD_CACHE_EVICTION_INTERVAL` writes against `BITMOD_CACHE_MAX_ENTRIES`. SQLite
  only.
- **Invalidation**: a changed source section invalidates answers derived from it. One hop.

---

## Security

| Layer | What it does |
|---|---|
| API keys | Stored as SHA-256 hashes, compared with `hmac.compare_digest`. Plaintext is never persisted. |
| Auth | On by default (`BITMOD_AUTH_ENABLED`). JWT and RBAC on the gateway. |
| Proxy routes | `POST /v1/chat` and the `/v1/chat/{path:path}` catch-all require a `read` scope (`services/gateway/app/main.py:676`), matching `/v1/chat/completions`. |
| Namespace isolation | Cache keys and queries are namespace-scoped; a backend that cannot scope a search fails closed. |
| Rate limiting | Configurable per route. |
| Input sanitisation | HTML escape, null byte removal, length limits. |
| Audit | Append-only audit events. |
| CSP | Locked to self, no external scripts. |

See [SECURITY.md](SECURITY.md) and the runbooks in `docs/runbooks/`.

---

## Design Principles

1. **Library first, service second.** Subsystems start as modules in `core/bitmod/`. A service
   is a deployment decision.
2. **Single database.** One backend holds cache, data and audit tables with logical separation.
3. **LLM-agnostic.** Any OpenAI-compatible provider works by setting a URL. Cache the answer,
   not the model.
4. **Deploy anywhere.** Docker Compose on a laptop, the same images in production, air-gapped
   on-prem. Nothing phones home.
5. **Config over code.** New intents, roles and model mappings are YAML.
6. **Intent drives compression.** How the user wants to be answered determines the content
   level, the model tier and the token budget.
7. **The LLM does less.** Facts come from verified data. The model does synthesis, reasoning
   and framing; retrieval and assembly are not its job.
8. **Measure before claiming.** Every published number has a committed artifact under
   `tests/benchmark/results/` with the commit and tree hash that produced it.

---

## Reference

- [README.md](README.md): install, configuration, benchmark results
- [docs/CACHE_ARCHITECTURE.md](docs/CACHE_ARCHITECTURE.md): the pipeline in depth
- [docs/adr/](docs/adr/): architecture decision records
- `tests/benchmark/results/`: every measurement, with provenance
