# BitMod Cache Architecture

## A 9-Layer Intelligent Cache Pipeline for Large Language Model Response Deduplication

### Abstract

BitMod implements a multi-layer cache pipeline that eliminates redundant LLM API calls by recognizing semantic equivalence across queries that differ in surface form. The system combines deterministic hashing, approximate nearest neighbor search, compositional query decomposition, fuzzy lexical matching, learned similarity graphs, atomic knowledge retrieval, session-aware context, cost-aware eviction, and Bayesian evidence accumulation into a single unified pipeline. Each layer operates independently and produces a confidence-weighted evidence signal; the final layer combines these signals probabilistically to make a serve-or-forward decision. This document describes the architecture, its theoretical foundations, and its relationship to prior work.

---

## 1. Design Principles

**Layered independence.** Each cache layer runs as an independent evaluator. A miss at one layer does not prevent a hit at another. This is analogous to hierarchical caching in content delivery networks [1], where each tier operates autonomously and a request may be satisfied at any level.

**Confidence composition over binary decisions.** Rather than a single hit/miss threshold, each layer produces a confidence score. The final Bayesian accumulation layer composes these scores into a posterior probability of answer correctness, enabling the system to serve high-confidence partial results or combine evidence from multiple layers.

**Cost-awareness.** The pipeline is ordered by computational cost: O(1) hash lookups run first, embedding comparisons second, decomposition third, and fuzzy scanning last. Two layers short-circuit: an exact-match hit returns at `proxy/base.py:608` and a composable full hit at `:770`. Every other layer contributes graded evidence and the pipeline continues, so a serve can rest on several layers that none of them would carry alone.

**Source integrity.** Answers generated from ingested documents are bound to the SHA-256 hash of each source section they came from, and double verification re-checks every hash at serve time, invalidating on any mismatch. This does not cover every cached answer: answers cached by the reverse proxy carry no manifest (`proxy/base.py:1350` and `services/chat/app/main.py:471` store an empty `source_sections`, and `double_verify` returns true immediately on an empty list). They were never derived from a document and have nothing to go stale against, but the guarantee above is not what protects them.

---

## 2. Layer Descriptions

### Layer 1: Deterministic Key-Value Cache (Exact Match)

The first layer constructs a composite cache key by hashing the normalized query, model identifier, parameter set, and namespace using SHA-256. The resulting key is used for an O(1) lookup against the backing store. This is the fastest path: if the exact same query with the exact same parameters has been answered before, the cached response is returned immediately.

Key construction follows the approach described in parameterized caching literature, where cache keys encode not just the query but the full request context [1]. The composite key ensures that the same question asked of different models or with different temperature settings produces distinct cache entries.

**Complexity:** O(1) lookup, O(n) key construction where n is the length of the input parameters.

### Layer 2: Approximate Nearest Neighbor Cache (Embedding Similarity)

When exact match fails, the system computes a dense embedding of the query and searches for cached entries whose embeddings fall within a similarity threshold (default: cosine similarity >= 0.92). The search uses a brute-force scan over stored embeddings with optional cluster-centroid indexing for larger cache sizes.

This layer draws on the body of work in approximate nearest neighbor (ANN) search. Malkov and Yashunin [2] demonstrated that Hierarchical Navigable Small World (HNSW) graphs achieve near-optimal recall with sub-linear query time. BitMod's current implementation uses a linear scan suitable for cache sizes up to ~100K entries; the architecture supports pluggable ANN backends (HNSW, IVF, LSH) for larger deployments.

The key insight from semantic caching research [3] is that queries with high embedding similarity tend to have equivalent answers, even when their surface forms differ substantially. "What is HIPAA?" and "Explain HIPAA to me" produce nearly identical embeddings and should return the same cached response.

**Complexity:** O(k) where k is the number of cached embeddings, reducible to O(log k) with HNSW indexing.

### Layer 3: Compositional Decomposition Cache (Sub-Query Factoring)

Complex queries are decomposed into independently cacheable sub-queries. For example, "Compare the privacy regulations in HIPAA and GDPR" decomposes into:

1. "What are the privacy regulations in HIPAA?"
2. "What are the privacy regulations in GDPR?"
3. "What are the differences between HIPAA and GDPR privacy regulations?"

Each sub-query is resolved against the cache independently (via Layers 1 and 2). If all components hit, the system can assemble a complete answer without any LLM call. If some components hit and others miss, the system can forward only the missing sub-queries to the LLM, reducing token consumption.

This approach is grounded in query decomposition research. Khot et al. [4] showed that complex questions can be answered by decomposing them into simpler sub-questions and joining evidence from multiple sources. BitMod applies the same principle to cache lookup: a novel composite question may be fully answerable from previously cached atomic answers.

**Complexity:** O(m * k) where m is the number of sub-queries and k is the per-sub-query lookup cost.

### Layer 4: Fuzzy Lexical Matching (Edit Distance + Token Overlap)

When semantic similarity fails (e.g., due to embedding model limitations or domain-specific terminology), the system falls back to lexical fuzzy matching. Queries are normalized into sorted token sets, and candidates are scored using a combination of:

- **Levenshtein edit distance** normalized to a similarity score [5], capturing character-level variations (typos, abbreviations, minor reformulations).
- **Jaccard token overlap** between the query token set and candidate token sets, capturing word-level similarity independent of word order.

The combined score must exceed a configurable threshold (default: 0.85) for a fuzzy match to be accepted. This layer catches cases where queries are nearly identical in wording but differ in trivial ways that alter the embedding enough to miss at Layer 2.

**Complexity:** O(k * n^2) where k is the number of candidates and n is the query length in characters. Bounded by a candidate pre-filter on token overlap.

### Layer 5: Learned Similarity Graph Traversal

BitMod maintains a graph of similarity links between cache entries. When a new query is cached, the system creates bidirectional weighted edges to entries that were considered during lookup. Over time, these links form a navigable graph where frequently co-accessed entries develop strong connections and rarely accessed paths decay via temporal discounting.

This layer draws on knowledge graph embedding research [6], where learned representations capture relational structure between entities. In BitMod, the "entities" are cached query-answer pairs and the "relations" are similarity signals observed during cache operation. Graph traversal enables the system to find relevant cached answers that are not direct semantic neighbors of the query but are reachable through a chain of related entries.

Link strength is reinforced on each successful traversal and decayed on a configurable time schedule. Weak links are pruned during periodic cleanup.

**Complexity:** O(d^h) where d is the average node degree and h is the traversal depth (typically bounded at h=2).

### Layer 6: Atomic Knowledge Base (Fact-Level Decomposition)

Cached answers are decomposed into atomic factual statements at storage time. Each fact is stored independently with a quality weight derived from its source confidence and recency. When a new query arrives and misses all previous layers, the system searches the atomic fact store for relevant facts and assembles a response from high-quality individual facts.

This approach enables cache reuse at a finer granularity than full answer matching. A question about "HIPAA penalties for data breaches" may be answerable from facts extracted from a broader cached answer about "HIPAA compliance requirements," even if the original query is not a semantic match.

Fact decomposition is rule-based (sentence boundary detection, list item extraction, definition pattern matching) and does not require an LLM call.

**Complexity:** O(f) where f is the number of stored atomic facts, with optional embedding-based pre-filtering.

### Layer 7: Session-Aware Contextual Cache

For conversational applications, cache hits depend not just on the current query but on the conversation history. Layer 7 maintains an LRU-bounded session context window and adjusts cache lookup to account for conversational continuity. A query like "What about its penalties?" is meaningless in isolation but fully resolvable when the session context indicates the previous topic was HIPAA.

The session layer applies context from the conversation thread to disambiguate queries before they enter the cache pipeline, effectively expanding the cache's ability to match queries that rely on anaphoric reference or topic continuity.

**Complexity:** O(s) where s is the session context window size (bounded by LRU policy).

### Layer 8: Time-to-Live Expiration with Cost-Aware Eviction

Each cache entry carries an optional TTL. Expired entries are invalidated lazily on access and eagerly during periodic eviction sweeps. When the cache exceeds its configured maximum size, eviction follows a cost-aware policy that considers:

- **Access frequency:** frequently served entries are more valuable.
- **Generation cost:** entries that required expensive LLM calls (large models, long outputs) are more costly to regenerate.
- **Recency:** standard LRU decay.

This policy draws on the ARC (Adaptive Replacement Cache) literature [7], which demonstrated that combining recency and frequency signals outperforms pure LRU or pure LFU. BitMod extends this with a cost dimension: evicting a cached GPT-4 response is more expensive than evicting a cached GPT-3.5-turbo response, so the eviction policy accounts for regeneration cost.

**Complexity:** O(n log n) for eviction sorting, amortized to O(1) per cache write via periodic batch eviction.

### Layer 9: Bayesian Evidence Accumulation

The final layer does not perform its own cache lookup. Instead, it aggregates the confidence signals from all preceding layers using Bayesian evidence composition. Each layer's output is treated as an independent piece of evidence with a prior probability, and the posterior confidence is computed via iterative Bayesian updating:

```
P(correct | evidence) = P(evidence | correct) * P(correct) / P(evidence)
```

In practice, the system uses a log-odds accumulation that is numerically equivalent:

```
log_odds += log(confidence / (1 - confidence))  for each layer's evidence
```

This formulation is related to the Dempster-Shafer theory of evidence [8], which provides a framework for combining uncertain evidence from independent sources. The key property is that multiple weak signals can accumulate into a high-confidence decision: a 0.7 confidence semantic match combined with a 0.6 confidence fuzzy match and a 0.5 atomic fact match may produce a composite confidence above the serve threshold.

Layers can also contribute negative evidence. A source integrity check failure at serve time contributes strong negative evidence, pulling the composite confidence below the serve threshold regardless of other signals.

**Complexity:** O(L) where L is the number of layers that produced evidence (at most 8).

---

## 3. Pipeline Execution Order

```
Query arrives
  |
  v
[1] Exact Match (SHA-256 composite key) -----> HIT: serve immediately
  |
  v (miss)
[2] Semantic Similarity (embedding ANN) -----> HIT: add evidence
  |
  v (miss or partial)
[3] Compositional Decomposition -------------> HIT: add evidence per sub-query
  |
  v (miss or partial)
[4] Fuzzy Lexical Match ---------------------> HIT: add evidence
  |
  v (miss or partial)
[5] Similarity Graph Traversal --------------> HIT: add evidence
  |
  v (miss or partial)
[6] Atomic Knowledge Base -------------------> HIT: add evidence
  |
  v
[7] Session Context Resolution --------------> Augments query for re-matching
  |
  v
[8] TTL + Eviction Check --------------------> Validates freshness of any hits
  |
  v
[9] Bayesian Evidence Accumulation -----------> Combine all evidence
  |
  +---> Confidence >= threshold: SERVE cached response
  +---> Confidence <  threshold: FORWARD to LLM provider
```

Layer 1 is the only layer that short-circuits the pipeline on a direct hit (deterministic exact match requires no further evidence). All other layers contribute evidence to the Bayesian accumulator, which makes the final serve/forward decision.

---

## 4. Source Integrity and Double Verification

Every cache entry records the SHA-256 hash of the source sections used to generate the answer. At serve time, the system performs double verification:

1. Retrieve the current hash of each source section from the database.
2. Compare against the hashes recorded at cache time.
3. If any hash has changed, the cache entry is invalidated and the query is forwarded to the LLM.

This guarantees that cached answers are never served from stale source data, even if the answer's TTL has not yet expired. The mechanism is critical for applications where source documents are updated frequently (e.g., policy documents, knowledge bases, regulatory filings).

---

## 5. Relationship to Prior Work

BitMod is, to our knowledge, the first production system to combine all of the following techniques in a unified pipeline for LLM response caching:

| Technique | Prior Work | BitMod Layer |
|---|---|---|
| Hierarchical multi-tier caching | Wang [1], CDN architectures | Pipeline structure |
| Approximate nearest neighbor search | Malkov & Yashunin [2] (HNSW) | Layer 2 |
| Semantic caching | Godfrey & Gryz [3] | Layers 2, 5 |
| Query decomposition for QA | Khot et al. [4] | Layer 3 |
| Edit distance matching | Levenshtein [5] | Layer 4 |
| Knowledge graph traversal | Wang et al. [6] | Layer 5 |
| Adaptive cache replacement | Megiddo & Modha [7] (ARC) | Layer 8 |
| Bayesian evidence combination | Dempster [8], Shafer [9] | Layer 9 |

Individual techniques are well-studied. The contribution of BitMod is their integration into a single coherent pipeline with confidence-weighted evidence accumulation, enabling cache hit rates substantially higher than any single technique achieves in isolation.

---

## 6. References

[1] J. Wang, "A survey of web caching schemes for the Internet," *ACM SIGCOMM Computer Communication Reviews*, vol. 29, no. 5, pp. 36-46, 1999.

[2] Y. A. Malkov and D. A. Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs," *IEEE Transactions on Pattern Analysis and Machine Intelligence*, vol. 42, no. 4, pp. 824-836, 2020.

[3] P. Godfrey and J. Gryz, "Answering queries by semantic caches," in *Proc. International Conference on Database and Expert Systems Applications (DEXA)*, pp. 485-498, 1999.

[4] T. Khot, D. Khashabi, K. Richardson, P. Clark, and A. Sabharwal, "Text modular networks: Learning to decompose tasks in the language of existing models," in *Proc. North American Chapter of the Association for Computational Linguistics (NAACL)*, 2021.

[5] V. I. Levenshtein, "Binary codes capable of correcting deletions, insertions, and reversals," *Soviet Physics Doklady*, vol. 10, no. 8, pp. 707-710, 1966.

[6] Q. Wang, Z. Mao, B. Wang, and L. Guo, "Knowledge graph embedding: A survey of approaches and applications," *IEEE Transactions on Knowledge and Data Engineering*, vol. 29, no. 12, pp. 2724-2743, 2017.

[7] N. Megiddo and D. S. Modha, "ARC: A self-tuning, low overhead replacement cache," in *Proc. USENIX Conference on File and Storage Technologies (FAST)*, pp. 115-130, 2003.

[8] A. P. Dempster, "Upper and lower probabilities induced by a multivalued mapping," *The Annals of Mathematical Statistics*, vol. 38, no. 2, pp. 325-339, 1967.

[9] G. Shafer, *A Mathematical Theory of Evidence*, Princeton University Press, 1976.

---

## 7. Implementation

The reference implementation is in `core/bitmod/cache_engine.py`. Key classes and functions:

- `compute_answer_key()` -- Layer 1 composite SHA-256 key construction
- `semantic_cache_match()` / `semantic_cache_search()` -- Layer 2 embedding similarity
- `decompose_query()` / `try_composable_cache()` -- Layer 3 compositional decomposition
- `fuzzy_match()` -- Layer 4 Levenshtein + Jaccard matching
- `decompose_answer()` -- Layer 6 atomic fact extraction
- `evict_expired_cache()` / `evict_lru_cache()` -- Layer 8 TTL and eviction
- `CacheEvidence` / `PipelineEvidence` -- Layer 9 Bayesian evidence accumulation
- `double_verify()` -- Source integrity verification
