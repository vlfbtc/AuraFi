# AuraFi Analytics

Contrato analítico do MVP em star schema puro, com três fatos e sete dimensões
conformadas. Todos os dados versionados em `dbt/seeds` são sintéticos, marcados
com `is_test_data=true` e não contêm PII nem texto bruto de conversas.

## Grãos

- `fato_recomendacao`: uma recomendação por usuário, canal e momento.
- `fato_yield_observacao`: um snapshot por pool, protocolo, ativo, blockchain e momento.
- `fato_interacao_conversacional`: uma sessão por usuário e canal; mensagens da mesma
  sessão devem ter gap inferior a 30 minutos na origem operacional.

As sete dimensões são `dim_tempo`, `dim_usuario`, `dim_perfil_risco`,
`dim_protocolo`, `dim_ativo`, `dim_blockchain` e `dim_canal`. `dim_usuario`
implementa SCD Tipo 2 e armazena somente identificador pseudônimo.

## Marts

- `recommendation_metrics`: aceitação, ticket simulado, confiança, tempo de decisão,
  tokens e custo por canal, perfil e protocolo.
- `market_metrics`: APY, APR, incentivos, TVL, volatilidade, IL, liquidez,
  elegibilidade e frescor.
- `hub_metrics`: engajamento, CSAT, fallback, escalação humana, geração de
  recomendação, tokens, custo, conversão premium e perda de contexto.
- `cross_channel_metrics`: handoff, tempo de retomada e perda de contexto por
  direção de canal.
- `product_metric_targets`: metas estratégicas separadas de valores observados.
- `mvp_metrics`: contrato agregado legado preservado para compatibilidade.

## Validação local sem serviços externos

```bash
python3.12 analytics/validate_pipeline.py
node analytics/scripts/validate_pipeline.mjs
```

O gate valida contratos CSV, pseudonimização, SCD2, integridade das fixtures,
medidas exigidas, handoff cross-channel, documentação e presença dos testes dbt.

## Execução dbt pendente

Quando houver PostgreSQL e um profile dbt configurado:

```bash
cd analytics/dbt
dbt seed
dbt run
dbt test
```

O MVP usa `generate_series`, `to_char` e `extract`, portanto os modelos atuais
são direcionados ao PostgreSQL. Uma migração futura para Redshift precisa adaptar
a geração de `dim_tempo`.

## Limites explícitos

- CAC, LTV/CAC, churn, MRR e número real de assinantes exigem fatos de billing e
  aquisição ainda inexistentes; apenas as metas são versionadas.
- `dim_tempo` cobre feriados nacionais de data fixa. Feriados móveis e calendários
  bancários oficiais exigem uma fonte externa governada.
- Métricas reais dependem de ingestão operacional, DeFiLlama e telemetria de LLM;
  as fixtures provam o contrato, não representam produção.
- O DW retém somente agregados e identificadores pseudônimos. Texto conversacional
  bruto deve permanecer fora desta camada e obedecer à política operacional de retenção.
