"""Testes da camada de apresentação do BFF de mercado.

Garante que o backend entrega strings prontas para exibição e nunca vaza
sentinelas internas como ``[LACUNA]`` para os clientes.
"""

from __future__ import annotations

import unittest

from services.market_data.presentation import (
    decorate_opportunity,
    decorate_simulation,
    derive_risk_level,
    format_asset_amount,
    format_money,
    format_money_compact,
    format_percent,
    source_display_label,
    status_label,
)


class PresentationFormattingTests(unittest.TestCase):
    def test_percent_uses_brazilian_decimal(self) -> None:
        self.assertEqual(format_percent(2.2), "2,20% a.a.")

    def test_money_full_groups_in_brazilian_format(self) -> None:
        self.assertEqual(format_money(1_200_000_000, "USD"), "US$ 1.200.000.000,00")
        self.assertEqual(format_money(12.5, "BRL"), "R$ 12,50")

    def test_money_compact_abbreviates_large_values(self) -> None:
        self.assertEqual(format_money_compact(17_600_000_000, "USD"), "US$ 17,6 bi")
        self.assertEqual(format_money_compact(4_000_000, "USD"), "US$ 4 mi")
        self.assertEqual(format_money_compact(950_000, "USD"), "US$ 950.000,00")

    def test_source_label_normalizes_and_drops_lacuna(self) -> None:
        self.assertEqual(source_display_label("defillama"), "DeFiLlama")
        self.assertIsNone(source_display_label("[LACUNA]"))
        self.assertIsNone(source_display_label("   "))

    def test_status_label_reflects_mode_and_staleness(self) -> None:
        self.assertEqual(status_label({"mode": "live", "is_stale": False}), "Dados atualizados")
        self.assertEqual(status_label({"mode": "live", "is_stale": True}), "Atualização pendente")
        self.assertEqual(status_label({"mode": "cache", "is_stale": False}), "Última leitura disponível")


class DecorateOpportunityTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "opportunity_id": "lido-steth",
            "apy": {"value": 2.2, "unit": "percent_annualized"},
            "tvl": {"value": 17_600_000_000, "currency": "USD"},
            "data_source": {
                "source": "defillama",
                "mode": "live",
                "is_stale": False,
                "freshness_note": "[LACUNA] definir frescor",
            },
            "currency_display": {
                "primary": {"value": 88_000_000_000, "currency": "BRL"},
                "secondary": {"value": 17_600_000_000, "currency": "USD"},
            },
        }

    def test_adds_display_strings_for_apy_and_money(self) -> None:
        result = decorate_opportunity(self._payload())
        self.assertEqual(result["apy"]["display"], "2,20% a.a.")
        self.assertEqual(result["tvl"]["display_compact"], "US$ 17,6 bi")
        self.assertEqual(result["currency_display"]["primary"]["display_compact"], "R$ 88,0 bi")
        self.assertEqual(result["currency_display"]["secondary"]["currency"], "USD")

    def test_data_source_is_sanitized_and_labelled(self) -> None:
        result = decorate_opportunity(self._payload())
        data_source = result["data_source"]
        self.assertEqual(data_source["source_label"], "DeFiLlama")
        self.assertEqual(data_source["status_label"], "Dados atualizados")
        self.assertNotIn("freshness_note", data_source)

    def test_does_not_mutate_input_payload(self) -> None:
        payload = self._payload()
        decorate_opportunity(payload)
        self.assertNotIn("display", payload["apy"])
        self.assertIn("freshness_note", payload["data_source"])

    def test_unknown_risk_is_classified_heuristically(self) -> None:
        payload = self._payload()
        payload["risk"] = {"score": None, "level": "unknown", "dimensions": []}
        payload["audit_status"] = "audited"
        result = decorate_opportunity(payload)
        self.assertEqual(result["risk"]["level"], "low")
        self.assertEqual(result["risk"]["classification"], "heuristic")

    def test_source_provided_risk_level_is_preserved(self) -> None:
        payload = self._payload()
        payload["risk"] = {"score": 40.0, "level": "high", "dimensions": []}
        result = decorate_opportunity(payload)
        self.assertEqual(result["risk"]["level"], "high")
        self.assertNotIn("classification", result["risk"])


class DeriveRiskLevelTests(unittest.TestCase):
    def test_low_for_mature_audited_low_yield(self) -> None:
        self.assertEqual(derive_risk_level(2.2, 17_600_000_000, "audited"), "low")

    def test_medium_for_moderate_yield_mid_tvl(self) -> None:
        self.assertEqual(derive_risk_level(13.0, 50_000_000, None), "medium")

    def test_high_for_aggressive_yield_thin_unaudited(self) -> None:
        self.assertEqual(derive_risk_level(30.0, 5_000_000, "not_verified"), "high")

    def test_missing_signals_default_to_low(self) -> None:
        self.assertEqual(derive_risk_level(None, None, None), "low")


class AssetAmountAndSimulationTests(unittest.TestCase):
    def test_asset_amount_trims_trailing_zeros(self) -> None:
        self.assertEqual(format_asset_amount(1000, "STETH"), "1.000 STETH")
        self.assertEqual(format_asset_amount(0.18, "USDC"), "0,18 USDC")
        self.assertEqual(format_asset_amount(2.2, "USDC"), "2,2 USDC")

    def test_simulation_decorated_with_display_strings(self) -> None:
        payload = {
            "input": {"amount": 500, "asset": "STETH"},
            "scenarios": [
                {
                    "horizon_days": 30,
                    "projected_value": 500.9,
                    "projected_yield": 0.18,
                    "idle_stablecoin_value": 500,
                    "currency": "STETH",
                }
            ],
        }
        result = decorate_simulation(payload)
        self.assertEqual(result["input"]["amount_display"], "500 STETH")
        scenario = result["scenarios"][0]
        self.assertEqual(scenario["projected_yield_display"], "0,18%")
        self.assertEqual(scenario["projected_value_display"], "500,9 STETH")
        self.assertEqual(scenario["idle_stablecoin_value_display"], "500 STETH")
        self.assertEqual(scenario["projected_gain"], 0.9)
        self.assertEqual(scenario["projected_gain_display"], "0,9 STETH")
        self.assertNotIn("amount_display", payload["input"])


if __name__ == "__main__":
    unittest.main()
