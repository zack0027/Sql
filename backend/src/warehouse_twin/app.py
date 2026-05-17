"""
FastAPI app: orquesta los 5 módulos del backend.

Endpoints:
  GET  /         - Health check
  GET  /healthz  - Liveness para load balancers
  POST /ingest   - Recibir un movimiento desde un WMS externo
  WS   /ws/alerts - Stream de alertas y narrativas para clientes Unity

Diseño POO: dependency injection vía lifespan. Las instancias singleton
(detector, narrator, manager, broker, simulator) viven en app.state.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .detection import AnomalyDetector
from .models import Movement
from .narration import MockNarrator, build_default_narrator
from .simulation import MovementSimulator
from .streaming import ConnectionManager, WebSocketBroker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("warehouse_twin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Construye los singletons al arrancar la app y los limpia al cerrar.

    Patrón: Composition Root. Aquí es el único lugar donde se instancian
    las clases concretas; todo lo demás recibe interfaces por inyección.
    """
    log.info("Building services...")

    detector = AnomalyDetector()

    if settings.ollama_enabled:
        narrator = build_default_narrator()  # Ollama → Mock
    else:
        narrator = MockNarrator()

    manager = ConnectionManager()
    broker = WebSocketBroker(detector, narrator, manager)

    app.state.detector = detector
    app.state.narrator = narrator
    app.state.manager = manager
    app.state.broker = broker

    simulator = None
    if settings.simulator_enabled:
        simulator = MovementSimulator(
            broker,
            movements_per_second=settings.simulator_rate,
            anomaly_ratio=settings.simulator_anomaly_ratio,
        )
        await simulator.start()
        app.state.simulator = simulator

    log.info("Services ready. Ollama=%s", await narrator.is_available())
    yield

    log.info("Shutting down...")
    if simulator:
        await simulator.stop()
    await broker.shutdown()


app = FastAPI(
    title="Warehouse Digital Twin API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "warehouse-digital-twin",
        "version": "1.0.0",
        "endpoints": ["/healthz", "/ingest", "/ws/alerts"],
    }


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
