#!/usr/bin/env bash
# Measures CampusMail with the local model and saves a results table in results/.
cd "$(dirname "$0")"
. .venv/bin/activate || { echo "Run ./setup.sh first."; exit 1; }
exec python eval/benchmark.py "$@"
