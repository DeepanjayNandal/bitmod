# BitMod and Complementary Caching Technologies

## How BitMod Works With -- Not Against -- Provider-Side Caching

BitMod operates at the application layer. Provider prompt caching and KV cache compression operate at the API and inference layers, respectively. These technologies are complementary: each reduces cost at a different point in the stack. Using all three together produces compounding savings.

---

## The Three-Layer Savings Stack

```
┌──────────────────────────────────────────┐
│       Application Layer (BitMod)         │
│  ┌────────────────────────────────────┐  │
│  │  9-layer cache: serve or forward   │  │
│  │  Cache hit  = $0.00 (no API call)  │  │
│  │  Cache miss = forward to provider  │  │
│  └────────────────────────────────────┘  │
│            | (cache miss only)           │
├──────────────────────────────────────────┤
│       API Layer (Provider Cache)         │
│  Anthropic prompt caching / OpenAI       │
│  cached prefixes                         │
│  Cache hit  = 90% discount on input      │
│  Cache miss = full price per token       │
├──────────────────────────────────────────┤
│    Inference Layer (KV Compression)      │
│  PagedAttention / MQA / GQA /            │
│  Quantized KV cache                      │
│  Effect = faster generation, more        │
│  concurrent requests, longer context     │
└──────────────────────────────────────────┘
```

Each layer is independent. You do not need to choose between them.

---

## 1. Provider-Side Prompt Caching

### What it does

LLM providers (Anthropic, OpenAI, Google) cache the internal KV-cache representation of prompt prefixes on their GPU infrastructure. When consecutive API calls share a common prompt prefix (system prompt, few-shot examples, document context), the provider skips reprocessing those tokens and charges a reduced rate.

- **Anthropic:** 90% discount on cached input tokens, 5-minute cache window
- **OpenAI:** 50% discount on cached input tokens, automatic for prompts >1024 tokens
- **Google:** Similar prefix caching for Gemini models

### What it does NOT do

Provider prompt caching reduces the cost of processing the *prompt*. It does not eliminate the API call. The LLM still generates a full response, consuming output tokens at full price. Every call still incurs network latency, rate limit consumption, and output token cost.

### How BitMod complements it

**Provider caching reduces cost *per call*. BitMod reduces the *number* of calls.**

When BitMod's cache hits, no API call is made at all -- zero input tokens and zero output tokens. The cached response still has to travel: 68-82ms over HTTP on the exact-match path, against seconds for generation. When BitMod's cache misses, the request passes through to the provider, where prompt caching can still reduce the cost of that call.

The result is double savings:

| Scenario | Input Cost | Output Cost | Latency |
|---|---|---|---|
| Cold call (no caching) | 100% | 100% | Full |
| Provider cache hit only | 10-50% | 100% | ~Full |
| BitMod cache hit only | 0% | 0% | <5ms |
| BitMod miss + provider cache hit | 10-50% | 100% | ~Full |

At a 60% BitMod cache hit rate (typical for production workloads with moderate query repetition), 60% of calls cost nothing. The remaining 40% benefit from provider prompt caching, reducing their input token cost by 50-90%. The combined savings exceed what either system achieves alone.

### Example: 10,000 queries/day with GPT-4o

| Configuration | Daily Cost (est.) |
|---|---|
| No caching | $50.00 |
| Provider prompt cache only (50% input discount) | $37.50 |
| BitMod only (60% hit rate) | $20.00 |
| BitMod + provider prompt cache | $15.00 |

---

## 2. KV Cache Compression (Inference Layer)

### What it does

At the inference layer -- inside the transformer model itself -- several techniques reduce the memory footprint and compute cost of the key-value cache that stores attention state:

- **Multi-Query Attention (MQA):** Shares key/value heads across query heads, reducing KV cache size by up to 8x.
- **Grouped-Query Attention (GQA):** A middle ground between MQA and standard multi-head attention. Used in Llama 2 70B, Mistral, and others.
- **PagedAttention (vLLM):** Manages KV cache memory like virtual memory pages, eliminating fragmentation and enabling more concurrent requests.
- **Quantized KV cache:** Stores KV cache entries in lower precision (FP8, INT8) to reduce memory bandwidth.

### What it does NOT do

KV cache compression operates entirely within the inference engine. It makes each LLM call faster and allows the provider to serve more concurrent requests. It does not reduce the number of calls, does not reduce token-based pricing, and is invisible to the application layer.

### How BitMod complements it

BitMod operates above the inference layer entirely. KV cache compression makes each LLM call cheaper and faster at the hardware level. BitMod eliminates calls at the application level. They address orthogonal concerns:

| Technology | Layer | Effect |
|---|---|---|
| KV compression | Inference (GPU) | More throughput per GPU, longer context |
| Provider prompt cache | API (provider) | Lower input token cost per call |
| BitMod | Application (your infra) | Fewer total calls to the provider |

For self-hosted LLM deployments (vLLM, TGI, Ollama), KV cache compression directly reduces your GPU costs per request. BitMod reduces the number of requests that reach your GPU at all. Together, they minimize both the volume and the unit cost of inference.

---

## 3. Why "Eliminate the Call" Beats "Discount the Call"

The most effective cost reduction is not making the call in the first place:

- **Zero tokens processed** -- no input cost, no output cost
- **Sub-5ms latency** -- cache lookup vs. 500ms-5s LLM generation
- **No rate limit consumption** -- cache hits do not count against provider rate limits
- **No provider dependency** -- cache hits are served from your own infrastructure
- **Deterministic responses** -- cache hits return the same answer every time

Provider caching and KV compression are valuable optimizations for the calls you must make. BitMod determines which calls you actually need to make.

---

## 4. Deployment Recommendations

**Use all three layers.** They are complementary, not competitive.

1. **Deploy BitMod** as a reverse proxy between your application and the LLM provider. Cache hits are served instantly. Cache misses pass through transparently.

2. **Enable provider prompt caching** on your API calls. Anthropic prompt caching is automatic for eligible prompts. OpenAI caching is automatic for prompts over 1024 tokens. No code changes needed -- BitMod's proxy forwards requests with prompt structure preserved.

3. **If self-hosting:** choose an inference engine with PagedAttention (vLLM) or GQA-optimized models. BitMod reduces load on your GPU fleet; KV compression maximizes what each GPU can handle.

The three layers compound:

```
Total cost = (1 - BitMod_hit_rate) * (1 - provider_cache_discount) * base_cost

Example:
  60% BitMod hit rate, 50% provider discount on remaining calls:
  Total = 0.40 * 0.50 * base = 20% of original cost
```

---

## 5. What BitMod Is NOT

BitMod is not a prompt cache, a KV cache, or an inference optimizer. It is an application-layer semantic cache that determines whether an LLM call is necessary at all. It sits above the entire inference stack and complements every optimization happening below it.

| "I already use Anthropic prompt caching" | Great -- BitMod eliminates 60%+ of calls before they reach Anthropic. The remaining calls still get your prompt cache discount. |
|---|---|
| "I already use vLLM with PagedAttention" | Great -- BitMod reduces the request volume hitting your vLLM cluster. PagedAttention handles the remaining requests more efficiently. |
| "I already use a Redis response cache" | BitMod goes beyond exact-match key lookup. Semantic similarity, compositional decomposition, fuzzy matching, and Bayesian evidence accumulation catch cache-equivalent queries that a simple key-value store misses. |
