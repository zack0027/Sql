# Aplicar los shaders custom a los racks

Guía paso a paso. Lleva ~10 minutos de configuración una sola vez.

## Pre-requisito: shaders importados

Después de copiar `Assets/Shaders/WarehouseRack.shader` y `Assets/Shaders/RackOutline.shader` al proyecto, Unity los compila automáticamente.

Verificar en Project: ambos deben aparecer sin íconos de error rojos. Si tienen error, abrir el Inspector del shader y leer el mensaje compile-time.

## Paso 1 — Crear materiales

1. Project > Assets/Materials > Create > Material → `M_RackBase`.
   - Inspector > Shader > seleccionar `JCain > WarehouseRack`.
   - Base color: gris medio `(0.35, 0.35, 0.37, 1)`.
   - Emission color: negro `(0, 0, 0, 1)` — esto es importante porque el shader interpreta valores HDR, queremos arrancar apagado.
   - Pulse intensity: 0.
   - Smoothness: 0.35.

2. Create > Material → `M_RackOutline`.
   - Shader: `JCain > RackOutline`.
   - Outline color: HDR rojo `(2.5, 0.3, 0.1, 1)` — los valores >1 son la marca HDR.
   - Outline width: 0 (apagado por default; se modula en runtime).

## Paso 2 — Configurar el generador de grilla

En Unity:

1. Tools > Warehouse > Generate Grid.
2. En la ventana que se abre:
   - Rows: 6
   - Columns: 6
   - Spacing: 2.5
   - Rack size: (1.5, 2.5, 1.0)
   - **Rack material**: arrastrar `M_RackBase`.
   - **Outline material**: arrastrar `M_RackOutline`.
3. Click "Generate".

Esto crea 36 racks. Cada uno tiene:
- `MeshRenderer` con dos materiales en el array (slot 0 = base, slot 1 = outline).
- Componente `RackId` con su código de ubicación.
- Componente `SmoothNormalsAtRuntime` (suaviza normales del cubo al arrancar).

## Paso 3 — Configurar el visualizador

En la escena:

1. Seleccionar `_Bootstrap/AnomalyVisualizer`.
2. En el Inspector verificar:
   - Rack Material Index: 0
   - Outline Material Index: 1
   - Emission Property: `_EmissionColor`
   - Pulse Intensity Property: `_PulseIntensity`
   - Outline Color Property: `_OutlineColor`
   - Outline Width Property: `_OutlineWidth`
   - Pulse Hz: 2
   - Max Outline Width: 0.04
   - Outline Color Boost: 1.2

## Paso 4 — Configurar el Volume Profile

Ver `VOLUME_PROFILE.md` (instrucciones detalladas para Bloom + Tonemapping).

## Paso 5 — Verificar Color Space

Crítico para que el HDR funcione bien:

1. Edit > Project Settings > Player > Other Settings.
2. **Color Space: Linear** (NO Gamma).

> En Gamma color space, los valores HDR no se procesan correctamente y el bloom se ve "lavado".

## Paso 6 — Verificar URP Asset

1. Edit > Project Settings > Graphics.
2. Click en el URP Asset asignado (usualmente `URP-HighFidelity` o similar).
3. Quality > **HDR: ✅ ON**.
4. Post Processing: ✅ ON.

## Paso 7 — Probar

1. Play Mode.
2. El `ReplayConnection` empieza a disparar eventos a los 3 segundos.
3. Cuando una alerta de severidad `high` o `critical` llega al rack `C-018`:
   - El cubo se ilumina en color (rojo crítico, ámbar high).
   - Aparece un outline alrededor del cubo del mismo color, también pulsante.
   - El halo del bloom hace que el rack parezca "incandescente".

## Troubleshooting

**No veo emission ni outline al pulsar**
- Color Space no está en Linear.
- HDR está OFF en el URP Asset.
- El componente `AnomalyVisualizer` no tiene asignados los índices correctos de material.

**El outline tiene huecos en las esquinas del cubo**
- `SmoothNormalsAtRuntime` no está en el rack. Añadirlo manualmente o regenerar la grilla.

**El bloom es demasiado intenso (todo el almacén glow)**
- Subir el `Threshold` del Bloom de 1.0 a 1.5.
- Bajar la `Intensity` del Bloom de 1.2 a 0.8.

**Performance bajo en WebGL build**
- Bloom > High Quality Filtering: OFF.
- En el URP Renderer Data: desactivar Depth Texture si ningún shader la necesita.

## Próximos refinamientos opcionales

Una vez que la versión base funcione, ideas de polish:

- Añadir un `Light` puntual hijo de cada rack que se enciende sincronizado con el pulso (ilumina el suelo y los racks vecinos).
- Añadir partículas (`ParticleSystem`) que emanen del rack alertado, tipo humo o chispas.
- Sustituir el cubo primitivo por un mesh de rack industrial (modelo gratis en SketchFab).
