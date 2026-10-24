"""Contagem agregada da origem dos cadastros, sem dado pessoal.

Só três parâmetros de campanha entram (fonte, meio e campanha), e cada um é
comparado com a lista fechada da convenção de origem: um valor fora da lista
vira ``outro`` e um valor ausente vira ``direto``. Nenhum texto livre é
gravado, nem o que a pessoa digitou no link.

O resultado é um contador por semana (segunda-feira, em UTC) e por combinação
de fonte, meio e campanha, com duas somas: pedidos de código que podem abrir
uma conta e contas criadas. Não há conta, e-mail, IP, cookie nem instante mais
preciso que a semana, e a origem nunca é gravada junto do pedido de código ou
da conta. A fonte ``teste`` é reservada para ensaios e fica fora dos
relatórios.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import threading
from typing import Any, Mapping, Protocol

DIRECT = "direto"
OTHER = "outro"
TEST_SOURCE = "teste"

SOURCES = frozenset(
    {
        "perfil_a",
        "perfil_b",
        "perfil_c",
        "perfil_d",
        "google",
        "meta",
        "youtube",
        "x",
        "linkedin",
        "tiktok",
        "podcast",
        TEST_SOURCE,
    }
)
MEDIUMS = frozenset(
    {
        "influenciador",
        "busca_paga",
        "video_pago",
        "social_pago",
        "social_organico",
        "video_organico",
        "indicacao",
    }
)
CAMPAIGNS = frozenset({"entenda_onda1", "entenda_onda2", "piloto_onda3"})

# Parâmetro do link -> valores aceitos. Qualquer outro parâmetro é ignorado.
FIELDS: tuple[tuple[str, frozenset[str]], ...] = (
    ("utm_source", SOURCES),
    ("utm_medium", MEDIUMS),
    ("utm_campaign", CAMPAIGNS),
)
# Nenhum valor da convenção passa disso; um texto maior nem é examinado.
MAX_VALUE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class Attribution:
    """Origem já normalizada: só valores da lista, ``direto`` ou ``outro``."""

    source: str = DIRECT
    medium: str = DIRECT
    campaign: str = DIRECT


def normalize_attribution(value: Any) -> Attribution:
    """Reduz o objeto enviado pelo site à convenção, sem nunca rejeitar o pedido.

    Sem objeto, tudo é ``direto``; um objeto malformado conta como ``outro``.
    """

    if value is None:
        return Attribution()
    if not isinstance(value, Mapping):
        return Attribution(OTHER, OTHER, OTHER)
    source, medium, campaign = (_normalize(value.get(name), accepted) for name, accepted in FIELDS)
    return Attribution(source, medium, campaign)


def _normalize(raw: Any, accepted: frozenset[str]) -> str:
    if raw is None:
        return DIRECT
    if not isinstance(raw, str) or len(raw) > MAX_VALUE_LENGTH:
        return OTHER
    candidate = raw.strip().casefold()
    if not candidate:
        return DIRECT
    return candidate if candidate in accepted else OTHER


def week_start(moment: datetime) -> date:
    """Segunda-feira, em UTC, da semana do instante."""

    utc = moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    day = utc.date()
    return day - timedelta(days=day.weekday())


class AcquisitionStore(Protocol):
    """Implementada pelos repositórios SQLite e PostgreSQL e pelo modo em memória."""

    def record_acquisition(
        self,
        week: date,
        source: str,
        medium: str,
        campaign: str,
        *,
        code_requests: int = 0,
        accounts_created: int = 0,
    ) -> None: ...

    def list_acquisition_counts(self) -> list[dict[str, Any]]: ...


def check_counts(source: str, medium: str, campaign: str, code_requests: int, accounts_created: int) -> None:
    """Barreira dos repositórios: só valores da convenção e somas não negativas."""

    for value, accepted in ((source, SOURCES), (medium, MEDIUMS), (campaign, CAMPAIGNS)):
        if value not in accepted and value not in (DIRECT, OTHER):
            raise ValueError("valor fora da convenção de origem")
    if code_requests < 0 or accounts_created < 0 or code_requests + accounts_created == 0:
        raise ValueError("a contagem soma pelo menos um pedido ou uma conta")


class InMemoryAcquisitionCounter:
    """Contagem do modo sem banco (desenvolvimento e testes)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str, str], list[int]] = {}

    def record_acquisition(
        self,
        week: date,
        source: str,
        medium: str,
        campaign: str,
        *,
        code_requests: int = 0,
        accounts_created: int = 0,
    ) -> None:
        check_counts(source, medium, campaign, code_requests, accounts_created)
        key = (week.isoformat(), source, medium, campaign)
        with self._lock:
            totals = self._rows.setdefault(key, [0, 0])
            totals[0] += code_requests
            totals[1] += accounts_created

    def list_acquisition_counts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "week_start": week,
                    "utm_source": source,
                    "utm_medium": medium,
                    "utm_campaign": campaign,
                    "code_requests": totals[0],
                    "accounts_created": totals[1],
                }
                for (week, source, medium, campaign), totals in sorted(self._rows.items())
            ]
