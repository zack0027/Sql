# Seguridad — HANA Knowledge Engine

HANA lee código fuente ajeno: scripts de producción, exportaciones de Oracle,
reportes, configuraciones. Ese material es sensible y a menudo no es de fiar. El
modelo de seguridad parte de esa premisa.

## 1. Promesas

1. **Nada sale del equipo.** Sin API externas, sin telemetría, sin actualizaciones
   automáticas, sin sockets de red. La aplicación funciona con el adaptador de red
   desconectado.
2. **Nada se ejecuta.** El análisis es estático. HANA no ejecuta SQL, PL/SQL,
   comandos MOCA, JavaScript, Python ni expresiones de JRXML.
3. **Nada se modifica.** Los archivos analizados se abren en modo lectura. No hay
   ninguna ruta de código que escriba en el proyecto del usuario.
4. **Nada fuera del proyecto.** Solo se leen las carpetas que el usuario abrió
   explícitamente mediante el diálogo del sistema operativo.

## 2. Frontera del sistema de archivos

Implementada en `crates/hana-fs/src/security.rs` y aplicada en
`apps/desktop/src-tauri/src/commands.rs`.

### Raíces permitidas

Una carpeta se vuelve legible únicamente cuando el usuario la selecciona en el
diálogo del SO. `open_project` la canonicaliza y la añade a la lista de raíces
permitidas de la sesión. Todo escaneo la vuelve a verificar:

```rust
if !state.is_allowed(&root) {
    return Err("la carpeta no está autorizada en esta sesión; ábrela de nuevo");
}
```

Un identificador de proyecto guardado **no** es autorización. Reabrir el proyecto
—lo que pasa por el diálogo del SO— es lo que vuelve a concederla.

### Contención de rutas

Cada ruta candidata se resuelve y se compara por **componentes completos**, no por
prefijo de cadena:

```rust
resolved.components().count() >= root.components().count() && resolved.starts_with(root)
```

Esto cierra el error clásico en el que `/data/proyecto-secretos` pasa por hijo de
`/data/proyecto`. Cubierto por
`rejects_a_sibling_with_a_shared_prefix` en Rust y su espejo en Python.

### Enlaces simbólicos

No se siguen por omisión. Aunque la política se active, el destino resuelto debe
seguir dentro de la raíz del proyecto; si no, el enlace se registra como
`symlink_escape` y no se abre. Un enlace es precisamente la forma en que un
escaneo se escaparía de la carpeta elegida, así que activarlo es una decisión
explícita por proyecto y aun así insuficiente para salir.

Aplica igual a los *junctions* de Windows: la canonicalización los resuelve antes
de la comprobación.

### Límites

| Límite | Valor por omisión | Motivo |
|---|---|---|
| Tamaño de archivo | 5 MiB | Un volcado de 2 GB no debe agotar la memoria |
| Profundidad de directorios | 24 | Corta jerarquías patológicas y ciclos |
| Fragmento de hashing | 1 MiB | El uso de memoria no crece con el archivo |
| Detección de binarios | 8 KiB | Un byte nulo basta para no tratarlo como texto |
| Timeout de petición IPC | 600 s | La interfaz nunca se cuelga indefinidamente |

Los archivos que exceden un límite **se inventarían igualmente**, con su
`skip_reason`. El usuario debe poder ver que una exportación de 40 MB existe y
que HANA decidió no leerla — un archivo omitido en silencio es peor que uno
señalado.

## 3. Aislamiento de los analizadores

Un `AnalysisContext` contiene el texto de un archivo y su identidad. Nada más.
Sin conexión a la base, sin red, sin capacidad de abrir otros archivos.

Consecuencias directas:

* Una expresión de JRXML es **texto que se compara**, nunca se evalúa.
* Una consulta SQL se **analiza sintácticamente**, nunca se ejecuta.
* Un pipeline MOCA se **descompone**, nunca se envía a un servidor.
* Un `.py` o un `.js` hallado en el proyecto se lee como datos, jamás se importa
  ni se ejecuta.

En el MVP **no existe conexión a Oracle**. No hay driver, no hay cadena de
conexión, no hay credenciales que filtrar.

## 4. Superficie de ataque de la aplicación

### Sin puertos de red

El motor es un proceso hijo que habla JSON-Lines por stdin/stdout. No hay
servidor HTTP, ni WebSocket, ni puerto que escanear, ni autenticación que
implementar mal.

### Capacidades de Tauri

`apps/desktop/src-tauri/capabilities/default.json` concede lo mínimo:

```json
["core:default", "core:event:allow-listen", "core:event:allow-unlisten", "dialog:allow-open"]
```

No hay capacidad de sistema de archivos, ni de shell, ni de HTTP. La webview
**no puede** leer un archivo aunque quiera: solo puede pedir al host que lo haga,
y el host aplica la frontera descrita arriba.

### Política de seguridad de contenido

```
default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
connect-src 'self' ipc: http://ipc.localhost
```

Sin orígenes remotos. Sin CDN. Sin fuentes externas. `assetProtocol` está
desactivado.

### Contenido no confiable en la interfaz

Los nombres de archivo, identificadores y fragmentos de evidencia provienen de los
proyectos del usuario y deben tratarse como datos, nunca como marcado. React
escapa el texto por omisión, y el proyecto no usa `dangerouslySetInnerHTML` en
ningún punto. Cuando la Etapa 4 incorpore Monaco, se configurará en solo lectura.

## 5. Integridad de los datos

* **Un solo proceso escritor** en SQLite. Rust nunca escribe en la base.
* **Claves foráneas activadas** (`PRAGMA foreign_keys = ON`): el borrado en
  cascada del que depende el análisis incremental es real, no aspiracional.
* **Una transacción por archivo**: o el conocimiento nuevo del archivo entra
  entero, o el archivo queda marcado como fallido. Nunca un grafo a medio
  escribir.
* **Historial append-only** en `file_versions`: se agrega, no se actualiza.
* **Evidencia obligatoria**: `CHECK (entity_id IS NOT NULL OR relationship_id IS NOT NULL)`.

## 6. Lo que HANA deliberadamente no hace

| No hace | Por qué |
|---|---|
| Ejecutar SQL, PL/SQL o MOCA | El análisis debe ser seguro sobre código de producción |
| Evaluar expresiones de JRXML | Son código; compararlas como texto basta |
| Conectarse a Oracle | Fuera del alcance del MVP; sin credenciales que perder |
| Seguir enlaces fuera del proyecto | Es la vía de escape del sandbox |
| Modificar archivos analizados | Sin aprobación explícita, jamás |
| Enviar telemetría | Nada sale del equipo |
| Inventar relaciones sin marcarlas | Una inferencia siempre se registra como `inferred` |

## 7. Verificación

```bash
cargo test --manifest-path crates/hana-fs/Cargo.toml   # frontera de rutas
python -m pytest engine/tests/test_scanner.py            # espejo en Python
```

Pruebas que cubren específicamente la seguridad:

* `rejects_a_sibling_with_a_shared_prefix` / `test_sibling_prefixes_are_not_inside`
* `rejects_dotdot_escapes` / `test_dotdot_cannot_escape`
* `rejects_a_symlink_pointing_outside` / `test_symlinks_are_not_followed_by_default`
* `escaping_symlinks_are_refused_even_when_following_is_enabled`
* `test_oversized_files_are_inventoried_but_not_hashed`
* `test_depth_limit_is_enforced`
* `test_unreadable_directory_is_reported_without_aborting`
* `test_a_zero_size_limit_is_rejected` / `test_a_zero_depth_is_rejected` — la
  política de escaneo es editable desde la interfaz desde la Etapa 5, así que
  ahora puede llegar con valores imposibles

### Aislamiento de red, comprobado

`engine/tests/test_offline.py` no se limita a afirmarlo:

```bash
python -m pytest engine/tests/test_offline.py
```

Reemplaza `socket.socket`, `socket.create_connection`, `socket.getaddrinfo`,
`socket.gethostbyname` y `urllib.request.urlopen` por versiones que fallan, y
sobre eso ejecuta un análisis completo —escaneo, hashing, los seis analizadores,
persistencia— y las trece consultas. Cualquier intento de salir a la red rompe la
prueba y dice quién lo intentó.

Incluye además un JRXML que declara un DTD externo. Un parser XML que resuelva
entidades saldría a buscarlo: es la forma clásica de que una herramienta «local»
empiece a hacer peticiones, y con un archivo hostil, de que empiece a leer
archivos del sistema.

`TestNoListeningPorts` comprueba que el código del sidecar no menciona sockets,
`bind`, `listen`, HTTP ni `localhost`. Un puerto significaría que cualquier cosa
en la máquina puede hablar con el motor que sostiene el código del usuario.

Comprobación manual complementaria: desconectar el adaptador de red y ejecutar el
escenario completo de la sección «Verificar que funciona» del README. No debe
cambiar nada.

## 8. Reporte de vulnerabilidades

HANA es una aplicación local sin servicio asociado. Los problemas de seguridad
se reportan como *issues* en el repositorio. Si el reporte incluye una ruta que
permite leer fuera del proyecto o ejecutar contenido analizado, márcalo como
**crítico**: son las dos invariantes de las que depende todo lo demás.
