"""Adaptador HTTP mínimo para o Anthropic Messages API.

O adaptador ignora identificadores internos presentes em ``LlmRequest`` e envia
somente o texto necessário. Recomendações, simulações e regras de risco continuam
nos serviços determinísticos do domínio; este provider atende apenas conversa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .service import LlmRequest, LlmResult, PROMPT_VERSION
from .redaction import redact_text


DEFAULT_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """Você é a Aura, assistente educativa da AuraFi.
Responda em português brasileiro, com linguagem direta e sem prometer retorno.
Você não movimenta recursos, não executa transações, não solicita seed phrase,
chave privada, token ou senha e não substitui aconselhamento profissional.
Não invente APY, TVL, auditoria, risco, saldo ou resultado de simulação. Quando
faltarem dados verificáveis, diga isso claramente. Recomendações e simulações são
produzidas por serviços determinísticos separados, nunca por esta conversa."""


def _system_prompt(request: LlmRequest) -> str:
    """Prompt de sistema com os dados de mercado observados quando disponíveis."""
    grounding = getattr(request, "grounding", "") or ""
    grounding = grounding.strip()
    if not grounding:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n{grounding[:6_000]}"


def _conversation_messages(request: LlmRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in request.context[-12:]:
        role = str(item.get("role", "")).casefold()
        if role not in {"user", "assistant"}:
            continue
        text = redact_text(item.get("text", ""), max_length=4_000).text
        if not text:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] = (
                messages[-1]["content"] + "\n" + text
            )[:8_000]
        else:
            messages.append({"role": role, "content": text})
    current = redact_text(request.text, max_length=4_000).text
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] = (
            messages[-1]["content"] + "\n" + current
        )[:8_000]
    else:
        messages.append({"role": "user", "content": current})
    return messages


class AnthropicConfigurationError(ValueError):
    """Configuração ausente ou insegura do provider."""


class AnthropicTransportError(RuntimeError):
    """Falha genérica que não inclui chave, prompt ou corpo da resposta."""


class JsonPostPort(Protocol):
    def __call__(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> Mapping[str, Any]: ...


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise AnthropicConfigurationError(f"Missing required configuration: {name}")
    return value


def _positive_float(value: str | None, *, name: str, default: float) -> float:
    try:
        parsed = default if value is None or not value.strip() else float(value)
    except ValueError as exc:
        raise AnthropicConfigurationError(f"{name} must be positive") from exc
    if parsed <= 0 or parsed != parsed or parsed == float("inf"):
        raise AnthropicConfigurationError(f"{name} must be positive")
    return parsed


def _positive_int(value: str | None, *, name: str, default: int) -> int:
    try:
        parsed = default if value is None or not value.strip() else int(value)
    except ValueError as exc:
        raise AnthropicConfigurationError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise AnthropicConfigurationError(f"{name} must be a positive integer")
    return parsed


def _validate_messages_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "api.anthropic.com":
        raise AnthropicConfigurationError(
            "Anthropic endpoint must use HTTPS on api.anthropic.com"
        )
    if parsed.path.rstrip("/") != "/v1/messages" or parsed.query or parsed.fragment:
        raise AnthropicConfigurationError("Anthropic endpoint must be /v1/messages")
    return value


@dataclass(frozen=True, slots=True)
class AnthropicConfig:
    api_key: str = field(repr=False)
    model: str = DEFAULT_ANTHROPIC_MODEL
    messages_url: str = DEFAULT_ANTHROPIC_MESSAGES_URL
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    max_tokens: int = 700
    timeout_seconds: float = 20.0
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise AnthropicConfigurationError("Anthropic API key is required")
        if not self.model.strip() or not self.anthropic_version.strip():
            raise AnthropicConfigurationError("Anthropic model and version are required")
        _validate_messages_url(self.messages_url)
        if self.max_tokens <= 0 or self.max_response_bytes <= 0 or self.timeout_seconds <= 0:
            raise AnthropicConfigurationError("Anthropic limits must be positive")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AnthropicConfig":
        values = os.environ if env is None else env
        return cls(
            api_key=_required(values, "AURAFI_ANTHROPIC_API_KEY"),
            model=values.get("AURAFI_ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL).strip(),
            messages_url=values.get(
                "AURAFI_ANTHROPIC_MESSAGES_URL", DEFAULT_ANTHROPIC_MESSAGES_URL
            ).strip(),
            anthropic_version=values.get(
                "AURAFI_ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION
            ).strip(),
            max_tokens=_positive_int(
                values.get("AURAFI_ANTHROPIC_MAX_TOKENS"),
                name="AURAFI_ANTHROPIC_MAX_TOKENS",
                default=700,
            ),
            timeout_seconds=_positive_float(
                values.get("AURAFI_ANTHROPIC_TIMEOUT"),
                name="AURAFI_ANTHROPIC_TIMEOUT",
                default=20.0,
            ),
            max_response_bytes=_positive_int(
                values.get("AURAFI_ANTHROPIC_MAX_RESPONSE_BYTES"),
                name="AURAFI_ANTHROPIC_MAX_RESPONSE_BYTES",
                default=1_048_576,
            ),
        )


def _post_json(
    url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
    max_response_bytes: int,
) -> Mapping[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise AnthropicTransportError("Anthropic returned an invalid content type")
            raw = response.read(max_response_bytes + 1)
            if len(raw) > max_response_bytes:
                raise AnthropicTransportError("Anthropic response exceeded the configured limit")
    except (HTTPError, URLError, OSError, TimeoutError):
        raise AnthropicTransportError("Anthropic request failed") from None
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AnthropicTransportError("Anthropic returned invalid JSON") from None
    if not isinstance(decoded, Mapping):
        raise AnthropicTransportError("Anthropic returned an invalid response")
    return decoded


class AnthropicLlm:
    """Provider Claude real para a porta síncrona do hub conversacional."""

    def __init__(
        self,
        config: AnthropicConfig,
        *,
        post_json: JsonPostPort | None = None,
    ) -> None:
        self.config = config
        self._post_json = post_json or _post_json

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        post_json: JsonPostPort | None = None,
    ) -> "AnthropicLlm":
        return cls(AnthropicConfig.from_env(env), post_json=post_json)

    def complete(self, request: LlmRequest) -> LlmResult:
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": _system_prompt(request),
            "messages": _conversation_messages(request),
        }
        if self.config.model == "claude-sonnet-5":
            payload["thinking"] = {"type": "disabled"}
        response = self._post_json(
            self.config.messages_url,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "x-api-key": self.config.api_key,
                "anthropic-version": self.config.anthropic_version,
                "user-agent": "AuraFi/1.0",
            },
            payload=payload,
            timeout_seconds=self.config.timeout_seconds,
            max_response_bytes=self.config.max_response_bytes,
        )
        content = response.get("content")
        if not isinstance(content, list):
            raise AnthropicTransportError("Anthropic response has no content")
        text_parts = [
            item.get("text", "").strip()
            for item in content
            if isinstance(item, Mapping) and item.get("type") == "text"
        ]
        text = "\n".join(part for part in text_parts if part).strip()
        if not text:
            raise AnthropicTransportError("Anthropic response has no text")
        return LlmResult(
            text=text,
            mode="provider",
            provider="claude",
            model=str(response.get("model") or self.config.model),
            prompt_version=PROMPT_VERSION,
            explanation=("Resposta conversacional gerada pelo provider configurado.",),
            structured=False,
        )


__all__ = [
    "AnthropicConfig",
    "AnthropicConfigurationError",
    "AnthropicLlm",
    "AnthropicTransportError",
    "DEFAULT_ANTHROPIC_MESSAGES_URL",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_ANTHROPIC_VERSION",
]
