#!/usr/bin/env bash
# Backup or restore the .data directory.
# Place this file at: tools/backup_data.sh
#
# Usage:
#   ./tools/backup_data.sh backup
#   ./tools/backup_data.sh restore
#
# The backup files are stored in the "backup" directory at the project root.

set -euo pipefail

#######################################
# Setup paths
#######################################
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

DATA_DIR="${PROJECT_ROOT}/.data"
BACKUP_DIR="${PROJECT_ROOT}/backup"

MD5_MANIFEST="${BACKUP_DIR}/md5sum.txt"

#######################################
# Helper: Ensure backup directory exists
#######################################
ensure_backup_dir() {
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        echo "Creating backup directory at: ${BACKUP_DIR}"
        mkdir -p "${BACKUP_DIR}"
    fi
}

#######################################
# Backup function
# Creates a timestamped tar.gz of the .data directory
# and updates md5sum.txt
#######################################
backup_data() {
    ensure_backup_dir

    if [[ ! -d "${DATA_DIR}" ]]; then
        echo "ERROR: ${DATA_DIR} does not exist. Nothing to back up."
        exit 1
    fi

    EPOCH_TS="$(date +%s)"
    ARCHIVE_NAME="data-backup-${EPOCH_TS}.tar.gz"
    ARCHIVE_PATH="${BACKUP_DIR}/${ARCHIVE_NAME}"

    echo "Creating backup archive: ${ARCHIVE_PATH}"
    tar -C "${PROJECT_ROOT}" -czf "${ARCHIVE_PATH}" ".data"

    echo "Updating MD5 manifest..."
    find "${BACKUP_DIR}" -maxdepth 1 -type f -name "*.tar.gz" -print0 \
      | sort -z \
      | xargs -0 md5sum > "${MD5_MANIFEST}"

    echo "Backup completed successfully."
    echo "Archive: ${ARCHIVE_PATH}"
    echo "Manifest: ${MD5_MANIFEST}"
}

#######################################
# Restore function
# Restores the most recent backup archive into .data,
# overwriting any existing files.
#######################################
restore_data() {
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        echo "ERROR: Backup directory not found at ${BACKUP_DIR}"
        exit 1
    fi

    LATEST_ARCHIVE=$(ls -t "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | head -n 1 || true)

    if [[ -z "${LATEST_ARCHIVE}" ]]; then
        echo "ERROR: No backup archives found in ${BACKUP_DIR}"
        exit 1
    fi

    echo "Restoring from archive: ${LATEST_ARCHIVE}"
    echo "This will overwrite the existing .data directory."

    # Remove old .data folder before restore
    if [[ -d "${DATA_DIR}" ]]; then
        echo "Removing existing .data directory..."
        rm -rf "${DATA_DIR}"
    fi

    echo "Extracting backup..."
    tar -C "${PROJECT_ROOT}" -xzf "${LATEST_ARCHIVE}"

    echo "Restore completed successfully."
}

#######################################
# CLI argument parsing
#######################################
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 {backup|restore}"
    exit 1
fi

ACTION="$1"

case "${ACTION}" in
    backup)
        backup_data
        ;;
    restore)
        restore_data
        ;;
    *)
        echo "Invalid action: ${ACTION}"
        echo "Usage: $0 {backup|restore}"
        exit 1
        ;;
esac
