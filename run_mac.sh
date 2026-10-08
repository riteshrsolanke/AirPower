#!/bin/bash

echo "============================================================"
echo "  AIR POWER PREDICTIVE MAINTENANCE — MAC STARTUP SCRIPT"
echo "============================================================"

# Start backend in the background
echo "Starting FastAPI backend on port 8000..."
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend in the background
echo "Starting HTTP server for frontend on port 8080..."
python3 -m http.server 8080 --directory frontend &
FRONTEND_PID=$!

# Wait a moment for servers to start
sleep 2

# Open in browser
echo "Opening frontend in default browser..."
open http://localhost:8080

echo "============================================================"
echo "✅ Both servers are running!"
echo "🛑 Press Ctrl+C to stop both servers."
echo "============================================================"

# Trap SIGINT (Ctrl+C) to kill both processes
trap "echo -e '\nStopping servers...'; kill $BACKEND_PID $FRONTEND_PID; exit" INT TERM EXIT

# Keep the script running to keep the background processes alive and listen for Ctrl+C
wait $BACKEND_PID $FRONTEND_PID
