"""Registro estruturado de eventos de segurança e de privacidade.

Cada evento vira uma linha JSON no log do servidor, com o instante, o nome do
evento, a gravidade e identificadores técnicos (requisição, correlação, conta).
Código de acesso, tokens, chaves, e-mail em claro e texto de conversa nunca
entram no registro: campos com esses nomes são descartados antes da gravação.

O logger ``aurafi.security`` só escreve no fluxo de saída depois de
``configure()``, chamado pelo processo do servidor; em testes, os eventos
podem ser capturados com ``assertLogs``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import traceback
from typing import Any, Iterator, Mapping

LOGGER_NAME = "aurafi.security"

_FORBIDDEN_FIELDS = frozenset(
    {
        "email",
        "otp",
        "code",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "pepper",
        "api_key",
        "text",
        "message",
        "payload",
        "body",
    }
)
_WARNING_MARKERS = ("failed", "locked", "rejected", "rate_limited", "prohibited")

_bound: ContextVar[Mapping[str, Any]] = ContextVar("aurafi_security_request", default={})

# Sem configure(), os eventos não vão para o console (evita ruído em testes).
logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


def configure(stream: Any = None) -> logging.Logger:
    """Envia os eventos para o fluxo de saída do processo, uma linha JSON por evento."""

    logger = logging.getLogger(LOGGER_NAME)
    if not any(getattr(handler, "_aurafi_security", False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._aurafi_security = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


@contextmanager
def bind(**fields: Any) -> Iterator[None]:
    """Associa campos da requisição atual (rota, origem) aos eventos emitidos nela."""

    token = _bound.set({**_bound.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _bound.reset(token)


def emit(event: str, /, *, severity: str | None = None, **fields: Any) -> None:
    """Grava um evento; falhas de registro nunca interrompem a requisição."""

    level = severity or _severity(event)
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": event,
        "severity": level,
    }
    for key, value in {**_bound.get(), **fields}.items():
        if value is None or key.casefold() in _FORBIDDEN_FIELDS:
            continue
        record[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    try:
        logging.getLogger(LOGGER_NAME).log(
            logging.ERROR if level == "error" else logging.WARNING if level == "warning" else logging.INFO,
            json.dumps(record, ensure_ascii=False),
        )
    except Exception:  # pragma: no cover - registro é best effort
        pass


def exception_fields(error: BaseException) -> dict[str, str]:
    """Tipo da exceção e onde ocorreu, sem a mensagem (que pode conter dados)."""

    frames = traceback.extract_tb(error.__traceback__)
    where = f"{Path(frames[-1].filename).name}:{frames[-1].lineno} in {frames[-1].name}" if frames else "desconhecido"
    return {"error_type": type(error).__name__, "error_at": where}


def reference(value: str) -> str:
    """Referência pseudônima e curta para identificadores que não devem aparecer inteiros."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _severity(event: str) -> str:
    if event.startswith("system.") and event.endswith("error"):
        return "error"
    return "warning" if any(marker in event for marker in _WARNING_MARKERS) else "info"
