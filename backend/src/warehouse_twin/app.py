"""
FastAPI app: orquesta el runtime del backend (v2).

Endpoints:
  GET  /                      - Dashboard web (UI)
  GET  /healthz               - Health check con estado de dependencias
  POST /movements            - Ingesta de un movimiento desde un WMS externo
  GET  /anomalies/recent     - Últimas anomalías detectadas
  WS   /ws/events            - Stream de anomalías y narraciones (Unity/web)
  GET  /api/status           - Estado del sistema (utilidad del dashboard)
  POST /api/simulator/toggle - Activar/desactivar simulador

Diseño POO: dependency injection vía lifespan (Composition Root). El runtime
es determinista y SIN LLM en vivo: detección híbrida (reglas + ML) + narración
por plantilla (latencia cero).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .detection import HybridDetector, MLAnomalyDetector, RuleBasedDetector
from .models import Movement
from .narration import build_runtime_narrator
from .simulation import MovementSimulator
from .streaming import ConnectionManager, WebSocketBroker

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("warehouse_twin")

_MAX_RECENT_ANOMALIES = 100


def _store_anomaly(application: FastAPI, payload: dict) -> None:
    """Guarda la anomalía en el store in-memory circular (últimas 100)."""
    recent = application.state.recent_anomalies
    recent.insert(0, payload)
    if len(recent) > _MAX_RECENT_ANOMALIES:
        del recent[_MAX_RECENT_ANOMALIES:]
    application.state.anomaly_count += 1


def _build_detector():
    """
    Arma el detector de runtime.

    Por defecto RuleBasedDetector. Si `ml_enabled` y sklearn está disponible,
    entrena un MLAnomalyDetector con un lote sintético del simulador y compone
    ambos en un HybridDetector (reglas + ML deduplicadas).
    """
    rules = RuleBasedDetector()
    if not settings.ml_enabled:
        return rules, False

    ml = MLAnomalyDetector(contamination=settings.simulator_anomaly_ratio)
    if not ml.available:
        log.warning("ml_enabled=True pero scikit-learn no está instalado; solo reglas.")
        return rules, False

    # Entrenamiento offline ligero con datos sintéticos del simulador.
    from .simulation import AnomalyInjector

    injector = AnomalyInjector(seed=42)
    training = [injector.generate_normal() for _ in range(800)]
    training += [injector.generate_anomaly() for _ in range(200)]
    ml.fit(training)
    log.info("MLAnomalyDetector entrenado con %d movimientos.", len(training))
    return HybridDetector([rules, ml]), True


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Construye los singletons al arrancar y los limpia al cerrar."""
    log.info("Building services...")

    application.state.recent_anomalies = []
    application.state.anomaly_count = 0

    detector, ml_active = _build_detector()
    application.state.ml_active = ml_active

    # Runtime SIEMPRE determinista: TemplateNarrator → Mock. Sin LLM en vivo.
    narrator = build_runtime_narrator()

    manager = ConnectionManager()
    broker = WebSocketBroker(
        detector,
        narrator,
        manager,
        on_broadcast=lambda payload: _store_anomaly(application, payload),
    )

    application.state.detector = detector
    application.state.narrator = narrator
    application.state.manager = manager
    application.state.broker = broker
    application.state.simulator = None

    if settings.simulator_enabled:
        simulator = MovementSimulator(
            broker,
            movements_per_second=settings.simulator_rate,
            anomaly_ratio=settings.simulator_anomaly_ratio,
        )
        await simulator.start()
        application.state.simulator = simulator

    log.info("Services ready. narrator=%s ml=%s", narrator.model_name, ml_active)
    yield

    log.info("Shutting down...")
    if application.state.simulator:
        await application.state.simulator.stop()
    await broker.shutdown()


app = FastAPI(
    title="Warehouse Digital Twin API",
    version="2.0.0",
    lifespan=lifespan,  # type: ignore[arg-type]
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def dashboard():
    """Sirve el dashboard web."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    """Health check con estado de cada dependencia activa (v2, §8.2)."""
    narrator = app.state.narrator
    return {
        "status": "ok",
        "dependencies": {
            "narrator": {"model": narrator.model_name, "available": await narrator.is_available()},
            "ml_detector": {"active": app.state.ml_active},
            "websocket_clients": app.state.manager.count,
        },
    }


@app.post("/movements")
async def post_movement(movement: Movement):
    """Ingesta de un movimiento desde un WMS externo; dispara la pipeline."""
    anomalies = await app.state.broker.process_movement(movement)
    return {
        "accepted": True,
        "movement_id": movement.id,
        "anomalies": [a.id for a in anomalies],
    }


@app.get("/anomalies/recent")
async def anomalies_recent(limit: int = 50):
    """Retorna las últimas `limit` anomalías (más recientes primero)."""
    return app.state.recent_anomalies[:limit]


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    """Stream de anomalías y narraciones para clientes Unity/web."""
    await app.state.manager.connect(websocket)
    await websocket.send_json({"type": "hello", "version": "2.0.0"})
    try:
        while True:
            await websocket.receive_text()  # mantiene viva la conexión
    except WebSocketDisconnect:
        app.state.manager.disconnect(websocket)


# ─── API de monitoreo y control (utilidad del dashboard) ─────────────────────


@app.get("/api/status")
async def api_status():
    """Estado del sistema: conexiones, contadores, config del simulador."""
    sim = app.state.simulator
    return {
        "connections": app.state.manager.count,
        "anomaly_count": app.state.anomaly_count,
        "simulator_enabled": sim is not None and getattr(sim, "_running", False),
        "simulator_rate": settings.simulator_rate,
        "anomaly_ratio": settings.simulator_anomaly_ratio,
        "ml_active": app.state.ml_active,
        "narrator_model": app.state.narrator.model_name,
    }


@app.post("/api/simulator/toggle")
async def toggle_simulator():
    """Activa o desactiva el simulador de movimientos."""
    sim = app.state.simulator
    if sim is not None and getattr(sim, "_running", False):
        await sim.stop()
        app.state.simulator = None
        return {"running": False}
    new_sim = MovementSimulator(
        app.state.broker,
        movements_per_second=settings.simulator_rate,
        anomaly_ratio=settings.simulator_anomaly_ratio,
    )
    await new_sim.start()
    app.state.simulator = new_sim
    return {"running": True}
