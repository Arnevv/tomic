@echo off
REM === TOMIC Exit Intent Auto Runner ===
REM Met timeout om hangen te voorkomen
setlocal EnableDelayedExpansion

REM === CONFIGURATIE ===
set "MAX_RUNTIME_SECONDS=300"

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

REM Snelle bereikbaarheidstest TWS (poort 7497) - faal snel als down
powershell -NoProfile -Command "if (-not (Test-NetConnection -ComputerName '127.0.0.1' -Port 7497 -WarningAction SilentlyContinue).TcpTestSucceeded) { exit 2 }"
if %errorlevel% equ 2 (
    echo [%time%] FOUT: TWS/IB Gateway niet bereikbaar op 127.0.0.1:7497.
    echo         Zorg dat TWS of IB Gateway draait en API toegang aan staat.
    pause
    endlocal & exit /b 2
)
echo [%time%] TWS verbinding OK

REM Start de exit-flow module MET TIMEOUT
echo [%time%] Starten van exit-flow module (max %MAX_RUNTIME_SECONDS%s)...

REM Gebruik PowerShell om proces met timeout te starten
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$proc = Start-Process -FilePath '.venv\Scripts\python.exe' ^
        -ArgumentList '-u', '-m', 'tomic.cli.exit_flow' ^
        -NoNewWindow -PassThru -RedirectStandardOutput '%LOGFILE%' -RedirectStandardError '%LOGFILE%.err'; ^
    $finished = $proc.WaitForExit(%MAX_RUNTIME_SECONDS%000); ^
    if (-not $finished) { ^
        Write-Host '[TIMEOUT] Forceer stop na %MAX_RUNTIME_SECONDS%s'; ^
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; ^
        Start-Sleep -Milliseconds 500; ^
        exit 124; ^
    }; ^
    exit $proc.ExitCode"
set "RC=%ERRORLEVEL%"

REM Cleanup lege error log
if exist "%LOGFILE%.err" (
    for %%A in ("%LOGFILE%.err") do if %%~zA equ 0 del "%LOGFILE%.err"
)

if %RC% equ 124 (
    echo [%time%] TIMEOUT: Exit-flow duurde langer dan %MAX_RUNTIME_SECONDS% seconden.
    echo [%time%] Controleer %LOGFILE% voor details.
    pause
    endlocal & exit /b 124
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
