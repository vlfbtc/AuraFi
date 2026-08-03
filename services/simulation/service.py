"""Serviço de domínio para projeções de simulação sem execução financeira.

O serviço valida a entrada, delega o cálculo a uma estratégia versionada e
monta uma resposta estável para os consumidores. Ele não conhece fórmula de
produção, câmbio, slippage, taxas ou qualquer mecanismo de execução.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Protocol, TypeAlias
from uuid import uuid4


ALLOWED_HORIZONS_DAYS = (30, 180, 365)
DEFAULT_DISCLAIMER = (
    "Simulação educativa: não constitui promessa ou garantia de retorno, "
    "recomendação personalizada, ordem ou execução de transação."
)

DecimalLike: TypeAlias = Decimal | int | float | str


class SimulationError(Exception):
    """Erro de domínio serializável e seguro para consumidores da simulação."""

    code = "SIMULATION_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})
        if retryable is not None:
            self.retryable = retryable
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        """Retorna o formato equivalente a ``ErrorDetail`` do contrato."""

        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }


class SimulationInputError(SimulationError):
    """Entrada ausente ou inválida, sem efeitos colaterais."""

    code = "SIMULATION_INPUT_INVALID"


class SimulationConfigurationError(SimulationError):
    """Fórmula não configurada conforme o contrato interno do serviço."""

    code = "SIMULATION_FORMULA_INVALID"


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    """Entrada de domínio; ``amount`` corresponde ao principal da simulação."""

    opportunity_id: str
    amount: DecimalLike
    asset: str
    apy: DecimalLike | Mapping[str, Any] | None
    horizons_days: Sequence[int]
    compare_idle_stablecoin: bool = True
    assumptions: Sequence[str] = ()
    data_source: Mapping[str, Any] | None = None

    @property
    def principal(self) -> DecimalLike:
        """Alias semântico para o campo ``amount`` do contrato OpenAPI."""

        return self.amount

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SimulationRequest":
        """Cria uma entrada a partir de payload JSON sem perder erros estruturados."""

        if "amount" in value and "principal" in value:
            raise SimulationInputError(
                "Informe apenas um valor para o principal.",
                details={"field": "amount", "aliases": ["amount", "principal"]},
            )

        amount = value.get("amount", value.get("principal"))
        required = {
            "opportunity_id": value.get("opportunity_id"),
            "amount": amount,
            "asset": value.get("asset"),
            "horizons_days": value.get("horizons_days"),
        }
        missing = [field for field, item in required.items() if item is None]
        if missing:
            raise SimulationInputError(
                "A entrada da simulação possui campos obrigatórios ausentes.",
                details={"fields": missing},
            )

        return cls(
            opportunity_id=required["opportunity_id"],
            amount=required["amount"],
            asset=required["asset"],
            apy=value.get("apy"),
            horizons_days=required["horizons_days"],
            compare_idle_stablecoin=value.get("compare_idle_stablecoin", True),
            assumptions=value.get("assumptions", ()),
            data_source=value.get("data_source"),
        )


@dataclass(frozen=True, slots=True)
class FormulaProjection:
    """Saída mínima que uma fórmula injetada precisa fornecer."""

    projected_value: DecimalLike
    projected_yield: DecimalLike
    idle_stablecoin_value: DecimalLike | None = None


class FormulaStrategy(Protocol):
    """Contrato de uma fórmula de produção fornecida pelo integrador."""

    formula_version: str
    assumptions: Sequence[str]

    def project(
        self,
        *,
        principal: Decimal,
        apy: Decimal,
        horizon_days: int,
    ) -> FormulaProjection:
        """Calcula um cenário; não executa nem solicita transações."""


@dataclass(frozen=True, slots=True)
class SimulationScenario:
    """Cenário calculado por uma fórmula injetada."""

    horizon_days: int
    projected_value: Decimal
    projected_yield: Decimal
    currency: str
    idle_stablecoin_value: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "horizon_days": self.horizon_days,
            "projected_value": _number_for_json(self.projected_value),
            "projected_yield": _number_for_json(self.projected_yield),
            "currency": self.currency,
        }
        if self.idle_stablecoin_value is not None:
            result["idle_stablecoin_value"] = _number_for_json(
                self.idle_stablecoin_value
            )
        return result


@dataclass(frozen=True, slots=True)
class Simulation:
    """Resposta versionada e deliberadamente incapaz de representar execução."""

    simulation_id: str
    opportunity_id: str
    input: SimulationRequest
    scenarios: tuple[SimulationScenario, ...]
    assumptions: tuple[str, ...]
    formula_version: str
    generated_at: datetime
    disclaimer: str = DEFAULT_DISCLAIMER
    execution_supported: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, Any]:
        """Serializa para um payload próximo ao ``Simulation`` do OpenAPI."""

        input_payload: dict[str, Any] = {
            "opportunity_id": self.input.opportunity_id,
            "amount": _number_for_json(_to_decimal(self.input.amount, "amount")),
            "asset": self.input.asset,
            "horizons_days": list(self.input.horizons_days),
            "compare_idle_stablecoin": self.input.compare_idle_stablecoin,
        }
        result: dict[str, Any] = {
            "simulation_id": self.simulation_id,
            "opportunity_id": self.opportunity_id,
            "input": input_payload,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "assumptions": list(self.assumptions),
            "formula_version": self.formula_version,
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "execution_supported": False,
            "disclaimer": self.disclaimer,
        }
        if self.input.data_source is not None:
            result["data_source"] = dict(self.input.data_source)
        return result


class SimulationService:
    """Orquestra validação e cálculo sem possuir uma fórmula oficial própria."""

    def __init__(
        self,
        formula: FormulaStrategy,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        disclaimer: str = DEFAULT_DISCLAIMER,
    ) -> None:
        self._validate_formula_configuration(formula)
        if not isinstance(disclaimer, str) or not disclaimer.strip():
            raise SimulationConfigurationError(
                "O disclaimer obrigatório não pode ser vazio.",
                details={"field": "disclaimer"},
            )
        self._formula = formula
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._disclaimer = disclaimer.strip()

    def simulate(
        self, request: SimulationRequest | Mapping[str, Any]
    ) -> Simulation:
        """Gera os cenários solicitados e nunca expõe uma operação de execução."""

        normalized_request = self._normalize_request(request)
        principal = _to_decimal(
            normalized_request.amount,
            "amount",
            error_code="SIMULATION_PRINCIPAL_INVALID",
        )
        if principal <= 0:
            raise SimulationInputError(
                "O principal deve ser maior que zero.",
                details={"field": "amount", "minimum_exclusive": 0},
                code="SIMULATION_PRINCIPAL_INVALID",
            )
        apy = _to_apy(normalized_request.apy)
        horizons = _validate_horizons(normalized_request.horizons_days)
        opportunity_id = _required_text(
            normalized_request.opportunity_id, "opportunity_id"
        )
        asset = _required_text(normalized_request.asset, "asset")
        compare_idle = _validate_bool(
            normalized_request.compare_idle_stablecoin,
            "compare_idle_stablecoin",
        )
        request_assumptions = _validate_assumptions(normalized_request.assumptions)

        scenarios: list[SimulationScenario] = []
        for horizon_days in horizons:
            try:
                projection = self._formula.project(
                    principal=principal,
                    apy=apy,
                    horizon_days=horizon_days,
                )
            except SimulationError:
                raise
            except Exception as exc:  # pragma: no cover - depends on injected code
                raise SimulationError(
                    "A fórmula configurada não conseguiu calcular o cenário.",
                    details={"horizon_days": horizon_days},
                    code="SIMULATION_FORMULA_FAILED",
                ) from exc

            scenarios.append(
                self._scenario_from_projection(
                    projection=projection,
                    horizon_days=horizon_days,
                    asset=asset,
                    compare_idle_stablecoin=compare_idle,
                )
            )

        assumptions = tuple(
            request_assumptions
            + _validate_assumptions(self._formula.assumptions, field="formula.assumptions")
        )
        generated_at = self._clock()
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        generated_at = generated_at.astimezone(UTC)

        return Simulation(
            simulation_id=str(self._id_factory()),
            opportunity_id=opportunity_id,
            input=SimulationRequest(
                opportunity_id=opportunity_id,
                amount=principal,
                asset=asset,
                apy=apy,
                horizons_days=horizons,
                compare_idle_stablecoin=compare_idle,
                assumptions=request_assumptions,
                data_source=normalized_request.data_source,
            ),
            scenarios=tuple(scenarios),
            assumptions=assumptions,
            formula_version=self._formula.formula_version.strip(),
            generated_at=generated_at,
            disclaimer=self._disclaimer,
        )

    def _normalize_request(
        self, request: SimulationRequest | Mapping[str, Any]
    ) -> SimulationRequest:
        if isinstance(request, SimulationRequest):
            return request
        if isinstance(request, Mapping):
            return SimulationRequest.from_mapping(request)
        raise SimulationInputError(
            "A entrada da simulação deve ser um payload mapeável.",
            details={"field": "request", "received_type": type(request).__name__},
        )

    @staticmethod
    def _validate_formula_configuration(formula: FormulaStrategy) -> None:
        if formula is None:
            raise SimulationConfigurationError(
                "Uma fórmula versionada deve ser fornecida ao serviço.",
                details={"field": "formula"},
            )
        version = getattr(formula, "formula_version", None)
        project = getattr(formula, "project", None)
        assumptions = getattr(formula, "assumptions", None)
        if not isinstance(version, str) or not version.strip():
            raise SimulationConfigurationError(
                "A fórmula fornecida precisa declarar formula_version.",
                details={"field": "formula.formula_version"},
            )
        if not callable(project):
            raise SimulationConfigurationError(
                "A fórmula fornecida precisa implementar project().",
                details={"field": "formula.project"},
            )
        if assumptions is None:
            raise SimulationConfigurationError(
                "A fórmula fornecida precisa declarar suas premissas.",
                details={"field": "formula.assumptions"},
            )
        if (
            isinstance(assumptions, (str, bytes))
            or not isinstance(assumptions, Sequence)
            or not assumptions
            or any(not isinstance(item, str) or not item.strip() for item in assumptions)
        ):
            raise SimulationConfigurationError(
                "A fórmula fornecida precisa declarar ao menos uma premissa válida.",
                details={"field": "formula.assumptions"},
            )

    @staticmethod
    def _scenario_from_projection(
        *,
        projection: FormulaProjection,
        horizon_days: int,
        asset: str,
        compare_idle_stablecoin: bool,
    ) -> SimulationScenario:
        if not isinstance(projection, FormulaProjection):
            raise SimulationError(
                "A fórmula retornou uma projeção em formato inválido.",
                details={"horizon_days": horizon_days, "expected": "FormulaProjection"},
                code="FORMULA_OUTPUT_INVALID",
            )
        projected_value = _to_decimal(
            projection.projected_value,
            "projected_value",
            error_code="FORMULA_OUTPUT_INVALID",
        )
        projected_yield = _to_decimal(
            projection.projected_yield,
            "projected_yield",
            error_code="FORMULA_OUTPUT_INVALID",
        )
        idle_value: Decimal | None = None
        if compare_idle_stablecoin:
            if projection.idle_stablecoin_value is None:
                raise SimulationError(
                    "A fórmula não forneceu a comparação com stablecoin parada.",
                    details={"field": "idle_stablecoin_value", "horizon_days": horizon_days},
                    code="FORMULA_OUTPUT_INVALID",
                )
            idle_value = _to_decimal(
                projection.idle_stablecoin_value,
                "idle_stablecoin_value",
                error_code="FORMULA_OUTPUT_INVALID",
            )
        elif projection.idle_stablecoin_value is not None:
            idle_value = _to_decimal(
                projection.idle_stablecoin_value,
                "idle_stablecoin_value",
                error_code="FORMULA_OUTPUT_INVALID",
            )

        return SimulationScenario(
            horizon_days=horizon_days,
            projected_value=_require_non_negative(
                projected_value, "projected_value", "FORMULA_OUTPUT_INVALID"
            ),
            projected_yield=projected_yield,
            currency=asset,
            idle_stablecoin_value=(
                _require_non_negative(
                    idle_value, "idle_stablecoin_value", "FORMULA_OUTPUT_INVALID"
                )
                if idle_value is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class AssumptionFixtureFormula:
    """Fórmula determinística somente para testes/demonstrações controladas.

    [ASSUNÇÃO] Usa rendimento anualizado linear proporcional a dias/365 e
    considera a stablecoin parada sem rendimento. Não é fórmula oficial de
    produção nem recomendação financeira.
    """

    formula_version: str = "fixture-assumption-linear-v1"
    assumptions: tuple[str, ...] = (
        "[ASSUNÇÃO] O APY é tratado como percentual anualizado e aplicado de forma linear por dias/365.",
        "[ASSUNÇÃO] A comparação com stablecoin parada considera rendimento zero e preservação do principal.",
        "[ASSUNÇÃO] projected_yield representa o percentual acumulado do cenário.",
    )

    def project(
        self,
        *,
        principal: Decimal,
        apy: Decimal,
        horizon_days: int,
    ) -> FormulaProjection:
        projected_yield = apy * Decimal(horizon_days) / Decimal(365)
        projected_value = principal * (
            Decimal("1") + projected_yield / Decimal(100)
        )
        return FormulaProjection(
            projected_value=projected_value,
            projected_yield=projected_yield,
            idle_stablecoin_value=principal,
        )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SimulationInputError(
            f"O campo {field} é obrigatório e deve ser texto não vazio.",
            details={"field": field},
        )
    return value.strip()


def _to_decimal(
    value: Any,
    field: str,
    *,
    error_code: str = "SIMULATION_INPUT_INVALID",
) -> Decimal:
    if isinstance(value, bool) or value is None:
        _raise_numeric_error(value, field, error_code)
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        _raise_numeric_error(value, field, error_code)
    if not decimal_value.is_finite():
        _raise_numeric_error(value, field, error_code)
    return decimal_value


def _raise_numeric_error(value: Any, field: str, code: str) -> None:
    raise SimulationInputError(
        f"O campo {field} deve ser um número finito.",
        details={"field": field, "received_type": type(value).__name__},
        code=code,
    )


def _require_non_negative(value: Decimal, field: str, code: str) -> Decimal:
    if value < 0:
        raise SimulationError(
            f"A fórmula retornou {field} negativo.",
            details={"field": field},
            code=code,
        )
    return value


def _to_apy(value: DecimalLike | Mapping[str, Any] | None) -> Decimal:
    if value is None:
        raise SimulationInputError(
            "APY é obrigatório para gerar uma simulação.",
            details={"field": "apy"},
            code="SIMULATION_APY_REQUIRED",
        )
    if isinstance(value, Mapping):
        unit = value.get("unit")
        if unit != "percent_annualized" or "value" not in value:
            raise SimulationInputError(
                "APY deve informar value e unit=percent_annualized.",
                details={"field": "apy", "expected_unit": "percent_annualized"},
                code="SIMULATION_APY_INVALID",
            )
        value = value["value"]
    apy = _to_decimal(value, "apy", error_code="SIMULATION_APY_INVALID")
    if apy < 0:
        raise SimulationInputError(
            "APY não pode ser negativo.",
            details={"field": "apy", "minimum": 0},
            code="SIMULATION_APY_INVALID",
        )
    return apy


def _validate_horizons(value: Sequence[int]) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SimulationInputError(
            "horizons_days deve ser uma lista de inteiros.",
            details={"field": "horizons_days"},
            code="SIMULATION_HORIZONS_INVALID",
        )
    if not 1 <= len(value) <= 3:
        raise SimulationInputError(
            "Informe entre um e três horizontes de simulação.",
            details={"field": "horizons_days", "min_items": 1, "max_items": 3},
            code="SIMULATION_HORIZONS_INVALID",
        )
    invalid = [
        horizon
        for horizon in value
        if isinstance(horizon, bool) or not isinstance(horizon, int)
        or horizon not in ALLOWED_HORIZONS_DAYS
    ]
    if invalid:
        raise SimulationInputError(
            "Há horizontes não permitidos na simulação.",
            details={
                "field": "horizons_days",
                "invalid": invalid,
                "allowed": list(ALLOWED_HORIZONS_DAYS),
            },
            code="SIMULATION_HORIZONS_INVALID",
        )
    if len(set(value)) != len(value):
        raise SimulationInputError(
            "Os horizontes da simulação não podem se repetir.",
            details={"field": "horizons_days"},
            code="SIMULATION_HORIZONS_INVALID",
        )
    return tuple(value)


def _validate_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise SimulationInputError(
            f"O campo {field} deve ser booleano.",
            details={"field": field},
            code="SIMULATION_INPUT_INVALID",
        )
    return value


def _validate_assumptions(
    value: Sequence[str], *, field: str = "assumptions"
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SimulationInputError(
            f"O campo {field} deve ser uma lista de textos.",
            details={"field": field},
        )
    invalid = [item for item in value if not isinstance(item, str) or not item.strip()]
    if invalid:
        raise SimulationInputError(
            f"O campo {field} contém premissas vazias ou inválidas.",
            details={"field": field},
        )
    return tuple(item.strip() for item in value)


def _number_for_json(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    number = float(value)
    if not isfinite(number):  # defensive guard for very large Decimal values
        raise SimulationError(
            "O resultado da simulação não pode ser serializado como número finito.",
            details={"field": "numeric_result"},
        )
    return number
