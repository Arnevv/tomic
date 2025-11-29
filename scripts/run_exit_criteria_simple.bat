@echo off
REM === TOMIC Exit Intent Runner (Simple) ===
REM Gebruikt de Python timeout wrapper voor betere betrouwbaarheid
setlocal

set "TOMIC_DIR=C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"
set "MAX_TIMEOUT=300"

echo [%date% %time%] Start TOMIC Exit Intent Runner

cd /d "%TOMIC_DIR%"
if %errorlevel% neq 0 (
    echo [FOUT] Kon niet navigeren naar %TOMIC_DIR%
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [FOUT] .venv\Scripts\python.exe niet gevonden
    exit /b 1
)

REM Check TWS beschikbaarheid (directe TCP socket - veel sneller dan Test-NetConnection)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $tcp = New-Object System.Net.Sockets.TcpClient; $async = $tcp.BeginConnect('127.0.0.1', 7497, $null, $null); $wait = $async.AsyncWaitHandle.WaitOne(3000, $false); if (-not $wait -or -not $tcp.Connected) { $tcp.Close(); exit 2 }; $tcp.Close(); exit 0"
if %errorlevel% equ 2 (
    echo [FOUT] TWS niet bereikbaar op 127.0.0.1:7497
    exit /b 2
)

REM Stel logging in
set "PYTHONUNBUFFERED=1"
if not exist "exports\exit_logs" mkdir "exports\exit_logs"
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set "D=%%c%%b%%a"
for /f "tokens=1-3 delims=:., " %%a in ("%time: =0%") do set "T=%%a%%b%%c"
set "LOGFILE=exports\exit_logs\exit_%D%_%T%.log"

echo [%time%] Logbestand: %LOGFILE%
echo [%time%] Start exit flow (timeout: %MAX_TIMEOUT%s)...

REM Run met de timeout wrapper
".venv\Scripts\python.exe" -u -m tomic.cli.exit_flow_runner --timeout %MAX_TIMEOUT% >> "%LOGFILE%" 2>&1
set "RC=%ERRORLEVEL%"

if %RC% equ 124 (
    echo [%time%] TIMEOUT: Exit flow duurde te lang
) else if %RC% neq 0 (
    echo [%time%] FOUT: Exit code %RC%
) else (
    echo [%time%] OK: Exit flow succesvol
)

echo [%time%] Log: %LOGFILE%
endlocal
exit /b %RC%
