"""Punto de entrada para el ejecutable standalone v0.1."""
import sys
import os

# Cuando PyInstaller extrae, los archivos van a _MEIPASS.
# Aseguramos que src/ quede en el path para los imports.
if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    src_path = os.path.join(base, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    print("=" * 56)
    print("  Warehouse Digital Twin  v0.1")
    print(f"  Backend: http://{host}:{port}")
    print(f"  Docs:    http://{host}:{port}/docs")
    print(f"  WS:      ws://{host}:{port}/ws/alerts")
    print("=" * 56)

    uvicorn.run(
        "warehouse_twin.app:app",
        host=host,
        port=port,
        log_level="info",
    )
