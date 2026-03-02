#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/Yaroslav/Documents/dev/BizonVR"
RUN_DIR="${PROJECT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/django-dev.pid"
LAUNCHER_LOG="${LOG_DIR}/launcher.log"
HOST="127.0.0.1"
PORT="8000"

mkdir -p "${LOG_DIR}"
touch "${LAUNCHER_LOG}"

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[${ts}] $1" | tee -a "${LAUNCHER_LOG}"
}

stop_pid() {
  local pid="$1"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    for _ in {1..20}; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        return 0
      fi
      sleep 0.2
    done
    kill -9 "${pid}" 2>/dev/null || true
    return 0
  fi
  return 1
}

STOPPED=0
if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if stop_pid "${PID}"; then
    log "Stopped server PID ${PID}"
    STOPPED=1
  fi
  rm -f "${PID_FILE}"
fi

# Fallback: kill by command signature in case pid file is stale.
PIDS="$(pgrep -f "manage.py runserver ${HOST}:${PORT}" || true)"
if [[ -n "${PIDS}" ]]; then
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    if stop_pid "${pid}"; then
      log "Stopped fallback PID ${pid}"
      STOPPED=1
    fi
  done <<< "${PIDS}"
fi

if [[ "${STOPPED}" -eq 1 ]]; then
  echo "BizonVR server stopped."
else
  log "Stop requested, but no running server found"
  echo "Server is not running."
fi
