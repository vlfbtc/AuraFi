"""Aplicacao HTTP local do AuraFi.

Este modulo e deliberadamente independente de FastAPI. Ele concentra o
roteamento e a composicao dos servicos de dominio, deixando o transporte
(``http.server`` hoje e um adapter FastAPI futuro) em ``server.py``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import ceil
import os
from threading import RLock
from time import monotonic
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from database.local.repository import SQLiteRepository, create_repository
from services.conversation import (
    AuditMetadata,
    AnthropicLlm,
    Consent,
    ConversationCreateRequest,
    ConversationError,
    ConversationInputError,
    ConversationNotFoundError,
    ConversationRecord,
    ConversationService,
    DeterministicMockLlm,
    LlmPort,
    MessageEnvelope,
    MessageRequest,
    SessionSnapshot,
)
from services.identity import (
    Account,
    ApiMeta,
    AuthenticationError,
    ChannelContext,
    DeliveryError,
    IdentityService,
    IdentityServiceError,
    InMemoryAccountRepository,
    InMemoryChannelIdentityRepository,
    InMemoryOtpChallengeRepository,
    InMemoryOtpSink,
    InMemorySessionRepository,
    OtpChallenge,
    SessionRecord,
    UnsupportedChannelError,
)
from services.identity import otp_delivery as otp_delivery_module
from services.identity.otp_delivery import OtpDeliveryConfigurationError
from services.identity.service import HmacOtpHasher, OtpDeliveryPort
from services.identity.service import RequestContext
from services.market_data import DeFiLlamaAdapter, MarketDataError
from services.recommendation import (
    Opportunity,
    Recommendation,
    RecommendationService,
    RiskAnswer,
    RiskProfile,
)
from services.simulated_channel import SimulatedChannelAdapter
from services.simulation import (
    AssumptionFixtureFormula,
    SimulationError,
    SimulationService,
)


API_VERSION = "1.0.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_MARKET_BASE_URL = "https://yields.llama.fi"
DEFAULT_MARKET_ENDPOINT = "/pools"
MAX_BODY_BYTES = 1_048_576
PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production", "producao", "produção"})
SUPPORTED_ENVIRONMENTS = PRODUCTION_ENVIRONMENTS | frozenset(
    {"", "local", "dev", "development", "test", "testing", "staging"}
)
MARKET_MODES = frozenset({"auto", "live", "cache", "test", "fallback"})
DISCLAIMER = (
    "A AuraFi oferece apoio a decisao. Informacoes, riscos e simulacoes sao "
    "educativos; nao constituem ordem, consultoria personalizada ou garantia "
    "de retorno e nao executam alocacoes."
)
SUPPORTED_CHANNELS = frozenset({"web_widget", "ios_app", "simulated"})
PROHIBITED_KEYS = frozenset(
    {
        "wallet",
        "wallet_id",
        "wallet_address",
        "wallet_identity",
        "open_finance",
        "open_finance_account",
        "bank_account",
        "transaction",
        "transaction_id",
        "execution",
        "execute",
        "signature",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FixedOtpGenerator:
    """Gerador opt-in para demonstração local, nunca usado por padrão."""

    def __init__(self, code: str) -> None:
        if len(code) != 6 or not code.isdigit():
            raise ValueError("AURAFI_DEV_OTP_CODE deve conter seis dígitos")
        self.code = code

    def generate(self) -> str:
        return self.code


def create_otp_delivery_from_env(
    env: Mapping[str, str] | None = None,
) -> OtpDeliveryPort:
    """Create the configured SMTP delivery adapter without exposing secrets."""

    values = os.environ if env is None else env
    provider = values.get("AURAFI_OTP_PROVIDER", "").strip().casefold()
    if provider != "smtp":
        raise OtpDeliveryConfigurationError(
            "AURAFI_OTP_PROVIDER must be configured as smtp"
        )
    return otp_delivery_module.SmtpOtpDelivery.from_env(values)


def create_llm_from_env(
    env: Mapping[str, str] | None = None,
    *,
    is_production: bool = False,
) -> LlmPort:
    """Resolve o provider do hub; produção nunca cai silenciosamente em mock."""

    values = os.environ if env is None else env
    provider = values.get("AURAFI_LLM_PROVIDER", "").strip().casefold()
    if provider in {"anthropic", "claude"}:
        return AnthropicLlm.from_env(values)
    if not provider and not is_production:
        return DeterministicMockLlm()
    if not provider:
        raise ValueError("AURAFI_LLM_PROVIDER is required in production")
    raise ValueError("AURAFI_LLM_PROVIDER must be configured as anthropic")


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    target: str
    headers: Mapping[str, str]
    body: Any = None
    provided_request_id: str | None = None
    provided_correlation_id: str | None = None
    source_ip: str | None = None

    @property
    def path(self) -> str:
        return urlsplit(self.target).path or "/"

    @property
    def query(self) -> dict[str, str]:
        parsed = parse_qs(urlsplit(self.target).query, keep_blank_values=False)
        return {key: values[-1] for key, values in parsed.items() if values}

    @property
    def request_id(self) -> str | None:
        return _header(self.headers, "x-request-id")

    @property
    def correlation_id(self) -> str | None:
        return _header(self.headers, "x-correlation-id")


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    payload: Any = None
    headers: Mapping[str, str] | None = None


class RateLimitExceeded(RuntimeError):
    """Sinaliza throttling sem incluir identidade, token ou conteúdo no erro."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Limite temporário de requisições excedido.")
        self.retry_after = max(1, retry_after)


class _RateLimiter:
    """Sliding window local; adequado ao deploy suportado de uma réplica."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise RateLimitExceeded(ceil(events[0] + window_seconds - now))
            events.append(now)


def _parse_persisted_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class _SQLiteAccountRepository:
    """Adapta as linhas SQLite ao port de contas da identidade."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repository = repository

    def create(self, account: Account) -> Account:
        return self._account(self._repository.save_account(account.to_dict())) or account

    @staticmethod
    def _account(row: Mapping[str, Any] | None) -> Account | None:
        if row is None:
            return None
        return Account(
            account_id=str(row["account_id"]),
            email=str(row["email"]),
            email_verified=bool(row.get("email_verified", False)),
            created_at=_parse_persisted_timestamp(row["created_at"]),
        )

    def find_by_email(self, email: str) -> Account | None:
        return self._account(self._repository.find_account_by_email(email))

    def get(self, account_id: str) -> Account | None:
        return self._account(self._repository.get_account(account_id))

    def mark_email_verified(self, account_id: str, verified_at: datetime) -> Account | None:
        return self._account(self._repository.mark_email_verified(account_id, verified_at))


class _SQLiteOtpChallengeRepository:
    """Adapta desafios SQLite sem persistir OTP em claro."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repository = repository

    def save(self, challenge: OtpChallenge) -> None:
        self._repository.save_otp_challenge(
            {
                "challenge_id": challenge.challenge_id,
                "email": challenge.email,
                "channel": challenge.channel.name,
                "delivery": challenge.delivery,
                "otp_digest": challenge.otp_digest,
                "status": challenge.status,
                "attempts": challenge.attempts,
                "expires_at": challenge.expires_at,
                "created_at": challenge.created_at,
                "verified_at": challenge.verified_at,
            }
        )

    def get(self, challenge_id: str) -> OtpChallenge | None:
        row = self._repository.get_otp_challenge(challenge_id)
        if row is None:
            return None
        account = self._repository.find_account_by_email(row["email"])
        return OtpChallenge(
            challenge_id=str(row["challenge_id"]),
            email=str(row["email"]),
            channel=ChannelContext.from_value(str(row["channel"])),
            delivery=str(row["delivery"]),  # type: ignore[arg-type]
            otp_digest=str(row["otp_digest"]),
            expires_at=_parse_persisted_timestamp(row["expires_at"]),
            created_at=_parse_persisted_timestamp(row["created_at"]),
            account_id=str(account["account_id"]) if account else None,
            status=str(row["status"]),  # type: ignore[arg-type]
            attempts=int(row.get("attempts", 0)),
            verified_at=(
                _parse_persisted_timestamp(row["verified_at"])
                if row.get("verified_at")
                else None
            ),
        )

    def update(self, challenge: OtpChallenge) -> None:
        self._repository.update_otp_challenge(
            challenge.challenge_id,
            status=challenge.status,
            verified_at=challenge.verified_at,
            attempts=challenge.attempts,
        )


class _SQLiteSessionRepository:
    """Adapta sessões SQLite; tokens chegam aqui somente como digests."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repository = repository

    @staticmethod
    def _session(row: Mapping[str, Any] | None) -> SessionRecord | None:
        if row is None:
            return None
        return SessionRecord(
            session_id=str(row["session_id"]),
            account_id=str(row["account_id"]),
            started_at=_parse_persisted_timestamp(row["started_at"]),
            expires_at=_parse_persisted_timestamp(row["expires_at"]),
            access_token_digest=str(row["access_token_digest"]),
            refresh_token_digest=str(row["refresh_token_digest"]),
            status=str(row.get("status", "active")),  # type: ignore[arg-type]
            ended_at=(
                _parse_persisted_timestamp(row["ended_at"])
                if row.get("ended_at")
                else None
            ),
        )

    def save(self, session: SessionRecord) -> None:
        self._repository.save_session(
            {
                "session_id": session.session_id,
                "account_id": session.account_id,
                "started_at": session.started_at,
                "expires_at": session.expires_at,
                "status": session.status,
                "ended_at": session.ended_at,
                "access_token_digest": session.access_token_digest,
                "refresh_token_digest": session.refresh_token_digest,
            }
        )

    def get_by_access_token_digest(self, digest: str) -> SessionRecord | None:
        return self._session(self._repository.get_by_access_token_digest(digest))

    def get_by_refresh_token_digest(self, digest: str) -> SessionRecord | None:
        return self._session(self._repository.get_by_refresh_token_digest(digest))

    def get(self, session_id: str) -> SessionRecord | None:
        return self._session(self._repository.get_session(session_id))

    def update(self, session: SessionRecord) -> None:
        self._repository.update_session(
            {
                "session_id": session.session_id,
                "expires_at": session.expires_at,
                "status": session.status,
                "ended_at": session.ended_at,
                "access_token_digest": session.access_token_digest,
                "refresh_token_digest": session.refresh_token_digest,
            }
        )


class _SQLiteConversationRepository:
    """Persiste o agregado conversacional sem e-mail, token ou OTP."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repository = repository

    @staticmethod
    def _state(conversation: ConversationRecord) -> dict[str, Any]:
        return {
            "conversation_id": conversation.conversation_id,
            "account_id": conversation.account_id,
            "session": conversation.session.to_dict(),
            "identity": dict(conversation.identity),
            "channel": conversation.channel.to_dict(),
            "consent": conversation.consent.to_dict(),
            "correlation_id": conversation.correlation_id,
            "status": conversation.status,
            "messages": [message.to_dict() for message in conversation.messages],
            "last_activity_at": conversation.last_activity_at.isoformat(),
        }

    @staticmethod
    def _channel(value: Mapping[str, Any]) -> ChannelContext:
        return ChannelContext(
            name=str(value["name"]),  # type: ignore[arg-type]
            adapter=str(value["adapter"]),
            external_message_id=(
                str(value["external_message_id"])
                if value.get("external_message_id") is not None
                else None
            ),
            simulated=bool(value.get("simulated", False)),
        )

    @classmethod
    def _session(cls, value: Mapping[str, Any]) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=str(value["session_id"]),
            started_at=_parse_persisted_timestamp(value["started_at"]),
            expires_at=_parse_persisted_timestamp(value["expires_at"]),
        )

    @classmethod
    def _message(cls, value: Mapping[str, Any]) -> MessageEnvelope:
        audit = value["audit"]
        return MessageEnvelope(
            envelope_version=str(value["envelope_version"]),
            message_id=str(value["message_id"]),
            message_type=str(value["message_type"]),  # type: ignore[arg-type]
            occurred_at=_parse_persisted_timestamp(value["occurred_at"]),
            request_id=str(value["request_id"]),
            correlation_id=str(value["correlation_id"]),
            identity=dict(value["identity"]),
            session=cls._session(value["session"]),
            channel=cls._channel(value["channel"]),
            consent=Consent.from_mapping(value["consent"]),
            payload=dict(value["payload"]),
            disclaimer=str(value["disclaimer"]),
            audit=AuditMetadata(
                source=str(audit["source"]),
                actor=str(audit["actor"]),  # type: ignore[arg-type]
                trace_id=str(audit["trace_id"]),
                redaction=str(audit.get("redaction", "applied")),  # type: ignore[arg-type]
                llm=dict(audit.get("llm", {})),
                data_sources=tuple(audit.get("data_sources", ())),
                schema_version=str(audit.get("schema_version", "1.0")),
            ),
        )

    @classmethod
    def _conversation(cls, state: Mapping[str, Any] | None) -> ConversationRecord | None:
        if state is None:
            return None
        return ConversationRecord(
            conversation_id=str(state["conversation_id"]),
            account_id=str(state["account_id"]),
            session=cls._session(state["session"]),
            identity=dict(state["identity"]),
            channel=cls._channel(state["channel"]),
            consent=Consent.from_mapping(state["consent"]),
            correlation_id=str(state["correlation_id"]),
            status=str(state.get("status", "active")),  # type: ignore[arg-type]
            messages=tuple(cls._message(item) for item in state.get("messages", ())),
            last_activity_at=_parse_persisted_timestamp(state["last_activity_at"]),
        )

    def save(self, conversation: ConversationRecord) -> None:
        self._repository.save_conversation_runtime_state(
            conversation.conversation_id,
            conversation.account_id,
            self._state(conversation),
        )

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return self._conversation(
            self._repository.get_conversation_runtime_state(conversation_id)
        )

    def update(self, conversation: ConversationRecord) -> None:
        self._repository.update_conversation_runtime_state(
            conversation.conversation_id,
            conversation.account_id,
            self._state(conversation),
        )


class AuraFiApp:
    """Composicao local e testavel dos servicos do MVP."""

    def __init__(
        self,
        *,
        version: str = API_VERSION,
        capture_test_secrets: bool = True,
        account: Account | None = None,
        market_mode: str | None = None,
        otp_delivery: OtpDeliveryPort | None = None,
        llm: LlmPort | None = None,
    ) -> None:
        self.version = version
        self.environment = _environment_name(os.environ.get("AURAFI_ENV"))
        self.is_production = self.environment in PRODUCTION_ENVIRONMENTS
        self._lock = RLock()
        self._rate_limiter = _RateLimiter()
        self._otp_request_limit = _env_positive_int("AURAFI_OTP_REQUEST_LIMIT", 5)
        self._otp_verify_limit = _env_positive_int("AURAFI_OTP_VERIFY_LIMIT", 10)
        self._llm_request_limit = _env_positive_int("AURAFI_LLM_REQUEST_LIMIT", 30)
        self._profiles: dict[str, RiskProfile] = {}
        self._alerts: dict[str, list[dict[str, Any]]] = {}
        dev_otp = os.environ.get("AURAFI_DEV_OTP_CODE")
        otp_generator = FixedOtpGenerator(dev_otp) if dev_otp and not self.is_production else None

        initial_account = account or Account("acc_maria", "maria@example.com")
        database_path = os.environ.get("AURAFI_DB_PATH", "").strip()
        if self.is_production and (not database_path or database_path == ":memory:"):
            raise ValueError("AURAFI_DB_PATH persistente é obrigatório em produção")
        self.persistence: SQLiteRepository | None = create_repository(database_path or None)
        if self.persistence is None:
            self.account_repository = InMemoryAccountRepository([initial_account])
            self._challenges = InMemoryOtpChallengeRepository()
            self._sessions = InMemorySessionRepository()
        else:
            if self.persistence.get_account(initial_account.account_id) is None:
                if self.persistence.find_account_by_email(initial_account.email) is None:
                    self.persistence.save_account(initial_account.to_dict())
            self.account_repository = _SQLiteAccountRepository(self.persistence)
            self._challenges = _SQLiteOtpChallengeRepository(self.persistence)
            self._sessions = _SQLiteSessionRepository(self.persistence)
        configured_provider = os.environ.get("AURAFI_OTP_PROVIDER", "").strip()
        if configured_provider:
            delivery = create_otp_delivery_from_env()
            delivery_mode = "email"
        elif otp_delivery is not None:
            delivery = otp_delivery
            delivery_mode = "email"
        elif self.is_production:
            raise ValueError(
                "OTP delivery provider is required in production; "
                "configure AURAFI_OTP_PROVIDER or inject a delivery adapter"
            )
        else:
            delivery = InMemoryOtpSink(capture_secrets=capture_test_secrets)
            delivery_mode = "mock"
        self.otp_sink = delivery if isinstance(delivery, InMemoryOtpSink) else None
        self.identity_delivery_mode = delivery_mode
        otp_pepper = os.environ.get("AURAFI_OTP_HMAC_PEPPER", "").strip()
        if self.is_production and len(otp_pepper.encode("utf-8")) < 32:
            raise ValueError(
                "AURAFI_OTP_HMAC_PEPPER deve ter pelo menos 32 bytes em produção"
            )
        self.identity = IdentityService(
            accounts=self.account_repository,
            challenges=self._challenges,
            sessions=self._sessions,
            channel_identities=InMemoryChannelIdentityRepository(),
            otp_delivery=delivery,
            delivery_mode=delivery_mode,
            otp_generator=otp_generator,
            otp_hasher=(
                HmacOtpHasher(otp_pepper.encode("utf-8")) if otp_pepper else None
            ),
            allow_self_signup=_env_flag("AURAFI_ALLOW_SELF_SIGNUP"),
        )
        network_enabled = _env_flag("AURAFI_ENABLE_MARKET_NETWORK")
        configured_market_mode = market_mode
        if configured_market_mode is None:
            configured_market_mode = os.environ.get("AURAFI_MARKET_MODE")
        self.market_mode = _resolve_market_mode(
            configured_market_mode,
            network_enabled=network_enabled,
            is_production=self.is_production,
        )
        self.market = self._build_market_adapter()
        self.simulation = SimulationService(AssumptionFixtureFormula())
        self.recommendation = RecommendationService(disclaimer=DISCLAIMER)
        self.llm = llm or create_llm_from_env(is_production=self.is_production)
        self.llm_mode = "provider" if isinstance(self.llm, AnthropicLlm) else "mock"
        self.conversation = ConversationService(
            identity=self.identity,
            recommendation=self.recommendation,
            simulation=self.simulation,
            profile_port=self._get_profile,
            policy_port=lambda account_id: None,
            market_data_port=self.market,
            llm=self.llm,
            repository=(
                _SQLiteConversationRepository(self.persistence)
                if self.persistence is not None
                else None
            ),
            disclaimer=DISCLAIMER,
        )
        self.simulated_channel = SimulatedChannelAdapter(self.conversation)

    def close(self) -> None:
        """Fecha o SQLite opcional; o modo em memória não possui lifecycle."""

        if self.persistence is not None:
            self.persistence.close()

    def _build_market_adapter(self) -> DeFiLlamaAdapter:
        """Cria o adapter; producao usa live, local exige opt-in de rede."""

        # Produção sempre aponta para a fonte live; a rede não pode ser
        # desabilitada nessa camada e fazer o app recorrer a dados sintéticos.
        allow_network = self.is_production or _env_flag("AURAFI_ENABLE_MARKET_NETWORK")
        base_url = (
            os.environ.get("AURAFI_MARKET_BASE_URL") or DEFAULT_MARKET_BASE_URL
            if allow_network
            else None
        )
        endpoint = (
            os.environ.get("AURAFI_MARKET_ENDPOINT") or DEFAULT_MARKET_ENDPOINT
            if allow_network
            else None
        )
        if allow_network:
            parsed = urlsplit(str(base_url))
            if (
                parsed.scheme != "https"
                or parsed.hostname != "yields.llama.fi"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "AURAFI_MARKET_BASE_URL must use HTTPS on yields.llama.fi"
                )
            if endpoint != "/pools":
                raise ValueError("AURAFI_MARKET_ENDPOINT must be /pools")
        return DeFiLlamaAdapter(base_url=base_url, endpoint=endpoint)

    def handle(self, request: Request) -> Response:
        """Processa uma requisicao sem depender de um servidor HTTP."""

        try:
            request = _ensure_request_context(request)
            _reject_prohibited(request.body)
            method = request.method.upper()
            if method == "OPTIONS":
                return Response(204)
            route = (method, request.path.rstrip("/") or "/")
            if route == ("GET", "/health"):
                return self._health(request)
            if route == ("POST", "/v1/auth/otp/request"):
                return self._otp_request(request)
            if route == ("POST", "/v1/auth/otp/verify"):
                return self._otp_verify(request)
            if route == ("GET", "/v1/profile"):
                return self._get_profile_response(request)
            if route in {("GET", "/v1/profile/risk"), ("PUT", "/v1/profile/risk")}:
                return self._profile_risk(request)
            if route == ("GET", "/v1/opportunities"):
                return self._opportunities(request)
            if route == ("POST", "/v1/simulations"):
                return self._simulation(request)
            if route == ("POST", "/v1/recommendations"):
                return self._recommendation(request)
            if route == ("POST", "/v1/conversations"):
                return self._create_conversation(request)
            if route == ("GET", "/v1/alerts"):
                return self._alerts_response(request)

            conversation_message = _conversation_message_route(request.path)
            if method == "POST" and conversation_message is not None:
                return self._conversation_message(request, conversation_message)
            conversation_get = _conversation_get_route(request.path)
            if method == "GET" and conversation_get is not None:
                return self._get_conversation(request, conversation_get)
            return self._error_response(
                request,
                404,
                "NOT_FOUND",
                "Recurso nao encontrado.",
                retryable=False,
            )
        except RateLimitExceeded as exc:
            response = self._error_response(
                request,
                429,
                "RATE_LIMITED",
                "Muitas tentativas. Aguarde antes de tentar novamente.",
                retryable=True,
            )
            return Response(response.status, response.payload, {"Retry-After": str(exc.retry_after)})
        except ProhibitedOperationError as exc:
            return self._error_response(request, 400, exc.code, str(exc), retryable=False)
        except IdentityServiceError as exc:
            if isinstance(exc, AuthenticationError):
                status = 401
            elif isinstance(exc, DeliveryError):
                status = 503
            else:
                status = 400
            return self._error_from_domain(request, status, exc)
        except ConversationError as exc:
            status = 404 if isinstance(exc, ConversationNotFoundError) else 422
            return self._error_from_domain(request, status, exc)
        except SimulationError as exc:
            return self._error_from_domain(request, 422, exc)
        except MarketDataError as exc:
            return self._error_response(
                request,
                503,
                "MARKET_DATA_UNAVAILABLE",
                "Os dados de mercado nao estao disponiveis neste momento.",
                retryable=True,
                details={"reason": type(exc).__name__},
            )
        except RequestValidationError as exc:
            return self._error_response(
                request,
                400,
                "INVALID_REQUEST",
                str(exc),
                retryable=False,
                details=exc.details,
            )
        except (TypeError, ValueError, KeyError) as exc:
            return self._error_response(
                request,
                400,
                "INVALID_REQUEST",
                "A requisicao nao pode ser processada.",
                retryable=False,
                details={"reason": type(exc).__name__},
            )
        except Exception:
            return self._error_response(
                request,
                500,
                "INTERNAL_ERROR",
                "Nao foi possivel processar a requisicao.",
                retryable=True,
            )

    def _health(self, request: Request) -> Response:
        meta = self._meta(request)
        payload = {
            "status": "ok",
            "version": self.version,
            "checks": {
                "identity": self.identity_delivery_mode,
                "persistence": "sqlite" if self.persistence is not None else "memory",
                "market_data": self.market_mode,
                "llm": self.llm_mode,
            },
            "meta": meta.to_dict(),
        }
        return Response(200, payload)

    def _otp_request(self, request: Request) -> Response:
        payload = _object_body(request)
        source = request.source_ip or "unknown"
        email_digest = sha256(
            str(payload.get("email", "")).strip().casefold().encode("utf-8")
        ).hexdigest()
        for key in (f"otp-request:ip:{source}", f"otp-request:email:{email_digest}"):
            self._rate_limiter.check(
                key,
                limit=self._otp_request_limit,
                window_seconds=900,
            )
        channel = _channel(payload.get("channel"))
        result = self.identity.request_otp(
            payload.get("email"),
            channel,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )
        return Response(202, result.to_dict())

    def _otp_verify(self, request: Request) -> Response:
        payload = _object_body(request)
        source = request.source_ip or "unknown"
        challenge_digest = sha256(
            str(payload.get("challenge_id", "")).encode("utf-8")
        ).hexdigest()
        for key in (f"otp-verify:ip:{source}", f"otp-verify:challenge:{challenge_digest}"):
            self._rate_limiter.check(
                key,
                limit=self._otp_verify_limit,
                window_seconds=900,
            )
        result = self.identity.verify_otp(
            payload.get("challenge_id"),
            payload.get("otp"),
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )
        return Response(200, result.to_dict())

    def _get_profile_response(self, request: Request) -> Response:
        resolved = self._resolve(request)
        return Response(
            200,
            {
                "account": resolved.account.to_dict(),
                "risk_profile": self._profile_to_dict(self._get_profile(resolved.account.account_id)),
                "meta": self._meta(request).to_dict(),
            },
        )

    def _profile_risk(self, request: Request) -> Response:
        resolved = self._resolve(request)
        if request.method.upper() == "GET":
            payload = {
                "risk_profile": self._profile_to_dict(self._get_profile(resolved.account.account_id)),
                "meta": self._meta(request).to_dict(),
            }
            return Response(200, payload)

        data = _object_body(request)
        answers = data.get("answers")
        if not isinstance(answers, list) or len(answers) != 5:
            raise RequestValidationError(
                "O perfil de risco exige exatamente cinco respostas.",
                details={"field": "answers", "expected": 5},
            )
        profile = RiskProfile(
            declared_profile=data.get("declared_profile"),
            version=str(data.get("version", "profile-v1")),
            source="questionnaire",
            answers=tuple(RiskAnswer(item["question_id"], item["answer"]) for item in answers),
            declared_at=utc_now(),
        )
        if self.persistence is not None:
            # O schema exige a conta referenciada antes do perfil; isso nao
            # altera o fluxo de identidade, apenas satisfaz a FK do SQLite.
            if self.persistence.get_account(resolved.account.account_id) is None:
                self.persistence.save_account(resolved.account.to_dict())
            self.persistence.save_risk_profile(
                {
                    "risk_profile_id": str(uuid4()),
                    "account_id": resolved.account.account_id,
                    "declared_profile": getattr(
                        profile.declared_profile, "value", profile.declared_profile
                    ),
                    "status": getattr(profile.status, "value", profile.status),
                    "version": profile.version,
                    "declared_at": profile.declared_at,
                    "source": getattr(profile.source, "value", profile.source),
                    "answers": [
                        {"question_id": answer.question_id, "answer": answer.answer}
                        for answer in profile.answers
                    ],
                }
            )
        else:
            with self._lock:
                self._profiles[resolved.account.account_id] = profile
        return Response(
            200,
            {
                "account": resolved.account.to_dict(),
                "risk_profile": self._profile_to_dict(profile),
                "meta": self._meta(request).to_dict(),
            },
        )

    def _opportunities(self, request: Request) -> Response:
        self._resolve(request)
        snapshot = self._read_market()
        query = request.query
        asset = query.get("asset", "").casefold()
        blockchain = query.get("blockchain", "").casefold()
        items = [
            item.to_dict()
            for item in snapshot.items
            if (not asset or item.asset.casefold() == asset)
            and (not blockchain or item.blockchain.casefold() == blockchain)
        ]
        page, page_size = _pagination(query)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]
        meta = self._meta(request).to_dict()
        meta["data_sources"] = [snapshot.data_source.to_dict()]
        return Response(
            200,
            {
                "items": page_items,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": len(items),
                    "has_next": start + page_size < len(items),
                },
                "meta": meta,
            },
        )

    def _simulation(self, request: Request) -> Response:
        self._resolve(request)
        data = _object_body(request)
        snapshot = self._read_market()
        opportunity_id = data.get("opportunity_id")
        opportunity = next(
            (item for item in snapshot.items if item.opportunity_id == opportunity_id), None
        )
        if opportunity is None:
            return self._error_response(
                request,
                404,
                "OPPORTUNITY_NOT_FOUND",
                "Oportunidade nao encontrada.",
                retryable=False,
            )
        simulation_input = dict(data)
        simulation_input["apy"] = {
            "value": opportunity.apy_value,
            "unit": "percent_annualized",
        }
        simulation_input["data_source"] = opportunity.data_source.to_dict()
        simulation = self.simulation.simulate(simulation_input)
        meta = self._meta(request).to_dict()
        meta["data_sources"] = [opportunity.data_source.to_dict()]
        return Response(201, {"simulation": simulation.to_dict(), "meta": meta})

    def _recommendation(self, request: Request) -> Response:
        resolved = self._resolve(request)
        data = _object_body(request)
        if data.get("intent") not in {"discover", "compare", "explain", "next_step"}:
            raise RequestValidationError(
                "intent deve ser discover, compare, explain ou next_step.",
                details={"field": "intent"},
            )
        snapshot = self._read_market()
        requested_ids = set(data.get("opportunity_ids") or [])
        raw_items = [item for item in snapshot.items if not requested_ids or item.opportunity_id in requested_ids]
        domain_items = tuple(
            Opportunity(
                item.opportunity_id,
                risk_level=item.risk_level,
                risk_dimensions=item.risk_dimensions,
                attributes=item.to_dict(),
            )
            for item in raw_items
        )
        recommendation = self.recommendation.recommend(
            self._get_profile(resolved.account.account_id),
            domain_items,
            None,
            recommendation_id=f"rec_{uuid4().hex}",
            now=utc_now(),
        )
        meta = self._meta(request).to_dict()
        meta["data_sources"] = [snapshot.data_source.to_dict()]
        payload = {"recommendation": _recommendation_to_dict(recommendation), "meta": meta}
        return Response(201, payload)

    def _create_conversation(self, request: Request) -> Response:
        token = self._bearer(request)
        data = _object_body(request)
        create = ConversationCreateRequest.from_mapping(data)
        if create.channel not in SUPPORTED_CHANNELS:
            raise UnsupportedChannelError()
        result = self.conversation.create_conversation(
            token,
            request=create,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )
        return Response(201, result.to_dict())

    def _conversation_message(self, request: Request, conversation_id: str) -> Response:
        token = self._bearer(request)
        principal = sha256(token.encode("utf-8")).hexdigest()
        self._rate_limiter.check(
            f"llm:principal:{principal}",
            limit=self._llm_request_limit,
            window_seconds=3600,
        )
        data = _object_body(request)
        message = MessageRequest.from_mapping(data, default_channel=data.get("channel"))
        correlation_id = request.provided_correlation_id
        if correlation_id is None:
            conversation_record = self.conversation._repository.get(conversation_id)  # local adapter
            correlation_id = conversation_record.correlation_id if conversation_record else None
        if message.channel == "simulated":
            transport = {
                "access_token": token,
                "conversation_id": conversation_id,
                "text": message.text,
                "channel": "simulated",
                "consent": message.consent.to_dict(),
                "action": message.action,
                "request_id": request.request_id,
                "correlation_id": correlation_id,
            }
            result = self.simulated_channel.receive(transport)
        else:
            result = self.conversation.send_message(
                token,
                conversation_id,
                message,
                request_id=request.request_id,
                correlation_id=correlation_id,
            )
        return Response(200, result.to_dict())

    def _get_conversation(self, request: Request, conversation_id: str) -> Response:
        token = self._bearer(request)
        result = self.conversation.get_conversation(
            token,
            conversation_id,
            request_id=request.request_id,
            correlation_id=request.provided_correlation_id,
        )
        return Response(200, result.to_dict())

    def _alerts_response(self, request: Request) -> Response:
        resolved = self._resolve(request)
        query = request.query
        with self._lock:
            items = list(self._alerts.get(resolved.account.account_id, ()))
        status = query.get("status")
        if status:
            items = [item for item in items if item.get("status") == status]
        page, page_size = _pagination(query)
        start = (page - 1) * page_size
        return Response(
            200,
            {
                "items": items[start : start + page_size],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": len(items),
                    "has_next": start + page_size < len(items),
                },
                "meta": self._meta(request).to_dict(),
            },
        )

    def _read_market(self):
        mode = self.market_mode
        if mode not in MARKET_MODES:
            mode = "live" if self.is_production else "test"
        snapshot = self.market.read(mode=mode)
        if self.is_production and snapshot.data_source.mode in {"test", "fallback"}:
            raise MarketDataError(
                "Dados sintéticos não podem ser servidos em produção"
            )
        return snapshot

    def _resolve(self, request: Request):
        return self.identity.resolve_session(
            self._bearer(request),
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )

    def _bearer(self, request: Request) -> str:
        value = _header(request.headers, "authorization") or ""
        scheme, _, token = value.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            raise AuthenticationError()
        return token.strip()

    def _get_profile(self, account_id: str) -> RiskProfile | None:
        if self.persistence is not None:
            persisted = self.persistence.get_latest_risk_profile(account_id)
            if persisted is None:
                return None
            declared_at = persisted.get("declared_at")
            parsed_declared_at = (
                datetime.fromisoformat(str(declared_at).replace("Z", "+00:00"))
                if declared_at
                else None
            )
            return RiskProfile(
                declared_profile=persisted.get("declared_profile"),
                version=persisted.get("version"),
                source=persisted.get("source"),
                answers=tuple(
                    RiskAnswer(answer["question_id"], answer["answer"])
                    for answer in persisted.get("answers", ())
                ),
                declared_at=parsed_declared_at,
                status=persisted.get("status", "declared"),
            )
        with self._lock:
            return self._profiles.get(account_id)

    def _meta(self, request: Request) -> ApiMeta:
        return ApiMeta.from_context(
            RequestContext.create(request.request_id, request.correlation_id, now=utc_now())
        )

    def _error_from_domain(self, request: Request, status: int, error: Any) -> Response:
        payload = error.to_error(self._meta(request)) if hasattr(error, "to_error") else None
        if payload is None:
            return self._error_response(request, status, "DOMAIN_ERROR", str(error), retryable=False)
        return Response(status, payload)

    def _error_response(
        self,
        request: Request,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> Response:
        return Response(
            status,
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": dict(details or {}),
                    "retryable": retryable,
                },
                "meta": self._meta(request).to_dict(),
            },
        )

    @staticmethod
    def _profile_to_dict(profile: RiskProfile | None) -> dict[str, Any] | None:
        if profile is None:
            return None
        return {
            "declared_profile": getattr(profile.declared_profile, "value", profile.declared_profile),
            "status": getattr(profile.status, "value", profile.status),
            "version": profile.version,
            "declared_at": profile.declared_at.isoformat().replace("+00:00", "Z") if profile.declared_at else None,
            "source": getattr(profile.source, "value", profile.source),
        }


class RequestValidationError(ValueError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


class ProhibitedOperationError(ValueError):
    code = "OPERATION_NOT_SUPPORTED"


def create_app(**kwargs: Any) -> AuraFiApp:
    """Factory publica usada pelo servidor, CLI e smoke tests."""

    return AuraFiApp(**kwargs)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if key.casefold() == wanted:
            return str(value)
    return None


def _env_flag(name: str) -> bool:
    """Interpreta uma flag de ambiente sem habilitar rede por ambiguidade."""

    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes"}


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} deve ser um inteiro positivo")
    return value


def _environment_name(value: str | None) -> str:
    """Normaliza o ambiente e falha fechado para valores desconhecidos."""

    environment = (value or "").strip().casefold()
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            "AURAFI_ENV inválido; use local, dev, test, staging, prod ou production"
        )
    return environment


def _resolve_market_mode(
    configured_mode: str | None,
    *,
    network_enabled: bool,
    is_production: bool,
) -> str:
    mode = (configured_mode or "").strip().casefold()
    if not mode:
        mode = "live" if is_production else ("auto" if network_enabled else "test")
    if mode not in MARKET_MODES:
        raise ValueError(
            "AURAFI_MARKET_MODE inválido; use auto, live, cache, test ou fallback"
        )
    if is_production and mode in {"test", "fallback"}:
        raise ValueError(
            "AURAFI_MARKET_MODE sintético não é permitido quando AURAFI_ENV é produção"
        )
    return mode


def _ensure_request_context(request: Request) -> Request:
    provided_request_id = request.request_id
    provided_correlation_id = request.correlation_id
    if provided_request_id and provided_correlation_id:
        return Request(
            request.method,
            request.target,
            request.headers,
            request.body,
            provided_request_id,
            provided_correlation_id,
            request.source_ip,
        )
    context = RequestContext.create(request.request_id, request.correlation_id, now=utc_now())
    headers = dict(request.headers)
    headers.setdefault("X-Request-ID", context.request_id)
    headers.setdefault("X-Correlation-ID", context.correlation_id)
    return Request(
        request.method,
        request.target,
        headers,
        request.body,
        provided_request_id,
        provided_correlation_id,
        request.source_ip,
    )


def _object_body(request: Request) -> dict[str, Any]:
    if not isinstance(request.body, Mapping):
        raise RequestValidationError("O corpo JSON deve ser um objeto.", details={"field": "body"})
    return dict(request.body)


def _channel(value: Any) -> str:
    if value not in SUPPORTED_CHANNELS:
        raise UnsupportedChannelError()
    return str(value)


def _pagination(query: Mapping[str, str]) -> tuple[int, int]:
    try:
        page = int(query.get("page", "1"))
        page_size = int(query.get("page_size", "20"))
    except ValueError as exc:
        raise RequestValidationError("page e page_size devem ser inteiros.") from exc
    if page < 1 or page_size < 1 or page_size > 100:
        raise RequestValidationError("page e page_size estao fora dos limites.")
    return page, page_size


def _conversation_message_route(path: str) -> str | None:
    prefix = "/v1/conversations/"
    suffix = "/messages"
    if path.startswith(prefix) and path.endswith(suffix):
        conversation_id = path[len(prefix) : -len(suffix)]
        return conversation_id or None
    return None


def _conversation_get_route(path: str) -> str | None:
    prefix = "/v1/conversations/"
    if path.startswith(prefix):
        conversation_id = path[len(prefix) :]
        if conversation_id and "/" not in conversation_id:
            return conversation_id
    return None


def _reject_prohibited(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in PROHIBITED_KEYS or any(
                term in normalized for term in ("wallet", "open_finance", "transaction", "execution")
            ):
                raise ProhibitedOperationError(
                    "Wallet, Open Finance e execucao financeira nao fazem parte do MVP."
                )
            _reject_prohibited(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_prohibited(nested)


def _recommendation_to_dict(recommendation: Recommendation) -> dict[str, Any]:
    return {
        "recommendation_id": recommendation.recommendation_id,
        "status": recommendation.status.value,
        "profile_used": recommendation.profile_used.value if recommendation.profile_used else None,
        "items": [
            {
                "opportunity_id": item.opportunity_id,
                "suitability": item.suitability.value,
                "rationale": list(item.rationale),
                "risks": list(item.risks),
                "disclaimer": item.disclaimer,
            }
            for item in recommendation.items
        ],
        "explanation": recommendation.explanation,
        "disclaimer": recommendation.disclaimer,
        "generated_at": recommendation.generated_at.isoformat().replace("+00:00", "Z"),
        "policy_version": recommendation.policy_version,
        "eligibility": [
            {
                "opportunity_id": decision.opportunity_id,
                "status": decision.status.value,
                "reason_code": decision.reason_code,
                "reason": decision.reason,
                "policy_version": decision.policy_version,
                "profile_used": decision.profile_used.value if decision.profile_used else None,
                "suitability": decision.suitability.value if decision.suitability else None,
                "rationale": list(decision.rationale),
                "risks": list(decision.risks),
            }
            for decision in recommendation.eligibility
        ],
        "actionable": recommendation.actionable,
    }


__all__ = [
    "API_VERSION",
    "AuraFiApp",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DISCLAIMER",
    "MAX_BODY_BYTES",
    "Request",
    "RequestValidationError",
    "Response",
    "create_app",
]
