"""
Generador de replay para la demo pública.

Produce un JSON con una secuencia cinematográfica de eventos:
- 90 segundos totales
- 12 alertas mezclando severidades critical/high/medium
- 8 narrativas LLM que llegan 3-5s después de su alerta correspondiente
- Distribución espacial en racks A-001..F-006 para mostrar todo el almacén

El formato de cada evento es idéntico al que mandaría el WebSocket en vivo:
{ "t": offset_segundos, "msg": <WMSMessage payload> }

ReplayConnection.cs lee este archivo y dispara los mismos eventos C# que
WMSConnection, así que el resto del cliente Unity no nota la diferencia.
"""
import json
import random
from pathlib import Path

random.seed(42)  # reproducible

# Anomalías curadas, escogidas para mostrar diversidad de procesos WMS
SCRIPT = [
    # (offset_seg, location, severity, mov_type, sku, qty, dur, rule_reasons)
    (3.0,  "B-004", "high",     "INSPECTION", "MX-0017", 0,  280, "duración_excesiva, sin_actualizacion_status"),
    (8.5,  "C-018", "critical", "INSPECTION", "MX-0042", -3, 4,   "cantidad_negativa, duracion_minima, fuera_horario"),
    (15.0, "A-002", "medium",   "PUTAWAY",    "MX-0008", 12, 45,  "ubicacion_no_optima"),
    (22.0, "D-011", "high",     "PICK",       "MX-0033", 5,  180, "ot_sin_secuencia, tiempo_alto"),
    (29.5, "F-005", "critical", "TRACEABILITY", "MX-0089", 0, 8,  "lote_huerfano, sin_asn_origen"),
    (38.0, "B-001", "medium",   "RECEIVING",  "MX-0021", 50, 92,  "cantidad_diferente_esperada"),
    (45.0, "E-014", "high",     "PICK",       "MX-0055", 2,  220, "duracion_excesiva, mismo_usuario_3x"),
    (53.5, "C-006", "critical", "MAQUILA",    "MX-0073", -1, 6,   "stock_negativo, duracion_minima"),
    (61.0, "A-018", "medium",   "INSPECTION", "MX-0019", 4,  38,  "ubicacion_no_optima"),
    (68.0, "D-003", "high",     "ORDER",      "MX-0044", 8,  165, "ot_atorada, sin_progreso_5min"),
    (75.5, "F-012", "critical", "TRACEABILITY", "MX-0091", 0, 7,  "lote_huerfano, fecha_caducidad_proxima"),
    (83.0, "B-016", "high",     "PUTAWAY",    "MX-0028", 15, 195, "tiempo_excesivo, usuario_novato"),
]

# Plantillas de narrativas, una por movement_type. En producción esto lo
# generaría el LLM real; aquí son textos curados que suenan creíbles.
NARRATIVES = {
    "INSPECTION": {
        "narrative": "Movimiento de inspección con patrón irregular detectado en {loc}. El operario registró duración inusual ({dur}s) sobre el SKU {sku}.",
        "likely_cause": "Posible bloqueo del proceso de inspección o falta de actualización del estado en sistema.",
        "recommended_action": "Verificar físicamente el rack y revisar el último login del usuario asignado.",
    },
    "PUTAWAY": {
        "narrative": "Tarea de putaway en {loc} con desviación respecto al algoritmo de ubicación óptima para el SKU {sku}.",
        "likely_cause": "El sistema sugirió otra ubicación pero el operario la sobrescribió manualmente.",
        "recommended_action": "Revisar la regla de slotting y validar capacidad del rack destino.",
    },
    "PICK": {
        "narrative": "Picking prolongado en {loc} para el SKU {sku}. Duración registrada: {dur}s, más del triple del baseline.",
        "likely_cause": "Producto difícil de localizar, falta de stock parcial, o pickeo con el equipo equivocado.",
        "recommended_action": "Confirmar inventario físico y reportar al supervisor de turno.",
    },
    "TRACEABILITY": {
        "narrative": "Trazabilidad rota en {loc}: el lote del SKU {sku} no tiene ASN ni movimiento de entrada asociado.",
        "likely_cause": "Recepción no registrada en sistema, o lote ingresado por proceso paralelo no auditado.",
        "recommended_action": "Bloquear el lote y abrir investigación con calidad para validar origen.",
    },
    "RECEIVING": {
        "narrative": "Recepción en {loc} con cantidad reportada ({qty}) diferente a la esperada en ASN para el SKU {sku}.",
        "likely_cause": "Discrepancia con el proveedor o conteo manual erróneo en la rampa.",
        "recommended_action": "Detener recepción, recontar, y abrir caso si la diferencia persiste.",
    },
    "MAQUILA": {
        "narrative": "Operación de maquila en {loc} resultó en stock negativo para el SKU {sku}.",
        "likely_cause": "Falta una entrada de transformación o el BOM del producto está mal configurado.",
        "recommended_action": "Pausar la línea, revisar BOM en sistema y registrar la entrada faltante.",
    },
    "ORDER": {
        "narrative": "Orden de trabajo asignada al rack {loc} sin progreso por más de 5 minutos.",
        "likely_cause": "Operario ausente, equipo de scanning con falla, o tarea bloqueada por otra OT activa.",
        "recommended_action": "Reasignar tarea o liberar las dependencias bloqueantes desde la consola del supervisor.",
    },
}


def build_alert_msg(t, loc, sev, mov_type, sku, qty, dur, reasons):
    return {
        "type": "alert",
        "movement_id": f"MV-{int(t*100):06d}",
        "timestamp": f"2026-05-17 10:{int(t//60):02d}:{int(t%60):02d}",
        "movement_type": mov_type,
        "sku": sku,
        "location": loc,
        "user_id": f"USR_{random.randint(1, 60):03d}",
        "quantity": qty,
        "duration_sec": dur,
        "severity": sev,
        "is_anomaly": True,
        "rule_reasons": reasons,
    }


def build_narrative_msg(t, loc, mov_type, sku, qty, dur):
    template = NARRATIVES.get(mov_type, NARRATIVES["INSPECTION"])
    return {
        "type": "narrative",
        "movement_id": f"MV-{int(t*100):06d}",
        "location": loc,
        "narrative": template["narrative"].format(loc=loc, sku=sku, qty=qty, dur=dur),
        "likely_cause": template["likely_cause"],
        "recommended_action": template["recommended_action"],
        "source": "ollama-replay",
        "model": "llama-3.2-3b",
        "latency_sec": round(random.uniform(2.1, 4.8), 2),
        "emitted_at": f"2026-05-17 10:{int(t//60):02d}:{int(t%60):02d}",
    }


def main():
    events = []

    # Insertar alertas
    for t, loc, sev, mov_type, sku, qty, dur, reasons in SCRIPT:
        events.append({
            "t": round(t, 2),
            "msg": build_alert_msg(t, loc, sev, mov_type, sku, qty, dur, reasons),
        })

        # Para severidades critical y high, generar narrativa que llega 3-5s después
        if sev in ("critical", "high"):
            narrative_t = t + random.uniform(3.0, 5.0)
            events.append({
                "t": round(narrative_t, 2),
                "msg": build_narrative_msg(narrative_t, loc, mov_type, sku, qty, dur),
            })

    # Ordenar por tiempo
    events.sort(key=lambda e: e["t"])

    replay = {
        "name": "warehouse_demo_v1",
        "duration_sec": 90,
        "events": events,
        "loop": True,
        "generated_by": "replay_generator.py",
    }

    out_path = Path("../unity_client/Assets/StreamingAssets/replay.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(replay, indent=2, ensure_ascii=False))

    alerts = sum(1 for e in events if e["msg"]["type"] == "alert")
    narratives = sum(1 for e in events if e["msg"]["type"] == "narrative")
    print(f"Replay generado en {out_path}")
    print(f"  Eventos totales: {len(events)}")
    print(f"  Alertas: {alerts}")
    print(f"  Narrativas LLM: {narratives}")
    print(f"  Duración: {replay['duration_sec']}s")
    print(f"  Tamaño: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
