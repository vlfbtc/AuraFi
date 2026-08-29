-- AuraFi operational database - migration 002
-- PostgreSQL-compatible. Additive only, no DROP/TRUNCATE.
--
-- Fixes real gaps in migration 001: otp_challenges had no otp_digest column
-- (no OTP could ever be verified), sessions had no token digest columns (a
-- bearer token could never resolve to a session), and conversation_runtime_state
-- didn't exist (chat state couldn't survive a restart). Also adds
-- idempotent_responses for the Idempotency-Key contract in openapi.yaml.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM aurafi.schema_migrations
         WHERE version = '002_runtime_state_and_idempotency'
    ) THEN
        RAISE EXCEPTION 'Migration 002_runtime_state_and_idempotency is already applied';
    END IF;
END;
$$;

ALTER TABLE aurafi.otp_challenges
    ADD COLUMN IF NOT EXISTS otp_digest text NOT NULL;

ALTER TABLE aurafi.otp_challenges
    ADD CONSTRAINT otp_challenges_otp_digest_not_blank CHECK (btrim(otp_digest) <> '');

ALTER TABLE aurafi.otp_challenges
    ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0;

ALTER TABLE aurafi.otp_challenges
    ADD CONSTRAINT otp_challenges_attempts_ck CHECK (attempts >= 0);

ALTER TABLE aurafi.sessions
    ADD COLUMN IF NOT EXISTS access_token_digest text,
    ADD COLUMN IF NOT EXISTS refresh_token_digest text;

CREATE INDEX idx_sessions_access_token_digest
    ON aurafi.sessions (access_token_digest);

CREATE INDEX idx_sessions_refresh_token_digest
    ON aurafi.sessions (refresh_token_digest);

-- Whole-aggregate snapshot used to rehydrate ConversationRecord; no email, token, or OTP.
CREATE TABLE aurafi.conversation_runtime_state (
    conversation_id text PRIMARY KEY,
    account_id      text NOT NULL,
    state           jsonb NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT conversation_runtime_state_account_fk
        FOREIGN KEY (account_id) REFERENCES aurafi.accounts (account_id)
        ON DELETE RESTRICT,
    CONSTRAINT conversation_runtime_state_state_object_ck
        CHECK (jsonb_typeof(state) = 'object')
);

CREATE INDEX idx_conversation_runtime_state_account
    ON aurafi.conversation_runtime_state (account_id, updated_at);

-- Idempotency-Key ledger; principal is a SHA-256 digest of the bearer token, never the token itself.
CREATE TABLE aurafi.idempotent_responses (
    principal         text NOT NULL,
    route             text NOT NULL,
    idempotency_key   text NOT NULL,
    request_hash      text NOT NULL,
    response_status   integer NOT NULL,
    response_payload  jsonb NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT idempotent_responses_pk PRIMARY KEY (principal, route, idempotency_key),
    CONSTRAINT idempotent_responses_status_ck
        CHECK (response_status >= 200 AND response_status < 300)
);

CREATE INDEX idx_idempotent_responses_created
    ON aurafi.idempotent_responses (created_at);

INSERT INTO aurafi.schema_migrations (version, description)
VALUES (
    '002_runtime_state_and_idempotency',
    'otp_challenges.otp_digest/.attempts, sessions token digests, '
    'conversation_runtime_state, idempotent_responses'
);

COMMIT;
