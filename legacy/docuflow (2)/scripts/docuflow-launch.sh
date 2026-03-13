#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.docuflow-runtime"

FRONTEND_LOG="$RUNTIME_DIR/frontend.log"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
STATUS_FILE="$RUNTIME_DIR/status.txt"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"

FRONTEND_URL="http://localhost:3000"
BACKEND_URL="http://localhost:3001"

mkdir -p "$RUNTIME_DIR"

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

cleanup_stale_pid_file() {
  local file="$1"
  local pid
  pid="$(read_pid_file "$file" || true)"
  if [[ -n "$pid" ]] && ! is_running_pid "$pid"; then
    rm -f "$file"
  fi
}

pid_listening_on_port() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

wait_for_url() {
  local url="$1"
  local timeout_seconds="${2:-45}"
  local start_ts
  start_ts="$(date +%s)"

  while true; do
    if curl -fsS --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi

    if (( "$(date +%s)" - start_ts >= timeout_seconds )); then
      return 1
    fi

    sleep 1
  done
}

cleanup_stale_pid_file "$FRONTEND_PID_FILE"
cleanup_stale_pid_file "$BACKEND_PID_FILE"

existing_frontend_pid="$(read_pid_file "$FRONTEND_PID_FILE" || true)"
existing_backend_pid="$(read_pid_file "$BACKEND_PID_FILE" || true)"

if is_running_pid "$existing_frontend_pid" || is_running_pid "$existing_backend_pid"; then
  echo "DocuFlow appears to already be running."
  echo "Frontend PID: ${existing_frontend_pid:-not running}"
  echo "Backend PID:  ${existing_backend_pid:-not running}"
  echo "Logs: $RUNTIME_DIR"
  if [[ "${DOCUFLOW_NO_BROWSER:-0}" != "1" ]]; then
    open "$FRONTEND_URL" >/dev/null 2>&1 || true
  fi
  exit 0
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed (or not in PATH)."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not installed (or not in PATH)."
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/node_modules" ]]; then
  echo "Missing root node_modules. Run: npm install"
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/server/node_modules" ]]; then
  echo "Missing server node_modules. Run: npm --prefix server install"
  exit 1
fi

echo "Starting DocuFlow backend..."
nohup npm --prefix "$PROJECT_DIR/server" run dev >"$BACKEND_LOG" 2>&1 &
backend_pid=$!
echo "$backend_pid" > "$BACKEND_PID_FILE"

sleep 1

if ! is_running_pid "$backend_pid"; then
  echo "Backend failed to start. Check: $BACKEND_LOG"
  exit 1
fi

echo "Starting DocuFlow frontend..."
nohup npm --prefix "$PROJECT_DIR" run dev:client >"$FRONTEND_LOG" 2>&1 &
frontend_pid=$!
echo "$frontend_pid" > "$FRONTEND_PID_FILE"

sleep 1

if ! is_running_pid "$frontend_pid"; then
  echo "Frontend failed to start. Check: $FRONTEND_LOG"
  exit 1
fi

{
  echo "DocuFlow started: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "Project: $PROJECT_DIR"
  echo "Frontend URL: $FRONTEND_URL"
  echo "Backend URL:  $BACKEND_URL"
  echo "Frontend PID: $frontend_pid"
  echo "Backend PID:  $backend_pid"
  echo "Frontend log: $FRONTEND_LOG"
  echo "Backend log:  $BACKEND_LOG"
} > "$STATUS_FILE"

echo "Waiting for frontend on $FRONTEND_URL ..."
if wait_for_url "$FRONTEND_URL" 60; then
  echo "Frontend is up."
else
  echo "Frontend did not respond in time. It may still be starting."
  echo "Check logs: $FRONTEND_LOG"
fi

# Prefer the actual listener PIDs over npm wrapper PIDs so Stop_DocuFlow.command
# can terminate the right processes.
actual_frontend_pid="$(pid_listening_on_port 3000)"
actual_backend_pid="$(pid_listening_on_port 3001)"
if [[ -n "$actual_frontend_pid" ]]; then
  echo "$actual_frontend_pid" > "$FRONTEND_PID_FILE"
fi
if [[ -n "$actual_backend_pid" ]]; then
  echo "$actual_backend_pid" > "$BACKEND_PID_FILE"
fi

if [[ -n "$actual_frontend_pid" || -n "$actual_backend_pid" ]]; then
  frontend_pid="${actual_frontend_pid:-$frontend_pid}"
  backend_pid="${actual_backend_pid:-$backend_pid}"
  {
    echo "DocuFlow started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Project: $PROJECT_DIR"
    echo "Frontend URL: $FRONTEND_URL"
    echo "Backend URL:  $BACKEND_URL"
    echo "Frontend PID: $frontend_pid"
    echo "Backend PID:  $backend_pid"
    echo "Frontend log: $FRONTEND_LOG"
    echo "Backend log:  $BACKEND_LOG"
  } > "$STATUS_FILE"
fi

if [[ "${DOCUFLOW_NO_BROWSER:-0}" != "1" ]]; then
  echo "Opening browser: $FRONTEND_URL"
  open "$FRONTEND_URL" >/dev/null 2>&1 || true
fi

echo
echo "Done."
echo "Logs folder: $RUNTIME_DIR"
echo "Use ./DocuFlow_Logs.command to watch logs"
echo "Use ./Stop_DocuFlow.command to stop"
