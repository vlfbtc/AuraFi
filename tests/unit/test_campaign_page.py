"""Página da campanha "Entenda antes de mexer" e metadados públicos do site.

Lê o HTML-fonte (sempre) e o HTML gerado pelo build (quando ``dist/`` existe,
como depois de ``npm run build``). Falha se a página da campanha trouxer algo
que as regras da campanha proíbem: rendimento, percentual, promessa,
"melhor investimento", nome de protocolo, recomendação fora de "não é
recomendação", simulador, comparação, vídeo incorporado ou perfil com @.
"""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web-widget"
PAGE = WEB / "entenda" / "index.html"
BUILT_PAGE = WEB / "dist" / "entenda" / "index.html"
HOME = WEB / "index.html"
BUILT_HOME = WEB / "dist" / "index.html"
APP = WEB / "src" / "App.tsx"
SITEMAP = WEB / "public" / "sitemap.xml"
SECURITY_TXT = WEB / "public" / ".well-known" / "security.txt"
VITE_CONFIG = WEB / "vite.config.ts"
SITE = "https://aurafi-web-widget.onrender.com"

PROTECTION_RULE = (
    "A AuraFi nunca pede seed phrase, senha ou chave privada. O código de acesso só é digitado "
    "no site ou no app oficiais; ninguém da AuraFi pede esse código por mensagem, ligação ou e-mail."
)
PRICE_ANSWER = "Hoje o uso é gratuito. Um plano pago será anunciado aqui antes de qualquer cobrança."
PROTOCOLS = (
    "aave", "compound", "curve", "uniswap", "morpho", "spark", "maker", "makerdao", "sky", "lido",
    "pendle", "yearn", "ethena", "convex", "balancer", "venus", "kamino", "justlend", "sushi",
    "sushiswap", "gmx", "fluid", "euler", "radiant", "frax", "beefy", "stargate",
)
FORBIDDEN = {
    "APY ou APR": r"\bap[yr]\b",
    "número seguido de %": r"\d\s*%",
    "percentual por extenso": r"\d+\s*por\s*cento",
    "valor em dinheiro": r"(?:R\$|US\$|\$)\s*\d",
    "garantido": r"garantid",
    "melhor investimento": r"melhor\s+investimento",
    "nome de protocolo": r"\b(?:" + "|".join(PROTOCOLS) + r")\b",
    "simulador": r"simulador|simule|calculadora",
    "comparação": r"compar",
    "vídeo ou página incorporada": r"<\s*(?:iframe|embed|object|video)\b",
}
ALLOWED_LINK_PREFIXES = (
    f"{SITE}/",
    "https://github.com/vlfbtc/AuraFi",
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[dict[str, str | None]] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self.scripts.append(values)
            self._skip += 1
        elif tag == "style":
            self._skip += 1
        elif tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))
        elif tag == "meta":
            key = values.get("property") or values.get("name") or values.get("http-equiv")
            if key:
                self.meta[key] = values.get("content") or ""
        elif tag == "link" and values.get("rel") == "canonical":
            self.canonical = values.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text.append(data)


def parse(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    return parser


def collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class CampaignPageTests(unittest.TestCase):
    def pages(self) -> list[tuple[str, str]]:
        found = [("fonte", PAGE.read_text(encoding="utf-8"))]
        if BUILT_PAGE.exists():
            found.append(("build", BUILT_PAGE.read_text(encoding="utf-8")))
        return found

    def test_pagina_nao_tem_termo_proibido(self) -> None:
        for label, html in self.pages():
            lowered = html.casefold()
            for rule, pattern in FORBIDDEN.items():
                with self.subTest(pagina=label, regra=rule):
                    self.assertIsNone(re.search(pattern, lowered), f"{rule}: {re.search(pattern, lowered)}")
            with self.subTest(pagina=label, regra="recomendação"):
                remaining = lowered.replace("não é recomendação", "")
                self.assertNotIn("recomend", remaining)

    def test_nenhum_perfil_com_arroba_nem_link_de_fora_dos_canais_oficiais(self) -> None:
        for label, html in self.pages():
            without_structured_data = re.sub(
                r'<script type="application/ld\+json">.*?</script>', "", html, flags=re.S
            )
            with self.subTest(pagina=label):
                self.assertNotIn("@", without_structured_data)
                for href in parse(html).links:
                    if href.startswith("/"):
                        continue
                    self.assertTrue(href.startswith(ALLOWED_LINK_PREFIXES), href)

    def test_so_script_do_proprio_site(self) -> None:
        for label, html in self.pages():
            for script in parse(html).scripts:
                with self.subTest(pagina=label, script=script):
                    if script.get("type") == "application/ld+json":
                        self.assertIsNone(script.get("src"))
                        continue
                    source = script.get("src") or ""
                    self.assertTrue(source.startswith("/") and not source.startswith("//"), source)

    def test_textos_obrigatorios_e_chamada(self) -> None:
        html = PAGE.read_text(encoding="utf-8")
        page = parse(html)
        text = collapse(" ".join(page.text))
        self.assertIn("Entenda antes de mexer nas suas stablecoins.", text)
        self.assertIn(PROTECTION_RULE, text)
        self.assertIn(PRICE_ANSWER, text)
        self.assertIn("Contamos, sem identificar ninguém, quantos cadastros vieram de cada campanha.", text)
        self.assertIn("O que a AuraFi não faz", text)
        self.assertIn("Código público para consulta", text)
        self.assertNotIn("código aberto", text.casefold())
        self.assertIn("/#comecar", page.links)
        self.assertIn("https://github.com/vlfbtc/AuraFi/security/advisories/new", page.links)

    def test_metadados_proprios_da_pagina(self) -> None:
        page = parse(PAGE.read_text(encoding="utf-8"))
        self.assertEqual(page.canonical, f"{SITE}/entenda/")
        self.assertEqual(page.meta["og:url"], f"{SITE}/entenda/")
        self.assertEqual(page.meta["og:image"], f"{SITE}/og-image.png")
        self.assertEqual(page.meta["twitter:card"], "summary_large_image")
        for key in ("description", "og:title", "og:description", "og:image:alt", "twitter:image"):
            self.assertTrue(page.meta.get(key), key)

    def test_pagina_esta_no_mapa_do_site_e_no_build(self) -> None:
        self.assertIn(f"<loc>{SITE}/entenda/</loc>", SITEMAP.read_text(encoding="utf-8"))
        self.assertIn("entenda: 'entenda/index.html'", VITE_CONFIG.read_text(encoding="utf-8"))

    @unittest.skipUnless(BUILT_PAGE.exists(), "rode npm run build em apps/web-widget para conferir o HTML gerado")
    def test_build_tem_politica_de_seguranca_de_conteudo(self) -> None:
        for path in (BUILT_PAGE, BUILT_HOME):
            with self.subTest(pagina=path.parent.name):
                policy = parse(path.read_text(encoding="utf-8")).meta.get("Content-Security-Policy", "")
                self.assertIn("default-src 'self'", policy)
                self.assertIn("script-src 'self'", policy)
                self.assertIn("object-src 'none'", policy)
        for name in ("og-image.png", "favicon.svg", "favicon.ico", "apple-touch-icon.png", ".well-known/security.txt"):
            self.assertTrue((WEB / "dist" / name).exists(), name)


class HomeMetadataTests(unittest.TestCase):
    def test_titulo_sem_ano_e_igual_nos_dois_lugares(self) -> None:
        home = HOME.read_text(encoding="utf-8")
        app = APP.read_text(encoding="utf-8")
        title = "Entenda antes de mexer nas suas stablecoins."
        self.assertIn(f'<h1 id="welcome-title">{title}</h1>', home)
        self.assertIn(f"tabIndex={{-1}}>{title}</h1>", app)
        self.assertNotIn("em 2026", home + app)

    def test_descricao_sem_comparar_e_cartao_com_imagem(self) -> None:
        sources = [HOME.read_text(encoding="utf-8")]
        if BUILT_HOME.exists():
            sources.append(BUILT_HOME.read_text(encoding="utf-8"))
        for html in sources:
            self.assertNotIn("Compare oportunidades", html)
            self.assertNotIn("comparadas", html)
            meta = parse(html).meta
            self.assertEqual(meta["og:image"], f"{SITE}/og-image.png")
            self.assertEqual(meta["og:image:width"], "1200")
            self.assertEqual(meta["og:image:height"], "630")
            self.assertTrue(meta["og:image:alt"])
            self.assertEqual(meta["twitter:card"], "summary_large_image")
            self.assertEqual(meta["twitter:image"], f"{SITE}/og-image.png")
            self.assertIn('rel="icon"', html)
            self.assertIn('rel="apple-touch-icon"', html)

    def test_imagem_de_compartilhamento_tem_1200_por_630(self) -> None:
        data = (WEB / "public" / "og-image.png").read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (1200, 630))
        touch = (WEB / "public" / "apple-touch-icon.png").read_bytes()
        self.assertEqual((int.from_bytes(touch[16:20], "big"), int.from_bytes(touch[20:24], "big")), (180, 180))

    def test_consentimento_continua_verdadeiro_e_quadro_tem_a_contagem(self) -> None:
        app = APP.read_text(encoding="utf-8")
        self.assertIn("'Métricas de uso ficam desativadas'", app)
        self.assertIn("analytics: false", app)
        self.assertIn("'Contamos, sem identificar ninguém, quantos cadastros vieram de cada campanha.'", app)


class SecurityTxtTests(unittest.TestCase):
    def test_campos_da_rfc_9116(self) -> None:
        fields: dict[str, str] = {}
        for line in SECURITY_TXT.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                key, _, value = line.partition(": ")
                fields[key] = value
        self.assertEqual(fields["Contact"], "https://github.com/vlfbtc/AuraFi/security/advisories/new")
        self.assertIsInstance(datetime.fromisoformat(fields["Expires"].replace("Z", "+00:00")), datetime)
        self.assertEqual(fields["Preferred-Languages"], "pt, en")
        self.assertEqual(fields["Canonical"], f"{SITE}/.well-known/security.txt")
        self.assertEqual(fields["Policy"], "https://github.com/vlfbtc/AuraFi/blob/main/SECURITY.md")
        self.assertTrue((ROOT / "SECURITY.md").exists())


if __name__ == "__main__":
    unittest.main()
