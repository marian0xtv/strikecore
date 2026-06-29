-- StrikeCore — Postgres schema (Phase A baseline)
-- ============================================================================
-- Normalized entities + audit-chain + token ledger + memory store.
-- Every deduplicable entity carries a fingerprint_sha256 UNIQUE column.
-- Foreign-key cascades are deliberately conservative — historical traces and
-- ledger rows MUST survive entity/dossier deletion (kept as ORPHAN with NULL FK).
-- pgvector embeddings use dim=1536 (OpenAI text-embedding-3-small / Voyage v2);
-- swap when Anthropic exposes a first-party embedding endpoint.

SET client_min_messages = WARNING;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- ENUMS (idempotent — DROP-recreate gated to first-time setup)
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE entity_kind AS ENUM (
        'person', 'org', 'domain', 'ip', 'email', 'phone', 'handle', 'asset', 'other'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE dossier_status AS ENUM (
        'planning', 'collecting', 'synthesizing', 'completed', 'failed', 'aborted'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE agent_role AS ENUM (
        'planner', 'executor', 'critic', 'improver', 'synthesizer',
        'memory_writer', 'pir_router', 'subagent'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE agent_run_status AS ENUM (
        'pending', 'running', 'completed', 'failed', 'cancelled', 'budget_exceeded'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE improvement_category AS ENUM (
        'quality', 'efficiency', 'reliability', 'safety'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE trace_level AS ENUM (
        'debug', 'info', 'warn', 'error'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================================================================
-- IDENTITY: USER (single-operator scaffold, JWT-ready)
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_user (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'operator',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

INSERT INTO app_user (username, display_name, role)
    VALUES ('atlas', 'atlas (default operator)', 'operator')
    ON CONFLICT (username) DO NOTHING;

-- ============================================================================
-- ENTITY: dedup'd person / org / domain / ip / email / phone / handle / asset
-- ============================================================================

CREATE TABLE IF NOT EXISTS entity (
    id                  BIGSERIAL PRIMARY KEY,
    kind                entity_kind NOT NULL,
    canonical_value     TEXT NOT NULL,
    fingerprint_sha256  CHAR(64) NOT NULL UNIQUE,   -- sha256(kind || ':' || canonical_value)
    display_name        TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS entity_kind_idx          ON entity (kind);
CREATE INDEX IF NOT EXISTS entity_canonical_trgm_idx ON entity USING GIN (canonical_value gin_trgm_ops);
CREATE INDEX IF NOT EXISTS entity_metadata_gin_idx  ON entity USING GIN (metadata jsonb_path_ops);

-- ============================================================================
-- SOURCE: provenance for every finding
-- ============================================================================

CREATE TABLE IF NOT EXISTS source (
    id                  BIGSERIAL PRIMARY KEY,
    url                 TEXT,
    content_sha256      CHAR(64),                       -- NULL allowed for live API sources
    tool_name           TEXT NOT NULL,                  -- e.g. 'h8mail', 'sherlock', 'crt.sh'
    upstream            TEXT NOT NULL,                  -- canonical upstream provider (e.g. 'hibp', 'github')
    reliability         CHAR(1) NOT NULL DEFAULT 'C',   -- NATO Admiralty A-F
    credibility         CHAR(1) NOT NULL DEFAULT '3',   -- NATO Admiralty 1-6
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload         JSONB,
    UNIQUE NULLS NOT DISTINCT (url, content_sha256)     -- dedup by (URL, content) — PG ≥15
);

CREATE INDEX IF NOT EXISTS source_tool_idx       ON source (tool_name);
CREATE INDEX IF NOT EXISTS source_upstream_idx   ON source (upstream);
CREATE INDEX IF NOT EXISTS source_fetched_at_idx ON source (fetched_at DESC);

-- ============================================================================
-- DOSSIER: a Priority Intelligence Requirement realised as a structured report
-- ============================================================================

CREATE TABLE IF NOT EXISTS dossier (
    id                  BIGSERIAL PRIMARY KEY,
    target_entity_id    BIGINT REFERENCES entity (id) ON DELETE SET NULL,
    pir_question        TEXT NOT NULL,
    operator_id         INT REFERENCES app_user (id) ON DELETE SET NULL,
    status              dossier_status NOT NULL DEFAULT 'planning',
    bluf                TEXT,
    summary_markdown    TEXT,
    summary_json        JSONB,
    token_budget_micros BIGINT,                          -- 1 USD = 1_000_000 micros; NULL = no cap
    cost_micros         BIGINT NOT NULL DEFAULT 0,
    cache_hit_ratio     REAL,                            -- 0..1, populated by critic
    quality_score       REAL,                            -- 0..1, populated by critic
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    constraints         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS dossier_target_idx    ON dossier (target_entity_id);
CREATE INDEX IF NOT EXISTS dossier_status_idx    ON dossier (status);
CREATE INDEX IF NOT EXISTS dossier_created_idx   ON dossier (created_at DESC);
CREATE INDEX IF NOT EXISTS dossier_operator_idx  ON dossier (operator_id);

-- Findings persisted as JSONB rows for flexibility; dedup'd by (dossier, entity, type, value)
CREATE TABLE IF NOT EXISTS dossier_finding (
    id                  BIGSERIAL PRIMARY KEY,
    dossier_id          BIGINT NOT NULL REFERENCES dossier (id) ON DELETE CASCADE,
    domain              TEXT NOT NULL,                   -- socint | socialint | geoint | webint | techint | threatint | crossdb
    finding_type        TEXT NOT NULL,
    value               TEXT NOT NULL,
    related_entity_id   BIGINT REFERENCES entity (id) ON DELETE SET NULL,
    confidence          REAL NOT NULL DEFAULT 0.0,
    notes               TEXT,
    fingerprint_sha256  CHAR(64) NOT NULL,               -- sha256(dossier_id || domain || type || value)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (fingerprint_sha256)
);

CREATE INDEX IF NOT EXISTS finding_dossier_idx ON dossier_finding (dossier_id);
CREATE INDEX IF NOT EXISTS finding_domain_idx  ON dossier_finding (domain);
CREATE INDEX IF NOT EXISTS finding_entity_idx  ON dossier_finding (related_entity_id);

-- Finding ↔ Source many-to-many (provenance chain)
CREATE TABLE IF NOT EXISTS finding_source (
    finding_id   BIGINT NOT NULL REFERENCES dossier_finding (id) ON DELETE CASCADE,
    source_id    BIGINT NOT NULL REFERENCES source (id) ON DELETE CASCADE,
    PRIMARY KEY (finding_id, source_id)
);

-- ============================================================================
-- AGENT RUN + SUBAGENT INVOCATION (Hermes-style tracing)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_run (
    id                  BIGSERIAL PRIMARY KEY,
    dossier_id          BIGINT REFERENCES dossier (id) ON DELETE SET NULL,
    parent_run_id       BIGINT REFERENCES agent_run (id) ON DELETE SET NULL,
    role                agent_role NOT NULL,
    agent_name          TEXT NOT NULL,
    status              agent_run_status NOT NULL DEFAULT 'pending',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    input               JSONB,
    output              JSONB,
    error_text          TEXT,
    cost_micros         BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS run_dossier_idx     ON agent_run (dossier_id);
CREATE INDEX IF NOT EXISTS run_parent_idx      ON agent_run (parent_run_id);
CREATE INDEX IF NOT EXISTS run_role_idx        ON agent_run (role);
CREATE INDEX IF NOT EXISTS run_started_idx     ON agent_run (started_at DESC);
CREATE INDEX IF NOT EXISTS run_status_idx      ON agent_run (status);

CREATE TABLE IF NOT EXISTS subagent_invocation (
    id                  BIGSERIAL PRIMARY KEY,
    agent_run_id        BIGINT NOT NULL REFERENCES agent_run (id) ON DELETE CASCADE,
    tool_name           TEXT NOT NULL,
    input               JSONB NOT NULL,
    output              JSONB,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    success             BOOLEAN,
    error_text          TEXT,
    duration_ms         INT,
    cost_micros         BIGINT NOT NULL DEFAULT 0,
    input_hash          CHAR(64)                          -- for dedup_cache hits
);

CREATE INDEX IF NOT EXISTS subinv_run_idx       ON subagent_invocation (agent_run_id);
CREATE INDEX IF NOT EXISTS subinv_tool_idx      ON subagent_invocation (tool_name);
CREATE INDEX IF NOT EXISTS subinv_started_idx   ON subagent_invocation (started_at DESC);
CREATE INDEX IF NOT EXISTS subinv_hash_idx      ON subagent_invocation (input_hash);

-- ============================================================================
-- TRACE: every event in the agent loop (for live WebSocket stream)
-- ============================================================================

CREATE TABLE IF NOT EXISTS trace (
    id                  BIGSERIAL PRIMARY KEY,
    agent_run_id        BIGINT REFERENCES agent_run (id) ON DELETE CASCADE,
    subagent_inv_id     BIGINT REFERENCES subagent_invocation (id) ON DELETE CASCADE,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level               trace_level NOT NULL DEFAULT 'info',
    event               TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    hash_sha256         CHAR(64) NOT NULL                 -- SHA-256 chain-of-custody
);

CREATE INDEX IF NOT EXISTS trace_run_idx     ON trace (agent_run_id);
CREATE INDEX IF NOT EXISTS trace_ts_idx      ON trace (ts DESC);
CREATE INDEX IF NOT EXISTS trace_event_idx   ON trace (event);

-- pg_notify trigger so the FastAPI backend can stream live to /ws/traces
CREATE OR REPLACE FUNCTION notify_trace() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('trace_channel', json_build_object(
        'id', NEW.id,
        'agent_run_id', NEW.agent_run_id,
        'event', NEW.event,
        'ts', NEW.ts
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trace_notify_trigger ON trace;
CREATE TRIGGER trace_notify_trigger AFTER INSERT ON trace
    FOR EACH ROW EXECUTE FUNCTION notify_trace();

-- ============================================================================
-- IMPROVEMENT: critic-produced suggestions; improver consolidates after N evidence
-- ============================================================================

CREATE TABLE IF NOT EXISTS improvement (
    id                  BIGSERIAL PRIMARY KEY,
    agent_run_id        BIGINT REFERENCES agent_run (id) ON DELETE SET NULL,
    category            improvement_category NOT NULL,
    target_component    TEXT NOT NULL,                    -- e.g. 'planner.system_prompt', 'router.task[email_dedup]'
    description         TEXT NOT NULL,
    description_embed   vector(1536),                     -- for semantic grouping in improver
    evidence_count      INT NOT NULL DEFAULT 1,
    applied             BOOLEAN NOT NULL DEFAULT FALSE,
    applied_at          TIMESTAMPTZ,
    patch               JSONB,                            -- the actual change
    patch_revert        JSONB,                            -- inverse change (for revert)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS imp_category_idx  ON improvement (category);
CREATE INDEX IF NOT EXISTS imp_applied_idx   ON improvement (applied);
CREATE INDEX IF NOT EXISTS imp_target_idx    ON improvement (target_component);
CREATE INDEX IF NOT EXISTS imp_embed_idx     ON improvement USING ivfflat (description_embed vector_cosine_ops);

-- ============================================================================
-- TOKEN LEDGER: every LLM call (Hermes has rate-limit tracker; we add cost ledger)
-- ============================================================================

CREATE TABLE IF NOT EXISTS token_ledger (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_run_id        BIGINT REFERENCES agent_run (id) ON DELETE SET NULL,
    subagent_inv_id     BIGINT REFERENCES subagent_invocation (id) ON DELETE SET NULL,
    dossier_id          BIGINT REFERENCES dossier (id) ON DELETE SET NULL,
    provider            TEXT NOT NULL,                    -- 'anthropic' / 'openrouter' / 'ollama' / …
    model               TEXT NOT NULL,
    task_type           TEXT,                             -- 'planner' / 'critic' / 'specialist:socint' / …
    input_tokens        INT NOT NULL,
    output_tokens       INT NOT NULL,
    cached_tokens       INT NOT NULL DEFAULT 0,
    cost_usd_micros     BIGINT NOT NULL DEFAULT 0,        -- 1 USD = 1_000_000
    latency_ms          INT,
    cache_hit           BOOLEAN NOT NULL DEFAULT FALSE,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS ledger_ts_idx        ON token_ledger (ts DESC);
CREATE INDEX IF NOT EXISTS ledger_dossier_idx   ON token_ledger (dossier_id);
CREATE INDEX IF NOT EXISTS ledger_run_idx       ON token_ledger (agent_run_id);
CREATE INDEX IF NOT EXISTS ledger_model_idx     ON token_ledger (model);
CREATE INDEX IF NOT EXISTS ledger_task_idx      ON token_ledger (task_type);

-- ============================================================================
-- MODEL ROUTING: adaptive task_type → model policy (Phase D wires the bandit)
-- ============================================================================

CREATE TABLE IF NOT EXISTS model_routing (
    task_type           TEXT PRIMARY KEY,
    preferred_model     TEXT NOT NULL,
    alt_model_chain     JSONB NOT NULL DEFAULT '[]'::jsonb,
    success_count       BIGINT NOT NULL DEFAULT 0,
    failure_count       BIGINT NOT NULL DEFAULT 0,
    explore_pct         REAL NOT NULL DEFAULT 0.05,       -- bandit exploration rate
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sensible defaults (Phase A bootstrap; Phase D updates from outcomes)
INSERT INTO model_routing (task_type, preferred_model, alt_model_chain) VALUES
    ('planner',                     'claude-sonnet-4-6',         '["claude-opus-4-7"]'::jsonb),
    ('executor',                    'claude-haiku-4-5-20251001', '["claude-sonnet-4-6"]'::jsonb),
    ('critic',                      'claude-haiku-4-5-20251001', '["claude-sonnet-4-6"]'::jsonb),
    ('synthesizer',                 'claude-opus-4-7',           '["claude-sonnet-4-6"]'::jsonb),
    ('memory_compressor',           'claude-haiku-4-5-20251001', '[]'::jsonb),
    ('pir_router',                  'claude-haiku-4-5-20251001', '["claude-sonnet-4-6"]'::jsonb),
    ('specialist:socint',           'claude-sonnet-4-6',         '["claude-haiku-4-5-20251001"]'::jsonb),
    ('specialist:socialint',        'claude-sonnet-4-6',         '["claude-haiku-4-5-20251001"]'::jsonb),
    ('specialist:geoint',           'claude-sonnet-4-6',         '["claude-haiku-4-5-20251001"]'::jsonb),
    ('specialist:webint',           'claude-sonnet-4-6',         '["claude-haiku-4-5-20251001"]'::jsonb),
    ('specialist:audit',            'claude-sonnet-4-6',         '["claude-haiku-4-5-20251001"]'::jsonb),
    ('specialist:analyst',          'claude-opus-4-7',           '["claude-sonnet-4-6"]'::jsonb)
ON CONFLICT (task_type) DO NOTHING;

-- ============================================================================
-- MEMORY: pgvector embeddings + summaries
-- ============================================================================

CREATE TABLE IF NOT EXISTS memory_embedding (
    id                  BIGSERIAL PRIMARY KEY,
    entity_id           BIGINT REFERENCES entity (id) ON DELETE CASCADE,
    dossier_id          BIGINT REFERENCES dossier (id) ON DELETE SET NULL,
    source_run_id       BIGINT REFERENCES agent_run (id) ON DELETE SET NULL,
    content_chunk       TEXT NOT NULL,
    embedding           vector(1536) NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS memory_embed_idx    ON memory_embedding USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS memory_entity_idx   ON memory_embedding (entity_id);
CREATE INDEX IF NOT EXISTS memory_dossier_idx  ON memory_embedding (dossier_id);

CREATE TABLE IF NOT EXISTS memory_summary (
    id                      BIGSERIAL PRIMARY KEY,
    agent_run_id            BIGINT REFERENCES agent_run (id) ON DELETE SET NULL,
    dossier_id              BIGINT REFERENCES dossier (id) ON DELETE SET NULL,
    summary                 TEXT NOT NULL,
    original_token_count    INT NOT NULL,
    summary_token_count     INT NOT NULL,
    compression_ratio       REAL GENERATED ALWAYS AS (
        CASE WHEN original_token_count = 0 THEN 0
             ELSE summary_token_count::real / original_token_count::real END
    ) STORED,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS msum_run_idx     ON memory_summary (agent_run_id);
CREATE INDEX IF NOT EXISTS msum_dossier_idx ON memory_summary (dossier_id);

-- ============================================================================
-- BUDGET BUCKETS (Phase D will enforce; Phase A persists scaffold)
-- ============================================================================

CREATE TABLE IF NOT EXISTS budget_bucket (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,             -- 'daily', 'monthly', 'per_dossier_default'
    period              TEXT NOT NULL,                    -- 'day' | 'month' | 'dossier'
    cap_micros          BIGINT NOT NULL,                  -- USD micros
    soft_cap_pct        REAL NOT NULL DEFAULT 0.8,
    action_at_soft      TEXT NOT NULL DEFAULT 'warn',     -- warn|downgrade
    action_at_hard      TEXT NOT NULL DEFAULT 'throttle', -- throttle|stop
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO budget_bucket (name, period, cap_micros, soft_cap_pct, action_at_soft, action_at_hard) VALUES
    ('daily',               'day',      10000000,  0.80, 'downgrade', 'throttle'),
    ('monthly',             'month',   200000000,  0.85, 'warn',      'throttle'),
    ('per_dossier_default', 'dossier',   1500000,  0.70, 'downgrade', 'warn')
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- SCHEMA VERSION (for Alembic baseline reconciliation)
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes       TEXT
);

INSERT INTO schema_version (version, notes) VALUES
    ('2026.05.16.A.baseline', 'Phase A: postgres+pgvector unification, normalized entities, token ledger, model routing scaffold')
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- updated_at triggers
-- ============================================================================

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS entity_touch ON entity;
CREATE TRIGGER entity_touch BEFORE UPDATE ON entity
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS improvement_touch ON improvement;
CREATE TRIGGER improvement_touch BEFORE UPDATE ON improvement
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ============================================================================
-- investigation — document store for the per-target dossier (JSONB swap)
-- ============================================================================
-- Replaces the file-backed core/investigation_store.py persistence. The rich
-- nested shape (identity / emails / phones / profiles / organizations /
-- locations / social_graph / breaches / documents / timeline / devices /
-- notes / raw_evidence / phase_log) lives intact in `data`. This makes
-- Postgres the single cross-container state plane (backend reader + toolbox
-- writer) without sharing a mutable file over a bind mount. Document/photo
-- BLOBS still live on disk (referenced by path inside `data`).
CREATE TABLE IF NOT EXISTS investigation (
    target_id   TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    updated     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- jsonb_path_ops GIN: cheap containment queries on sub-fields later if needed.
CREATE INDEX IF NOT EXISTS investigation_data_gin
    ON investigation USING gin (data jsonb_path_ops);

INSERT INTO schema_version (version, notes) VALUES
    ('2026.06.29.B.investigation_jsonb', 'Containerization: investigation JSONB document store (single state plane)')
ON CONFLICT (version) DO NOTHING;
