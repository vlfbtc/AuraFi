# Envelope de mensagem canônica do AuraFi Hub

Versão do contrato: `1.0`  
Status: contrato inicial da Onda 0  
Escopo: Web Widget, app iOS e canal simulado

## Objetivo

Este documento define o envelope comum entre o Hub, os clientes e os adaptadores de canal. O envelope separa metadados de correlação, identidade, sessão, canal, consentimento, conteúdo e auditoria. Ele permite que a mesma conversa continue entre os três canais do MVP sem fundir identidades indevidamente.

O envelope não é schema de banco e não implementa transporte, persistência ou handlers. A definição equivalente para consumidores HTTP está em `contracts/openapi.yaml`, no schema `MessageEnvelope`.

## Regras de versionamento

- `envelope_version` usa `MAJOR.MINOR`, por exemplo `1.0`.
- Incrementar `MAJOR` quando houver remoção, renomeação, mudança de semântica ou quebra de compatibilidade em campo obrigatório.
- Incrementar `MINOR` quando houver campo opcional, novo tipo de payload ou extensão compatível.
- A versão do envelope é independente da versão da API (`/v1`) e da versão de prompt/modelo.
- Consumidores devem ignorar campos desconhecidos e rejeitar apenas ausência ou formato inválido de campos obrigatórios.
- `message_id` deve ser único no escopo lógico do Hub. Reenvios do mesmo comando devem preservar a chave de idempotência do transporte e não criar uma nova ação.

## Estrutura normativa

```yaml
envelope_version: "1.0"
message_id: "msg_01..."
message_type: user_message | assistant_message | system_event | alert
occurred_at: "2026-08-02T12:00:00Z"
request_id: "req_01..."
correlation_id: "cor_01..."
identity:
  account_id: "acc_01..."
  subject_type: account
  email_verified: true
  channel_identity_id: "cid_01..."
session:
  session_id: "ses_01..."
  started_at: "2026-08-02T11:45:00Z"
  expires_at: "2026-08-02T12:15:00Z"
channel:
  name: web_widget | ios_app | simulated
  adapter: "web-widget"
  external_message_id: "optional-id"
  simulated: false
consent:
  purpose: decision_support | conversation | memory | analytics
  status: granted | denied | revoked
  policy_version: "consent-1.0"
  captured_at: "2026-08-02T11:45:00Z"
  memory: true
  analytics: true
payload: {}
disclaimer: "Texto obrigatório de apoio à decisão e ausência de garantia de retorno."
audit:
  source: "hub"
  schema_version: "1.0"
  trace_id: "trace_01..."
  actor: user | hub | system | human_support
  redaction: applied | not_required
  llm: {}
  data_sources: []
```

### Campos obrigatórios

| Campo | Regra |
|---|---|
| `envelope_version` | Versão semântica do envelope, no formato `MAJOR.MINOR`. |
| `message_id` | Identificador único da mensagem; não deve conter e-mail, telefone ou wallet. |
| `message_type` | Tipo técnico da mensagem: `user_message`, `assistant_message`, `system_event` ou `alert`. |
| `occurred_at` | Timestamp ISO 8601 com timezone, preferencialmente UTC. |
| `correlation_id` | Identifica a jornada ponta a ponta e deve ser propagado entre API, Hub e adaptadores. |
| `identity` | Referência à conta interna resolvida; nunca deve ser inferida por similaridade de nome, telefone ou e-mail sem validação. |
| `session` | Sessão autenticada e seu prazo; o baseline do MVP considera sessão ativa de 30 minutos. |
| `channel` | Canal e adaptador que transportaram a mensagem. Valores do MVP: `web_widget`, `ios_app`, `simulated`. |
| `consent` | Finalidade, versão da política e estado do consentimento aplicável ao processamento. |
| `payload` | Conteúdo específico da mensagem. Deve conter somente dados necessários para a finalidade. |
| `disclaimer` | Aviso em pt-BR de apoio à decisão, riscos e ausência de garantia de retorno. |
| `audit` | Origem, versão do schema e estado de redaction para rastreabilidade segura. |

## Identidade e sessão

- `identity.account_id` é o identificador interno/pseudonimizado da conta AuraFi; o envelope não transporta wallet no MVP.
- A autenticação aprovada é conta interna com e-mail/OTP. O envelope não escolhe ou expõe um provedor externo de autenticação.
- `channel_identity_id` é opcional e representa a identidade já resolvida pelo adaptador. Ele não autoriza, sozinho, a criação ou fusão de conta.
- `session.session_id` deve ser o mesmo quando a conversa continuar em outro canal autorizado. A troca de canal deve manter o `correlation_id` da jornada quando a operação fizer parte da mesma interação.
- Dados de sessão expiram conforme política operacional; o envelope não deve ser usado para manter credenciais, tokens ou segredos.

## Canal

O campo `channel` descreve o transporte lógico, não um fornecedor externo. O canal simulado deve exercitar a mesma resolução de identidade, sessão, contexto e guardrails usados pelo Web Widget e pelo app iOS.

Adaptadores podem preencher `external_message_id`, mas esse identificador não substitui `message_id`, `request_id` ou `correlation_id`. Quando o canal for de teste, `simulated` deve ser `true`.

## Consentimento

O consentimento é explícito por finalidade. O Hub deve verificar o estado antes de usar memória, enviar conteúdo a um adaptador ou produzir dados analíticos. `denied` e `revoked` devem impedir o processamento correspondente e resultar em erro seguro ou resposta degradada, sem revelar dados de outra conta.

O envelope não presume base legal, retenção completa ou integração de terceiros além do que for aprovado em contrato posterior. Alterações de política devem gerar nova `policy_version`.

## Payload e disclaimer

`payload` é um objeto extensível. Tipos de payload podem ser definidos por cada contrato de domínio, mas não devem adicionar operações de custódia, wallet, execução de transação ou Open Finance ao MVP.

Mensagens sobre oportunidades, simulações ou recomendações devem manter disclaimer. Dados DeFi incluídos no payload devem carregar, em `audit.data_sources`, pelo menos:

- `source: defillama`;
- `mode: live`, `cache`, `test` ou `fallback`;
- `observed_at` e `retrieved_at` em ISO 8601;
- `read_only: true`;
- `is_stale` e uma explicação quando aplicável.

DeFiLlama é fonte somente leitura. O envelope não suporta comandos de escrita na fonte, assinatura, envio ou execução de transação.

## Auditoria e observabilidade

`audit` registra metadados mínimos para investigação e para alimentar o DW sem transportar PII desnecessária:

- `source`: componente lógico produtor, como `hub`, `channel_adapter` ou `system`;
- `schema_version`: versão do schema do conteúdo auditado;
- `trace_id`: vínculo opcional com tracing distribuído;
- `actor`: autor lógico da mensagem;
- `redaction`: informa se a saída passou por remoção de dados sensíveis;
- `llm`: quando houver IA, registra modo `mock` ou `provider`, provedor lógico, versão de prompt, explicabilidade e fallback;
- `data_sources`: fontes de mercado usadas na resposta.

Logs e eventos devem correlacionar `request_id` e `correlation_id`, mas não devem registrar OTP, tokens, conteúdo sensível sem necessidade ou qualquer chave privada. A pseudonimização para o DW é responsabilidade do fluxo analítico posterior, não uma permissão para expor PII no envelope.

## Erros e comportamento degradado

Erros HTTP usam o envelope `ErrorResponse` da OpenAPI, com `error.code`, mensagem segura, indicação `retryable`, `request_id`, `correlation_id`, timestamp e disclaimer em `meta`.

Quando uma dependência estiver indisponível:

- dados DeFi podem usar `cache`, `test` ou `fallback`, sempre marcando a fonte e a desatualização;
- a camada LLM pode usar mock, FAQ ou atendimento humano;
- nenhuma indisponibilidade pode ser convertida em execução de wallet ou em promessa de retorno;
- o mesmo `correlation_id` deve ser preservado enquanto a jornada estiver ativa.

## Garantias e exclusões do MVP

Este contrato garante a forma dos metadados e o fluxo de apoio à decisão. Ele não aprova fórmula de APY, suitability regulatória, thresholds de alerta, retenção completa, schema operacional ou infraestrutura; essas decisões pertencem a contratos e tarefas posteriores.

Explicitamente ausentes do contrato:

- endpoints ou mensagens de conexão de wallet;
- endpoints ou mensagens de execução, assinatura, envio ou confirmação de transação;
- custódia ou movimentação de fundos;
- Open Finance, agregação bancária, pagamentos ou cobrança real;
- canais externos reais não aprovados no Gate.
