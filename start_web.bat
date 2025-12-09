@echo off
REM === TOMIC Web Interface Starter (Windows) ===
setlocal EnableDelayedExpansion

echo === TOMIC Web Interface ===
echo.

REM Controleer of we in de juiste directory zijn
if not exist "requirements.txt" (
    echo FOUT: Voer dit script uit vanuit de TOMIC root directory
    pause
    exit /b 1
)

REM Zoek Python in venv of systeem
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    )
)

if "%PYTHON_EXE%"=="" (
    echo FOUT: Python niet gevonden
    pause
    exit /b 1
)

echo Python gevonden: %PYTHON_EXE%

REM Start backend in nieuwe terminal
echo.
echo [1/2] Backend starten op http://localhost:8000...
start "TOMIC Backend" cmd /k "%PYTHON_EXE% -m uvicorn tomic.web.main:app --reload --port 8000"

REM Wacht even tot backend opstart
timeout /t 3 /nobreak >nul

REM Start frontend
echo.
echo [2/2] Frontend starten op http://localhost:5173...
cd frontend

REM Check of node_modules bestaat
if not exist "node_modules" (
    echo Node modules niet gevonden, installeren...
    call npm install
)

start "TOMIC Frontend" cmd /k "npm run dev"

cd ..

echo.
echo === Servers gestart in aparte vensters ===
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo Open http://localhost:5173 in je browser
echo Sluit de terminal vensters om de servers te stoppen
echo.
pause
