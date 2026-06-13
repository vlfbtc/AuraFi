"""
AuraFi Backend — FastAPI (Python 3.12)
Hub Conversacional Multi-canal · Fase 4
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
import json
from datetime import datetime

app = FastAPI(
    title="AuraFi API",
    description="Backend do Hub Conversacional da AuraFi",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MODELOS ────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    user_profile: Optional[str] = "moderado"
    user_balance_usd: Optional[float] = 8420.0

class SimulacaoRequest(BaseModel):
    protocolo_id: str
    valor_usd: float
    prazo_meses: int
    perfil_risco: Optional[str] = "moderado"

class SimulacaoResponse(BaseModel):
    protocolo: str
    valor_inicial_usd: float
    rendimento_estimado_usd: float
    apy_atual: float
    score_seguranca: float
    prazo_meses: int
    explicacao_aura: str
    aviso: str

class PerfilRequest(BaseModel):
    respostas: List[int]  # pontuação de cada resposta do quiz

# ─── DADOS SIMULADOS (substituir por DeFiLlama API em produção) ─
PROTOCOLS_DATA = {
    "aave": {
        "nome": "Aave v3",
        "token": "USDC",
        "categoria": "Lending",
        "apy": 5.2,
        "score_seguranca": 9.2,
        "tvl_usd": 1_800_000_000,
        "chain": "Base",
        "auditor": "Trail of Bits",
        "auditado": True,
    },
    "compound": {
        "nome": "Compound",
        "token": "DAI",
        "categoria": "Lending",
        "apy": 4.7,
        "score_seguranca": 8.5,
        "tvl_usd": 890_000_000,
        "chain": "Ethereum",
        "auditor": "OpenZeppelin",
        "auditado": True,
    },
    "morpho": {
        "nome": "Morpho",
        "token": "USDC",
        "categoria": "Lending",
        "apy": 5.5,
        "score_seguranca": 8.8,
        "tvl_usd": 1_200_000_000,
        "chain": "Base",
        "auditor": "Dedaub",
        "auditado": True,
    },
    "spark": {
        "nome": "Spark",
        "token": "DAI",
        "categoria": "Lending",
        "apy": 4.9,
        "score_seguranca": 8.1,
        "tvl_usd": 650_000_000,
        "chain": "Ethereum",
        "auditor": "ChainSecurity",
        "auditado": True,
    },
    "curve": {
        "nome": "Curve 3pool",
        "token": "USDT",
        "categoria": "DEX",
        "apy": 3.8,
        "score_seguranca": 9.5,
        "tvl_usd": 3_200_000_000,
        "chain": "Ethereum",
        "auditor": "Trail of Bits",
        "auditado": True,
    },
}

AURA_SYSTEM_PROMPT = """Você é a Aura, assistente de IA da AuraFi — plataforma de apoio à decisão de alocação de stablecoins em DeFi.

REGRAS ABSOLUTAS:
1. NUNCA prometa retorno garantido — sempre use "pode render", "estimativa histórica"
2. NUNCA atue como gestor ou assessor de valores mobiliários regulado
3. SEMPRE lembre que a AuraFi não tem custódia dos fundos
4. SEMPRE diga que o usuário toma a decisão final
5. Score de segurança: escala 0-10, onde 10 = máximo (auditado, consolidado, alto TVL)

TOM: acolhedor, claro, direto, PT-BR. Máx 4 parágrafos por resposta.
PÚBLICO: investidores não-técnicos, brasileiros, curiosos sobre DeFi."""


# ─── ENDPOINTS ──────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "produto": "AuraFi", "versao": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/protocolos")
async def listar_protocolos(perfil: Optional[str] = "moderado"):
    """Retorna protocolos DeFi filtrados por perfil de risco."""
    perfis = {
        "conservador": {"score_min": 9.0, "apy_max": 5.0},
        "moderado": {"score_min": 8.0, "apy_max": 8.0},
        "arrojado": {"score_min": 7.0, "apy_max": 20.0},
    }
    filtro = perfis.get(perfil, perfis["moderado"])
    resultado = []
    for pid, p in PROTOCOLS_DATA.items():
        if p["score_seguranca"] >= filtro["score_min"] and p["apy"] <= filtro["apy_max"]:
            resultado.append({"id": pid, **p})
    resultado.sort(key=lambda x: x["apy"], reverse=True)
    return {"perfil": perfil, "total": len(resultado), "protocolos": resultado}


@app.get("/protocolos/{protocolo_id}")
async def detalhe_protocolo(protocolo_id: str):
    """Retorna detalhes de um protocolo específico."""
    if protocolo_id not in PROTOCOLS_DATA:
        raise HTTPException(status_code=404, detail="Protocolo não encontrado")
    return {"id": protocolo_id, **PROTOCOLS_DATA[protocolo_id]}


@app.post("/simular", response_model=SimulacaoResponse)
async def simular_alocacao(req: SimulacaoRequest):
    """Calcula simulação de rendimento e gera explicação da Aura."""
    if req.protocolo_id not in PROTOCOLS_DATA:
        raise HTTPException(status_code=404, detail="Protocolo não encontrado")
    
    p = PROTOCOLS_DATA[req.protocolo_id]
    apy_decimal = p["apy"] / 100
    rendimento = req.valor_usd * apy_decimal * (req.prazo_meses / 12)
    
    explicacoes = {
        "aave": f"O Aave v3 na Base chain tem TVL de US$ 1,8 bilhão e score 9,2/10, ideal para perfil {req.perfil_risco}. Gas fees baixas na Base tornam aportes de qualquer tamanho eficientes.",
        "compound": "Compound é um dos protocolos mais auditados do DeFi. Atenção: gas fees na Ethereum mainnet podem reduzir o rendimento real em aportes menores que US$ 1.000.",
        "morpho": "Morpho oferece APY superior ao Aave com mecanismo de matching peer-to-peer. Mais recente, mas auditado e com TVL crescente. Boa escolha para quem busca melhor rendimento com risco controlado.",
        "spark": "Spark é lastreado no protocolo MakerDAO, um dos mais testados do ecossistema. DAI é a stablecoin com maior histórico de estabilidade no DeFi.",
        "curve": "Curve 3pool tem o maior score de segurança disponível. Ideal para perfil conservador ou como base de uma estratégia diversificada.",
    }
    
    return SimulacaoResponse(
        protocolo=p["nome"],
        valor_inicial_usd=req.valor_usd,
        rendimento_estimado_usd=round(rendimento, 2),
        apy_atual=p["apy"],
        score_seguranca=p["score_seguranca"],
        prazo_meses=req.prazo_meses,
        explicacao_aura=explicacoes.get(req.protocolo_id, "Protocolo disponível para alocação."),
        aviso="Rendimento estimado com base no APY atual. Rendimentos em DeFi são variáveis. A AuraFi não tem custódia dos seus fundos e não garante retorno. Você decide."
    )


@app.post("/chat")
async def chat_aura(req: ChatRequest):
    """
    Endpoint do chat conversacional com a Aura.
    Em produção: usa Claude via AWS Bedrock.
    Para demo: chama API Anthropic diretamente.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "resposta": "API key não configurada. Configure ANTHROPIC_API_KEY no .env para ativar a Aura.",
            "canal": "web",
            "timestamp": datetime.now().isoformat()
        }
    
    contexto_usuario = f"""
Contexto do usuário:
- Saldo: US$ {req.user_balance_usd:,.2f} em stablecoins
- Perfil de risco: {req.user_profile}
- Canal: Web Widget
"""
    
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 800,
                "system": AURA_SYSTEM_PROMPT + "\n\n" + contexto_usuario,
                "messages": messages,
            }
        )
        data = response.json()
        texto = data.get("content", [{}])[0].get("text", "Desculpa, tente novamente.")
    
    return {
        "resposta": texto,
        "canal": "web",
        "perfil": req.user_profile,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/perfil/calcular")
async def calcular_perfil(req: PerfilRequest):
    """Calcula o perfil de risco com base nas respostas do quiz."""
    score = sum(req.respostas)
    if score <= 1:
        perfil = "conservador"
        desc = "Você prioriza segurança. Recomendamos protocolos com score ≥ 9,0 e TVL consolidado."
        protocols = ["aave", "curve"]
    elif score <= 3:
        perfil = "moderado"
        desc = "Equilíbrio entre segurança e rendimento. Boas opções: Aave, Morpho e Compound."
        protocols = ["aave", "morpho", "compound"]
    else:
        perfil = "arrojado"
        desc = "Você aceita mais risco em busca de rendimento. A Aura monitorará de perto para você."
        protocols = ["morpho", "spark", "compound"]
    
    return {
        "perfil": perfil,
        "score": score,
        "descricao": desc,
        "protocolos_recomendados": protocols,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/yields/live")
async def yields_live():
    """
    Busca yields em tempo real da DeFiLlama API.
    Em produção: filtra pelos protocolos curados da AuraFi.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://yields.llama.fi/pools")
            data = response.json()
            pools_curados = ["aave-v3", "compound-v3", "morpho"]
            resultado = []
            for pool in data.get("data", [])[:5]:
                resultado.append({
                    "pool": pool.get("pool"),
                    "project": pool.get("project"),
                    "symbol": pool.get("symbol"),
                    "apy": pool.get("apy"),
                    "tvlUsd": pool.get("tvlUsd"),
                    "chain": pool.get("chain"),
                })
        return {"fonte": "DeFiLlama", "total": len(resultado), "pools": resultado}
    except Exception:
        return {"fonte": "simulado", "pools": [
            {"project": "aave-v3", "symbol": "USDC", "apy": 5.2, "tvlUsd": 1_800_000_000, "chain": "Base"},
            {"project": "compound-v3", "symbol": "USDC", "apy": 4.7, "tvlUsd": 890_000_000, "chain": "Ethereum"},
        ]}
