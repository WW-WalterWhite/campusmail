#!/usr/bin/env bash
# CampusMail one-time setup for macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "CampusMail needs Python 3.11 or newer (found $(python3 --version 2>&1))."; exit 1; }
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
if command -v ollama >/dev/null; then
  echo "Downloading the Qwen3 4B model (about 2.5 GB, first time only)..."
  ollama pull qwen3:4b || echo "The model download failed. Is the Ollama app running? Rules-only mode still works."
else
  echo "Ollama is not installed. Get it from https://ollama.com/download, then run ./setup.sh again."
  echo "You can still use CampusMail in 'Rules only' mode without it."
fi
echo "Setup finished. Start CampusMail with ./run.sh"
