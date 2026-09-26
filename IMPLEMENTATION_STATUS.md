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
  chave com corpo diferente retorna 409. A chave vale para a conta, e não para
  o token de acesso, então a repetição continua reconhecida depois de renovar
  a sessão.
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

### Privacidade, segurança e auditoria (Fase 6)

- Direitos do titular na API: `GET /v1/account/export` devolve todos os dados
  da conta em JSON (sem resumos de tokens ou de códigos) e
  `POST /v1/account/deletion` apaga a conta e tudo o que está ligado a ela,
  depois de confirmar um código novo enviado ao e-mail da própria conta. A
  migration `003_account_erasure.sql` permite apagar o perfil de risco apenas
  dentro dessa transação; fora dela, o perfil continua somente de inclusão.
- Com cadastro aberto, a conta só é criada depois que o código é confirmado;
  e-mails digitados e nunca confirmados deixam de ser gravados.
- Eventos de segurança e de privacidade (pedidos de código, logins, falhas,
  bloqueios, limites de uso, origens recusadas, erros internos, consentimento,
  mudança de memória, exportação e exclusão) saem no log do processo como uma
  linha JSON por evento (`services/api/security_log.py`), sem código, token,
  e-mail em claro ou texto de conversa.
- Retenção (`database/account_data.py`): no máximo uma vez por hora, remove
  códigos vencidos há mais de 24 h, respostas de idempotência com mais de 24 h
  e contas nunca confirmadas há mais de 7 dias. Em produção, só roda com
  `AURAFI_RETENTION_PURGE=true`.
- Limite de mensagens à Aura contado por conta (renovar a sessão ou entrar de
  novo não zera o limite).
- Respostas da API com `X-Content-Type-Options`, `X-Frame-Options`,
  `Content-Security-Policy`, `Referrer-Policy` e, em produção, HSTS. A sessão é
  validada antes de revelar se uma conversa existe ou de validar o corpo.
- Memória da conversa opcional, desligada por padrão e revogável a qualquer
  momento; cada mudança fica registrada.
- Testes negativos de autorização entre contas (SQLite e memória) e teste de
  ponta a ponta de exportação, exclusão e retenção contra PostgreSQL real.

### Clientes

- Consentimento unificado no iOS e no Web Widget (versão de política
  `aurafi-privacy-2026-09`), com a mesma tela antes da conversa, memória
  opcional e o quadro "Como usamos seus dados".
- Área de privacidade nos dois clientes: "Baixar meus dados" e "Apagar minha
  conta" com confirmação por código.
- Web Widget com título e descrição para buscadores, Open Graph, dados
  estruturados, `robots.txt`, `sitemap.xml`, texto da tela inicial em HTML
  estático e política de segurança de conteúdo (CSP) no build de produção;
  `render.yaml` envia cabeçalhos de segurança do site estático.
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
- CI para backend, analytics, web e build iOS, com ações fixadas por hash,
  auditoria de dependências npm (falha em vulnerabilidade alta) e Dependabot
  semanal para npm e GitHub Actions.
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
- Enviar os eventos de segurança, que já saem em JSON, para um serviço de logs
  com alertas e retenção definida; adicionar SLOs e alertas operacionais.
- Propagar a exclusão de conta ao data warehouse quando ele passar a receber
  dados reais.
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
psql -d aurafi_test -f database/migrations/003_account_erasure.sql
AURAFI_TEST_DATABASE_URL="dbname=aurafi_test" \
  python3.12 -m unittest tests.integration.test_postgres_repository -v
```
