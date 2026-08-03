"""Domínio puro para simulações educativas do AuraFi."""

from .service import (
    ALLOWED_HORIZONS_DAYS,
    DEFAULT_DISCLAIMER,
    AssumptionFixtureFormula,
    FormulaProjection,
    FormulaStrategy,
    Simulation,
    SimulationConfigurationError,
    SimulationError,
    SimulationInputError,
    SimulationRequest,
    SimulationScenario,
    SimulationService,
)

__all__ = [
    "ALLOWED_HORIZONS_DAYS",
    "DEFAULT_DISCLAIMER",
    "AssumptionFixtureFormula",
    "FormulaProjection",
    "FormulaStrategy",
    "Simulation",
    "SimulationConfigurationError",
    "SimulationError",
    "SimulationInputError",
    "SimulationRequest",
    "SimulationScenario",
    "SimulationService",
]
