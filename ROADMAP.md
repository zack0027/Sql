# Roadmap — JARVIS Knowledge Engine

Estado: **Etapa 1 completa.** Base ejecutable, motor incremental, persistencia,
seguridad del sistema de archivos y pantalla de inicio.

---

## Etapa 1 — Fundación, proyectos y archivos ✅

Fases 1 y 2 de la especificación.

- [x] Monorepo con workspaces (pnpm, dos workspaces de Cargo, paquete Python)
- [x] Modelo de dominio: entidades, relaciones, evidencia, confianza, ULID
- [x] Esquema SQLite con migraciones versionadas, índices y FTS5
- [x] Repositorios con deduplicación por `identity_key`
- [x] Escáner seguro en Rust (`crates/jarvis-fs`) con SHA-256 y cancelación
- [x] Escáner headless en Python para la CLI y las pruebas
- [x] Detección incremental: nuevo / modificado / sin cambios / eliminado
- [x] Historial de versiones de archivo y de ejecuciones
- [x] Interfaz de plugins de analizadores con aislamiento de fallos
- [x] `LocalModelProvider` desacoplado, deshabilitado por omisión
- [x] Sidecar JSON-Lines y CLI headless
- [x] Host Tauri con comandos, eventos de progreso y raíces permitidas
- [x] Pantalla de inicio funcional
- [x] 207 pruebas automáticas (155 Python, 30 Rust, 22 TypeScript)

---

## Etapa 2 — Motor de análisis

Fase 3. **Es la etapa que convierte el inventario en conocimiento.**

### Analizador SQL / PL/SQL
- [ ] `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- [ ] Tablas, vistas, columnas calificadas por alias, resolución de alias
- [ ] Subconsultas y CTE
- [ ] Procedimientos, funciones, packages; definición frente a llamada
- [ ] Distinguir lectura de tabla, escritura de tabla y uso de columna
- [ ] Variables bind `:P117_NUMCTL` y variables MOCA `@ordnum`

### Analizador Oracle APEX
- [ ] Referencias `:P117_*`, `:APP_USER`, `:APP_PAGE_ID`, `:APP_ID`
- [ ] Inferencia de página desde el número del item (confianza 0.90, `inferred`)
- [ ] `APEX_ITEM_MAPS_TO_COLUMN` a partir de `INSERT`/`UPDATE`

### Analizador MOCA
- [ ] Pipelines separados por `|`
- [ ] Variables `@variable`, bloques entre corchetes
- [ ] `publish data` y `catch(@?)`
- [ ] Dependencias entre variables publicadas y consumidas

### Analizador JRXML
- [ ] Parser XML real (nunca expresiones regulares para la estructura)
- [ ] Nombre, fields, parameters, variables, queryString, subreports, imágenes
- [ ] Tablas y columnas usadas dentro de las consultas
- [ ] **Campos usados pero no declarados** (advertencia)
- [ ] **Parámetros declarados pero no usados** (advertencia)
- [ ] Imágenes con ruta relativa → `REPORT_REFERENCES_IMAGE` a un `File`

### Analizadores JSON y de código
- [ ] JSON: propiedades, objetos, arrays, estructuras repetidas
- [ ] JavaScript y Python: funciones, clases, imports, llamadas, endpoints
- [ ] Referencias a items APEX, tablas Oracle y reportes desde el código

### Infraestructura
- [ ] Tree-sitter donde exista gramática adecuada
- [ ] Fixtures y pruebas por analizador (las de `fixtures/` ya están listas)

---

## Etapa 3 — Grafo y búsqueda

Fase 4.

- [ ] Consultas de grafo con expansión por niveles
- [ ] Búsqueda global FTS5 sobre entidades, rutas, contenido, evidencias
- [ ] React Flow con carga progresiva: nodo seleccionado → vecinos → bajo demanda
- [ ] Zoom, desplazamiento, centrar nodo, ocultar tipos, filtrar relaciones
- [ ] Panel de detalles: relaciones entrantes, salientes, evidencias, historial
- [ ] Iconos y colores por tipo de entidad, configurables

---

## Etapa 4 — Experiencia de usuario

Fase 5.

- [ ] Explorador de tres paneles redimensionables
- [ ] Árbol de archivos virtualizado, filtro por extensión, estado de análisis
- [ ] Monaco Editor en solo lectura: abrir archivo, saltar a línea, resaltar
- [ ] Barra de progreso y cancelación desde la interfaz
- [ ] Pantalla de configuración (ignorados, límites, colores)
- [ ] Historial de análisis y vista de "qué cambió"

### Las diez consultas deterministas (sin modelo de lenguaje)
- [ ] ¿Dónde se utiliza esta entidad?
- [ ] ¿Qué depende de esta entidad?
- [ ] ¿Qué tablas lee esta consulta?
- [ ] ¿Qué tablas modifica este proceso?
- [ ] ¿Qué items APEX aparecen en este archivo?
- [ ] ¿Qué reportes utilizan esta tabla?
- [ ] ¿Qué imágenes utiliza este reporte?
- [ ] ¿Qué cambió desde el análisis anterior?
- [ ] ¿Qué archivos presentan errores de análisis?
- [ ] ¿Qué entidades tienen baja confianza?

---

## Etapa 5 — Empaquetado (adelantada parcialmente)

Fase 6. Era **el riesgo técnico más alto del proyecto** (R2) y se adelantó para
poder distribuir una versión de prueba.

- [x] Congelar el motor con PyInstaller como binario `externalBin`
- [x] Verificado: la aplicación empaquetada arranca el motor congelado, aplica
      las migraciones y crea la base — sin Python en el proceso
- [x] Flujo de trabajo de GitHub Actions que compila el instalador de Windows
- [x] Instalador `.msi` y `.exe` producidos en verde sobre windows-latest, con
      las 155 pruebas del motor pasando en Windows
- [ ] Instalador verificado a mano sobre un Windows real (pendiente: nadie lo
      ha ejecutado todavía)
- [ ] Verificar funcionamiento con el adaptador de red desconectado
- [ ] Firma de código (Windows marcará el ejecutable como no firmado)
- [ ] Documentar la instalación para usuarios no técnicos

---

## Más adelante

Nada de esto entra hasta que el grafo sea útil sin ello.

- Modelo local (llama.cpp, Ollama, GGUF empaquetado) para explicar el grafo
- Embeddings locales y búsqueda semántica
- Base de grafos dedicada, **solo si SQLite deja de rendir de verdad**
- Diferencias entre versiones de un archivo con impacto en el grafo
- Entidades `Error` y `Solution` a partir de logs
- Exportar el grafo (GraphML, JSON)
- Anotaciones manuales con estado `manual`
- Multiplataforma: macOS y Linux

## Principios que no cambian

1. El motor de conocimiento es el producto; el modelo es un accesorio.
2. Nada entra al grafo sin procedencia.
3. Una inferencia siempre se declara como inferencia.
4. Nada sale del equipo.
5. Nada se ejecuta.
