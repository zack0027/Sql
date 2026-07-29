# Instalar y usar HANA en Windows

Guía para quien solo quiere usar el programa. **No hace falta instalar Python,
Node ni ninguna otra cosa**: todo viaja dentro del instalador.

---

## 1. Instalar

Ejecuta **`HANA Knowledge Engine_0.1.0_x64-setup.exe`** y sigue el asistente.

### Windows te va a avisar. Es normal.

Aparecerá una pantalla azul:

> **Windows protegió su PC**
> Microsoft Defender SmartScreen impidió el inicio de una aplicación no
> reconocida.

Pulsa **Más información** y después **Ejecutar de todas formas**.

No es un virus ni un fallo. El instalador no lleva firma digital, y Windows
avisa de todo lo que no reconoce. Por qué, y qué haría falta para quitar el
aviso, está en [`FIRMA_DE_CODIGO.md`](FIRMA_DE_CODIGO.md).

### Si la ventana abre en blanco

Falta el **WebView2 Runtime**, que Windows 11 y Windows 10 actualizado ya
traen. Se descarga gratis desde el sitio de Microsoft buscando
«Evergreen WebView2 Runtime».

---

## 2. Analizar tu primer proyecto

1. Abre **HANA Knowledge Engine** desde el menú Inicio.
2. Pulsa **Abrir proyecto** y elige la carpeta que quieras estudiar. Vale
   cualquier carpeta con archivos `.sql`, `.jrxml`, `.mcmd`, `.json`, `.js` o
   `.py`. **Empieza por una pequeña** para ver el resultado en segundos.
3. Pulsa **Analizar proyecto**.

Verás el avance por fases: escaneando → comparando → inventariando →
analizando. Al terminar aparecen los contadores reales de archivos, entidades y
relaciones.

4. Pulsa **Explorar** para entrar al proyecto.

### Qué puedes hacer dentro

| Pestaña | Para qué |
|---|---|
| **Grafo** | Ver una entidad y lo que la rodea. Doble clic en un nodo para expandirlo. |
| **Diagrama ER** | Las tablas y cómo se relacionan, deducido de los `JOIN` que aparecen en el código. |
| **Reporte** | Un reporte Jasper pieza por pieza: cada banda con sus elementos y de dónde salen sus datos. |
| **Código** | El archivo abierto en la línea que prueba lo que estás mirando. |
| **Avisos** | Campos usados sin declarar, parámetros declarados sin usar, archivos que fallaron. |
| **Cambios** | Qué se movió desde el análisis anterior. |

El panel de la derecha es el importante: **cada relación trae el archivo, la
línea y el fragmento que la demuestran**. Pulsa cualquiera y se abre el código
justo ahí.

---

## 3. Qué significan las etiquetas

- **confirmado** — lo dice la sintaxis del archivo. No hay interpretación.
- **inferido** — HANA lo dedujo de una convención, por ejemplo que el item
  `P117_NUMCTL` pertenece a la página 117. Va con su nivel de confianza y puedes
  no estar de acuerdo.

Ninguna relación entra al grafo sin decir de dónde salió.

---

## 4. Volver a analizar

Analiza de nuevo cuando quieras: HANA solo relee lo que cambió, comparando el
contenido de cada archivo, no su fecha.

A veces verás un **aviso ámbar** al abrir un proyecto:

> *N archivos se analizaron con una versión anterior de los analizadores.*

Significa que HANA aprendió a extraer algo que antes no sabía leer, y que tu
grafo todavía no lo tiene. Pulsa **Volver a analizar** en el propio aviso. Tus
archivos no tienen nada malo.

---

## 5. Ajustar qué se escanea

Botón **Configuración**, en la pantalla de inicio, con un proyecto seleccionado.

| Ajuste | Qué hace |
|---|---|
| Carpetas ignoradas | Se saltan por nombre, a cualquier profundidad. Ya vienen `.git`, `node_modules`, `dist`… |
| Archivos ignorados | Patrones como `*.pyc`. |
| Tamaño máximo | Los archivos mayores se inventarían, pero no se leen. |
| Profundidad máxima | Niveles de carpeta por debajo de la raíz. |
| Seguir enlaces simbólicos | **Déjalo desactivado** salvo que sepas que lo necesitas: es la vía por la que un escaneo puede salirse de la carpeta que elegiste. |

Los cambios se aplican **en el próximo análisis**.

---

## 6. Lo que HANA nunca hace

Esto no son buenas intenciones: son restricciones comprobadas por las pruebas
automáticas del proyecto.

- **No envía nada fuera de tu equipo.** Ni tu código, ni nombres de archivo, ni
  estadísticas. No hay ninguna llamada de red — comprobado en
  `engine/tests/test_offline.py`, que ejecuta un análisis completo con la red
  bloqueada.
- **No ejecuta nada de lo que analiza.** Ni SQL, ni PL/SQL, ni comandos MOCA, ni
  scripts de Python o JavaScript, ni expresiones de JasperReports. Todo el
  análisis es lectura de texto.
- **No se conecta a Oracle.** Las relaciones entre tablas salen de las consultas
  escritas en tu código, no de la base de datos.
- **No modifica tus archivos.** Los abre en solo lectura.
- **No usa OpenAI ni ningún modelo remoto.** No hay ningún modelo de lenguaje
  involucrado: las respuestas se calculan sobre el grafo.

Puedes comprobarlo tú: desconecta el adaptador de red y usa el programa
normalmente. No cambia nada.

---

## 7. Dónde queda lo aprendido

```
%APPDATA%\com.hana.knowledge-engine\hana.db
```

Un solo archivo SQLite. Copiarlo es copiar todo el conocimiento; borrarlo es
empezar de cero. **No toca ningún archivo de tus proyectos.**

Para llegar rápido: `Win + R`, pega `%APPDATA%\com.hana.knowledge-engine` y
Enter.

---

## 8. Desinstalar

Configuración → *Aplicaciones* → **HANA Knowledge Engine** → Desinstalar.

La base de conocimiento en `%APPDATA%` **no se borra**. Elimínala a mano si
quieres no dejar rastro.

---

## Problemas conocidos

| Síntoma | Qué pasa |
|---|---|
| SmartScreen bloquea el inicio | El binario no está firmado. *Más información → Ejecutar de todas formas*. Ver [`FIRMA_DE_CODIGO.md`](FIRMA_DE_CODIGO.md). |
| La ventana abre en blanco | Falta el runtime de WebView2. Instálalo desde Microsoft. |
| «no se encontró WebView2Loader.dll» | Solo ocurre con la versión portátil: ese archivo tiene que estar en la misma carpeta que `hana-desktop.exe`. |
| Los contadores quedan en cero | La carpeta no tiene archivos analizables. Prueba con una que contenga `.sql` o `.jrxml`. |
| Un reporte `.jasper` no se analiza | Correcto: el `.jasper` es el compilado. HANA analiza el `.jrxml`. Ver [`REPORTES_JASPER.md`](REPORTES_JASPER.md). |
| El antivirus marca el ejecutable | Los binarios de PyInstaller disparan heurísticas con frecuencia. Se puede recompilar desde el código fuente para comprobarlo. |
| El análisis tarda mucho la primera vez | Es normal: la primera pasada lee todo. Las siguientes solo leen lo que cambió. |

---

## Versión portátil

Si prefieres no instalar nada, la carpeta portátil funciona igual. Estos tres
archivos **tienen que estar juntos**:

```
hana-desktop.exe        la aplicación
hana-engine.exe         el motor
WebView2Loader.dll      componente de la ventana
```

Se añade `hana.exe`, que es el motor desde la terminal, para quien lo quiera.
El protocolo que habla está en [`IPC_PROTOCOL.md`](IPC_PROTOCOL.md).
