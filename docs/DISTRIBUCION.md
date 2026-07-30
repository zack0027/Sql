# Repartir HANA a otras personas

Estado actual: **funciona en el equipo donde se compila; en otros equipos de la
empresa el antivirus mata el motor**. Lo que sigue es lo averiguado, con las
mediciones, y lo que queda por hacer.

## El síntoma

La aplicación abre, el usuario lanza un análisis, y a mitad aparece:

> no está disponible (Se está cerrando la canalización. (os error 232)).
> el motor terminó con código 259

## Qué significa cada parte

**`os error 232`** es «la tubería se está cerrando»: el host escribió a un
proceso que ya no estaba. Describe la fontanería, no la avería.

**«código 259»** no es un código de salida. Es `STILL_ACTIVE`, el valor que
Windows devuelve para decir *«este proceso todavía no ha terminado»*. Aparece
porque el motor congelado en modo *onefile* son **dos** procesos: un lanzador que
se descomprime a sí mismo y ejecuta el intérprete real como hijo. El de dentro
murió; el de fuera aún se estaba cerrando cuando se le preguntó.

**`engine.log` vacío** es la pieza decisiva. Python que falla por su cuenta deja
siempre un traceback. El silencio absoluto significa que el proceso no falló:
algo externo lo terminó, sin darle ocasión de escribir.

## Lo descartado, con pruebas

| Hipótesis | Cómo se descartó |
|---|---|
| Falta la carpeta de datos | El motor la crea (`persistence/database.py`) |
| Depende del Python instalado | Lleva dentro `python312.dll`, `VCRUNTIME140.dll`, `sqlite3.dll` |
| Rutas con acentos o espacios | Probado con `Diseño de Programación\José Martínez.db` |
| `PYTHONHOME` / `PYTHONPATH` / `TEMP` alterados | Probados los cuatro casos |
| Falta de memoria | **Pico de 11 MB** analizando 1.275 archivos, 14.842 entidades y 76.851 relaciones |
| Falta `hana-engine.exe` al lado | Da otro mensaje, y el motor aquí sí arranca |

Once megabytes de pico deja la memoria fuera de discusión por dos órdenes de
magnitud.

## La causa

Los equipos de la empresa llevan **Trend Micro Apex One** además de Defender.

El motor, empaquetado con PyInstaller en modo *onefile*, hace en **cada
arranque**: descomprimirse en `%TEMP%\_MEIxxxxx` —un intérprete de Python entero,
una treintena de DLL— y ejecutarlas desde ahí. Acto seguido abre y lee miles de
archivos en segundos.

Escribir DLL en la carpeta temporal y ejecutarlas, desde un binario sin firmar,
mientras se recorre el disco a toda velocidad, es el retrato de un ransomware
para el monitoreo de comportamiento de un EDR. Lo termina sin dejarle escribir
nada — que es exactamente lo observado.

Explica también por qué en el equipo de desarrollo no ocurre: esos binarios
llevan días ejecutándose ahí y ya son conocidos.

## Qué hacer cuando toque repartirlo

En orden de esfuerzo:

1. **Pedir a IT una exclusión** para `hana-engine.exe`. No depende del código y
   se confirma el mismo día.

2. **Pasar el empaquetado a *onedir***. El arreglo de fondo: los archivos del
   motor quedan desempaquetados en una subcarpeta en vez de extraerse a `%TEMP%`
   en cada arranque, que es la conducta concreta que dispara al antivirus.
   Arranca más rápido y los códigos de salida vuelven a significar algo.

   Toca: `--onefile` en `scripts/build_sidecar.py`, `externalBin` en
   `tauri.conf.json` (habría que pasar a `resources`, porque `externalBin` exige
   un único archivo), y `bundled_engine_path()` en `sidecar.rs`. La carpeta
   portátil pasaría de tres archivos a tres más una subcarpeta `engine\`.

3. **Firmar el código.** Reduce mucho la sospecha del antivirus, y de paso quita
   el aviso de SmartScreen. Ver [`FIRMA_DE_CODIGO.md`](FIRMA_DE_CODIGO.md).

## Lo que sí está resuelto

Un motor que muere ya no se lleva la explicación consigo:

- Su `stderr` se guarda en `engine.log`, junto a la base de datos. Antes iba a
  `eprintln!`, que en una aplicación con ventana no va a ninguna parte.
- El mensaje de error dice si el proceso salió y con qué código, y sus últimas
  líneas. Cuando no dejó ninguna, lo dice — porque esa ausencia *es* la pista.
- `STILL_ACTIVE` se traduce en vez de presentarse como un código de salida.
- Si el motor no saluda al arrancar, la primera llamada recibe el motivo en vez
  de un error de tubería. La espera va en su propio hilo: la ventana aparece en
  unos dos segundos tanto si el motor arranca como si no.
- Falta `hana-engine.exe` al lado → el mensaje dice eso y cómo arreglarlo, en vez
  de hablar de Python.
- `scripts/diagnostico.cmd` arranca el motor a mano y enseña lo que diga, para
  cuando el problema está en otro equipo.
