@echo off
setlocal enabledelayedexpansion
title AccelerateX - Local Launcher
cd /d "%~dp0.."
set "PYTHON_CMD="
py --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
  python --version >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo [Setup] Python was not found. Attempting installation through winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found and winget is unavailable. Install Python 3.9+ from https://www.python.org/downloads/.
    echo.
    pause
    exit /b 1
  )
  winget install --id Python.Python.3.12 --exact --silent --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [ERROR] Python installation failed.
    pause
    exit /b 1
  )
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts"
  py --version >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py"
  if not defined PYTHON_CMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
  if not defined PYTHON_CMD (
    echo [ERROR] Python was installed but is not available in this session. Close and reopen the launcher.
    pause
    exit /b 1
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo [Setup] First run detected - creating virtual environment and installing packages.
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create the virtual environment.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [Setup] Public PyPI install failed. To use a corporate mirror, edit this script
    echo and replace YOUR_CORPORATE_PYPI_MIRROR_URL_HERE with its URL.
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --index-url YOUR_CORPORATE_PYPI_MIRROR_URL_HERE
    if errorlevel 1 (
      echo [ERROR] Package installation failed from both indexes.
      pause
      exit /b 1
    )
  )
) else (
  echo [Setup] Virtual environment already present - checking packages.
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 echo [Warning] Package reconciliation failed. Existing deterministic modules may still run.
)
echo [Setup] Verifying RAG dependencies and indexing approved rules...
where ollama >nul 2>nul
if errorlevel 1 (
  echo [Setup] Ollama was not found. Attempting installation through winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Ollama is required. Install it from https://ollama.com/download/windows and retry.
    pause
    exit /b 1
  )
  winget install --id Ollama.Ollama --exact --silent --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo [ERROR] Ollama installation failed.
    pause
    exit /b 1
  )
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
)
".venv\Scripts\python.exe" scripts\setup_rag.py
if errorlevel 1 (
  echo [ERROR] RAG setup failed. AccelerateX will not start without embeddings, ChromaDB, and Ollama.
  pause
  exit /b 1
)
if not defined ADMIN_BANK_ID set "ADMIN_BANK_ID=admin"
if not defined ADMIN_PASSWORD set "ADMIN_PASSWORD=ChangeMe123!"
echo Checking for an existing process on port 8000...
set "FOUND_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  set "FOUND_PID=%%P"
  echo Stopping process %%P on port 8000.
  taskkill /PID %%P /F >nul 2>nul
)
for /f "tokens=2" %%P in ('tasklist /FI "WINDOWTITLE eq AccelerateX Server*" /FO LIST ^| findstr /B /C:"PID:"') do (
  echo Stopping previous AccelerateX console process %%P.
  taskkill /PID %%P /T /F >nul 2>nul
)
if not defined FOUND_PID echo Port 8000 is free.
echo Starting AccelerateX at http://localhost:8000
start "AccelerateX Server" cmd /k "cd /d "%~dp0.." && ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
timeout /t 4 /nobreak >nul
start "" "http://localhost:8000"
endlocal
exit /b 0
