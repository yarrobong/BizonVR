#!/bin/zsh
set -euo pipefail

# Можно запускать/копировать этот файл из любого места.
# Если перенесете проект, поменяйте PROJECT_DIR.
PROJECT_DIR="/Users/Yaroslav/Documents/dev/BizonVR"
HOST="127.0.0.1"
PORT="8000"
URL="http://${HOST}:${PORT}/"

RUN_DIR="${PROJECT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/django-dev.pid"
LAUNCHER_LOG="${LOG_DIR}/launcher.log"
SERVER_CMD="${PROJECT_DIR}/launchers/BizonVR_Server.command"
LOGS_CMD="${PROJECT_DIR}/launchers/BizonVR_Logs.command"

mkdir -p "${LOG_DIR}"
touch "${LAUNCHER_LOG}"

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[${ts}] $1" | tee -a "${LAUNCHER_LOG}"
}

fail() {
  log "ERROR: $1"
  echo "ERROR: $1"
  exit 1
}

[[ -d "${PROJECT_DIR}" ]] || fail "Project dir not found: ${PROJECT_DIR}"
[[ -f "${PROJECT_DIR}/manage.py" ]] || fail "manage.py not found in ${PROJECT_DIR}"
[[ -x "${SERVER_CMD}" ]] || fail "Server launcher not executable: ${SERVER_CMD}"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    log "Server already running (PID ${PID})"
    open "${URL}" >/dev/null 2>&1 || true
    open "${LOGS_CMD}" >/dev/null 2>&1 || true
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

log "Opening Terminal server window"
open "${SERVER_CMD}" >/dev/null 2>&1 || fail "Cannot open ${SERVER_CMD}"

READY=0
if command -v curl >/dev/null 2>&1; then
  for _ in {1..60}; do
    if curl -fsS "${URL}" >/dev/null 2>&1; then
      READY=1
      break
    fi
    sleep 0.5
  done
else
  sleep 3
  READY=1
fi

if [[ "${READY}" -eq 1 ]]; then
  log "Server is reachable: ${URL}"
else
  log "Server readiness timed out; check logs"
fi

open "${URL}" >/dev/null 2>&1 || true
open "${LOGS_CMD}" >/dev/null 2>&1 || true

echo
echo "BizonVR start command executed"
echo "URL: ${URL}"
echo "If the site did not open, run: ${LOGS_CMD}"
