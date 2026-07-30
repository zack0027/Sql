@echo off
REM ---------------------------------------------------------------------------
REM  HANA - diagnostico del motor
REM
REM  Si la aplicacion dice que no puede hablar con el motor, ejecuta este
REM  archivo (doble clic) y manda una captura de lo que salga.
REM
REM  Arranca el motor a mano y le hace una sola pregunta. Cuando falla dentro de
REM  la aplicacion el error se pierde, porque una ventana de Windows no tiene
REM  donde escribirlo; aqui si se ve.
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ==========================================================
echo   HANA - diagnostico del motor
echo ==========================================================
echo.

echo [1] Archivos que tienen que estar en esta carpeta
echo.
for %%F in (hana-desktop.exe hana-engine.exe WebView2Loader.dll) do (
    if exist "%%F" (echo     OK      %%F) else (echo     FALTA   %%F   ^<-- este es el problema)
)
echo.

if not exist "hana-engine.exe" goto :fin

echo [2] Version de Windows
ver
echo.

echo [3] Arrancando el motor y preguntandole si responde
echo     (si no aparece nada debajo, algo lo esta bloqueando)
echo.
REM Ruta absoluta, no el nombre a secas: hay equipos con
REM NoDefaultCurrentDirectoryInExePath activado, donde cmd no busca en la
REM carpeta actual y responde "no se reconoce como un comando".
echo {"id":"1","method":"engine.ping"} | "%~dp0hana-engine.exe" "%TEMP%\hana-diagnostico.db"
echo.
echo     Codigo de salida del motor: %ERRORLEVEL%
echo.

if "%ERRORLEVEL%"=="0" (
    echo     El motor funciona. Si la aplicacion sigue fallando, manda tambien
    echo     el archivo:
    echo     %%APPDATA%%\com.hana.knowledge-engine\engine.log
) else (
    echo     El motor NO arranco. Las dos causas habituales son:
    echo.
    echo       a^) El antivirus lo bloqueo o lo puso en cuarentena.
    echo          Los programas empaquetados con PyInstaller disparan
    echo          heuristicas con frecuencia. Revisa la cuarentena.
    echo.
    echo       b^) Una politica de la empresa impide ejecutar desde la
    echo          carpeta temporal. El motor se descomprime en %%TEMP%%
    echo          para arrancar.
    echo.
    echo     Manda una captura de esta ventana entera.
)

:fin
echo.
echo ==========================================================
pause
endlocal
