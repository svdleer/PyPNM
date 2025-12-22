#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

"""
# Clear all data
# ./tools/clean --all

# Restore from backup folder:
mkdocs.yml
src/pypnm/cli.py
src/pypnm/settings/system.json

# Will need to cause a webservice restart afterward

Factory reset and data cleanup helper for PyPNM.

This tool supports:
- Clearing runtime and cache data (logs, output, build/test artifacts).
- Restoring baseline configuration files from the backup folder created by install.sh.
- Performing both steps together as a full "factory reset" operation.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Final, Iterable


PROJECT_ROOT: Final[Path]     = Path(__file__).resolve().parent.parent
BACKUP_ROOT: Final[Path]      = PROJECT_ROOT / "backup"

BACKUP_RELATIVE_PATHS: Final[tuple[Path, ...]] = (
    Path("mkdocs.yml"),
    Path("src/pypnm/cli.py"),
    Path("src/pypnm/settings/system.json"),
)

DATA_RELATIVE_PATHS: Final[tuple[Path, ...]] = (
    Path("logs"),
    Path("output"),
    Path(".pytest_cache"),
    Path(".mypy_cache"),
    Path(".coverage"),
    Path("site"),
)


class FactoryResetTool:
    """
    Factory reset utility for PyPNM.

    This helper coordinates three primary operations:
      1. Clearing runtime and cache data directories.
      2. Restoring configuration and project files from the backup folder.
      3. Combining both into a full "factory reset" sequence.

    The backup folder is expected to be created by the install.sh bootstrap script:

      backup/
        mkdocs.yml
        src/pypnm/cli.py
        src/pypnm/settings/system.json

    All paths are resolved relative to the project root inferred from this script's
    location (two levels above tools/clean.py).
    """

    @staticmethod
    def clear_data(project_root: Path, targets: Iterable[Path], dry_run: bool) -> None:
        """
        Remove runtime and cache data under the given project root.

        Parameters
        ----------
        project_root:
            Resolved path to the PyPNM repository root.
        targets:
            Iterable of paths relative to project_root representing directories or
            files that should be removed for a clean "data reset".
        dry_run:
            When True, only print planned deletions without modifying the filesystem.
        """
        for rel_path in targets:
            abs_path = project_root / rel_path
            if abs_path.is_dir():
                print(f"Would remove directory: {abs_path}" if dry_run else f"Removing directory: {abs_path}")
                if not dry_run:
                    shutil.rmtree(abs_path, ignore_errors=True)
            elif abs_path.is_file():
                print(f"Would remove file:      {abs_path}" if dry_run else f"Removing file:      {abs_path}")
                if not dry_run:
                    abs_path.unlink(missing_ok=True)
            else:
                print(f"Skipping non-existent path: {abs_path}")

    @staticmethod
    def restore_from_backup(project_root: Path, backup_root: Path, rel_paths: Iterable[Path], dry_run: bool) -> None:
        """
        Restore baseline files from the backup folder into the project root.

        Parameters
        ----------
        project_root:
            Resolved path to the PyPNM repository root.
        backup_root:
            Root directory where baseline backup files are stored.
        rel_paths:
            Iterable of project-relative paths to restore (both source and target
            share the same relative layout under backup_root and project_root).
        dry_run:
            When True, only print planned copies without modifying the filesystem.
        """
        for rel_path in rel_paths:
            src = backup_root / rel_path
            dst = project_root / rel_path

            if not src.exists():
                print(f"Backup missing for {rel_path}: expected at {src}, skipping.")
                continue

            print(f"Would restore {src} -> {dst}" if dry_run else f"Restoring {src} -> {dst}")
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    @staticmethod
    def confirm(prompt: str) -> bool:
        """
        Prompt the user for confirmation before performing a destructive operation.

        Parameters
        ----------
        prompt:
            Human-readable message describing the pending action.

        Returns
        -------
        bool
            True if the user explicitly confirms with 'y' or 'yes' (case-insensitive),
            False otherwise.
        """
        try:
            answer = input(f"{prompt} [y/N]: ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")


def main() -> None:
    """
    Entry point for the PyPNM factory reset and cleanup CLI.

    Modes
    -----
    --all
        Perform a full factory reset:
          * Clear runtime/cache data (logs, output, caches).
          * Restore baseline files from the backup folder.

    --clear-data
        Clear runtime/cache data only, without restoring files from backup.

    --restore
        Restore baseline files from backup only, without clearing data.

    Common Options
    --------------
    --dry-run
        Show planned actions but do not modify the filesystem.

    Examples
    --------
    # Full factory reset: clear data and restore baseline config
    ./tools/clean --all

    # Inspect what would be done without changing anything
    ./tools/clean --all --dry-run

    # Only clear runtime data
    ./tools/clean --clear-data

    # Only restore from backup
    ./tools/clean --restore
    """
    parser = argparse.ArgumentParser(
        description="PyPNM factory reset and data cleanup tool (uses backup created by install.sh)."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Perform a full factory reset: clear data and restore files from backup.",
    )
    parser.add_argument(
        "--clear-data",
        action="store_true",
        help="Clear runtime and cache data only (logs, output, caches).",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore baseline files from backup only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without modifying the filesystem.",
    )

    args = parser.parse_args()
    do_all: bool        = args.all
    do_clear: bool      = args.clear_data
    do_restore: bool    = args.restore
    dry_run: bool       = args.dry_run

    if not (do_all or do_clear or do_restore):
        parser.error("You must specify at least one of --all, --clear-data, or --restore.")

    if do_all:
        if not dry_run:
            confirmed = FactoryResetTool.confirm(
                "This will clear runtime data and restore baseline configuration from backup."
            )
            if not confirmed:
                print("Aborted: factory reset was not confirmed.")
                sys.exit(1)

        print("Clearing runtime and cache data...")
        FactoryResetTool.clear_data(PROJECT_ROOT, DATA_RELATIVE_PATHS, dry_run=dry_run)

        print("Restoring baseline files from backup...")
        FactoryResetTool.restore_from_backup(PROJECT_ROOT, BACKUP_ROOT, BACKUP_RELATIVE_PATHS, dry_run=dry_run)
        print("Factory reset sequence complete." if not dry_run else "Dry-run: factory reset actions listed above.")
        return

    if do_clear:
        if not dry_run:
            confirmed = FactoryResetTool.confirm("This will clear runtime and cache data for PyPNM.")
            if not confirmed:
                print("Aborted: data cleanup was not confirmed.")
                sys.exit(1)

        print("Clearing runtime and cache data...")
        FactoryResetTool.clear_data(PROJECT_ROOT, DATA_RELATIVE_PATHS, dry_run=dry_run)
        print("Data cleanup complete." if not dry_run else "Dry-run: data cleanup actions listed above.")

    if do_restore:
        if not dry_run:
            confirmed = FactoryResetTool.confirm(
                "This will overwrite selected files with versions from the backup folder."
            )
            if not confirmed:
                print("Aborted: restore was not confirmed.")
                sys.exit(1)

        print("Restoring baseline files from backup...")
        FactoryResetTool.restore_from_backup(PROJECT_ROOT, BACKUP_ROOT, BACKUP_RELATIVE_PATHS, dry_run=dry_run)
        print("Restore complete." if not dry_run else "Dry-run: restore actions listed above.")


if __name__ == "__main__":
    main()
