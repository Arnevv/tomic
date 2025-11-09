@echo off
REM === TOMIC Exit Intent Auto Runner ===
setlocal

REM Ga naar de TOMIC-map
cd /d "C:\Users\Gebruiker\VSCode Projects\Tomic\tomic"

REM Activeer de virtuele omgeving
call ".venv\Scripts\activate.bat"

REM Start de exit-flow module en log uitvoer naar bestand
python -m tomic.cli.exit_flow >> "C:\Users\Gebruiker\VSCode Projects\Tomic\tomic\logs\exit_auto.log" 2>&1

endlocal
