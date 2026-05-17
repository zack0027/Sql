# Build Settings para WebGL + GitHub Pages

## Por qué importa esta combinación específica

GitHub Pages es un static hosting muy simple: sirve archivos tal cual, sin permitir configurar headers HTTP como `Content-Encoding`. Esto rompe la configuración default de Unity WebGL, que asume servidores configurables (Apache, IIS, nginx).

Hay un issue famoso documentado en el repo `yanniboi/game-ci-test` donde el error típico es:

```
WebGL.framework.js.gz:1 Uncaught SyntaxError: Invalid or unexpected token
WebGL.loader.js:1 Uncaught ReferenceError: unityFramework is not defined
```

Esto pasa porque el browser descarga el `.gz` pensando que es texto plano. La solución oficial de Unity para hosting sin control de headers es **Decompression Fallback**: Unity embebe un descompresor JavaScript en el loader que descomprime los archivos en el cliente.

Trade-off documentado en Unity Manual: "Using this option results in a larger loader size and a less efficient loading scheme for the build files."

Para nuestra demo, el trade-off es aceptable: prefiero loader 200KB más grande pero garantía de que funciona en cualquier static hosting.

## Configuración exacta paso a paso

### Edit > Project Settings > Player > WebGL tab

**Resolution and Presentation**:
- Run In Background: ✅ (sin esto el game loop se pausa y los timers del replay se rompen)

**Other Settings**:
- Color Space: Linear
- Auto Graphics API: ✅
- Lightmap Encoding: Normal Quality
- Strip Engine Code: ✅
- Managed Stripping Level: **High**
  > Documentación oficial Unity 6: "High setting offers the best size reduction, it can sometimes be too aggressive and remove code that is used indirectly (e.g., via reflection)". En nuestro proyecto no usamos reflection, así que High es seguro.

**Publishing Settings** (la sección crítica):
- Compression Format: **Brotli**
  > Reduce tamaño 60-80% vs sin comprimir. Combinado con el siguiente flag funciona en GitHub Pages.
- Decompression Fallback: **✅ ENABLED**
  > Sin esto, GitHub Pages servirá los .br como texto roto. Esta es la solución oficial Unity para hosting sin Content-Encoding configurable.
- Data Caching: ✅
  > Permite que el browser cachee los assets entre visitas.
- Debug Symbols: Off (release build)

### Build > Build Settings

- Platform: WebGL
- Development Build: ❌ (release sin debug symbols)
- Build folder: `Build/` en la raíz del repo

## Tamaño esperado de la build

Con esta configuración y un proyecto minimalista como el nuestro (sin texturas pesadas, solo cubos y URP):

| Archivo | Tamaño estimado |
|---|---|
| `Build/WarehouseDemo.loader.js` | ~50-80 KB |
| `Build/WarehouseDemo.framework.js.unityweb` | ~600 KB-1 MB comprimido |
| `Build/WarehouseDemo.wasm.unityweb` | ~5-10 MB comprimido |
| `Build/WarehouseDemo.data.unityweb` | ~1-2 MB (depende de StreamingAssets) |
| **Total inicial** | **~7-13 MB** |

Como referencia, la documentación de SnappGames cita que "Empty projects can reach as low as 1.8MB using the Built-in Render Pipeline and Brotli compression, though typical games start around 5-10MB after optimizations."

Nuestro proyecto está en el rango típico porque usa URP (más pesado que Built-in pero más bonito).

## Sanity check antes de subir

Después del build, debes ver en `Build/`:

```
Build/
├── WarehouseDemo.data.unityweb
├── WarehouseDemo.framework.js.unityweb
├── WarehouseDemo.loader.js
└── WarehouseDemo.wasm.unityweb
```

Las extensiones `.unityweb` son la marca de que Decompression Fallback está habilitado. Si ves `.br`, `.gz`, o `.gzip` sin `.unityweb`, el setting está mal.

## Fuentes consultadas

- Unity Manual 6: https://docs.unity3d.com/Manual/webgl-deploying.html
- Unity Manual — Recommended WebGL Player Settings: https://docs.unity3d.com/2022.3/Documentation/Manual/web-optimization-player.html
- GitHub Pages compression issue: https://github.com/yanniboi/game-ci-test/issues/3
- Milton Candelero, Unity WebGL Compression Done Right: https://miltoncandelero.github.io/unity-webgl-compression
