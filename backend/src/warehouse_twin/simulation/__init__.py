"""Módulo de simulación de movimientos (v2: con ground truth y drift)."""
from .anomaly_injector import AnomalyInjector, LabeledMovement
from .movement_simulator import MovementSimulator

__all__ = ["AnomalyInjector", "LabeledMovement", "MovementSimulator"]
