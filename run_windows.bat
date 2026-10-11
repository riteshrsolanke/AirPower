@echo off
echo ========================================================
echo Starting Air Power Resource Optimisation (PS 26250)
echo ========================================================

:: Go to script directory (root)
cd /d "%~dp0"

:: Set encoding and pythonpath to fix emoji errors and module imports
set PYTHONIOENCODING=utf-8
set PYTHONPATH=.

echo [1/3] Setting up backend...
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
echo Installing requirements...
pip install -r requirements.txt > nul
echo Seeding database...
python seed_database.py

echo Starting backend server on port 8000...
start cmd /k "title Backend Server && cd /d "%~dp0" && set PYTHONPATH=. && call venv\Scripts\activate && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"

echo [2/3] Starting frontend server on port 8080...
start cmd /k "title Frontend Server && cd /d "%~dp0" && cd frontend && python -m http.server 8080"

echo [3/3] Opening application in browser...
timeout /t 3 > nul
start http://localhost:8080

echo.
echo Application is running!
echo - Frontend: http://localhost:8080
echo - Backend API: http://localhost:8000
echo.
echo Keep the other two terminal windows open to keep the servers running.
echo To stop, close those terminal windows.
pause
