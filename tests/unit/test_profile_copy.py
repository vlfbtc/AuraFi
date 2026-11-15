"""O perfil vem da soma das respostas, e não é escolhido nem "declarado" pela pessoa.

Desde 15/11/2026, site e app calculam o perfil pelo mesmo questionário
(contracts/risk-questionnaire.json). A banca do TCC apontou que a tela de
resultado ainda o chamava de "Perfil declarado"; este teste impede que o texto
volte e confere que o aviso diz que o perfil não é avaliação de adequação.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_APP = ROOT / "apps" / "web-widget" / "src" / "App.tsx"
IOS_DASHBOARD = ROOT / "apps" / "ios" / "DashboardView.swift"

OLD_WEB = ("Perfil declarado", "Você declarou", "Ainda não declarado", "Seu contexto declarado", "perfil declarado")


class WebProfileCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = WEB_APP.read_text(encoding="utf-8")

    def test_site_nao_chama_o_perfil_de_declarado(self) -> None:
        for phrase in OLD_WEB:
            self.assertNotIn(phrase, self.text, phrase)

    def test_resultado_diz_que_o_perfil_vem_das_respostas(self) -> None:
        self.assertIn("Perfil calculado pelas respostas", self.text)
        self.assertIn("Suas respostas indicam", self.text)

    def test_aviso_diz_que_nao_e_avaliacao_de_adequacao(self) -> None:
        self.assertIn("não uma avaliação profissional de adequação", self.text)


class IosProfileCopyTests(unittest.TestCase):
    def test_app_nao_chama_a_falta_de_perfil_de_nao_declarado(self) -> None:
        text = IOS_DASHBOARD.read_text(encoding="utf-8")
        self.assertNotIn("não declarado", text.lower())


if __name__ == "__main__":
    unittest.main()
