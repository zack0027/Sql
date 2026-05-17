# Setup del proyecto Unity — Warehouse Digital Twin

Guía reproducible para levantar el cliente Unity que se conecta al backend FastAPI.

## 1. Versión de Unity

- **Unity 6 LTS (6000.x)** con plantilla **3D (URP)**.
- Descarga desde Unity Hub. La plantilla URP nos da iluminación moderna sin meternos a HDRP (que pesa más para WebGL).

## 2. Crear el proyecto

1. Abrir Unity Hub → New Project → 3D Universal Render Pipeline.
2. Nombre: `WarehouseDigitalTwin`.
3. Una vez creado, copiar la carpeta `Assets/Scripts` de este repo a la raíz del proyecto.

## 3. Instalar NativeWebSocket

Según docs oficiales del repo `endel/NativeWebSocket`, NO se copian los archivos a mano (rompe la compilación condicional WebGL). Usar UPM:

1. Window → Package Manager.
2. Botón `+` arriba a la izquierda → "Add package from git URL".
3. Pegar exactamente:
   ```
   https://github.com/endel/NativeWebSocket.git#upm-2
   ```
4. Esperar a que Unity descargue. Aparecerá "Native WebSockets" en la lista de packages.

> Si Unity te muestra error de Git, instala Git for Windows (https://git-scm.com/download/win) y reinicia Unity Hub.

## 4. Configurar Player Settings

Edit → Project Settings → Player:

- **Resolution and Presentation → Run In Background: ✅ habilitado.**
  Este flag es crítico. Sin él Unity pausa el game loop cuando el tab pierde foco y los callbacks del WebSocket dejan de dispararse en WebGL.

- **Other Settings → Api Compatibility Level: .NET Standard 2.1** (es el default en Unity 6).

## 5. Configurar la escena

1. Crear escena nueva: `Assets/Scenes/Warehouse.unity`.
2. Crear GameObjects vacíos para los managers:
   - `_Bootstrap` (raíz, se queda en escena)
   - `_Bootstrap/WMSConnection`
   - `_Bootstrap/RackRegistry`
   - `_Bootstrap/AnomalyVisualizer`
   - `_Bootstrap/AlertFeedUI`
   - `_Bootstrap/NarrativePanelUI`
3. Asignar el script correspondiente a cada uno (drag desde `Assets/Scripts/...`).

## 6. Crear racks (cubos 3D)

Hacer un prefab `Rack` con:
- Un `Cube` con `MeshRenderer` (material `M_RackBase`, color gris neutro).
- Componente `RackId` (script, en este repo) con campo `locationCode` (ej. "A-001", "C-018").

Generar la grilla del almacén con un script editor o a mano. Para la demo basta una grilla de 6×6 (36 racks).

## 7. Verificar conexión

1. Levantar el backend FastAPI en `localhost:8000`.
2. En el Inspector de `WMSConnection`, poner `serverUrl = ws://localhost:8000/ws/alerts`.
3. Play. La consola debe mostrar `[WMS] Connected`.
4. Correr `simulator.py --rate 3`. Los racks afectados deben pulsar en color.

## Fuentes consultadas

- NativeWebSocket: https://github.com/endel/NativeWebSocket
- Unity 6 UPM Git: https://docs.unity3d.com/6000.2/Documentation/Manual/upm-ui-giturl.html
- Application.runInBackground: https://docs.unity3d.com/ScriptReference/Application-runInBackground.html
