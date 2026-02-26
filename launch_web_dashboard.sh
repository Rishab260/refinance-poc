#!/bin/bash

set -e

echo "======================================================================"
echo "  Refi-Ready POC - FastAPI Dashboard Launcher"
echo "======================================================================"
echo ""

if [ -d ".conda" ]; then
  source "$(dirname "$0")/.conda/bin/activate" "$(dirname "$0")/.conda" || true
fi

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo ""
echo "Starting dashboard at: http://127.0.0.1:8000"
echo "Press Ctrl+C to stop."
echo ""

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
