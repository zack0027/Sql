# Dependencias en una red sin acceso a npm

En la red de destino, `registry.npmjs.org` **no es alcanzable**: el dominio solo
resuelve a IPv6 y esa ruta está muerta. Se comprobó con tres intentos y consulta
DNS. `crates.io`, `github.com` y `nodejs.org` sí responden, así que Rust, Node y
el propio código fuente se obtienen sin problema — el bloqueo es específico de
npm.

Esto afecta a cualquier dependencia nueva del frontend.

## Qué se hizo

Los metadatos de `registry.yarnpkg.com` sí se obtienen, pero apuntan los
tarballs de vuelta a `registry.npmjs.org`, así que pnpm falla igual al
descargarlos. Lo que sí funciona es pedir el tarball directamente a
`registry.yarnpkg.com`, que **es el CDN del propio npm bajo otro nombre de
host** — mismo publicador y mismos bytes, solo un dominio que resuelve. No es un
espejo de terceros, y por tanto no cambia en quién hay que confiar.

Los paquetes se descargan una vez a `vendor/` y se instalan desde disco:

| Paquete | Versión | Por qué |
|---|---|---|
| `monaco-editor` | 0.56.0 | El visor de código |
| `marked` | 18.0.7 | Dependencia de Monaco |
| `dompurify` | 3.4.12 | Dependencia de Monaco |
| `@types/trusted-types` | 2.0.7 | Dependencia de dompurify |

`apps/desktop/package.json` referencia Monaco con `file:`; las tres transitivas
se resuelven mediante `pnpm.overrides` en el `package.json` raíz, porque de otro
modo pnpm iría a buscarlas al registro inalcanzable.

`vendor/` **no está en el repositorio**: son 18 MB que no pertenecen al
historial. Para reconstruirlo:

```bash
python scripts/fetch_vendor.py
pnpm install
```

El script no lleva dentro la lista de lo que hay que bajar: la lee de
`pnpm-lock.yaml`, donde ya está el `sha512` de cada tarball. Así cada descarga
se verifica contra el mismo hash que pnpm comprobará después, y añadir un quinto
paquete vendorizado no obliga a editar el script. Es idempotente: si el archivo
ya está y es correcto, no lo vuelve a bajar; si está y no cuadra, lo reemplaza.

Es una herramienta de compilación. No viaja en el ejecutable y el motor sigue
sin abrir un solo socket — lo comprueba `engine/tests/test_offline.py`.

En una red con acceso normal a npm nada de esto hace falta: basta con borrar los
`overrides` y sustituir la referencia `file:` por `"monaco-editor": "^0.56.0"`.

## Un clon limpio

Esto era lo que estaba roto: `.gitignore` excluye `vendor/`, `package.json` lo
referencia con `file:`, y el flujo de CI hacía `pnpm install --frozen-lockfile`
sin aprovisionarlo. Un clon limpio fallaba con:

```
ENOENT: no such file or directory, open '.../vendor/monaco-editor-0.56.0.tgz'
```

Y no se notaba, porque el flujo solo se disparaba en ramas `claude/**` y
etiquetas `v*`. Ahora `.github/workflows/build-windows.yml` ejecuta
`scripts/fetch_vendor.py` antes de instalar, y corre también en `main` y en la
rama de trabajo.

## Lo que no se instaló

**React Flow**, que la especificación pedía para el grafo. Arrastra seis
dependencias, cada una con el mismo problema, y el lienzo que necesitábamos
—anillos acotados, expansión bajo demanda y una diferencia visual entre un hecho
y una inferencia— cabe en SVG propio sin dependencia alguna. Está en
`apps/desktop/src/components/GraphCanvas.tsx`, y la decisión se registró en el
commit de la Etapa 3.

## Un aviso que cuesta caro olvidar

`Set-Content -Encoding utf8` en Windows PowerShell 5.1 escribe **UTF-8 con BOM**.
Un BOM al principio de un `package.json` lo vuelve JSON inválido, y el error que
sale (`Failed to load PostCSS config`) no menciona el BOM por ningún lado. Para
editar archivos JSON desde PowerShell hay que usar
`[System.IO.File]::WriteAllText` con `UTF8Encoding($false)`.
