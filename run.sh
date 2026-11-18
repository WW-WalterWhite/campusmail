#!/usr/bin/env bash
cd "$(dirname "$0")"
. .venv/bin/activate || { echo "Run ./setup.sh first."; exit 1; }
exec streamlit run app.py --browser.gatherUsageStats false
