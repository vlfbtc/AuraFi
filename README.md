# AuraFi — Clareza para Investir

> Plataforma mobile de apoio à decisão de alocação de stablecoins em DeFi, assistida por IA generativa em português.

**Startup One 2026 · Enterprise Challenge — Claro**

## Sobre o Projeto

A AuraFi é uma plataforma mobile que traduz a complexidade do ecossistema DeFi em recomendações claras e personalizadas, usando Inteligência Artificial generativa em português brasileiro.

**Proposta de valor:** Clareza para Investir.

**Problema:** Investidores pessoa física brasileiros possuem stablecoins (USDT, USDC, DAI) ociosas em exchanges, perdendo poder de compra, enquanto oportunidades de rendimento em DeFi (2–8% a.a.) existem mas são bloqueadas por complexidade técnica e falta de linguagem acessível.

**Solução:** Agente de IA conversacional (Aura) que monitora protocolos DeFi, filtra por perfil de risco declarado e entrega recomendações em PT-BR, em qualquer canal que o usuário já usa.

---

## Estrutura do Repositório

```
aurafi/
├── frontend/          # Protótipo web navegável (HTML/React)
│   └── index.html     # Protótipo funcional com IA real
├── backend/           # API FastAPI (Python 3.12)
│   ├── main.py
│   └── requirements.txt
└── README.md
```

---

## Protótipo Funcional

O protótipo de alta fidelidade está em `frontend/index.html`. Ele inclui:

- **8 telas completas:** Splash, Quiz de Perfil, Resultado, Dashboard, Aura Chat, Simulação, Protocolos e Histórico
- **IA real:** Chat com a Aura via API do Claude (Anthropic)
- **Dados simulados:** 5 protocolos DeFi com APY, TVL e score de segurança
- **Fluxo completo:** do onboarding à simulação de alocação

### Como rodar localmente

```bash
# Clone o repositório
git clone https://github.com/SEU_USUARIO/aurafi.git
cd aurafi

# Abra o protótipo no browser (não precisa de servidor)
open frontend/index.html
```

> **Nota sobre a API:** O protótipo chama a API do Claude diretamente do browser para fins de demonstração acadêmica. Em produção, toda chamada à IA deve ser feita pelo backend FastAPI.

---

## Backend (FastAPI)

### Requisitos

- Python 3.12+
- AWS CLI configurada (região sa-east-1)
- Variáveis de ambiente no `.env`

### Instalação

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

```env
ANTHROPIC_API_KEY=sk-ant-...
AWS_REGION=sa-east-1
DATABASE_URL=postgresql://user:pass@host:5432/aurafi
REDIS_URL=redis://localhost:6379
DEFI_LLAMA_BASE_URL=https://yields.llama.fi
```

---

## Stack Técnica

| Camada | Tecnologia |
|---|---|
| Frontend iOS | SwiftUI (iOS 17+) |
| Frontend Web | React + TypeScript |
| Backend | FastAPI (Python 3.12) |
| Cloud | AWS (sa-east-1 São Paulo) |
| LLM | Claude via AWS Bedrock |
| Banco de dados | PostgreSQL (RDS) |
| Cache | Redis (ElastiCache) |
| Filas | Amazon SQS |
| Dados DeFi | DeFiLlama API |

---

## Princípios de UX

1. Mobile-first nativo iOS
2. Hierarquia clara e escaneável
3. Linguagem em PT-BR direto (sem jargão)
4. IA visível e revogável
5. Acessibilidade WCAG 2.2 AA
6. Continuidade cross-channel
7. Transparência radical sobre risco
8. Não-custodial sempre visível

---

## Segurança e Conformidade

- **Não-custodial:** a AuraFi nunca toca os fundos do usuário
- **LGPD:** privacidade por design desde o nascimento do produto
- **Guardrails:** a Aura nunca promete retorno garantido nem aconselha como gestor
- **Autenticação:** JWT + biometria (Face ID)
- **Criptografia:** TLS 1.3 em trânsito, AES-256 em repouso

---

## Licença

Projeto acadêmico — FIAP Startup One 2026. Todos os direitos reservados ao grupo.
