#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
IFS=$'\n\t'

KEY_PATH_DEFAULT="$HOME/.ssh/pypnm_secrets.key"

usage() {
  cat <<EOF
PyPNM Secret Key Initializer

Usage:
  $(basename "$0") [OPTIONS]

Options:
  --path PATH     Key file path (default: $KEY_PATH_DEFAULT)
  --force         Overwrite existing key file (rotate)
  --check         Validate key file and exit
  --quiet         Suppress non-error output
  -h, --help      Show this help and exit

Notes:
  - Creates ~/.ssh with 700 permissions.
  - Creates key file with 600 permissions.
  - Requires Python and cryptography to be available in the current environment.
EOF
}

python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  return 1
}

key_path="$KEY_PATH_DEFAULT"
force=0
check_only=0
quiet=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path)
      if [[ $# -lt 2 ]]; then
        echo "Error: --path requires a value" >&2
        exit 2
      fi
      key_path="$2"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    --check)
      check_only=1
      shift
      ;;
    --quiet)
      quiet=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option '$1'" >&2
      usage >&2
      exit 2
      ;;
  esac
done

py="$(python_cmd)" || { echo "Error: python3/python not found in PATH" >&2; exit 1; }

ssh_dir="$(dirname "$key_path")"
mkdir -p "$ssh_dir"
chmod 700 "$ssh_dir" >/dev/null 2>&1 || true

validate_key() {
  "$py" - <<PY
from __future__ import annotations
from cryptography.fernet import Fernet
import pathlib
p = pathlib.Path(r"$key_path")
key = p.read_text(encoding="utf-8").strip()
Fernet(key.encode("utf-8"))
print("OK")
PY
}

if [[ -f "$key_path" ]]; then
  if [[ $check_only -eq 1 ]]; then
    validate_key >/dev/null
    if [[ $quiet -eq 0 ]]; then
      echo "Secret key valid: $key_path"
    fi
    exit 0
  fi

  if [[ $force -eq 0 ]]; then
    validate_key >/dev/null
    if [[ $quiet -eq 0 ]]; then
      echo "Secret key already exists (valid): $key_path"
    fi
    exit 0
  fi
fi

if [[ $check_only -eq 1 ]]; then
  echo "Error: key file does not exist: $key_path" >&2
  exit 1
fi

umask 077

tmp="$(mktemp "${key_path}.tmp.XXXXXX")"
"$py" - <<PY > "$tmp"
from __future__ import annotations
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode("utf-8"))
PY

chmod 600 "$tmp" >/dev/null 2>&1 || true
mv -f "$tmp" "$key_path"
chmod 600 "$key_path" >/dev/null 2>&1 || true

validate_key >/dev/null

if [[ $quiet -eq 0 ]]; then
  echo "Secret key created: $key_path"
fi
