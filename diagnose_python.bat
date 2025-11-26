@echo off
REM === Python Diagnostiek Tool voor TOMIC ===
REM Dit script helpt bij het troubleshooten van Python/venv problemen
setlocal EnableDelayedExpansion

echo ============================================
echo    TOMIC Python Diagnostiek
echo ============================================
echo.

REM Ga naar de TOMIC-map
cd /d "C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"
echo [INFO] Huidige directory: %cd%
echo.

echo === STAP 1: Controleer of .venv bestaat ===
if exist ".venv\Scripts\python.exe" (
    echo [OK] .venv\Scripts\python.exe gevonden
) else (
    echo [FOUT] .venv\Scripts\python.exe NIET gevonden!
    echo       Oplossing: Maak de venv opnieuw aan met: python -m venv .venv
    goto :end
)
echo.

echo === STAP 2: Test Python versie ===
echo Probeer: .venv\Scripts\python.exe --version
.venv\Scripts\python.exe --version
if %ERRORLEVEL% neq 0 (
    echo [FOUT] Python kon niet starten. Error code: %ERRORLEVEL%
    echo       Dit wijst op een corrupte venv of DLL probleem.
    goto :repair_suggestions
) else (
    echo [OK] Python versie check geslaagd
)
echo.

echo === STAP 3: Test Python import ===
echo Probeer basis imports...
.venv\Scripts\python.exe -c "import sys; print('Python pad:', sys.executable)"
if %ERRORLEVEL% neq 0 (
    echo [FOUT] Basis Python import mislukt.
    goto :repair_suggestions
)
echo [OK] Basis imports werken
echo.

echo === STAP 4: Test TOMIC imports ===
echo Probeer tomic module te importeren...
.venv\Scripts\python.exe -c "import tomic; print('TOMIC module OK')"
if %ERRORLEVEL% neq 0 (
    echo [WAARSCHUWING] TOMIC module import mislukt.
    echo               Controleer of alle dependencies geinstalleerd zijn.
    echo               Probeer: .venv\Scripts\pip install -e .
) else (
    echo [OK] TOMIC module import werkt
)
echo.

echo === STAP 5: Controleer TWS poort 7497 ===
powershell -NoProfile -Command "if ((Test-NetConnection -ComputerName '127.0.0.1' -Port 7497 -WarningAction SilentlyContinue).TcpTestSucceeded) { Write-Host '[OK] TWS/IB Gateway bereikbaar op poort 7497' } else { Write-Host '[FOUT] TWS/IB Gateway NIET bereikbaar op poort 7497' }"
echo.

echo === STAP 6: Controleer exit_logs directory ===
if exist "exports\exit_logs" (
    echo [OK] exports\exit_logs directory bestaat
    dir /b exports\exit_logs 2>nul | find /c /v "" > temp_count.txt
    set /p LOGCOUNT=<temp_count.txt
    del temp_count.txt
    echo     Aantal bestaande logs: !LOGCOUNT!
) else (
    echo [INFO] exports\exit_logs bestaat niet, wordt aangemaakt bij eerste run
)
echo.

echo ============================================
echo    Diagnostiek voltooid
echo ============================================
goto :end

:repair_suggestions
echo.
echo ============================================
echo    REPARATIE SUGGESTIES
echo ============================================
echo.
echo 1. VENV OPNIEUW AANMAKEN:
echo    Verwijder de .venv map en maak opnieuw aan:
echo    - rmdir /s /q .venv
echo    - python -m venv .venv
echo    - .venv\Scripts\pip install -e .
echo.
echo 2. SYSTEM PYTHON CONTROLEREN:
echo    Open een nieuwe CMD en type: python --version
echo    Als dit ook faalt, herinstalleer Python.
echo.
echo 3. ANTIVIRUS CONTROLEREN:
echo    Sommige antivirus software blokkeert Python.
echo    Voeg de TOMIC map toe aan de uitzonderingen.
echo.
echo 4. REBOOT:
echo    Soms lost een herstart DLL-problemen op.
echo.
echo 5. WINDOWS UPDATES:
echo    Controleer of alle Windows updates geinstalleerd zijn.
echo.

:end
echo.
echo Druk op een toets om af te sluiten...
pause >nul
endlocal
