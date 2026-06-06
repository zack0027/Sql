"""Detector ML no supervisado (v2, §4.2).

`MLAnomalyDetector` usa Isolation Forest entrenado offline con el dataset
etiquetado del simulador. Comparte la interfaz `AnomalyDetector`, así que
enchufa sin tocar la pipeline. El parámetro `contamination` se fija con la
tasa de anomalías esperada (0.15 del simulador).

scikit-learn es una dependencia OPCIONAL (extra `ml`). El import está
protegido: si sklearn no está instalado, el detector se construye en estado
"no disponible" y `detect()` devuelve [] sin romper el runtime determinista.

FUNDAMENTO: Castellani, Schmitt y Squartini (Honda RIE; Univ. Politecnica
delle Marche) entrenan con datos del gemelo; Xu, Ali y Yue (Simula; U. Oslo)
con LATTICE. Tancredi et al. (U. Parma) recuerdan medir: el ML no es garantía.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Sequence

from ..models import AnomalyEvent, AnomalyType, Movement, MovementType, Severity
from .base import AnomalyDetector

if TYPE_CHECKING:  # pragma: no cover
    pass

try:
    from sklearn.ensemble import IsolationForest  # type: ignore

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - depende del entorno
    IsolationForest = None  # type: ignore
    _SKLEARN_AVAILABLE = False


# Orden estable de los tipos de movimiento para one-hot determinista.
_MOVEMENT_TYPES = [mt.value for mt in MovementType]


class MLAnomalyDetector(AnomalyDetector):
    """Detector basado en Isolation Forest. Requiere fit() antes de detect()."""

    def __init__(self, contamination: float = 0.15, seed: int = 42):
        self.contamination = contamination
        self.seed = seed
        self._fitted = False
        self._model = None
        if _SKLEARN_AVAILABLE:
            self._model = IsolationForest(
                n_estimators=100,
                contamination=contamination,
                random_state=seed,
                n_jobs=-1,
            )

    @property
    def available(self) -> bool:
        """True si sklearn está instalado y se puede entrenar/predecir."""
        return _SKLEARN_AVAILABLE

    @property
    def fitted(self) -> bool:
        return self._fitted

    def _features(self, m: Movement) -> List[float]:
        """Vector de features numéricas + one-hot de movement_type."""
        base = [
            float(m.quantity),
            float(m.duration_s if m.duration_s is not None else 0.0),
            float(m.timestamp.hour),
            1.0 if m.is_known_rack() else 0.0,
        ]
        one_hot = [1.0 if m.movement_type.value == t else 0.0 for t in _MOVEMENT_TYPES]
        return base + one_hot

    def fit(self, movements: Sequence[Movement]) -> "MLAnomalyDetector":
        """Entrena el modelo con un conjunto de movimientos."""
        if not self._model or not movements:
            return self
        self._model.fit([self._features(m) for m in movements])
        self._fitted = True
        return self

    def detect(self, movement: Movement) -> List[AnomalyEvent]:
        if not self._fitted or not self._model:
            return []
        prediction = self._model.predict([self._features(movement)])[0]
        if prediction == -1:  # outlier
            return [
                AnomalyEvent(
                    movement_id=movement.id,
                    rack_id=movement.rack_id,
                    type=AnomalyType.DURATION_OUTLIER,
                    severity=Severity.MEDIUM,
                    detail="Patrón atípico detectado por Isolation Forest "
                    "(combinación inusual de cantidad/duración/hora).",
                    detector="ml",
                )
            ]
        return []
