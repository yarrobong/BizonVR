#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.docuflow-runtime"

FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"

read_pid_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -dc '0-9' < "$file"
  fi
}

is_running_pid() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

pid_listening_on_port() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

stop_pid() {
  local name="$1"
  local pid="$2"

  if [[ -z "$pid" ]]; then
    echo "$name: no PID"
    return 0
  fi

  if ! is_running_pid "$pid"; then
    echo "$name: PID $pid is not running"
    return 0
  fi

  echo "Stopping $name (PID $pid)..."
  kill "$pid" 2>/dev/null || true

  for _ in {1..10}; do
    if ! is_running_pid "$pid"; then
      echo "$name stopped"
      return 0
    fi
    sleep 0.5
  done

  echo "$name did not stop gracefully, forcing..."
  kill -9 "$pid" 2>/dev/null || true
}

frontend_pid="$(read_pid_file "$FRONTEND_PID_FILE" || true)"
backend_pid="$(read_pid_file "$BACKEND_PID_FILE" || true)"

if [[ -z "$frontend_pid" ]]; then
  frontend_pid="$(pid_listening_on_port 3000)"
elif ! is_running_pid "$frontend_pid"; then
  fallback_frontend_pid="$(pid_listening_on_port 3000)"
  if [[ -n "$fallback_frontend_pid" ]]; then
    frontend_pid="$fallback_frontend_pid"
  fi
fi

if [[ -z "$backend_pid" ]]; then
  backend_pid="$(pid_listening_on_port 3001)"
elif ! is_running_pid "$backend_pid"; then
  fallback_backend_pid="$(pid_listening_on_port 3001)"
  if [[ -n "$fallback_backend_pid" ]]; then
    backend_pid="$fallback_backend_pid"
  fi
fi

stop_pid "frontend" "$frontend_pid"
stop_pid "backend" "$backend_pid"

rm -f "$FRONTEND_PID_FILE" "$BACKEND_PID_FILE"

echo "Done. Logs are kept in: $RUNTIME_DIR"
