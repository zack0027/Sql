# Volume Profile — Configuración para Bloom y Tonemapping

El Volume Profile es lo que hace que los valores HDR de emission del shader se vean realmente incandescentes. Sin Bloom activo, valores HDR como `(2.5, 0.1, 0.1)` se ven solo como rojo saturado pero plano. Con Bloom, el rojo "se desparrama" alrededor del rack creando el halo característico.

## Paso 1 — Crear el Volume GameObject

1. Jerarquía: GameObject > Volume > Global Volume.
2. Esto crea un GameObject con un componente `Volume` con `Is Global = true`.

## Paso 2 — Crear el Volume Profile

1. En el Inspector del Volume, click `New` al lado del campo Profile.
2. Unity crea un `.asset` en `Assets/`. Moverlo a `Assets/Settings/Warehouse_VolumeProfile.asset`.

## Paso 3 — Añadir overrides

Click "Add Override" y añadir tres efectos. Configurar cada uno:

### Bloom

| Parámetro | Valor | Comentario |
|---|---|---|
| Threshold | 1.0 | Solo amplifica píxeles con luminancia > 1.0 (HDR) |
| Intensity | 1.2 | Fuerza del halo |
| Scatter | 0.7 | Tamaño del halo (0=concentrado, 1=disperso) |
| Tint | (1, 1, 1) | Sin tinte específico (mantiene el color del shader) |
| Clamp | 65472 | Default, evita overflow numérico |
| High Quality Filtering | ON | En WebGL puede pesar; si va lento bajarlo a OFF |

### Tonemapping

| Parámetro | Valor |
|---|---|
| Mode | ACES |

> ACES (Academy Color Encoding System) es el tonemapper estándar de la industria del cine. Mapea valores HDR a colores percibidos de manera natural. Si los racks se ven "lavados" probar con `Neutral`.

### Color Adjustments (opcional, le da un toque cinemático)

| Parámetro | Valor |
|---|---|
| Post Exposure | 0 |
| Contrast | 15 |
| Saturation | 10 |

## Paso 4 — Verificar que URP Asset tiene Post-Processing habilitado

1. Edit > Project Settings > Graphics > Scriptable Render Pipeline Settings.
2. Click en el URP Asset asignado.
3. Quality > Post Processing: **ON**.
4. En el Renderer asset (asignado al URP Asset): Post Processing también ON.

## Paso 5 — Camera tiene Post-Processing habilitado

Seleccionar la Main Camera:
1. Component Camera > Rendering > Post Processing: **ON**.

## Verificación visual

En Play Mode con un rack alertado deberías ver:

- El rack en color rojo/ámbar saturado al pico del pulso.
- Un halo brillante alrededor del rack que se desvanece según la distancia.
- Las áreas no afectadas (otros racks, suelo) mantienen su iluminación normal.

Si NO ves el halo:
- Threshold del Bloom es demasiado alto (bajarlo a 0.9).
- El shader `_EmissionColor` no es HDR (valores < 1.0).
- Color Space NO está en Linear (Edit > Project Settings > Player > Color Space).
- Post-Processing está OFF en la camera.

## Fuentes consultadas

- Unity Manual Bloom: https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@17.0/manual/post-processing/bloom.html
- ACES Tonemapping explanation: https://acescentral.com/
