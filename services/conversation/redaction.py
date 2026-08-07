"""Sanitização central de texto conversacional sem reter o valor removido."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Pattern


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    applied: bool
    categories: tuple[str, ...] = ()


_PatternReplacement = tuple[str, Pattern[str], str]

_PATTERNS: tuple[_PatternReplacement, ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
            r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "[chave privada removida]",
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
            r"[A-Za-z0-9_-]{8,}\b"
        ),
        "[token removido]",
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
        "Bearer [token removido]",
    ),
    (
        "seed_phrase",
        re.compile(
            r"\b(seed phrase|mnemonic(?: phrase)?|frase (?:semente|de recuperação)|"
            r"palavras? de recuperação)\b\s*(?:é|e|:|=|-)?\s*"
            r"(?:[A-Za-zÀ-ÖØ-öø-ÿ]+[\s,;]+){5,23}[A-Za-zÀ-ÖØ-öø-ÿ]+",
            re.IGNORECASE,
        ),
        r"\1 [segredo removido]",
    ),
    (
        "api_secret",
        re.compile(
            r"\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|"
            r"private[_ -]?key|senha|password|token)\b\s*[:=]\s*"
            r"[\"']?[A-Za-z0-9._~+/=-]{6,}[\"']?",
            re.IGNORECASE,
        ),
        r"\1=[segredo removido]",
    ),
    (
        "api_key",
        re.compile(
            r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{8,}|re_[A-Za-z0-9_-]{12,}|"
            r"(?:gh[oprsu]|xox[baprs])_[A-Za-z0-9_-]{12,}|"
            r"AKIA[A-Z0-9]{16})\b",
            re.IGNORECASE,
        ),
        "[chave de API removida]",
    ),
    (
        "private_key",
        re.compile(r"\b(?:0x)?[a-fA-F0-9]{64}\b"),
        "[chave privada removida]",
    ),
    (
        "email",
        re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", re.IGNORECASE),
        "[email removido]",
    ),
    (
        "wallet",
        re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
        "[endereço removido]",
    ),
    (
        "cpf",
        re.compile(r"(?<!\d)(?:\d{3}[.\s-]?){3}\d{2}(?!\d)"),
        "[CPF removido]",
    ),
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)"
            r"(?:9\d{4}|\d{4})[\s.-]?\d{4}(?!\d)"
        ),
        "[telefone removido]",
    ),
    (
        "otp",
        re.compile(r"(?<!\d)\d{6}(?!\d)"),
        "[segredo removido]",
    ),
)


def redact_text(value: Any, *, max_length: int | None = None) -> RedactionResult:
    """Retorna somente texto sanitizado e categorias, nunca os valores removidos."""

    text = str(value).strip()
    if max_length is not None:
        text = text[:max_length]
    categories: list[str] = []
    for category, pattern, replacement in _PATTERNS:
        text, count = pattern.subn(replacement, text)
        if count and category not in categories:
            categories.append(category)
    return RedactionResult(text=text, applied=bool(categories), categories=tuple(categories))
