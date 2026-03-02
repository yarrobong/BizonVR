#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/Yaroslav/Documents/dev/BizonVR"
LAUNCHERS_DIR="${PROJECT_DIR}/launchers"
APPS_DIR="${LAUNCHERS_DIR}/apps"
WRAPPER_SRC="${LAUNCHERS_DIR}/BizonVR_AppWrapper.applescript"

mkdir -p "${APPS_DIR}"

if [[ ! -f "${WRAPPER_SRC}" ]]; then
  echo "Wrapper source not found: ${WRAPPER_SRC}"
  exit 1
fi

if ! command -v osacompile >/dev/null 2>&1; then
  echo "osacompile not found (macOS required)"
  exit 1
fi

build_app() {
  local app_name="$1"
  local script_path="$2"
  local app_title="$3"
  local out_app="${APPS_DIR}/${app_name}.app"

  rm -rf "${out_app}"
  osacompile -o "${out_app}" "${WRAPPER_SRC}"

  # Подменяем запуск так, чтобы compiled app передавал аргументы wrapper-скрипту.
  # Script is stored inside app bundle; use `osascript` launcher shim for predictable argv.
  cat > "${out_app}/Contents/MacOS/applet" <<EOF
#!/bin/zsh
exec /usr/bin/osascript "${WRAPPER_SRC}" "${script_path}" "${app_title}"
EOF
  chmod +x "${out_app}/Contents/MacOS/applet"
  echo "Built: ${out_app}"
}

build_app "BizonVR Start"  "${LAUNCHERS_DIR}/BizonVR_Start.command"  "BizonVR Start"
build_app "BizonVR Logs"   "${LAUNCHERS_DIR}/BizonVR_Logs.command"   "BizonVR Logs"
build_app "BizonVR Status" "${LAUNCHERS_DIR}/BizonVR_Status.command" "BizonVR Status"
build_app "BizonVR Stop"   "${LAUNCHERS_DIR}/BizonVR_Stop.command"   "BizonVR Stop"

echo
echo "Done."
echo "Apps folder: ${APPS_DIR}"
echo "Можно перетащить .app на Рабочий стол / в Dock."
