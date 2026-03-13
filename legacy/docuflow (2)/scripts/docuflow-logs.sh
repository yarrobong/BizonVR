#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.docuflow-runtime"

FRONTEND_LOG="$RUNTIME_DIR/frontend.log"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
STATUS_FILE="$RUNTIME_DIR/status.txt"

mkdir -p "$RUNTIME_DIR"
touch "$FRONTEND_LOG" "$BACKEND_LOG"

echo "DocuFlow logs"
echo "Project: $PROJECT_DIR"
echo "Logs dir: $RUNTIME_DIR"
if [[ -f "$STATUS_FILE" ]]; then
  echo
  cat "$STATUS_FILE"
fi
echo
echo "Press Ctrl+C to stop watching."
echo

tail -n 120 -F "$BACKEND_LOG" "$FRONTEND_LOG"

