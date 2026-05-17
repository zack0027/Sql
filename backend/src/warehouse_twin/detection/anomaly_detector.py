"""
Detector que combina reglas de negocio + scoring IA.

Diseño POO: Facade. Esconde la composición de RuleEngine + ModelEnsemble
detrás de una interfaz simple detect(movement) -> Anomaly.
"""
from __future__ import annotations

from ..models import Anomaly, Movement, Severity
from .model_ensemble import HeuristicEnsemble, ModelEnsemble
from .rule_engine import RuleEngine


class AnomalyDetector:
    """
    Facade del módulo de detección.

    Combina dos fuentes de evidencia:
      - reglas determinísticas (RuleEngine)
      - scoring probabilístico (ModelEnsemble)

    La severidad final se calcula como max(severidad_reglas, severidad_score).
    """

    def __init__(
        self,
        rule_engine: RuleEngine | None = None,
        ensemble: ModelEnsemble | None = None,
        score_thresholds: dict[Severity, float] | None = None,
    ):
        self.rule_engine = rule_engine or RuleEngine()
        self.ensemble = ensemble or HeuristicEnsemble()
        self.score_thresholds = score_thresholds or {
            Severity.MEDIUM: 0.35,
            Severity.HIGH: 0.6,
            Severity.CRITICAL: 0.85,
        }

    def detect(self, movement: Movement) -> Anomaly:
        """
        Procesa un movimiento y devuelve la decisión.

        Siempre devuelve un Anomaly (incluso para movimientos normales,
        con severity=NORMAL e is_anomaly=False), para que el caller pueda
        decidir si broadcastear o no.
        """
        rule_codes = self.rule_engine.evaluate(movement)
        score = self.ensemble.score(movement)
        severity = self._compute_severity(rule_codes, score)

        return Anomaly(
            movement=movement,
            severity=severity,
            score=score,
            is_anomaly=severity is not Severity.NORMAL,
            rule_reasons=rule_codes,
        )

    def _compute_severity(self, rule_codes: list[str], score: float) -> Severity:
        # Severidad por reglas: dos o más reglas críticas → critical
        critical_rules = {"cantidad_negativa", "duracion_minima"}
        crit_hits = sum(1 for c in rule_codes if c in critical_rules)
        if crit_hits >= 2:
            return Severity.CRITICAL
        if crit_hits == 1 or len(rule_codes) >= 2:
            return Severity.HIGH
        if len(rule_codes) == 1:
            severity_from_rules = Severity.MEDIUM
        else:
            severity_from_rules = Severity.NORMAL

        # Severidad por score
        if score >= self.score_thresholds[Severity.CRITICAL]:
            severity_from_score = Severity.CRITICAL
        elif score >= self.score_thresholds[Severity.HIGH]:
            severity_from_score = Severity.HIGH
        elif score >= self.score_thresholds[Severity.MEDIUM]:
            severity_from_score = Severity.MEDIUM
        else:
            severity_from_score = Severity.NORMAL

        return severity_from_rules if severity_from_rules.rank >= severity_from_score.rank else severity_from_score
