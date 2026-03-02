#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/Yaroslav/Documents/dev/BizonVR"
HOST="127.0.0.1"
PORT="8000"
RUN_DIR="${PROJECT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/django-dev.pid"
LOG_FILE="${LOG_DIR}/django-dev.log"
LAUNCHER_LOG="${LOG_DIR}/launcher.log"

mkdir -p "${LOG_DIR}"
touch "${LOG_FILE}" "${LAUNCHER_LOG}"

if [[ ! -d "${PROJECT_DIR}" || ! -f "${PROJECT_DIR}/manage.py" ]]; then
  echo "Project not found: ${PROJECT_DIR}"
  exit 1
fi

PYTHON_BIN=""
if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
elif [[ -x "${PROJECT_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_DIR}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "Python not found (.venv/bin/python, venv/bin/python, python3)"
  exit 1
fi

cd "${PROJECT_DIR}"

# Пишем и на экран, и в файл лога.
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "================================================================="
echo "BizonVR Django server launcher"
echo "Project: ${PROJECT_DIR}"
echo "Python:  ${PYTHON_BIN}"
echo "URL:     http://${HOST}:${PORT}/"
echo "Time:    $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================="

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server window opened" >> "${LAUNCHER_LOG}"

if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
    echo "Another server process is already running (PID ${OLD_PID})."
    echo "Use BizonVR_Stop.command first."
    exit 1
  fi
fi

# PID shell'а станет PID python после exec ниже.
echo $$ > "${PID_FILE}"
echo "PID file: ${PID_FILE} (PID $$)"
echo "Log file: ${LOG_FILE}"
echo

# DEBUG=1 нужен для локального старта, если в .env DEBUG задан не-булевым значением.
exec env DEBUG=1 PYTHONUNBUFFERED=1 "${PYTHON_BIN}" manage.py runserver "${HOST}:${PORT}" --noreload
