# Roadmap — HANA Knowledge Engine

Estado: **las cinco etapas están completas.** El producto analiza, explica y se
instala. Lo que queda abierto está al final, y lo que se decidió no hacer
también.

---

## Etapa 1 — Fundación, proyectos y archivos ✅

Fases 1 y 2 de la especificación.

- [x] Monorepo con workspaces (pnpm, dos workspaces de Cargo, paquete Python)
- [x] Modelo de dominio: entidades, relaciones, evidencia, confianza, ULID
- [x] Esquema SQLite con migraciones versionadas, índices y FTS5
- [x] Repositorios con deduplicación por `identity_key`
- [x] Escáner seguro en Rust (`crates/hana-fs`) con SHA-256 y cancelación
- [x] Escáner headless en Python para la CLI y las pruebas
- [x] Detección incremental: nuevo / modificado / sin cambios / eliminado
- [x] Historial de versiones de archivo y de ejecuciones
- [x] Interfaz de plugins de analizadores con aislamiento de fallos
- [x] `LocalModelProvider` desacoplado, deshabilitado por omisión
- [x] Sidecar JSON-Lines y CLI headless
- [x] Host Tauri con comandos, eventos de progreso y raíces permitidas
- [x] Pantalla de inicio funcional

---

## Etapa 2 — Motor de análisis ✅

Fase 3. La etapa que convierte el inventario en conocimiento.

### Analizador SQL / PL/SQL
- [x] `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- [x] Tablas, vistas, columnas calificadas por alias, resolución de alias
- [x] Subconsultas y CTE
- [x] Procedimientos, funciones, packages; definición frente a llamada
- [x] Distinguir lectura de tabla, escritura de tabla y uso de columna
- [x] Variables bind `:P117_NUMCTL` y variables MOCA `@ordnum`
- [x] Condiciones `JOIN` entre tablas, que alimentan el diagrama ER

### Analizador Oracle APEX
- [x] Referencias `:P117_*`, `:APP_USER`, `:APP_PAGE_ID`, `:APP_ID`
- [x] Inferencia de página desde el número del item (confianza 0.90, `inferred`)
- [x] `APEX_ITEM_MAPS_TO_COLUMN` a partir de `INSERT`/`UPDATE`, con evidencia por
      item — cada mapeo cita su propia línea, no la del `values (`

### Analizador MOCA
- [x] Pipelines separados por `|`
- [x] Variables `@variable`, bloques entre corchetes
- [x] `publish data` y `catch(@?)`
- [x] Dependencias entre variables publicadas y consumidas

### Analizador JRXML
- [x] Parser XML real (nunca expresiones regulares para la estructura)
- [x] Nombre, fields, parameters, variables, queryString, subreports, imágenes
- [x] Tablas y columnas usadas dentro de las consultas, y sus `JOIN`
- [x] Bandas en orden de impresión, con geometría y elementos
- [x] **Campos usados pero no declarados** (advertencia)
- [x] **Parámetros declarados pero no usados** (advertencia), excluyendo los
      parámetros de plataforma `MOCA_REPORT_*`
- [x] Imágenes con ruta relativa → `REPORT_REFERENCES_IMAGE` a un `File`

### Analizadores JSON y de código
- [x] JSON: propiedades, objetos, arrays, estructuras repetidas
- [x] JavaScript y Python: funciones, clases, imports, llamadas, endpoints
- [x] Referencias a items APEX, tablas Oracle y reportes desde el código

### Infraestructura
- [x] Fixtures y pruebas por analizador
- [x] Versión por analizador y huella del conjunto: un archivo intacto se relee
      cuando quien lo leyó ya no es quien lo leería hoy
- [~] Tree-sitter — **descartado por ahora**. El registro npm no es alcanzable
      desde esta red (ver `docs/OFFLINE_DEPENDENCIES.md`) y los analizadores
      escritos a mano cubren los dialectos que importan aquí, incluido MOCA, que
      no tiene gramática publicada.

---

## Etapa 3 — Grafo y búsqueda ✅

Fase 4.

- [x] Consultas de grafo con expansión por niveles
- [x] Búsqueda global FTS5 sobre entidades, rutas, contenido, evidencias
- [x] Carga progresiva: nodo seleccionado → vecinos → bajo demanda
- [x] Zoom, desplazamiento, centrar nodo, filtrar relaciones
- [x] Panel de detalles: relaciones entrantes, salientes, evidencias
- [x] Colores por tipo de entidad
- [~] React Flow — **sustituido por SVG escrito a mano**. La biblioteca no es
      instalable desde esta red, y dibujar el grafo directamente da control sobre
      lo que más importa aquí: distinguir en pantalla un hecho confirmado de una
      inferencia.

---

## Etapa 4 — Experiencia de usuario ✅

Fase 5.

- [x] Explorador de tres paneles redimensionables
- [x] Árbol de archivos virtualizado, filtro por ruta, estado de análisis
- [x] Monaco Editor en solo lectura: abrir archivo, saltar a línea, resaltar
- [x] Barra de progreso y cancelación desde la interfaz
- [x] Pantalla de configuración: carpetas y archivos ignorados, tamaño máximo,
      profundidad, enlaces simbólicos
- [x] Historial de análisis y vista de «qué cambió»
- [x] Diagrama ER a partir de las condiciones `JOIN`
- [x] Previsualización de reportes Jasper banda por banda

### Las diez consultas deterministas (sin modelo de lenguaje)
- [x] ¿Dónde se utiliza esta entidad?
- [x] ¿Qué depende de esta entidad?
- [x] ¿Qué tablas lee esta consulta?
- [x] ¿Qué tablas modifica este proceso?
- [x] ¿Qué items APEX aparecen en este archivo?
- [x] ¿Qué reportes utilizan esta tabla?
- [x] ¿Qué imágenes utiliza este reporte?
- [x] ¿Qué cambió desde el análisis anterior?
- [x] ¿Qué archivos presentan errores de análisis?
- [x] ¿Qué entidades tienen baja confianza?

---

## Etapa 5 — Empaquetado ✅ (salvo la firma)

Fase 6. Era **el riesgo técnico más alto del proyecto** (R2) y se adelantó
parcialmente para poder distribuir versiones de prueba desde la Etapa 1.

- [x] Congelar el motor con PyInstaller como binario `externalBin`
- [x] La aplicación empaquetada arranca el motor congelado, aplica las
      migraciones y crea la base — sin Python en el proceso
- [x] Flujo de trabajo de GitHub Actions que compila el instalador de Windows
- [x] Instalador `.msi` y `.exe`
- [x] **Instalador verificado a mano sobre un Windows real**, con proyectos
      reales del usuario (1239 archivos, base de 208 MB)
- [x] **Aislamiento de red comprobado automáticamente**: `test_offline.py`
      ejecuta un análisis completo y las trece consultas con el módulo `socket`
      bloqueado, e incluye un JRXML con un DTD externo para probar que el parser
      XML no sale a buscarlo
- [x] Documentación de instalación para usuarios no técnicos
      (`docs/INSTALL_WINDOWS.md`)
- [x] Cadena de compilación firmable: `scripts/build_release.py` firma los
      binarios antes de empaquetarlos y deja que Tauri firme la aplicación y el
      instalador, gobernado por variables de entorno
- [ ] **Firmar de verdad.** Requiere comprar un certificado de firma
      (200–600 USD/año) y, desde 2023, guardarlo en un HSM o token físico. Es
      una decisión de negocio, no una tarea de programación — el mecanismo ya
      está listo y documentado en `docs/FIRMA_DE_CODIGO.md`.

---

## Abierto

Nada de esto entra hasta que haga falta de verdad.

- Modelo local (llama.cpp, Ollama, GGUF empaquetado) para explicar el grafo
- Embeddings locales y búsqueda semántica
- Base de grafos dedicada, **solo si SQLite deja de rendir de verdad**
- Diferencias entre versiones de un archivo con impacto en el grafo
- Entidades `Error` y `Solution` a partir de logs
- Exportar el grafo (GraphML, JSON)
- Anotaciones manuales con estado `manual`
- Multiplataforma: macOS y Linux
- Actualizaciones automáticas — hoy se reinstala a mano, que para una
  herramienta interna es suficiente y no abre un canal de red

## Principios que no cambian

1. El motor de conocimiento es el producto; el modelo es un accesorio.
2. Nada entra al grafo sin procedencia.
3. Una inferencia siempre se declara como inferencia.
4. Nada sale del equipo.
5. Nada se ejecuta.
