"""Adapter de transporte do canal simulado.

Este módulo é uma borda fina entre um transporte de teste e o Aura Core. Ele
não resolve identidade, não cria sessão e não cria um envelope alternativo:
essas responsabilidades continuam nas portas de identidade e conversação.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Mapping, Protocol

from services.conversation.service import (
    Consent,
    MessageRequest,
    MessageResponse,
)
from services.identity.service import (
    ApiMeta,
    ChannelContext,
    RequestContext,
    UnsupportedChannelError,
)


SIMULATED_CHANNEL = "simulated"
SIMULATED_ADAPTER = "simulated"
AURA_CORE_PORT = "aura-core"


class AuraCorePort(Protocol):
    """Porta mínima usada pelo adapter para entregar uma mensagem ao Hub."""

    def handle_message(
        self,
        access_token: str,
        conversation_id: str,
        request: MessageRequest,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        channel_identity_id: str | None = None,
    ) -> MessageResponse:
        """Processa a mensagem usando a identidade/sessão do Hub."""


class SimulatedChannelError(Exception):
    """Erro seguro e serializável da borda do canal simulado."""

    code = "SIMULATED_CHANNEL_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
        retryable: bool | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.details = dict(details or {})
        self.retryable = self.retryable if retryable is None else retryable
        self.request_id = request_id
        self.correlation_id = correlation_id

    def to_error(
        self,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Retorna o formato seguro compatível com ``ErrorResponse``."""

        context = RequestContext.create(
            request_id or self.request_id,
            correlation_id or self.correlation_id,
            now=now or datetime.now(timezone.utc),
        )
        meta = ApiMeta.from_context(context).to_dict()
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": dict(self.details),
                "retryable": self.retryable,
            },
            "meta": meta,
        }


class SimulatedChannelInputError(SimulatedChannelError):
    """Entrada de transporte ausente ou incompatível com o adapter."""

    code = "SIMULATED_CHANNEL_INPUT_INVALID"


@dataclass(frozen=True, slots=True)
class SimulatedTransportMessage:
    """Comando de transporte recebido pelo canal simulado.

    ``access_token`` é usado somente para delegação e nunca é incluído em
    ``to_dict`` ou em qualquer envelope. Conta e sessão também não são campos
    de entrada: o Hub os resolve a partir do token de sessão.
    """

    access_token: str
    conversation_id: str
    text: str
    consent: Consent | Mapping[str, Any]
    channel: str | ChannelContext = SIMULATED_CHANNEL
    request_id: str | None = None
    correlation_id: str | None = None
    channel_identity_id: str | None = None
    external_message_id: str | None = None
    action: str | None = None
    simulation: Any | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SimulatedTransportMessage":
        if not isinstance(value, Mapping):
            raise SimulatedChannelInputError(
                "A mensagem do transporte deve ser um objeto.",
                details={"field": "message"},
            )
        prohibited = {
            "wallet",
            "wallet_id",
            "wallet_address",
            "wallet_identity",
            "open_finance_account",
        }
        if prohibited.intersection(str(key).casefold() for key in value):
            raise SimulatedChannelInputError(
                "Wallet não pode ser usada como identidade no MVP.",
                code="WALLET_IDENTITY_NOT_SUPPORTED",
                details={"field": "identity"},
            )
        required = ("access_token", "conversation_id", "text", "channel", "consent")
        missing = [field for field in required if field not in value]
        if missing:
            raise SimulatedChannelInputError(
                "A mensagem simulada possui campos obrigatórios ausentes.",
                details={"fields": missing},
            )
        return cls(
            access_token=value["access_token"],
            conversation_id=value["conversation_id"],
            text=value["text"],
            consent=value["consent"],
            channel=value.get("channel", SIMULATED_CHANNEL),
            request_id=value.get("request_id"),
            correlation_id=value.get("correlation_id"),
            channel_identity_id=value.get("channel_identity_id"),
            external_message_id=value.get("external_message_id"),
            action=value.get("action"),
            simulation=value.get("simulation"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Representação de fixture sem credencial ou segredo de sessão."""

        channel = self.channel.to_dict() if isinstance(self.channel, ChannelContext) else self.channel
        consent = self.consent.to_dict() if isinstance(self.consent, Consent) else dict(self.consent)
        result: dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "text": self.text,
            "channel": channel,
            "consent": consent,
        }
        for key in (
            "request_id",
            "correlation_id",
            "channel_identity_id",
            "external_message_id",
            "action",
            "simulation",
        ):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


class DeterministicIdFactory:
    """Gera IDs estáveis e legíveis para fixtures e demonstrações."""

    def __init__(self, prefix: str = "fixture") -> None:
        if not prefix or not prefix.strip():
            raise ValueError("prefix deve ser não vazio")
        self._prefix = prefix.strip()
        self._counters: dict[str, int] = {}

    def __call__(self, kind: str) -> str:
        if not kind or not kind.strip():
            raise ValueError("kind deve ser não vazio")
        normalized = kind.strip()
        next_value = self._counters.get(normalized, 0) + 1
        self._counters[normalized] = next_value
        return f"{normalized}_{self._prefix}_{next_value:03d}"


class SimulatedChannelAdapter:
    """Entrega comandos simulados ao Aura Core por uma porta explícita.

    O adapter aceita somente o canal lógico ``simulated``. A resolução de
    sessão, associação de canal, autorização da conversa e produção do
    envelope ficam no ``ConversationService``/``IdentityService`` recebido
    pela porta.
    """

    def __init__(
        self,
        core: AuraCorePort | None = None,
        *,
        core_port: AuraCorePort | None = None,
        deterministic: bool = False,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        if core is not None and core_port is not None and core is not core_port:
            raise ValueError("Informe apenas uma porta do Aura Core")
        resolved_core = core or core_port
        if resolved_core is None:
            raise ValueError("A porta do Aura Core é obrigatória")
        if deterministic and id_factory is None:
            id_factory = DeterministicIdFactory()
        self._core = resolved_core
        self._id_factory = id_factory if deterministic else None

    def receive(
        self,
        message: SimulatedTransportMessage | Mapping[str, Any],
    ) -> MessageResponse:
        """Recebe uma mensagem e retorna a resposta canônica do Hub."""

        transport = self._coerce_message(message)
        self._validate_channel(transport.channel)
        request_id = transport.request_id or self._new_transport_id("req")
        correlation_id = transport.correlation_id or self._new_transport_id("cor")
        external_message_id = transport.external_message_id
        if isinstance(transport.channel, ChannelContext):
            external_message_id = external_message_id or transport.channel.external_message_id

        request = MessageRequest(
            text=transport.text,
            channel=ChannelContext.from_value(
                SIMULATED_CHANNEL,
                adapter=SIMULATED_ADAPTER,
                external_message_id=external_message_id,
            ),
            consent=transport.consent,
            action=transport.action,
            simulation=transport.simulation,
            external_message_id=external_message_id,
        )
        response = self._core.handle_message(
            transport.access_token,
            transport.conversation_id,
            request,
            request_id=request_id,
            correlation_id=correlation_id,
            channel_identity_id=transport.channel_identity_id,
        )
        self._validate_response(
            response,
            request_id=request_id,
            correlation_id=transport.correlation_id,
            external_message_id=external_message_id,
        )
        return response

    handle = receive
    handle_message = receive
    process_message = receive
    send = receive

    def _new_transport_id(self, kind: str) -> str | None:
        return self._id_factory(kind) if self._id_factory is not None else None

    @staticmethod
    def _coerce_message(
        message: SimulatedTransportMessage | Mapping[str, Any],
    ) -> SimulatedTransportMessage:
        if isinstance(message, SimulatedTransportMessage):
            return message
        return SimulatedTransportMessage.from_mapping(message)

    @staticmethod
    def _validate_channel(channel: str | ChannelContext) -> None:
        if isinstance(channel, ChannelContext):
            if channel.name != SIMULATED_CHANNEL:
                raise UnsupportedChannelError()
            return
        if not isinstance(channel, str) or channel != SIMULATED_CHANNEL:
            raise UnsupportedChannelError()

    @staticmethod
    def _validate_response(
        response: MessageResponse,
        *,
        request_id: str | None,
        correlation_id: str | None,
        external_message_id: str | None,
    ) -> None:
        if not isinstance(response, MessageResponse):
            raise SimulatedChannelError(
                "A porta do Aura Core retornou uma resposta inválida.",
                code="AURA_CORE_RESPONSE_INVALID",
                details={"expected": "MessageResponse"},
                retryable=True,
            )
        user = response.user_message
        assistant = response.assistant_message
        if user.channel.name != SIMULATED_CHANNEL or assistant.channel.name != SIMULATED_CHANNEL:
            raise SimulatedChannelError(
                "O Aura Core retornou uma mensagem fora do canal simulado.",
                code="CHANNEL_CONTEXT_MISMATCH",
                details={"expected_channel": SIMULATED_CHANNEL},
            )
        if not user.channel.simulated or not assistant.channel.simulated:
            raise SimulatedChannelError(
                "O envelope do canal simulado deve marcar simulated=true.",
                code="CHANNEL_CONTEXT_MISMATCH",
            )
        if user.request_id != assistant.request_id or user.correlation_id != assistant.correlation_id:
            raise SimulatedChannelError(
                "A resposta perdeu o contexto de correlação entre as mensagens.",
                code="MESSAGE_CONTEXT_LOST",
                details={"context": ["request_id", "correlation_id"]},
            )
        if user.identity != assistant.identity or user.session != assistant.session:
            raise SimulatedChannelError(
                "A resposta perdeu identidade ou sessão entre as mensagens.",
                code="MESSAGE_CONTEXT_LOST",
                details={"context": ["identity", "session"]},
            )
        if request_id is not None and user.request_id != request_id:
            raise SimulatedChannelError(
                "request_id não foi preservado pelo Aura Core.",
                code="MESSAGE_CONTEXT_LOST",
                details={"context": ["request_id"]},
            )
        if correlation_id is not None and user.correlation_id != correlation_id:
            raise SimulatedChannelError(
                "correlation_id não foi preservado pelo Aura Core.",
                code="MESSAGE_CONTEXT_LOST",
                details={"context": ["correlation_id"]},
            )
        if external_message_id is not None:
            for envelope in (user, assistant):
                if envelope.channel.external_message_id != external_message_id:
                    raise SimulatedChannelError(
                        "external_message_id não foi preservado pelo Aura Core.",
                        code="MESSAGE_CONTEXT_LOST",
                        details={"context": ["external_message_id"]},
                    )


@dataclass(slots=True)
class SimulatedTransportFixture:
    """Transporte em memória para testes e a prova E2E de dois canais.

    O fixture não simula um fornecedor externo. Ele apenas enfileira comandos,
    entrega-os ao adapter e captura as respostas canônicas produzidas pelo Hub.
    """

    deterministic: bool = True
    id_factory: Callable[[str], str] | None = None
    _inbound: Deque[SimulatedTransportMessage] = field(default_factory=deque, init=False)
    _outbound: list[MessageResponse] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.deterministic and self.id_factory is None:
            self.id_factory = DeterministicIdFactory()

    @property
    def inbound(self) -> tuple[SimulatedTransportMessage, ...]:
        return tuple(self._inbound)

    @property
    def outbound(self) -> tuple[MessageResponse, ...]:
        return tuple(self._outbound)

    def enqueue(
        self,
        message: SimulatedTransportMessage | Mapping[str, Any],
    ) -> SimulatedTransportMessage:
        prepared = self._prepare(message)
        self._inbound.append(prepared)
        return prepared

    def send(
        self,
        adapter: SimulatedChannelAdapter,
        message: SimulatedTransportMessage | Mapping[str, Any],
    ) -> MessageResponse:
        prepared = self._prepare(message)
        response = adapter.receive(prepared)
        self._outbound.append(response)
        return response

    def drain(self, adapter: SimulatedChannelAdapter) -> tuple[MessageResponse, ...]:
        responses: list[MessageResponse] = []
        while self._inbound:
            message = self._inbound.popleft()
            response = adapter.receive(message)
            self._outbound.append(response)
            responses.append(response)
        return tuple(responses)

    def _prepare(
        self,
        message: SimulatedTransportMessage | Mapping[str, Any],
    ) -> SimulatedTransportMessage:
        if isinstance(message, SimulatedTransportMessage):
            prepared = message
        else:
            prepared = SimulatedTransportMessage.from_mapping(message)
        if self.id_factory is None:
            return prepared
        return replace(
            prepared,
            request_id=prepared.request_id or self.id_factory("req"),
            correlation_id=prepared.correlation_id or self.id_factory("cor"),
        )


__all__ = [
    "AURA_CORE_PORT",
    "SIMULATED_CHANNEL",
    "SIMULATED_ADAPTER",
    "AuraCorePort",
    "DeterministicIdFactory",
    "SimulatedChannelError",
    "SimulatedChannelInputError",
    "SimulatedChannelAdapter",
    "SimulatedTransportFixture",
    "SimulatedTransportMessage",
]
