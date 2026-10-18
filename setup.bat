@echo off
setlocal enabledelayedexpansion

echo === Job Tracker Setup ===
echo.

:: ── Check Python 3.11+ ──
python --version >nul 2>&1
if errorlevel 1 (
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found. Install Python 3.11+ from https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
    set "PY=python3"
) else (
    set "PY=python"
)

for /f "tokens=*" %%i in ('%PY% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VERSION=%%i
for /f "tokens=*" %%i in ('%PY% -c "import sys; print(sys.version_info.major)"') do set PY_MAJOR=%%i
for /f "tokens=*" %%i in ('%PY% -c "import sys; print(sys.version_info.minor)"') do set PY_MINOR=%%i

if !PY_MAJOR! lss 3 (
    echo ERROR: Python 3.11+ required ^(found !PY_VERSION!^)
    pause
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 11 (
    echo ERROR: Python 3.11+ required ^(found !PY_VERSION!^)
    pause
    exit /b 1
)
echo [OK] Python !PY_VERSION!

:: ── Install uv if missing ──
uv --version >nul 2>&1
if errorlevel 1 (
    echo [*] Installing uv...
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    :: Refresh PATH
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
    uv --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: uv install failed. Visit https://docs.astral.sh/uv/getting-started/installation/
        pause
        exit /b 1
    )
)
echo [OK] uv installed

:: ── Create venv and install ──
cd /d "%~dp0"
set "PROJECT_DIR=%cd%"

echo [*] Creating virtual environment and installing dependencies...
:: uv sync installs the exact versions in uv.lock (newer sqlmodel/sqlalchemy break the app)
uv sync --quiet

:: ── Copy config if needed ──
if not exist config.yaml (
    copy config.example.yaml config.yaml >nul
    echo [OK] Created config.yaml from template
) else (
    echo [OK] config.yaml already exists
)

:: ── Run initial scrape ──
echo.
echo [*] Running initial scrape (this may take a minute)...
.venv\Scripts\job-tracker.exe scrape 2>nul || echo     (some sources may have failed - that's normal)

:: ── Import big company jobs if available ──
if exist by_hand\all_jobs.json (
    echo [*] Importing big company jobs...
    .venv\Scripts\job-tracker.exe scrape-byhand 2>nul || echo     (import had some issues - that's normal)
)

echo.
echo ========================================
echo   Setup complete!
echo.
echo   Start the dashboard:
echo     cd %PROJECT_DIR%
echo     .venv\Scripts\activate
echo     job-tracker serve
echo.
echo   Then open http://127.0.0.1:8000
echo ========================================
echo.
pause
