# Warehouse Digital Twin — v0.1

**Plataforma:** Linux x86-64  
**Fecha:** 2026-05-17  
**Tamaño:** ~20 MB (single binary, sin instalador)

## Qué incluye

Ejecutable standalone del **backend FastAPI** con:

- Motor de detección de anomalías (4 reglas + ensemble heurístico)
- Narrador LLM (MockNarrator por defecto; Ollama si está disponible)
- WebSocket en tiempo real `/ws/alerts` para el cliente Unity
- Simulador interno de eventos WMS
- Endpoint REST `/ingest` para conectar un WMS externo

## Cómo ejecutar

```bash
chmod +x warehouse-twin-v0.1
./warehouse-twin-v0.1
```

El servidor levanta en `http://0.0.0.0:8000` por defecto.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `HOST` | `0.0.0.0` | Interfaz de red |
| `PORT` | `8000` | Puerto HTTP |
| `OLLAMA_ENABLED` | `false` | Activar narración con Ollama |
| `OLLAMA_URL` | `http://localhost:11434` | URL de Ollama |
| `SIMULATOR_ENABLED` | `true` | Simular eventos WMS internos |
| `SIMULATOR_RATE` | `2.0` | Movimientos por segundo |
| `SIMULATOR_ANOMALY_RATIO` | `0.15` | Fracción de anomalías inyectadas |

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Info del servicio |
| `GET` | `/healthz` | Health check |
| `GET` | `/docs` | Swagger UI |
| `POST` | `/ingest` | Ingesta de movimiento WMS |
| `WS` | `/ws/alerts` | Stream de alertas para Unity |

## Cliente Unity

El cliente Unity debe abrirse con Unity 6 LTS + URP.  
Ver `unity_client/docs/SETUP.md` para la configuración completa.  
Conectar al WebSocket en `ws://localhost:8000/ws/alerts`.
