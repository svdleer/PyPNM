#!/usr/bin/env bash
# run_all_py_with_cli.sh — Execute all Python scripts in a directory tree,
# passing --mac and --inet flags through to each script.

set -euo pipefail

# Default scan directory
DIR="."

# Parse command-line flags
CM_MAC=""
CM_IP=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mac)
      CM_MAC="$2"
      shift 2
      ;;
    --inet)
      CM_IP="$2"
      shift 2
      ;;
    *)
      # if it's a directory, treat it as the scan root
      if [[ -d "$1" ]]; then
        DIR="$1"
        shift
      else
        echo "Unknown argument or non-existent directory: $1" >&2
        echo "Usage: $0 --mac <MAC_ADDRESS> --inet <IP_ADDRESS> [directory]" >&2
        exit 1
      fi
      ;;
  esac
done

# Validate that required flags were provided
if [[ -z "$CM_MAC" || -z "$CM_IP" ]]; then
  echo "Error: both --mac and --inet must be provided" >&2
  echo "Usage: $0 --mac <MAC_ADDRESS> --inet <IP_ADDRESS> [directory]" >&2
  exit 1
fi

echo "Scanning Python files under: ${DIR}"
echo "Passing to scripts: --mac ${CM_MAC} --inet ${CM_IP}"
echo

# Find and execute each .py file
find "${DIR}" -type f -name '*.py' -print0 | while IFS= read -r -d '' script; do
    echo "=== Running: ${script} --mac ${CM_MAC} --inet ${CM_IP} ==="
    python3 "${script}" --mac "${CM_MAC}" --inet "${CM_IP}"
    echo
done

echo "All done."
