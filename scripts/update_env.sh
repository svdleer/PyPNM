#!/usr/bin/env bash
set -euo pipefail

# Activate your Python virtual environment.
VENV_PATH="${1:-}"

if [[ -z "${VENV_PATH}" ]]; then
  if [[ -d ".env" ]]; then
    VENV_PATH=".env"
  elif [[ -d ".venv" ]]; then
    VENV_PATH=".venv"
  else
    VENV_PATH="./venv"
  fi
fi

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "✅ Using active virtual environment at ${VIRTUAL_ENV}"
elif [[ -d "${VENV_PATH}" ]]; then
  # shellcheck source=/dev/null
  source "${VENV_PATH}/bin/activate"
  echo "✅ Activated virtual environment at ${VENV_PATH}"
else
  echo "❌ Virtual environment not found at ${VENV_PATH}"
  echo "   Pass the venv path: ./scripts/update_env.sh .env"
  exit 1
fi

# Set environment variables.
export PYTHON_ENV="development"
export LOG_LEVEL="DEBUG"
export PYTHONPATH="${PWD}/src"

SYSTEM_JSON="${PWD}/src/pypnm/settings/system.json"
if [[ -f "${SYSTEM_JSON}" ]]; then
  export PNM_CONFIG_PATH="${SYSTEM_JSON}"
else
  echo "⚠️  Expected system.json not found at ${SYSTEM_JSON}"
fi

echo "✅ Environment variables set:"
echo "   PYTHON_ENV=${PYTHON_ENV}"
echo "   LOG_LEVEL=${LOG_LEVEL}"
echo "   PYTHONPATH=${PYTHONPATH}"
if [[ -n "${PNM_CONFIG_PATH:-}" ]]; then
  echo "   PNM_CONFIG_PATH=${PNM_CONFIG_PATH}"
fi
