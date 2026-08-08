"""Domínio puro para conta interna, OTP e sessão do AuraFi.

O módulo não conhece HTTP, PostgreSQL ou um provedor de e-mail. Os protocolos
definidos aqui são as portas que os adaptadores de entrada e infraestrutura
devem implementar.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Literal, Protocol


ChannelName = Literal["web_widget", "ios_app", "simulated"]
DeliveryMode = Literal["email", "mock"]
SessionStatus = Literal["active", "expired", "revoked", "closed"]
ChallengeStatus = Literal["pending", "verified", "expired", "cancelled"]

SUPPORTED_CHANNELS: frozenset[str] = frozenset({"web_widget", "ios_app", "simulated"})
DEFAULT_OTP_TTL = timedelta(minutes=5)
DEFAULT_SESSION_TTL = timedelta(minutes=30)
DEFAULT_MAX_OTP_ATTEMPTS = 5
AUTHENTICATION_FAILURE_MESSAGE = "Não foi possível validar o código informado."
AUTHENTICATION_FAILURE_CODE = "AUTHENTICATION_FAILED"
AUTH_DISCLAIMER = (
    "A AuraFi oferece apoio à decisão e não garante retorno, execução ou movimentação de fundos."
)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def utc_now() -> datetime:
    """Retorna um instante UTC consciente de timezone."""

    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def normalize_email(email: str) -> str:
    """Normaliza e valida o único identificador canônico aceito pela identidade."""

    if not isinstance(email, str):
        raise ValueError("Email must be a string")
    normalized = email.strip().casefold()
    if len(normalized) > 320 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid email")
    return normalized


def _safe_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Metadados de correlação propagados entre adaptadores."""

    request_id: str
    correlation_id: str
    generated_at: datetime

    @classmethod
    def create(
        cls,
        request_id: str | None = None,
        correlation_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> "RequestContext":
        return cls(
            request_id=_trace_id(request_id, "req"),
            correlation_id=_trace_id(correlation_id, "cor"),
            generated_at=_as_utc(now or utc_now()),
        )


def _trace_id(value: str | None, prefix: str) -> str:
    if value is None or not value.strip():
        return _safe_id(prefix)
    normalized = value.strip()
    if len(normalized) > 128:
        raise ValueError("Trace identifiers must have at most 128 characters")
    return normalized


@dataclass(frozen=True, slots=True)
class ApiMeta:
    request_id: str
    correlation_id: str
    generated_at: datetime
    disclaimer: str = AUTH_DISCLAIMER

    @classmethod
    def from_context(cls, context: RequestContext) -> "ApiMeta":
        return cls(
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            generated_at=context.generated_at,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "generated_at": self.generated_at.isoformat(),
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True, slots=True)
class ChannelContext:
    """Canal lógico aprovado; nunca é uma identidade canônica."""

    name: ChannelName
    adapter: str
    external_message_id: str | None = None
    simulated: bool = False

    def __post_init__(self) -> None:
        if self.name not in SUPPORTED_CHANNELS:
            raise UnsupportedChannelError()
        if not self.adapter or len(self.adapter.strip()) > 128:
            raise ValueError("Channel adapter must be non-empty and short")
        if self.name == "simulated" and not self.simulated:
            object.__setattr__(self, "simulated", True)
        if self.name != "simulated" and self.simulated:
            raise UnsupportedChannelError("Simulated mode is only valid for the simulated channel")

    @classmethod
    def from_value(
        cls,
        value: "ChannelContext | ChannelName | str",
        *,
        adapter: str | None = None,
        external_message_id: str | None = None,
    ) -> "ChannelContext":
        if isinstance(value, cls):
            return value
        if value not in SUPPORTED_CHANNELS:
            raise UnsupportedChannelError()
        default_adapters: dict[str, str] = {
            "web_widget": "web-widget",
            "ios_app": "ios-app",
            "simulated": "simulated",
        }
        return cls(
            name=value,  # type: ignore[arg-type]
            adapter=adapter or default_adapters[value],
            external_message_id=external_message_id,
            simulated=value == "simulated",
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "name": self.name,
            "adapter": self.adapter,
            "simulated": self.simulated,
        }
        if self.external_message_id is not None:
            result["external_message_id"] = self.external_message_id
        return result


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    email: str
    email_verified: bool = False
    created_at: datetime = field(default_factory=utc_now)
    subject_type: Literal["account"] = "account"

    def __post_init__(self) -> None:
        if not self.account_id or len(self.account_id) > 128:
            raise ValueError("Account id must be non-empty and short")
        object.__setattr__(self, "email", normalize_email(self.email))
        object.__setattr__(self, "created_at", _as_utc(self.created_at))

    def to_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "email": self.email,
            "email_verified": self.email_verified,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OtpChallenge:
    challenge_id: str
    email: str
    channel: ChannelContext
    delivery: DeliveryMode
    otp_digest: str
    expires_at: datetime
    created_at: datetime
    account_id: str | None = None
    status: ChallengeStatus = "pending"
    attempts: int = 0
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalize_email(self.email))
        object.__setattr__(self, "created_at", _as_utc(self.created_at))
        object.__setattr__(self, "expires_at", _as_utc(self.expires_at))
        if self.expires_at <= self.created_at:
            raise ValueError("OTP expiration must be after creation")
        if self.delivery not in {"email", "mock"}:
            raise ValueError("Unsupported OTP delivery mode")


@dataclass(frozen=True, slots=True)
class ChannelAssociation:
    channel_identity_id: str
    account_id: str
    channel: ChannelContext
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", _as_utc(self.created_at))

    def to_identity_dict(self, *, email_verified: bool) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "subject_type": "account",
            "email_verified": email_verified,
            "channel_identity_id": self.channel_identity_id,
        }


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    account_id: str
    started_at: datetime
    expires_at: datetime
    access_token_digest: str
    refresh_token_digest: str
    status: SessionStatus = "active"
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", _as_utc(self.started_at))
        object.__setattr__(self, "expires_at", _as_utc(self.expires_at))
        if self.expires_at <= self.started_at:
            raise ValueError("Session expiration must be after start")


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    account: Account
    token_type: Literal["Bearer"] = "Bearer"

    def to_dict(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at.isoformat(),
            "account": self.account.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OtpRequestResult:
    challenge_id: str
    expires_at: datetime
    delivery: DeliveryMode
    meta: ApiMeta

    def to_dict(self) -> dict[str, object]:
        return {
            "challenge_id": self.challenge_id,
            "expires_at": self.expires_at.isoformat(),
            "delivery": self.delivery,
            "meta": self.meta.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    session: SessionGrant
    identity: dict[str, object]
    channel: ChannelContext
    meta: ApiMeta

    def to_dict(self) -> dict[str, object]:
        return {"session": self.session.to_dict(), "meta": self.meta.to_dict()}


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    account: Account
    session: SessionRecord
    channel_association: ChannelAssociation | None
    meta: ApiMeta

    @property
    def identity(self) -> dict[str, object]:
        if self.channel_association is None:
            return {
                "account_id": self.account.account_id,
                "subject_type": "account",
                "email_verified": self.account.email_verified,
            }
        return self.channel_association.to_identity_dict(
            email_verified=self.account.email_verified
        )


class IdentityServiceError(Exception):
    """Erro seguro para o adaptador HTTP mapear para ErrorResponse."""

    code = "IDENTITY_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable

    def to_error(self, meta: ApiMeta) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            },
            "meta": meta.to_dict(),
        }


class AuthenticationError(IdentityServiceError):
    """Falha indistinguível para OTP inválido, expirado, reutilizado ou órfão."""

    code = AUTHENTICATION_FAILURE_CODE
    retryable = True

    def __init__(self) -> None:
        super().__init__(
            AUTHENTICATION_FAILURE_MESSAGE,
            code=self.code,
            retryable=self.retryable,
        )


class UnsupportedChannelError(IdentityServiceError):
    code = "CHANNEL_NOT_ALLOWED"

    def __init__(self, message: str = "Canal não permitido para o MVP.") -> None:
        super().__init__(message, code=self.code, retryable=False)


class DeliveryError(IdentityServiceError):
    code = "OTP_DELIVERY_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(
            "Não foi possível processar a solicitação neste momento.",
            code=self.code,
            retryable=True,
        )


class AccountRepository(Protocol):
    def create(self, account: Account) -> Account: ...

    def find_by_email(self, email: str) -> Account | None: ...

    def get(self, account_id: str) -> Account | None: ...

    def mark_email_verified(self, account_id: str, verified_at: datetime) -> Account | None: ...


class OtpChallengeRepository(Protocol):
    def save(self, challenge: OtpChallenge) -> None: ...

    def get(self, challenge_id: str) -> OtpChallenge | None: ...

    def update(self, challenge: OtpChallenge) -> None: ...


class SessionRepository(Protocol):
    def save(self, session: SessionRecord) -> None: ...

    def get_by_access_token_digest(self, digest: str) -> SessionRecord | None: ...

    def get_by_refresh_token_digest(self, digest: str) -> SessionRecord | None: ...

    def get(self, session_id: str) -> SessionRecord | None: ...

    def update(self, session: SessionRecord) -> None: ...


class ChannelIdentityRepository(Protocol):
    def save(self, association: ChannelAssociation) -> None: ...

    def get(self, channel_identity_id: str) -> ChannelAssociation | None: ...

    def find(self, account_id: str, channel: ChannelContext) -> ChannelAssociation | None: ...

    def first_for_account(self, account_id: str) -> ChannelAssociation | None: ...


@dataclass(frozen=True, slots=True)
class OtpDeliveryMessage:
    challenge_id: str
    email: str
    otp: str
    channel: ChannelContext
    correlation_id: str


class OtpDeliveryPort(Protocol):
    """Porta para entrega; o adaptador real não deve registrar o OTP."""

    def deliver(self, message: OtpDeliveryMessage) -> None: ...


class OtpGenerator(Protocol):
    def generate(self) -> str: ...


class TokenGenerator(Protocol):
    def generate(self) -> str: ...


class OtpHasher(Protocol):
    def digest(self, otp: str) -> str: ...

    def matches(self, otp: str, digest: str) -> bool: ...


class TokenHasher(Protocol):
    def digest(self, token: str) -> str: ...


class SecureOtpGenerator:
    def generate(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"


class SecureTokenGenerator:
    def generate(self) -> str:
        return secrets.token_urlsafe(32)


class HmacOtpHasher:
    """Hash de OTP com pepper injetável e comparação em tempo constante."""

    def __init__(self, pepper: bytes | None = None) -> None:
        self._pepper = pepper or secrets.token_bytes(32)

    def digest(self, otp: str) -> str:
        return hmac.new(self._pepper, otp.encode("ascii"), hashlib.sha256).hexdigest()

    def matches(self, otp: str, digest: str) -> bool:
        candidate = self.digest(otp)
        return hmac.compare_digest(candidate, digest)


class Sha256TokenHasher:
    def digest(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InMemoryAccountRepository:
    """Adaptador de memória para contas previamente conhecidas."""

    def __init__(self, accounts: Iterable[Account] = ()) -> None:
        self._accounts: dict[str, Account] = {}
        self._email_index: dict[str, str] = {}
        self._lock = threading.RLock()
        for account in accounts:
            self.add(account)

    def add(self, account: Account) -> None:
        with self._lock:
            if account.account_id in self._accounts:
                raise ValueError("Account id already exists")
            if account.email in self._email_index:
                raise ValueError("Email already exists")
            self._accounts[account.account_id] = account
            self._email_index[account.email] = account.account_id

    def create(self, account: Account) -> Account:
        self.add(account)
        return account

    def find_by_email(self, email: str) -> Account | None:
        normalized = normalize_email(email)
        with self._lock:
            account_id = self._email_index.get(normalized)
            return self._accounts.get(account_id) if account_id else None

    def get(self, account_id: str) -> Account | None:
        with self._lock:
            return self._accounts.get(account_id)

    def mark_email_verified(self, account_id: str, verified_at: datetime) -> Account | None:
        del verified_at
        with self._lock:
            current = self._accounts.get(account_id)
            if current is None:
                return None
            updated = replace(current, email_verified=True)
            self._accounts[account_id] = updated
            return updated


class InMemoryOtpChallengeRepository:
    def __init__(self) -> None:
        self._challenges: dict[str, OtpChallenge] = {}
        self._lock = threading.RLock()

    def save(self, challenge: OtpChallenge) -> None:
        with self._lock:
            if challenge.challenge_id in self._challenges:
                raise ValueError("Challenge id already exists")
            self._challenges[challenge.challenge_id] = challenge

    def get(self, challenge_id: str) -> OtpChallenge | None:
        with self._lock:
            return self._challenges.get(challenge_id)

    def update(self, challenge: OtpChallenge) -> None:
        with self._lock:
            if challenge.challenge_id not in self._challenges:
                raise KeyError(challenge.challenge_id)
            self._challenges[challenge.challenge_id] = challenge


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._access_index: dict[str, str] = {}
        self._refresh_index: dict[str, str] = {}
        self._lock = threading.RLock()

    def save(self, session: SessionRecord) -> None:
        with self._lock:
            if session.session_id in self._sessions:
                raise ValueError("Session id already exists")
            self._sessions[session.session_id] = session
            self._access_index[session.access_token_digest] = session.session_id
            self._refresh_index[session.refresh_token_digest] = session.session_id

    def get_by_access_token_digest(self, digest: str) -> SessionRecord | None:
        with self._lock:
            session_id = self._access_index.get(digest)
            return self._sessions.get(session_id) if session_id else None

    def get_by_refresh_token_digest(self, digest: str) -> SessionRecord | None:
        with self._lock:
            session_id = self._refresh_index.get(digest)
            return self._sessions.get(session_id) if session_id else None

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def update(self, session: SessionRecord) -> None:
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is None:
                raise KeyError(session.session_id)
            if current.access_token_digest != session.access_token_digest:
                self._access_index.pop(current.access_token_digest, None)
                self._access_index[session.access_token_digest] = session.session_id
            if current.refresh_token_digest != session.refresh_token_digest:
                self._refresh_index.pop(current.refresh_token_digest, None)
                self._refresh_index[session.refresh_token_digest] = session.session_id
            self._sessions[session.session_id] = session


class InMemoryChannelIdentityRepository:
    def __init__(self) -> None:
        self._associations: dict[str, ChannelAssociation] = {}
        self._key_index: dict[tuple[str, str, str], str] = {}
        self._lock = threading.RLock()

    def save(self, association: ChannelAssociation) -> None:
        key = (association.account_id, association.channel.name, association.channel.adapter)
        with self._lock:
            existing_id = self._key_index.get(key)
            if existing_id is not None and existing_id != association.channel_identity_id:
                raise ValueError("Channel association already exists")
            self._associations[association.channel_identity_id] = association
            self._key_index[key] = association.channel_identity_id

    def get(self, channel_identity_id: str) -> ChannelAssociation | None:
        with self._lock:
            return self._associations.get(channel_identity_id)

    def find(self, account_id: str, channel: ChannelContext) -> ChannelAssociation | None:
        with self._lock:
            association_id = self._key_index.get((account_id, channel.name, channel.adapter))
            return self._associations.get(association_id) if association_id else None

    def first_for_account(self, account_id: str) -> ChannelAssociation | None:
        with self._lock:
            matches = [
                association
                for association in self._associations.values()
                if association.account_id == account_id
            ]
            return min(
                matches,
                key=lambda item: (item.created_at, item.channel_identity_id),
                default=None,
            )


class InMemoryOtpSink:
    """Sink explícito para testes; só captura o segredo quando solicitado.

    Em modo padrão, a entrega guarda apenas metadados. Para um teste de fluxo
    que precise ler o OTP, use ``InMemoryOtpSink(capture_secrets=True)`` de forma
    consciente e isolada. Nenhum resultado do serviço expõe o valor.
    """

    def __init__(self, *, capture_secrets: bool = False) -> None:
        self.capture_secrets = capture_secrets
        self.deliveries: list[OtpDeliveryMessage] = []

    def deliver(self, message: OtpDeliveryMessage) -> None:
        if self.capture_secrets:
            self.deliveries.append(message)
        else:
            self.deliveries.append(replace(message, otp="[redacted]"))

    def code_for(self, challenge_id: str) -> str | None:
        for delivery in reversed(self.deliveries):
            if delivery.challenge_id == challenge_id:
                return delivery.otp if self.capture_secrets else None
        return None


class IdentityService:
    """Casos de uso de autenticação interna e resolução segura de canal."""

    def __init__(
        self,
        *,
        accounts: AccountRepository,
        challenges: OtpChallengeRepository,
        sessions: SessionRepository,
        channel_identities: ChannelIdentityRepository,
        otp_delivery: OtpDeliveryPort,
        delivery_mode: DeliveryMode = "mock",
        clock: Callable[[], datetime] = utc_now,
        otp_generator: OtpGenerator | None = None,
        otp_hasher: OtpHasher | None = None,
        token_generator: TokenGenerator | None = None,
        token_hasher: TokenHasher | None = None,
        id_generator: Callable[[str], str] = _safe_id,
        otp_ttl: timedelta = DEFAULT_OTP_TTL,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        max_otp_attempts: int = DEFAULT_MAX_OTP_ATTEMPTS,
        allow_self_signup: bool = False,
    ) -> None:
        if delivery_mode not in {"email", "mock"}:
            raise ValueError("Unsupported OTP delivery mode")
        if otp_ttl <= timedelta(0) or session_ttl <= timedelta(0):
            raise ValueError("Expiration durations must be positive")
        if max_otp_attempts < 1:
            raise ValueError("max_otp_attempts must be positive")
        self._accounts = accounts
        self._challenges = challenges
        self._sessions = sessions
        self._channel_identities = channel_identities
        self._otp_delivery = otp_delivery
        self._delivery_mode = delivery_mode
        self._clock = clock
        self._otp_generator = otp_generator or SecureOtpGenerator()
        self._otp_hasher = otp_hasher or HmacOtpHasher()
        self._token_generator = token_generator or SecureTokenGenerator()
        self._token_hasher = token_hasher or Sha256TokenHasher()
        self._id_generator = id_generator
        self._otp_ttl = otp_ttl
        self._session_ttl = session_ttl
        self._max_otp_attempts = max_otp_attempts
        self._allow_self_signup = allow_self_signup
        self._verification_lock = threading.RLock()

    def request_otp(
        self,
        email: str,
        channel: ChannelContext | ChannelName | str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> OtpRequestResult:
        context = RequestContext.create(request_id, correlation_id, now=self._now())
        normalized_email = normalize_email(email)
        channel_context = ChannelContext.from_value(channel)
        account = self._accounts.find_by_email(normalized_email)
        if account is None and self._allow_self_signup:
            account = self._accounts.create(
                Account(account_id=self._id_generator("acc"), email=normalized_email)
            )
        now = context.generated_at
        challenge_id = self._id_generator("chl")
        otp = self._otp_generator.generate()
        if not re.fullmatch(r"[0-9]{6}", otp):
            raise ValueError("OTP generator must return exactly six digits")
        challenge = OtpChallenge(
            challenge_id=challenge_id,
            email=normalized_email,
            channel=channel_context,
            delivery=self._delivery_mode,
            otp_digest=self._otp_hasher.digest(otp),
            expires_at=now + self._otp_ttl,
            created_at=now,
            account_id=account.account_id if account else None,
        )
        self._challenges.save(challenge)

        if account is not None:
            try:
                self._otp_delivery.deliver(
                    OtpDeliveryMessage(
                        challenge_id=challenge_id,
                        email=normalized_email,
                        otp=otp,
                        channel=channel_context,
                        correlation_id=context.correlation_id,
                    )
                )
            except Exception as exc:  # pragma: no cover - adapter-specific failure
                raise DeliveryError() from exc
        return OtpRequestResult(
            challenge_id=challenge_id,
            expires_at=challenge.expires_at,
            delivery=self._delivery_mode,
            meta=ApiMeta.from_context(context),
        )

    def verify_otp(
        self,
        challenge_id: str,
        otp: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        channel: ChannelContext | ChannelName | str | None = None,
    ) -> AuthenticationResult:
        with self._verification_lock:
            return self._verify_otp(
                challenge_id,
                otp,
                request_id=request_id,
                correlation_id=correlation_id,
                channel=channel,
            )

    def _verify_otp(
        self,
        challenge_id: str,
        otp: str,
        *,
        request_id: str | None,
        correlation_id: str | None,
        channel: ChannelContext | ChannelName | str | None,
    ) -> AuthenticationResult:
        context = RequestContext.create(request_id, correlation_id, now=self._now())
        challenge = self._challenges.get(challenge_id)
        candidate_otp = otp if isinstance(otp, str) else ""
        digest = challenge.otp_digest if challenge is not None else self._otp_hasher.digest("000000")
        matches = bool(re.fullmatch(r"[0-9]{6}", candidate_otp)) and self._otp_hasher.matches(
            candidate_otp if re.fullmatch(r"[0-9]{6}", candidate_otp) else "000000", digest
        )
        now = context.generated_at
        if challenge is None or challenge.status != "pending":
            raise AuthenticationError()
        if now >= challenge.expires_at:
            self._challenges.update(replace(challenge, status="expired"))
            raise AuthenticationError()
        if challenge.attempts >= self._max_otp_attempts:
            self._challenges.update(replace(challenge, status="cancelled"))
            raise AuthenticationError()
        if not matches:
            next_attempts = challenge.attempts + 1
            status: ChallengeStatus = "cancelled" if next_attempts >= self._max_otp_attempts else "pending"
            self._challenges.update(replace(challenge, attempts=next_attempts, status=status))
            raise AuthenticationError()

        account = self._accounts.get(challenge.account_id) if challenge.account_id else None
        if account is None or account.email != challenge.email:
            self._challenges.update(replace(challenge, status="cancelled"))
            raise AuthenticationError()

        consumed = replace(challenge, status="verified", verified_at=now)
        self._challenges.update(consumed)
        account = self._accounts.mark_email_verified(account.account_id, now) or account
        resolved_channel = (
            ChannelContext.from_value(channel) if channel is not None else challenge.channel
        )
        association = self._associate_channel(account.account_id, resolved_channel, now)
        grant = self._create_session(account, now)
        return AuthenticationResult(
            session=grant,
            identity=association.to_identity_dict(email_verified=account.email_verified),
            channel=resolved_channel,
            meta=ApiMeta.from_context(context),
        )

    def resolve_session(
        self,
        access_token: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        channel: ChannelContext | ChannelName | str | None = None,
        channel_identity_id: str | None = None,
    ) -> ResolvedIdentity:
        context = RequestContext.create(request_id, correlation_id, now=self._now())
        session = self._sessions.get_by_access_token_digest(self._token_hasher.digest(access_token))
        now = context.generated_at
        if session is None or session.status != "active" or now >= session.expires_at:
            if session is not None and session.status == "active" and now >= session.expires_at:
                self._sessions.update(replace(session, status="expired", ended_at=now))
            raise AuthenticationError()
        account = self._accounts.get(session.account_id)
        if account is None:
            raise AuthenticationError()
        association: ChannelAssociation | None = None
        if channel_identity_id is not None:
            association = self._channel_identities.get(channel_identity_id)
            if association is None or association.account_id != account.account_id:
                raise AuthenticationError()
        elif channel is not None:
            association = self._associate_channel(
                account.account_id, ChannelContext.from_value(channel), now
            )
        return ResolvedIdentity(account, session, association, ApiMeta.from_context(context))

    def refresh_session(
        self,
        refresh_token: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuthenticationResult:
        context = RequestContext.create(request_id, correlation_id, now=self._now())
        now = context.generated_at
        current = self._sessions.get_by_refresh_token_digest(self._token_hasher.digest(refresh_token))
        if current is None or current.status != "active" or now >= current.expires_at:
            raise AuthenticationError()
        account = self._accounts.get(current.account_id)
        if account is None:
            raise AuthenticationError()
        access_token = self._token_generator.generate()
        new_refresh_token = self._token_generator.generate()
        refreshed = replace(
            current,
            expires_at=now + self._session_ttl,
            access_token_digest=self._token_hasher.digest(access_token),
            refresh_token_digest=self._token_hasher.digest(new_refresh_token),
        )
        self._sessions.update(refreshed)
        association = self._channel_identities.first_for_account(account.account_id)
        channel = association.channel if association else ChannelContext.from_value("simulated")
        return AuthenticationResult(
            session=SessionGrant(
                session_id=refreshed.session_id,
                access_token=access_token,
                refresh_token=new_refresh_token,
                expires_at=refreshed.expires_at,
                account=account,
            ),
            identity=(
                association.to_identity_dict(email_verified=account.email_verified)
                if association
                else {
                    "account_id": account.account_id,
                    "subject_type": "account",
                    "email_verified": account.email_verified,
                }
            ),
            channel=channel,
            meta=ApiMeta.from_context(context),
        )

    def logout(
        self,
        access_token: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ApiMeta:
        context = RequestContext.create(request_id, correlation_id, now=self._now())
        session = self._sessions.get_by_access_token_digest(self._token_hasher.digest(access_token))
        if session is None or session.status != "active":
            raise AuthenticationError()
        self._sessions.update(replace(session, status="revoked", ended_at=context.generated_at))
        return ApiMeta.from_context(context)

    def associate_channel(
        self,
        account_id: str,
        channel: ChannelContext | ChannelName | str,
        *,
        now: datetime | None = None,
    ) -> ChannelAssociation:
        """Associa um canal somente após o consumidor validar a conta."""

        if self._accounts.get(account_id) is None:
            raise AuthenticationError()
        return self._associate_channel(account_id, ChannelContext.from_value(channel), _as_utc(now or self._now()))

    def _associate_channel(
        self, account_id: str, channel: ChannelContext, now: datetime
    ) -> ChannelAssociation:
        current = self._channel_identities.find(account_id, channel)
        if current is not None:
            return current
        association = ChannelAssociation(
            channel_identity_id=self._id_generator("cid"),
            account_id=account_id,
            channel=channel,
            created_at=now,
        )
        self._channel_identities.save(association)
        return association

    def _create_session(self, account: Account, now: datetime) -> SessionGrant:
        access_token = self._token_generator.generate()
        refresh_token = self._token_generator.generate()
        session = SessionRecord(
            session_id=self._id_generator("ses"),
            account_id=account.account_id,
            started_at=now,
            expires_at=now + self._session_ttl,
            access_token_digest=self._token_hasher.digest(access_token),
            refresh_token_digest=self._token_hasher.digest(refresh_token),
        )
        self._sessions.save(session)
        return SessionGrant(
            session_id=session.session_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=session.expires_at,
            account=account,
        )

    def _now(self) -> datetime:
        return _as_utc(self._clock())
