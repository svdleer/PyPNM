#!/usr/bin/env sh
set -eu

APP_USER="pypnm"
APP_UID="10001"
APP_GID="10001"

CONFIG_DIR="/app/config"
CONFIG_FILE="${CONFIG_DIR}/system.json"
DEFAULT_CONFIG="/app/src/pypnm/settings/system.json"
DEFAULT_CONFIG_TEMPLATE="/app/src/pypnm/settings/system.json.template"
DEMO_CONFIG="/app/demo/settings/system.json"
DEMO_CONFIG_TEMPLATE="/app/demo/settings/system.json.template"
DEPLOY_CONFIG="/app/deploy/config/system.json"
DEPLOY_CONFIG_TEMPLATE="/app/deploy/config/system.json.template"
PKG_SETTINGS_DIR=""

LOG_DIR="/app/logs"
LOG_FILE="${LOG_DIR}/pypnm.log"

DATA_DIR="/app/.data"
OUTPUT_DIR="/app/output"

mkdir -p "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}"

# Resolve installed package settings path for system.json
PKG_SETTINGS_DIR="$(python3.12 - <<'PY'
import pathlib, pypnm
print((pathlib.Path(pypnm.__file__).parent / "settings").as_posix())
PY
)"
PKG_CONFIG="${PKG_SETTINGS_DIR}/system.json"

if [ ! -f "${CONFIG_FILE}" ]; then
  # Pick the first available source config
  for candidate in "${DEPLOY_CONFIG}" "${DEMO_CONFIG}" "${DEFAULT_CONFIG}" "${DEPLOY_CONFIG_TEMPLATE}" "${DEMO_CONFIG_TEMPLATE}" "${DEFAULT_CONFIG_TEMPLATE}"; do
    if [ -f "${candidate}" ]; then
      cp -f "${candidate}" "${CONFIG_FILE}"
      break
    fi
  done
fi

if [ ! -f "${CONFIG_FILE}" ]; then
  echo "Error: no config source found (checked ${DEFAULT_CONFIG}, ${DEPLOY_CONFIG}, templates)."
  exit 1
fi

# Point the installed package settings directory to the writable volume-backed config dir
if [ -n "${PKG_SETTINGS_DIR}" ]; then
  if [ -d "${PKG_SETTINGS_DIR}" ] && [ ! -L "${PKG_SETTINGS_DIR}" ]; then
    rm -rf "${PKG_SETTINGS_DIR}"
  fi
  if [ ! -L "${PKG_SETTINGS_DIR}" ]; then
    ln -s "${CONFIG_DIR}" "${PKG_SETTINGS_DIR}"
  fi
fi

if [ ! -f "${LOG_FILE}" ]; then
  touch "${LOG_FILE}"
fi

chown -R "${APP_UID}:${APP_GID}" "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}" || true
chmod -R u+rwX,go-rwx "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}" || true
# Prepare demo directory if present
if [ -d "/app/demo" ]; then
  mkdir -p /app/demo/.demo
  chown -R "${APP_UID}:${APP_GID}" /app/demo || true
  chmod -R u+rwX,go-rwx /app/demo || true
fi

exec gosu "${APP_USER}" "$@"
