"""
FastAPI app: orquesta los 5 módulos del backend.

Endpoints:
  GET  /         - Dashboard web (UI)
  GET  /healthz  - Liveness para load balancers
  POST /ingest   - Recibir un movimiento desde un WMS externo
  WS   /ws/alerts - Stream de alertas y narrativas para clientes Unity/web
  GET  /api/status           - Estado del sistema
  GET  /api/anomalies        - Últimas anomalías guardadas
  POST /api/simulator/toggle - Activar/desactivar simulador

Diseño POO: dependency injection vía lifespan. Las instancias singleton
(detector, narrator, manager, broker, simulator) viven en app.state.
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
from .detection import AnomalyDetector
from .models import Movement
from .narration import MockNarrator, build_default_narrator
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


@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    Construye los singletons al arrancar la app y los limpia al cerrar.

    Patrón: Composition Root. Aquí es el único lugar donde se instancian
    las clases concretas; todo lo demás recibe interfaces por inyección.
    """
    log.info("Building services...")

    # In-memory anomaly store
    application.state.recent_anomalies = []
    application.state.anomaly_count = 0

    detector = AnomalyDetector()

    if settings.ollama_enabled:
        narrator = build_default_narrator()  # Ollama → Mock
    else:
        narrator = MockNarrator()

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

    log.info("Services ready. Ollama=%s", await narrator.is_available())
    yield

    log.info("Shutting down...")
    if application.state.simulator:
        await application.state.simulator.stop()
    await broker.shutdown()


app = FastAPI(
    title="Warehouse Digital Twin API",
    version="1.0.0",
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
    return {
        "ok": True,
        "connections": app.state.manager.count,
        "ollama_available": await app.state.narrator.is_available(),
    }


@app.post("/ingest")
async def ingest(movement: Movement):
    """Ingesta de movimiento desde un WMS externo."""
    await app.state.broker.process_movement(movement)
    return {"accepted": True, "movement_id": movement.movement_id}


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    """Stream de alertas y narrativas para el cliente Unity."""
    await app.state.manager.connect(websocket)
    await websocket.send_json({"type": "hello", "version": "1.0.0"})
    try:
        while True:
            # Mantiene la conexión viva; no leemos nada del cliente todavía.
            await websocket.receive_text()
    except WebSocketDisconnect:
        app.state.manager.disconnect(websocket)


# ─── API de monitoreo y control ─────────────────────────────────────────────


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
        "ollama_available": await app.state.narrator.is_available(),
    }


@app.get("/api/anomalies")
async def api_anomalies(limit: int = 50):
    """Retorna las últimas `limit` anomalías (más recientes primero)."""
    recent = app.state.recent_anomalies
    return recent[:limit]


@app.post("/api/simulator/toggle")
async def toggle_simulator():
    """Activa o desactiva el simulador de movimientos."""
    sim = app.state.simulator
    if sim is not None and getattr(sim, "_running", False):
        await sim.stop()
        app.state.simulator = None
        return {"running": False}
    else:
        new_sim = MovementSimulator(
            app.state.broker,
            movements_per_second=settings.simulator_rate,
            anomaly_ratio=settings.simulator_anomaly_ratio,
        )
        await new_sim.start()
        app.state.simulator = new_sim
        return {"running": True}
