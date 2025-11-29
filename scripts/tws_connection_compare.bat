@echo off
REM === TWS Connection Comparison Test ===
REM Tests both IBClient and QuoteSnapshotApp to find the problem
setlocal EnableDelayedExpansion

set "TOMIC_DIR=C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"

echo.
echo ============================================================
echo  TWS Connection Comparison Test
echo  %date% %time%
echo ============================================================

cd /d "%TOMIC_DIR%"
if %errorlevel% neq 0 (
    echo [FOUT] Kon niet navigeren naar %TOMIC_DIR%
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [FOUT] .venv\Scripts\python.exe niet gevonden
    exit /b 1
)

.venv\Scripts\python.exe scripts\tws_connection_compare.py
set "RC=%ERRORLEVEL%"

echo.
echo Exit code: %RC%
echo.
pause
endlocal
exit /b %RC%
