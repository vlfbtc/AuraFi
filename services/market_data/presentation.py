"""Camada de apresentação do BFF para dados de mercado e simulação.

Os clientes (app iOS e web widget) não devem formatar moeda/percentual/valores
por ativo nem filtrar sentinelas internas como ``[LACUNA]``. Este módulo
enriquece os payloads de oportunidade e de simulação com strings prontas para
exibição, em português brasileiro, e higieniza rótulos de fonte/frescor antes de
sair pela API.
"""

from __future__ import annotations

from typing import Any, Mapping

_LACUNA_MARKER = "lacuna"


def _br_number(value: float, decimals: int) -> str:
    """Formata um número no padrão brasileiro (milhar ``.`` e decimal ``,``)."""
    negative = value < 0
    formatted = f"{abs(value):,.{decimals}f}"
    formatted = formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"-{formatted}" if negative else formatted


def _currency_symbol(currency: str | None) -> str:
    code = (currency or "USD").strip().upper()
    if code == "BRL":
        return "R$"
    if code == "USD":
        return "US$"
    return code


def format_percent(value: float) -> str:
    """Ex.: ``2.2`` -> ``"2,20% a.a."``."""
    return f"{_br_number(value, 2)}% a.a."


def format_money(value: float, currency: str | None) -> str:
    """Valor monetário completo. Ex.: ``"US$ 1.200.000.000,00"``."""
    return f"{_currency_symbol(currency)} {_br_number(value, 2)}"


def format_money_compact(value: float, currency: str | None) -> str:
    """Valor monetário abreviado para cards. Ex.: ``"US$ 17,6 bi"``."""
    symbol = _currency_symbol(currency)
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{symbol} {_br_number(value / 1_000_000_000, 1)} bi"
    if magnitude >= 1_000_000:
        return f"{symbol} {_br_number(value / 1_000_000, 0)} mi"
    return format_money(value, currency)


def _br_number_trim(value: float, max_decimals: int = 2) -> str:
    """Número brasileiro com até ``max_decimals`` casas, sem zeros à direita."""
    text = _br_number(value, max_decimals)
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def format_asset_amount(value: float, asset: str) -> str:
    """Valor denominado em ativo. Ex.: ``(1000, "STETH")`` -> ``"1.000 STETH"``."""
    suffix = f" {asset}" if asset else ""
    return f"{_br_number_trim(value)}{suffix}"


def format_percent_plain(value: float) -> str:
    """Percentual acumulado, sem "a.a.". Ex.: ``0.18`` -> ``"0,18%"``."""
    return f"{_br_number(value, 2)}%"


def clean_label(value: Any) -> str | None:
    """Retorna o texto limpo ou ``None`` quando for vazio ou uma sentinela."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _LACUNA_MARKER in text.casefold():
        return None
    return text


def source_display_label(source: Any) -> str | None:
    text = clean_label(source)
    if text is None:
        return None
    return "DeFiLlama" if text.casefold() == "defillama" else text


def status_label(data_source: Mapping[str, Any]) -> str:
    if data_source.get("is_stale"):
        return "Atualização pendente"
    mode = data_source.get("mode")
    if mode == "live":
        return "Dados atualizados"
    if mode == "cache":
        return "Última leitura disponível"
    return "Conteúdo informativo"


def _decorate_amount(amount: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(amount)
    value = result.get("value")
    if isinstance(value, (int, float)):
        currency = result.get("currency")
        result["display"] = format_money(float(value), currency)
        result["display_compact"] = format_money_compact(float(value), currency)
    return result


def _decorate_data_source(data_source: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(data_source)
    label = source_display_label(result.get("source"))
    if label is not None:
        result["source_label"] = label
    result["status_label"] = status_label(result)
    note = clean_label(result.get("freshness_note"))
    if note is not None:
        result["freshness_note"] = note
    else:
        result.pop("freshness_note", None)
    return result


def derive_risk_level(
    apy_value: Any, tvl_value: Any, audit_status: Any
) -> str:
    """Classifica o risco a partir de sinais observáveis quando a fonte não o traz.

    Heurística transparente: o risco cresce com o APY (busca por rendimento) e
    diminui com a maturidade de liquidez (TVL) e com auditoria. Não é aconselhamento
    personalizado, apenas uma leitura dos dados de mercado observados.
    """
    points = 0
    if isinstance(apy_value, (int, float)):
        if apy_value >= 25:
            points += 3
        elif apy_value >= 12:
            points += 2
        elif apy_value >= 6:
            points += 1
    if isinstance(tvl_value, (int, float)):
        if tvl_value >= 1_000_000_000:
            points -= 1
        elif tvl_value < 10_000_000:
            points += 2
        elif tvl_value < 100_000_000:
            points += 1
    if audit_status == "audited":
        points -= 1
    elif audit_status == "not_verified":
        points += 1
    if points <= 0:
        return "low"
    if points <= 3:
        return "medium"
    return "high"


def decorate_opportunity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Enriquece uma oportunidade serializada com campos prontos para exibição."""
    result = dict(payload)

    risk = result.get("risk")
    if isinstance(risk, Mapping):
        risk = dict(risk)
        if not str(risk.get("level") or "").strip() or risk.get("level") == "unknown":
            apy_value = result.get("apy")
            apy_value = apy_value.get("value") if isinstance(apy_value, Mapping) else None
            tvl_value = result.get("tvl")
            tvl_value = tvl_value.get("value") if isinstance(tvl_value, Mapping) else None
            risk["level"] = derive_risk_level(apy_value, tvl_value, result.get("audit_status"))
            risk["classification"] = "heuristic"
        result["risk"] = risk

    apy = result.get("apy")
    if isinstance(apy, Mapping):
        apy = dict(apy)
        value = apy.get("value")
        if isinstance(value, (int, float)):
            apy["display"] = format_percent(float(value))
        result["apy"] = apy

    tvl = result.get("tvl")
    if isinstance(tvl, Mapping):
        result["tvl"] = _decorate_amount(tvl)

    data_source = result.get("data_source")
    if isinstance(data_source, Mapping):
        result["data_source"] = _decorate_data_source(data_source)

    currency_display = result.get("currency_display")
    if isinstance(currency_display, Mapping):
        currency_display = dict(currency_display)
        primary = currency_display.get("primary")
        if isinstance(primary, Mapping):
            currency_display["primary"] = _decorate_amount(primary)
        secondary = currency_display.get("secondary")
        if isinstance(secondary, Mapping):
            currency_display["secondary"] = _decorate_amount(secondary)
        result["currency_display"] = currency_display

    history = result.get("history")
    if isinstance(history, Mapping):
        history = dict(history)
        hist_source = history.get("data_source")
        if isinstance(hist_source, Mapping):
            hist_source = dict(hist_source)
            label = source_display_label(hist_source.get("source"))
            if label is not None:
                hist_source["source_label"] = label
            note = clean_label(hist_source.get("freshness_note"))
            if note is not None:
                hist_source["freshness_note"] = note
            else:
                hist_source.pop("freshness_note", None)
            history["data_source"] = hist_source
        result["history"] = history

    return result


_SCENARIO_ASSET_FIELDS = ("projected_value", "idle_stablecoin_value")


def decorate_simulation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Enriquece uma simulação serializada com valores prontos para exibição.

    Convém lembrar a semântica do domínio: ``projected_value`` e
    ``idle_stablecoin_value`` são montantes no ativo, enquanto ``projected_yield``
    é o percentual acumulado do cenário. O ganho em montante é derivado aqui como
    ``projected_gain`` para que os clientes exibam o "+" corretamente.
    """
    result = dict(payload)

    principal: float | None = None
    input_payload = result.get("input")
    if isinstance(input_payload, Mapping):
        input_payload = dict(input_payload)
        amount = input_payload.get("amount")
        asset = input_payload.get("asset")
        if isinstance(amount, (int, float)):
            principal = float(amount)
            if isinstance(asset, str):
                input_payload["amount_display"] = format_asset_amount(principal, asset)
        result["input"] = input_payload

    scenarios = result.get("scenarios")
    if isinstance(scenarios, list):
        decorated_scenarios = []
        for scenario in scenarios:
            if isinstance(scenario, Mapping):
                scenario = dict(scenario)
                currency = scenario.get("currency", "")
                asset = currency if isinstance(currency, str) else ""

                for field in _SCENARIO_ASSET_FIELDS:
                    value = scenario.get(field)
                    if isinstance(value, (int, float)):
                        scenario[f"{field}_display"] = format_asset_amount(
                            float(value), asset
                        )

                projected_yield = scenario.get("projected_yield")
                if isinstance(projected_yield, (int, float)):
                    scenario["projected_yield_display"] = format_percent_plain(
                        float(projected_yield)
                    )

                projected_value = scenario.get("projected_value")
                if principal is not None and isinstance(projected_value, (int, float)):
                    gain = round(float(projected_value) - principal, 8)
                    scenario["projected_gain"] = gain
                    scenario["projected_gain_display"] = format_asset_amount(gain, asset)
            decorated_scenarios.append(scenario)
        result["scenarios"] = decorated_scenarios

    data_source = result.get("data_source")
    if isinstance(data_source, Mapping):
        result["data_source"] = _decorate_data_source(data_source)

    return result
