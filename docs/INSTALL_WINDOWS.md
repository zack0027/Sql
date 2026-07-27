# Instalación en Windows

Guía para probar HANA sin compilar nada. **No hace falta instalar Python**: el
motor viaja congelado dentro del instalador.

## 1. Descargar

1. Abre la pestaña **Actions** del repositorio.
2. Entra en la ejecución más reciente de **Build Windows** que aparezca en verde.
3. Al final de la página, en **Artifacts**, descarga
   `hana-knowledge-engine-windows`.
4. Descomprime el `.zip`. Dentro encontrarás:

| Archivo | Tamaño | Qué es |
|---|---|---|
| `HANA Knowledge Engine_0.1.0_x64_en-US.msi` | 10,8 MB | Instalador MSI |
| `HANA Knowledge Engine_0.1.0_x64-setup.exe` | 10,3 MB | Instalador NSIS |
| `portable/hana-desktop.exe` | 3,5 MB | Aplicación, sin instalar |
| `portable/hana-engine.exe` | 9,1 MB | Motor congelado |

Los dos archivos de `portable/` **deben quedar en la misma carpeta**: la
aplicación busca el motor junto a su propio ejecutable y no arranca sin él.

Los artefactos de GitHub Actions **caducan a los 30 días** y requieren haber
iniciado sesión en GitHub para descargarlos.

## 2. Instalar

Ejecuta cualquiera de los dos instaladores. El MSI es el más predecible en
equipos corporativos; el NSIS permite instalar sin privilegios de administrador.

### El aviso de SmartScreen

El ejecutable **no está firmado digitalmente**, así que Windows mostrará:

> *Windows protegió su PC — Microsoft Defender SmartScreen impidió el inicio de
> una aplicación desconocida.*

Es lo esperado en una compilación de prueba. Para continuar:
**Más información → Ejecutar de todas formas**.

Firmar el código requiere un certificado de firma comercial; está anotado como
pendiente en `ROADMAP.md`.

### WebView2

La aplicación usa el motor de WebView2, incluido de serie en Windows 11 y en
Windows 10 actualizado. Si el instalador se queja, instala el
*Evergreen WebView2 Runtime* desde el sitio de Microsoft.

## 3. Probar

1. Abre **HANA Knowledge Engine** desde el menú Inicio.
2. Pulsa **Abrir proyecto** y elige una carpeta con archivos `.sql`, `.jrxml`,
   `.mcmd` o `.json`. Empieza por algo pequeño.
3. Pulsa **Analizar proyecto**.

Deberías ver el progreso por fases (escaneando → comparando → inventariando →
analizando), y al terminar los contadores de archivos, entidades y relaciones.

**Qué esperar de esta versión:** los analizadores llegan en la Etapa 2, así que
el grafo todavía contiene una entidad `File` por archivo analizado. Lo que ya es
real y comprobable es la tubería completa: escaneo seguro, hash SHA-256,
detección incremental y persistencia con procedencia.

### La prueba que de verdad demuestra el motor

1. Analiza la carpeta. Anota los archivos nuevos.
2. Vuelve a pulsar **Analizar proyecto** sin tocar nada.
   → debe reportar **0 nuevos, 0 modificados** y 0 archivos analizados.
3. Edita **un** archivo y analiza otra vez.
   → debe reportar exactamente **1 modificado**.
4. Cierra la aplicación y vuelve a abrirla.
   → el proyecto y sus contadores siguen ahí.
5. Desconecta el adaptador de red y repite.
   → nada cambia.

## 4. Dónde queda el conocimiento

```
%APPDATA%\HanaKnowledgeEngine\hana.db
```

Borrar ese archivo borra todo lo aprendido. **No toca ningún archivo de tus
proyectos**: HANA los abre en solo lectura y nunca ejecuta nada de lo que
encuentra.

## 5. Usar el motor desde la terminal

El motor congelado funciona sin la interfaz:

```powershell
.\portable\hana-engine.exe C:\ruta\hana.db
```

Queda a la espera de líneas JSON. Para probarlo:

```json
{"id":"1","method":"engine.ping"}
{"id":"2","method":"project.open","params":{"path":"C:\\proyectos\\inspeccion"}}
```

El protocolo completo está en [`IPC_PROTOCOL.md`](IPC_PROTOCOL.md).

## 6. Desinstalar

Panel de control → *Aplicaciones* → **HANA Knowledge Engine** → Desinstalar.
La base de conocimiento en `%APPDATA%` no se borra automáticamente; elimínala a
mano si quieres empezar de cero.

## Problemas conocidos

| Síntoma | Causa y solución |
|---|---|
| SmartScreen bloquea el inicio | El binario no está firmado. *Más información → Ejecutar de todas formas*. |
| La ventana abre en blanco | Falta el runtime de WebView2. Instálalo desde Microsoft. |
| Los contadores quedan en cero | Normal si la carpeta no tiene archivos analizables. Prueba con `.sql` o `.jrxml`. |
| El antivirus marca el ejecutable | Los binarios de PyInstaller disparan heurísticas con frecuencia. La compilación es reproducible desde el código fuente del repositorio. |
