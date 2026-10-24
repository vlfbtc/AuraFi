-- AuraFi - consulta de funil sobre o banco operacional (PostgreSQL, só leitura).
--
-- Rodar com um usuário só de leitura, por exemplo:
--   psql "$DATABASE_URL_SOMENTE_LEITURA" -v ON_ERROR_STOP=1 -f analytics/sql/funil_operacional.sql
--
-- Regras:
-- * a conta semente (acc_maria / maria@example.com, gravada pela API ao iniciar)
--   nunca entra na conta;
-- * a fonte de campanha 'teste' é reservada para ensaios e fica fora;
-- * semanas começam na segunda-feira (UTC), como a contagem de origem;
-- * contas apagadas somem com todos os dados ligados a elas, e contas de teste
--   do grupo continuam na base: os números servem para acompanhar o funil,
--   não para virar resultado medido sem antes conferir de onde vêm.
--
-- Ativação (definição da Fase 6): perfil declarado e primeira pergunta à Aura
-- em até 7 dias depois da criação da conta.

BEGIN TRANSACTION READ ONLY;

-- 1. Funil por semana de criação da conta e canal de entrada.
WITH contas AS (
    SELECT a.account_id,
           a.created_at,
           date_trunc('week', a.created_at AT TIME ZONE 'UTC')::date AS semana
      FROM aurafi.accounts a
     WHERE a.email_verified
       AND a.account_id <> 'acc_maria'
       AND a.email <> 'maria@example.com'
),
primeiro_canal AS (
    SELECT DISTINCT ON (account_id) account_id, channel_name
      FROM aurafi.channel_identities
     ORDER BY account_id, created_at
),
perfil AS (
    SELECT account_id, min(declared_at) AS declarado_em
      FROM aurafi.risk_profiles
     WHERE status = 'declared'
     GROUP BY account_id
),
primeira_pergunta AS (
    SELECT account_id, min(occurred_at) AS perguntou_em
      FROM aurafi.messages
     WHERE message_type = 'user_message'
     GROUP BY account_id
),
simulou AS (
    SELECT DISTINCT account_id FROM aurafi.simulations
)
SELECT c.semana,
       coalesce(pc.channel_name, 'desconhecido') AS canal_de_entrada,
       count(*) AS contas_confirmadas,
       count(p.account_id) AS perfil_declarado,
       count(*) FILTER (
           WHERE p.declarado_em <= c.created_at + interval '7 days'
             AND q.perguntou_em <= c.created_at + interval '7 days'
       ) AS ativadas_7d,
       count(s.account_id) AS fizeram_simulacao
  FROM contas c
  LEFT JOIN primeiro_canal pc USING (account_id)
  LEFT JOIN perfil p USING (account_id)
  LEFT JOIN primeira_pergunta q USING (account_id)
  LEFT JOIN simulou s USING (account_id)
 GROUP BY 1, 2
 ORDER BY 1, 2;

-- 2. Taxa geral de ativação em 7 dias (base do custo estimado por conta
--    ativada). Só contas com pelo menos 7 dias, para não contar como não
--    ativada quem ainda está dentro do prazo.
WITH contas AS (
    SELECT a.account_id, a.created_at
      FROM aurafi.accounts a
     WHERE a.email_verified
       AND a.account_id <> 'acc_maria'
       AND a.email <> 'maria@example.com'
       AND a.created_at <= now() - interval '7 days'
),
ativadas AS (
    SELECT c.account_id
      FROM contas c
     WHERE EXISTS (
               SELECT 1 FROM aurafi.risk_profiles p
                WHERE p.account_id = c.account_id
                  AND p.status = 'declared'
                  AND p.declared_at <= c.created_at + interval '7 days'
           )
       AND EXISTS (
               SELECT 1 FROM aurafi.messages m
                WHERE m.account_id = c.account_id
                  AND m.message_type = 'user_message'
                  AND m.occurred_at <= c.created_at + interval '7 days'
           )
)
SELECT (SELECT count(*) FROM contas) AS contas_com_7_dias,
       (SELECT count(*) FROM ativadas) AS ativadas_7d,
       round(
           (SELECT count(*) FROM ativadas)::numeric
           / nullif((SELECT count(*) FROM contas), 0),
           4
       ) AS taxa_de_ativacao_7d;

-- 3. Alertas gerados e lidos por semana.
SELECT date_trunc('week', al.created_at AT TIME ZONE 'UTC')::date AS semana,
       count(*) AS alertas_gerados,
       count(*) FILTER (WHERE al.status = 'read') AS alertas_lidos
  FROM aurafi.alerts al
 WHERE al.account_id <> 'acc_maria'
 GROUP BY 1
 ORDER BY 1;

-- 4. Origem dos cadastros por semana (contagem agregada, migration 004), sem
--    a fonte 'teste'. Pedidos de código só contam quando podem abrir uma conta
--    nova; contas ÷ pedidos é a parte dos cadastros iniciados que terminou.
SELECT week_start AS semana,
       utm_source AS fonte,
       utm_medium AS meio,
       utm_campaign AS campanha,
       code_requests AS pedidos_de_codigo,
       accounts_created AS contas_criadas,
       round(accounts_created::numeric / nullif(code_requests, 0), 4) AS contas_por_pedido
  FROM aurafi.acquisition_weekly
 WHERE utm_source <> 'teste'
 ORDER BY week_start, utm_source, utm_medium, utm_campaign;

COMMIT;
