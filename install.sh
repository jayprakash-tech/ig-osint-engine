#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
echo "== IG-OSINT-ENGINE installer =="

if [ -n "${PREFIX:-}" ] && echo "$PREFIX" | grep -q "com.termux"; then
    echo "[*] Termux detected"
    pkg update -y
    pkg install -y python python-numpy python-pandas libjpeg-turbo zlib
    VENV_FLAGS="--system-site-packages"
else
    echo "[*] Linux detected"
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 not found - install it first (e.g. sudo apt install python3 python3-venv)"
        exit 1
    fi
    VENV_FLAGS=""
fi

PYBIN="$(command -v python3 || command -v python)"

echo "[*] Creating virtual environment..."
"$PYBIN" -m venv $VENV_FLAGS venv

echo "[*] Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "[OK] Setup complete."
echo "Activate with:  source venv/bin/activate"
echo "Then run:       python main.py harvest --username <target> --cookies cookies.json"
