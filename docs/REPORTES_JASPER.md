# Reportes Jasper: `.jrxml` y `.jasper`

Un reporte de JasperReports vive en dos formatos, y HANA los trata de forma
distinta a propósito.

| | `.jrxml` | `.jasper` |
|---|---|---|
| Qué es | el fuente, XML | el compilado, objeto Java serializado |
| Lo edita | una persona, o iReport/Jaspersoft Studio | nadie: lo genera el compilador |
| HANA lo analiza | sí | no |
| Aparece en el explorador | sí | sí, marcado `binary` |

## Por qué el `.jasper` no se analiza

Leerlo exigiría deserializar objetos Java, y deserializar es ejecutar: la clase
elegida por el archivo decide qué corre al reconstruirse. Es exactamente el tipo
de cosa que este proyecto no hace con el código de tus proyectos. Además no
aportaría nada que el `.jrxml` no diga mejor, y no podría citar una línea, que es
lo único que HANA acepta como prueba.

Así que el `.jasper` se inventaría —para que sepas que existe y que hay un
compilado junto al fuente— con `detected_type = jasper-compiled` y
`skip_reason = binary`, y ahí se detiene.

**Si un reporte solo existe como `.jasper`, HANA no puede decir nada de él.** No
es una limitación que se pueda levantar sin romper la regla de no ejecutar nada
de lo analizado. Recupera el `.jrxml` del control de versiones o expórtalo desde
Jaspersoft Studio.

## Qué se extrae del `.jrxml`

- **Bandas** en orden de impresión, con su altura y sus elementos ubicados: es la
  previsualización por pieza.
- **Campos, parámetros y variables** declarados, y en qué elemento se consume
  cada uno.
- **Tablas y columnas** de la consulta del reporte (`queryString`), incluidas las
  **condiciones JOIN**, que alimentan el diagrama ER. En proyectos formados solo
  por reportes —sin un `.sql`— esta es la única fuente de relaciones entre
  tablas.
- **Subreportes e imágenes** referenciados, cuando la expresión es un literal.
  Una imagen elegida por un condicional (`$F{x}=="A" ? "./on.png" : "./off.png"`)
  se reconoce por sus literales con extensión de imagen; evaluar la condición
  sería ejecutar el reporte.

Nada de esto se calcula ejecutando JasperReports. La previsualización dibuja la
estructura, no el resultado impreso: no hay datos, no se resuelve ninguna
expresión, y la vista lo dice en pantalla para que no se confunda con una
impresión real.

## Si la previsualización sale vacía

Dos causas muy distintas, y HANA las distingue:

- *«el analizador no encontró bandas en este reporte»* — el `.jrxml` se leyó con
  los analizadores actuales y de verdad no declara bandas.
- *«lo leyó una versión anterior de HANA»* — el archivo se analizó antes de que
  existiera la extracción de bandas. El análisis incremental compara **hashes de
  contenido**, así que un archivo intacto no se vuelve a leer aunque HANA haya
  aprendido a sacarle más. El aviso ámbar de la parte superior del explorador
  ofrece volver a analizar; el archivo no tiene nada malo.

Ver [`002_analyzer_version.sql`](../engine/hana_engine/persistence/migrations/002_analyzer_version.sql)
para cómo se registra qué versión leyó cada archivo.
