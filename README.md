# Warehouse Digital Twin · v2

> Gemelo digital de un almacén WMS con detección híbrida de anomalías en tiempo real, narración determinista por plantilla (LLM destilado offline) y visualización 3D en Unity.

[![Backend Tests](https://github.com/USER/warehouse-digital-twin/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/USER/warehouse-digital-twin/actions/workflows/backend-tests.yml)
[![Deploy WebGL](https://github.com/USER/warehouse-digital-twin/actions/workflows/deploy-webgl.yml/badge.svg)](https://github.com/USER/warehouse-digital-twin/actions/workflows/deploy-webgl.yml)

## ¿Qué es esto?

Un sistema que observa el flujo de movimientos de un Warehouse Management System (WMS), detecta anomalías operativas (cantidades negativas, duraciones atípicas, trazabilidad rota, racks desconocidos), las explica en lenguaje natural y las visualiza en un almacén 3D donde cada rack pulsa cuando algo anormal le sucede.

### La decisión que distingue a la v2: dos tiempos

La arquitectura separa una **fase de diseño** (offline, con LLM, donde el no-determinismo es aceptable) de una **fase de runtime** (online, sin LLM, determinista y rápida). El LLM no opera en vivo: durante el diseño **destila** las reglas de detección y **pre-genera** las plantillas de narración, que quedan versionadas en git. En runtime el sistema corre sin LLM, con latencia cercana a cero y salida reproducible.

```
FASE DE DISEÑO (offline · LLM local · artefactos versionados)
  simulador ─► Ollama (llama3.2) ─► reglas + narration_templates.json + metrics_report.md

FASE DE RUNTIME (online · SIN LLM · determinista)
  WMS/Simulator ─► HybridDetector ─► TemplateNarrator ─► WebSocketBroker ─► Unity/Web
                  (reglas + ML)      (plantilla, 0 ms)     (WS /ws/events)   (3D / dashboard)
```

> **Fundamento:** Zhang & Jain (Amazon) muestran que destilar el conocimiento de un LLM en reglas interpretables logra F1 equivalente a una fracción del costo, sin la latencia, el no-determinismo ni las alucinaciones del LLM en línea.

## Demo

- **Demo pública (GitHub Pages)**: `https://USER.github.io/warehouse-digital-twin/` — modo replay con eventos pregrabados
- **Demo local**: backend FastAPI + Unity Editor — modo live con detección y LLM reales

## Arquitectura

```
┌──────────────────────┐          ┌──────────────────────────┐
│   WMS externo o      │  POST    │   Backend FastAPI        │
│   Simulator interno  │ /movements│   (Python, POO)          │
└──────────────────────┘          │  ┌────────────────────┐  │
                                   │  │ HybridDetector     │  │
                                   │  │  ├ RuleBasedDetector│ │
                                   │  │  └ MLAnomalyDetector│ │
                                   │  └────────────────────┘  │
                                   │  ┌────────────────────┐  │
                                   │  │ TemplateNarrator   │  │
                                   │  │ (plantilla · 0 ms) │  │
                                   │  └────────────────────┘  │
                                   │  ┌────────────────────┐  │
                                   │  │ WebSocketBroker    │  │
                                   │  └─────────┬──────────┘  │
                                   └────────────┼─────────────┘
                                                │ ws:///ws/events
                                                ▼
                                   ┌──────────────────────────┐
                                   │   Unity Client           │
                                   │  ┌────────────────────┐  │
                                   │  │ WMSConnection      │  │
                                   │  │ ReplayConnection   │  │
                                   │  │   (intercambiables)│  │
                                   │  └─────────┬──────────┘  │
                                   │  ┌─────────▼──────────┐  │
                                   │  │ WMSEventBus        │  │
                                   │  └─────────┬──────────┘  │
                                   │  ┌─────────▼──────────┐  │
                                   │  │ AnomalyVisualizer  │  │
                                   │  │ AlertFeedUI        │  │
                                   │  │ NarrativePanelUI   │  │
                                   │  └────────────────────┘  │
                                   └──────────────────────────┘
```

## Estructura del repositorio

```
warehouse-digital-twin/
├── backend/                            # Backend Python (FastAPI + IA + Ollama)
│   ├── src/warehouse_twin/
│   │   ├── models/                     # Modelos de dominio (Pydantic v2)
│   │   │   ├── movement.py             # Movement + MovementType (id, rack_id, duration_s)
│   │   │   ├── anomaly.py              # AnomalyEvent + AnomalyType (enum)
│   │   │   ├── narrative.py            # NarrationResult
│   │   │   └── severity.py             # Severity (LOW/MEDIUM/HIGH)
│   │   ├── detection/                  # Detección (ABC + implementaciones)
│   │   │   ├── base.py                 # AnomalyDetector (ABC)
│   │   │   ├── rule_engine.py          # RuleBasedDetector (Strategy + Composite)
│   │   │   ├── ml_detector.py          # MLAnomalyDetector (Isolation Forest)
│   │   │   └── hybrid.py               # HybridDetector (Composite reglas + ML)
│   │   ├── narration/                  # Narración (runtime sin LLM)
│   │   │   ├── base.py                 # LLMNarrator (abstract)
│   │   │   ├── template_backend.py     # TemplateNarrator (runtime, 0 ms)
│   │   │   ├── narration_templates.json# Plantillas pre-generadas offline
│   │   │   ├── mock_narrator.py        # Fallback mínimo
│   │   │   ├── ollama_narrator.py      # Cliente Ollama (solo fase de diseño)
│   │   │   └── fallback_narrator.py    # Chain Template → Mock
│   │   ├── design/                     # FASE DE DISEÑO offline (no runtime)
│   │   │   ├── evaluate.py             # F1 por tipo → metrics_report.md
│   │   │   ├── rule_distiller.py       # Destila reglas desde falsos negativos
│   │   │   └── template_generator.py   # Genera plantillas con Ollama
│   │   ├── streaming/                  # WebSocket
│   │   │   ├── connection_manager.py   # Gestor de conexiones
│   │   │   └── websocket_broker.py     # Mediator detect→narrate→publish
│   │   ├── simulation/                 # Simulador (ground truth + drift)
│   │   │   ├── anomaly_injector.py     # Generador sintético etiquetado
│   │   │   └── movement_simulator.py   # Loop async
│   │   ├── static/index.html           # Dashboard web (cliente de pruebas)
│   │   ├── config/settings.py          # Pydantic Settings
│   │   └── app.py                      # FastAPI app (orquestador)
│   ├── tests/                          # pytest (20 tests)
│   └── pyproject.toml
│
├── unity_client/                       # Cliente Unity 6 + URP
│   ├── Assets/
│   │   ├── Scripts/
│   │   │   ├── Models/                 # WMSMessage.cs (DTOs)
│   │   │   ├── Connection/             # WebSocket + Replay + EventBus
│   │   │   ├── Visualization/          # AnomalyVisualizer, RackRegistry, etc.
│   │   │   ├── UI/                     # AlertFeedUI, NarrativePanelUI
│   │   │   ├── Camera/                 # CameraOrbitController
│   │   │   └── Editor/                 # WarehouseGridGenerator
│   │   ├── Shaders/                    # WarehouseRack.shader + RackOutline.shader
│   │   └── StreamingAssets/replay.json # Demo grabada (90s)
│   └── docs/                           # Guías SETUP, BUILD, DEPLOY, SHADERS
│
├── replay_tool/
│   └── generate_replay.py              # Genera replay.json sintético
│
└── .github/workflows/
    ├── backend-tests.yml               # CI tests Python
    ├── deploy-webgl.yml                # Build Unity + deploy GitHub Pages
    └── acquire-license.yml             # Setup one-time licencia Unity
```

## Quick start

### Backend

```bash
cd backend
pip install -e ".[dev]"                     # núcleo (runtime sin LLM)
pip install -e ".[dev,ml]"                  # opcional: añade Isolation Forest (sklearn)
pytest tests/                               # corre 20 tests
uvicorn warehouse_twin.app:app --reload     # http://localhost:8000
```

Endpoints (v2):
- `GET  /` — dashboard web
- `GET  /healthz` — health con estado de dependencias
- `POST /movements` — recibe un Movement JSON y dispara la pipeline
- `GET  /anomalies/recent?limit=N` — últimas anomalías
- `WS   /ws/events` — stream de anomalías y narraciones
- `GET  /api/docs` — Swagger

Fase de diseño (offline, requiere Ollama corriendo):

```bash
python -m warehouse_twin.design.evaluate --n 5000          # F1 por tipo → metrics_report.md
python -m warehouse_twin.design.template_generator --variants 3  # regenera plantillas
python -m warehouse_twin.design.rule_distiller --n 3000    # propone reglas (revisión humana)
```

### Cliente Unity

Ver `unity_client/docs/SETUP.md` para la configuración paso a paso.
Resumen: Unity 6 LTS con plantilla URP, instalar NativeWebSocket vía UPM, ejecutar `Tools > Warehouse > Generate Grid`.

### Demo pública (GitHub Pages)

Ver `unity_client/docs/DEPLOY_GITHUB_PAGES.md`.

## Patrones POO aplicados

| Módulo | Patrón | Por qué |
|---|---|---|
| `detection/base` | Abstract Base Class | Contrato `detect()` común a reglas, ML e híbrido |
| `detection/rule_engine` | Strategy + Composite | Reglas independientes que el detector orquesta |
| `detection/ml_detector` | Strategy | Isolation Forest tras la misma interfaz `AnomalyDetector` |
| `detection/hybrid` | Composite | Compone reglas + ML deduplicando |
| `narration/base` | Strategy + Abstract Base | Intercambiar backends de narración |
| `narration/template_backend` | Strategy | Narración determinista 0 ms (sin LLM en runtime) |
| `narration/fallback_narrator` | Chain of Responsibility | Template → Mock automático |
| `streaming/websocket_broker` | Mediator | Coordina detector + narrator + manager |
| `config/settings` | Singleton module-level | Configuración única tipada |
| `app.py` | Composition Root | Único lugar donde se instancian concretos |
| Unity: `WMSEventBus` | Pub/Sub estático | Desacopla fuente de datos de UI |
| Unity: `ConnectionModeSelector` | Strategy | Toggle Live/Replay sin tocar UI |
| Unity: `RackRegistry` | Singleton de escena | Lookup O(1) ubicación → GameObject |

## Estado del proyecto

### ✅ Completado

**Backend Python**
- [x] Modelos de dominio con Pydantic V2
- [x] Motor de reglas extensible (4 reglas iniciales)
- [x] Ensemble IA con interfaz Strategy (heurístico funcional)
- [x] Narrador LLM con Ollama + fallback automático a Mock
- [x] Broker WebSocket con flujo asíncrono (alerta inmediata + narrativa diferida)
- [x] Simulador interno configurable
- [x] Settings centralizadas con env vars
- [x] FastAPI app con lifespan y dependency injection
- [x] Test suite (7/7 passing)
- [x] CI workflow para tests automáticos

**Cliente Unity**
- [x] DTOs `WMSMessage.cs` compatibles con JsonUtility
- [x] Cliente WebSocket con reconexión (`WMSConnection`)
- [x] Cliente Replay para demo estática (`ReplayConnection`)
- [x] EventBus para desacoplar fuente de datos (`WMSEventBus`)
- [x] Visualizador con pulse animation (`AnomalyVisualizer`)
- [x] Feed lateral de alertas (`AlertFeedUI`)
- [x] Panel de narrativa LLM (`NarrativePanelUI`)
- [x] Cámara orbital con drag y zoom
- [x] Generador procedural de grid (Editor tool)
- [x] Shader emissive con pulse HDR (`WarehouseRack.shader`)
- [x] Shader outline inverted hull (`RackOutline.shader`)
- [x] Suavizado de normales en runtime para outline limpio

**Infraestructura**
- [x] Workflow CI/CD para Unity WebGL build
- [x] Workflow para deploy a GitHub Pages
- [x] Replay JSON con 21 eventos cinematográficos
- [x] Documentación completa: SETUP, BUILD, DEPLOY, SHADERS, VOLUME_PROFILE

### 🚧 Falta por integrar y programar

**Prioridad ALTA (necesario para demo end-to-end real)**

- [ ] **Walkthrough Unity Editor: armar la escena**
  - Crear escena `Warehouse.unity`, montar jerarquía `_Bootstrap/*`
  - Configurar Canvas con Feed UI y Narrative Panel
  - Aplicar materiales a los racks
  - Crear el Volume Profile (ver `docs/VOLUME_PROFILE.md`)
  - Asignar referencias en todos los Inspector
- [ ] **Modelo IA entrenado (Isolation Forest + ECOD)**
  - Generar dataset sintético JDA-like (~50k filas)
  - Entrenar y serializar a `backend/models/iforest_v1.pkl`
  - Conectar `IsolationForestEnsemble.score()` para cargar el pickle
  - Esto sustituye `HeuristicEnsemble` y debería subir F1 de ~0.6 a ~0.75
- [ ] **Setup de licencia Unity en GitHub Actions**
  - Ejecutar workflow `acquire-license.yml` una vez
  - Subir el `.ulf` resultante como secret `UNITY_LICENSE`
  - Validar el primer build con un push a `main`

**Prioridad MEDIA (polish para el día del pitch)**

- [ ] **Configurar Volume Profile en escena**
  - Bloom threshold 1.0, intensity 1.2, scatter 0.7
  - Tonemapping ACES
  - Probar valores en Play Mode
- [ ] **Habilitar Decompression Fallback en Player Settings**
  - Crítico para que GitHub Pages funcione (ver `docs/BUILD_SETTINGS.md`)
- [ ] **Modo Live con query string**
  - Parche en `WMSConnection.cs` para leer `?live=wss://...` del URL
  - Permite alternar modos sin rebuild
- [ ] **Pitch deck**
  - 5-7 slides con screenshots reales de la demo
  - Estructura: problema, solución, demo, arquitectura, métricas, equipo, ask

**Prioridad BAJA (refinamientos opcionales)**

- [ ] **Persistencia de eventos en TimescaleDB**
  - Guardar Movement + Anomaly para histórico y métricas
  - Endpoint `/metrics` con KPIs (anomalías/hora, latencia media, etc.)
- [ ] **Dashboard web 2D complementario**
  - Next.js + Tremor con métricas históricas
  - Útil para supervisores que no quieren abrir Unity
- [ ] **Polish visual extra Unity**
  - Lights puntuales sincronizadas con el pulse
  - Particle System cuando severity = critical
  - Sustituir cubos por mesh de rack industrial real
- [ ] **Autenticación en /ingest**
  - API key vía header `X-API-Key`
  - Necesario para conectar un WMS real en producción
- [ ] **Tests E2E**
  - Levantar backend + cliente HTTP simulado
  - Validar que un POST /ingest genera 2 mensajes WS (alert + narrative)
- [ ] **Métricas Prometheus**
  - `/metrics` endpoint con counters de mensajes, latencias, errores
  - Útil si se despliega en cloud para observability

## Stack tecnológico

| Capa | Tech | Por qué |
|---|---|---|
| Backend API | FastAPI + uvicorn | WebSockets nativos, async, tipado fuerte |
| Validación | Pydantic V2 | Validación + serialización en una librería |
| LLM | Ollama (local) | Privacidad, gratis, sin rate limits |
| Modelo LLM | Llama 3.2 3B | Funciona en laptops, calidad suficiente |
| Detección IA | scikit-learn + PyOD | Isolation Forest + ECOD ensemble |
| Engine 3D | Unity 6 LTS + URP | Bloom, shadows, web export |
| WebSocket Unity | endel/NativeWebSocket | 800+ stars, soporta WebGL |
| CI/CD | GitHub Actions + GameCI | Standard de facto para Unity CI |
| Hosting demo | GitHub Pages | Gratis, HTTPS, dominio profesional |

## Licencia

MIT. Ver `LICENSE`.

## Créditos

Desarrollado por J. Cain. Construido durante 7 sesiones de pair programming con Claude (Anthropic), iterando arquitectura, modelos, shaders y CI/CD.
