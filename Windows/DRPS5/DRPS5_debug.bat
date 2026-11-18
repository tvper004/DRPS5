@echo off
setlocal
cd /d "%~dp0"

echo ==========================================================
echo        DRPS5 - Diagnostico de Inicio
echo ==========================================================
echo Directorio: %CD%
echo.

if not exist "%CD%\runtime\python.exe" (
    echo [ERROR] No se encuentra runtime\python.exe en %CD%
    echo Verifique que los archivos de DRPS5 esten completos.
    goto :fin
)

echo [1/3] Verificando runtime de Python embebido...
"%CD%\runtime\python.exe" -c "import sys, platform; print("  Python:", sys.version); print("  Arch:", platform.machine()); print("  OS:", platform.platform())"
if errorlevel 1 (
    echo [ERROR CRITICO] Fallo al iniciar runtime\python.exe
    goto :fin
)

echo.
echo [2/3] Verificando modulos nativos...
"%CD%\runtime\python.exe" -c "import sys, os; sys.path.insert(0, os.getcwd()); import drps5_config; print("  drps5_config: OK")"
"%CD%\runtime\python.exe" -c "import sys, os; sys.path.insert(0, os.getcwd()); import drps5_core; print("  drps5_core: OK")"
"%CD%\runtime\python.exe" -c "import pygame; print("  pygame: OK")"
"%CD%\runtime\python.exe" -c "import av; print("  PyAV: OK")"
"%CD%\runtime\python.exe" -c "import sounddevice; print("  sounddevice: OK")"
"%CD%\runtime\python.exe" -c "import webview; print("  pywebview: OK")"

echo.
echo [3/3] Iniciando DRPS5 en modo consola interactiva...
echo ----------------------------------------------------------
"%CD%\runtime\python.exe" drps5.py --console
echo ----------------------------------------------------------
echo DRPS5 finalizo con codigo de salida: %ERRORLEVEL%

:fin
echo.
if exist crash.log (
    echo [CONTENIDO DE CRASH.LOG]:
    type crash.log
    echo.
)
echo ==========================================================
echo Presiona una tecla para salir...
pause >nul
