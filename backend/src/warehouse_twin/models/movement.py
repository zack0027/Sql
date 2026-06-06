"""Movimiento WMS: unidad atómica que entra al detector.

v2 (§9 de la documentación técnica):
  - `id`        reemplaza a `movement_id`
  - `rack_id`   reemplaza a `location`; patrón relajado para que la anomalía
                UNKNOWN_RACK sea alcanzable
  - `duration_s` (float, opcional) reemplaza a `duration_sec`; habilita
                DURATION_OUTLIER real
  - `sku` y `user_id` se conservan como metadatos opcionales (no forman
                parte del contrato mínimo v2 pero enriquecen la narración)
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MovementType(str, Enum):
    """Tipo de movimiento operativo dentro del almacén."""

    RECEIVING = "RECEIVING"
    INSPECTION = "INSPECTION"
    PUTAWAY = "PUTAWAY"
    PICK = "PICK"
    ORDER = "ORDER"
    TRACEABILITY = "TRACEABILITY"
    MAQUILA = "MAQUILA"
    ADJUSTMENT = "ADJUSTMENT"


# Layout canónico del almacén: filas A-F, columnas 001-018.
# Un rack_id que NO cumpla este patrón dispara UNKNOWN_RACK.
KNOWN_RACK_PATTERN = re.compile(r"^[A-F]-(00[1-9]|01[0-8])$")


class Movement(BaseModel):
    """
    Un movimiento del WMS.

    Representa una acción del operario sobre el almacén: recepción,
    inspección, picking, maquila, etc. El detector consume objetos de
    esta clase y produce AnomalyEvent cuando detecta patrones sospechosos.
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda dt: dt.isoformat()},
    )

    id: str = Field(..., min_length=1, description="Identificador único del movimiento")
    rack_id: str = Field(..., min_length=1, description="Código de ubicación, ej. C-018")
    movement_type: MovementType = Field(..., description="Tipo de movimiento")
    quantity: int = Field(..., description="Cantidad (puede ser negativa en ajustes)")
    duration_s: float | None = Field(
        default=None, ge=0.0, description="Duración registrada en segundos (v2)"
    )
    timestamp: datetime = Field(default_factory=datetime.now, description="Cuándo ocurrió")

    # Metadatos opcionales (no forman parte del contrato mínimo v2)
    sku: str | None = Field(default=None, description="Código del producto")
    user_id: str | None = Field(default=None, description="Operario que ejecutó")

    def is_off_hours(self) -> bool:
        """Helper para reglas de negocio: fuera de horario laboral típico."""
        hour = self.timestamp.hour
        return hour < 6 or hour >= 22

    def is_known_rack(self) -> bool:
        """True si el rack_id pertenece al layout canónico del almacén."""
        return bool(KNOWN_RACK_PATTERN.match(self.rack_id))
