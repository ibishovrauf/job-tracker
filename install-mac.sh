#!/bin/bash
# Budapest Internship Tracker — one-step installer for macOS.
#
# Needs nothing pre-installed (no git, no Python, no admin password):
#   curl -fsSL https://raw.githubusercontent.com/ibishovrauf/job-tracker/hungary/install-mac.sh | bash
#
# Re-run the same line any time to update. Your settings (config.yaml) and
# saved jobs (jobtracker.sqlite3) are kept.

set -euo pipefail

APP_DIR="$HOME/BudapestJobs"
ZIP_URL="https://github.com/ibishovrauf/job-tracker/archive/refs/heads/hungary.zip"
LAUNCHER="$HOME/Desktop/Budapest Jobs.command"
PYTHON_VERSION="3.12"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
fail() {
    printf '\n\033[1;31mSomething went wrong:\033[0m %s\n' "$1"
    printf 'Take a screenshot of this window and send it to Rauf.\n\n'
    exit 1
}
trap 'fail "unexpected error on line $LINENO"' ERR

printf '\n\033[1m Budapest Internship Tracker — installer\033[0m\n'
printf ' This takes 2–5 minutes. Keep this window open until it says "All done".\n'

[[ "$(uname -s)" == "Darwin" ]] || fail "this installer is for macOS only."
curl -fsS --max-time 15 -o /dev/null https://github.com \
    || fail "no internet connection (could not reach github.com)."

# 1. uv: installs Python and all libraries privately, inside your home folder.
say "Step 1/4: installing the uv tool"
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
    ok "uv already installed"
else
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null \
        || fail "could not install uv."
    command -v uv >/dev/null 2>&1 || fail "uv was installed but cannot be found."
    ok "uv installed"
fi
# Only use uv's own Python. Touching macOS's /usr/bin/python3 placeholder would
# pop up a large "install developer tools" dialog.
export UV_PYTHON_PREFERENCE=only-managed

# 2. Download the app (a zip from GitHub; no git needed).
say "Step 2/4: downloading the app"
TMP="$(mktemp -d)"
curl -fsSL "$ZIP_URL" -o "$TMP/app.zip" || fail "could not download the app from GitHub."
unzip -q "$TMP/app.zip" -d "$TMP" || fail "the download was damaged; please run the installer again."
SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
mkdir -p "$APP_DIR"
# Update the code, but never touch the user's settings, jobs, or environment.
rsync -a --delete \
    --exclude 'config.yaml' --exclude 'jobtracker.sqlite3' --exclude '.venv/' \
    --exclude '*.log' \
    "$SRC/" "$APP_DIR/"
rm -rf "$TMP"
ok "app saved in $APP_DIR"

# 3. Python + libraries (exact tested versions from uv.lock).
say "Step 3/4: installing Python and libraries (the slow part)"
cd "$APP_DIR"
uv python install "$PYTHON_VERSION" --quiet || fail "could not install Python."
uv sync --frozen --python "$PYTHON_VERSION" --quiet || fail "could not install the libraries."
ok "Python $PYTHON_VERSION and libraries ready"

if [[ -f config.yaml ]]; then
    ok "kept your existing settings (config.yaml)"
else
    cp config.example.yaml config.yaml
    ok "created settings file config.yaml"
fi

# 4. Desktop launcher: double-click to collect new jobs and open the dashboard.
say "Step 4/4: creating the \"Budapest Jobs\" icon on your Desktop"
mkdir -p "$HOME/Desktop"
cat > "$LAUNCHER" <<'LAUNCH'
#!/bin/bash
# Double-click: opens the dashboard and collects today's new jobs.
# Close this window (or press Ctrl+C) to stop the dashboard.
cd "$HOME/BudapestJobs" || { echo "App folder ~/BudapestJobs is missing. Run the installer again."; read -r; exit 1; }
URL="http://127.0.0.1:8000"
TRACKER=".venv/bin/job-tracker"

clear
echo "Budapest Internship Tracker"
echo "---------------------------"

if curl -fs -o /dev/null "$URL"; then
    echo "The dashboard is already running — opening it."
    open "$URL"
    exit 0
fi

"$TRACKER" serve >/tmp/budapest-jobs-server.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

for _ in $(seq 1 30); do
    curl -fs -o /dev/null "$URL" && break
    sleep 1
done
open "$URL"

echo ""
echo "Dashboard opened in your browser: $URL"
echo ""
echo "Now collecting new jobs (1–2 minutes)..."
if "$TRACKER" scrape 2>>scrape.log | tail -n 1; then
    echo ""
    echo "Done. Refresh the browser page to see new jobs."
else
    echo "Some sources could not be reached; the dashboard still works."
fi
echo ""
echo "Keep this window open while you use the dashboard."
echo "Close it (or press Ctrl+C) when you're finished."
wait $SERVER
LAUNCH
chmod +x "$LAUNCHER"
ok "Desktop icon created"

say "First job collection (1–2 minutes)"
"$APP_DIR/.venv/bin/job-tracker" scrape 2>>"$APP_DIR/scrape.log" | tail -n 1 \
    || echo "    (some sources could not be reached — that's OK)"

trap - ERR
printf '\n\033[1;32m All done!\033[0m\n\n'
printf ' • Double-click \033[1m"Budapest Jobs"\033[0m on your Desktop to open the tracker.\n'
printf ' • To update later, run the same install line again.\n'
printf ' • Settings: %s/config.yaml  (guide: docs/CONFIGURATION.md)\n\n' "$APP_DIR"
