@echo off
echo ========================================================
echo Air Power - Dynamic Air Operations & Resource Optimisation
echo Problem Statement 26250 | SIH 2026
echo ========================================================
echo.

echo [1/3] Starting FastAPI Backend on port 8000...
start "Backend (FastAPI)" cmd /c "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/3] Starting Frontend Server on port 8080...
start "Frontend (HTTP)" cmd /c "python -m http.server 8080 --directory frontend"

echo [3/3] Waiting for servers to initialize...
timeout /t 3 /nobreak > nul

echo Opening dashboard in your default browser...
start http://localhost:8080

echo.
echo Press any key to terminate both servers and exit...
pause > nul

taskkill /fi "windowtitle eq Backend (FastAPI)" > nul 2>&1
taskkill /fi "windowtitle eq Frontend (HTTP)" > nul 2>&1
echo Services stopped.
exit
