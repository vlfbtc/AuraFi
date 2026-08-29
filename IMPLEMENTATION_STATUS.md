# AuraFi — status de implementação

Atualizado em 2026-08-29 após auditoria integral dos artefatos de escopo e
confronto com o código executável (backend, analytics, web widget e app iOS).

## Entregue e validado

### Backend e integrações

- API HTTP versionada com contrato OpenAPI e erros estruturados.
- Autenticação OTP por e-mail, refresh com rotação e logout com revogação.
- Envio real por SMTP compatível com Resend; nenhum OTP fixo é aceito em
  produção. Fluxo completo (requisição → e-mail real → verificação → sessão)
  confirmado em produção em 2026-08-29 via Web Widget com destinatário real;
  domínio `aurafi.com.br` verificado no Resend.
- Persistência SQLite de identidade canônica, identidades por canal, sessões,
  perfil de risco, consentimento, conversas, mensagens e alertas.
- Dados de mercado reais via API pública da DeFiLlama, com origem, frescor e
  fallback degradado explicitados na resposta.
- Conversão informativa USD/BRL via PTAX do Banco Central, com marcação de
  cotação em cache quando aplicável.
- Hub conversacional real via Anthropic, com histórico condicionado ao
  consentimento, retomada entre sessões/canais e redação de PII antes do envio.
- Simulação educativa e recomendações fechadas por padrão quando não existe
  política de produto aprovada.
- CORS explícito (inclui preflight PATCH e o cabeçalho Idempotency-Key), rate
  limit de OTP, validação de configuração de produção e bloqueio de operações
  de custódia ou movimentação de recursos.
- Deduplicação real por Idempotency-Key (PUT /v1/profile/risk, POST
  /v1/simulations, POST /v1/recommendations, POST
  /v1/conversations/{id}/messages): uma repetição com a mesma chave e o mesmo
  corpo reexibe a resposta original sem repetir o efeito colateral; a mesma
  chave com corpo diferente retorna 409.
- Backend de PostgreSQL gerenciado como alternativa ao SQLite local, ativado
  por `DATABASE_URL` (prioridade sobre `AURAFI_DB_PATH`). Adapter em
  `database/postgres/repository.py` espelha o contrato do `SQLiteRepository`
  método a método; migrations em `database/migrations/001_...` e
  `002_runtime_state_and_idempotency.sql` (a 002 corrige lacunas reais da 001:
  faltavam `otp_challenges.otp_digest`, os digests de token de sessão e a
  tabela `conversation_runtime_state`, sem os quais autenticação e retomada
  de conversa não funcionariam em PostgreSQL). Validado ponta a ponta contra
  PostgreSQL 16 local, incluindo persistência de perfil de risco e conversa
  após reinício do processo.
- Geração real de alertas (BE-008 `services/notifications/alerts.py`, motor
  já existente, agora com política concreta e disparo ligado à leitura de
  mercado). Cada `GET /v1/opportunities`, detalhe, simulação e recomendação
  compara o snapshot atual ao último observado; muda ≥2pp de APY, muda o
  nível de risco derivado (`derive_risk_level`) ou aparece uma oportunidade
  nova → alerta é persistido de verdade (nunca na primeira leitura, que só
  estabelece a base, e nunca duplicado para a mesma mudança). `data_stale`
  continua desabilitado por não mapear para uma única oportunidade de forma
  limpa. Thresholds em `DEFAULT_ALERT_POLICY` (`services/api/app.py`) são um
  default de MVP, ajustável e sem gate de compliance (ao contrário da
  política de recomendação).

### Clientes

- Aplicativo iOS conectado ao backend público, com onboarding OTP, perfil,
  oportunidades, simulação, alertas e Aura Hub.
- Bloqueio biométrico opcional (Face ID / Touch ID) com fallback para o código
  do aparelho, reengajado quando o app volta do segundo plano.
- Sessão iOS persistida no Keychain, renovada automaticamente e revogada no
  logout.
- Chat com envio otimista e estados por mensagem (enviando, enviada, não
  enviada com reenvio), tolerante a indisponibilidade da IA.
- Tela de alertas real nos dois clientes (iOS: ícone de sino no painel inicial
  com indicador de não lidos, sheet dedicado; Web Widget: ícone no cabeçalho
  com contagem, tela própria), consumindo `GET /v1/alerts` e
  `PATCH /v1/alerts/{id}` — antes desta rodada, a geração existia no backend
  mas nenhum cliente exibia os alertas.
- Web widget publicado em `https://aurafi-web-widget.onrender.com` (Render
  Static Site, `render.yaml`, build a partir do mesmo repositório), conectado
  por padrão a `https://aurafi-api.onrender.com`, com OTP, perfil, conversa,
  retomada, rotação de sessão e logout real. Origem incluída em
  `AURAFI_ALLOWED_ORIGINS` no serviço da API; testado ponta a ponta (preflight
  CORS e requisição real) contra a API pública.
- Estados explícitos de carregamento, vazio, indisponibilidade e erro nos fluxos
  principais, em português brasileiro; offline/cache sinalizado de forma
  discreta e erros de autenticação distintos de falhas de conexão.

### Dados e qualidade

- Star schema com 7 dimensões, 3 fatos e marts de recomendação, mercado, hub,
  continuidade entre canais e metas de produto.
- Fixtures reprodutíveis para handoff Web Widget → iOS, retomada, perda de
  contexto, recomendação e mudança SCD2 de plano.
- Validação estática de analytics em Python e Node e testes dbt singulares.
- CI para backend, analytics, web e build iOS.
- Catálogo seguro de variáveis em `backend/.env.example`; segredos reais não
  pertencem ao Git.

## Dependências externas em ativação

### Anthropic

É necessário manter no Render uma chave ativa com créditos em
`AURAFI_ANTHROPIC_API_KEY`. O modelo padrão está configurado por variável de
ambiente; falhas do provedor geram resposta degradada explícita.

### Analytics

Faltam um PostgreSQL analítico e um profile dbt para executar `dbt seed`,
`dbt run` e `dbt test`. CAC, MRR, churn e LTV/CAC também dependem de fontes reais
de billing e aquisição ainda não fornecidas.

## Decisões de produto ainda necessárias

Estes itens foram deliberadamente mantidos em modo seguro porque os artefatos
não definem regras aprovadas suficientes:

- política de elegibilidade e ranking de recomendações;
- fórmula oficial, premissas e disclaimer final da simulação;
- texto jurídico final de privacidade, termos, retenção e exclusão;
- critérios e operação do fallback humano;
- canais WhatsApp e Telegram e seus respectivos provedores;
- planos free/premium/plus e provedor de cobrança (modelados no DW, sem
  cobrança no app).

## Próximas evoluções técnicas

- Migrar o estado efêmero (rate limiting) para Redis quando houver múltiplas
  réplicas; hoje é local ao processo, adequado à réplica única declarada em
  `render.yaml` mesmo já com PostgreSQL gerenciado.
- Notificações push (APNs) para os alertas, hoje disponíveis apenas no backend.
- Introduzir fila gerenciada para alertas e ingestão analítica.
- Adicionar observabilidade centralizada, SLOs, alertas operacionais e trilhas de
  auditoria exportáveis.
- Implementar exportação/exclusão de dados do titular após aprovação jurídica.
- Ligar a telemetria operacional aos fatos analíticos e conectar billing.
- Executar testes end-to-end em dispositivo físico e preparar TestFlight/App
  Store após aprovação visual e legal.

## Divergências conscientes em relação aos documentos de escopo

- O núcleo da API usa a biblioteca padrão `http.server` (independente de
  framework), com adapter FastAPI previsto; os documentos citam FastAPI.
- A persistência aceita SQLite local (`AURAFI_DB_PATH`, usado em
  desenvolvimento/testes) ou PostgreSQL gerenciado (`DATABASE_URL`, usado em
  produção via Render Postgres); os documentos previam RDS especificamente,
  mas o modelo de dados e o contrato do repositório são os mesmos.
- Os canais vivos são iOS, Web Widget e o hub conversacional; WhatsApp e Telegram
  existem como modelagem analítica (`dim_canal`), não como integrações ativas.
- WalletConnect e assistência à execução permanecem fora de escopo (exigem nova
  revisão de segurança e compliance).

## Gates locais

```bash
# Backend: usar Python 3.10+ (dataclass slots). Ex.: python3.12
python3.12 -m unittest discover -s tests -t . -p 'test*.py'
python3 analytics/validate_pipeline.py
node analytics/scripts/validate_pipeline.mjs
npm --prefix apps/web-widget run build
xcodebuild build -project apps/ios/AuraFi.xcodeproj -scheme AuraFi \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO

# Opcional: suíte do backend PostgreSQL (pulada por padrão sem esta variável)
createdb aurafi_test
psql -d aurafi_test -f database/migrations/001_initial_operational.sql
psql -d aurafi_test -f database/migrations/002_runtime_state_and_idempotency.sql
AURAFI_TEST_DATABASE_URL="dbname=aurafi_test" \
  python3.12 -m unittest tests.integration.test_postgres_repository -v
```
