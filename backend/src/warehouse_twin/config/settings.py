"""
Settings de la app. Lee de variables de entorno con defaults sensatos.

Diseño POO: singleton vía instancia module-level `settings`. Toda la app
importa `from warehouse_twin.config import settings` y usa los atributos.
Cero strings mágicos repartidos por el código.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración centralizada del backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WMS_",
        extra="ignore",
    )

    # --- Servidor ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["*"]

    # --- Ollama ---
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_sec: float = 30.0
    ollama_enabled: bool = True

    # --- Simulator ---
    simulator_enabled: bool = True
    simulator_rate: float = 2.0
    simulator_anomaly_ratio: float = 0.18

    # --- Detector ---
    detector_score_medium: float = 0.35
    detector_score_high: float = 0.6
    detector_score_critical: float = 0.85


# Singleton module-level (forma idiomática en Python)
settings = Settings()
