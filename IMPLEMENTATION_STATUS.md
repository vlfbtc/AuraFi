# AuraFi — status de implementação

Atualizado em 2026-08-03 após auditoria integral dos artefatos em
`.aurafi-internal/context/` e confronto com o código executável.

## Entregue e validado

### Backend e integrações

- API HTTP versionada com contrato OpenAPI e erros estruturados.
- Autenticação OTP por e-mail, refresh com rotação e logout com revogação.
- Envio real por SMTP compatível com Resend; nenhum OTP fixo é aceito em produção.
- Persistência SQLite de identidade canônica, identidades por canal, sessões,
  perfil de risco, consentimento, conversas, mensagens e alertas.
- Dados de mercado reais via API pública da DeFiLlama, com origem, frescor e
  fallback degradado explicitados na resposta.
- Hub conversacional real via Anthropic, com histórico condicionado ao
  consentimento, retomada entre sessões/canais e redação de PII antes do envio.
- Simulação educativa e recomendações fechadas por padrão quando não existe
  política de produto aprovada.
- CORS explícito, rate limit de OTP, validação de configuração de produção e
  bloqueio de operações de custódia ou movimentação de recursos.

### Clientes

- Aplicativo iOS conectado ao backend público, com onboarding OTP, perfil,
  oportunidades, simulação, alertas e Aura Hub.
- Sessão iOS persistida no Keychain, renovada automaticamente e revogada no
  logout.
- Web widget conectado por padrão a `https://aurafi-api.onrender.com`, com OTP,
  perfil, conversa, retomada, rotação de sessão e logout real.
- Estados explícitos de carregamento, vazio, indisponibilidade e erro nos fluxos
  principais, em português brasileiro.

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

### Resend / OTP

O código está pronto. O domínio `aurafi.com.br` precisa terminar a verificação
DNS no Resend. Depois disso, no Render:

1. definir `AURAFI_OTP_FROM_EMAIL=nao-responder@aurafi.com.br`;
2. conferir `AURAFI_OTP_SMTP_HOST=smtp.resend.com`;
3. conferir `AURAFI_OTP_SMTP_PORT=587`,
   `AURAFI_OTP_SMTP_STARTTLS=true` e `AURAFI_OTP_SMTP_SSL=false`;
4. usar `resend` como usuário SMTP e uma API key de envio como senha;
5. salvar, redeployar e testar o fluxo OTP com um e-mail real.

### Anthropic

É necessário manter no Render uma chave ativa com créditos em
`AURAFI_ANTHROPIC_API_KEY`. O modelo padrão está configurado por variável de
ambiente; falhas do provedor geram resposta degradada explícita.

### Web widget

O bundle está pronto para hospedagem, mas ainda precisa de um provedor web e de
um domínio/origem definitivos. Essa origem deve ser acrescentada exatamente em
`AURAFI_ALLOWED_ORIGINS` no Render; curingas não são aceitos em produção.

### Analytics

Faltam um PostgreSQL analítico e um profile dbt para executar `dbt seed`,
`dbt run` e `dbt test`. CAC, MRR, churn e LTV/CAC também dependem de fontes reais
de billing e aquisição ainda não fornecidas.

## Decisões de produto ainda necessárias

Estes itens foram deliberadamente mantidos em modo seguro porque os artefatos
não definem regras aprovadas suficientes:

- política de elegibilidade e ranking de recomendações;
- fórmula oficial, premissas e disclaimer final da simulação;
- thresholds e frequência dos alertas de risco/oportunidade;
- texto jurídico final de privacidade, termos, retenção e exclusão;
- critérios e operação do fallback humano;
- canais WhatsApp e Telegram e seus respectivos provedores.

## Próximas evoluções técnicas

- Migrar a persistência operacional para PostgreSQL e o estado efêmero para
  Redis quando houver infraestrutura provisionada.
- Introduzir fila gerenciada para alertas e ingestão analítica.
- Adicionar observabilidade centralizada, SLOs, alertas operacionais e trilhas de
  auditoria exportáveis.
- Implementar exportação/exclusão de dados do titular após aprovação jurídica.
- Ligar a telemetria operacional aos fatos analíticos e conectar billing.
- Executar testes end-to-end em dispositivo físico e preparar TestFlight/App
  Store após aprovação visual e legal.

## Gates locais

```bash
python3 -m unittest discover -s tests -t . -p 'test*.py'
python3 analytics/validate_pipeline.py
node analytics/scripts/validate_pipeline.mjs
npm --prefix apps/web-widget run build
xcodebuild build -project apps/ios/AuraFi.xcodeproj -scheme AuraFi \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```
