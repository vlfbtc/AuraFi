"""Regras puras para perfil de risco, guardrails e recomendação.

Este módulo não consulta banco, rede, wallet, Open Finance ou qualquer serviço
externo. Critérios de suitability devem ser fornecidos por ``EligibilityPolicy``;
o domínio não calcula score, APY, threshold ou limite de alocação.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from uuid import uuid4


DEFAULT_DISCLAIMER = (
    "Esta recomendação é apoio à decisão, não constitui ordem, consultoria "
    "personalizada ou garantia de retorno. Não executa alocações."
)


class _StrEnum(str, Enum):
    """Enumeração serializável diretamente nos contratos JSON."""

    def __str__(self) -> str:
        return self.value


class RiskProfileLevel(_StrEnum):
    """Níveis declarados no contrato canônico do AuraFi."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class ProfileStatus(_StrEnum):
    DECLARED = "declared"
    MISSING = "missing"


class ProfileSource(_StrEnum):
    QUESTIONNAIRE = "questionnaire"
    MANUAL = "manual"


class EligibilityStatus(_StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_PROFILE = "needs_profile"
    PENDING = "pending"


class Suitability(_StrEnum):
    ALIGNED = "aligned"
    CAUTION = "caution"
    NOT_ALIGNED = "not_aligned"
    UNAVAILABLE = "unavailable"


class RecommendationStatus(_StrEnum):
    READY = "ready"
    NO_MATCH = "no_match"
    FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class RiskAnswer:
    """Resposta declarada do quiz, sem interpretação ou pontuação local."""

    question_id: str
    answer: str

    def __post_init__(self) -> None:
        if not self.question_id.strip():
            raise ValueError("question_id não pode ser vazio")
        if not self.answer.strip():
            raise ValueError("answer não pode ser vazio")
        if len(self.answer) > 200:
            raise ValueError("answer não pode exceder 200 caracteres")


@dataclass(frozen=True, slots=True)
class RiskProfile:
    """Perfil declarado pelo usuário.

    ``questionnaire`` exige exatamente cinco respostas, conforme o contrato.
    ``manual`` representa uma declaração explícita e pode não carregar respostas
    do quiz. Nenhum campo é inferido a partir de patrimônio, wallet ou mercado.
    """

    declared_profile: RiskProfileLevel | str | None = None
    version: str | None = None
    source: ProfileSource | str | None = None
    answers: tuple[RiskAnswer, ...] = ()
    declared_at: datetime | None = None
    status: ProfileStatus | str = ProfileStatus.DECLARED

    def __post_init__(self) -> None:
        profile_status = _coerce_enum(self.status, ProfileStatus, "status")
        object.__setattr__(self, "status", profile_status)

        answers = tuple(
            answer if isinstance(answer, RiskAnswer) else RiskAnswer(**answer)
            for answer in self.answers
        )
        object.__setattr__(self, "answers", answers)

        if profile_status is ProfileStatus.MISSING:
            if any((self.declared_profile, self.version, self.source, answers)):
                raise ValueError("perfil missing não pode conter declaração")
            return

        if self.declared_profile is None:
            raise ValueError("perfil declarado exige declared_profile")
        object.__setattr__(
            self,
            "declared_profile",
            _coerce_enum(self.declared_profile, RiskProfileLevel, "declared_profile"),
        )
        if not self.version or not self.version.strip():
            raise ValueError("perfil declarado exige uma versão")

        source = self.source
        if source is None and answers:
            source = ProfileSource.QUESTIONNAIRE
        if source is None:
            raise ValueError("perfil declarado exige source questionnaire ou manual")
        source = _coerce_enum(source, ProfileSource, "source")
        object.__setattr__(self, "source", source)

        if source is ProfileSource.QUESTIONNAIRE:
            if len(answers) != 5:
                raise ValueError("questionnaire exige exatamente cinco respostas")
            question_ids = [answer.question_id for answer in answers]
            if len(set(question_ids)) != len(question_ids):
                raise ValueError("questionnaire não pode repetir question_id")

        if self.declared_at is None:
            object.__setattr__(self, "declared_at", datetime.now(timezone.utc))
        elif self.declared_at.tzinfo is None:
            raise ValueError("declared_at deve incluir timezone")

    @classmethod
    def missing(cls) -> "RiskProfile":
        """Cria uma representação explícita de perfil ausente."""

        return cls(status=ProfileStatus.MISSING)

    @property
    def is_declared(self) -> bool:
        return self.status is ProfileStatus.DECLARED


@dataclass(frozen=True, slots=True)
class Opportunity:
    """Dados mínimos que uma política pode usar para decidir.

    O serviço não calcula risco. ``attributes`` permite que uma política
    aprovada receba dados de mercado sem acoplar este domínio a um schema de
    integração ou inventar campos de APY/score.
    """

    opportunity_id: str
    risk_level: str | None = None
    risk_dimensions: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.opportunity_id.strip():
            raise ValueError("opportunity_id não pode ser vazio")
        object.__setattr__(self, "risk_dimensions", tuple(self.risk_dimensions))
        object.__setattr__(self, "attributes", dict(self.attributes))


@dataclass(frozen=True, slots=True)
class EligibilityRule:
    """Regra explícita para uma oportunidade.

    A compatibilidade é declarada por conjunto de perfis, sem score ou
    threshold implícito. ``rationale`` e ``risks`` são exigidos para que uma
    decisão elegível seja explicável.
    """

    allowed_profiles: frozenset[RiskProfileLevel | str]
    rationale: tuple[str, ...]
    risks: tuple[str, ...]
    suitability: Suitability | str = Suitability.ALIGNED
    reason: str | None = None

    def __post_init__(self) -> None:
        profiles = frozenset(
            _coerce_enum(profile, RiskProfileLevel, "allowed_profiles")
            for profile in self.allowed_profiles
        )
        object.__setattr__(self, "allowed_profiles", profiles)
        object.__setattr__(self, "rationale", _non_empty_texts(self.rationale, "rationale"))
        object.__setattr__(self, "risks", _non_empty_texts(self.risks, "risks"))
        object.__setattr__(
            self, "suitability", _coerce_enum(self.suitability, Suitability, "suitability")
        )


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Resultado verificável de um guardrail para uma oportunidade."""

    opportunity_id: str
    status: EligibilityStatus
    reason_code: str
    reason: str
    policy_version: str | None
    profile_used: RiskProfileLevel | None = None
    suitability: Suitability | None = None
    rationale: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _coerce_enum(self.status, EligibilityStatus, "status")
        )
        if not self.opportunity_id.strip():
            raise ValueError("opportunity_id não pode ser vazio")
        if not self.reason_code.strip() or not self.reason.strip():
            raise ValueError("decisão exige reason_code e reason")
        if self.policy_version is not None and not self.policy_version.strip():
            raise ValueError("policy_version não pode ser vazio")
        if self.profile_used is not None:
            object.__setattr__(
                self,
                "profile_used",
                _coerce_enum(self.profile_used, RiskProfileLevel, "profile_used"),
            )
        if self.suitability is not None:
            object.__setattr__(
                self,
                "suitability",
                _coerce_enum(self.suitability, Suitability, "suitability"),
            )
        object.__setattr__(self, "rationale", tuple(self.rationale))
        object.__setattr__(self, "risks", tuple(self.risks))

    @property
    def is_recommendable(self) -> bool:
        return self.status is EligibilityStatus.ELIGIBLE


PolicyEvaluator = Callable[[RiskProfile, Opportunity], EligibilityDecision]


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    """Política de elegibilidade fornecida pelo consumidor do serviço.

    Pode ser uma tabela de ``rules`` ou um ``evaluator`` puro. Pelo menos um
    deve ser fornecido. A versão é obrigatória para permitir auditoria e
    revogação. A política não deve ser omitida nem substituída por defaults.
    """

    version: str
    rules: Mapping[str, EligibilityRule] = field(default_factory=dict)
    evaluator: PolicyEvaluator | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("EligibilityPolicy exige version")
        if not self.rules and self.evaluator is None:
            raise ValueError("EligibilityPolicy exige rules ou evaluator explícito")
        normalized_rules = dict(self.rules)
        for opportunity_id, rule in normalized_rules.items():
            if not opportunity_id.strip():
                raise ValueError("rule não pode ter opportunity_id vazio")
            if not isinstance(rule, EligibilityRule):
                raise TypeError("rules deve mapear opportunity_id para EligibilityRule")
        object.__setattr__(self, "rules", normalized_rules)

    @classmethod
    def from_rules(
        cls, version: str, rules: Mapping[str, EligibilityRule]
    ) -> "EligibilityPolicy":
        return cls(version=version, rules=rules)

    def evaluate(
        self, profile: RiskProfile, opportunity: Opportunity
    ) -> EligibilityDecision:
        """Avalia sem aplicar qualquer fallback de suitability."""

        try:
            if self.evaluator is not None:
                decision = self.evaluator(profile, opportunity)
                if not isinstance(decision, EligibilityDecision):
                    return _pending(
                        opportunity.opportunity_id,
                        self.version,
                        "POLICY_DECISION_INVALID",
                        "A política não retornou uma decisão estruturada.",
                        profile.declared_profile,
                    )
                if decision.policy_version not in (None, self.version):
                    return _pending(
                        opportunity.opportunity_id,
                        self.version,
                        "POLICY_VERSION_MISMATCH",
                        "A decisão retornada não corresponde à versão da política.",
                        profile.declared_profile,
                    )
                if decision.status is EligibilityStatus.ELIGIBLE and (
                    decision.suitability is None
                    or not decision.rationale
                    or not decision.risks
                ):
                    return _pending(
                        opportunity.opportunity_id,
                        self.version,
                        "POLICY_EXPLANATION_REQUIRED",
                        "Uma decisão elegível precisa informar suitability, rationale e risks.",
                        profile.declared_profile,
                    )
                return replace(
                    decision,
                    opportunity_id=opportunity.opportunity_id,
                    policy_version=self.version,
                    profile_used=profile.declared_profile,
                )

            rule = self.rules.get(opportunity.opportunity_id)
            if rule is None:
                return _pending(
                    opportunity.opportunity_id,
                    self.version,
                    "POLICY_RULE_MISSING",
                    "Não há regra explícita de elegibilidade para esta oportunidade.",
                    profile.declared_profile,
                )

            if profile.declared_profile in rule.allowed_profiles:
                return EligibilityDecision(
                    opportunity_id=opportunity.opportunity_id,
                    status=EligibilityStatus.ELIGIBLE,
                    reason_code="PROFILE_COMPATIBLE",
                    reason=(rule.reason or "O perfil declarado é compatível com a regra explícita."),
                    policy_version=self.version,
                    profile_used=profile.declared_profile,
                    suitability=rule.suitability,
                    rationale=rule.rationale,
                    risks=rule.risks,
                )

            return EligibilityDecision(
                opportunity_id=opportunity.opportunity_id,
                status=EligibilityStatus.INELIGIBLE,
                reason_code="PROFILE_NOT_COMPATIBLE",
                reason=(
                    rule.reason
                    or "O perfil declarado não está entre os perfis compatíveis da política."
                ),
                policy_version=self.version,
                profile_used=profile.declared_profile,
                suitability=Suitability.NOT_ALIGNED,
                rationale=rule.rationale,
                risks=rule.risks,
            )
        except Exception as exc:  # pragma: no cover - exercised by consumer policies
            return _pending(
                opportunity.opportunity_id,
                self.version,
                "POLICY_EVALUATION_ERROR",
                f"A política não pôde concluir a avaliação: {type(exc).__name__}.",
                profile.declared_profile,
            )


@dataclass(frozen=True, slots=True)
class RecommendationItem:
    """Item explicável de uma recomendação pronta."""

    opportunity_id: str
    suitability: Suitability
    rationale: tuple[str, ...]
    risks: tuple[str, ...]
    disclaimer: str = DEFAULT_DISCLAIMER


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Resultado do serviço, incluindo diagnóstico de guardrails.

    ``eligibility`` preserva bloqueios e pendências para o chamador explicar o
    resultado. ``revoke`` é local e imutável; persistência/auditoria pertencem a
    outra camada.
    """

    recommendation_id: str
    status: RecommendationStatus
    profile_used: RiskProfileLevel | None
    items: tuple[RecommendationItem, ...]
    explanation: str
    disclaimer: str
    generated_at: datetime
    policy_version: str | None
    eligibility: tuple[EligibilityDecision, ...] = ()
    revocable: bool = True
    revoked: bool = False
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    @property
    def actionable(self) -> bool:
        return self.status is RecommendationStatus.READY and not self.revoked

    def revoke(
        self, *, reason: str = "Recomendação revogada pelo consumidor do serviço.", now: datetime | None = None
    ) -> "Recommendation":
        if not self.revocable:
            raise ValueError("esta recomendação não é revogável")
        if not reason.strip():
            raise ValueError("revocation reason não pode ser vazio")
        revoked_at = now or datetime.now(timezone.utc)
        if revoked_at.tzinfo is None:
            raise ValueError("revoked_at deve incluir timezone")
        return replace(
            self,
            revoked=True,
            revoked_at=revoked_at,
            revocation_reason=reason,
        )


class RecommendationService:
    """Orquestra perfil, política explícita e guardrails de recomendação."""

    def __init__(self, *, disclaimer: str = DEFAULT_DISCLAIMER) -> None:
        if not disclaimer.strip():
            raise ValueError("disclaimer não pode ser vazio")
        self._disclaimer = disclaimer

    def recommend(
        self,
        profile: RiskProfile | None,
        opportunities: Iterable[Opportunity],
        policy: EligibilityPolicy | None,
        *,
        recommendation_id: str | None = None,
        now: datetime | None = None,
    ) -> Recommendation:
        """Gera uma decisão; sem perfil/política nunca retorna itens."""

        generated_at = now or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            raise ValueError("now deve incluir timezone")
        result_id = recommendation_id or f"recommendation-{uuid4()}"
        opportunity_list = tuple(opportunities)

        if profile is None or not profile.is_declared:
            return self._no_match(
                result_id,
                profile_used=None,
                policy_version=policy.version if policy else None,
                explanation=(
                    "PROFILE_REQUIRED: nenhuma recomendação foi emitida porque "
                    "não existe perfil de risco declarado válido."
                ),
                generated_at=generated_at,
                eligibility=tuple(
                    _needs_profile_decision(
                        opportunity.opportunity_id,
                        policy.version if policy else None,
                    )
                    for opportunity in opportunity_list
                ),
            )

        if policy is None:
            return self._no_match(
                result_id,
                profile_used=profile.declared_profile,
                policy_version=None,
                explanation=(
                    "POLICY_REQUIRED: decisão pendente; uma EligibilityPolicy "
                    "explícita é necessária para recomendar."
                ),
                generated_at=generated_at,
                eligibility=tuple(
                    _pending(
                        opportunity.opportunity_id,
                        None,
                        "POLICY_REQUIRED",
                        "Uma EligibilityPolicy explícita é necessária para decidir.",
                        profile.declared_profile,
                    )
                    for opportunity in opportunity_list
                ),
            )

        decisions = tuple(policy.evaluate(profile, opportunity) for opportunity in opportunity_list)
        eligible = tuple(decision for decision in decisions if decision.is_recommendable)
        items = tuple(
            RecommendationItem(
                opportunity_id=decision.opportunity_id,
                suitability=decision.suitability or Suitability.UNAVAILABLE,
                rationale=decision.rationale,
                risks=decision.risks,
                disclaimer=self._disclaimer,
            )
            for decision in eligible
        )

        if not items:
            reason_codes = ", ".join(decision.reason_code for decision in decisions)
            explanation = (
                "NO_MATCH: nenhuma oportunidade foi elegível pela política explícita."
                if decisions
                else "NO_MATCH: nenhuma oportunidade foi informada."
            )
            if reason_codes:
                explanation = f"{explanation} Motivos: {reason_codes}."
            return self._no_match(
                result_id,
                profile_used=profile.declared_profile,
                policy_version=policy.version,
                explanation=explanation,
                generated_at=generated_at,
                eligibility=decisions,
            )

        return Recommendation(
            recommendation_id=result_id,
            status=RecommendationStatus.READY,
            profile_used=profile.declared_profile,
            items=items,
            explanation=(
                "A recomendação contém somente oportunidades elegíveis pela "
                f"EligibilityPolicy {policy.version}; decisões não elegíveis "
                "permanecem registradas em eligibility."
            ),
            disclaimer=self._disclaimer,
            generated_at=generated_at,
            policy_version=policy.version,
            eligibility=decisions,
        )

    # Alias semântico para consumidores que tratam a operação como avaliação.
    assess = recommend

    def _no_match(
        self,
        recommendation_id: str,
        *,
        profile_used: RiskProfileLevel | None,
        policy_version: str | None,
        explanation: str,
        generated_at: datetime,
        eligibility: Sequence[EligibilityDecision] = (),
    ) -> Recommendation:
        return Recommendation(
            recommendation_id=recommendation_id,
            status=RecommendationStatus.NO_MATCH,
            profile_used=profile_used,
            items=(),
            explanation=explanation,
            disclaimer=self._disclaimer,
            generated_at=generated_at,
            policy_version=policy_version,
            eligibility=tuple(eligibility),
        )


def _coerce_enum(value: Any, enum_type: type[_StrEnum], field_name: str) -> _StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} inválido; valores aceitos: {allowed}") from exc


def _non_empty_texts(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    result = tuple(value.strip() for value in values)
    if not result or any(not value for value in result):
        raise ValueError(f"{field_name} deve conter ao menos um texto não vazio")
    return result


def _pending(
    opportunity_id: str,
    policy_version: str | None,
    reason_code: str,
    reason: str,
    profile_used: RiskProfileLevel | None,
) -> EligibilityDecision:
    return EligibilityDecision(
        opportunity_id=opportunity_id,
        status=EligibilityStatus.PENDING,
        reason_code=reason_code,
        reason=reason,
        policy_version=policy_version,
        profile_used=profile_used,
        suitability=Suitability.UNAVAILABLE,
    )


def _needs_profile_decision(
    opportunity_id: str, policy_version: str | None
) -> EligibilityDecision:
    return EligibilityDecision(
        opportunity_id=opportunity_id,
        status=EligibilityStatus.NEEDS_PROFILE,
        reason_code="PROFILE_REQUIRED",
        reason="Perfil de risco declarado é obrigatório antes da recomendação.",
        policy_version=policy_version,
        suitability=Suitability.UNAVAILABLE,
    )
