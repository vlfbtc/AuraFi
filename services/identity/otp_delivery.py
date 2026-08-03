"""SMTP delivery adapter for identity one-time passwords.

The adapter depends only on the identity delivery port and accepts the SMTP
transport factory as a dependency. Production code can use ``smtplib`` while
tests can provide an in-memory fake without opening a socket.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Callable, Mapping, Protocol

from .service import OtpDeliveryMessage, OtpDeliveryPort


class OtpDeliveryConfigurationError(ValueError):
    """Raised when SMTP configuration is missing, invalid, or unsafe."""


class OtpDeliveryTransportError(RuntimeError):
    """Raised when SMTP cannot deliver an OTP message."""


class SmtpTransport(Protocol):
    """Small portion of the smtplib client used by the adapter."""

    def __enter__(self) -> "SmtpTransport": ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...

    def starttls(self, *, context: ssl.SSLContext) -> Any: ...

    def login(self, user: str, password: str) -> Any: ...

    def send_message(self, message: EmailMessage) -> Any: ...


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise OtpDeliveryConfigurationError(f"Missing required configuration: {name}")
    return value


def _boolean(raw: str | None, *, name: str, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise OtpDeliveryConfigurationError(f"{name} must be a boolean")


def _positive_float(raw: str | None, *, name: str, default: float) -> float:
    try:
        value = default if raw is None or not raw.strip() else float(raw)
    except ValueError as exc:
        raise OtpDeliveryConfigurationError(f"{name} must be positive") from exc
    if value <= 0 or value != value or value == float("inf"):
        raise OtpDeliveryConfigurationError(f"{name} must be positive")
    return value


def _port(raw: str | None) -> int:
    try:
        value = 587 if raw is None or not raw.strip() else int(raw)
    except ValueError as exc:
        raise OtpDeliveryConfigurationError("SMTP port must be an integer") from exc
    if not 1 <= value <= 65535:
        raise OtpDeliveryConfigurationError("SMTP port must be between 1 and 65535")
    return value


def _email_address(value: str, *, name: str) -> str:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise OtpDeliveryConfigurationError(f"{name} must be a valid email address")
    address = parseaddr(value.strip())[1].strip()
    if (
        not address
        or address.count("@") != 1
        or address.startswith("@")
        or address.endswith("@")
        or any(character.isspace() for character in address)
    ):
        raise OtpDeliveryConfigurationError(f"{name} must be a valid email address")
    return address


def _message_body(message: OtpDeliveryMessage) -> str:
    if not isinstance(message.otp, str) or not re.fullmatch(r"[0-9]{6}", message.otp):
        raise OtpDeliveryConfigurationError("OTP must contain exactly six digits")
    return (
        "Seu código de acesso AuraFi é: "
        f"{message.otp}\n\n"
        "Não compartilhe este código. Se você não solicitou este acesso, "
        "ignore esta mensagem."
    )


@dataclass(frozen=True, slots=True)
class SmtpOtpDeliveryConfig:
    """Explicit, validated settings for one SMTP delivery adapter."""

    host: str
    from_email: str
    port: int = 587
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    starttls: bool = True
    ssl: bool = False
    timeout: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise OtpDeliveryConfigurationError("SMTP host is required")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise OtpDeliveryConfigurationError("SMTP port must be an integer")
        if not 1 <= self.port <= 65535:
            raise OtpDeliveryConfigurationError("SMTP port must be between 1 and 65535")
        _email_address(self.from_email, name="SMTP from email")
        if not isinstance(self.starttls, bool) or not isinstance(self.ssl, bool):
            raise OtpDeliveryConfigurationError("SMTP TLS settings must be boolean")
        if self.starttls and self.ssl:
            raise OtpDeliveryConfigurationError("SMTP STARTTLS and SSL are mutually exclusive")
        if not self.starttls and not self.ssl:
            raise OtpDeliveryConfigurationError("SMTP delivery requires STARTTLS or SSL")
        if self.username is not None and (
            not isinstance(self.username, str) or not self.username.strip()
        ):
            raise OtpDeliveryConfigurationError("SMTP username cannot be empty")
        if self.password is not None and (
            not isinstance(self.password, str) or not self.password.strip()
        ):
            raise OtpDeliveryConfigurationError("SMTP password cannot be empty")
        if (self.username is None) != (self.password is None):
            raise OtpDeliveryConfigurationError(
                "SMTP username and password must be provided together"
            )
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool):
            raise OtpDeliveryConfigurationError("SMTP timeout must be positive")
        if self.timeout <= 0 or self.timeout != self.timeout or self.timeout == float("inf"):
            raise OtpDeliveryConfigurationError("SMTP timeout must be positive")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SmtpOtpDeliveryConfig":
        """Build settings from environment, rejecting incomplete configuration."""

        values = os.environ if env is None else env
        username = values.get("AURAFI_OTP_SMTP_USERNAME") or None
        password = values.get("AURAFI_OTP_SMTP_PASSWORD") or None
        return cls(
            host=_required(values, "AURAFI_OTP_SMTP_HOST"),
            from_email=_required(values, "AURAFI_OTP_FROM_EMAIL"),
            port=_port(values.get("AURAFI_OTP_SMTP_PORT")),
            username=username,
            password=password,
            starttls=_boolean(
                values.get("AURAFI_OTP_SMTP_STARTTLS"),
                name="AURAFI_OTP_SMTP_STARTTLS",
                default=True,
            ),
            ssl=_boolean(
                values.get("AURAFI_OTP_SMTP_SSL"),
                name="AURAFI_OTP_SMTP_SSL",
                default=False,
            ),
            timeout=_positive_float(
                values.get("AURAFI_OTP_SMTP_TIMEOUT"),
                name="AURAFI_OTP_SMTP_TIMEOUT",
                default=10.0,
            ),
        )


class SmtpOtpDelivery(OtpDeliveryPort):
    """Deliver ``OtpDeliveryMessage`` through an injectable SMTP transport."""

    def __init__(
        self,
        config: SmtpOtpDeliveryConfig,
        *,
        smtp_factory: Callable[..., SmtpTransport] | None = None,
    ) -> None:
        self.config = config
        self._smtp_factory = smtp_factory or (smtplib.SMTP_SSL if config.ssl else smtplib.SMTP)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        smtp_factory: Callable[..., SmtpTransport] | None = None,
    ) -> "SmtpOtpDelivery":
        return cls(SmtpOtpDeliveryConfig.from_env(env), smtp_factory=smtp_factory)

    def deliver(self, message: OtpDeliveryMessage) -> None:
        recipient = _email_address(message.email, name="OTP recipient")
        email = EmailMessage()
        email["From"] = self.config.from_email
        email["To"] = recipient
        email["Subject"] = "Seu código de acesso AuraFi"
        email.set_content(_message_body(message))

        try:
            with self._smtp_factory(
                self.config.host,
                self.config.port,
                timeout=self.config.timeout,
            ) as client:
                if self.config.starttls:
                    client.starttls(context=ssl.create_default_context())
                if self.config.username is not None and self.config.password is not None:
                    client.login(self.config.username, self.config.password)
                client.send_message(email)
        except (OSError, smtplib.SMTPException):
            # Keep transport errors deliberately generic: SMTP exceptions must
            # never place credentials or OTP contents in application logs.
            raise OtpDeliveryTransportError("SMTP OTP delivery failed") from None


SmtpOtpDeliveryAdapter = SmtpOtpDelivery


__all__ = [
    "OtpDeliveryConfigurationError",
    "OtpDeliveryTransportError",
    "SmtpOtpDelivery",
    "SmtpOtpDeliveryAdapter",
    "SmtpOtpDeliveryConfig",
    "SmtpTransport",
]
