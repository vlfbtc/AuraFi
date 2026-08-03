-- AuraFi operational database - migration 001
-- PostgreSQL-compatible. This migration is additive and contains no DROP/TRUNCATE.
-- It deliberately does not create wallet, execution, Open Finance, billing, or seed data.

BEGIN;

CREATE SCHEMA IF NOT EXISTS aurafi;

CREATE TABLE IF NOT EXISTS aurafi.schema_migrations (
    version     text PRIMARY KEY,
    description text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A second direct execution is rejected before any domain DDL runs. Migration
-- runners may treat an already-recorded version as a no-op instead.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM aurafi.schema_migrations
         WHERE version = '001_initial_operational'
    ) THEN
        RAISE EXCEPTION 'Migration 001_initial_operational is already applied';
    END IF;
END;
$$;

CREATE TABLE aurafi.accounts (
    account_id     text PRIMARY KEY,
    email          text NOT NULL,
    email_verified boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT accounts_account_id_not_blank CHECK (btrim(account_id) <> ''),
    CONSTRAINT accounts_email_not_blank CHECK (btrim(email) <> ''),
    CONSTRAINT accounts_email_shape CHECK (position('@' IN email) > 1)
);

CREATE TABLE aurafi.otp_challenges (
    challenge_id text PRIMARY KEY,
    email        text NOT NULL,
    channel      text NOT NULL,
    delivery     text NOT NULL,
    status       text NOT NULL DEFAULT 'pending',
    expires_at   timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_at  timestamptz,
    CONSTRAINT otp_challenges_channel_ck
        CHECK (channel IN ('web_widget', 'ios_app', 'simulated')),
    CONSTRAINT otp_challenges_delivery_ck
        CHECK (delivery IN ('email', 'mock')),
    CONSTRAINT otp_challenges_status_ck
        CHECK (status IN ('pending', 'verified', 'expired', 'cancelled')),
    CONSTRAINT otp_challenges_dates_ck CHECK (expires_at > created_at),
    CONSTRAINT otp_challenges_verified_at_ck CHECK (
        (status = 'verified' AND verified_at IS NOT NULL)
        OR (status <> 'verified' AND verified_at IS NULL)
    ),
    CONSTRAINT otp_challenges_email_not_blank CHECK (btrim(email) <> '')
);

CREATE TABLE aurafi.sessions (
    session_id text PRIMARY KEY,
    account_id text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    status     text NOT NULL DEFAULT 'active',
    ended_at   timestamptz,
    CONSTRAINT sessions_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT sessions_session_account_uq UNIQUE (session_id, account_id),
    CONSTRAINT sessions_status_ck
        CHECK (status IN ('active', 'expired', 'revoked', 'closed')),
    CONSTRAINT sessions_dates_ck CHECK (expires_at > started_at),
    CONSTRAINT sessions_ended_at_ck CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE aurafi.channel_identities (
    channel_identity_id text PRIMARY KEY,
    account_id          text NOT NULL,
    channel_name        text NOT NULL,
    adapter             text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT channel_identities_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT channel_identities_id_account_uq UNIQUE (channel_identity_id, account_id),
    CONSTRAINT channel_identities_channel_ck
        CHECK (channel_name IN ('web_widget', 'ios_app', 'simulated')),
    CONSTRAINT channel_identities_adapter_not_blank CHECK (btrim(adapter) <> '')
);

CREATE TABLE aurafi.consents (
    consent_id     text PRIMARY KEY,
    account_id     text NOT NULL,
    purpose        text NOT NULL,
    status         text NOT NULL,
    policy_version text NOT NULL,
    captured_at    timestamptz NOT NULL,
    memory         boolean,
    analytics      boolean,
    CONSTRAINT consents_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT consents_consent_account_uq UNIQUE (consent_id, account_id),
    CONSTRAINT consents_purpose_ck
        CHECK (purpose IN ('decision_support', 'conversation', 'memory', 'analytics')),
    CONSTRAINT consents_status_ck
        CHECK (status IN ('granted', 'denied', 'revoked')),
    CONSTRAINT consents_policy_version_not_blank CHECK (btrim(policy_version) <> '')
);

CREATE TABLE aurafi.risk_profiles (
    risk_profile_id text PRIMARY KEY,
    account_id      text NOT NULL,
    declared_profile text,
    status          text NOT NULL,
    version         text NOT NULL,
    declared_at     timestamptz NOT NULL,
    source          text,
    CONSTRAINT risk_profiles_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT risk_profiles_id_account_uq UNIQUE (risk_profile_id, account_id),
    CONSTRAINT risk_profiles_account_version_uq UNIQUE (account_id, version),
    CONSTRAINT risk_profiles_status_ck
        CHECK (status IN ('declared', 'missing')),
    CONSTRAINT risk_profiles_profile_ck CHECK (
        (status = 'declared'
            AND declared_profile IS NOT NULL
            AND declared_profile IN ('conservative', 'moderate', 'aggressive')
            AND source IS NOT NULL
            AND source IN ('questionnaire', 'manual'))
        OR
        (status = 'missing' AND declared_profile IS NULL AND source IS NULL)
    ),
    CONSTRAINT risk_profiles_version_not_blank CHECK (btrim(version) <> '')
);

CREATE TABLE aurafi.risk_profile_answers (
    risk_profile_id text NOT NULL,
    question_id     text NOT NULL,
    answer          text NOT NULL,
    CONSTRAINT risk_profile_answers_pk PRIMARY KEY (risk_profile_id, question_id),
    CONSTRAINT risk_profile_answers_profile_fk
        FOREIGN KEY (risk_profile_id) REFERENCES aurafi.risk_profiles (risk_profile_id)
        ON DELETE RESTRICT,
    CONSTRAINT risk_profile_answers_question_ck CHECK (btrim(question_id) <> ''),
    CONSTRAINT risk_profile_answers_answer_ck CHECK (
        btrim(answer) <> '' AND char_length(answer) <= 200
    )
);

CREATE TABLE aurafi.defi_market_observations (
    market_observation_id text PRIMARY KEY,
    source                text NOT NULL,
    mode                  text NOT NULL,
    observed_at           timestamptz NOT NULL,
    retrieved_at          timestamptz NOT NULL,
    cache_expires_at      timestamptz,
    read_only             boolean NOT NULL DEFAULT true,
    is_stale              boolean NOT NULL,
    freshness_note        text,
    protocol              text NOT NULL,
    pool                  text NOT NULL,
    asset                 text NOT NULL,
    blockchain            text NOT NULL,
    apy_value             numeric NOT NULL,
    apy_unit              text NOT NULL,
    apy_observed_at       timestamptz NOT NULL,
    tvl_value             numeric NOT NULL,
    tvl_currency          text NOT NULL,
    tvl_observed_at       timestamptz NOT NULL,
    liquidity_level       text NOT NULL,
    liquidity_value       numeric,
    liquidity_currency    text,
    liquidity_observed_at timestamptz NOT NULL,
    risk_score            numeric,
    risk_level            text,
    risk_dimensions       text[] NOT NULL DEFAULT '{}',
    audit_status          text,
    CONSTRAINT defi_observations_source_ck CHECK (source = 'defillama'),
    CONSTRAINT defi_observations_mode_ck
        CHECK (mode IN ('live', 'cache', 'test', 'fallback')),
    CONSTRAINT defi_observations_read_only_ck CHECK (read_only IS TRUE),
    CONSTRAINT defi_observations_freshness_note_ck CHECK (
        NOT is_stale
        OR (freshness_note IS NOT NULL AND btrim(freshness_note) <> '')
    ),
    CONSTRAINT defi_observations_values_ck CHECK (
        apy_value >= 0
        AND tvl_value >= 0
        AND (liquidity_value IS NULL OR liquidity_value >= 0)
        AND (risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100))
    ),
    CONSTRAINT defi_observations_apy_unit_ck CHECK (apy_unit = 'percent_annualized'),
    CONSTRAINT defi_observations_liquidity_level_ck
        CHECK (liquidity_level IN ('low', 'medium', 'high', 'unknown')),
    CONSTRAINT defi_observations_risk_level_ck
        CHECK (risk_level IS NULL OR risk_level IN ('low', 'medium', 'high', 'unknown')),
    CONSTRAINT defi_observations_audit_status_ck CHECK (
        audit_status IS NULL
        OR audit_status IN ('audited', 'partially_audited', 'not_verified', 'unknown')
    ),
    CONSTRAINT defi_observations_risk_dimensions_ck CHECK (
        risk_dimensions <@ ARRAY[
            'smart_contract', 'liquidity', 'volatility',
            'underlying_asset', 'counterparty', 'data_quality'
        ]::text[]
    )
);

CREATE TABLE aurafi.opportunities (
    opportunity_id             text PRIMARY KEY,
    market_observation_id     text NOT NULL,
    protocol                   text NOT NULL,
    pool                       text NOT NULL,
    asset                      text NOT NULL,
    blockchain                 text NOT NULL,
    apy_value                  numeric NOT NULL,
    apy_unit                   text NOT NULL,
    apy_observed_at            timestamptz NOT NULL,
    tvl_value                  numeric NOT NULL,
    tvl_currency               text NOT NULL,
    tvl_observed_at            timestamptz NOT NULL,
    liquidity_level            text NOT NULL,
    liquidity_value            numeric,
    liquidity_currency         text,
    liquidity_observed_at      timestamptz NOT NULL,
    risk_score                 numeric NOT NULL,
    risk_level                 text NOT NULL,
    risk_dimensions            text[] NOT NULL DEFAULT '{}',
    audit_status               text,
    eligibility_status         text,
    eligibility_reason         text,
    disclaimer                 text NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT opportunities_observation_fk
        FOREIGN KEY (market_observation_id)
        REFERENCES aurafi.defi_market_observations (market_observation_id)
        ON DELETE RESTRICT,
    CONSTRAINT opportunities_values_ck CHECK (
        apy_value >= 0
        AND tvl_value >= 0
        AND (liquidity_value IS NULL OR liquidity_value >= 0)
        AND risk_score >= 0 AND risk_score <= 100
    ),
    CONSTRAINT opportunities_apy_unit_ck CHECK (apy_unit = 'percent_annualized'),
    CONSTRAINT opportunities_liquidity_level_ck
        CHECK (liquidity_level IN ('low', 'medium', 'high', 'unknown')),
    CONSTRAINT opportunities_risk_level_ck
        CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
    CONSTRAINT opportunities_risk_dimensions_ck CHECK (
        risk_dimensions <@ ARRAY[
            'smart_contract', 'liquidity', 'volatility',
            'underlying_asset', 'counterparty', 'data_quality'
        ]::text[]
    ),
    CONSTRAINT opportunities_audit_status_ck CHECK (
        audit_status IS NULL
        OR audit_status IN ('audited', 'partially_audited', 'not_verified', 'unknown')
    ),
    CONSTRAINT opportunities_eligibility_ck CHECK (
        eligibility_status IS NULL
        OR eligibility_status IN ('eligible', 'ineligible', 'needs_profile', 'unknown')
    ),
    CONSTRAINT opportunities_disclaimer_ck CHECK (btrim(disclaimer) <> '')
);

CREATE FUNCTION aurafi.has_unique_integer_array(input_values integer[])
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT cardinality(input_values) = (
        SELECT count(DISTINCT value)
          FROM unnest(input_values) AS item(value)
    );
$$;

CREATE TABLE aurafi.simulations (
    simulation_id                    text PRIMARY KEY,
    account_id                       text NOT NULL,
    opportunity_id                   text NOT NULL,
    input_amount                     numeric NOT NULL,
    input_asset                      text NOT NULL,
    horizons_days                    integer[] NOT NULL,
    compare_idle_stablecoin          boolean NOT NULL DEFAULT true,
    assumptions                      jsonb NOT NULL,
    data_source_observation_id      text,
    generated_at                     timestamptz NOT NULL,
    execution_supported              boolean NOT NULL DEFAULT false,
    disclaimer                       text NOT NULL,
    CONSTRAINT simulations_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT simulations_id_account_uq UNIQUE (simulation_id, account_id),
    CONSTRAINT simulations_opportunity_fk
        FOREIGN KEY (opportunity_id) REFERENCES aurafi.opportunities (opportunity_id)
        ON DELETE RESTRICT,
    CONSTRAINT simulations_observation_fk
        FOREIGN KEY (data_source_observation_id)
        REFERENCES aurafi.defi_market_observations (market_observation_id)
        ON DELETE RESTRICT,
    CONSTRAINT simulations_amount_ck CHECK (input_amount > 0),
    CONSTRAINT simulations_horizons_count_ck CHECK (cardinality(horizons_days) BETWEEN 1 AND 3),
    CONSTRAINT simulations_horizons_values_ck
        CHECK (horizons_days <@ ARRAY[30, 180, 365]::integer[]),
    CONSTRAINT simulations_horizons_unique_ck
        CHECK (aurafi.has_unique_integer_array(horizons_days)),
    CONSTRAINT simulations_assumptions_array_ck CHECK (jsonb_typeof(assumptions) = 'array'),
    CONSTRAINT simulations_execution_ck CHECK (execution_supported IS FALSE),
    CONSTRAINT simulations_disclaimer_ck CHECK (btrim(disclaimer) <> '')
);

CREATE TABLE aurafi.simulation_scenarios (
    simulation_id          text NOT NULL,
    horizon_days           integer NOT NULL,
    projected_value        numeric NOT NULL,
    projected_yield        numeric NOT NULL,
    idle_stablecoin_value  numeric,
    currency               text NOT NULL,
    CONSTRAINT simulation_scenarios_pk PRIMARY KEY (simulation_id, horizon_days),
    CONSTRAINT simulation_scenarios_simulation_fk
        FOREIGN KEY (simulation_id) REFERENCES aurafi.simulations (simulation_id)
        ON DELETE RESTRICT,
    CONSTRAINT simulation_scenarios_horizon_ck
        CHECK (horizon_days IN (30, 180, 365))
);

CREATE TABLE aurafi.conversations (
    conversation_id text PRIMARY KEY,
    account_id      text NOT NULL,
    session_id      text NOT NULL,
    consent_id      text NOT NULL,
    correlation_id  text NOT NULL,
    channel_name    text NOT NULL,
    adapter         text NOT NULL,
    simulated       boolean NOT NULL DEFAULT false,
    status          text NOT NULL DEFAULT 'active',
    last_activity_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT conversations_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT conversations_id_account_uq UNIQUE (conversation_id, account_id),
    CONSTRAINT conversations_session_fk
        FOREIGN KEY (session_id, account_id)
        REFERENCES aurafi.sessions (session_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT conversations_consent_fk
        FOREIGN KEY (consent_id, account_id)
        REFERENCES aurafi.consents (consent_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT conversations_channel_ck
        CHECK (channel_name IN ('web_widget', 'ios_app', 'simulated')),
    CONSTRAINT conversations_simulated_ck CHECK (
        (channel_name = 'simulated' AND simulated IS TRUE)
        OR (channel_name <> 'simulated' AND simulated IS FALSE)
    ),
    CONSTRAINT conversations_adapter_not_blank CHECK (btrim(adapter) <> ''),
    CONSTRAINT conversations_status_ck
        CHECK (status IN ('active', 'waiting_human', 'closed')),
    CONSTRAINT conversations_correlation_not_blank CHECK (btrim(correlation_id) <> '')
);

CREATE TABLE aurafi.recommendations (
    recommendation_id text PRIMARY KEY,
    account_id        text NOT NULL,
    risk_profile_id   text NOT NULL,
    profile_used      text NOT NULL,
    conversation_id   text,
    channel_name      text,
    channel_adapter   text,
    channel_simulated boolean,
    status            text NOT NULL,
    explanation       text NOT NULL,
    disclaimer        text NOT NULL,
    generated_at      timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    llm_mode          text,
    llm_provider      text,
    llm_model         text,
    llm_prompt_version text,
    llm_mockable      boolean,
    llm_explainability text,
    llm_fallback      text,
    CONSTRAINT recommendations_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT recommendations_id_account_uq UNIQUE (recommendation_id, account_id),
    CONSTRAINT recommendations_profile_fk
        FOREIGN KEY (risk_profile_id, account_id)
        REFERENCES aurafi.risk_profiles (risk_profile_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT recommendations_conversation_fk
        FOREIGN KEY (conversation_id, account_id)
        REFERENCES aurafi.conversations (conversation_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT recommendations_profile_used_ck
        CHECK (profile_used IN ('conservative', 'moderate', 'aggressive')),
    CONSTRAINT recommendations_status_ck
        CHECK (status IN ('ready', 'no_match', 'fallback')),
    CONSTRAINT recommendations_channel_ck CHECK (
        channel_name IS NULL
        OR (channel_name IN ('web_widget', 'ios_app', 'simulated')
            AND channel_adapter IS NOT NULL
            AND btrim(channel_adapter) <> '')
    ),
    CONSTRAINT recommendations_simulated_ck CHECK (
        channel_name IS NULL
        OR (channel_name = 'simulated' AND channel_simulated IS TRUE)
        OR (channel_name <> 'simulated' AND channel_simulated IS FALSE)
    ),
    CONSTRAINT recommendations_explanation_ck CHECK (btrim(explanation) <> ''),
    CONSTRAINT recommendations_disclaimer_ck CHECK (btrim(disclaimer) <> ''),
    CONSTRAINT recommendations_llm_metadata_ck CHECK (
        (llm_mode IS NULL
            AND llm_mockable IS NULL
            AND llm_explainability IS NULL)
        OR
        (llm_mode IN ('mock', 'provider')
            AND llm_mockable IS TRUE
            AND llm_explainability IS NOT NULL
            AND llm_explainability IN ('structured', 'unavailable'))
    ),
    CONSTRAINT recommendations_llm_provider_ck CHECK (
        llm_provider IS NULL OR llm_provider IN ('claude', 'mock')
    ),
    CONSTRAINT recommendations_llm_fallback_ck CHECK (
        llm_fallback IS NULL OR llm_fallback IN ('faq', 'human_support')
    )
);

CREATE TABLE aurafi.recommendation_items (
    recommendation_id text NOT NULL,
    item_position     integer NOT NULL,
    opportunity_id    text NOT NULL,
    suitability       text NOT NULL,
    rationale         text[] NOT NULL,
    risks             text[] NOT NULL,
    comparison        text,
    disclaimer        text NOT NULL,
    CONSTRAINT recommendation_items_pk PRIMARY KEY (recommendation_id, item_position),
    CONSTRAINT recommendation_items_recommendation_fk
        FOREIGN KEY (recommendation_id) REFERENCES aurafi.recommendations (recommendation_id)
        ON DELETE RESTRICT,
    CONSTRAINT recommendation_items_opportunity_fk
        FOREIGN KEY (opportunity_id) REFERENCES aurafi.opportunities (opportunity_id)
        ON DELETE RESTRICT,
    CONSTRAINT recommendation_items_position_ck CHECK (item_position > 0),
    CONSTRAINT recommendation_items_suitability_ck
        CHECK (suitability IN ('aligned', 'caution', 'not_aligned', 'unavailable')),
    CONSTRAINT recommendation_items_disclaimer_ck CHECK (btrim(disclaimer) <> '')
);

CREATE TABLE aurafi.messages (
    message_id             text PRIMARY KEY,
    conversation_id        text NOT NULL,
    account_id             text NOT NULL,
    session_id             text NOT NULL,
    envelope_version       text NOT NULL,
    message_type           text NOT NULL,
    occurred_at            timestamptz NOT NULL,
    request_id             text,
    correlation_id         text NOT NULL,
    subject_type           text NOT NULL DEFAULT 'account',
    email_verified         boolean NOT NULL,
    channel_identity_id    text,
    channel_name           text NOT NULL,
    channel_adapter        text NOT NULL,
    external_message_id   text,
    channel_simulated      boolean NOT NULL DEFAULT false,
    consent_id             text NOT NULL,
    payload                jsonb NOT NULL,
    disclaimer             text NOT NULL,
    audit_source           text NOT NULL,
    audit_schema_version   text NOT NULL,
    trace_id               text,
    audit_actor            text NOT NULL,
    audit_redaction        text NOT NULL,
    audit_llm              jsonb NOT NULL DEFAULT '{}',
    audit_data_sources     jsonb NOT NULL DEFAULT '[]',
    CONSTRAINT messages_conversation_fk
        FOREIGN KEY (conversation_id, account_id)
        REFERENCES aurafi.conversations (conversation_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT messages_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT messages_session_fk
        FOREIGN KEY (session_id, account_id)
        REFERENCES aurafi.sessions (session_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT messages_channel_identity_fk
        FOREIGN KEY (channel_identity_id, account_id)
        REFERENCES aurafi.channel_identities (channel_identity_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT messages_consent_fk
        FOREIGN KEY (consent_id, account_id)
        REFERENCES aurafi.consents (consent_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT messages_envelope_version_ck
        CHECK (envelope_version ~ '^[0-9]+\.[0-9]+$'),
    CONSTRAINT messages_type_ck
        CHECK (message_type IN ('user_message', 'assistant_message', 'system_event', 'alert')),
    CONSTRAINT messages_subject_type_ck CHECK (subject_type = 'account'),
    CONSTRAINT messages_channel_ck
        CHECK (channel_name IN ('web_widget', 'ios_app', 'simulated')),
    CONSTRAINT messages_simulated_ck CHECK (
        (channel_name = 'simulated' AND channel_simulated IS TRUE)
        OR (channel_name <> 'simulated' AND channel_simulated IS FALSE)
    ),
    CONSTRAINT messages_adapter_not_blank CHECK (btrim(channel_adapter) <> ''),
    CONSTRAINT messages_correlation_not_blank CHECK (btrim(correlation_id) <> ''),
    CONSTRAINT messages_payload_object_ck CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT messages_disclaimer_ck CHECK (btrim(disclaimer) <> ''),
    CONSTRAINT messages_audit_actor_ck
        CHECK (audit_actor IN ('user', 'hub', 'system', 'human_support')),
    CONSTRAINT messages_audit_redaction_ck
        CHECK (audit_redaction IN ('applied', 'not_required')),
    CONSTRAINT messages_audit_llm_object_ck CHECK (jsonb_typeof(audit_llm) = 'object'),
    CONSTRAINT messages_audit_sources_array_ck CHECK (jsonb_typeof(audit_data_sources) = 'array'),
    CONSTRAINT messages_audit_source_not_blank CHECK (btrim(audit_source) <> ''),
    CONSTRAINT messages_audit_schema_version_not_blank CHECK (btrim(audit_schema_version) <> '')
);

CREATE TABLE aurafi.allocation_plans (
    plan_id           text PRIMARY KEY,
    account_id        text NOT NULL,
    opportunity_id    text,
    simulation_id     text,
    recommendation_id text,
    status            text NOT NULL DEFAULT 'saved',
    created_at        timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT allocation_plans_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT allocation_plans_id_account_uq UNIQUE (plan_id, account_id),
    CONSTRAINT allocation_plans_opportunity_fk
        FOREIGN KEY (opportunity_id) REFERENCES aurafi.opportunities (opportunity_id)
        ON DELETE RESTRICT,
    CONSTRAINT allocation_plans_simulation_fk
        FOREIGN KEY (simulation_id, account_id)
        REFERENCES aurafi.simulations (simulation_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT allocation_plans_recommendation_fk
        FOREIGN KEY (recommendation_id, account_id)
        REFERENCES aurafi.recommendations (recommendation_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT allocation_plans_target_ck CHECK (
        opportunity_id IS NOT NULL
        OR simulation_id IS NOT NULL
        OR recommendation_id IS NOT NULL
    ),
    CONSTRAINT allocation_plans_status_ck
        CHECK (status IN ('saved', 'archived')),
    CONSTRAINT allocation_plans_dates_ck CHECK (updated_at >= created_at)
);

CREATE TABLE aurafi.decision_history (
    decision_id       text PRIMARY KEY,
    account_id        text NOT NULL,
    plan_id           text,
    opportunity_id    text,
    simulation_id     text,
    recommendation_id text,
    decision          text NOT NULL,
    reason            text NOT NULL,
    counterfactual    text NOT NULL,
    decided_at        timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT decision_history_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT decision_history_plan_fk
        FOREIGN KEY (plan_id, account_id)
        REFERENCES aurafi.allocation_plans (plan_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT decision_history_opportunity_fk
        FOREIGN KEY (opportunity_id) REFERENCES aurafi.opportunities (opportunity_id)
        ON DELETE RESTRICT,
    CONSTRAINT decision_history_simulation_fk
        FOREIGN KEY (simulation_id, account_id)
        REFERENCES aurafi.simulations (simulation_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT decision_history_recommendation_fk
        FOREIGN KEY (recommendation_id, account_id)
        REFERENCES aurafi.recommendations (recommendation_id, account_id)
        ON DELETE RESTRICT,
    CONSTRAINT decision_history_decision_ck
        CHECK (decision IN ('accepted', 'rejected')),
    CONSTRAINT decision_history_target_ck CHECK (
        plan_id IS NOT NULL
        OR opportunity_id IS NOT NULL
        OR simulation_id IS NOT NULL
        OR recommendation_id IS NOT NULL
    ),
    CONSTRAINT decision_history_reason_ck CHECK (btrim(reason) <> ''),
    CONSTRAINT decision_history_counterfactual_ck CHECK (btrim(counterfactual) <> '')
);

CREATE TABLE aurafi.alerts (
    alert_id                    text PRIMARY KEY,
    account_id                  text NOT NULL,
    opportunity_id              text,
    data_source_observation_id  text,
    type                        text NOT NULL,
    title                       text NOT NULL,
    message                     text NOT NULL,
    status                      text NOT NULL DEFAULT 'unread',
    created_at                  timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    observed_at                 timestamptz,
    suggested_action            text NOT NULL DEFAULT 'none',
    disclaimer                  text NOT NULL,
    CONSTRAINT alerts_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT alerts_opportunity_fk
        FOREIGN KEY (opportunity_id) REFERENCES aurafi.opportunities (opportunity_id)
        ON DELETE RESTRICT,
    CONSTRAINT alerts_observation_fk
        FOREIGN KEY (data_source_observation_id)
        REFERENCES aurafi.defi_market_observations (market_observation_id)
        ON DELETE RESTRICT,
    CONSTRAINT alerts_type_ck
        CHECK (type IN ('apy_change', 'risk_change', 'new_opportunity', 'data_stale')),
    CONSTRAINT alerts_status_ck CHECK (status IN ('unread', 'read')),
    CONSTRAINT alerts_suggested_action_ck CHECK (
        suggested_action IN ('view_opportunity', 'simulate', 'ask_hub', 'none')
    ),
    CONSTRAINT alerts_title_ck CHECK (btrim(title) <> ''),
    CONSTRAINT alerts_message_ck CHECK (btrim(message) <> ''),
    CONSTRAINT alerts_disclaimer_ck CHECK (btrim(disclaimer) <> '')
);

-- The profile is immutable once written: changes create a new version. The
-- deferred trigger permits one transaction to insert a profile and its five answers.
CREATE FUNCTION aurafi.validate_risk_profile_answer_count()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    profile_key text;
    profile_status text;
    answer_count integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        profile_key := OLD.risk_profile_id;
    ELSE
        profile_key := NEW.risk_profile_id;
    END IF;

    SELECT status
      INTO profile_status
      FROM aurafi.risk_profiles
     WHERE risk_profile_id = profile_key;

    IF profile_status IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT count(*)
      INTO answer_count
      FROM aurafi.risk_profile_answers
     WHERE risk_profile_id = profile_key;

    IF profile_status = 'declared' AND answer_count <> 5 THEN
        RAISE EXCEPTION
            'Declared risk profile % must have exactly five answers; found %',
            profile_key, answer_count;
    ELSIF profile_status = 'missing' AND answer_count <> 0 THEN
        RAISE EXCEPTION
            'Missing risk profile % must not have answers; found %',
            profile_key, answer_count;
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER risk_profiles_answer_count_ck
AFTER INSERT OR UPDATE OR DELETE ON aurafi.risk_profiles
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION aurafi.validate_risk_profile_answer_count();

CREATE CONSTRAINT TRIGGER risk_profile_answers_count_ck
AFTER INSERT OR UPDATE OR DELETE ON aurafi.risk_profile_answers
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION aurafi.validate_risk_profile_answer_count();

CREATE FUNCTION aurafi.reject_risk_profile_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'Risk profiles are append-only; create a new version instead of %',
        lower(TG_OP);
END;
$$;

CREATE TRIGGER risk_profiles_append_only_ck
BEFORE UPDATE OR DELETE ON aurafi.risk_profiles
FOR EACH ROW EXECUTE FUNCTION aurafi.reject_risk_profile_mutation();

CREATE FUNCTION aurafi.require_declared_recommendation_profile()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    profile_status text;
    declared_level text;
BEGIN
    SELECT status, declared_profile
      INTO profile_status, declared_level
      FROM aurafi.risk_profiles
     WHERE risk_profile_id = NEW.risk_profile_id
       AND account_id = NEW.account_id;

    IF profile_status IS DISTINCT FROM 'declared'
       OR declared_level IS DISTINCT FROM NEW.profile_used THEN
        RAISE EXCEPTION
            'Recommendation % requires a matching declared risk profile',
            NEW.recommendation_id;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER recommendations_declared_profile_ck
BEFORE INSERT OR UPDATE ON aurafi.recommendations
FOR EACH ROW EXECUTE FUNCTION aurafi.require_declared_recommendation_profile();

INSERT INTO aurafi.schema_migrations (version, description)
VALUES ('001_initial_operational', 'Initial AuraFi operational model');

COMMIT;
