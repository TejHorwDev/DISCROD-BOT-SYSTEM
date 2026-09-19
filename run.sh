#!/usr/bin/env bash
# ============================================================
#  SELLER BOT - one-click starter for Mac & Linux
#
#  Run it with:   bash run.sh      (or:  chmod +x run.sh && ./run.sh)
#
#  First run:  creates a private Python environment (.venv),
#              installs the requirements, creates your .env file.
#  Every run:  starts the app and opens http://localhost:5000
# ============================================================
cd "$(dirname "$0")" || exit 1

# ---- Find Python 3 ----
if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "  Python 3 was not found on this computer."
    echo "  Please install Python 3.10 or newer from:"
    echo "      https://www.python.org/downloads/"
    echo ""
    echo "  (Linux only: if 'python3 -m venv' later complains, also run:"
    echo "   sudo apt install python3-venv)"
    echo ""
    exit 1
fi

# ---- First run: create the private Python environment ----
if [ ! -f ".venv/bin/python" ]; then
    echo "  First run: creating a private Python environment..."
    python3 -m venv .venv || exit 1
fi

# ---- Install / update the requirements (needs internet) ----
echo "  Checking requirements (quick after the first time)..."
".venv/bin/python" -m pip install -r requirements.txt --disable-pip-version-check --quiet || {
    echo ""
    echo "  Could not install the requirements. Check your internet"
    echo "  connection and run this script again."
    echo ""
    exit 1
}

# ---- First run: create the .env settings file from the example ----
if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo ""
    echo "  A settings file (.env) has been created for you."
    echo ""
    echo "  NEXT STEPS:"
    echo "    1. Open the file .env in this folder with any text editor."
    echo "    2. Paste your Discord bot token after DISCORD_TOKEN="
    echo "    3. Save it, then run this script again."
    echo ""
    echo "  Where is my token? Discord Developer Portal -> your app -> Bot -> Reset Token"
    echo ""
    exit 0
fi

# ---- Which port? (reads PORT=... from .env if you changed it) ----
PORT=$(grep -E '^PORT=' .env 2>/dev/null | tail -1 | cut -d'=' -f2 | tr -d '[:space:]')
PORT=${PORT:-5000}

# ---- Start the app ----
echo ""
echo "  Starting SELLER BOT at http://localhost:$PORT"
echo "  Keep this window open. To stop the app, press CTRL+C here."
echo ""

# Open the browser a moment later, without blocking the server.
(
    sleep 1.5
    if command -v open >/dev/null 2>&1; then open "http://localhost:$PORT" 2>/dev/null
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$PORT" 2>/dev/null
    fi
) &

".venv/bin/python" "app.py"

echo ""
echo "  SELLER BOT has stopped."
