# Protocolo IPC

El host de Tauri y el motor Python se comunican con **JSON-Lines** por
stdin/stdout: un objeto JSON por línea, codificado en UTF-8, sin saltos de línea
internos.

No hay sockets, ni puertos, ni HTTP. Es lo que permite empaquetar el motor sin
autenticación y sin abrir nada a la red.

## Marcos

### Petición → motor

```json
{"id": "7", "method": "project.open", "params": {"path": "C:\\proyectos\\insp"}}
```

`id` es opaco para el motor y se devuelve tal cual. `params` puede omitirse.

### Respuesta correcta

```json
{"id": "7", "ok": true, "result": {"id": "01KYB…", "name": "insp"}}
```

### Respuesta con error

```json
{"id": "7", "ok": false, "error": {"code": "invalid_path", "message": "…"}}
```

Códigos: `invalid_json`, `invalid_request`, `unknown_method`, `missing_param`,
`invalid_path`, `not_found`, `internal_error`. Los `internal_error` incluyen un
campo `traceback` recortado.

### Evento (sin `id`)

```json
{"event": "progress", "data": {"project_id": "…", "phase": "analyzing", "current": 12, "total": 40, "message": "sql/x.sql"}}
```

Eventos actuales: `ready` (al arrancar), `progress`, `analysis.finished`.

## Métodos

| Método | Parámetros | Devuelve |
|---|---|---|
| `engine.ping` | — | `{pong, protocol}` |
| `engine.status` | — | `EngineStatus` |
| `project.open` | `path`, `name?` | `Project` |
| `project.list` | `limit?` | `Project[]` |
| `project.get` | `project_id` | `Project` |
| `project.stats` | `project_id` | `ProjectStats` |
| `project.files` | `project_id` | `FileTreeItem[]` |
| `project.delete` | `project_id` | `{deleted: true}` |
| `project.scan_policy.get` | `project_id` | `ScanPolicy` |
| `project.scan_policy.set` | `project_id`, `policy` | `ScanPolicy` |
| `analysis.run` | `project_id`, `scanned_files?`, `trigger?` | `AnalysisRun` |
| `analysis.cancel` | `project_id?` | `{cancelled: n}` |
| `analysis.history` | `project_id`, `limit?` | `AnalysisRun[]` |
| `analysis.latest` | `project_id` | `AnalysisRun \| null` |
| `model.status` | `provider?` | `{id, label, available, models}` |

`analysis.run` acepta `scanned_files`: el inventario que produjo el escáner nativo.
Cuando se omite, el motor recorre la carpeta él mismo — así funciona la CLI.

## Modelo de hilos

```
stdin ──► hilo lector ──┬─► analysis.cancel   (en línea: solo levanta una bandera)
                        └─► cola ──► hilo trabajador ──► SQLite
                                                   └──► stdout (con cerrojo)
```

Toda llamada que toca la base se encola a **un** hilo trabajador, porque una
conexión SQLite pertenece al hilo que la creó. `analysis.cancel` se atiende en el
hilo lector para que cancelar siga funcionando mientras un análisis largo ocupa al
trabajador.

`connect()` usa `check_same_thread=False` deliberadamente: CPython reporta
`sqlite3.threadsafety == 3` (SQLite compilado en modo serializado), así que la
única barrera era la comprobación de afinidad de hilo de Python. Lo que garantiza
la seguridad es la cola, no la bandera.

## Arranque del motor

`sidecar.rs` resuelve el ejecutable en este orden:

1. `HANA_ENGINE_CMD` — sobrescritura explícita (pruebas de integración).
2. Un binario `hana-engine` junto al ejecutable — la aplicación empaquetada.
3. `python -m hana_engine.ipc.server` — el árbol de desarrollo.

Siempre con `PYTHONUNBUFFERED=1`; sin eso las respuestas se quedan en el búfer del
hijo. En Windows se añade `CREATE_NO_WINDOW` para que no aparezca una consola.

## Errores y fin del proceso

* `stderr` del motor no es protocolo: se reenvía al log del host con el prefijo
  `[engine]`. Es lo que hace localizable un traceback de Python.
* Si el hijo muere, el hilo lector desbloquea a todos los que esperaban con
  `"el motor se detuvo"`, en vez de dejar la interfaz colgada.
* Al destruirse la ventana, el host termina el proceso hijo: un motor huérfano
  seguiría reteniendo la base de conocimiento.

## Probarlo a mano

```bash
cd engine
printf '%s\n' \
  '{"id":"1","method":"engine.ping"}' \
  '{"id":"2","method":"project.open","params":{"path":"../fixtures"}}' \
| python -m hana_engine.ipc.server /tmp/hana.db
```
