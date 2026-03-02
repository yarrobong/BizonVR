#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/Yaroslav/Documents/dev/BizonVR"
RUN_DIR="${PROJECT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/django-dev.pid"
LOG_FILE="${LOG_DIR}/django-dev.log"
URL="http://127.0.0.1:8000/"

mkdir -p "${LOG_DIR}"
touch "${LOG_FILE}"

echo "BizonVR status"
echo "Project: ${PROJECT_DIR}"
echo "URL: ${URL}"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "Server: RUNNING (PID ${PID})"
  else
    echo "Server: NOT RUNNING (stale pid file: ${PID:-empty})"
  fi
else
  echo "Server: NOT RUNNING (pid file missing)"
fi

if command -v curl >/dev/null 2>&1; then
  if curl -fsS "${URL}" >/dev/null 2>&1; then
    echo "HTTP: OK"
  else
    echo "HTTP: unreachable"
  fi
fi

echo
echo "Last log lines:"
echo "------------------------------------------------------------"
tail -n 40 "${LOG_FILE}" || true
