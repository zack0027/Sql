# Contrato de escaneo

El recorrido de directorios existe dos veces: en Rust
(`crates/hana-fs/src/scanner.rs`) para la aplicación de escritorio, y en Python
(`engine/hana_engine/indexing/scanner.py`) para la CLI y las pruebas.

Este documento es la fuente de verdad de lo que ambos deben cumplir. **Cualquier
cambio de comportamiento se escribe aquí primero.**

## Invariantes

| # | Invariante | Prueba (Rust) | Prueba (Python) |
|---|---|---|---|
| I1 | Las rutas relativas usan `/`, nunca `\` | `relative_paths_use_forward_slashes` | `test_relative_paths_use_forward_slashes` |
| I2 | El hash es SHA-256 en hexadecimal minúscula de los bytes íntegros | `matches_a_known_sha256_vector` | `test_hash_file_returns_digest_and_size` |
| I3 | Contenido idéntico produce hash idéntico | `identical_content_hashes_identically` | `test_identical_content_hashes_identically` |
| I4 | Los directorios ignorados por omisión son los doce de la especificación | `default_ignore_list_matches_the_specification` | `test_default_ignore_list_is_applied` |
| I5 | La lista de ignorados es configurable | `the_ignore_list_is_configurable` | `test_ignore_list_is_configurable` |
| I6 | Un archivo mayor que el límite se inventaría con `too_large` y sin hash | `oversized_files_are_inventoried_but_not_hashed` | `test_oversized_files_are_inventoried_but_not_hashed` |
| I7 | Un directorio más profundo que el límite se omite con `too_deep` | `the_depth_limit_is_enforced` | `test_depth_limit_is_enforced` |
| I8 | Los binarios **sí** se hashean pero se marcan `binary` | `binary_files_are_hashed_but_flagged` | `test_binary_files_are_hashed_but_flagged` |
| I9 | Los enlaces simbólicos no se siguen por omisión | `symlinks_are_not_followed_by_default` | `test_symlinks_are_not_followed_by_default` |
| I10 | Un enlace que escapa se rechaza aunque se permita seguirlos | `escaping_symlinks_are_refused_even_when_following_is_enabled` | `test_symlinks_that_escape_are_refused_even_when_following_is_enabled` |
| I11 | Un directorio ilegible se registra como error sin abortar el escaneo | (cubierto por `report.errors`) | `test_unreadable_directory_is_reported_without_aborting` |
| I12 | La cancelación detiene el recorrido y lo marca `cancelled` | `cancellation_stops_the_walk` | `test_progress_and_cancellation` |
| I13 | Una raíz inexistente es un error, nunca un pánico | `a_missing_root_is_an_error_not_a_panic` | `test_missing_root_is_rejected` |
| I15 | Un límite de tamaño o de profundidad menor o igual que cero se rechaza | (la política llega ya validada desde el motor) | `test_a_zero_size_limit_is_rejected`, `test_a_zero_depth_is_rejected` |

I15 apareció con la pantalla de configuración de la Etapa 5. Hasta entonces la
política solo la construía el código; ahora la escribe una persona. Un límite de
cero no escanearía nada, y el resultado sería indistinguible de un proyecto
vacío — una respuesta equivocada es peor que un rechazo.

## Reparto de responsabilidades

| Responsabilidad | Rust | Python |
|---|---|---|
| Recorrer directorios | sí | sí |
| Aplicar ignorados y límites | sí | sí |
| Calcular SHA-256 | sí | sí |
| Contención de rutas | sí | sí |
| **Clasificar el tipo de archivo** | **no** | **sí** |

I14: **Rust no clasifica tipos de archivo.** El registro serializado no incluye
`detected_type`; el motor lo deriva de la ruta al ingerir el inventario
(`AnalysisPipeline._typed`). La tabla de extensiones existe una sola vez, en
`engine/hana_engine/indexing/file_types.py`.

Prueba: `records_serialise_to_the_shape_the_engine_parses`.

## Formato del registro

```json
{
  "relative_path": "sql/guardar_inspeccion.sql",
  "absolute_path": "C:\\proyectos\\inspeccion\\sql\\guardar_inspeccion.sql",
  "extension": ".sql",
  "size_bytes": 1284,
  "content_hash": "9f2c…",
  "modified_at": "2026-07-24T21:15:03.482911Z",
  "skip_reason": null
}
```

* `content_hash` es `null` **si y solo si** el archivo no se leyó.
* `modified_at` es ISO-8601 UTC terminado en `Z`.
* `skip_reason` pertenece al vocabulario `SkipReason` en snake_case.
* Un registro puede tener `content_hash` **y** `skip_reason: "binary"` a la vez:
  el binario se hashea para detectar cambios, pero nunca se lee como texto.

## Al cambiar el comportamiento

1. Actualiza este documento.
2. Actualiza `ScanPolicy` en ambos lenguajes.
3. Añade la prueba en ambos lados, con nombres espejo.
4. Ejecuta las dos suites.
