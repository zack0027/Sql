# Firma de código

**Estado actual: HANA se distribuye sin firmar.** Esta página explica qué
significa eso, qué verá quien lo instale, y cómo firmarlo si decides hacerlo.

## Qué pasa hoy al instalar

Windows muestra una pantalla azul de **SmartScreen**:

> Windows protegió su PC
> Microsoft Defender SmartScreen impidió el inicio de una aplicación no
> reconocida.

Hay que pulsar **Más información → Ejecutar de todas formas**. No es un error ni
un falso positivo: Windows está diciendo la verdad. El instalador no lleva una
firma que diga quién lo hizo, así que el sistema no puede afirmar que el archivo
que estás abriendo es el que se compiló.

También aparecerá el aviso «Editor: Desconocido» en el control de cuentas de
usuario (UAC) al pedir permiso de administrador.

## Qué compra una firma, y qué no

Una firma Authenticode:

- **Acredita quién publicó** el binario, con una identidad verificada por una
  autoridad certificadora.
- **Detecta la manipulación**: si alguien modifica un byte del instalador, la
  firma deja de validar.
- **Reduce las alertas** de SmartScreen. Con un certificado OV la alerta
  desaparece tras acumular reputación; con uno EV desaparece de inmediato.

Lo que **no** hace: no dice que el programa sea seguro, ni lo audita nadie. Una
firma responde «¿quién lo hizo y llegó intacto?», no «¿es de fiar?».

Para una herramienta interna, distribuida por la propia empresa a sus propios
equipos, el aviso de SmartScreen es una molestia conocida y aceptable. Firmar
tiene sentido cuando el instalador va a circular por correo o por una unidad
compartida, donde nadie puede saber de dónde salió el archivo.

## Tipos de certificado

| Tipo | Coste anual aproximado | SmartScreen | Almacenamiento de la clave |
|---|---|---|---|
| OV (validación de organización) | 200–400 USD | Avisa hasta acumular reputación | Desde junio de 2023, obligatoriamente en HSM o token USB |
| EV (validación extendida) | 300–600 USD | Sin aviso desde el primer día | Token físico o HSM |
| Autofirmado | gratis | **No ayuda**: solo funciona en equipos donde se haya instalado el certificado a mano | Donde quieras |

Un certificado autofirmado sirve para probar la mecánica de firma, y para un
parque de equipos gestionado donde el certificado se distribuya por directiva de
grupo. Para todo lo demás, no resuelve nada.

Proveedores habituales: DigiCert, Sectigo, SSL.com, GlobalSign.

## Cómo firmar

Todo pasa por variables de entorno; el certificado nunca entra al repositorio.

### Con el certificado en el almacén de Windows (recomendado)

Localiza su huella digital:

```powershell
Get-ChildItem Cert:\CurrentUser\My | Format-List Subject, Thumbprint
```

Y compila:

```powershell
$env:HANA_SIGN_THUMBPRINT = "A1B2C3...."
python scripts/build_release.py
```

### Con un archivo .pfx

```powershell
$env:HANA_SIGN_PFX = "C:\ruta\certificado.pfx"
$env:HANA_SIGN_PASSWORD = "..."
python scripts/build_release.py
```

### Variables reconocidas

| Variable | Para qué |
|---|---|
| `HANA_SIGN_THUMBPRINT` | Huella SHA-1 de un certificado del almacén |
| `HANA_SIGN_PFX` | Ruta a un `.pfx`, si no está en el almacén |
| `HANA_SIGN_PASSWORD` | Contraseña del `.pfx` |
| `HANA_SIGN_TIMESTAMP` | Servidor RFC 3161. Por omisión, `http://timestamp.digicert.com` |

Sin ninguna de ellas la compilación sale sin firmar y lo dice al terminar.

## El orden importa

`scripts/build_release.py` firma **los binarios del motor antes** de que Tauri los
empaquete, y deja que Tauri firme la aplicación y el instalador. Ese orden no es
cosmético: un instalador firmado que contiene ejecutables sin firmar es peor que
uno sin firmar, porque presenta un sello de confianza sobre una carga que nadie
avala.

Lo que se firma, en orden:

1. `binaries/hana-engine-<triple>.exe` — el motor congelado
2. `binaries/hana.exe` — la herramienta de terminal
3. `hana-desktop.exe` — la aplicación (lo hace Tauri)
4. `HANA Knowledge Engine_<versión>_x64-setup.exe` — el instalador (lo hace Tauri)

## Requisitos

- **Windows SDK**, que aporta `signtool.exe`. El script lo busca en
  `C:\Program Files (x86)\Windows Kits\10\bin\*\x64\` y elige el más reciente; si
  no lo encuentra, lo dice y se detiene en vez de compilar algo a medias.
- **Conexión a internet durante la compilación**, solo para el sellado de tiempo.
  Esto no contradice el aislamiento del producto: HANA no abre la red al
  ejecutarse (ver `engine/tests/test_offline.py`), y el sellado ocurre en la
  máquina que compila, no en la del usuario.

## Comprobar una firma

```powershell
Get-AuthenticodeSignature ".\HANA Knowledge Engine_0.1.0_x64-setup.exe" |
  Format-List Status, SignerCertificate, TimeStamperCertificate
```

`Status: Valid` es lo que se busca. `NotSigned` es lo que se obtiene hoy.
