-- AuraFi operational database - migration 003
-- PostgreSQL-compatible. Additive only, no DROP/TRUNCATE of data.
--
-- Risk profiles stay append-only: updates are always rejected, and deletes are
-- rejected unless the transaction that deletes a whole account (the holder's
-- right to erasure, LGPD art. 18) sets aurafi.account_erasure = 'on' locally.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM aurafi.schema_migrations
         WHERE version = '003_account_erasure'
    ) THEN
        RAISE EXCEPTION 'Migration 003_account_erasure is already applied';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION aurafi.reject_risk_profile_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('aurafi.account_erasure', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION
        'Risk profiles are append-only; create a new version instead of %',
        lower(TG_OP);
END;
$$;

INSERT INTO aurafi.schema_migrations (version, description)
VALUES (
    '003_account_erasure',
    'risk_profiles accept DELETE only inside an account erasure transaction'
);

COMMIT;
