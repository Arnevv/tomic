@echo off
REM === TOMIC Exit Intent Auto Runner ===
setlocal

echo [%date% %time%] === Start TOMIC Exit Intent Auto Runner ===

REM Ga naar de TOMIC-map
cd /d "C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"
echo [%time%] In directory: %cd%

REM Zorg dat logmap bestaat
if not exist "exports\exit_logs" (
    mkdir "exports\exit_logs"
    echo [%time%] Logmap aangemaakt: exports\exit_logs
)

REM Check virtuele omgeving
if not exist ".venv\Scripts\python.exe" (
    echo [%time%] FOUT: .venv\Scripts\python.exe niet gevonden.
    exit /b 1
)

REM Gebruik ongebufferde output naar een dag-log
set "PYTHONUNBUFFERED=1"
set "RUNSTAMP=%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%"
set "RUNSTAMP=%RUNSTAMP: =0%"
set "LOGFILE=exports\exit_logs\exit_auto_%RUNSTAMP%.log"
echo [%time%] Logbestand: %LOGFILE%

REM Snelle bereikbaarheidstest TWS (poort 7497) - faal snel als down
powershell -NoProfile -Command "if (-not (Test-NetConnection -ComputerName '127.0.0.1' -Port 7497 -WarningAction SilentlyContinue).TcpTestSucceeded) { exit 2 }"
if %errorlevel% equ 2 (
    echo [%time%] FOUT: TWS/IB Gateway niet bereikbaar op 127.0.0.1:7497.
    exit /b 2
)

REM Start de exit-flow module (unbuffered) met expliciete venv-python
echo [%time%] Starten van exit-flow module...
".venv\Scripts\python.exe" -u -m tomic.cli.exit_flow  >> "%LOGFILE%" 2>&1
set "RC=%ERRORLEVEL%"

if %RC% neq 0 (
    echo [%time%] FOUT: Exit-flow gestopt met code %
