#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Cleans logs, Python caches, build artifacts, PNM data, and output files.

set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Usage info
# -----------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] [ROOT_DIR]

Options:
  --all             Clean logs, Python cache, build artifacts, PNM data,
                    output, issues support bundles, settings backups, and
                    related artifacts
  --logs            Truncate logs/pypnm.log (preserve file and permissions)
  --python          Clean only Python caches (__pycache__, *.pyc, .pytest_cache, etc.)
  --build           Clean build/, dist/, *.egg-info
  --pnm             Clean .data/pnm/ and .data/db/
  --archive         Clean .data/archive/
  --excel           Clean .data/xlsx/ and .data/csv/
  --json            Clean .data/json/
  --plot-data       Clean .data/png/, .data/csv/ and .data/archive/
  --msg-rsp         Clean .data/msg_rsp (Message Response)
  --output          Clean output/
  --issues          Clean issues/ support bundles (preserve directory)
  --remove-issues   Remove the issues/ directory entirely
  --settings-backup Clean src/pypnm/settings/system.bak.*.json backup files
  -h, --help        Show this help and exit

ROOT_DIR defaults to the current directory if not provided.
EOF
  exit 1
}

# -----------------------------------------------------------------------------
# Defaults
# -----------------------------------------------------------------------------
ROOT_DIR="."
declare -a ACTIONS=()

# -----------------------------------------------------------------------------
# Parse args
# -----------------------------------------------------------------------------
while (( $# )); do
  case "$1" in
    --all|--logs|--python|--build|--pnm|--output|--plot-data|--msg-rsp|--archive|--excel|--json|--issues|--remove-issues|--settings-backup)
      ACTIONS+=("$1")
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      # assume anything else is the root directory
      ROOT_DIR="$1"
      shift
      ;;
  esac
done

if [[ ${#ACTIONS[@]} -eq 0 ]]; then
  usage
fi

# Canonicalize ROOT_DIR
ROOT_DIR=$(realpath "$ROOT_DIR")
echo "🔍 Cleaning in root directory: $ROOT_DIR"

# -----------------------------------------------------------------------------
# Helper: safe remove (handles multiple args)
# -----------------------------------------------------------------------------
safe_rm() {
  local path
  for path in "$@"; do
    if [[ -e $path || -L $path ]]; then
      rm -rf "$path"
      echo "🗑️  Removed: $path"
    fi
  done
}

# -----------------------------------------------------------------------------
# Individual “clean” functions
# -----------------------------------------------------------------------------
clean_logs() {
  echo "🧹 Cleaning logs (truncate, preserve files)..."

  local log_file="$ROOT_DIR/logs/pypnm.log"

  if [[ -f "$log_file" ]]; then
    : > "$log_file"   # truncate to zero bytes, keep permissions and inode
    echo "🧾 Truncated: $log_file"
  else
    echo "ℹ️  No log file found at: $log_file"
  fi
}

clean_archives() {
  echo "🧹 Cleaning archives..."
  safe_rm "$ROOT_DIR/.data/archive/"*
}

clean_python() {
  echo "🐍 Cleaning Python caches and test artifacts..."

  # Skip virtualenv directory (.env) while cleaning caches
  find "$ROOT_DIR" \
    -path "$ROOT_DIR/.env" -prune -o \
    -type d -name '__pycache__' -print -exec rm -rf {} +

  find "$ROOT_DIR" \
    -path "$ROOT_DIR/.env" -prune -o \
    -type f -name '*.pyc' -print -exec rm -f {} +

  # Common tool/test caches
  safe_rm \
    "$ROOT_DIR/.pytest_cache" \
    "$ROOT_DIR/.mypy_cache" \
    "$ROOT_DIR/.ruff_cache" \
    "$ROOT_DIR/.hypothesis" \
    "$ROOT_DIR/.coverage" \
    "$ROOT_DIR/coverage.xml"
}

clean_build() {
  echo "🏗️  Cleaning build artifacts..."
  safe_rm "$ROOT_DIR/build" "$ROOT_DIR/dist"

  # Top-level and src-level egg-info (e.g., src/pypnm.egg-info)
  safe_rm "$ROOT_DIR"/*.egg-info
  safe_rm "$ROOT_DIR/src"/*.egg-info
}

clean_pnm() {
  echo "📦 Cleaning PNM data..."
  safe_rm "$ROOT_DIR/.data/pnm/"*
  safe_rm "$ROOT_DIR/.data/db/"*
}

clean_excel() {
  echo "📊 Cleaning Excel/CSV data..."
  safe_rm "$ROOT_DIR/.data/xlsx/"*
  safe_rm "$ROOT_DIR/.data/csv/"*
}

clean_json() {
  echo "🧾 Cleaning JSON data..."
  safe_rm "$ROOT_DIR/.data/json/"*
}

clean_png() {
  echo "🖼️  Cleaning PNG data..."
  safe_rm "$ROOT_DIR/.data/png/"*
}

clean_output() {
  echo "📤 Cleaning output files..."
  safe_rm "$ROOT_DIR/output/"*
}

clean_plot_data() {
  echo "📈 Cleaning plot data and archive files..."
  safe_rm "$ROOT_DIR/.data/png/"*
  safe_rm "$ROOT_DIR/.data/csv/"*
  safe_rm "$ROOT_DIR/.data/archive/"*
}

clean_msg_rsp() {
  echo "📨 Cleaning message-response data..."
  safe_rm "$ROOT_DIR/.data/msg_rsp/"*
}

clean_issues() {
  echo "🧹 Cleaning issues support bundles (preserve directory)..."
  safe_rm "$ROOT_DIR/issues/"*
}

remove_issues_dir() {
  echo "🗑️  Removing issues directory..."
  safe_rm "$ROOT_DIR/issues"
}

clean_settings_backups() {
  echo "🧹 Cleaning system.json backup files..."
  # Only remove system.bak.*.json, leave system.json intact
  safe_rm "$ROOT_DIR/src/pypnm/settings"/system.bak.*.json
}

# -----------------------------------------------------------------------------
# Dispatch actions
# -----------------------------------------------------------------------------
for action in "${ACTIONS[@]}"; do
  case "$action" in

    --all)
      echo "🚀 Performing full cleanup..."
      clean_logs
      clean_archives
      clean_python
      clean_build
      clean_pnm
      clean_excel
      clean_json
      clean_output
      clean_png
      clean_plot_data
      clean_msg_rsp
      clean_issues
      clean_settings_backups
      ;;

    --archive)
      clean_archives
      ;;

    --logs)
      clean_logs
      ;;

    --python)
      clean_python
      ;;

    --build)
      clean_build
      ;;

    --pnm)
      clean_pnm
      ;;

    --excel)
      clean_excel
      ;;

    --json)
      clean_json
      ;;

    --plot-data)
      clean_plot_data
      ;;

    --msg-rsp)
      clean_msg_rsp
      ;;

    --output)
      clean_output
      ;;

    --issues)
      clean_issues
      ;;

    --remove-issues)
      remove_issues_dir
      ;;

    --settings-backup)
      clean_settings_backups
      ;;
  esac
done

echo "✅ Cleanup complete."
