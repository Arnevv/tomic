@echo off
REM === TWS Connection Test ===
REM Simpele test om TWS connectie te valideren met client ID 999
setlocal EnableDelayedExpansion

REM === CONFIGURATIE ===
set "TOMIC_DIR=C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"

echo.
echo ============================================================
echo  TWS Connection Test
echo  %date% %time%
echo ============================================================
echo.

REM === Ga naar de TOMIC-map ===
cd /d "%TOMIC_DIR%"
if %errorlevel% neq 0 (
    echo [FOUT] Kon niet navigeren naar %TOMIC_DIR%
    exit /b 1
)
echo [INFO] Werkmap: %cd%

REM === Check virtuele omgeving ===
if not exist ".venv\Scripts\python.exe" (
    echo [FOUT] .venv\Scripts\python.exe niet gevonden
    echo       Zorg dat de virtuele omgeving is geinstalleerd
    exit /b 1
)

echo.
echo [INFO] Start TWS connection test...
echo.

REM === Voer de test uit ===
.venv\Scripts\python.exe scripts\tws_connection_test.py
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Afgerond: %date% %time%
echo  Exit code: %RC%
echo ============================================================

endlocal
exit /b %RC%
