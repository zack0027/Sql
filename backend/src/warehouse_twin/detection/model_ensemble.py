"""
Ensemble IA para scoring de anomalías.

Diseño POO: Strategy pattern. ModelEnsemble es la interfaz que el detector
consume; las implementaciones concretas (HeuristicEnsemble, IsolationForestEnsemble)
se pueden intercambiar sin tocar el detector.

NOTA: la versión entrenada (Isolation Forest + ECOD con F1 0.747) vive en
sesiones anteriores como un .pkl. Esta versión heurística es el fallback
que funciona sin dependencia de scikit-learn ni dataset entrenado.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Movement


class ModelEnsemble(ABC):
    """
    Interfaz abstracta de un scorer de anomalías.

    Cualquier modelo (heurístico, IsolationForest, deep learning) implementa
    score() devolviendo un float [0, 1].
    """

    @abstractmethod
    def score(self, movement: Movement) -> float:
        """Devuelve probabilidad de ser anomalía en [0, 1]."""

    def name(self) -> str:
        return self.__class__.__name__


class HeuristicEnsemble(ModelEnsemble):
    """
    Scorer heurístico que combina señales simples sin necesidad de entrenamiento.

    Es el "modelo bootstrap": permite que el sistema funcione end-to-end
    desde el día 1, mientras el dataset y el modelo real se preparan.

    Pesa señales conocidamente correlacionadas con anomalías reales en WMS:
    - duración extrema (muy corta o muy larga)
    - cantidad atípica
    - horario fuera de turno
    """

    def __init__(
        self,
        duration_short_threshold: int = 10,
        duration_long_threshold: int = 180,
        quantity_atypical_threshold: int = 100,
    ):
        self.duration_short = duration_short_threshold
        self.duration_long = duration_long_threshold
        self.quantity_atypical = quantity_atypical_threshold

    def score(self, movement: Movement) -> float:
        signals = []

        # Duración
        if movement.duration_sec < self.duration_short:
            signals.append(0.4)
        elif movement.duration_sec > self.duration_long:
            signals.append(min(0.6, movement.duration_sec / 600.0))
        else:
            signals.append(0.05)

        # Cantidad
        if movement.quantity < 0:
            signals.append(0.6)
        elif abs(movement.quantity) > self.quantity_atypical:
            signals.append(0.3)
        else:
            signals.append(0.1)

        # Horario
        signals.append(0.3 if movement.is_off_hours() else 0.0)

        # Promedio ponderado simple
        return min(1.0, sum(signals) / 2.0)


class IsolationForestEnsemble(ModelEnsemble):
    """
    Placeholder para el modelo entrenado (Isolation Forest + ECOD, F1 0.747).

    Para cargar el modelo real:
        with open('models/iforest_v1.pkl', 'rb') as f:
            self._model = pickle.load(f)

    Por ahora delega en heurística para que el sistema corra sin .pkl.
    Cuando se entrene y serialice el modelo, sustituir score() por la
    inferencia real.
    """

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path
        self._heuristic = HeuristicEnsemble()
        # TODO: cargar pickle desde model_path cuando esté disponible

    def score(self, movement: Movement) -> float:
        return self._heuristic.score(movement)
