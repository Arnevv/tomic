#!/bin/bash
# TOMIC Web Interface Starter
# Dit script start zowel de backend als de frontend

echo "=== TOMIC Web Interface ==="
echo ""

# Controleer of we in de juiste directory zijn
if [ ! -f "requirements.txt" ]; then
    echo "FOUT: Voer dit script uit vanuit de TOMIC root directory"
    exit 1
fi

# Functie om processen op te ruimen bij exit
cleanup() {
    echo ""
    echo "Stoppen van servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo "[1/2] Backend starten op http://localhost:8000..."
python -m uvicorn tomic.web.main:app --reload --port 8000 &
BACKEND_PID=$!

# Wacht even tot backend opstart
sleep 2

# Check of backend draait
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "FOUT: Backend kon niet starten"
    echo "Controleer of Python dependencies geinstalleerd zijn: pip install -r requirements.txt"
    exit 1
fi

echo "Backend draait (PID: $BACKEND_PID)"

# Start frontend
echo ""
echo "[2/2] Frontend starten op http://localhost:5173..."
cd frontend

# Check of node_modules bestaat
if [ ! -d "node_modules" ]; then
    echo "Node modules niet gevonden, installeren..."
    npm install
fi

npm run dev &
FRONTEND_PID=$!

cd ..

echo ""
echo "=== Servers gestart ==="
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo ""
echo "Open http://localhost:5173 in je browser"
echo "Druk Ctrl+C om te stoppen"
echo ""

# Wacht op beide processen
wait
