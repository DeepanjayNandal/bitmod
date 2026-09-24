-- Bitmod Initial Schema
-- 3-tier data store + intelligent cache engine

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- fuzzy query matching

-- ============================================================================
-- TIER 1: Documents
-- ============================================================================

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_type VARCHAR(50) NOT NULL,
    source VARCHAR(100) NOT NULL,
    jurisdiction VARCHAR(50),
    title VARCHAR(500) NOT NULL,
    source_url TEXT,
    source_format VARCHAR(50),
    version VARCHAR(100),
    effective_date TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    is_current BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_documents_type_source ON documents (document_type, source);
CREATE INDEX IF NOT EXISTS ix_documents_current ON documents (is_current);
CREATE INDEX IF NOT EXISTS ix_documents_jurisdiction ON documents (jurisdiction);

-- ============================================================================
-- TIER 2: Sections
-- ============================================================================

CREATE TABLE IF NOT EXISTS sections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id),
    citation VARCHAR(500),
    parent_citation VARCHAR(500),
    section_number VARCHAR(100),
    section_title VARCHAR(1000),
    hierarchy_path TEXT[],
    sort_order INTEGER DEFAULT 0,
    text_content TEXT NOT NULL,
    section_type VARCHAR(50) DEFAULT 'section',
    version INTEGER NOT NULL DEFAULT 1,
    version_hash VARCHAR(64) NOT NULL,  -- SHA-256
    previous_version_id UUID REFERENCES sections(id),
    effective_date TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    change_type VARCHAR(20) DEFAULT 'initial',
    search_vector TSVECTOR,
    metadata JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    is_current BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_sections_document ON sections (document_id);
CREATE INDEX IF NOT EXISTS ix_sections_citation ON sections (citation);
CREATE INDEX IF NOT EXISTS ix_sections_current ON sections (is_current);
CREATE INDEX IF NOT EXISTS ix_sections_search ON sections USING gin (search_vector);
CREATE INDEX IF NOT EXISTS ix_sections_tags ON sections USING gin (tags);
CREATE INDEX IF NOT EXISTS ix_sections_hierarchy ON sections (document_id, sort_order);
CREATE INDEX IF NOT EXISTS ix_sections_version ON sections (citation, version);

-- Auto-generate search vector
CREATE OR REPLACE FUNCTION sections_search_vector_trigger() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.citation, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.section_title, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.text_content, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sections_search_update
    BEFORE INSERT OR UPDATE OF citation, section_title, text_content
    ON sections
    FOR EACH ROW
    EXECUTE FUNCTION sections_search_vector_trigger();

-- ============================================================================
-- TIER 3: Chunks (vector search only)
-- ============================================================================

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    section_id UUID NOT NULL REFERENCES sections(id),
    chunk_index INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    embedding vector(384),
    citation VARCHAR(500),
    document_type VARCHAR(50),
    jurisdiction VARCHAR(50),
    char_offset INTEGER DEFAULT 0,
    is_current BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_chunks_section ON chunks (section_id);
CREATE INDEX IF NOT EXISTS ix_chunks_current ON chunks (is_current);
CREATE INDEX IF NOT EXISTS ix_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================================
-- ANSWER CACHE
-- ============================================================================

CREATE TABLE IF NOT EXISTS answer_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    answer_key VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256 composite key
    question_raw TEXT,
    question_normalized TEXT NOT NULL,
    filters JSONB DEFAULT '{}',
    answer_text TEXT NOT NULL,
    source_sections JSONB NOT NULL DEFAULT '[]',  -- source-data manifest
    confidence FLOAT,
    model_used VARCHAR(100),
    generation_ms INTEGER,
    serve_count INTEGER DEFAULT 0,
    storage_tier VARCHAR(10) DEFAULT 'warm',  -- hot, warm, cold
    is_valid BOOLEAN NOT NULL DEFAULT true,
    invalidated_at TIMESTAMPTZ,
    invalidation_reason TEXT,
    previous_version_id UUID REFERENCES answer_cache(id),  -- version chain
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_answer_cache_key ON answer_cache (answer_key);
CREATE INDEX IF NOT EXISTS ix_answer_cache_valid ON answer_cache (is_valid);
CREATE INDEX IF NOT EXISTS ix_answer_cache_tier ON answer_cache (storage_tier) WHERE is_valid = true;
CREATE INDEX IF NOT EXISTS ix_answer_cache_normalized ON answer_cache USING gin (question_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_answer_cache_sections ON answer_cache USING gin (source_sections);

-- ============================================================================
-- CACHED ACTION PLANS (schema only: no code reads or writes these)
-- ============================================================================

CREATE TABLE IF NOT EXISTS action_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intent_key VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256 of normalized intent + filters
    intent_raw TEXT,
    intent_normalized TEXT NOT NULL,
    filters JSONB DEFAULT '{}',
    steps JSONB NOT NULL,  -- ordered tool invocations with parameter slots
    parameter_slots JSONB NOT NULL DEFAULT '{}',  -- typed parameter definitions
    allowed_tools TEXT[] NOT NULL,
    forbidden_tools TEXT[] DEFAULT '{}',
    source_manifest JSONB NOT NULL DEFAULT '[]',
    hmac_signature VARCHAR(128) NOT NULL,
    model_used VARCHAR(100),
    generation_ms INTEGER,
    execution_count INTEGER DEFAULT 0,
    is_valid BOOLEAN NOT NULL DEFAULT true,
    invalidated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_action_plans_key ON action_plans (intent_key);
CREATE INDEX IF NOT EXISTS ix_action_plans_valid ON action_plans (is_valid);

-- ============================================================================
-- PLAN APPROVALS (schema only: no code reads or writes these)
-- ============================================================================

CREATE TABLE IF NOT EXISTS plan_approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID NOT NULL REFERENCES action_plans(id),
    approved_by VARCHAR(200) NOT NULL,
    plan_hash VARCHAR(64) NOT NULL,  -- must match plan's current hash
    parameter_constraints JSONB DEFAULT '{}',
    max_executions INTEGER,
    expires_at TIMESTAMPTZ NOT NULL,
    execution_count INTEGER DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- PLAN EXECUTIONS (Immutable Audit Trail)
-- ============================================================================

CREATE TABLE IF NOT EXISTS plan_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID NOT NULL REFERENCES action_plans(id),
    approval_id UUID REFERENCES plan_approvals(id),
    injected_parameters JSONB NOT NULL,
    step_results JSONB NOT NULL,  -- per-step: input, output, duration_ms, success
    source_versions_at_execution JSONB NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    total_duration_ms INTEGER,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_plan_executions_plan ON plan_executions (plan_id);

-- ============================================================================
-- CHANGE DETECTION (schema only: no code reads or writes these)
-- ============================================================================

CREATE TABLE IF NOT EXISTS source_monitors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_name VARCHAR(200) UNIQUE NOT NULL,
    document_type VARCHAR(50),
    jurisdiction VARCHAR(50),
    check_url TEXT,
    check_method VARCHAR(50) DEFAULT 'hash',  -- hash, etag, last_modified, rss, api
    last_etag VARCHAR(500),
    last_content_hash VARCHAR(64),
    last_check_at TIMESTAMPTZ,
    last_change_at TIMESTAMPTZ,
    check_interval_seconds INTEGER DEFAULT 21600,  -- 6 hours
    is_active BOOLEAN DEFAULT true,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS change_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    monitor_id UUID REFERENCES source_monitors(id),
    change_type VARCHAR(20) NOT NULL,  -- added, amended, repealed, corrected
    affected_sections UUID[] DEFAULT '{}',
    affected_citations TEXT[] DEFAULT '{}',
    diff_summary TEXT,
    processing_status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, complete
    answers_invalidated INTEGER DEFAULT 0,
    plans_invalidated INTEGER DEFAULT 0,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_change_events_status ON change_events (processing_status)
    WHERE processing_status != 'complete';
CREATE INDEX IF NOT EXISTS ix_change_events_citations ON change_events USING gin (affected_citations);

-- ============================================================================
-- GAP DETECTION (schema only: no code reads or writes these)
-- ============================================================================

CREATE TABLE IF NOT EXISTS data_gaps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_text TEXT NOT NULL,
    filters JSONB DEFAULT '{}',
    gap_type VARCHAR(50) DEFAULT 'missing_data',  -- missing_data, insufficient_coverage, no_results
    frequency INTEGER DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_data_gaps_unresolved ON data_gaps (resolved, frequency DESC)
    WHERE resolved = false;

-- ============================================================================
-- SUBSCRIPTIONS & NOTIFICATIONS (schema only: no code reads or writes these)
-- ============================================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(200),
    watch_type VARCHAR(50) NOT NULL,  -- citation, jurisdiction, category, query
    watch_value TEXT NOT NULL,
    filters JSONB DEFAULT '{}',
    notify_email BOOLEAN DEFAULT true,
    notify_push BOOLEAN DEFAULT false,
    notify_in_app BOOLEAN DEFAULT true,
    digest_frequency VARCHAR(20) DEFAULT 'immediate',  -- immediate, daily, weekly
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subscription_id UUID REFERENCES subscriptions(id),
    user_id VARCHAR(200),
    title VARCHAR(500) NOT NULL,
    body TEXT,
    channel VARCHAR(20) NOT NULL,  -- email, push, in_app
    status VARCHAR(20) DEFAULT 'pending',  -- pending, sent, read
    change_event_id UUID REFERENCES change_events(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ
);

-- ============================================================================
-- CACHE METRICS
-- ============================================================================

CREATE TABLE IF NOT EXISTS cache_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric_type VARCHAR(50) NOT NULL,  -- hit, miss, fuzzy_hit, decomposed_hit, invalidation
    answer_key VARCHAR(64),
    query_normalized TEXT,
    filters JSONB,
    generation_ms INTEGER,
    model_used VARCHAR(100),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_cache_metrics_type ON cache_metrics (metric_type, recorded_at);

-- ============================================================================
-- AUTO-UPDATE TIMESTAMPS
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER sections_updated_at BEFORE UPDATE ON sections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER answer_cache_updated_at BEFORE UPDATE ON answer_cache
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
