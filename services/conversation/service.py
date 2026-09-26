"""Domínio puro do Aura Core conversacional.

O serviço orquestra identidade, conversa, recomendação e simulação através de
portas pequenas. Não conhece HTTP, banco, rede ou um SDK de LLM. O caminho
default usa um mock determinístico e o envelope produzido aqui é o contrato
canônico consumido pelos canais do MVP.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re
import threading
from typing import Any, Literal, Protocol
from uuid import uuid4

from services.identity import (
    ApiMeta,
    ChannelContext,
    ChannelName,
    IdentityService,
    ResolvedIdentity,
)
from services.recommendation import (
    EligibilityPolicy,
    Opportunity,
    Recommendation,
    RecommendationService,
    RiskProfile,
)
from .redaction import redact_text


ENVELOPE_VERSION = "1.0"
PROMPT_VERSION = "aura-core-v1"
CONVERSATION_SCHEMA_VERSION = "1.0"
DEFAULT_DISCLAIMER = (
    "A AuraFi oferece apoio à decisão. Informações, riscos e simulações são "
    "educativos; não constituem ordem, consultoria personalizada ou garantia "
    "de retorno e não executam alocações."
)
SUPPORTED_ACTIONS = frozenset({"ask_why", "simulate", "explain_risk", "compare", "request_human"})
SUPPORTED_CONSENT_PURPOSES = frozenset(
    {"decision_support", "conversation", "memory", "analytics"}
)
SUPPORTED_CONSENT_STATUS = frozenset({"granted", "denied", "revoked"})

ConversationStatus = Literal["active", "waiting_human", "closed"]
MessageAction = Literal["ask_why", "simulate", "explain_risk", "compare", "request_human"]
LlmMode = Literal["mock", "provider"]
LlmExplainability = Literal["structured", "unavailable"]
FallbackKind = Literal["faq", "human_support"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps devem incluir timezone")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


@dataclass(frozen=True, slots=True)
class Consent:
    """Consentimento explícito carregado no envelope de cada mensagem."""

    purpose: str
    status: str
    policy_version: str
    captured_at: datetime
    memory: bool = False
    analytics: bool = False

    def __post_init__(self) -> None:
        if self.purpose not in SUPPORTED_CONSENT_PURPOSES:
            raise ConversationInputError("Finalidade de consentimento inválida.", details={"field": "purpose"})
        if self.status not in SUPPORTED_CONSENT_STATUS:
            raise ConversationInputError("Estado de consentimento inválido.", details={"field": "status"})
        if not self.policy_version.strip():
            raise ConversationInputError("policy_version é obrigatório.", details={"field": "policy_version"})
        object.__setattr__(self, "captured_at", _utc(self.captured_at))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Consent":
        captured_at = value.get("captured_at")
        if isinstance(captured_at, str):
            captured_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured_at is None:
            captured_at = datetime.now(timezone.utc)
        try:
            return cls(
                purpose=str(value.get("purpose", "conversation")),
                status=str(value.get("status", "denied")),
                policy_version=str(value.get("policy_version", "")),
                captured_at=captured_at,
                memory=bool(value.get("memory", False)),
                analytics=bool(value.get("analytics", False)),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ConversationError):
                raise
            raise ConversationInputError("Consentimento inválido.", details={"field": "consent"}) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "status": self.status,
            "policy_version": self.policy_version,
            "captured_at": _iso(self.captured_at),
            "memory": self.memory,
            "analytics": self.analytics,
        }


@dataclass(frozen=True, slots=True)
class LlmMetadata:
    """Metadados auditáveis da camada LLM e de sua degradação."""

    mode: LlmMode = "mock"
    provider: str | None = "mock"
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    mockable: Literal[True] = True
    explainability: LlmExplainability = "structured"
    fallback: FallbackKind | None = None
    fallback_used: bool = False
    escalation_flag: bool = False
    llm_available: bool = True
    service_status: Literal["available", "fallback", "unavailable", "not_required"] = "available"
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"mock", "provider"}:
            raise ValueError("modo LLM inválido")
        if self.provider not in {None, "claude", "mock"}:
            raise ValueError("provedor LLM inválido")
        if self.explainability not in {"structured", "unavailable"}:
            raise ValueError("nível de explicabilidade inválido")
        if self.service_status not in {"available", "fallback", "unavailable", "not_required"}:
            raise ValueError("estado do serviço LLM inválido")
        if not self.prompt_version.strip():
            raise ValueError("prompt_version é obrigatório")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "mockable": True,
            "explainability": self.explainability,
            "fallback": self.fallback,
            "fallback_used": self.fallback_used,
            "escalation_flag": self.escalation_flag,
            "llm_available": self.llm_available,
            "service_status": self.service_status,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True, slots=True)
class LlmRequest:
    text: str
    account_id: str
    conversation_id: str
    action: str | None = None
    context: tuple[Mapping[str, Any], ...] = ()
    grounding: str = ""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("texto LLM não pode ser vazio")
        if not self.account_id.strip() or not self.conversation_id.strip():
            raise ValueError("LLM exige identidade e conversa resolvidas")
        object.__setattr__(self, "context", tuple(dict(item) for item in self.context))


@dataclass(frozen=True, slots=True)
class LlmResult:
    text: str
    mode: LlmMode = "mock"
    provider: str | None = "mock"
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    explanation: tuple[str, ...] = ()
    structured: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("LLM deve retornar texto não vazio")
        if self.mode not in {"mock", "provider"}:
            raise ValueError("modo LLM inválido")
        if self.provider not in {None, "claude", "mock"}:
            raise ValueError("provedor LLM inválido")
        object.__setattr__(self, "explanation", tuple(self.explanation))


class LlmPort(Protocol):
    """Porta mínima. Um adaptador Claude real pode ser conectado depois."""

    def complete(self, request: LlmRequest) -> LlmResult | str:
        ...


class DeterministicMockLlm:
    """Mock controlado para testes, demos e execução local sem rede."""

    def __init__(
        self,
        response: str | Callable[[LlmRequest], LlmResult | str] | None = None,
        *,
        prompt_version: str = PROMPT_VERSION,
        model: str = "mock-deterministic",
    ) -> None:
        self._response = response or (
            "Posso explicar riscos, dados observados e cenários educativos. "
            "Para uma recomendação, primeiro precisamos de um perfil declarado "
            "e de uma política de elegibilidade válida."
        )
        self._prompt_version = prompt_version
        self._model = model

    def complete(self, request: LlmRequest) -> LlmResult:
        result = self._response(request) if callable(self._response) else self._response
        if isinstance(result, LlmResult):
            return result
        return LlmResult(
            text=str(result),
            mode="mock",
            provider="mock",
            model=self._model,
            prompt_version=self._prompt_version,
        )


MockLlm = DeterministicMockLlm


class UnavailableLlm:
    """Porta explícita para testar indisponibilidade e o fallback."""

    def complete(self, request: LlmRequest) -> LlmResult:
        raise RuntimeError("LLM indisponível")


class FaqPort(Protocol):
    def answer(self, text: str, *, action: str | None = None) -> str:
        ...


class DeterministicFaq:
    """FAQ pequeno e previsível; não cria recomendação nem promessa."""

    def answer(self, text: str, *, action: str | None = None) -> str:
        normalized = _normalize_text(text)
        if action == "request_human" or any(term in normalized for term in ("humano", "atendente", "suporte")):
            return "Seu pedido foi marcado para atendimento humano. Nenhuma ação financeira foi executada."
        if "wallet" in normalized or "carteira" in normalized:
            return "Wallet não é identidade no MVP. A conta AuraFi usa e-mail/OTP; não conectamos wallet nem executamos transações."
        if action == "simulate" or "simul" in normalized:
            return "Para simular com segurança, informe a oportunidade, o valor hipotético, o ativo e o horizonte. A projeção usa premissas explícitas, não movimenta fundos e não garante retorno."
        if action in {"ask_why", "explain_risk"} or "risco" in normalized:
            return "Ao avaliar risco, confira contrato inteligente, liquidez, volatilidade do ativo, dependências do protocolo, auditorias e frescor dos dados. Risco desconhecido não significa risco baixo; esta explicação é educativa e não garante retorno."
        if action == "compare" or any(term in normalized for term in ("compare", "comparar", "diferença")):
            return "Para comparar alternativas, coloque lado a lado APY observado, TVL e liquidez, rede, exposição ao ativo, risco de contrato e data da fonte. Uma taxa maior isoladamente não torna uma alternativa melhor ou adequada ao seu perfil."
        if "cash and carry" in normalized or "cash-and-carry" in normalized:
            return "Cash-and-carry combina posições opostas no mercado à vista e em derivativos para observar um spread. Ainda há risco de contraparte, liquidação, funding, base, custódia e execução; a AuraFi apenas explica o conceito e não monta nem executa a estratégia."
        if action in {"recommend", "discover"} or any(term in normalized for term in ("recomend", "aloca", "investir", "qual oportunidade")):
            return "Para sugerir uma oportunidade, é necessário um perfil de risco declarado e uma política de elegibilidade válida."
        return "Posso ajudar a entender oportunidades, riscos e simulações educativas. Não executo alocações."


FaqFallback = DeterministicFaq


@dataclass(frozen=True, slots=True)
class MessageRequest:
    text: str
    channel: ChannelContext | ChannelName | str
    consent: Consent | Mapping[str, Any]
    action: MessageAction | str | None = None
    simulation: Mapping[str, Any] | Any | None = None
    profile: RiskProfile | None = None
    policy: EligibilityPolicy | None = None
    opportunities: tuple[Opportunity, ...] | None = None
    external_message_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 4000:
            raise ConversationInputError("A mensagem deve ter entre 1 e 4000 caracteres.", details={"field": "text"})
        if self.action is not None and self.action not in SUPPORTED_ACTIONS:
            raise ConversationInputError("Ação de mensagem inválida.", details={"field": "action"})
        consent = self.consent if isinstance(self.consent, Consent) else Consent.from_mapping(self.consent)
        object.__setattr__(self, "consent", consent)
        if self.external_message_id is not None:
            normalized_external_id = self.external_message_id.strip()
            if not normalized_external_id or len(normalized_external_id) > 200:
                raise ConversationInputError(
                    "external_message_id deve ter entre 1 e 200 caracteres.",
                    details={"field": "external_message_id"},
                )
            object.__setattr__(self, "external_message_id", normalized_external_id)

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        default_channel: ChannelContext | ChannelName | str | None = None,
    ) -> "MessageRequest":
        _reject_wallet_identity(value)
        channel = value.get("channel", default_channel)
        if channel is None:
            raise ConversationInputError("Canal é obrigatório.", details={"field": "channel"})
        consent = value.get("consent")
        if consent is None:
            raise ConversationInputError("Consentimento é obrigatório.", details={"field": "consent"})
        return cls(
            text=value.get("text", ""),
            channel=channel,
            consent=consent,
            action=value.get("action"),
            simulation=value.get("simulation"),
            external_message_id=value.get("external_message_id"),
        )


@dataclass(frozen=True, slots=True)
class ConversationCreateRequest:
    channel: ChannelContext | ChannelName | str
    consent: Consent | Mapping[str, Any]
    initial_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "consent",
            self.consent if isinstance(self.consent, Consent) else Consent.from_mapping(self.consent),
        )
        if self.initial_message is not None and (not self.initial_message.strip() or len(self.initial_message) > 2000):
            raise ConversationInputError("initial_message deve ter entre 1 e 2000 caracteres.", details={"field": "initial_message"})

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConversationCreateRequest":
        _reject_wallet_identity(value)
        if "channel" not in value or "consent" not in value:
            raise ConversationInputError("channel e consent são obrigatórios.", details={"fields": ["channel", "consent"]})
        return cls(value["channel"], value["consent"], value.get("initial_message"))


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str
    started_at: datetime
    expires_at: datetime

    @classmethod
    def from_identity(cls, resolved: ResolvedIdentity) -> "SessionSnapshot":
        return cls(resolved.session.session_id, resolved.session.started_at, resolved.session.expires_at)

    def to_dict(self) -> dict[str, str]:
        return {"session_id": self.session_id, "started_at": _iso(self.started_at), "expires_at": _iso(self.expires_at)}


@dataclass(frozen=True, slots=True)
class AuditMetadata:
    source: str
    actor: Literal["user", "hub", "system", "human_support"]
    trace_id: str
    redaction: Literal["applied", "not_required"] = "not_required"
    llm: Mapping[str, Any] = field(default_factory=dict)
    data_sources: tuple[Mapping[str, Any], ...] = ()
    schema_version: str = CONVERSATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "actor": self.actor,
            "redaction": self.redaction,
            "llm": dict(self.llm),
            "data_sources": [dict(item) for item in self.data_sources],
        }


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    envelope_version: str
    message_id: str
    message_type: Literal["user_message", "assistant_message", "system_event", "alert"]
    occurred_at: datetime
    request_id: str
    correlation_id: str
    identity: Mapping[str, Any]
    session: SessionSnapshot
    channel: ChannelContext
    consent: Consent
    payload: Mapping[str, Any]
    disclaimer: str
    audit: AuditMetadata

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d+\.\d+", self.envelope_version):
            raise ValueError("envelope_version inválido")
        if self.message_type not in {"user_message", "assistant_message", "system_event", "alert"}:
            raise ValueError("message_type inválido")
        if not self.request_id.strip() or not self.correlation_id.strip():
            raise ValueError("request_id e correlation_id são obrigatórios")
        if not self.disclaimer.strip():
            raise ValueError("disclaimer é obrigatório")
        _reject_wallet_identity(self.identity)
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "occurred_at": _iso(self.occurred_at),
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "identity": dict(self.identity),
            "session": self.session.to_dict(),
            "channel": self.channel.to_dict(),
            "consent": self.consent.to_dict(),
            "payload": dict(self.payload),
            "disclaimer": self.disclaimer,
            "audit": self.audit.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    conversation_id: str
    account_id: str
    session: SessionSnapshot
    identity: Mapping[str, Any]
    channel: ChannelContext
    consent: Consent
    correlation_id: str
    status: ConversationStatus = "active"
    messages: tuple[MessageEnvelope, ...] = ()
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.status not in {"active", "waiting_human", "closed"}:
            raise ValueError("status de conversa inválido")
        if not self.conversation_id.strip() or not self.account_id.strip():
            raise ValueError("conversa exige identidade interna")
        _reject_wallet_identity(self.identity)
        object.__setattr__(self, "last_activity_at", _utc(self.last_activity_at))
        object.__setattr__(self, "messages", tuple(self.messages))

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "session": self.session.to_dict(),
            "channel": self.channel.to_dict(),
            "status": self.status,
            "messages": [message.to_dict() for message in self.messages],
            "last_activity_at": _iso(self.last_activity_at),
        }


@dataclass(frozen=True, slots=True)
class ConversationResponse:
    conversation: ConversationRecord
    meta: ApiMeta

    def to_dict(self) -> dict[str, Any]:
        return {"conversation": self.conversation.to_dict(), "meta": self.meta.to_dict()}


@dataclass(frozen=True, slots=True)
class MessageResponse:
    user_message: MessageEnvelope
    assistant_message: MessageEnvelope
    meta: ApiMeta
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_message": self.user_message.to_dict(),
            "assistant_message": self.assistant_message.to_dict(),
            "meta": self.meta.to_dict(),
            "metadata": dict(self.metadata),
        }


class ConversationRepository(Protocol):
    def save(self, conversation: ConversationRecord) -> None:
        ...

    def get(self, conversation_id: str) -> ConversationRecord | None:
        ...

    def update(self, conversation: ConversationRecord) -> None:
        ...

    def latest_for_account(self, account_id: str) -> ConversationRecord | None:
        ...


class InMemoryConversationRepository:
    """Adapter local determinístico; persistência real fica fora do domínio."""

    def __init__(self) -> None:
        self._items: dict[str, ConversationRecord] = {}
        self._lock = threading.RLock()

    def save(self, conversation: ConversationRecord) -> None:
        with self._lock:
            if conversation.conversation_id in self._items:
                raise ValueError("conversation_id já existe")
            self._items[conversation.conversation_id] = conversation

    def get(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock:
            return self._items.get(conversation_id)

    def update(self, conversation: ConversationRecord) -> None:
        with self._lock:
            if conversation.conversation_id not in self._items:
                raise KeyError(conversation.conversation_id)
            self._items[conversation.conversation_id] = conversation

    def latest_for_account(self, account_id: str) -> ConversationRecord | None:
        with self._lock:
            matches = [
                item
                for item in self._items.values()
                if item.account_id == account_id
            ]
            return max(
                matches,
                key=lambda item: (item.last_activity_at, item.conversation_id),
                default=None,
            )


class ProfilePort(Protocol):
    def get_profile(self, account_id: str) -> RiskProfile | None:
        ...


class PolicyPort(Protocol):
    def get_policy(self, account_id: str) -> EligibilityPolicy | None:
        ...


class OpportunityPort(Protocol):
    def list_opportunities(self) -> Iterable[Any]:
        ...


class MarketDataPort(Protocol):
    def read_opportunities(self, *, mode: str = "auto") -> Any:
        ...


class SimulationPort(Protocol):
    def simulate(self, request: Any) -> Any:
        ...


class ConversationError(Exception):
    code = "CONVERSATION_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.retryable = self.retryable if retryable is None else retryable
        self.details = dict(details or {})

    def to_error(self, meta: ApiMeta) -> dict[str, Any]:
        return {
            "error": {"code": self.code, "message": self.message, "details": self.details, "retryable": self.retryable},
            "meta": meta.to_dict(),
        }


class ConversationInputError(ConversationError):
    code = "CONVERSATION_INPUT_INVALID"


class ConversationNotFoundError(ConversationError):
    code = "CONVERSATION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Conversa não encontrada.", code=self.code, retryable=False)


class ConversationConsentError(ConversationError):
    code = "CONSENT_REQUIRED"

    def __init__(self) -> None:
        super().__init__("Consentimento de conversa ativo é obrigatório.", code=self.code, retryable=False)


class ConversationMessageProcessingError(ConversationError):
    code = "MESSAGE_PROCESSING"

    def __init__(self) -> None:
        super().__init__(
            "Uma mensagem com este external_message_id já está em processamento.",
            code=self.code,
            retryable=True,
        )


class WalletIdentityError(ConversationError):
    code = "WALLET_IDENTITY_NOT_SUPPORTED"

    def __init__(self) -> None:
        super().__init__("Wallet não pode ser usada como identidade no MVP.", code=self.code, retryable=False)


@dataclass(frozen=True, slots=True)
class _AssistantResult:
    text: str
    payload: Mapping[str, Any]
    llm: LlmMetadata
    status: ConversationStatus = "active"
    data_sources: tuple[Mapping[str, Any], ...] = ()


class ConversationService:
    """Aura Core conversacional autenticado e sem capacidade de execução."""

    def __init__(
        self,
        *,
        identity: IdentityService | None = None,
        identity_service: IdentityService | None = None,
        repository: ConversationRepository | None = None,
        recommendation_service: RecommendationService | None = None,
        recommendation: RecommendationService | None = None,
        simulation_service: SimulationPort | None = None,
        simulation: SimulationPort | None = None,
        profile_port: ProfilePort | Callable[[str], RiskProfile | None] | None = None,
        policy_port: PolicyPort | Callable[[str], EligibilityPolicy | None] | None = None,
        opportunity_port: OpportunityPort | Callable[[str], Iterable[Any]] | None = None,
        market_data_port: MarketDataPort | None = None,
        llm: LlmPort | None = None,
        faq: FaqPort | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[str], str] | None = None,
        disclaimer: str = DEFAULT_DISCLAIMER,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._identity = identity or identity_service
        if self._identity is None:
            raise ValueError("IdentityService é obrigatório")
        self._repository = repository or InMemoryConversationRepository()
        self._recommendation = recommendation_service or recommendation or RecommendationService()
        self._simulation = simulation_service or simulation
        self._profile_port = profile_port
        self._policy_port = policy_port
        self._opportunity_port = opportunity_port
        self._market_data = market_data_port
        self._llm = llm or DeterministicMockLlm(prompt_version=prompt_version)
        self._faq = faq or DeterministicFaq()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or _new_id
        self._message_lock = threading.RLock()
        self._disclaimer = disclaimer.strip()
        self._prompt_version = prompt_version.strip()
        if not self._disclaimer or not self._prompt_version:
            raise ValueError("disclaimer e prompt_version são obrigatórios")

    def create_conversation(
        self,
        access_token: str,
        channel: ChannelContext | ChannelName | str | None = None,
        consent: Consent | Mapping[str, Any] | None = None,
        *,
        request: ConversationCreateRequest | Mapping[str, Any] | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        channel_identity_id: str | None = None,
    ) -> ConversationResponse:
        create_request = self._coerce_create_request(channel, consent, request)
        resolved = self._resolve(
            access_token,
            channel=create_request.channel,
            request_id=request_id,
            correlation_id=correlation_id,
            channel_identity_id=channel_identity_id,
        )
        _require_consent(create_request.consent)
        now = self._now()
        if create_request.consent.memory:
            existing = self._repository.latest_for_account(
                resolved.account.account_id
            )
            if (
                existing is not None
                and existing.status != "closed"
                and existing.consent.memory
                and _same_consent(existing.consent, create_request.consent)
            ):
                conversation = replace(
                    existing,
                    session=SessionSnapshot.from_identity(resolved),
                    identity=resolved.identity,
                    channel=_resolved_channel(resolved, create_request.channel),
                    last_activity_at=now,
                )
                if create_request.initial_message:
                    message_request = MessageRequest(
                        text=create_request.initial_message,
                        channel=conversation.channel,
                        consent=create_request.consent,
                    )
                    conversation, _ = self._append_message(
                        conversation, resolved, message_request, now=now
                    )
                self._repository.update(conversation)
                return ConversationResponse(conversation, resolved.meta)
        conversation = ConversationRecord(
            conversation_id=self._id_factory("cnv"),
            account_id=resolved.account.account_id,
            session=SessionSnapshot.from_identity(resolved),
            identity=resolved.identity,
            channel=_resolved_channel(resolved, create_request.channel),
            consent=create_request.consent,
            correlation_id=resolved.meta.correlation_id,
            last_activity_at=now,
        )
        self._repository.save(conversation)
        if create_request.initial_message:
            message_request = MessageRequest(
                text=create_request.initial_message,
                channel=conversation.channel,
                consent=create_request.consent,
            )
            conversation, _ = self._append_message(conversation, resolved, message_request, now=now)
            self._repository.update(conversation)
        return ConversationResponse(conversation, resolved.meta)

    start_conversation = create_conversation

    def get_conversation(
        self,
        access_token: str,
        conversation_id: str,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        channel: ChannelContext | ChannelName | str | None = None,
    ) -> ConversationResponse:
        # Autentica antes de revelar se a conversa existe: 401 vem antes de 404.
        self._resolve(access_token, channel=None, request_id=request_id, correlation_id=correlation_id)
        conversation = self._repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError()
        resolved = self._resolve(
            access_token,
            channel=channel,
            request_id=request_id,
            correlation_id=correlation_id or conversation.correlation_id,
        )
        self._authorize(conversation, resolved)
        return ConversationResponse(conversation, resolved.meta)

    def send_message(
        self,
        access_token: str,
        conversation_id: str,
        request: MessageRequest | Mapping[str, Any] | str | None = None,
        *,
        text: str | None = None,
        channel: ChannelContext | ChannelName | str | None = None,
        consent: Consent | Mapping[str, Any] | None = None,
        action: MessageAction | str | None = None,
        simulation: Any | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        channel_identity_id: str | None = None,
    ) -> MessageResponse:
        # Autentica antes de revelar se a conversa existe: 401 vem antes de 404.
        self._resolve(access_token, channel=None, request_id=request_id, correlation_id=correlation_id)
        with self._message_lock:
            conversation = self._repository.get(conversation_id)
            if conversation is None:
                raise ConversationNotFoundError()
            message_request = self._coerce_message_request(
                request,
                text=text,
                channel=channel or conversation.channel,
                consent=consent or conversation.consent,
                action=action,
                simulation=simulation,
            )
            resolved = self._resolve(
                access_token,
                channel=message_request.channel,
                request_id=request_id,
                correlation_id=correlation_id or conversation.correlation_id,
                channel_identity_id=channel_identity_id,
            )
            self._authorize(conversation, resolved)
            _require_same_consent(conversation.consent, message_request.consent)
            _require_consent(message_request.consent)
            if message_request.external_message_id:
                replay = self._idempotent_replay(conversation, message_request.external_message_id, resolved.meta)
                if replay is not None:
                    return replay
            claim_token: str | None = None
            if message_request.external_message_id:
                claim = getattr(self._repository, "claim_external_message", None)
                if callable(claim):
                    claim_result = claim(
                        conversation_id,
                        message_request.external_message_id,
                    )
                    status = str(claim_result.get("status", "processing"))
                    if status == "completed":
                        current = self._repository.get(conversation_id)
                        replay = (
                            self._idempotent_replay(
                                current,
                                message_request.external_message_id,
                                resolved.meta,
                            )
                            if current is not None
                            else None
                        )
                        if replay is not None:
                            return replay
                    if status != "claimed":
                        raise ConversationMessageProcessingError()
                    claim_token = str(claim_result["claim_token"])
            try:
                updated, response = self._append_message(
                    conversation,
                    resolved,
                    message_request,
                    now=self._now(),
                )
                if claim_token is not None and message_request.external_message_id:
                    commit = getattr(self._repository, "commit_claimed_message", None)
                    if not callable(commit):
                        raise RuntimeError("repository idempotente sem commit atômico")
                    commit(
                        updated,
                        message_request.external_message_id,
                        claim_token,
                    )
                else:
                    self._repository.update(updated)
                return response
            except Exception:
                if claim_token is not None and message_request.external_message_id:
                    release = getattr(self._repository, "release_external_message", None)
                    if callable(release):
                        release(
                            conversation_id,
                            message_request.external_message_id,
                            claim_token,
                        )
                raise

    def replay_message(
        self,
        access_token: str,
        conversation_id: str,
        request: MessageRequest,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> MessageResponse | None:
        """Consulta replay autenticado sem invocar provider nem consumir rate limit."""

        if not request.external_message_id:
            return None
        with self._message_lock:
            conversation = self._repository.get(conversation_id)
            if conversation is None:
                raise ConversationNotFoundError()
            resolved = self._resolve(
                access_token,
                channel=request.channel,
                request_id=request_id,
                correlation_id=correlation_id or conversation.correlation_id,
            )
            self._authorize(conversation, resolved)
            _require_same_consent(conversation.consent, request.consent)
            _require_consent(request.consent)
            return self._idempotent_replay(
                conversation,
                request.external_message_id,
                resolved.meta,
            )

    handle_message = send_message
    process_message = send_message

    @staticmethod
    def _idempotent_replay(
        conversation: ConversationRecord,
        external_message_id: str,
        meta: ApiMeta,
    ) -> MessageResponse | None:
        """Reproduz o par original sem chamar provedor nem persistir novamente."""

        for index, message in enumerate(conversation.messages):
            if message.message_type != "user_message" or message.channel.external_message_id != external_message_id:
                continue
            assistant = next(
                (candidate for candidate in conversation.messages[index + 1 :] if candidate.message_type == "assistant_message"),
                None,
            )
            if assistant is None:
                return None
            llm = dict(assistant.payload.get("llm", {}))
            return MessageResponse(
                message,
                assistant,
                meta,
                {
                    "idempotent_replay": True,
                    "fallback_used": bool(assistant.payload.get("fallback_used", False)),
                    "escalation_flag": bool(assistant.payload.get("escalation_flag", False)),
                    "service_status": llm.get("service_status", "not_required"),
                    "failure_code": llm.get("failure_code"),
                    "llm": llm,
                },
            )
        return None

    def _append_message(
        self,
        conversation: ConversationRecord,
        resolved: ResolvedIdentity,
        request: MessageRequest,
        *,
        now: datetime,
    ) -> tuple[ConversationRecord, MessageResponse]:
        if conversation.status == "closed":
            raise ConversationError("A conversa está encerrada.", code="CONVERSATION_CLOSED", retryable=False)
        redacted_user = redact_text(request.text, max_length=4_000)
        safe_request = replace(request, text=redacted_user.text)
        channel = ChannelContext.from_value(
            request.channel,
            external_message_id=request.external_message_id,
        )
        action = safe_request.action or _infer_action(safe_request.text)
        user_payload: dict[str, Any] = {"text": safe_request.text}
        if action:
            user_payload["action"] = action
        user_message = self._envelope(
            resolved,
            conversation,
            message_type="user_message",
            payload=user_payload,
            consent=request.consent,
            channel=channel,
            actor="user",
            occurred_at=now,
            llm={},
            redaction="applied" if redacted_user.applied else "not_required",
        )
        assistant = self._answer(conversation, resolved, safe_request, action)
        redacted_assistant = redact_text(assistant.text, max_length=4_000)
        assistant_payload = dict(assistant.payload)
        assistant_payload["text"] = redacted_assistant.text
        assistant_payload["fallback_used"] = assistant.llm.fallback_used
        assistant_payload["escalation_flag"] = assistant.llm.escalation_flag
        assistant_payload["llm"] = assistant.llm.to_dict()
        assistant_message = self._envelope(
            resolved,
            conversation,
            message_type="assistant_message",
            payload=assistant_payload,
            consent=request.consent,
            channel=channel,
            actor="human_support" if assistant.llm.escalation_flag else "hub",
            occurred_at=now,
            llm=assistant.llm.to_dict(),
            data_sources=assistant.data_sources,
            redaction="applied" if redacted_assistant.applied else "not_required",
        )
        updated = replace(
            conversation,
            session=SessionSnapshot.from_identity(resolved),
            identity=resolved.identity,
            channel=channel,
            consent=request.consent,
            status=assistant.status,
            messages=conversation.messages + (user_message, assistant_message),
            last_activity_at=now,
        )
        metadata = {
            "fallback_used": assistant.llm.fallback_used,
            "escalation_flag": assistant.llm.escalation_flag,
            "service_status": assistant.llm.service_status,
            "failure_code": assistant.llm.failure_code,
            "llm": assistant.llm.to_dict(),
        }
        return updated, MessageResponse(user_message, assistant_message, resolved.meta, metadata)

    def _answer(
        self,
        conversation: ConversationRecord,
        resolved: ResolvedIdentity,
        request: MessageRequest,
        action: str | None,
    ) -> _AssistantResult:
        if action == "request_human":
            text = self._faq_answer(request.text, action=action)
            return _AssistantResult(
                text=_sanitize(text),
                payload={"kind": "human_support", "escalation_available": True},
                llm=self._metadata(fallback="human_support", fallback_used=True, escalation_flag=True),
                status="waiting_human",
            )
        if action in {"simulate"}:
            return self._answer_simulation(request)
        if action in {"recommend", "discover"}:
            return self._answer_recommendation(resolved, conversation, request, action)
        return self._answer_llm(resolved, conversation, request, action)

    def _answer_llm(
        self,
        resolved: ResolvedIdentity,
        conversation: ConversationRecord,
        request: MessageRequest,
        action: str | None,
    ) -> _AssistantResult:
        llm_request = LlmRequest(
            text=request.text,
            account_id=resolved.account.account_id,
            conversation_id=conversation.conversation_id,
            action=action,
            grounding=self._aura_grounding(resolved.account.account_id),
            context=(
                tuple(
                    {
                        "role": (
                            "user"
                            if message.message_type == "user_message"
                            else "assistant"
                        ),
                        "text": str(message.payload.get("text", ""))[:2_000],
                    }
                    for message in conversation.messages[-12:]
                    if message.message_type
                    in {"user_message", "assistant_message"}
                    and str(message.payload.get("text", "")).strip()
                )
                if request.consent.memory
                else ()
            ),
        )
        try:
            raw_result = self._call_llm(llm_request)
            result = raw_result if isinstance(raw_result, LlmResult) else LlmResult(str(raw_result), prompt_version=self._prompt_version)
            if result.mode == "provider":
                _validate_provider_output(result.text)
            text = _sanitize(result.text)
            metadata = LlmMetadata(
                mode=result.mode,
                provider=result.provider,
                model=result.model,
                prompt_version=result.prompt_version,
                explainability="structured" if result.structured else "unavailable",
            )
            return _AssistantResult(
                text=text,
                payload={"kind": "answer", "explanation": list(result.explanation)},
                llm=metadata,
            )
        except Exception as exc:
            text = self._faq_answer(request.text, action=action)
            failure_code = _llm_failure_code(exc)
            return _AssistantResult(
                text=_sanitize(text),
                payload={
                    "kind": "educational_fallback",
                    "fallback_reason": failure_code,
                    "service_status": "unavailable",
                    "escalation_available": True,
                },
                llm=self._metadata(
                    fallback="faq",
                    fallback_used=True,
                    llm_available=False,
                    failure_code=failure_code,
                ),
            )

    _PROFILE_LABELS = {"conservative": "conservador", "moderate": "moderado", "aggressive": "arrojado"}
    _PROFILE_APPETITE = {
        "conservative": {"low"},
        "moderate": {"low", "medium"},
        "aggressive": {"low", "medium", "high"},
    }

    @staticmethod
    def _risk_tier(attributes: Mapping[str, Any]) -> str:
        from services.market_data.presentation import derive_risk_level

        risk = attributes.get("risk")
        level = risk.get("level") if isinstance(risk, Mapping) else None
        if isinstance(level, str) and level and level != "unknown":
            return level
        apy = attributes.get("apy")
        apy_value = apy.get("value") if isinstance(apy, Mapping) else None
        tvl = attributes.get("tvl")
        tvl_value = tvl.get("value") if isinstance(tvl, Mapping) else None
        return derive_risk_level(apy_value, tvl_value, attributes.get("audit_status"))

    @staticmethod
    def _opportunity_head(attributes: Mapping[str, Any]) -> str:
        return " · ".join(
            part
            for part in (str(attributes.get("protocol", "")).strip(), str(attributes.get("asset", "")).strip())
            if part
        )

    def _recommendation_pivot(
        self, profile_missing: bool, opportunities: Sequence[Any], profile: Any = None
    ) -> str:
        from services.market_data.presentation import format_percent

        opps = tuple(opportunities or ())
        if profile_missing:
            options: list[str] = []
            for opp in opps[:3]:
                attrs = getattr(opp, "attributes", None)
                attrs = attrs if isinstance(attrs, Mapping) else {}
                head = self._opportunity_head(attrs)
                apy = attrs.get("apy")
                if head and isinstance(apy, Mapping) and isinstance(apy.get("value"), (int, float)):
                    head += f" ({format_percent(float(apy['value']))})"
                if head:
                    options.append(head)
            listing = f" Agora observo, por exemplo: {'; '.join(options)}." if options else ""
            return (
                "Para eu apoiar melhor a sua decisão, conclua o questionário de perfil de risco na aba Início. "
                "Enquanto isso, já posso explicar os riscos das oportunidades atuais, comparar as opções e simular "
                "cenários educativos." + listing
            )

        raw = str(getattr(profile, "declared_profile", "") or "")
        label = self._PROFILE_LABELS.get(raw, raw or "declarado")
        appetite = self._PROFILE_APPETITE.get(raw)
        matched: list[str] = []
        for opp in opps:
            attrs = getattr(opp, "attributes", None)
            attrs = attrs if isinstance(attrs, Mapping) else {}
            tier = self._risk_tier(attrs)
            if appetite is not None and tier not in appetite:
                continue
            head = self._opportunity_head(attrs)
            if head:
                matched.append(f"{head} (risco {tier})")
            if len(matched) >= 3:
                break

        if matched:
            return (
                f"Perfil {label}. Entre as oportunidades observadas, estas tendem a se alinhar ao seu perfil: "
                + "; ".join(matched)
                + ". Isto é educativo, não é recomendação de investimento. Quer que eu explique os riscos de cada "
                "uma ou compare as opções?"
            )
        return (
            f"Perfil {label}. No momento não observo oportunidades que se enquadrem com folga nesse perfil. Posso "
            "explicar os riscos das opções atuais e comparar os trade-offs de forma educativa. Quer seguir assim?"
        )

    def _answer_recommendation(
        self,
        resolved: ResolvedIdentity,
        conversation: ConversationRecord,
        request: MessageRequest,
        action: str,
    ) -> _AssistantResult:
        if self._recommendation is None:
            return self._pending_answer(request.text, "O serviço de recomendação ainda não está configurado.")
        profile = request.profile if request.profile is not None else self._get_profile(resolved.account.account_id)
        policy = request.policy if request.policy is not None else self._get_policy(resolved.account.account_id)
        opportunities = request.opportunities
        data_sources: tuple[Mapping[str, Any], ...] = ()
        if opportunities is None:
            opportunities, data_sources = self._get_opportunities(resolved.account.account_id)
        recommendation = self._recommendation.recommend(
            profile,
            opportunities,
            policy,
            recommendation_id=self._id_factory("rec"),
            now=self._now(),
        )
        payload = {
            "kind": "recommendation",
            "recommendation": _recommendation_to_dict(recommendation),
        }
        if profile is None or not profile.is_declared or policy is None:
            profile_missing = profile is None or not profile.is_declared
            return _AssistantResult(
                text=_sanitize(self._recommendation_pivot(profile_missing, opportunities, profile)),
                payload={
                    **payload,
                    "kind": "recommendation_pending",
                    "pending": True,
                    "blocker": "PROFILE_REQUIRED" if profile_missing else "ELIGIBILITY_POLICY_REQUIRED",
                    "service_status": "not_required",
                },
                llm=self._metadata(service_status="not_required"),
                data_sources=data_sources,
            )
        if not recommendation.items:
            return _AssistantResult(
                text=_sanitize("Nenhuma oportunidade foi considerada elegível pela política vigente. Posso explicar os motivos e os riscos."),
                payload=payload,
                llm=self._metadata(),
                data_sources=data_sources,
            )
        ids = ", ".join(item.opportunity_id for item in recommendation.items)
        explanation = " ".join(item.rationale[0] for item in recommendation.items if item.rationale)
        text = _sanitize(f"A política vigente identificou {ids} como oportunidade(s) elegível(is) para apoio à decisão. {explanation}")
        return _AssistantResult(text=text, payload=payload, llm=self._metadata(), data_sources=data_sources)

    def _answer_simulation(self, request: MessageRequest) -> _AssistantResult:
        if self._simulation is None or request.simulation is None:
            return _AssistantResult(
                text="Para simular, informe oportunidade, valor hipotético, ativo e horizonte. Nenhuma operação será executada.",
                payload={
                    "kind": "simulation_input_required",
                    "pending": True,
                    "required_inputs": ["opportunity_id", "amount", "asset", "horizons_days"],
                    "service_status": "not_required",
                },
                llm=self._metadata(service_status="not_required"),
            )
        try:
            simulation = self._simulation.simulate(request.simulation)
            payload = {"kind": "simulation", "simulation": simulation.to_dict() if hasattr(simulation, "to_dict") else dict(simulation)}
            return _AssistantResult(
                text=_sanitize("A simulação educativa foi calculada com as premissas informadas. Veja os cenários e os riscos no detalhe."),
                payload=payload,
                llm=self._metadata(),
            )
        except Exception as exc:
            return _AssistantResult(
                text=_sanitize(self._faq_answer(request.text, action="simulate")),
                payload={
                    "kind": "simulation_fallback",
                    "fallback_reason": "SIMULATION_INPUT_INVALID",
                    "service_status": "not_required",
                },
                llm=self._metadata(fallback="faq", fallback_used=True, service_status="not_required"),
            )

    def _pending_answer(self, original_text: str, reason: str) -> _AssistantResult:
        return _AssistantResult(
            text=_sanitize(reason),
            payload={"kind": "pending", "pending": True, "fallback_used": True},
            llm=self._metadata(fallback="faq", fallback_used=True),
        )

    def _envelope(
        self,
        resolved: ResolvedIdentity,
        conversation: ConversationRecord,
        *,
        message_type: Literal["user_message", "assistant_message", "system_event", "alert"],
        payload: Mapping[str, Any],
        consent: Consent,
        channel: ChannelContext,
        actor: Literal["user", "hub", "system", "human_support"],
        occurred_at: datetime,
        llm: Mapping[str, Any],
        data_sources: Sequence[Mapping[str, Any]] = (),
        redaction: Literal["applied", "not_required"] = "not_required",
    ) -> MessageEnvelope:
        return MessageEnvelope(
            envelope_version=ENVELOPE_VERSION,
            message_id=self._id_factory("msg"),
            message_type=message_type,
            occurred_at=occurred_at,
            request_id=resolved.meta.request_id,
            correlation_id=conversation.correlation_id,
            identity=resolved.identity,
            session=SessionSnapshot.from_identity(resolved),
            channel=channel,
            consent=consent,
            payload=payload,
            disclaimer=self._disclaimer,
            audit=AuditMetadata(
                source="hub",
                actor=actor,
                trace_id=resolved.meta.correlation_id,
                redaction=redaction,
                llm=llm,
                data_sources=tuple(data_sources),
            ),
        )

    def _metadata(
        self,
        *,
        fallback: FallbackKind | None = None,
        fallback_used: bool = False,
        escalation_flag: bool = False,
        llm_available: bool = True,
        failure_code: str | None = None,
        service_status: Literal["available", "fallback", "unavailable", "not_required"] | None = None,
    ) -> LlmMetadata:
        resolved_status = service_status or (
            "unavailable"
            if not llm_available
            else "fallback"
            if fallback_used
            else "not_required"
        )
        return LlmMetadata(
            mode="mock",
            provider="mock",
            model="mock-deterministic",
            prompt_version=self._prompt_version,
            fallback=fallback,
            fallback_used=fallback_used,
            escalation_flag=escalation_flag,
            llm_available=llm_available,
            service_status=resolved_status,
            failure_code=failure_code,
        )

    def _call_llm(self, request: LlmRequest) -> LlmResult | str:
        if callable(self._llm):
            return self._llm(request)  # type: ignore[operator]
        complete = getattr(self._llm, "complete", None)
        if callable(complete):
            return complete(request)
        generate = getattr(self._llm, "generate", None)
        if callable(generate):
            return generate(request)
        raise TypeError("A porta LLM precisa implementar complete() ou generate().")

    def _faq_answer(self, text: str, *, action: str | None = None) -> str:
        if callable(self._faq):
            return str(self._faq(text, action=action))  # type: ignore[operator]
        answer = getattr(self._faq, "answer", None)
        if not callable(answer):
            raise TypeError("A porta FAQ precisa implementar answer().")
        return str(answer(text, action=action))

    def _resolve(self, access_token: str, *, channel: ChannelContext | ChannelName | str | None, request_id: str | None, correlation_id: str | None, channel_identity_id: str | None = None) -> ResolvedIdentity:
        return self._identity.resolve_session(
            access_token,
            request_id=request_id,
            correlation_id=correlation_id,
            channel=channel,
            channel_identity_id=channel_identity_id,
        )

    @staticmethod
    def _authorize(conversation: ConversationRecord, resolved: ResolvedIdentity) -> None:
        if conversation.account_id != resolved.account.account_id:
            raise ConversationNotFoundError()

    def _get_profile(self, account_id: str) -> RiskProfile | None:
        if self._profile_port is None:
            return None
        if callable(self._profile_port):
            return self._profile_port(account_id)
        getter = getattr(self._profile_port, "get_profile", None) or getattr(self._profile_port, "get", None)
        return getter(account_id) if callable(getter) else None

    def _get_policy(self, account_id: str) -> EligibilityPolicy | None:
        if self._policy_port is None:
            return None
        if callable(self._policy_port):
            return self._policy_port(account_id)
        getter = getattr(self._policy_port, "get_policy", None) or getattr(self._policy_port, "get", None)
        return getter(account_id) if callable(getter) else None

    def _aura_grounding(self, account_id: str) -> str:
        """Contexto factual (perfil do usuário + mercado observado) para aterrar a Aura.

        Sem esse contexto o provider responde que "não tem acesso a dados de
        mercado em tempo real". Aqui injetamos o perfil declarado e os dados
        observados (fonte DeFiLlama) como verdade verificável, sem inventar
        valores e sem cruzar a fronteira de recomendação personalizada.
        """
        sections: list[str] = []

        profile_section = self._profile_grounding(account_id)
        if profile_section:
            sections.append(profile_section)

        market_section = self._market_grounding_section(account_id)
        if market_section:
            sections.append(market_section)

        return "\n\n".join(sections)

    def _profile_grounding(self, account_id: str) -> str:
        try:
            profile = self._get_profile(account_id)
        except Exception:
            return ""
        if profile is None or not getattr(profile, "is_declared", False):
            return (
                "PERFIL DO USUÁRIO: ainda não declarado. Se ele pedir algo "
                "dependente de perfil, sugira concluir o questionário de risco."
            )
        labels = {
            "conservative": "conservador",
            "moderate": "moderado",
            "aggressive": "arrojado",
        }
        raw = str(getattr(profile, "declared_profile", "") or "")
        label = labels.get(raw, raw or "não informado")
        return (
            f"PERFIL DE RISCO DECLARADO PELO USUÁRIO: {label}. "
            "Ajuste o tom e destaque os riscos e trade-offs relevantes a esse "
            "perfil. Não faça recomendação personalizada de alocação nem diga o "
            "quanto alocar — sugestões pessoais cabem ao serviço dedicado; aqui "
            "você apenas explica e compara de forma educativa."
        )

    def _market_grounding_section(self, account_id: str) -> str:
        from services.market_data.presentation import (
            format_money_compact,
            format_percent,
        )

        try:
            opportunities, data_sources = self._get_opportunities(account_id)
        except Exception:
            return ""
        if not opportunities:
            return ""
        lines: list[str] = []
        for opp in opportunities[:6]:
            attributes = opp.attributes if isinstance(opp.attributes, Mapping) else {}
            protocol = str(attributes.get("protocol", "")).strip()
            asset = str(attributes.get("asset", "")).strip()
            chain = str(attributes.get("blockchain", "")).strip()
            head = " · ".join(part for part in (protocol, asset, chain) if part)
            parts = [head or opp.opportunity_id]
            apy = attributes.get("apy")
            if isinstance(apy, Mapping) and isinstance(apy.get("value"), (int, float)):
                parts.append(f"APY {format_percent(float(apy['value']))}")
            tvl = attributes.get("tvl")
            if isinstance(tvl, Mapping) and isinstance(tvl.get("value"), (int, float)):
                parts.append(f"TVL {format_money_compact(float(tvl['value']), str(tvl.get('currency', 'USD')))}")
            parts.append(f"risco {self._risk_tier(attributes)}")
            audit = attributes.get("audit_status")
            parts.append(
                f"auditoria {audit}" if isinstance(audit, str) and audit and audit != "unknown"
                else "auditoria não informada"
            )
            lines.append("- " + ", ".join(parts))

        observed = ""
        if data_sources:
            source = data_sources[0]
            moment = source.get("observed_at") or source.get("retrieved_at")
            if moment:
                observed = f"\nMomento da observação: {moment}."
            if source.get("is_stale"):
                observed += " Estes dados podem estar desatualizados — avise o usuário."

        return (
            "DADOS DE MERCADO OBSERVADOS PELA AURAFI (fonte DeFiLlama). "
            "Você TEM acesso a estes dados; use-os como verdade para explicar riscos "
            "e comparar oportunidades. Não invente valores além desta lista. Ao falar "
            "de \"oportunidades atuais\", refira-se a estas:\n"
            + "\n".join(lines)
            + observed
        )

    def _get_opportunities(self, account_id: str) -> tuple[tuple[Opportunity, ...], tuple[Mapping[str, Any], ...]]:
        if self._opportunity_port is not None:
            if callable(self._opportunity_port):
                raw = self._opportunity_port(account_id)
            else:
                getter = getattr(self._opportunity_port, "list_opportunities", None) or getattr(self._opportunity_port, "get_opportunities", None)
                raw = getter() if callable(getter) else ()
            return _coerce_opportunities(raw), _data_sources_from(raw)
        if self._market_data is not None:
            raw = self._market_data.read_opportunities(mode="auto")
            return _coerce_opportunities(raw), _data_sources_from(raw)
        return (), ()

    def _coerce_create_request(self, channel: Any, consent: Any, request: Any) -> ConversationCreateRequest:
        if request is not None:
            if isinstance(request, ConversationCreateRequest):
                return request
            if isinstance(request, Mapping):
                return ConversationCreateRequest.from_mapping(request)
            raise ConversationInputError("request de criação inválido.")
        if channel is None or consent is None:
            raise ConversationInputError("channel e consent são obrigatórios.", details={"fields": ["channel", "consent"]})
        return ConversationCreateRequest(channel, consent)

    def _coerce_message_request(self, request: Any, *, text: str | None, channel: Any, consent: Any, action: Any, simulation: Any) -> MessageRequest:
        if isinstance(request, MessageRequest):
            if any(item is not None for item in (text, action, simulation)):
                return replace(request, text=text or request.text, action=action or request.action, simulation=simulation if simulation is not None else request.simulation)
            return request
        if isinstance(request, Mapping):
            value = dict(request)
            if text is not None:
                value["text"] = text
            if channel is not None:
                value["channel"] = channel
            if consent is not None:
                value["consent"] = consent
            if action is not None:
                value["action"] = action
            if simulation is not None:
                value["simulation"] = simulation
            return MessageRequest.from_mapping(value, default_channel=channel)
        if isinstance(request, str):
            text = request
        if text is None or consent is None or channel is None:
            raise ConversationInputError("text, channel e consent são obrigatórios.", details={"fields": ["text", "channel", "consent"]})
        return MessageRequest(text, channel, consent, action=action, simulation=simulation)

    def _now(self) -> datetime:
        return _utc(self._clock())


def _require_consent(consent: Consent) -> None:
    if consent.status != "granted" or consent.purpose not in {"conversation", "decision_support"}:
        raise ConversationConsentError()


def _require_same_consent(authoritative: Consent, presented: Consent) -> None:
    """Impede que o payload da mensagem altere a decisão persistida da conversa."""

    if not _same_consent(authoritative, presented):
        raise ConversationConsentError()


def _same_consent(authoritative: Consent, presented: Consent) -> bool:
    comparable = lambda value: (
        value.purpose,
        value.status,
        value.policy_version,
        value.memory,
        value.analytics,
    )
    return comparable(authoritative) == comparable(presented)


def _resolved_channel(
    resolved: ResolvedIdentity,
    requested: ChannelContext | ChannelName | str | None,
) -> ChannelContext:
    if resolved.channel_association is not None:
        return resolved.channel_association.channel
    if requested is not None:
        return ChannelContext.from_value(requested)
    return ChannelContext.from_value("simulated")


def _reject_wallet_identity(value: Mapping[str, Any]) -> None:
    prohibited = {"wallet", "wallet_id", "wallet_address", "wallet_identity", "open_finance_account"}
    if prohibited.intersection(str(key).casefold() for key in value):
        raise WalletIdentityError()


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _infer_action(text: str) -> str | None:
    normalized = _normalize_text(text)
    if any(term in normalized for term in ("atendente", "humano", "suporte")):
        return "request_human"
    if any(term in normalized for term in ("simular", "simulação", "simulacao")):
        return "simulate"
    if any(term in normalized for term in ("por que", "porque", "risco", "explica o risco", "explicar risco")):
        return "explain_risk"
    if any(term in normalized for term in ("compare", "comparar", "diferença")):
        return "compare"
    if any(term in normalized for term in ("recomend", "aloca", "onde investir", "qual oportunidade")):
        return "recommend"
    return None


def _llm_failure_code(error: Exception) -> str:
    """Classifica a degradação sem expor exceção, credencial ou fornecedor."""

    name = type(error).__name__.casefold()
    message = str(error).casefold()
    if "unsafe provider output" in message:
        return "LLM_OUTPUT_REJECTED"
    if "timeout" in name or "timeout" in message or "timed out" in message:
        return "LLM_TIMEOUT"
    if "rate" in message or "429" in message or "limit" in message:
        return "LLM_RATE_LIMITED"
    return "LLM_UNAVAILABLE"


_GUARANTEE_PATTERNS = (
    (r"\b(retorno|rendimento|lucro|ganho)s?\s+(é|e|será|sera|foi)\s+(garantid[oa]s?|certo[s]?|assegurad[oa]s?)\b", r"\1 não é assegurado"),
    (r"\b(retorno|rendimento|lucro|ganho)s?\s+garantid[oa]s?\b", r"\1 não assegurado"),
    (r"\bsem\s+riscos?\b", "com riscos que precisam ser avaliados"),
    (r"\bsem\s+risco\b", "com risco a avaliar"),
    (r"\b(vai|irá|ira)\s+(render|lucrar|valorizar)\b", "pode ter resultado diferente do esperado"),
    (r"\bcerteza\s+de\s+(retorno|lucro|ganho)\b", r"possibilidade de \1"),
)

_UNSAFE_PROVIDER_OUTPUT = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\b(envie|informe|compartilhe|digite|provide|send|share)\b.{0,80}\b(seed phrase|frase semente|chave privada|private key|senha|password|otp|access token)\b",
        r"\b(transfira|deposite|assine a transa[cç][aã]o|conecte sua carteira|transfer funds|sign the transaction|connect your wallet)\b",
        r"\b0x[a-f0-9]{40}\b",
    )
)


def _validate_provider_output(text: str) -> None:
    if any(pattern.search(text) for pattern in _UNSAFE_PROVIDER_OUTPUT):
        raise ValueError("unsafe provider output")


def _sanitize(text: str) -> str:
    """Remove garantias sem fabricar um resultado positivo."""

    sanitized = text.strip()
    for pattern, replacement in _GUARANTEE_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\bgarantid[oa]s?\b", "sem promessa de retorno", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\bassegurad[oa]s?\b", "sem promessa de retorno", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\bgarantias?\b", "promessas", sanitized, flags=re.IGNORECASE)
    return sanitized or "Não foi possível produzir uma resposta agora. Posso encaminhar para atendimento humano."


def _coerce_opportunities(raw: Any) -> tuple[Opportunity, ...]:
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        items = raw.get("items", raw.values())
    else:
        items = getattr(raw, "items", raw)
    if isinstance(items, Mapping):
        items = items.values()
    result: list[Opportunity] = []
    for item in items:
        if isinstance(item, Opportunity):
            result.append(item)
            continue
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if not isinstance(item, Mapping):
            continue
        risk = item.get("risk", {})
        risk = risk if isinstance(risk, Mapping) else {}
        result.append(
            Opportunity(
                opportunity_id=str(item.get("opportunity_id", item.get("id", ""))),
                risk_level=risk.get("level", item.get("risk_level")),
                risk_dimensions=tuple(risk.get("dimensions", item.get("risk_dimensions", ()))),
                attributes=dict(item),
            )
        )
    return tuple(item for item in result if item.opportunity_id.strip())


def _data_sources_from(raw: Any) -> tuple[Mapping[str, Any], ...]:
    source = getattr(raw, "data_source", None)
    if source is not None and hasattr(source, "to_dict"):
        return (source.to_dict(),)
    return ()


def _recommendation_to_dict(recommendation: Recommendation) -> dict[str, Any]:
    return {
        "recommendation_id": recommendation.recommendation_id,
        "status": _value(recommendation.status),
        "profile_used": _value(recommendation.profile_used) if recommendation.profile_used is not None else None,
        "items": [
            {
                "opportunity_id": item.opportunity_id,
                "suitability": _value(item.suitability),
                "rationale": list(item.rationale),
                "risks": list(item.risks),
                "disclaimer": item.disclaimer,
            }
            for item in recommendation.items
        ],
        "explanation": recommendation.explanation,
        "disclaimer": recommendation.disclaimer,
        "generated_at": _iso(recommendation.generated_at),
        "policy_version": recommendation.policy_version,
        "eligibility": [
            {
                "opportunity_id": decision.opportunity_id,
                "status": _value(decision.status),
                "reason_code": decision.reason_code,
                "reason": decision.reason,
                "policy_version": decision.policy_version,
                "profile_used": _value(decision.profile_used) if decision.profile_used is not None else None,
                "suitability": _value(decision.suitability) if decision.suitability is not None else None,
                "rationale": list(decision.rationale),
                "risks": list(decision.risks),
            }
            for decision in recommendation.eligibility
        ],
    }


__all__ = [
    "AuditMetadata",
    "CONVERSATION_SCHEMA_VERSION",
    "Consent",
    "ConversationCreateRequest",
    "Conversation",
    "ConversationError",
    "ConversationConsentError",
    "ConversationInputError",
    "ConversationNotFoundError",
    "ConversationRecord",
    "ConversationRepository",
    "ConversationRequest",
    "ConversationResponse",
    "ConversationService",
    "DEFAULT_DISCLAIMER",
    "DeterministicFaq",
    "DeterministicMockLlm",
    "ENVELOPE_VERSION",
    "FAQFallback",
    "FaqFallback",
    "FaqPort",
    "InMemoryConversationRepository",
    "LlmMetadata",
    "LLMPort",
    "LlmPort",
    "LlmRequest",
    "LlmResult",
    "LLMRequest",
    "LLMResult",
    "MessageEnvelope",
    "MessageRequest",
    "MessageInput",
    "MessageResponse",
    "MockLlm",
    "PROMPT_VERSION",
    "PolicyPort",
    "ProfilePort",
    "OpportunityPort",
    "MarketDataPort",
    "SessionSnapshot",
    "SimulationPort",
    "UnavailableLlm",
    "WalletIdentityError",
    "ClaudeLlmPort",
    "MockLlmProvider",
]


LLMPort = LlmPort
FAQFallback = DeterministicFaq
Conversation = ConversationRecord
ConversationRequest = ConversationCreateRequest
MessageInput = MessageRequest
LLMRequest = LlmRequest
LLMResult = LlmResult
ClaudeLlmPort = LlmPort
MockLlmProvider = DeterministicMockLlm
