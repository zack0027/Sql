"""Movimiento WMS: unidad atómica que entra al detector."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class Movement(BaseModel):
    """
    Un movimiento del WMS.

    Representa una acción del operario sobre el almacén: una recepción,
    una inspección, un picking, una operación de maquila, etc.

    El detector consume objetos de esta clase y produce Anomaly cuando
    detecta patrones sospechosos.
    """

    model_config = ConfigDict(
        json_encoders={datetime: lambda dt: dt.isoformat()},
    )

    movement_id: str = Field(..., description="Identificador único del movimiento")
    timestamp: datetime = Field(..., description="Cuándo ocurrió")
    movement_type: str = Field(
        ...,
        description="Tipo: RECEIVING, INSPECTION, PUTAWAY, PICK, ORDER, TRACEABILITY, MAQUILA",
    )
    sku: str = Field(..., description="Código del producto")
    location: str = Field(..., description="Código de ubicación, ej. C-018")
    user_id: str = Field(..., description="Operario que ejecutó")
    quantity: int = Field(..., description="Cantidad (puede ser negativa en algunos casos)")
    duration_sec: int = Field(..., ge=0, description="Duración registrada en segundos")

    def is_off_hours(self) -> bool:
        """Helper para reglas de negocio."""
        hour = self.timestamp.hour
        return hour < 6 or hour >= 22
