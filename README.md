# AuraFi — Clareza para Investir

AuraFi é uma plataforma de apoio à decisão para pessoas que desejam entender oportunidades de stablecoins em DeFi. O produto explica dados de mercado, considera um perfil de risco declarado e oferece simulações educativas. Não há custódia, conexão de wallet, assinatura ou execução de transações.

Consulte [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) para a matriz
atualizada do que está entregue, das dependências externas e das decisões de
produto ainda necessárias.

## Estrutura atual

- `apps/web-widget`: Web Widget atual, Vite + React + TypeScript.
- `apps/ios`: aplicativo nativo SwiftUI para iOS 17 ou superior.
- `services/api`: API atual, autenticação interna por OTP, perfil, oportunidades e simulações.
- `database`: persistência local SQLite e artefatos do DW.
- `analytics`: validação da camada analítica.
- `contracts`: contratos HTTP/OpenAPI e envelopes de mensagem.
- `tests`: testes unitários, integração, contrato e validações.

## Requisitos

- Python 3.11 ou superior;
- Node.js 20.19+ na linha 20 LTS, ou Node.js 22.12+ e npm;
- navegador moderno.

A API atual usa somente a biblioteca padrão do Python. O Web Widget instala as dependências pelo `package-lock.json`. DeFiLlama é consultado em modo somente leitura quando a rede é habilitada.

## Rodar no Windows (PowerShell)

Abra dois terminais PowerShell na raiz do repositório.

Terminal 1 — API:

```powershell
Set-Location "C:\caminho\para\AuraFi"
$env:AURAFI_ENABLE_MARKET_NETWORK = "true"
$env:AURAFI_MARKET_MODE = "live"
$env:AURAFI_ALLOWED_ORIGINS = "http://127.0.0.1:5173"
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
export AURAFI_ALLOWED_ORIGINS=http://127.0.0.1:5173
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

`AURAFI_ALLOWED_ORIGINS` aceita uma lista separada por vírgulas de origens HTTP(S)
explícitas. Configure nela somente os domínios publicados do Web Widget; curingas
(`*`) são recusados e a variável é obrigatória em produção. Clientes sem contexto de navegador, como o aplicativo iOS,
não enviam o cabeçalho `Origin` e continuam compatíveis.

## Aplicativo iOS no Xcode

O aplicativo exige iOS 17 ou superior. No macOS, abra
`apps/ios/AuraFi.xcodeproj`, selecione o scheme `AuraFi` e um iPhone Simulator.
Os builds Debug e Release usam `https://aurafi-api.onrender.com` por padrão.
Para desenvolvimento exclusivamente local, altere `AURAFI_API_BASE_URL` nas
Build Settings para `http://127.0.0.1:8000`; HTTP continua aceito apenas para
`localhost` e `127.0.0.1` em Debug.

Para percorrer localmente a jornada de OTP no Simulator, use Python 3.11+ e
inicie a API com um código fixo exclusivo de desenvolvimento:

```bash
export AURAFI_DEV_OTP_CODE=123456
python3 -m services.api.cli --host 127.0.0.1 --port 8000
```

No aplicativo, solicite o acesso com um e-mail de teste e informe `123456`.
`AURAFI_DEV_OTP_CODE` é ignorado em produção e não deve ser configurado em um
ambiente publicado.

Validação por linha de comando, sem assinatura:

```bash
cd apps/ios
xcodebuild build \
  -project AuraFi.xcodeproj \
  -scheme AuraFi \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/aurafi-derived-data \
  CODE_SIGNING_ALLOWED=NO

xcodebuild test \
  -project AuraFi.xcodeproj \
  -scheme AuraFi \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  -derivedDataPath /tmp/aurafi-derived-data-tests \
  CODE_SIGNING_ALLOWED=NO
```

O nome do simulador pode variar conforme os runtimes instalados no Xcode.

## Servidor com integrações reais

O `Dockerfile` empacota a API para uma plataforma de containers e escuta em
`0.0.0.0:$PORT` (ou `8000` quando a plataforma não injeta `PORT`). Em um ambiente publicado, coloque o container atrás do HTTPS e
do balanceador/reverse proxy gerenciado da plataforma; não exponha a porta HTTP
diretamente à internet. Use [backend/.env.example](backend/.env.example) somente como catálogo
de configuração e injete os valores reais pelo secret manager.

O perfil de produção exige:

- SMTP com TLS para entrega do OTP;
- pepper HMAC estável e aleatório em `AURAFI_OTP_HMAC_PEPPER`;
- `AURAFI_ALLOW_SELF_SIGNUP=true` quando novos e-mails puderem criar conta;
- DeFiLlama em `https://yields.llama.fi/pools`, somente leitura;
- `AURAFI_LLM_PROVIDER=anthropic` e chave do provider para a conversa Aura;
- origens HTTPS explícitas em `AURAFI_ALLOWED_ORIGINS`;
- volume persistente em `/data` enquanto o adapter SQLite de instância única for usado.

Exemplo de build, sem incorporar `.env` ou segredos na imagem:

```bash
docker build -t aurafi-api:local .
docker run --rm --env-file .env -p 8000:8000 -v aurafi-data:/data aurafi-api:local
```

Para um domínio real, configure a plataforma para encaminhar HTTPS ao container,
publique por exemplo `https://api.seu-dominio.example` e use essa URL em
`VITE_API_BASE_URL` e `AURAFI_API_BASE_URL` do iOS Release. SMTP requer domínio
de remetente validado e SPF/DKIM/DMARC configurados no provedor.

O SQLite é adequado apenas para uma única instância controlada. Escala horizontal,
alta disponibilidade e continuidade conversacional entre réplicas ainda exigem
um adapter PostgreSQL e cache compartilhado; não execute múltiplas réplicas com
o volume SQLite atual.

O [render.yaml](render.yaml) provisiona esse perfil no Render com uma réplica,
health check em `/health`, disco persistente em `/data` e geração automática do
pepper. O Blueprint já configura o SMTP do Resend em `smtp.resend.com:587`, com
STARTTLS e usuário `resend`. No dashboard, informe:

- `AURAFI_OTP_SMTP_PASSWORD`: a chave Resend completa iniciada por `re_`;
- `AURAFI_OTP_FROM_EMAIL`: `onboarding@resend.dev` durante o primeiro teste,
  limitado ao e-mail da própria conta Resend; depois que `aurafi.com.br` estiver
  verificado, use por exemplo `nao-responder@aurafi.com.br`;
- `AURAFI_ALLOWED_ORIGINS`: somente as origens HTTPS do Web Widget, separadas por
  vírgula; o aplicativo iOS não depende de CORS;
- `AURAFI_ANTHROPIC_API_KEY`: a chave do provider conversacional.

Depois de salvar as variáveis, faça um deploy/restart do serviço. Os segredos não
são versionados. O disco persistente requer um plano pago.

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
