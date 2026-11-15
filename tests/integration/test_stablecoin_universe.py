"""Universo de stablecoins da lista de oportunidades (pendência U1 da banca).

Usa uma leitura gravada de ``yields.llama.fi/pools`` em 15/11/2026
(``tests/fixtures/defillama_pools_20261115.json``: os 80 primeiros pools, na
ordem da fonte). Antes do filtro, a lista repetia a fonte, em que só 2 dos 12
primeiros pools são stablecoins. Agora entram só os pools que a DeFiLlama
marca com ``stablecoin: true`` e cujo ativo é USDT, USDC ou DAI, e esse
universo vale para o site, o app e o aterramento da Aura.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from services.api import create_app
from services.api.app import Request
from services.conversation import LlmResult
from services.market_data import (
    DeFiLlamaAdapter,
    DeFiLlamaSchema,
    MarketDataError,
    STABLECOIN_ASSETS,
    is_supported_stablecoin_pool,
)

ROOT = Path(__file__).resolve().parents[2]
RECORDING = ROOT / "tests" / "fixtures" / "defillama_pools_20261115.json"
CONSENT = {"purpose": "conversation", "status": "granted", "policy_version": "aurafi-privacy-2026-09"}

# Os 8 pools que passam no filtro, na ordem da gravação.
EXPECTED = [
    ("maple", "USDC", "Ethereum"),
    ("maple", "USDT", "Ethereum"),
    ("jupiter-lend", "USDC", "Solana"),
    ("aave-v3", "USDT", "Ethereum"),
    ("spark-savings", "USDT", "Ethereum"),
    ("spark-savings", "USDC", "Ethereum"),
    ("hyperliquid-earn", "USDC", "Hyperliquid L1"),
    ("centrifuge-protocol", "USDC", "Avalanche"),
]
STETH_POOL_ID = "747c1d2a-c668-4682-b9f9-296708a3dd90"


def _recording() -> dict:
    return json.loads(RECORDING.read_text(encoding="utf-8"))


class RecordedHttp:
    """Devolve a gravação para ``/pools``; o resto (histórico, PTAX) falha e degrada."""

    def __init__(self) -> None:
        self.payload = _recording()

    def get(self, url: str, *, timeout_seconds: float):
        del timeout_seconds
        if url.endswith("/pools"):
            return self.payload
        raise OSError("só /pools está gravado")


class SpyLlm:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LlmResult("Explico os riscos das oportunidades observadas.", mode="provider", provider="spy")


class RecordedSourceTests(unittest.TestCase):
    def test_gravacao_mostra_o_problema_da_lista_sem_filtro(self) -> None:
        pools = _recording()["data"]
        self.assertEqual(len(pools), 80)
        first_twelve = pools[:12]
        self.assertEqual(sum(1 for pool in first_twelve if pool["stablecoin"] is True), 2)
        self.assertEqual(first_twelve[0]["symbol"], "STETH")

    def test_adapter_mantem_so_stablecoins_usdt_usdc_dai(self) -> None:
        adapter = DeFiLlamaAdapter(
            base_url="https://yields.llama.fi", endpoint="/pools", http_client=RecordedHttp()
        )
        snapshot = adapter.read(mode="live")

        self.assertEqual([(i.protocol, i.asset, i.blockchain) for i in snapshot.items], EXPECTED)
        self.assertTrue(all(item.asset in STABLECOIN_ASSETS for item in snapshot.items))
        ids = {item.opportunity_id for item in snapshot.items}
        self.assertNotIn(STETH_POOL_ID, ids)
        # Stablecoins fora das três acompanhadas também ficam de fora.
        excluded = {(pool["project"], pool["symbol"]) for pool in _recording()["data"] if pool["pool"] not in ids}
        for outside in (("sky-lending", "SUSDS"), ("ethena-usde", "SUSDE"), ("maple", "USDG"), ("lido", "STETH")):
            self.assertIn(outside, excluded)


class StablecoinRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = DeFiLlamaSchema()

    def pool(self, **fields) -> dict:
        base = {"pool": "p", "project": "x", "symbol": "USDC", "chain": "Ethereum", "apy": 1.0, "tvlUsd": 1.0}
        base.update(fields)
        return base

    def test_regra_exige_marca_da_fonte_e_ativo_acompanhado(self) -> None:
        cases = {
            "USDC marcado": (self.pool(stablecoin=True), True),
            "DAI em minúsculas": (self.pool(symbol="dai", stablecoin=True), True),
            "USDT com espaço": (self.pool(symbol=" USDT ", stablecoin=True), True),
            "sem o campo stablecoin": (self.pool(), False),
            "marcado como falso": (self.pool(stablecoin=False), False),
            "texto em vez de booleano": (self.pool(stablecoin="true"), False),
            "par de liquidez": (self.pool(symbol="USDC-USDT", stablecoin=True), False),
            "outra stablecoin": (self.pool(symbol="USDE", stablecoin=True), False),
            "ativo volátil": (self.pool(symbol="STETH", stablecoin=False), False),
        }
        for label, (pool, expected) in cases.items():
            with self.subTest(caso=label):
                self.assertIs(is_supported_stablecoin_pool(pool, self.schema), expected)

    def test_resposta_sem_nenhuma_stablecoin_e_erro_controlado(self) -> None:
        adapter = DeFiLlamaAdapter(fallback=lambda: {"data": [self.pool(symbol="STETH", stablecoin=False)]})
        with self.assertRaises(MarketDataError):
            adapter.read(mode="test")


class StablecoinUniverseApiTests(unittest.TestCase):
    """Site e app usam a mesma API; a Aura lê o mesmo snapshot."""

    def setUp(self) -> None:
        self.llm = SpyLlm()
        self.app = create_app(market_mode="test", llm=self.llm)
        self.addCleanup(self.app.close)
        self.app.market_mode = "live"
        self.app.market.base_url = "https://yields.llama.fi"
        self.app.market.endpoint = "/pools"
        self.app.market.http_client = RecordedHttp()

    def call(self, method: str, target: str, body: dict | None = None, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.app.handle(Request(method=method, target=target, headers=headers, body=body))

    def login(self, channel: str) -> str:
        requested = self.call("POST", "/v1/auth/otp/request", {"email": "maria@example.com", "channel": channel})
        code = self.app.otp_sink.code_for(requested.payload["challenge_id"])
        verified = self.call("POST", "/v1/auth/otp/verify", {"challenge_id": requested.payload["challenge_id"], "otp": code})
        self.assertEqual(verified.status, 200)
        return verified.payload["session"]["access_token"]

    def test_site_e_app_recebem_so_stablecoins(self) -> None:
        # Os mesmos parâmetros que api.ts (site) e APIClient.swift (app) enviam.
        requests = {
            "web_widget": "/v1/opportunities?page=1&page_size=12&risk_profile=moderate",
            "ios_app": "/v1/opportunities?page=1&page_size=20",
        }
        for channel, target in requests.items():
            with self.subTest(canal=channel):
                response = self.call("GET", target, token=self.login(channel))
                self.assertEqual(response.status, 200)
                items = response.payload["items"]
                self.assertEqual(response.payload["pagination"]["total"], len(EXPECTED))
                self.assertEqual([(i["protocol"], i["asset"], i["blockchain"]) for i in items], EXPECTED)
                self.assertTrue(all(item["asset"] in STABLECOIN_ASSETS for item in items))

    def test_pool_fora_do_universo_nao_abre_detalhe_nem_simulacao(self) -> None:
        token = self.login("web_widget")
        detail = self.call("GET", f"/v1/opportunities/{STETH_POOL_ID}", token=token)
        self.assertEqual(detail.status, 404)
        simulation = self.call(
            "POST",
            "/v1/simulations",
            {"opportunity_id": STETH_POOL_ID, "amount": 500, "asset": "STETH", "horizons_days": [30]},
            token,
        )
        self.assertEqual(simulation.status, 404)

    def test_aura_e_aterrada_nas_seis_primeiras_stablecoins(self) -> None:
        token = self.login("ios_app")
        created = self.call("POST", "/v1/conversations", {"channel": "ios_app", "consent": CONSENT}, token)
        conversation_id = created.payload["conversation"]["conversation_id"]
        sent = self.call(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            {"text": "Quais riscos devo observar nas oportunidades atuais?", "channel": "ios_app", "consent": CONSENT},
            token,
        )
        self.assertEqual(sent.status, 201)
        self.assertTrue(self.llm.requests)

        grounding = self.llm.requests[-1].grounding
        lines = [line for line in grounding.splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 6)
        for line, (protocol, asset, chain) in zip(lines, EXPECTED[:6], strict=True):
            self.assertTrue(line.startswith(f"- {protocol} · {asset} · {chain}"), line)
        for outside in ("STETH", "WEETH", "SUSDS", "CBBTC"):
            self.assertNotIn(outside, grounding)


if __name__ == "__main__":
    unittest.main()
