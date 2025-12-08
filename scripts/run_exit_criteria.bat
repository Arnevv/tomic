@echo off
REM === TOMIC Exit Intent Auto Runner (Improved) ===
REM Met timeout, betere foutafhandeling en automatische cleanup
setlocal EnableDelayedExpansion

REM === CONFIGURATIE ===
set "TOMIC_DIR=C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"
set "TWS_HOST=127.0.0.1"
set "TWS_PORT=4002"
set "MAX_RUNTIME_SECONDS=300"
set "TWS_CHECK_TIMEOUT=5"

echo.
echo ============================================================
echo  TOMIC Exit Intent Auto Runner
echo  Gestart: %date% %time%
echo ============================================================
echo.

REM === Ga naar de TOMIC-map ===
cd /d "%TOMIC_DIR%"
if %errorlevel% neq 0 (
    echo [FOUT] Kon niet navigeren naar %TOMIC_DIR%
    exit /b 1
)
echo [INFO] Werkmap: %cd%

REM === Zorg dat logmap bestaat ===
if not exist "exports\exit_logs" (
    mkdir "exports\exit_logs"
    echo [INFO] Logmap aangemaakt: exports\exit_logs
)

REM === Check virtuele omgeving ===
if not exist ".venv\Scripts\python.exe" (
    echo [FOUT] .venv\Scripts\python.exe niet gevonden
    echo       Zorg dat de virtuele omgeving is geinstalleerd
    exit /b 1
)
echo [INFO] Python gevonden: .venv\Scripts\python.exe

REM === Snelle bereikbaarheidstest TWS ===
echo [INFO] Controleer TWS bereikbaarheid op %TWS_HOST%:%TWS_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='SilentlyContinue'; ^
    $tcp = New-Object System.Net.Sockets.TcpClient; ^
    $result = $tcp.BeginConnect('%TWS_HOST%', %TWS_PORT%, $null, $null); ^
    $wait = $result.AsyncWaitHandle.WaitOne(%TWS_CHECK_TIMEOUT%000, $false); ^
    if (-not $wait -or -not $tcp.Connected) { exit 2 }; ^
    $tcp.Close(); exit 0"
if %errorlevel% equ 2 (
    echo [FOUT] TWS/IB Gateway niet bereikbaar op %TWS_HOST%:%TWS_PORT%
    echo       Controleer of:
    echo       - TWS/IB Gateway is gestart
    echo       - API connections zijn ingeschakeld (Configure ^> API ^> Settings)
    echo       - Socket port klopt (%TWS_PORT% voor paper, 4001 voor live)
    exit /b 2
)
echo [OK] TWS bereikbaar

REM === Stel logbestand in ===
set "PYTHONUNBUFFERED=1"
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set "D=%%c%%b%%a"
for /f "tokens=1-3 delims=:., " %%a in ("%time%") do set "T=%%a%%b%%c"
set "T=%T: =0%"
set "LOGFILE=exports\exit_logs\exit_auto_%D%_%T%.log"
echo [INFO] Logbestand: %LOGFILE%
echo.

REM === Start de exit-flow met timeout ===
echo [INFO] Start exit-flow module (max %MAX_RUNTIME_SECONDS%s)...
echo [INFO] Start: %time%
echo.

REM Gebruik timeout commando om proces te limiteren
REM Note: Dit vereist Windows 7+ of Server 2008+
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$proc = Start-Process -FilePath '.venv\Scripts\python.exe' ^
        -ArgumentList '-u', '-m', 'tomic.cli.exit_flow' ^
        -NoNewWindow -PassThru -RedirectStandardOutput '%LOGFILE%' -RedirectStandardError '%LOGFILE%.err'; ^
    $finished = $proc.WaitForExit(%MAX_RUNTIME_SECONDS%000); ^
    if (-not $finished) { ^
        Write-Host '[WAARSCHUWING] Timeout bereikt, forceer stop...'; ^
        $proc.Kill(); ^
        exit 124; ^
    }; ^
    exit $proc.ExitCode"
set "RC=%ERRORLEVEL%"

echo.
echo [INFO] Einde: %time%

REM === Resultaat verwerking ===
if %RC% equ 124 (
    echo [FOUT] Exit-flow timeout na %MAX_RUNTIME_SECONDS% seconden
    echo       Check %LOGFILE% voor details
    echo       Mogelijk hangt de TWS connectie - herstart TWS indien nodig
    goto :cleanup
)

if %RC% neq 0 (
    echo [FOUT] Exit-flow gestopt met code %RC%
    if exist "%LOGFILE%.err" (
        echo.
        echo === Foutmeldingen ===
        type "%LOGFILE%.err"
    )
    goto :cleanup
)

echo [OK] Exit-flow succesvol afgerond

:cleanup
REM === Cleanup error log als leeg ===
if exist "%LOGFILE%.err" (
    for %%A in ("%LOGFILE%.err") do (
        if %%~zA equ 0 del "%LOGFILE%.err"
    )
)

echo.
echo ============================================================
echo  Afgerond: %date% %time%
echo  Exit code: %RC%
echo ============================================================

endlocal
exit /b %RC%
