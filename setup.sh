#!/usr/bin/env bash
# CampusMail one-time setup for macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
if command -v ollama >/dev/null; then
  echo "Downloading the Qwen3 4B model (about 2.5 GB, first time only)..."
  ollama pull qwen3:4b
else
  echo "Ollama is not installed. Get it from https://ollama.com/download, then run ./setup.sh again."
  echo "You can still use CampusMail in 'Rules only' mode without it."
fi
echo "Setup finished. Start CampusMail with ./run.sh"
