# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Warehouse Digital Twin v0.1

import sys
from pathlib import Path

SRC = str(Path("src").resolve())

a = Analysis(
    ["main.py"],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=[
        # FastAPI / Starlette internals
        "fastapi",
        "fastapi.middleware.cors",
        "starlette",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.routing",
        "starlette.responses",
        "starlette.websockets",
        # Uvicorn
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.config",
        # Pydantic
        "pydantic",
        "pydantic_settings",
        "pydantic.deprecated.class_validators",
        # httpx
        "httpx",
        "httpx._transports.default",
        # websockets
        "websockets",
        "websockets.legacy",
        "websockets.legacy.server",
        # anyio
        "anyio",
        "anyio._backends._asyncio",
        # h11
        "h11",
        # email / stdlib used by pydantic
        "email.mime.text",
        "email.mime.multipart",
        # warehouse_twin modules
        "warehouse_twin",
        "warehouse_twin.app",
        "warehouse_twin.config",
        "warehouse_twin.config.settings",
        "warehouse_twin.models",
        "warehouse_twin.models.movement",
        "warehouse_twin.models.anomaly",
        "warehouse_twin.models.narrative",
        "warehouse_twin.models.severity",
        "warehouse_twin.detection",
        "warehouse_twin.detection.anomaly_detector",
        "warehouse_twin.detection.rule_engine",
        "warehouse_twin.detection.model_ensemble",
        "warehouse_twin.narration",
        "warehouse_twin.narration.base",
        "warehouse_twin.narration.mock_narrator",
        "warehouse_twin.narration.ollama_narrator",
        "warehouse_twin.narration.fallback_narrator",
        "warehouse_twin.streaming",
        "warehouse_twin.streaming.connection_manager",
        "warehouse_twin.streaming.websocket_broker",
        "warehouse_twin.simulation",
        "warehouse_twin.simulation.movement_simulator",
        "warehouse_twin.simulation.anomaly_injector",
    ],
    excludes=["tkinter", "matplotlib", "PIL", "numpy", "pandas", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="warehouse-twin-v0.1",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
