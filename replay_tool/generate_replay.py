"""
Generador de replay para la demo pública (contrato v2).

Produce un JSON con una secuencia cinematográfica de eventos:
- ~90 segundos totales
- ~10 anomalías cubriendo los 4 tipos (NEGATIVE_QUANTITY, DURATION_OUTLIER,
  TRACEABILITY_BROKEN, UNKNOWN_RACK) y las 3 severidades (LOW/MEDIUM/HIGH)
- Cada anomalía es seguida ~1.5s después por su narración, correlacionada
  por anomaly_id == id de la anomalía
- Distribución espacial en racks del layout canónico (filas A-F, columnas
  001-018) más al menos un rack fuera del layout (Z-999) para UNKNOWN_RACK

El formato de cada evento es idéntico al que mandaría el WebSocket en vivo:
{ "t": offset_segundos, "msg": <payload v2> }

donde msg.type ∈ {"anomaly", "narration"}.

ReplayConnection.cs lee este archivo y dispara los mismos eventos C# que
WMSConnection, así que el resto del cliente Unity no nota la diferencia.

Reusa los modelos del backend (AnomalyEvent / NarrationResult) y sus
serializadores `to_websocket_payload()` cuando están disponibles, de modo
que el contrato queda garantizado por una única fuente de verdad. Si el
backend no se puede importar, cae a una construcción equivalente con dicts.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# --- Reuso de los modelos del backend (fuente de verdad del contrato v2) ----
HERE = Path(__file__).resolve().parent
BACKEND_SRC = HERE.parent / "backend" / "src"
if BACKEND_SRC.is_dir():
    sys.path.insert(0, str(BACKEND_SRC))

try:
    from warehouse_twin.models.anomaly import AnomalyEvent, AnomalyType  # type: ignore
    from warehouse_twin.models.narrative import NarrationResult  # type: ignore
    from warehouse_twin.models.severity import Severity  # type: ignore

    HAVE_BACKEND = True
except Exception:  # pragma: no cover - fallback determinista sin pydantic
    HAVE_BACKEND = False

    class AnomalyType:  # type: ignore
        NEGATIVE_QUANTITY = "NEGATIVE_QUANTITY"
        DURATION_OUTLIER = "DURATION_OUTLIER"
        TRACEABILITY_BROKEN = "TRACEABILITY_BROKEN"
        UNKNOWN_RACK = "UNKNOWN_RACK"

    class Severity:  # type: ignore
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"


BASE_TS = datetime(2026, 5, 17, 14, 30, 0)


def _at(t: float) -> str:
    """Timestamp legible (segundos enteros) a partir de un offset relativo."""
    secs = int(round(t))
    h, rem = divmod(BASE_TS.hour * 3600 + BASE_TS.minute * 60 + BASE_TS.second + secs, 3600)
    m, s = divmod(rem, 60)
    return f"{BASE_TS:%Y-%m-%d} {h:02d}:{m:02d}:{s:02d}"


# Guion curado de la demo.
# (offset_seg, anomaly_id, movement_id, rack_id, anomaly_type, severity,
#  detail, narration[text/likely_cause/recommended_action])
SCRIPT = [
    (
        3.0, "AN-000001", "MV-000001", "C-018",
        AnomalyType.DURATION_OUTLIER, Severity.HIGH,
        "Duración 412s supera el máximo (180s); posible bloqueo.",
        (
            "Operación fuera del rango temporal esperado en C-018: 412s frente a un máximo de 180s.",
            "Bloqueo del proceso o equipo de scanning con falla.",
            "Verificar físicamente el rack y liberar dependencias.",
        ),
    ),
    (
        11.0, "AN-000002", "MV-000002", "A-005",
        AnomalyType.NEGATIVE_QUANTITY, Severity.HIGH,
        "Cantidad resultante -3 unidades; el stock no puede ser negativo.",
        (
            "El movimiento dejó el inventario de A-005 en -3 unidades, lo cual es imposible físicamente.",
            "Falta una entrada de transformación o un conteo manual erróneo.",
            "Pausar la línea, recontar el rack y registrar la entrada faltante.",
        ),
    ),
    (
        20.0, "AN-000003", "MV-000003", "F-012",
        AnomalyType.TRACEABILITY_BROKEN, Severity.HIGH,
        "El lote en F-012 no tiene ASN ni movimiento de entrada asociado.",
        (
            "Trazabilidad rota en F-012: el lote no tiene origen registrado en sistema.",
            "Recepción no registrada o lote ingresado por un proceso paralelo no auditado.",
            "Bloquear el lote y abrir investigación con calidad para validar el origen.",
        ),
    ),
    (
        29.0, "AN-000004", "MV-000004", "Z-999",
        AnomalyType.UNKNOWN_RACK, Severity.HIGH,
        "Ubicación 'Z-999' no existe en el layout del almacén.",
        (
            "Se reportó actividad en Z-999, un rack que no pertenece al layout canónico.",
            "Error de captura del operario o etiqueta de ubicación dañada/falsa.",
            "Validar la ubicación física y corregir el maestro de ubicaciones.",
        ),
    ),
    (
        38.0, "AN-000005", "MV-000005", "B-007",
        AnomalyType.DURATION_OUTLIER, Severity.MEDIUM,
        "Duración 240s sobre el baseline; revisar pero sin urgencia crítica.",
        (
            "Picking prolongado en B-007: 240s, por encima del baseline esperado.",
            "Producto difícil de localizar o stock parcial.",
            "Confirmar inventario físico y reportar al supervisor de turno.",
        ),
    ),
    (
        47.0, "AN-000006", "MV-000006", "D-003",
        AnomalyType.TRACEABILITY_BROKEN, Severity.MEDIUM,
        "Salto de secuencia en la trazabilidad del lote de D-003.",
        (
            "La cadena de trazabilidad de D-003 presenta un salto entre movimientos consecutivos.",
            "Un evento intermedio no fue registrado a tiempo en el WMS.",
            "Revisar el historial del lote y completar el evento faltante.",
        ),
    ),
    (
        56.0, "AN-000007", "MV-000007", "E-014",
        AnomalyType.UNKNOWN_RACK, Severity.MEDIUM,
        "Formato de ubicación válido pero E-014 está marcado como inactivo.",
        (
            "E-014 figura en el layout pero está fuera de servicio; no debería recibir movimientos.",
            "Tarea asignada a un rack inactivo por una regla de slotting desactualizada.",
            "Reasignar la tarea a un rack activo y revisar la regla de slotting.",
        ),
    ),
    (
        65.0, "AN-000008", "MV-000008", "A-001",
        AnomalyType.NEGATIVE_QUANTITY, Severity.MEDIUM,
        "Ajuste dejó -1 unidad en A-001 tras un movimiento de maquila.",
        (
            "El ajuste de maquila dejó A-001 en -1 unidad.",
            "BOM mal configurado o doble descuento de inventario.",
            "Revisar el BOM del producto y corregir el ajuste.",
        ),
    ),
    (
        74.0, "AN-000009", "MV-000009", "C-006",
        AnomalyType.DURATION_OUTLIER, Severity.LOW,
        "Duración 95s ligeramente sobre lo normal; informativo.",
        (
            "Putaway en C-006 algo más lento de lo habitual (95s); dentro de tolerancia.",
            "Variación normal de carga de trabajo en el turno.",
            "Sin acción inmediata; monitorear si se repite.",
        ),
    ),
    (
        82.0, "AN-000010", "MV-000010", "F-001",
        AnomalyType.TRACEABILITY_BROKEN, Severity.LOW,
        "Pequeño desfase de timestamp en el registro de trazabilidad de F-001.",
        (
            "Desfase menor de timestamps en la trazabilidad de F-001; sin impacto operativo.",
            "Reloj del dispositivo de scanning ligeramente desincronizado.",
            "Sincronizar el dispositivo; no requiere intervención sobre el lote.",
        ),
    ),
]

# Retraso entre una anomalía y su narración (segundos).
NARRATION_DELAY = 1.5


def _to_str(value) -> str:
    """Normaliza enums (con .value) o strings planos a su representación JSON."""
    return getattr(value, "value", value)


def build_anomaly_msg(anomaly_id, movement_id, rack_id, anomaly_type, severity, detail, t):
    if HAVE_BACKEND:
        return AnomalyEvent(
            id=anomaly_id,
            movement_id=movement_id,
            rack_id=rack_id,
            type=anomaly_type,
            severity=severity,
            detail=detail,
            detector="rule",
            timestamp=BASE_TS,
        ).to_websocket_payload() | {"timestamp": _at(t)}
    return {
        "type": "anomaly",
        "id": anomaly_id,
        "movement_id": movement_id,
        "rack_id": rack_id,
        "anomaly_type": _to_str(anomaly_type),
        "severity": _to_str(severity),
        "detail": detail,
        "detector": "rule",
        "timestamp": _at(t),
    }


def build_narration_msg(anomaly_id, rack_id, narration, t):
    text, likely_cause, recommended_action = narration
    if HAVE_BACKEND:
        return NarrationResult(
            anomaly_id=anomaly_id,
            rack_id=rack_id,
            text=text,
            likely_cause=likely_cause,
            recommended_action=recommended_action,
            model="template-v1",
            latency_ms=0,
            emitted_at=BASE_TS,
        ).to_websocket_payload() | {"emitted_at": _at(t)}
    return {
        "type": "narration",
        "anomaly_id": anomaly_id,
        "rack_id": rack_id,
        "text": text,
        "likely_cause": likely_cause,
        "recommended_action": recommended_action,
        "model": "template-v1",
        "latency_ms": 0,
        "emitted_at": _at(t),
    }


def main():
    events = []

    for (t, anomaly_id, movement_id, rack_id, anomaly_type, severity,
         detail, narration) in SCRIPT:
        events.append({
            "t": round(t, 2),
            "msg": build_anomaly_msg(
                anomaly_id, movement_id, rack_id, anomaly_type, severity, detail, t
            ),
        })
        nt = t + NARRATION_DELAY
        events.append({
            "t": round(nt, 2),
            "msg": build_narration_msg(anomaly_id, rack_id, narration, nt),
        })

    events.sort(key=lambda e: e["t"])

    replay = {
        "name": "warehouse_demo_v2",
        "duration_sec": 90.0,
        "loop": True,
        "events": events,
    }

    out_path = (HERE.parent / "unity_client" / "Assets" / "StreamingAssets" / "replay.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(replay, indent=2, ensure_ascii=False))

    anomalies = sum(1 for e in events if e["msg"]["type"] == "anomaly")
    narrations = sum(1 for e in events if e["msg"]["type"] == "narration")
    print(f"Replay generado en {out_path}")
    print(f"  Modelos backend: {'sí' if HAVE_BACKEND else 'no (fallback dicts)'}")
    print(f"  Eventos totales: {len(events)}")
    print(f"  Anomalías: {anomalies}")
    print(f"  Narraciones: {narrations}")
    print(f"  Duración: {replay['duration_sec']}s")
    print(f"  Tamaño: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
