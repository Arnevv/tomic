@echo off
REM === TOMIC Exit Intent Auto Runner ===
REM Roept exit_flow direct aan (niet via Start-Process om environment issues te voorkomen)
setlocal EnableDelayedExpansion

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
    echo         Voer eerst uit: python -m venv .venv
    pause
    endlocal & exit /b 1
)

REM Snelle Python gezondheidscheck voordat we beginnen
echo [%time%] Python gezondheidscheck...
.venv\Scripts\python.exe --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [%time%] FOUT: Python kan niet starten. Mogelijke oorzaken:
    echo         - Corrupte .venv map ^(oplossing: verwijder .venv en maak opnieuw^)
    echo         - DLL probleem ^(oplossing: herstart PC^)
    echo         - Antivirus blokkade
    echo         Voer diagnose_python.bat uit voor meer details.
    pause
    endlocal & exit /b 1
)
echo [%time%] Python OK

REM Gebruik ongebufferde output naar een dag-log
set "PYTHONUNBUFFERED=1"
set "RUNSTAMP=%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%"
set "RUNSTAMP=%RUNSTAMP: =0%"
set "LOGFILE=exports\exit_logs\exit_auto_%RUNSTAMP%.log"
echo [%time%] Logbestand: %LOGFILE%

REM Snelle bereikbaarheidstest TWS (poort 7497) - gebruik directe TCP socket (veel sneller dan Test-NetConnection)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $tcp = New-Object System.Net.Sockets.TcpClient; $async = $tcp.BeginConnect('127.0.0.1', 7497, $null, $null); $wait = $async.AsyncWaitHandle.WaitOne(3000, $false); if (-not $wait -or -not $tcp.Connected) { $tcp.Close(); exit 2 }; $tcp.Close(); exit 0"
if %errorlevel% equ 2 (
    echo [%time%] FOUT: TWS/IB Gateway niet bereikbaar op 127.0.0.1:7497.
    echo         Zorg dat TWS of IB Gateway draait en API toegang aan staat.
    pause
    endlocal & exit /b 2
)
echo [%time%] TWS verbinding OK

REM Start de exit-flow module DIRECT (niet via Start-Process om environment issues te voorkomen)
echo [%time%] Starten van exit-flow module...

REM Direct aanroepen - output gaat naar logfile, console toont voortgang
.venv\Scripts\python.exe -u -m tomic.cli.exit_flow > "%LOGFILE%" 2>&1
set "RC=%ERRORLEVEL%"

REM Cleanup lege error log
if exist "%LOGFILE%.err" (
    for %%A in ("%LOGFILE%.err") do if %%~zA equ 0 del "%LOGFILE%.err"
)

if %RC% neq 0 (
    echo [%time%] FOUT: Exit-flow gestopt met code %RC%.
    echo [%time%] Controleer %LOGFILE% en %LOGFILE%.err voor details.
    pause
    endlocal & exit /b %RC%
)

echo [%time%] Exit-flow succesvol afgerond.
echo [%time%] Log: %LOGFILE%
endlocal & exit /b 0
