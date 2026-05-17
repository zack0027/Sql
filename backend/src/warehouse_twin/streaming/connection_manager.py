"""
Gestor de conexiones WebSocket.

Diseño POO: encapsula el conjunto de clientes conectados y expone una
interfaz simple (connect, disconnect, broadcast). Thread-safe vía asyncio.
"""
from __future__ import annotations

from typing import List

from fastapi import WebSocket


class ConnectionManager:
    """Mantiene el set de WebSockets activos."""

    def __init__(self):
        self._active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._active:
            self._active.remove(websocket)

    async def broadcast(self, payload: dict) -> None:
        """
        Envía el payload a TODOS los clientes conectados.

        Si algún cliente falla, se desconecta silenciosamente para no romper
        el broadcast a los demás.
        """
        stale: List[WebSocket] = []
        for ws in self._active:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._active)
