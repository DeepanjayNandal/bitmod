"""Environment-based configuration for all Bitmod services."""

import os
from dataclasses import dataclass, field

# Where an unconfigured Bitmod points, and what it asks that endpoint for.
#
# These two belong together. The URL has always defaulted to a local Ollama;
# the model defaulted to "" and so an out-of-the-box Bitmod() sent
# {"model": ""} and got back 400 "model is required". A default endpoint with
# no default model is not a default — it is a half-configured one.
DEFAULT_LLM_URL = "http://localhost:11434/v1"
DEFAULT_LOCAL_MODEL = "llama3.2"


@dataclass
class DatabaseConfig:
    """Database backend configuration.

    BITMOD_DB_BACKEND: sqlite (default), postgresql
    """

    backend: str = field(default_factory=lambda: os.getenv("BITMOD_DB_BACKEND", "sqlite"))
    # SQLite
    sqlite_path: str = field(
        default_factory=lambda: os.getenv("BITMOD_SQLITE_PATH", os.path.expanduser("~/.bitmod/bitmod.db"))
    )
    # PostgreSQL / MySQL (connection URL)
    url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            os.getenv("BITMOD_MYSQL_URL", ""),
        )
    )
    # MongoDB
    mongodb_url: str = field(default_factory=lambda: os.getenv("BITMOD_MONGODB_URL", "mongodb://localhost:27017"))
    mongodb_db: str = field(default_factory=lambda: os.getenv("BITMOD_MONGODB_DB", "bitmod"))
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle: int = 3600


@dataclass
class RedisConfig:
    host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    password: str = field(default_factory=lambda: os.getenv("REDIS_PASSWORD", ""), repr=False)

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}"
        return f"redis://{self.host}:{self.port}"


@dataclass
class LLMConfig:
    """LLM provider configuration.

    Simple setup (works with any OpenAI-compatible API):
        BITMOD_LLM_URL, BITMOD_LLM_API_KEY, BITMOD_LLM_MODEL

    Advanced (provider-specific adapters):
        BITMOD_LLM_PROVIDER: auto, anthropic, openai, openai_compatible, ollama, gemini,
            bedrock, azure_openai, xai, mistral, perplexity, openrouter, huggingface
    """

    # --- Universal config (just set these 3) ---
    url: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_URL", DEFAULT_LLM_URL))
    api_key: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_API_KEY", ""), repr=False)
    model: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_MODEL", ""))

    # --- Provider selection (auto-detected from URL if not set) ---
    provider: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_PROVIDER", ""))

    # --- Legacy fields (backwards compat — override universal config if set) ---
    primary: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_PRIMARY", os.getenv("PRIMARY_LLM", "")))
    fallback: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_FALLBACK", os.getenv("FALLBACK_LLM", "")))
    primary_model: str = field(
        default_factory=lambda: os.getenv("BITMOD_LLM_PRIMARY_MODEL", os.getenv("PRIMARY_MODEL", ""))
    )
    fallback_model: str = field(
        default_factory=lambda: os.getenv("BITMOD_LLM_FALLBACK_MODEL", os.getenv("FALLBACK_MODEL", "llama3.2"))
    )
    # Provider API keys
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""), repr=False)
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""), repr=False)
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""), repr=False)
    # Ollama
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    # OpenAI-compatible (Groq, Together, Fireworks, etc.)
    openai_compatible_base_url: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_BASE_URL", ""))
    openai_compatible_api_key: str = field(default_factory=lambda: os.getenv("BITMOD_LLM_API_KEY", ""), repr=False)
    # xAI (Grok)
    xai_api_key: str = field(default_factory=lambda: os.getenv("XAI_API_KEY", ""), repr=False)
    # Mistral
    mistral_api_key: str = field(default_factory=lambda: os.getenv("MISTRAL_API_KEY", ""), repr=False)
    # Perplexity
    perplexity_api_key: str = field(default_factory=lambda: os.getenv("PERPLEXITY_API_KEY", ""), repr=False)
    # OpenRouter
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""), repr=False)
    # Hugging Face
    hf_api_key: str = field(default_factory=lambda: os.getenv("HF_API_KEY", ""), repr=False)

    def resolve_provider(self) -> str:
        """Determine which provider to use based on what's configured.

        Priority:
        1. Explicit BITMOD_LLM_PROVIDER if set
        2. Legacy BITMOD_LLM_PRIMARY if set
        3. If provider-specific API key is set, use that provider
        4. Auto-detect from BITMOD_LLM_URL
        5. Default: openai_compatible with Ollama URL
        """
        # 1. Explicit provider
        if self.provider:
            return self.provider

        # 2. Legacy primary provider
        if self.primary:
            return self.primary

        # 3. Provider-specific API key set
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        if self.xai_api_key:
            return "xai"
        if self.mistral_api_key:
            return "mistral"
        if self.perplexity_api_key:
            return "perplexity"
        if self.openrouter_api_key:
            return "openrouter"
        if self.hf_api_key:
            return "huggingface"

        # 4/5. Auto-detect from URL (default: openai_compatible)
        return "auto"

    def resolve_model(self) -> str:
        """Resolve the model to use. Universal > legacy > default-when-local.

        The fallback is deliberately NOT unconditional. If the URL still points
        at the default local Ollama, nothing has been configured and naming
        that server's usual model is the only way `Bitmod()` can work with zero
        setup, which the class docstring promises.

        If the URL has been changed, the caller is talking to something else and
        we cannot guess its model names — "llama3.2" would be a confusing error
        from a hosted provider where "" is at least a clear one. So a configured
        endpoint with no configured model still returns empty and lets that
        provider reject it on its own terms.
        """
        explicit = self.model or self.primary_model
        if explicit:
            return explicit
        return DEFAULT_LOCAL_MODEL if self.url == DEFAULT_LLM_URL else ""


@dataclass
class EmbeddingConfig:
    """Embedding provider configuration.

    BITMOD_EMBEDDING_PROVIDER: local (default), openai, cohere, ollama
    """

    provider: str = field(default_factory=lambda: os.getenv("BITMOD_EMBEDDING_PROVIDER", "local"))
    model: str = field(
        default_factory=lambda: os.getenv("BITMOD_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )
    device: str = field(default_factory=lambda: os.getenv("BITMOD_EMBEDDING_DEVICE", "cpu"))
    dimensions: int = field(default_factory=lambda: int(os.getenv("BITMOD_EMBEDDING_DIMENSIONS", "384")))


@dataclass
class VectorStoreConfig:
    """Optional dedicated vector store (separate from primary DB).

    BITMOD_VECTOR_STORE: (empty = use DB backend), chroma, qdrant, pinecone
    """

    store: str = field(default_factory=lambda: os.getenv("BITMOD_VECTOR_STORE", ""))
    # ChromaDB
    chroma_path: str = field(default_factory=lambda: os.getenv("BITMOD_CHROMA_PATH", "./chroma_data"))
    chroma_collection: str = field(default_factory=lambda: os.getenv("BITMOD_CHROMA_COLLECTION", "bitmod"))
    # Qdrant
    qdrant_url: str = field(default_factory=lambda: os.getenv("BITMOD_QDRANT_URL", "http://localhost:6333"))
    qdrant_api_key: str = field(default_factory=lambda: os.getenv("BITMOD_QDRANT_API_KEY", ""), repr=False)
    qdrant_collection: str = field(default_factory=lambda: os.getenv("BITMOD_QDRANT_COLLECTION", "bitmod"))
    # Pinecone
    pinecone_api_key: str = field(default_factory=lambda: os.getenv("BITMOD_PINECONE_API_KEY", ""), repr=False)
    pinecone_index: str = field(default_factory=lambda: os.getenv("BITMOD_PINECONE_INDEX", "bitmod"))


@dataclass
class BackupConfig:
    """Persistent context window — saves full query/response history.

    BITMOD_BACKUP_ENABLED: true/false (default: true)
    BITMOD_BACKUP_PATH: directory for backup files (default: ./bitmod_backup)
    """

    enabled: bool = field(
        default_factory=lambda: os.getenv("BITMOD_BACKUP_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    path: str = field(default_factory=lambda: os.getenv("BITMOD_BACKUP_PATH", "./bitmod_backup"))
    max_sessions: int = field(default_factory=lambda: int(os.getenv("BITMOD_BACKUP_MAX_SESSIONS", "100")))
    compress: bool = field(
        default_factory=lambda: os.getenv("BITMOD_BACKUP_COMPRESS", "true").lower() in ("true", "1", "yes")
    )


@dataclass
class GatewayConfig:
    port: int = field(default_factory=lambda: int(os.getenv("GATEWAY_PORT", "8000")))
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv(
            "CORS_ORIGINS", "https://bitmod.io,https://app.bitmod.io,http://localhost:3000"
        ).split(",")
    )
    chat_service_url: str = field(default_factory=lambda: os.getenv("CHAT_SERVICE_URL", "http://localhost:8001"))


@dataclass
class RateLimitConfig:
    """Rate limiting configuration.

    BITMOD_RATE_LIMIT: max requests per minute per API key (default: 60)
    BITMOD_RATE_LIMIT_ENABLED: enable/disable rate limiting (default: true)
    """

    enabled: bool = field(
        default_factory=lambda: os.getenv("BITMOD_RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    requests_per_minute: int = field(default_factory=lambda: int(os.getenv("BITMOD_RATE_LIMIT", "60")))


@dataclass
class PromotionConfig:
    """LLM-verified cache promotion — optional accuracy layer.

    When enabled, high-confidence cached answers are verified by the LLM
    before serving. Off by default (zero cost when disabled).

    BITMOD_CACHE_PROMOTION_ENABLED: enable/disable (default: false)
    BITMOD_CACHE_PROMOTION_MIN_CONFIDENCE: only verify above this (default: 0.85)
    BITMOD_CACHE_PROMOTION_MAX_DAILY: cost cap on daily verifications (default: 50)
    """

    enabled: bool = field(
        default_factory=lambda: os.getenv("BITMOD_CACHE_PROMOTION_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    min_confidence: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_PROMOTION_MIN_CONFIDENCE", "0.85"))
    )
    max_daily_verifications: int = field(
        default_factory=lambda: int(os.getenv("BITMOD_CACHE_PROMOTION_MAX_DAILY", "50"))
    )
    verification_prompt: str = (
        "Given this question and cached answer, is the answer still accurate and complete? "
        "Reply YES or NO with a brief explanation."
    )


@dataclass
class StorageLimitsConfig:
    """Storage limits and eviction thresholds.

    Configurable via environment variables for all deployments.
    """

    max_answer_length: int = field(default_factory=lambda: int(os.getenv("BITMOD_MAX_ANSWER_LENGTH", "100000")))
    max_atomic_facts: int = field(default_factory=lambda: int(os.getenv("BITMOD_MAX_ATOMIC_FACTS", "500000")))
    max_similarity_links: int = field(default_factory=lambda: int(os.getenv("BITMOD_MAX_SIMILARITY_LINKS", "1000000")))
    audit_retention_days: int = field(default_factory=lambda: int(os.getenv("BITMOD_AUDIT_RETENTION_DAYS", "90")))
    max_documents_per_namespace: int = field(default_factory=lambda: int(os.getenv("BITMOD_MAX_DOCUMENTS", "50000")))


@dataclass
class CacheConfig:
    """Cache engine tuning parameters.

    All thresholds and limits are configurable via environment variables.
    Defaults are tuned for balanced precision/recall.
    """

    semantic_threshold: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_SEMANTIC_THRESHOLD", "0.88"))
    )
    fuzzy_threshold: float = field(default_factory=lambda: float(os.getenv("BITMOD_CACHE_FUZZY_THRESHOLD", "0.85")))
    composable_threshold: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_COMPOSABLE_THRESHOLD", "0.80"))
    )
    # --- Calibration, fitted rather than chosen ---
    #
    # Confidence is P(this cached answer is right for this query), fitted
    # against labelled pairs by tests/benchmark/fit_confidence_curve.py. Two
    # curves, because two different things are being mapped.
    #
    # semantic_*: cosine similarity -> probability. Replaces a hand-drawn
    #   piecewise curve from the first commit whose slope inverted — flattest
    #   between 0.92 and 0.98, exactly where serve decisions are made — so a
    #   lone semantic match needed cosine 0.980 to serve. Held-out Brier
    #   0.1707 against 0.1852, log loss 0.5117 against 1.8745. From the
    #   "raw labels" fit in tests/benchmark/results/confidence_curve_fit.json,
    #   which is the variant that file records as adopted; its "noise-adjusted"
    #   fit is a different curve (a 17.4426, b -14.6017) and is not what ships.
    #
    # accumulation_*: accumulated confidence -> probability. The layers combine
    #   as noisy-OR, which assumes they are conditionally independent. They are
    #   not — semantic and fuzzy read the same two strings — so the total
    #   overstates, and measurably: where one layer contributed, claimed minus
    #   observed was -0.006; at two layers, +0.126. Held-out log loss 0.4540
    #   against 1.6082. Both from tests/benchmark/results/accumulation_fit.json.
    #
    # Both are properties of nomic-embed-text and of the corpus they were fitted
    # on. Re-run the fitters before changing embedder, and do not hand-edit.
    semantic_confidence_a: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_SEMANTIC_CONF_A", "14.643"))
    )
    semantic_confidence_b: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_SEMANTIC_CONF_B", "-12.002"))
    )
    # How much of what combining adds survives. Noisy-OR treats the layers as
    # independent evidence and they are not — semantic and fuzzy read the same
    # two strings, so most of the gain over the single best piece is one signal
    # counted twice. Applied to that gain alone, so a single contributing layer
    # is untouched and an exact match still means 1.0.
    #
    # 0.5 is the midpoint between treating the layers as independent (1.0) and
    # as fully redundant (0.0). It is NOT a fitted value. Fits on the available
    # data gave 0.00 on the quora passes, 1.00 on the conversational ones and
    # 0.77 combined — all artefacts of pass design, since every benchmark pass
    # is entirely positive or entirely negative and the fit just recovers that
    # base rate.
    #
    # Measured at serve_threshold 0.85 across 4,600 queries:
    #
    #     damping 1.00   paraphrase 51.6%   37 wrong   8.0 per 1000
    #     damping 0.50   paraphrase 40.4%    8 wrong   1.7 per 1000
    #     damping 0.25   paraphrase 33.0%    7 wrong   1.5 per 1000
    #
    # Full weight has the most recall and five times the wrong answers. 0.25
    # gives up a further 7 points of recall to remove one. This is a
    # conservatism control, not a calibration; fitting it properly would need a
    # labelled corpus with mixed-outcome passes at a realistic base rate.
    accumulation_damping: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_ACCUMULATION_DAMPING", "0.50"))
    )
    calibrated_confidence: bool = field(
        default_factory=lambda: os.getenv("BITMOD_CACHE_CALIBRATED", "true").lower() in ("true", "1", "yes")
    )

    # Refuse a candidate when the two questions name different things —
    # "Sigma-Aldrich" against "Sigma Designs", "taffy in Austria" against "in
    # China". Similarity cannot separate those: the sentences really are alike.
    # Measured on 130 hand-classified serves: 5 of 23 wrong serves refused, 1
    # correct serve lost in 107. Switchable so the cost can be re-measured
    # against a different corpus rather than assumed to hold.
    entity_guard_enabled: bool = field(
        default_factory=lambda: os.getenv("BITMOD_CACHE_ENTITY_GUARD", "true").lower() in ("true", "1", "yes")
    )

    # Preprocessing applied to every text this cache embeds — "key" drops
    # function words, "raw" passes the sentence through. Which one separates
    # better is a property of the embedding model, measured, not assumed: on
    # nomic-embed-text against surface-confusable negatives "key" gives
    # AUC 0.831 versus 0.759. Re-measure before changing embedder.
    embedding_normalisation: str = field(
        default_factory=lambda: os.getenv("BITMOD_CACHE_EMBEDDING_NORMALISATION", "key")
    )
    # 0.60, not 0.75. The old value was doing ceiling work: the queries that
    # produced no evidence at all sat at median cosine 0.702 with a maximum of
    # 0.749, so the retrieval cutoff — not the serve threshold — was what made
    # them unreachable.
    #
    # Measured at serve_threshold 0.85: dropping to 0.60 takes zero-evidence
    # duplicates from 43 to 18 and adds six correct serves for no additional
    # wrong ones. A single match this weak scores 0.148 and can never serve
    # alone; it earns its place by combining.
    search_threshold: float = field(default_factory=lambda: float(os.getenv("BITMOD_CACHE_SEARCH_THRESHOLD", "0.60")))
    max_entries: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_MAX_ENTRIES", "100000")))
    eviction_interval: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_EVICTION_INTERVAL", "100")))
    max_answer_length: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_MAX_ANSWER_LENGTH", "100000")))
    max_scan_numpy: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_MAX_SCAN_NUMPY", "2000")))
    max_scan_fallback: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_MAX_SCAN_FALLBACK", "500")))
    link_cleanup_days: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_LINK_CLEANUP_DAYS", "30")))
    fuzzy_max_candidates: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_FUZZY_MAX_CANDIDATES", "5")))
    search_max_results: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_SEARCH_MAX_RESULTS", "3")))

    # --- Fuzzy pre-filter ---
    # Candidates are pre-filtered on token prefixes of this length. Longer is
    # more selective but stops tolerating typos near the start of a word;
    # shorter widens the candidate set that scoring then has to reject.
    fuzzy_prefix_length: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_FUZZY_PREFIX_LENGTH", "3")))
    # PostgreSQL pre-filters candidates with an index-backed trigram similarity
    # before Python scoring. Permissive on purpose: it only has to discard the
    # clearly unrelated, and a typo pair scores around 0.81 here.
    fuzzy_prefilter_similarity: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_FUZZY_PREFILTER_SIMILARITY", "0.30"))
    )

    # --- Serve decision ---
    # Accumulated confidence at or above this serves from cache. The single
    # most behaviour-changing value in the pipeline.
    # 0.85, chosen from the error rate it produces rather than by feel. With
    # confidence calibrated, this threshold *is* the error budget: serve when
    # P(this answer is right) is at least this.
    #
    # Measured on 500 labelled duplicate and 500 hard-negative pairs, against
    # the pre-calibration system at 0.95 (recall 20.6%, 23 wrong per 1000):
    #
    #     0.80   recall 43.0%   34 wrong/1000
    #     0.85   recall 31.0%   16 wrong/1000   <- beats the old system on both
    #     0.90   recall 16.8%    6 wrong/1000
    #
    # 0.95 no longer means what it did. The calibrated curve caps a single
    # semantic match at 0.9335 and an accumulated total at 0.8772, so keeping
    # 0.95 would serve almost nothing — 15 of 500 duplicates when measured.
    # That is why the curve and this number cannot be changed separately.
    #
    # The measurement set is half hard negatives by construction, which is far
    # more adversarial than real traffic, so the per-1000 figures are an upper
    # bound on the production error rate rather than a forecast of it.
    serve_threshold: float = field(default_factory=lambda: float(os.getenv("BITMOD_CACHE_SERVE_THRESHOLD", "0.85")))

    # --- Per-layer confidence contributions ---
    # What each layer is worth when it matches. Exact match is 1.0 by
    # definition — the key matched — so it is not configurable.
    #
    # Fuzzy has no entry here. Its contribution is a function of the measured
    # similarity via _similarity_to_confidence, not a constant, so there is
    # nothing for a single value to mean. BITMOD_CACHE_FUZZY_CONFIDENCE was
    # removed rather than left inert.
    composable_confidence: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_COMPOSABLE_CONFIDENCE", "0.85"))
    )

    # --- Atomic facts (layer 8) ---
    fact_min_similarity: float = field(
        # 0.65, not the 0.80 the semantic layer uses. This compares a question
        # against a declarative sentence, which scores lower by construction.
        # Measured on 401 question/own-fact pairs: 0.80 admitted 12.2% of the
        # facts that answer the question, 0.65 admits 60.1% at 95.3% precision —
        # the precision the semantic layer already runs at.
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_FACT_MIN_SIMILARITY", "0.65"))
    )
    fact_confidence_weight: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_FACT_CONFIDENCE_WEIGHT", "0.40"))
    )
    fact_dedup_threshold: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_FACT_DEDUP_THRESHOLD", "0.95"))
    )
    fact_min_answer_length: int = field(
        default_factory=lambda: int(os.getenv("BITMOD_CACHE_FACT_MIN_ANSWER_LENGTH", "100"))
    )
    fact_max_per_answer: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_FACT_MAX_PER_ANSWER", "10")))

    # --- Similarity links (layer 7) ---
    # Near-misses in this band are recorded as links. Below it the pair is not
    # related enough to be worth remembering; above it the query would have
    # been served on semantic similarity alone.
    link_learn_min: float = field(default_factory=lambda: float(os.getenv("BITMOD_CACHE_LINK_LEARN_MIN", "0.75")))
    link_learn_max: float = field(default_factory=lambda: float(os.getenv("BITMOD_CACHE_LINK_LEARN_MAX", "0.91")))
    link_hop2_discount: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_LINK_HOP2_DISCOUNT", "0.30"))
    )
    link_strength_bonus: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_LINK_STRENGTH_BONUS", "0.05"))
    )
    link_strength_bonus_cap: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_LINK_STRENGTH_BONUS_CAP", "0.25"))
    )
    link_max_per_query: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_LINK_MAX_PER_QUERY", "10")))
    link_max_total: int = field(default_factory=lambda: int(os.getenv("BITMOD_CACHE_LINK_MAX_TOTAL", "1000000")))
    # A traversed link is weaker evidence than the semantic match that seeded
    # it — this scales its similarity down before it enters the evidence pool.
    link_confidence_weight: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_LINK_CONFIDENCE_WEIGHT", "0.50"))
    )

    # --- Verification penalties ---
    # Negative evidence applied when a check rejects the chosen answer. The
    # serve-verify penalty is large enough to drop any single serve below
    # threshold; the promotion penalty is softer because an LLM disagreeing is
    # weaker grounds than a source hash mismatch.
    serve_verify_penalty: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_SERVE_VERIFY_PENALTY", "1.0"))
    )
    promotion_demotion_penalty: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_PROMOTION_DEMOTION_PENALTY", "0.5"))
    )
    # Assumed similarity when a backend returns a bare fact rather than a
    # (fact, similarity) pair. Adapter contracts differ on this.
    fact_assumed_similarity: float = field(
        default_factory=lambda: float(os.getenv("BITMOD_CACHE_FACT_ASSUMED_SIMILARITY", "0.85"))
    )


@dataclass
class BitmodConfig:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)
    promotion: PromotionConfig = field(default_factory=PromotionConfig)
    storage_limits: StorageLimitsConfig = field(default_factory=StorageLimitsConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    _loaded_from: str = field(default="", init=False, repr=False)


_SUPPORTED_DB_BACKENDS = frozenset({"sqlite", "postgresql", "mysql", "mongodb"})


def _apply_overrides(config: "BitmodConfig", overrides: dict) -> None:
    """Apply YAML/kwarg overrides onto a BitmodConfig instance.

    Supports flat keys like db_backend, db_url, llm_primary, etc.
    Maps them to the nested dataclass fields.
    """
    field_map: dict[str, tuple[str, str]] = {
        # database
        "db_backend": ("db", "backend"),
        "db_sqlite_path": ("db", "sqlite_path"),
        "db_url": ("db", "url"),
        "db_mongodb_url": ("db", "mongodb_url"),
        "db_mongodb_db": ("db", "mongodb_db"),
        # llm (universal)
        "llm_url": ("llm", "url"),
        "llm_api_key": ("llm", "api_key"),
        "llm_model": ("llm", "model"),
        "llm_provider": ("llm", "provider"),
        # llm (legacy)
        "llm_primary": ("llm", "primary"),
        "llm_fallback": ("llm", "fallback"),
        "llm_primary_model": ("llm", "primary_model"),
        "llm_fallback_model": ("llm", "fallback_model"),
        "anthropic_api_key": ("llm", "anthropic_api_key"),
        "openai_api_key": ("llm", "openai_api_key"),
        "gemini_api_key": ("llm", "gemini_api_key"),
        "ollama_url": ("llm", "ollama_url"),
        # embedding
        "embedding_provider": ("embedding", "provider"),
        "embedding_model": ("embedding", "model"),
        "embedding_device": ("embedding", "device"),
        "embedding_dimensions": ("embedding", "dimensions"),
        # vector store
        "vector_store": ("vector_store", "store"),
        # backup
        "backup_enabled": ("backup", "enabled"),
        "backup_path": ("backup", "path"),
        "backup_max_sessions": ("backup", "max_sessions"),
        "backup_compress": ("backup", "compress"),
        # gateway
        "gateway_port": ("gateway", "port"),
        # cache
        "cache_semantic_threshold": ("cache", "semantic_threshold"),
        "cache_fuzzy_threshold": ("cache", "fuzzy_threshold"),
        "cache_composable_threshold": ("cache", "composable_threshold"),
        "cache_search_threshold": ("cache", "search_threshold"),
        "cache_max_entries": ("cache", "max_entries"),
        "cache_eviction_interval": ("cache", "eviction_interval"),
    }

    env_map: dict[str, str] = {
        "db_backend": "BITMOD_DB_BACKEND",
        "db_sqlite_path": "BITMOD_DB_SQLITE_PATH",
        "db_url": "DATABASE_URL",
        "db_mongodb_url": "BITMOD_MONGODB_URL",
        "db_mongodb_db": "BITMOD_MONGODB_DB",
        "llm_url": "BITMOD_LLM_URL",
        "llm_api_key": "BITMOD_LLM_API_KEY",
        "llm_model": "BITMOD_LLM_MODEL",
        "llm_provider": "BITMOD_LLM_PROVIDER",
        "llm_primary": "BITMOD_LLM_PRIMARY",
        "llm_fallback": "BITMOD_LLM_FALLBACK",
        "llm_primary_model": "BITMOD_LLM_PRIMARY_MODEL",
        "llm_fallback_model": "BITMOD_LLM_FALLBACK_MODEL",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "ollama_url": "OLLAMA_URL",
        "embedding_provider": "BITMOD_EMBEDDING_PROVIDER",
        "embedding_model": "BITMOD_EMBEDDING_MODEL",
        "embedding_device": "BITMOD_EMBEDDING_DEVICE",
        "embedding_dimensions": "BITMOD_EMBEDDING_DIMENSIONS",
        "vector_store": "BITMOD_VECTOR_STORE",
        "backup_enabled": "BITMOD_BACKUP_ENABLED",
        "backup_path": "BITMOD_BACKUP_PATH",
        "backup_max_sessions": "BITMOD_BACKUP_MAX_SESSIONS",
        "backup_compress": "BITMOD_BACKUP_COMPRESS",
        "gateway_port": "BITMOD_GATEWAY_PORT",
        # cache
        "cache_semantic_threshold": "BITMOD_CACHE_SEMANTIC_THRESHOLD",
        "cache_fuzzy_threshold": "BITMOD_CACHE_FUZZY_THRESHOLD",
        "cache_composable_threshold": "BITMOD_CACHE_COMPOSABLE_THRESHOLD",
        "cache_search_threshold": "BITMOD_CACHE_SEARCH_THRESHOLD",
        "cache_max_entries": "BITMOD_CACHE_MAX_ENTRIES",
        "cache_eviction_interval": "BITMOD_CACHE_EVICTION_INTERVAL",
    }

    for key, value in overrides.items():
        if key in field_map:
            env_var = env_map.get(key)
            if env_var and os.getenv(env_var):
                continue
            section_name, field_name = field_map[key]
            section = getattr(config, section_name)
            setattr(section, field_name, value)


def _validate_config(config: "BitmodConfig") -> None:
    """Validate configuration values. Raises ValueError on invalid config."""
    import logging

    logger = logging.getLogger(__name__)

    # Rate limit values must be positive integers
    if config.rate_limits.requests_per_minute < 1:
        raise ValueError(f"Rate limit requests_per_minute must be >= 1, got {config.rate_limits.requests_per_minute}")

    # Port numbers must be 1-65535
    for label, port in [
        ("gateway_port", config.gateway.port),
        ("redis_port", config.redis.port),
    ]:
        if not (1 <= port <= 65535):
            raise ValueError(f"{label} must be 1-65535, got {port}")

    # Database backend must be supported
    if config.db.backend not in _SUPPORTED_DB_BACKENDS:
        raise ValueError(
            f"Unsupported db backend {config.db.backend!r}, must be one of {sorted(_SUPPORTED_DB_BACKENDS)}"
        )

    logger.debug("Config validation passed")


def load_config(config_path: str | None = None) -> BitmodConfig:
    """Load configuration from environment variables and optional YAML file.

    Priority: env vars > YAML values > dataclass defaults.
    """
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    config = BitmodConfig()

    # Try to load bitmod.yaml for values not set via env vars.
    # Search order: explicit path > ./bitmod.yaml > ~/.bitmod/bitmod.yaml
    import pathlib

    candidates: list[pathlib.Path] = []
    if config_path:
        candidates.append(pathlib.Path(config_path))
    else:
        candidates.append(pathlib.Path("bitmod.yaml"))
        candidates.append(pathlib.Path(os.path.expanduser("~/.bitmod/bitmod.yaml")))

    config._loaded_from = ""  # track which file was used
    for yaml_path in candidates:
        if yaml_path.is_file():
            try:
                import yaml  # type: ignore[import-untyped]

                with open(yaml_path) as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    _apply_overrides(config, data)
                resolved = str(yaml_path.resolve())
                config._loaded_from = resolved
                _logger.debug("Config loaded from %s", resolved)
                break  # Use the first config file found
            except ImportError:
                pass  # PyYAML not installed — skip YAML loading
            except Exception as e:  # noqa: S110 — config file loading fallback
                _logger.warning("Failed to load bitmod.yaml: %s", e)

    if not config._loaded_from:
        _logger.debug("Config loaded from environment variables (no YAML file found)")

    _validate_config(config)
    return config
