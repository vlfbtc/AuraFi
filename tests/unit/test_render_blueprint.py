"""Arquivo de implantação da Render (``render.yaml``), pendências da banca.

Confere que a publicação espera o CI aprovado e que a API de produção liga a
limpeza de retenção. O leitor abaixo cobre só o formato deste arquivo (listas
``- key:``/``value:`` e campos simples), para o teste não depender de PyYAML.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "render.yaml"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _blocks() -> dict[str, list[str]]:
    """Linhas de cada serviço ou banco, indexadas pelo ``name``."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in RENDER.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        if line.startswith("  - "):  # início de um item de databases: ou services:
            current = []
        if current is None:
            continue
        current.append(line.strip())
        # O nome do item fica na linha do traço ou logo abaixo, com 4 espaços.
        match = re.match(r"^(?:  - |    )name: (\S+)$", line)
        if match:
            blocks[match.group(1)] = current
    return blocks


def render_field(name: str, field: str) -> str | None:
    for line in _blocks()[name]:
        match = re.match(rf"^(?:- )?{re.escape(field)}: (.+)$", line)
        if match:
            return match.group(1).strip().strip('"')
    return None


def render_env(name: str) -> dict[str, str]:
    env: dict[str, str] = {}
    key: str | None = None
    for line in _blocks()[name]:
        match = re.match(r"^- key: (\S+)$", line)
        if match:
            key = match.group(1)
            continue
        match = re.match(r"^value: (.*)$", line)
        if match and key is not None:
            env[key] = match.group(1).strip().strip('"')
            key = None
    return env


class RenderBlueprintTests(unittest.TestCase):
    def test_leitor_encontra_os_servicos_e_o_banco(self) -> None:
        self.assertEqual(set(_blocks()), {"aurafi-db", "aurafi-api", "aurafi-web-widget"})
        self.assertEqual(render_env("aurafi-api")["AURAFI_ENV"], "production")

    def test_publicacao_so_depois_dos_checks_do_ci(self) -> None:
        for service in ("aurafi-api", "aurafi-web-widget"):
            with self.subTest(servico=service):
                self.assertEqual(render_field(service, "autoDeployTrigger"), "checksPass")
        self.assertNotIn("autoDeployTrigger: commit", RENDER.read_text(encoding="utf-8"))
        # Os checks que a Render espera rodam no push para main.
        workflow = CI.read_text(encoding="utf-8")
        self.assertRegex(workflow, r"push:\s*\n\s*branches: \[main\]")

    def test_api_de_producao_liga_a_limpeza_de_retencao(self) -> None:
        self.assertEqual(render_env("aurafi-api").get("AURAFI_RETENTION_PURGE"), "true")

    def test_banco_declara_o_plano_pago_em_uso(self) -> None:
        # O arquivo dizia "plan: free"; o banco de produção é pago (basic-256mb).
        self.assertEqual(render_field("aurafi-db", "plan"), "basic-256mb")
        self.assertNotRegex(RENDER.read_text(encoding="utf-8"), r"(?m)^\s*plan: free\s*$")
        # A API continua apontando para este banco.
        api_lines = "\n".join(_blocks()["aurafi-api"])
        self.assertIn("fromDatabase:", api_lines)
        self.assertIn("name: aurafi-db", api_lines)


if __name__ == "__main__":
    unittest.main()
