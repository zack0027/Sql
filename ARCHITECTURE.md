# Arquitectura — HANA Knowledge Engine

## 1. Idea central

HANA no es un chatbot con acceso a archivos. Es un **motor de conocimiento**:
lee proyectos técnicos, los convierte en entidades y relaciones con procedencia
verificable, y guarda ese grafo localmente.

Un modelo de lenguaje es opcional y sustituible. El grafo no lo es.

```
┌──────────────────────────────────────────────────────────────┐
│  Webview (React + TypeScript)                                │
│  Vistas, estado (Zustand), React Flow, Monaco                │
│  · No contiene reglas de dominio                             │
└───────────────────────────┬──────────────────────────────────┘
                            │ comandos Tauri (IPC interno)
┌───────────────────────────▼──────────────────────────────────┐
│  Host nativo (Rust + Tauri 2)                                │
│  · Frontera de seguridad: raíces permitidas                  │
│  · Escaneo y hashing (crates/hana-fs)                      │
│  · Ciclo de vida del proceso motor                           │
│  · No escribe en la base de conocimiento                     │
└───────────────────────────┬──────────────────────────────────┘
                            │ JSON-Lines por stdin/stdout
┌───────────────────────────▼──────────────────────────────────┐
│  Motor (Python)                                              │
│  dominio · analizadores · persistencia · pipeline            │
│  · Único escritor de SQLite                                  │
│  · No importa nada de Tauri                                  │
└───────────────────────────┬──────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │  SQLite + FTS5 │
                    └────────────────┘
```

## 2. Capas y sus fronteras

| Capa | Ubicación | Puede depender de | Nunca depende de |
|---|---|---|---|
| Dominio | `engine/hana_engine/domain/` | stdlib | persistencia, Tauri, UI |
| Persistencia | `engine/hana_engine/persistence/` | dominio, sqlite3 | analizadores, UI |
| Indexación | `engine/hana_engine/indexing/` | dominio | persistencia, UI |
| Analizadores | `engine/hana_engine/analyzers/` | dominio | persistencia, red, disco |
| Pipeline | `engine/hana_engine/pipeline/` | todas las anteriores | Tauri, UI |
| Host nativo | `apps/desktop/src-tauri/` | `hana-fs`, Tauri | el motor como biblioteca |
| Seguridad FS | `crates/hana-fs/` | stdlib, sha2, serde | Tauri, el motor |
| UI | `apps/desktop/src/` | `@hana/shared-types` | SQLite, analizadores |

La regla que las hace verificables: **`pytest engine/tests` corre sin Node y sin
Rust; `cargo test -p hana-fs` corre sin Tauri y sin Python; `vitest` corre sin
ninguno de los dos.**

## 3. Modelo de dominio

### 3.1 Entidad

Una cosa identificable hallada en un archivo. Su tipo pertenece a un vocabulario
cerrado (`EntityType`) compartido con TypeScript.

Cada entidad guarda: id (ULID), tipo, nombre tal como se encontró, nombre
normalizado, `identity_key`, nombre calificado, descripción, archivo de origen,
línea inicial y final, confianza, estado de verificación, metadatos y fechas.

### 3.2 Relación

Una afirmación dirigida entre dos entidades. Guarda además el archivo que la
prueba, las líneas exactas, el fragmento de evidencia, la confianza, el estado y
el analizador responsable.

**La relación pertenece al archivo que la prueba.** Reanalizar ese archivo borra
sus relaciones antes de reconstruirlas. Es lo que garantiza que una arista cuya
línea de respaldo desapareció, desaparezca con ella.

### 3.3 Evidencia

El recibo. Archivo, líneas, fragmento, analizador, confianza, estado, y
`original_name`: la grafía exacta que apareció en ese archivo. Gracias a esa
última columna, una entidad deduplicada como `UC_INSP_ENT` puede seguir mostrando
`uc_insp_ent` allí donde el código lo escribió así.

Nada entra al grafo sin evidencia. Una entidad o relación sin procedencia es un
error de programación, no un caso límite.

## 4. Deduplicación — `identity_key`

La política vive en `domain/naming.py`, no en el esquema. La base solo impone
`UNIQUE(project_id, identity_key)`.

```
identity_key = tipo | esquema | contenedor | nombre_normalizado
```

* `uc_insp_ent`, `UC_INSP_ENT` y `"UC_INSP_ENT"` → la misma clave.
* `getRows` en JavaScript **no** se pliega a mayúsculas: solo los identificadores
  Oracle, APEX y MOCA son insensibles a mayúsculas.
* Un componente vacío significa *desconocido*, y **desconocido nunca coincide con
  conocido**: `UC_INSP_ENT` sin esquema no se fusiona con `WMS.UC_INSP_ENT`. Ante
  ambigüedad, HANA prefiere dos entidades separadas a una fusión inventada.

Al fusionar, la primera grafía observada se conserva y **la confianza solo sube**:
un avistamiento débil no degrada un hecho probado por un `INSERT INTO`.

### Identidad estable

`identity_key` es estable entre ejecuciones, y los ids también deben serlo. Por
eso el pipeline persiste los resultados nuevos **antes** de recolectar huérfanos:
recolectar primero borraría cada entidad que el archivo sigue definiendo y la
reinsertaría con un ULID nuevo, rompiendo cualquier referencia guardada.
Cubierto por `test_entity_ids_survive_a_reanalysis`.

## 5. Confianza

| Rango | Significado | Ejemplo |
|---|---|---|
| `1.00` | Confirmado por sintaxis directa | `INSERT INTO UC_INSP_ENT` |
| `0.80–0.99` | Inferencia fuerte | `P117_NUMCTL` pertenece a la página 117 |
| `0.50–0.79` | Inferencia probable | un alias resuelto por heurística |
| `0.00–0.49` | Baja confianza | un nombre mencionado en un comentario |

Invariante impuesta en el constructor de los borradores: **nada puede marcarse
`confirmed` con confianza menor que 1.0.** Intentarlo lanza `ValueError`.

## 6. Analizadores — arquitectura de plugins

```python
class Analyzer(ABC):
    name: str
    supported_extensions: Sequence[str]
    priority: int = 0

    def can_analyze(self, file_path: str, content: str) -> bool: ...

    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AnalysisResult: ...
```

Un analizador recibe un `AnalysisContext` deliberadamente estrecho: el texto de
**un** archivo y su identidad. Sin handle de base de datos, sin red, sin acceso a
otros archivos. Eso es lo que hace seguro ejecutarlos sobre contenido de
proyectos ajenos.

Devuelven *borradores*, no filas: `EntityDraft` y `RelationshipDraft`. La
`ref` de un borrador **es** su `identity_key`, así que un analizador puede
referirse a una entidad sin conocer ningún estado de la base. El pipeline los
resuelve, deduplica y asigna ids.

Aislamiento de fallos: una excepción se captura por archivo **y por analizador**,
se registra en `analysis_errors`, y el análisis continúa. Un `.jrxml` malformado
no puede vaciar el grafo.

## 7. Flujo de análisis incremental

```
 1. El usuario selecciona una carpeta   (diálogo del SO)
 2. Rust canonicaliza la ruta           → raíz permitida
 3. Rust recorre el árbol               (hana-fs, ignora, limita, hashea)
 4. Rust envía el inventario            (JSON-Lines)
 5. El motor deriva el tipo de archivo  (una sola tabla, en Python)
 6. El motor compara contra SQLite      → nuevo | modificado | igual | borrado
 7. Solo nuevos y modificados se leen
 8. El registro olvida lo que el archivo probaba
 9. Los analizadores compatibles corren
10. Se persisten entidades, relaciones y evidencias
11. Se recolectan huérfanos
12. Se registra la ejecución; los errores no la detienen
```

La detección es **por hash de contenido, nunca por mtime**. Copiar un proyecto o
volver a clonarlo cambia todas las marcas de tiempo sin cambiar nada; reanalizar
20.000 archivos por eso haría inútil el análisis incremental.

## 8. Persistencia

SQLite, un solo archivo, un solo proceso escritor, modo WAL.

Tablas: `projects`, `files`, `file_versions`, `entities`, `relationships`,
`evidence`, `analysis_runs`, `analysis_errors`, `settings`, `tags`,
`entity_tags`, más los índices FTS5 `entities_fts`, `files_fts` y `evidence_fts`
(contenido externo + triggers).

Migraciones versionadas y numeradas en
`engine/hana_engine/persistence/migrations/`, aplicadas en orden y registradas
en `schema_migrations`. Son idempotentes.

### Nota sobre el tokenizador

`unicode61` trata `_` como separador, de modo que `UC_INSP_ENT` se indexa como
`uc`, `insp`, `ent`. Buscar el identificador completo lo encuentra como frase, y
buscar `INSP` a secas también lo encuentra. Los índices `prefix='2 3 4'` hacen
barata la búsqueda mientras se escribe.

## 9. IPC

JSON-Lines sobre stdin/stdout. Ni sockets, ni puertos, ni HTTP.

```
Petición  {"id":"1","method":"project.open","params":{"path":"..."}}
Respuesta {"id":"1","ok":true,"result":{...}}
Error     {"id":"1","ok":false,"error":{"code":"...","message":"..."}}
Evento    {"event":"progress","data":{...}}
```

**Hilos.** El hilo lector solo analiza líneas; todo lo que toca SQLite se encola
a un único hilo trabajador. `analysis.cancel` es la excepción: solo levanta una
bandera, así que se atiende en línea y sigue respondiendo mientras un análisis
largo ocupa al trabajador.

Protocolo completo: [`docs/IPC_PROTOCOL.md`](docs/IPC_PROTOCOL.md).

## 10. El reparto Rust / Python

El escaneo existe en dos implementaciones, y eso es intencional:

* **Rust (`crates/hana-fs`)** es la ruta de producción de la aplicación de
  escritorio. Es la frontera de seguridad, es rápida y es cancelable sin bloquear
  la interfaz.
* **Python (`indexing/scanner.py`)** es la ruta *headless*: la CLI y la suite de
  pruebas, para que el motor se ejercite de punta a punta sin compilar Rust.

Para que no se separen:
* La política (`ScanPolicy`) está escrita en ambos lados con los mismos campos.
* Las pruebas son espejo: mismos casos, mismos nombres.
* **El tipado de archivos vive solo en Python.** Rust no clasifica; el motor
  deriva `detected_type` de la ruta. Así la tabla de extensiones existe una vez.

Invariantes compartidas: [`docs/SCAN_CONTRACT.md`](docs/SCAN_CONTRACT.md).

## 11. El modelo local

```typescript
interface LocalModelProvider {
  isAvailable(): Promise<boolean>;
  listModels(): Promise<ModelInfo[]>;
  generate(request: ModelRequest): Promise<ModelResponse>;
}
```

La implementación por defecto es `DisabledModelProvider`, que devuelve una
respuesta bien formada con `available: false` en lugar de lanzar una excepción —
así ningún llamador necesita un camino especial para "no hay modelo".

Más adelante se podrán conectar llama.cpp, Ollama o un GGUF empaquetado. Ninguna
funcionalidad del camino crítico dependerá de ello: **el grafo lo construyen los
analizadores, no un modelo.**

## 12. Rendimiento

Objetivos: 20.000 archivos, decenas de miles de entidades, cientos de miles de
relaciones.

| Técnica | Dónde |
|---|---|
| Análisis incremental por hash | `pipeline/changes.py` |
| Lotes de 250 archivos por transacción | `pipeline/orchestrator.py` |
| Hashing por bloques de 1 MiB | ambos escáneres |
| Índices por proyecto, tipo, nombre y hash | migración 001 |
| Cancelación consultada entre archivos | escáner y pipeline |
| Progreso emitido sin bloquear la UI | eventos Tauri |
| Persistencia parcial | commit por lote y por archivo |

Pendiente para etapas siguientes: virtualización de listas y carga progresiva del
grafo.

## 13. Decisiones registradas

| # | Decisión | Razón |
|---|---|---|
| D1 | Rust escanea, Python persiste | Rendimiento y seguridad en Rust; el conocimiento en un solo lenguaje |
| D2 | `hana-fs` sin dependencia de Tauri | Auditable y testeable donde Tauri no compila |
| D3 | Un solo escritor de SQLite | Evita corrupción y bloqueos cruzados |
| D4 | JSON-Lines en vez de HTTP | No abre puertos; empaquetado trivial |
| D5 | ULID en vez de UUIDv4 | Ordenable por tiempo; los índices no se fragmentan |
| D6 | `identity_key` explícita | La deduplicación es código versionado y probado |
| D7 | FTS5 con contenido externo | No duplica el texto; se sincroniza por triggers |
| D8 | Persistir antes de recolectar huérfanos | Mantiene estables los ids de entidad |
