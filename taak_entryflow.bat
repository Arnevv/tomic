@echo off
REM === TOMIC Entry Flow Auto Runner ===
REM Gebruikt absolute paden om te werken vanuit elke directory (incl. Task Scheduler)
setlocal EnableDelayedExpansion

REM === CONFIGURATIE: Repo root eenmalig vastleggen ===
set "REPO_ROOT=C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"
set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
set "LOG_DIR=%REPO_ROOT%\exports\entry_logs"

echo [%date% %time%] === Start TOMIC Entry Flow Auto Runner ===
echo [%time%] Repo root: %REPO_ROOT%

REM Zorg dat logmap bestaat
if not exist "%LOG_DIR%" (
    mkdir "%LOG_DIR%"
    echo [%time%] Logmap aangemaakt: %LOG_DIR%
)

REM Check virtuele omgeving
if not exist "%PYTHON_EXE%" (
    echo [%time%] FOUT: Python niet gevonden: %PYTHON_EXE%
    echo         Voer eerst uit: python -m venv .venv
    pause
    endlocal & exit /b 1
)

REM Snelle Python gezondheidscheck
echo [%time%] Python gezondheidscheck...
"%PYTHON_EXE%" --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [%time%] FOUT: Python kan niet starten.
    pause
    endlocal & exit /b 1
)
echo [%time%] Python OK

REM Stel logbestand in met absolute path
set "PYTHONUNBUFFERED=1"
set "RUNSTAMP=%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%"
set "RUNSTAMP=%RUNSTAMP: =0%"
set "LOGFILE=%LOG_DIR%\entry_auto_%RUNSTAMP%.log"
echo [%time%] Logbestand: %LOGFILE%

REM TWS bereikbaarheidstest via Python script (respecteert IB protocol)
echo [%time%] TWS bereikbaarheidscheck...
"%PYTHON_EXE%" "%REPO_ROOT%\scripts\tws_connection_test.py" >nul 2>&1
if %errorlevel% neq 0 (
    echo [%time%] FOUT: TWS/IB Gateway niet bereikbaar of connectie mislukt.
    echo [%time%] Controleer of TWS draait en API connecties accepteert op poort 7497.
    pause
    endlocal & exit /b 2
)
echo [%time%] TWS verbinding OK
REM Korte pauze om TWS tijd te geven de vorige connectie netjes af te sluiten
REM Gebruik ping i.p.v. timeout (werkt ook in niet-interactieve Taakplanner sessies)
ping localhost -n 3 >nul 2>&1

REM Start de entry-flow module met expliciete working directory
echo [%time%] Starten van entry-flow module...

REM Wissel naar repo root
cd /d "%REPO_ROOT%"

REM Gebruik PowerShell Tee-Object voor live console output + logging, met correcte exit code
REM NB: Commando op 1 regel om compatibiliteit met PowerShell-als-parent-shell te garanderen
REM Entry flow heeft timeout van 300s (5 min) en doet automatisch git sync voor IV data
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PYTHONUNBUFFERED='1'; & '%PYTHON_EXE%' -u -m tomic.cli.entry_flow_runner --timeout 300 2>&1 | Tee-Object -FilePath '%LOGFILE%'; exit $LASTEXITCODE"
set "RC=%ERRORLEVEL%"

REM Cleanup lege error log
if exist "%LOGFILE%.err" (
    for %%A in ("%LOGFILE%.err") do if %%~zA equ 0 del "%LOGFILE%.err"
)

if %RC% equ 124 (
    echo [%time%] WAARSCHUWING: Entry-flow timeout na 5 minuten.
    echo [%time%] Controleer of TWS nog draait en reageert.
    echo [%time%] Log: %LOGFILE%
    pause
    endlocal & exit /b %RC%
)

if %RC% neq 0 (
    echo [%time%] FOUT: Entry-flow gestopt met code %RC%.
    echo [%time%] Controleer %LOGFILE% voor details.
    pause
    endlocal & exit /b %RC%
)

echo [%time%] Entry-flow succesvol afgerond.
echo [%time%] Log: %LOGFILE%
endlocal & exit /b 0
