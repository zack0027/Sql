# Deploy a GitHub Pages — Guía paso a paso

## Resumen del flujo

```
Push a main → GitHub Actions → game-ci/unity-builder@v4 → WebGL build
            → actions/upload-pages-artifact → actions/deploy-pages@v4
            → usuario.github.io/warehouse-twin disponible
```

Tiempo aproximado: **15-25 minutos** en el primer build (la image de Unity es grande). En builds incrementales con cache: **5-8 minutos**.

## Pre-requisitos

1. Cuenta de GitHub con repositorio público o GitHub Pro (Pages requiere repo público en plan free).
2. Cuenta de Unity (la versión Personal funciona, es gratis).
3. Tener el proyecto subido al repo con la estructura:
   ```
   repo/
   ├── unity_project/
   │   ├── Assets/
   │   ├── Packages/
   │   ├── ProjectSettings/
   │   └── ...
   └── .github/workflows/
       ├── deploy-webgl.yml
       └── acquire-license.yml
   ```

## Paso 1 — Setup inicial de secrets

En el repo de GitHub, ir a **Settings > Secrets and variables > Actions** y crear estos secrets:

| Nombre | Valor |
|---|---|
| `UNITY_EMAIL` | tu email de cuenta Unity |
| `UNITY_PASSWORD` | tu password de Unity |
| `UNITY_LICENSE` | (lo obtenemos en el paso 2) |

## Paso 2 — Obtener UNITY_LICENSE (one-time)

Unity Personal requiere activación manual con un archivo de licencia. El proceso es:

1. En el repo, ir a **Actions** tab.
2. Click en el workflow "Acquire Unity Activation File" (lado izquierdo).
3. Click "Run workflow" > "Run workflow" (botón verde).
4. Esperar a que termine (~1 min).
5. Descargar el artifact "Manual Activation File" del run.
6. Descomprimir, se obtiene un archivo `.alf`.
7. Ir a https://license.unity3d.com/manual
8. Subir el `.alf`, llenar el formulario (Personal license, individual).
9. Descargar el archivo `.ulf` que te entregan.
10. Copiar TODO el contenido del `.ulf` (es XML).
11. En GitHub > Settings > Secrets > Actions, crear secret `UNITY_LICENSE` con ese contenido.

> Este paso solo se hace UNA VEZ. La licencia vale por toda la vida del proyecto.

## Paso 3 — Habilitar GitHub Pages

1. En el repo, ir a **Settings > Pages**.
2. En "Build and deployment > Source", seleccionar **GitHub Actions**.
3. No es necesario crear branch `gh-pages` manualmente; el workflow se encarga.

## Paso 4 — Configurar Unity Player Settings

Antes del primer push, abrir el proyecto en Unity localmente y configurar:

**Edit > Project Settings > Player > WebGL > Publishing Settings**:
- Compression Format: **Brotli**
- Decompression Fallback: **✅ ENABLED** ← crítico para GH Pages
- Data Caching: ✅
- Debug Symbols: Off

**Player > Other Settings**:
- Managed Stripping Level: High
- Strip Engine Code: ✅

**Player > Resolution and Presentation**:
- Run In Background: ✅

Ver `BUILD_SETTINGS.md` para el detalle de cada opción.

## Paso 5 — Configurar la escena para Replay mode

En la escena `Warehouse.unity`:

1. Crear `_Bootstrap/Connections` (GameObject vacío).
2. Dentro crear dos hijos:
   - `_Bootstrap/Connections/LiveConnection` con `WMSConnection.cs`.
   - `_Bootstrap/Connections/ReplayConnection` con `ReplayConnection.cs`.
3. En `_Bootstrap/Connections` agregar `ConnectionModeSelector.cs`.
4. En el Inspector del Selector:
   - Initial Mode: **Replay**
   - Live Connection: arrastrar el hijo LiveConnection
   - Replay Connection: arrastrar el hijo ReplayConnection

Esto garantiza que el build de GitHub Pages arranque en modo Replay. Si en el día de la demo quieres modo Live, basta cambiar el toggle en Unity y rebuildear (o exponer un botón en la UI llamando a `SwitchToLive()`).

## Paso 6 — Primer push

```bash
git add .github/ unity_project/
git commit -m "Setup CI/CD for WebGL deploy"
git push origin main
```

Ir a la pestaña **Actions** del repo y observar el progreso. El primer build tarda 15-25 minutos.

## Paso 7 — Verificar el deploy

Cuando el workflow termina con check verde:

1. Ir a **Settings > Pages**.
2. Aparece la URL: `https://<usuario>.github.io/<repo>/`
3. Abrirla. Debe cargar el loader de Unity y luego la escena.
4. Después de 3 segundos debe empezar el replay.

## Troubleshooting

**El loader carga pero la escena no aparece (pantalla negra)**
- Revisar la consola del navegador (F12).
- Si dice "Invalid or unexpected token" en `.framework.js.unityweb`: Decompression Fallback NO está habilitado en el build. Activarlo y rebuildear.

**"Application.LoadFromStreamingAssets failed"**
- Falta el archivo `replay.json` en `Assets/StreamingAssets/`. Regenerarlo con `python3 replay_generator/generate_replay.py`.

**El workflow falla con "no UNITY_LICENSE"**
- El secret no se creó o el contenido del `.ulf` está incompleto. Repetir el paso 2.

**Build excede el tiempo del runner (>6h)**
- Improbable, pero si pasa, es problema de cache. Limpiar cache desde Actions > Caches.

## Modo Live el día de la demo (opcional)

Si quieres mostrar el sistema con backend real durante el pitch:

1. Levantar el backend en tu laptop: `python server.py`.
2. Exponer con ngrok: `ngrok http 8000 --scheme https`.
3. Copiar la URL HTTPS que da ngrok (ej. `https://abc123.ngrok-free.app`).
4. La URL WebSocket es `wss://abc123.ngrok-free.app/ws/alerts`.
5. Abrir tu demo desde la URL de GitHub Pages con query string:
   `https://usuario.github.io/repo/?live=wss://abc123.ngrok-free.app/ws/alerts`
6. (Esto requiere un pequeño parche en `WMSConnection.cs` para leer query string; queda como mejora opcional.)

## Fuentes oficiales

- GameCI docs: https://game.ci/docs/github/builder/
- actions/deploy-pages: https://github.com/actions/deploy-pages
- Unity Manual: https://docs.unity3d.com/Manual/webgl-deploying.html
- Ejemplo de referencia: https://github.com/NextFaze/github-action-unity-example
