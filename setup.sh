#!/usr/bin/env bash
set -euo pipefail

echo "=== Job Tracker Setup ==="
echo ""

# ── Check Python 3.11+ ──
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python 3.11+ required (found $PY_VERSION)"
    exit 1
fi
echo "[OK] Python $PY_VERSION"

# ── Install uv if missing ──
if ! command -v uv &>/dev/null; then
    echo "[*] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo "ERROR: uv install failed. Visit https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi
echo "[OK] uv $(uv --version 2>/dev/null || echo 'installed')"

# ── Create venv and install ──
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "[*] Creating virtual environment..."
uv venv .venv

echo "[*] Installing dependencies..."
uv pip install -e . --quiet

# ── Copy config if needed ──
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo "[OK] Created config.yaml from template"
else
    echo "[OK] config.yaml already exists"
fi

# ── Run initial scrape ──
echo ""
echo "[*] Running initial scrape (this may take a minute)..."
.venv/bin/job-tracker scrape || true

# ── Scrape big companies if by_hand/all_jobs.json exists ──
if [ -f by_hand/all_jobs.json ]; then
    echo "[*] Importing big company jobs..."
    .venv/bin/job-tracker scrape-byhand || true
fi

echo ""
echo "========================================"
echo "  Setup complete!"
echo ""
echo "  Start the dashboard:"
echo "    cd $PROJECT_DIR"
echo "    source .venv/bin/activate"
echo "    job-tracker serve"
echo ""
echo "  Then open http://127.0.0.1:8000"
echo "========================================"
