"""Texto do nível de risco no site e no app (pendência U2 da banca).

O nível de risco que os clientes mostram vem da heurística
``derive_risk_level`` (services/market_data/presentation.py), que usa APY, TVL
e, quando existe, a auditoria. A DeFiLlama não classifica risco. O texto não
pode, portanto, atribuir o nível à fonte nem dizer que a AuraFi não o calcula.

Lê o código-fonte do site (sempre) e o JavaScript gerado pelo build (quando
``dist/`` existe, como depois de ``npm run build``), além do app iOS.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from services.market_data.presentation import decorate_opportunity

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web-widget"
APP = WEB / "src" / "App.tsx"
BUILT_ASSETS = WEB / "dist" / "assets"
IOS_DASHBOARD = ROOT / "apps" / "ios" / "DashboardView.swift"

FORBIDDEN = {
    "nível atribuído à fonte": r"informad[oa]s?\s+pela\s+fonte",
    "negação do cálculo": r"n[ãa]o\s+calcula\s+score",
    "rótulo 'risco informado'": r"risco\s+informado",
    "lista de riscos informados": r"riscos\s+informados",
}
ESTIMATE = "Nível estimado pela AuraFi a partir de APY e TVL"
LIMITS = "Não avalia contrato, paridade, liquidez nem governança"


def _web_sources() -> list[tuple[str, str]]:
    sources = [(str(APP.relative_to(ROOT)), APP.read_text(encoding="utf-8"))]
    if BUILT_ASSETS.is_dir():
        for path in sorted(BUILT_ASSETS.glob("*.js")):
            sources.append((str(path.relative_to(ROOT)), path.read_text(encoding="utf-8")))
    return sources


class WebRiskCopyTests(unittest.TestCase):
    def test_site_nao_atribui_o_nivel_de_risco_a_fonte(self) -> None:
        for name, text in _web_sources():
            for label, pattern in FORBIDDEN.items():
                with self.subTest(arquivo=name, regra=label):
                    match = re.search(pattern, text, flags=re.IGNORECASE)
                    self.assertIsNone(match, f"{name} traz {label}: {match.group(0) if match else ''}")

    def test_detalhe_explica_que_o_nivel_e_estimado_e_o_que_fica_de_fora(self) -> None:
        text = APP.read_text(encoding="utf-8")
        self.assertIn(ESTIMATE, text)
        self.assertIn(LIMITS, text)
        # O detalhe da oportunidade usa a nota, e o card do painel chama o campo de estimado.
        self.assertIn("<p className=\"detail-note\">{RISK_ESTIMATE_NOTE}</p>", text)
        self.assertIn("<span>Risco estimado</span>", text)

    def test_build_traz_o_texto_novo_quando_existe(self) -> None:
        if not BUILT_ASSETS.is_dir():
            self.skipTest("dist/ ausente; rode npm run build em apps/web-widget")
        bundle = "\n".join(path.read_text(encoding="utf-8") for path in BUILT_ASSETS.glob("*.js"))
        self.assertIn(ESTIMATE, bundle)


class IosRiskCopyTests(unittest.TestCase):
    def test_app_diz_que_o_nivel_e_estimado(self) -> None:
        text = IOS_DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("estimado por APY, TVL e auditoria", text)
        self.assertIn("Estimado pela AuraFi a partir de APY e TVL", text)
        # O texto antigo do explicador dizia que o nível considerava contrato,
        # liquidez e ativo, o que a heurística não faz.
        self.assertNotIn("Considera o contrato, a liquidez e o ativo", text)
        for label, pattern in FORBIDDEN.items():
            with self.subTest(regra=label):
                self.assertIsNone(re.search(pattern, text, flags=re.IGNORECASE))


class RiskClassificationContractTests(unittest.TestCase):
    def test_nivel_sem_classificacao_da_fonte_sai_marcado_como_heuristico(self) -> None:
        # Uma pool da DeFiLlama nunca traz nível de risco: o BFF estima e marca.
        payload = {
            "apy": {"value": 5.2},
            "tvl": {"value": 2_271_796_499, "currency": "USD"},
            "risk": {"score": None, "level": "unknown", "dimensions": []},
        }
        risk = decorate_opportunity(payload)["risk"]
        self.assertEqual(risk["classification"], "heuristic")
        self.assertEqual(risk["level"], "low")


if __name__ == "__main__":
    unittest.main()
