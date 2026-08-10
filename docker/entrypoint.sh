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

# Normalize legacy and canonical configuration selectors without overriding
# an explicit operator-provided path. Runtime configuration belongs under
# /app/config and must never require rewriting installed or bind-mounted code.
PYPNM_CONFIG_PATH="${PYPNM_CONFIG_PATH:-${PYPNM_CONFIG:-${CONFIG_FILE}}}"
export PYPNM_CONFIG_PATH

LOG_DIR="/app/logs"
LOG_FILE="${LOG_DIR}/pypnm.log"

DATA_DIR="/app/.data"
OUTPUT_DIR="/app/output"
VOLUME_DATA_DIR="/app/data"
VOLUME_CACHE_DIR="/app/data/pnm_cache"

mkdir -p "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}" "${VOLUME_DATA_DIR}" "${VOLUME_CACHE_DIR}"

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

if [ ! -f "${LOG_FILE}" ]; then
  touch "${LOG_FILE}"
fi

chown -R "${APP_UID}:${APP_GID}" "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}" || true
chmod -R u+rwX,go-rwx "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${OUTPUT_DIR}" || true

# Ensure volume-backed data directories remain writable even when Docker
# recreates the volume with host-side ownership that differs from APP_UID.
chown -R "${APP_UID}:${APP_GID}" "${VOLUME_DATA_DIR}" || true
chmod -R u+rwX,g+rX "${VOLUME_DATA_DIR}" || true
# Prepare demo directory if present
if [ -d "/app/demo" ]; then
  mkdir -p /app/demo/.demo
  chown -R "${APP_UID}:${APP_GID}" /app/demo || true
  chmod -R u+rwX,go-rwx /app/demo || true
fi

exec gosu "${APP_UID}:${APP_GID}" "$@"
