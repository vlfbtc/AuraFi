"""Adapter do canal simulado para o AuraFi Hub."""

from .adapter import (
    AURA_CORE_PORT,
    SIMULATED_CHANNEL,
    SIMULATED_ADAPTER,
    AuraCorePort,
    DeterministicIdFactory,
    SimulatedChannelError,
    SimulatedChannelInputError,
    SimulatedChannelAdapter,
    SimulatedTransportFixture,
    SimulatedTransportMessage,
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
