# AuraFi — Clareza para Investir

AuraFi é uma plataforma de apoio à decisão para pessoas que desejam entender oportunidades de stablecoins em DeFi. O produto explica dados de mercado, considera um perfil de risco declarado e oferece simulações educativas. Não há custódia, conexão de wallet, assinatura ou execução de transações.

## Estrutura atual

- `apps/web-widget`: Web Widget atual, Vite + React + TypeScript.
- `services/api`: API atual, autenticação interna por OTP, perfil, oportunidades e simulações.
- `database`: persistência local SQLite e artefatos do DW.
- `analytics`: validação da camada analítica.
- `contracts`: contratos HTTP/OpenAPI e envelopes de mensagem.
- `tests`: testes unitários, integração, contrato e validações.

## Requisitos

- Python 3.11 ou superior;
- Node.js 18 ou superior e npm;
- navegador moderno.

A API atual usa somente a biblioteca padrão do Python. O Web Widget instala as dependências pelo `package-lock.json`. DeFiLlama é consultado em modo somente leitura quando a rede é habilitada.

## Rodar no Windows (PowerShell)

Abra dois terminais PowerShell na raiz do repositório.

Terminal 1 — API:

```powershell
Set-Location "C:\caminho\para\AuraFi"
$env:AURAFI_ENABLE_MARKET_NETWORK = "true"
$env:AURAFI_MARKET_MODE = "live"
python -m services.api.cli --host 127.0.0.1 --port 8000
```

Terminal 2 — Web Widget:

```powershell
Set-Location "C:\caminho\para\AuraFi\apps\web-widget"
npm ci
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_ALLOW_DEMO_DATA = "false"
npm run build
npm run dev -- --host 127.0.0.1 --port 5173
```

Se o comando `python` não existir, use `py -3` no lugar dele.

## Rodar no macOS / MacBook

No MacBook, abra o aplicativo **Terminal**. Se ainda não tiver as ferramentas,
instale o Git, Python e Node.js — por exemplo, usando o Homebrew:

```bash
brew install git python node
```

Clone o repositório e entre na pasta do projeto:

```bash
git clone https://github.com/vlfbtc/AuraFi.git
cd AuraFi
```

Abra dois terminais nessa pasta. O ambiente virtual é recomendado para manter o
Python do AuraFi isolado do restante do MacBook.

Terminal 1 — API:

```bash
cd ~/Projects/AuraFi
python3 -m venv .venv
source .venv/bin/activate
export AURAFI_ENABLE_MARKET_NETWORK=true
export AURAFI_MARKET_MODE=live
python3 -m services.api.cli --host 127.0.0.1 --port 8000
```

Terminal 2 — Web Widget:

```bash
cd ~/Projects/AuraFi/apps/web-widget
npm ci
export VITE_API_BASE_URL=http://127.0.0.1:8000
export VITE_ALLOW_DEMO_DATA=false
npm run build
npm run dev -- --host 127.0.0.1 --port 5173
```

Para conferir que a API iniciou corretamente:

```bash
curl http://127.0.0.1:8000/health
```

Depois abra `http://127.0.0.1:5173` no navegador. Dados de demonstração são opt-in e não devem ser habilitados no ambiente publicado.

Se o comando `python3` não existir depois da instalação, feche e reabra o
Terminal para atualizar o `PATH`. No segundo terminal não é necessário ativar o
`.venv`, porque ele executa apenas o Web Widget com Node.js.

## Validação

```bash
python -m unittest discover -s tests -t . -p "test*.py"
python -m compileall -q services database analytics
python analytics/validate_pipeline.py
```

No Windows, use `py -3` no lugar de `python` se necessário.
