-- AuraFi local/demo compatibility schema.
-- This is NOT a replacement for database/migrations/001_initial_operational.sql
-- or for PostgreSQL/RDS. It exists to run the MVP journey without a network.

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS local_schema_metadata (
    schema_name TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    compatibility_note TEXT NOT NULL
);

INSERT OR IGNORE INTO local_schema_metadata
    (schema_name, schema_version, compatibility_note)
VALUES
    ('aurafi_local', '1', 'Compatibilidade local/demo; nao substitui PostgreSQL/RDS.');

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    email TEXT NOT NULL CHECK (trim(email) <> '' AND instr(email, '@') > 1),
    email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_challenges (
    challenge_id TEXT PRIMARY KEY,
    email TEXT NOT NULL CHECK (trim(email) <> '' AND instr(email, '@') > 1),
    channel TEXT NOT NULL CHECK (channel IN ('web_widget', 'ios_app', 'simulated')),
    delivery TEXT NOT NULL CHECK (delivery IN ('email', 'mock')),
    otp_digest TEXT NOT NULL CHECK (trim(otp_digest) <> ''),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'verified', 'expired', 'cancelled')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    verified_at TEXT,
    CHECK ((status = 'verified' AND verified_at IS NOT NULL)
        OR (status <> 'verified' AND verified_at IS NULL)),
    CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'expired', 'revoked', 'closed')),
    ended_at TEXT,
    access_token_digest TEXT,
    refresh_token_digest TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    UNIQUE (session_id, account_id),
    CHECK (expires_at > started_at),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

-- A conta e a identidade do canal são conceitos separados. Persistir esta
-- associação mantém o mesmo usuário reconhecível no Widget e no iOS após um
-- restart da única réplica, sem armazenar telefone, wallet ou outro PII.
CREATE TABLE IF NOT EXISTS channel_identities (
    channel_identity_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    channel_name TEXT NOT NULL
        CHECK (channel_name IN ('web_widget', 'ios_app', 'simulated')),
    adapter TEXT NOT NULL CHECK (trim(adapter) <> ''),
    simulated INTEGER NOT NULL DEFAULT 0 CHECK (simulated IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    UNIQUE (account_id, channel_name, adapter),
    CHECK ((channel_name = 'simulated' AND simulated = 1)
        OR (channel_name <> 'simulated' AND simulated = 0))
);

-- Consent is kept because the canonical conversation/message envelope requires
-- an explicit purpose. It stores no policy text or unnecessary PII.
CREATE TABLE IF NOT EXISTS consents (
    consent_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    purpose TEXT NOT NULL
        CHECK (purpose IN ('decision_support', 'conversation', 'memory', 'analytics')),
    status TEXT NOT NULL CHECK (status IN ('granted', 'denied', 'revoked')),
    policy_version TEXT NOT NULL CHECK (trim(policy_version) <> ''),
    captured_at TEXT NOT NULL,
    memory INTEGER,
    analytics INTEGER,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    UNIQUE (consent_id, account_id),
    CHECK (memory IS NULL OR memory IN (0, 1)),
    CHECK (analytics IS NULL OR analytics IN (0, 1))
);

CREATE TABLE IF NOT EXISTS risk_profiles (
    risk_profile_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    declared_profile TEXT,
    status TEXT NOT NULL CHECK (status IN ('declared', 'missing')),
    version TEXT NOT NULL CHECK (trim(version) <> ''),
    declared_at TEXT NOT NULL,
    source TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    UNIQUE (risk_profile_id, account_id),
    UNIQUE (account_id, version),
    CHECK (
        (status = 'declared'
            AND declared_profile IN ('conservative', 'moderate', 'aggressive')
            AND source IN ('questionnaire', 'manual'))
        OR
        (status = 'missing' AND declared_profile IS NULL AND source IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS risk_profile_answers (
    risk_profile_id TEXT NOT NULL,
    question_id TEXT NOT NULL CHECK (trim(question_id) <> ''),
    answer TEXT NOT NULL CHECK (trim(answer) <> '' AND length(answer) <= 200),
    PRIMARY KEY (risk_profile_id, question_id),
    FOREIGN KEY (risk_profile_id) REFERENCES risk_profiles(risk_profile_id)
        ON DELETE RESTRICT
);

CREATE TRIGGER IF NOT EXISTS risk_profiles_append_only_update
BEFORE UPDATE ON risk_profiles
BEGIN
    SELECT RAISE(ABORT, 'risk profiles are append-only');
END;

CREATE TRIGGER IF NOT EXISTS risk_profiles_append_only_delete
BEFORE DELETE ON risk_profiles
BEGIN
    SELECT RAISE(ABORT, 'risk profiles are append-only');
END;

CREATE TABLE IF NOT EXISTS defi_market_observations (
    market_observation_id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source = 'defillama'),
    mode TEXT NOT NULL CHECK (mode IN ('live', 'cache', 'test', 'fallback')),
    observed_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    cache_expires_at TEXT,
    read_only INTEGER NOT NULL DEFAULT 1 CHECK (read_only = 1),
    is_stale INTEGER NOT NULL CHECK (is_stale IN (0, 1)),
    freshness_note TEXT,
    protocol TEXT NOT NULL,
    pool TEXT NOT NULL,
    asset TEXT NOT NULL,
    blockchain TEXT NOT NULL,
    apy_value REAL NOT NULL CHECK (apy_value >= 0),
    apy_unit TEXT NOT NULL CHECK (apy_unit = 'percent_annualized'),
    apy_observed_at TEXT NOT NULL,
    tvl_value REAL NOT NULL CHECK (tvl_value >= 0),
    tvl_currency TEXT NOT NULL,
    tvl_observed_at TEXT NOT NULL,
    liquidity_level TEXT NOT NULL
        CHECK (liquidity_level IN ('low', 'medium', 'high', 'unknown')),
    liquidity_value REAL CHECK (liquidity_value IS NULL OR liquidity_value >= 0),
    liquidity_currency TEXT,
    liquidity_observed_at TEXT NOT NULL,
    risk_score REAL CHECK (risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)),
    risk_level TEXT CHECK (risk_level IS NULL OR risk_level IN ('low', 'medium', 'high', 'unknown')),
    risk_dimensions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(risk_dimensions)),
    audit_status TEXT CHECK (
        audit_status IS NULL OR audit_status IN ('audited', 'partially_audited', 'not_verified', 'unknown')
    ),
    CHECK (NOT is_stale OR (freshness_note IS NOT NULL AND trim(freshness_note) <> ''))
);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY,
    market_observation_id TEXT NOT NULL,
    protocol TEXT NOT NULL,
    pool TEXT NOT NULL,
    asset TEXT NOT NULL,
    blockchain TEXT NOT NULL,
    apy_value REAL NOT NULL CHECK (apy_value >= 0),
    apy_unit TEXT NOT NULL CHECK (apy_unit = 'percent_annualized'),
    apy_observed_at TEXT NOT NULL,
    tvl_value REAL NOT NULL CHECK (tvl_value >= 0),
    tvl_currency TEXT NOT NULL,
    tvl_observed_at TEXT NOT NULL,
    liquidity_level TEXT NOT NULL
        CHECK (liquidity_level IN ('low', 'medium', 'high', 'unknown')),
    liquidity_value REAL CHECK (liquidity_value IS NULL OR liquidity_value >= 0),
    liquidity_currency TEXT,
    liquidity_observed_at TEXT NOT NULL,
    risk_score REAL NOT NULL CHECK (risk_score >= 0 AND risk_score <= 100),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
    risk_dimensions TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(risk_dimensions)),
    audit_status TEXT CHECK (
        audit_status IS NULL OR audit_status IN ('audited', 'partially_audited', 'not_verified', 'unknown')
    ),
    eligibility_status TEXT CHECK (
        eligibility_status IS NULL OR eligibility_status IN ('eligible', 'ineligible', 'needs_profile', 'unknown')
    ),
    eligibility_reason TEXT,
    disclaimer TEXT NOT NULL CHECK (trim(disclaimer) <> ''),
    created_at TEXT NOT NULL,
    FOREIGN KEY (market_observation_id) REFERENCES defi_market_observations(market_observation_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS simulations (
    simulation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    input_amount REAL NOT NULL CHECK (input_amount > 0),
    input_asset TEXT NOT NULL,
    horizons_days TEXT NOT NULL CHECK (json_valid(horizons_days)),
    compare_idle_stablecoin INTEGER NOT NULL DEFAULT 1 CHECK (compare_idle_stablecoin IN (0, 1)),
    assumptions TEXT NOT NULL CHECK (json_valid(assumptions) AND json_type(assumptions) = 'array'),
    data_source_observation_id TEXT,
    generated_at TEXT NOT NULL,
    execution_supported INTEGER NOT NULL DEFAULT 0 CHECK (execution_supported = 0),
    disclaimer TEXT NOT NULL CHECK (trim(disclaimer) <> ''),
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(opportunity_id) ON DELETE RESTRICT,
    FOREIGN KEY (data_source_observation_id) REFERENCES defi_market_observations(market_observation_id)
        ON DELETE RESTRICT,
    UNIQUE (simulation_id, account_id)
);

CREATE TABLE IF NOT EXISTS simulation_scenarios (
    simulation_id TEXT NOT NULL,
    horizon_days INTEGER NOT NULL CHECK (horizon_days IN (30, 180, 365)),
    projected_value REAL NOT NULL,
    projected_yield REAL NOT NULL,
    idle_stablecoin_value REAL,
    currency TEXT NOT NULL,
    PRIMARY KEY (simulation_id, horizon_days),
    FOREIGN KEY (simulation_id) REFERENCES simulations(simulation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    consent_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL CHECK (trim(correlation_id) <> ''),
    channel_name TEXT NOT NULL CHECK (channel_name IN ('web_widget', 'ios_app', 'simulated')),
    adapter TEXT NOT NULL CHECK (trim(adapter) <> ''),
    simulated INTEGER NOT NULL DEFAULT 0 CHECK (simulated IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'waiting_human', 'closed')),
    last_activity_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    FOREIGN KEY (session_id, account_id) REFERENCES sessions(session_id, account_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (consent_id, account_id) REFERENCES consents(consent_id, account_id)
        ON DELETE RESTRICT,
    UNIQUE (conversation_id, account_id),
    CHECK ((channel_name = 'simulated' AND simulated = 1)
        OR (channel_name <> 'simulated' AND simulated = 0))
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    envelope_version TEXT NOT NULL CHECK (envelope_version GLOB '[0-9]*.[0-9]*'),
    message_type TEXT NOT NULL
        CHECK (message_type IN ('user_message', 'assistant_message', 'system_event', 'alert')),
    occurred_at TEXT NOT NULL,
    request_id TEXT,
    correlation_id TEXT NOT NULL CHECK (trim(correlation_id) <> ''),
    subject_type TEXT NOT NULL DEFAULT 'account' CHECK (subject_type = 'account'),
    email_verified INTEGER NOT NULL CHECK (email_verified IN (0, 1)),
    channel_name TEXT NOT NULL CHECK (channel_name IN ('web_widget', 'ios_app', 'simulated')),
    channel_adapter TEXT NOT NULL CHECK (trim(channel_adapter) <> ''),
    channel_simulated INTEGER NOT NULL DEFAULT 0 CHECK (channel_simulated IN (0, 1)),
    consent_id TEXT NOT NULL,
    payload TEXT NOT NULL CHECK (json_valid(payload) AND json_type(payload) = 'object'),
    disclaimer TEXT NOT NULL CHECK (trim(disclaimer) <> ''),
    audit_source TEXT NOT NULL CHECK (trim(audit_source) <> ''),
    audit_schema_version TEXT NOT NULL CHECK (trim(audit_schema_version) <> ''),
    trace_id TEXT,
    audit_actor TEXT NOT NULL CHECK (audit_actor IN ('user', 'hub', 'system', 'human_support')),
    audit_redaction TEXT NOT NULL CHECK (audit_redaction IN ('applied', 'not_required')),
    audit_llm TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(audit_llm) AND json_type(audit_llm) = 'object'),
    audit_data_sources TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(audit_data_sources) AND json_type(audit_data_sources) = 'array'),
    FOREIGN KEY (conversation_id, account_id) REFERENCES conversations(conversation_id, account_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (session_id, account_id) REFERENCES sessions(session_id, account_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    FOREIGN KEY (consent_id, account_id) REFERENCES consents(consent_id, account_id)
        ON DELETE RESTRICT,
    CHECK ((channel_name = 'simulated' AND channel_simulated = 1)
        OR (channel_name <> 'simulated' AND channel_simulated = 0))
);

-- Snapshot operacional do agregado conversacional usado pelo adapter de domínio.
-- Não contém e-mail, tokens, OTP ou outras credenciais; a escrita inteira é
-- atômica para que uma conversa não reapareça com apenas metade das mensagens.
CREATE TABLE IF NOT EXISTS conversation_runtime_state (
    conversation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK (json_valid(state_json) AND json_type(state_json) = 'object'),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    opportunity_id TEXT,
    data_source_observation_id TEXT,
    type TEXT NOT NULL CHECK (type IN ('apy_change', 'risk_change', 'new_opportunity', 'data_stale')),
    title TEXT NOT NULL CHECK (trim(title) <> ''),
    message TEXT NOT NULL CHECK (trim(message) <> ''),
    status TEXT NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read')),
    created_at TEXT NOT NULL,
    observed_at TEXT,
    suggested_action TEXT NOT NULL DEFAULT 'none'
        CHECK (suggested_action IN ('view_opportunity', 'simulate', 'ask_hub', 'none')),
    disclaimer TEXT NOT NULL CHECK (trim(disclaimer) <> ''),
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    FOREIGN KEY (opportunity_id) REFERENCES opportunities(opportunity_id) ON DELETE RESTRICT,
    FOREIGN KEY (data_source_observation_id) REFERENCES defi_market_observations(market_observation_id)
        ON DELETE RESTRICT
);

-- Backs the Idempotency-Key contract (contracts/openapi.yaml); `principal`
-- is the account_id that sent the request, so a retry after a session refresh
-- still replays. Rows written before that change hold a SHA-256 digest of the
-- bearer token, never the token itself.
CREATE TABLE IF NOT EXISTS idempotent_responses (
    principal TEXT NOT NULL,
    route TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER NOT NULL CHECK (response_status >= 200 AND response_status < 300),
    response_payload TEXT NOT NULL CHECK (json_valid(response_payload)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (principal, route, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id, started_at);
CREATE INDEX IF NOT EXISTS idx_channel_identities_account
    ON channel_identities(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_risk_profiles_account ON risk_profiles(account_id, version);
CREATE INDEX IF NOT EXISTS idx_opportunities_created ON opportunities(created_at, opportunity_id);
CREATE INDEX IF NOT EXISTS idx_simulations_account ON simulations(account_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, occurred_at, message_id);
CREATE INDEX IF NOT EXISTS idx_conversation_runtime_account
    ON conversation_runtime_state(account_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_alerts_account_status ON alerts(account_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_idempotent_responses_created ON idempotent_responses(created_at);

COMMIT;
