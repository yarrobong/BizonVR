#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/Yaroslav/Documents/dev/BizonVR"
LOG_DIR="${PROJECT_DIR}/.run/logs"
LOG_FILE="${LOG_DIR}/django-dev.log"
PID_FILE="${PROJECT_DIR}/.run/django-dev.pid"

mkdir -p "${LOG_DIR}"
touch "${LOG_FILE}"

echo "BizonVR logs"
echo "Project: ${PROJECT_DIR}"
if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "Server PID: ${PID} (running)"
  else
    echo "Server PID file exists, but process is not running"
  fi
else
  echo "Server PID: not found"
fi
echo "Log file: ${LOG_FILE}"
echo "Press Ctrl+C to stop tailing"
echo "------------------------------------------------------------"

tail -n 120 -f "${LOG_FILE}"
