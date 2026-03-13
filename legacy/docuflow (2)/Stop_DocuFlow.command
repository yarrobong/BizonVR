#!/bin/bash

PROJECT_DIR="/Users/Yaroslav/Downloads/docuflow (2)"
SCRIPT_PATH="$PROJECT_DIR/scripts/docuflow-stop.sh"

if [[ ! -x "$SCRIPT_PATH" ]]; then
  echo "Не найден файл остановки:"
  echo "$SCRIPT_PATH"
  echo
  echo "Если проект был перемещен, обновите путь PROJECT_DIR в этом файле."
  exit 1
fi

"$SCRIPT_PATH"
