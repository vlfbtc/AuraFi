"""Questionário de perfil igual no site e no app (pendência da banca, U3 no TCC).

Antes, o site fazia quatro perguntas de preferência e pedia o perfil na quinta,
e o app somava pontos de cinco perguntas de risco: a mesma pessoa podia sair
com perfis diferentes conforme o canal. Agora os dois usam as perguntas e a
pontuação de ``contracts/risk-questionnaire.json``.

O módulo só usa a biblioteca padrão. Os testes de execução rodam o código real
de cada cliente com as mesmas respostas (todas as 243 combinações, mais dois
casos inválidos): o TypeScript do site pelo Node (22.18 ou mais novo, ou 22.6
com ``--experimental-strip-types``) e o Swift do app pelo ``swiftc`` do Xcode.
Sem a ferramenta, o teste correspondente é pulado; a conferência estática roda
sempre. No CI, o job do iOS (macOS, com Node 22) roda este módulo inteiro.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "contracts" / "risk-questionnaire.json"
WEB_MODULE = ROOT / "apps" / "web-widget" / "src" / "riskQuestionnaire.ts"
WEB_APP = ROOT / "apps" / "web-widget" / "src" / "App.tsx"
IOS_MODULE = ROOT / "apps" / "ios" / "RiskQuestionnaire.swift"
IOS_ONBOARDING = ROOT / "apps" / "ios" / "OnboardingView.swift"
IOS_PROJECT = ROOT / "apps" / "ios" / "AuraFi.xcodeproj" / "project.pbxproj"

_TS_QUESTION = re.compile(
    r"id: '(?P<id>question_\d+)',\s*title: '(?P<title>[^']*)',\s*context: '(?P<context>[^']*)',"
    r"\s*options: \[(?P<options>.*?)\]",
    re.S,
)
_TS_OPTION = re.compile(
    r"\{ id: '(?P<id>[^']+)', title: '(?P<title>[^']*)', subtitle: '(?P<subtitle>[^']*)', score: (?P<score>\d+) \}"
)
_SWIFT_QUESTION = re.compile(
    r'RiskQuestion\(id: "(?P<id>[^"]+)", title: "(?P<title>[^"]*)", context: "(?P<context>[^"]*)",'
    r" options: \[(?P<options>.*?)\]\)",
    re.S,
)
_SWIFT_OPTION = re.compile(
    r'RiskOption\(id: "(?P<id>[^"]+)", title: "(?P<title>[^"]*)", subtitle: "(?P<subtitle>[^"]*)", score: (?P<score>\d+)\)'
)

NODE_DRIVER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [modulePath, casesPath] = process.argv.slice(2);
const q = await import(pathToFileURL(modulePath).href);
const cases = JSON.parse(readFileSync(casesPath, 'utf8'));
process.stdout.write(JSON.stringify({
  version: q.RISK_QUESTIONNAIRE_VERSION,
  conservative_max_score: q.CONSERVATIVE_MAX_SCORE,
  moderate_max_score: q.MODERATE_MAX_SCORE,
  questions: q.RISK_QUESTIONS,
  profiles: cases.map((answers) => q.profileForAnswers(answers) ?? 'none'),
}));
"""

SWIFT_STUB = "enum RiskProfile: String { case conservative, moderate, aggressive }\n"
SWIFT_DRIVER = """
import Foundation

let data = try! Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
let cases = try! JSONSerialization.jsonObject(with: data) as! [[String: String]]
let questions: [[String: Any]] = RiskQuestionnaire.questions.map { question in
    [
        "id": question.id,
        "title": question.title,
        "context": question.context,
        "options": question.options.map { option -> [String: Any] in
            ["id": option.id, "title": option.title, "subtitle": option.subtitle, "score": option.score]
        },
    ]
}
let output: [String: Any] = [
    "version": RiskQuestionnaire.version,
    "conservative_max_score": RiskQuestionnaire.conservativeMaxScore,
    "moderate_max_score": RiskQuestionnaire.moderateMaxScore,
    "questions": questions,
    "profiles": cases.map { RiskQuestionnaire.profile(forAnswers: $0)?.rawValue ?? "none" },
]
FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: output))
"""


def _canonical() -> dict:
    return json.loads(CANONICAL.read_text(encoding="utf-8"))


def _answer_sets(spec: dict) -> list[dict[str, str]]:
    """Todas as combinações de respostas, mais um caso vazio e um com opção inexistente."""
    question_ids = [question["id"] for question in spec["questions"]]
    option_ids = [[option["id"] for option in question["options"]] for question in spec["questions"]]
    combos = [dict(zip(question_ids, choice)) for choice in itertools.product(*option_ids)]
    invalid = dict(combos[0])
    invalid[question_ids[0]] = "q1-z"
    return combos + [{}, invalid]


def _expected_profile(spec: dict, answers: dict[str, str]) -> str:
    total = 0
    for question in spec["questions"]:
        option = next((o for o in question["options"] if o["id"] == answers.get(question["id"])), None)
        if option is None:
            return "none"
        total += option["score"]
    scoring = spec["scoring"]
    if total <= scoring["conservative_max_score"]:
        return "conservative"
    if total <= scoring["moderate_max_score"]:
        return "moderate"
    return "aggressive"


def _parse(text: str, question_re: re.Pattern[str], option_re: re.Pattern[str]) -> list[dict]:
    questions = []
    for match in question_re.finditer(text):
        options = [
            {"id": o["id"], "title": o["title"], "subtitle": o["subtitle"], "score": int(o["score"])}
            for o in option_re.finditer(match["options"])
        ]
        questions.append({"id": match["id"], "title": match["title"], "context": match["context"], "options": options})
    return questions


def _number(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    if match is None:
        raise AssertionError(f"padrão ausente: {pattern}")
    return int(match.group(1))


def _run_web(cases_path: Path, workdir: Path) -> dict | None:
    node = shutil.which("node")
    if node is None:
        return None
    driver = workdir / "driver.mjs"
    driver.write_text(NODE_DRIVER, encoding="utf-8")
    for flags in ([], ["--experimental-strip-types"]):
        result = subprocess.run(
            [node, *flags, str(driver), str(WEB_MODULE), str(cases_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    return None


def _run_ios(cases_path: Path, workdir: Path) -> dict | None:
    # Só no macOS, onde o app é compilado; no Linux do CI o teste é pulado e
    # roda no job do iOS (.github/workflows/ci.yml).
    if sys.platform != "darwin" or shutil.which("xcrun") is None:
        return None
    compiler = ["xcrun", "swiftc"]
    (workdir / "stub.swift").write_text(SWIFT_STUB, encoding="utf-8")
    (workdir / "main.swift").write_text(SWIFT_DRIVER, encoding="utf-8")
    binary = workdir / "questionnaire"
    build = subprocess.run(
        [*compiler, "-swift-version", "5", str(IOS_MODULE), "stub.swift", "main.swift", "-o", str(binary)],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build.returncode != 0:
        raise AssertionError(f"RiskQuestionnaire.swift não compilou:\n{build.stderr}")
    result = subprocess.run([str(binary), str(cases_path)], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"o executável Swift falhou:\n{result.stderr}")
    return json.loads(result.stdout)


class QuestionnaireSourceTests(unittest.TestCase):
    """Conferência estática: roda sempre, sem Node nem Swift."""

    def setUp(self) -> None:
        self.spec = _canonical()

    def test_canonico_tem_cinco_perguntas_de_tres_opcoes_de_0_a_2_pontos(self) -> None:
        self.assertEqual(len(self.spec["questions"]), 5)
        for question in self.spec["questions"]:
            self.assertEqual([option["score"] for option in question["options"]], [0, 1, 2])
        self.assertEqual(self.spec["scoring"], {"method": "sum", "conservative_max_score": 3, "moderate_max_score": 7})

    def test_site_e_app_seguem_o_questionario_canonico(self) -> None:
        web = WEB_MODULE.read_text(encoding="utf-8")
        ios = IOS_MODULE.read_text(encoding="utf-8")
        canonical_questions = self.spec["questions"]
        self.assertEqual(_parse(web, _TS_QUESTION, _TS_OPTION), canonical_questions)
        self.assertEqual(_parse(ios, _SWIFT_QUESTION, _SWIFT_OPTION), canonical_questions)
        scoring = self.spec["scoring"]
        self.assertEqual(_number(r"CONSERVATIVE_MAX_SCORE = (\d+);", web), scoring["conservative_max_score"])
        self.assertEqual(_number(r"MODERATE_MAX_SCORE = (\d+);", web), scoring["moderate_max_score"])
        self.assertEqual(_number(r"conservativeMaxScore = (\d+)", ios), scoring["conservative_max_score"])
        self.assertEqual(_number(r"moderateMaxScore = (\d+)", ios), scoring["moderate_max_score"])
        self.assertIn(f"RISK_QUESTIONNAIRE_VERSION = '{self.spec['version']}'", web)
        self.assertIn(f'static let version = "{self.spec["version"]}"', ios)

    def test_telas_usam_o_modulo_compartilhado(self) -> None:
        app = WEB_APP.read_text(encoding="utf-8")
        self.assertIn("const questions = RISK_QUESTIONS;", app)
        self.assertIn("profileForAnswers(answers)", app)
        # A pergunta antiga em que o site pedia o perfil saiu.
        self.assertNotIn("Qual perfil você deseja declarar", app)
        onboarding = IOS_ONBOARDING.read_text(encoding="utf-8")
        self.assertIn("private let questions = RiskQuestionnaire.questions", onboarding)
        self.assertIn("RiskQuestionnaire.profile(forAnswers:", onboarding)
        self.assertNotIn("score <= 3", onboarding)
        self.assertIn("RiskQuestionnaire.swift in Sources", IOS_PROJECT.read_text(encoding="utf-8"))


class QuestionnaireExecutionTests(unittest.TestCase):
    """Dá as mesmas respostas ao código do site e ao do app e compara os perfis."""

    spec: dict
    cases: list[dict[str, str]]
    expected: list[str]
    web: dict | None
    ios: dict | None

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = _canonical()
        cls.cases = _answer_sets(cls.spec)
        cls.expected = [_expected_profile(cls.spec, answers) for answers in cls.cases]
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            cases_path = workdir / "cases.json"
            cases_path.write_text(json.dumps(cls.cases), encoding="utf-8")
            cls.web = _run_web(cases_path, workdir)
            cls.ios = _run_ios(cases_path, workdir)

    def _check_client(self, output: dict | None, name: str) -> None:
        if output is None:
            self.skipTest(f"ferramenta para executar o {name} indisponível")
        self.assertEqual(output["version"], self.spec["version"])
        self.assertEqual(output["conservative_max_score"], self.spec["scoring"]["conservative_max_score"])
        self.assertEqual(output["moderate_max_score"], self.spec["scoring"]["moderate_max_score"])
        self.assertEqual(output["questions"], self.spec["questions"])
        self.assertEqual(output["profiles"], self.expected)

    def test_casos_cobrem_todas_as_combinacoes_e_os_tres_perfis(self) -> None:
        self.assertEqual(len(self.cases), 3**5 + 2)
        self.assertEqual(set(self.expected), {"conservative", "moderate", "aggressive", "none"})

    def test_codigo_do_site_segue_o_canonico(self) -> None:
        self._check_client(self.web, "site (Node)")

    def test_codigo_do_app_segue_o_canonico(self) -> None:
        self._check_client(self.ios, "app (swiftc)")

    def test_mesmas_respostas_dao_o_mesmo_perfil_no_site_e_no_app(self) -> None:
        if self.web is None or self.ios is None:
            self.skipTest("é preciso Node e swiftc para executar as duas versões")
        self.assertEqual(self.web["questions"], self.ios["questions"])
        divergent = [
            (answers, web, ios)
            for answers, web, ios in zip(self.cases, self.web["profiles"], self.ios["profiles"], strict=True)
            if web != ios
        ]
        self.assertEqual(divergent, [])
        # Fronteiras da soma: 3 pontos ainda é conservador; 4, moderado; 8, arrojado.
        points = {o["id"]: o["score"] for q in self.spec["questions"] for o in q["options"]}
        by_score: dict[int, set[str]] = {}
        for answers, profile in zip(self.cases, self.ios["profiles"], strict=True):
            if profile == "none":
                continue
            score = sum(points[option_id] for option_id in answers.values())
            by_score.setdefault(score, set()).add(profile)
        self.assertEqual(by_score[3], {"conservative"})
        self.assertEqual(by_score[4], {"moderate"})
        self.assertEqual(by_score[7], {"moderate"})
        self.assertEqual(by_score[8], {"aggressive"})


if __name__ == "__main__":
    unittest.main()
