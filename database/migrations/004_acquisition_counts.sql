-- AuraFi operational database - migration 004
-- PostgreSQL-compatible. Additive only, no DROP/TRUNCATE.
--
-- Aggregate count of where sign-ups come from (campaign source, medium and
-- campaign), per week. Values come from a closed list (services/acquisition):
-- anything else is stored as 'outro' and a missing value as 'direto', so no
-- free text is ever written. The table has no account, e-mail, IP, cookie or
-- timestamp finer than the week, and nothing links a row to an access-code
-- request or to an account. Source 'teste' is reserved for rehearsals and is
-- left out of reports.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM aurafi.schema_migrations
         WHERE version = '004_acquisition_counts'
    ) THEN
        RAISE EXCEPTION 'Migration 004_acquisition_counts is already applied';
    END IF;
END;
$$;

CREATE TABLE aurafi.acquisition_weekly (
    week_start       date NOT NULL,
    utm_source       text NOT NULL,
    utm_medium       text NOT NULL,
    utm_campaign     text NOT NULL,
    code_requests    integer NOT NULL DEFAULT 0,
    accounts_created integer NOT NULL DEFAULT 0,
    CONSTRAINT acquisition_weekly_pk
        PRIMARY KEY (week_start, utm_source, utm_medium, utm_campaign),
    CONSTRAINT acquisition_weekly_week_start_monday_ck
        CHECK (extract(isodow FROM week_start) = 1),
    CONSTRAINT acquisition_weekly_source_ck
        CHECK (utm_source IN (
            'direto', 'outro', 'perfil_a', 'perfil_b', 'perfil_c', 'perfil_d', 'google',
            'meta', 'youtube', 'x', 'linkedin', 'tiktok', 'podcast', 'teste'
        )),
    CONSTRAINT acquisition_weekly_medium_ck
        CHECK (utm_medium IN (
            'direto', 'outro', 'influenciador', 'busca_paga', 'video_pago', 'social_pago',
            'social_organico', 'video_organico', 'indicacao'
        )),
    CONSTRAINT acquisition_weekly_campaign_ck
        CHECK (utm_campaign IN (
            'direto', 'outro', 'entenda_onda1', 'entenda_onda2', 'piloto_onda3'
        )),
    CONSTRAINT acquisition_weekly_counts_ck
        CHECK (code_requests >= 0 AND accounts_created >= 0)
);

INSERT INTO aurafi.schema_migrations (version, description)
VALUES (
    '004_acquisition_counts',
    'acquisition_weekly: aggregate weekly sign-up origin counts, closed list, '
    'no personal data'
);

COMMIT;
