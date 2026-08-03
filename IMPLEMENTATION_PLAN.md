# HANA Knowledge Engine — Plan de Implementación

> Estado del documento: **vivo**. Se actualiza al cerrar cada etapa.
> Última actualización: cierre de la **Etapa 6, secciones 1 a 3 y 5**.
>
> Las secciones 1 a 3 (estado inicial, principio rector y decisiones) describen
> el punto de partida y no se reescriben: valen precisamente porque dicen qué se
> decidió antes de saber cómo iba a salir. La sección 4 sí lleva el estado real,
> incluidas las cosas que acabaron haciéndose de otra manera.

---

## 1. Estado inicial del repositorio

El repositorio `zack0027/sql` estaba **vacío**: un único archivo `.gitkeep` y un
commit inicial (`b1f1fc6 Initialize repository`). No había código, ni
configuración, ni historial del que partir. Todo lo descrito aquí se construye
desde cero.

Herramientas verificadas en el entorno de desarrollo:

| Herramienta | Versión | Uso |
|---|---|---|
| Node | 22.22.2 | Frontend / Vite |
| pnpm | 10.33.0 | Gestor de paquetes del monorepo |
| Python | 3.11.15 | Motor de análisis |
| Rust / Cargo | 1.94.1 | Núcleo nativo y host Tauri |
| SQLite (libsqlite3 vía Python) | 3.45.1 | Persistencia (incluye FTS5) |

---

## 2. Principio arquitectónico rector

> **El motor de conocimiento es el producto. Tauri es solamente la carcasa y el
> guardián del sistema de archivos. El modelo de lenguaje es un accesorio
> opcional.**

De ahí se derivan tres reglas que gobiernan todo el código:

1. **El motor no importa nada de Tauri.** `engine/` es un paquete Python puro,
   ejecutable y testeable con `pytest` sin compilar nada de Rust ni de Node.
2. **La UI no contiene lógica de dominio.** El frontend consume tipos
   compartidos y llama comandos; no deduce relaciones ni normaliza nombres.
3. **Nada entra al grafo sin procedencia.** Una entidad o relación sin archivo,
   líneas, fragmento, analizador y confianza es un error de programación, no un
   caso límite.

---

## 3. Decisiones tomadas (y por qué)

### D1 — Reparto Rust / Python

El enunciado asigna a Rust el escaneo y el hashing, y a Python el análisis. Se
respeta, con un matiz necesario para que el motor sea testeable por separado:

| Responsabilidad | Dueño | Motivo |
|---|---|---|
| Validación de rutas permitidas, política de symlinks | **Rust** (`crates/hana-fs`) | Es la frontera de seguridad; debe estar en el proceso que tiene los permisos del SO. |
| Recorrido de directorios, ignorados, límites, SHA-256 | **Rust** (`crates/hana-fs`) | Rendimiento (20.000 archivos) y cancelación sin bloquear la UI. |
| Modelo de dominio, deduplicación, confianza | **Python** (`engine/`) | Es donde vive el conocimiento. |
| SQLite, migraciones, FTS5, repositorios | **Python** (`engine/`) | Un único escritor de la base evita corrupción y bloqueos cruzados. |
| Detección incremental (nuevo/modificado/borrado) | **Python** (`engine/`) | Requiere consultar el estado previo, que vive en SQLite. |
| Analizadores | **Python** (`engine/analyzers/`) | Ecosistema de parsers (tree-sitter, lxml). |

**Duplicación aceptada y controlada:** `engine/hana_engine/indexing/scanner.py`
reimplementa el recorrido en Python. No es un descuido: es el escáner de la ruta
*headless* (CLI y suite de pruebas), para que el motor pueda ejercitarse de
punta a punta sin compilar Rust. Ambas implementaciones responden al mismo
contrato declarado en `packages/shared-types` y a la misma política
(`ScanPolicy`). El riesgo de divergencia se mitiga con:
- un conjunto de invariantes escritas en `docs/SCAN_CONTRACT.md`,
- pruebas espejo (mismos casos, mismos nombres) en `engine/tests/test_scanner.py`
  y `crates/hana-fs/src/scanner.rs`,
- la regla de que cualquier cambio de política se hace primero en el contrato.

### D2 — `crates/hana-fs` es un crate independiente de Tauri

La lógica de escaneo y seguridad vive en un crate **sin dependencia de Tauri**,
con su propio workspace. Consecuencias:
- `cargo test -p hana-fs` corre en cualquier máquina, incluidos contenedores
  Linux sin `webkit2gtk` (donde el shell Tauri no compila).
- La frontera de seguridad se puede auditar y probar aislada.
- `apps/desktop/src-tauri` la consume como dependencia de ruta y solo aporta
  comandos, eventos y el ciclo de vida del sidecar.

### D3 — Un solo escritor de SQLite

Rust **no escribe** en la base. Escanea, hashea y entrega el inventario al
sidecar Python, que es el único proceso que abre la base en modo escritura. Se
usa WAL para permitir lectores concurrentes en el futuro.

### D4 — IPC por JSON-Lines sobre stdin/stdout

Ni HTTP, ni sockets, ni puertos. El sidecar Python habla líneas JSON por sus
descriptores estándar. Motivos: no abre puertos de red (requisito de
seguridad), no necesita autenticación, es trivialmente empaquetable y funciona
idéntico en Windows y Linux. Protocolo en `docs/IPC_PROTOCOL.md`.

### D5 — ULID en lugar de UUID

IDs ULID de 26 caracteres Crockford base32: ordenables por tiempo (los índices
de SQLite no se fragmentan al insertar decenas de miles de entidades), sin
guiones, seguros en URLs y legibles en logs.

### D6 — `identity_key` explícita para deduplicación

En vez de un índice único sobre columnas sueltas, cada entidad y relación
calcula en el dominio una `identity_key` textual y la base impone
`UNIQUE(project_id, identity_key)`. Así la política de deduplicación es código
Python versionado y probado, no un detalle del esquema. Permite además la regla
"no fusionar ante ambigüedad de esquema": si hay esquema conocido, entra en la
clave; si no, la entidad sin esquema queda separada en lugar de fusionarse a
ciegas.

### D7 — FTS5 con contenido externo

Los índices `entities_fts`, `files_fts` y `evidence_fts` usan
`content=` (external content) más triggers. Evita duplicar el texto en disco y
mantiene el índice sincronizado sin código de aplicación.

---

## 4. Etapas

### Etapa 1 — Fundación + Proyectos y Archivos ✅

- [x] Monorepo, workspaces, scripts de desarrollo.
- [x] Modelo de dominio completo (entidades, relaciones, evidencia, confianza).
- [x] Esquema SQLite con migraciones versionadas + FTS5 + índices.
- [x] Repositorios de persistencia.
- [x] Escáner seguro (Rust y Python) con hashing SHA-256.
- [x] Detección incremental: nuevo / modificado / sin cambios / eliminado.
- [x] Historial de versiones de archivo y de ejecuciones de análisis.
- [x] Registro de la interfaz de analizadores (plugins) — sin analizadores aún.
- [x] `LocalModelProvider` desacoplado con implementación deshabilitada.
- [x] Sidecar IPC + CLI headless.
- [x] Host Tauri con comandos y eventos de progreso.
- [x] Pantalla de inicio funcional.
- [x] Pruebas automáticas (pytest + cargo test + vitest).

### Etapa 2 — Motor de análisis (Fase 3 del enunciado) ✅

- [x] `SqlAnalyzer`: SELECT/INSERT/UPDATE/DELETE/MERGE, tablas, vistas, alias,
      columnas calificadas, CTE, subconsultas; lectura vs escritura.
- [x] PL/SQL: procedimientos, funciones, packages, llamadas. **No** salió un
      `PlSqlAnalyzer` aparte: un `.sql` mezcla las dos cosas y separarlos habría
      obligado a leer el archivo dos veces para partir el mismo texto. Vive en
      `SqlAnalyzer`.
- [x] `ApexAnalyzer`: `:P117_ITEM`, `:APP_USER`; inferencia de página (0.9).
- [x] `MocaAnalyzer`: pipelines `|`, `@variables`, `publish data`, `catch(@?)`.
- [x] `JrxmlAnalyzer`: parser XML real, fields/parameters/variables/queries/
      subreports/imágenes; campos usados no definidos; parámetros no usados.
- [x] `JsonAnalyzer` y `CodeAnalyzer`. JavaScript y Python quedaron en un solo
      analizador: comparten el trabajo de "declaraciones e imports", y el que
      importa de verdad es el de Python, que usa `ast` en vez de expresiones
      regulares.
- [x] Fixtures y pruebas por analizador.

### Etapa 3 — Grafo y búsqueda (Fase 4) ✅

- [x] Consultas de grafo con expansión por niveles.
- [x] Búsqueda global FTS5 sobre entidades, rutas, evidencias.
- [x] Lienzo de grafo con carga progresiva; panel de detalles y evidencias.
      **Sin React Flow**: arrastraba seis dependencias que la red de destino no
      alcanza, y lo que hacía falta —anillos acotados, expansión bajo demanda y
      una diferencia visual entre un hecho y una inferencia— cabe en SVG propio.
      Ver `docs/OFFLINE_DEPENDENCIES.md`.

### Etapa 4 — Experiencia (Fase 5) ✅

- [x] Explorador de proyecto de tres paneles, redimensionables.
- [x] Monaco Editor solo lectura con salto a línea y resaltado.
- [x] Progreso, cancelación, filtros, historial, configuración.
- [x] Las 10 consultas deterministas sin modelo de lenguaje.

### Etapa 5 — Empaquetado (Fase 6) ✅ salvo la firma

- [x] Congelar el sidecar Python (PyInstaller).
- [ ] **Firmarlo.** Requiere comprar un certificado; sin él, SmartScreen avisa
      y los antivirus corporativos matan el binario. Ver `docs/FIRMA_DE_CODIGO.md`
      y `docs/DISTRIBUCION.md`.
- [x] Instalador de Windows, verificación sin internet
      (`engine/tests/test_offline.py`).

### Etapa 6 — Impacto, juicio humano y conocimiento operativo

- [x] **1.** Aprovisionamiento de `vendor/` en CI y atribución correcta del
      archivo en las consultas por archivo.
- [x] **2.** Grafo de llamadas PL/SQL (`PROCEDURE_CALLS_PROCEDURE`, que estaba
      en el dominio sin producirse nunca) y análisis de impacto transitivo.
- [x] **3.** Anotaciones manuales que sobreviven al reanálisis, candidatos a
      revisar, comparación entre entornos, y errores de log con sus soluciones.
- [ ] **4.** El modelo local, los embeddings y la conexión a Oracle siguen
      deliberadamente sin hacer. Ver el encargo de la etapa.
- [x] **5.** Arreglos menores y este documento.

---

## 5. Riesgos identificados

| # | Riesgo | Impacto | Mitigación |
|---|---|---|---|
| R1 | **Divergencia entre el escáner Rust y el Python** | Resultados distintos según la ruta de ejecución | Contrato escrito, pruebas espejo, política única (`ScanPolicy`) |
| R2 | **Empaquetar Python dentro de Tauri** es la parte más frágil del proyecto | Bloquea la Fase 6 | Sidecar aislado tras una interfaz IPC estrecha; se puede cambiar a PyInstaller, `python -m` o incluso reescribir en Rust sin tocar la UI |
| R3 | **Falsos positivos de los analizadores** (regex sobre SQL) | Ruido en el grafo, pérdida de confianza del usuario | Bandas de confianza obligatorias, estado `inferred` visible en la UI, evidencia siempre citada |
| R4 | **Rendimiento con 20.000 archivos / 100.000 relaciones** | UI congelada | Análisis incremental por hash, lotes, escritura parcial, virtualización de listas, grafo con carga bajo demanda |
| R5 | **Deduplicación agresiva** fusiona entidades homónimas de esquemas distintos | Conocimiento corrupto y difícil de revertir | `identity_key` conservadora: ante ambigüedad, **no** se fusiona (D6) |
| R6 | **Corrupción de SQLite** por escrituras concurrentes | Pérdida de conocimiento | Un solo proceso escritor (D3), WAL, transacción por archivo |
| R7 | El shell Tauri **no compila en Linux sin `webkit2gtk`** | El desarrollador en contenedor no puede ver la UI nativa | El frontend arranca en navegador con un adaptador simulado (`src/api/mock.ts`); el motor y `hana-fs` se prueban sin Tauri |
| R8 | Symlinks y rutas UNC en Windows permitirían escapar del proyecto | Fuga de datos, lectura fuera del alcance | Canonicalización + verificación de prefijo en cada archivo, symlinks no seguidos por defecto |
| R9 | Un analizador que lanza excepción aborta el análisis completo | El usuario pierde todo el trabajo | Aislamiento por archivo y por analizador; los fallos se registran en `analysis_errors` y el análisis continúa |
| R10 | Archivos binarios o gigantes consumen memoria | Caída del proceso | Límite de tamaño, detección de binarios por bytes nulos, hashing por bloques |

---

## 6. Criterio de "terminado" de la Etapa 1

> Se conserva tal cual porque los puntos 4, 5 y 6 siguen siendo la comprobación
> que de verdad demuestra que el análisis incremental está sano, y se ejecutan
> en cada suite. El punto 3 usa `open-project`, que hoy se llama `open`.

Se considera cerrada cuando, en una máquina sin internet:

1. `pytest engine/tests` pasa en verde.
2. `cargo test -p hana-fs` pasa en verde.
3. `python -m hana_engine.cli open-project <carpeta>` crea el proyecto, lo
   escanea, hashea y persiste el inventario.
4. Reejecutarlo sin cambios reporta **0 nuevos, 0 modificados**.
5. Tocar un archivo y reejecutar reporta exactamente **1 modificado**.
6. Borrar un archivo y reejecutar lo marca eliminado sin perder su historial.
7. La pantalla de inicio muestra proyectos recientes, estado del motor y
   contadores reales.

Todos estos puntos están cubiertos por pruebas automáticas salvo el 7, que se
verifica manualmente.
