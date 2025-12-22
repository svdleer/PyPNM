#!/usr/bin/env python3
from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

import argparse
import logging
import sys
from pathlib import Path
from typing import Final, Iterable, Iterator, Sequence

from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import MacAddressStr, PathLike
from pypnm.pnm.parser.fetch_pnm_process import PnmFileTypeObjectFetcher
from pypnm.pnm.parser.pnm_file_type import PnmFileType

LOG: Final[logging.Logger] = logging.getLogger("pnm-mac-rewriter")
MAC_BYTES_LEN: Final[int] = 6


# ────────────────────────────────────────────────────────────────────────────────
# Logging / file discovery
# ────────────────────────────────────────────────────────────────────────────────

def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def _iter_files_from_root(root: Path) -> Iterator[Path]:
    """
    Yield all non-hidden regular files under root.

    Hidden *files* (name starting with '.') are skipped.
    Directories named with a leading '.' (e.g. .data, .git) are allowed,
    so that .data/pnm/... PNM captures are still processed.
    """
    if root.is_file():
        if not root.name.startswith("."):
            yield root
        return

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Skip only hidden files, not paths whose parents are hidden
        if path.name.startswith("."):
            continue
        yield path


def _is_amp_data_by_name(path: Path) -> bool:
    """
    Quick guard to skip SNMP AMP_DATA PNM files by filename pattern.

    These are not true PNM capture binaries and do not contain a MAC at
    the expected location, so they are excluded from rewriting.
    """
    name = path.name.lower()
    return "amp_data" in name or "spectrum_analyzer_snmp_amp_data" in name


# ────────────────────────────────────────────────────────────────────────────────
# PNM parsing and MAC extraction
# ────────────────────────────────────────────────────────────────────────────────

def _parse_pnm_and_mac(path: Path, data: bytes) -> tuple[PnmFileType, MacAddress, int] | None:
    """
    Parse a PNM file, obtain its type and MAC address from the parser,
    then locate the MAC bytes within the raw byte stream.

    Returns
    -------
    (pnm_type, mac, offset) or None if unable to extract.
    """
    try:
        fetcher = PnmFileTypeObjectFetcher(data)
        parser = fetcher.get_parser()
        pnm_type = fetcher.get_pnm_file_type()
    except Exception as exc:
        LOG.error("Failed to parse PNM file '%s': %s", path, exc)
        return None

    if pnm_type is None:
        LOG.error("Unknown PNM file type for '%s'", path)
        return None

    # Skip SNMP AMP_DATA PNM pseudo-files by type, just in case
    if pnm_type == PnmFileType.CM_SPECTRUM_ANALYSIS_SNMP_AMP_DATA:
        LOG.info("Skipping SNMP AMP_DATA file by type: %s", path)
        return None

    # Try both _mac_address and mac_address attributes, depending on parser style
    raw_mac: MacAddressStr | str | None = None
    if hasattr(parser, "_mac_address"):
        raw_mac = getattr(parser, "_mac_address")
    elif hasattr(parser, "mac_address"):
        raw_mac = getattr(parser, "mac_address")

    if not raw_mac:
        LOG.error("Parser for '%s' (type=%s) did not expose a MAC address", path, pnm_type.name)
        return None

    try:
        mac = MacAddress(str(raw_mac))
    except Exception as exc:
        LOG.error("Failed to normalize MAC for '%s': %s", path, exc)
        return None

    mac_bytes = mac.to_bytes()
    idx = data.find(mac_bytes)
    if idx < 0:
        LOG.error(
            "Could not locate MAC bytes in '%s' for type=%s (MAC=%s)",
            path,
            pnm_type.name,
            str(mac),
        )
        return None

    return pnm_type, mac, idx


def _iter_candidate_files(
    files: Iterable[Path],
    only_types: set[PnmFileType] | None,
) -> Iterator[tuple[Path, PnmFileType, MacAddress, int]]:
    """
    Iterate over files, yielding those for which we can determine a MAC
    and its byte offset.

    Files may be filtered by PnmFileType via only_types.
    """
    for path in files:
        if _is_amp_data_by_name(path):
            LOG.info("Skipping SNMP AMP_DATA file by name: %s", path)
            continue

        try:
            data = path.read_bytes()
        except OSError as exc:
            LOG.error("Failed to read '%s': %s", path, exc)
            continue

        parsed = _parse_pnm_and_mac(path, data)
        if parsed is None:
            continue

        pnm_type, mac, offset = parsed

        if only_types is not None and pnm_type not in only_types:
            continue

        yield path, pnm_type, mac, offset


# ────────────────────────────────────────────────────────────────────────────────
# Info + rewrite operations
# ────────────────────────────────────────────────────────────────────────────────

def _show_info(
    files: Iterable[Path],
    only_types: set[PnmFileType] | None,
) -> None:
    """
    Print summary lines for each PNM file we can parse, showing type and MAC.
    """
    for path, pnm_type, mac, _offset in _iter_candidate_files(files, only_types):
        print(f"{path}: {pnm_type.name}({pnm_type.value}) mac_address={str(mac)}")


def _rewrite_mac_candidates(
    candidates: Iterable[tuple[Path, PnmFileType, MacAddress, int]],
    new_mac: MacAddress,
    dry_run: bool,
) -> int:
    """
    Given a set of (path, type, old_mac, offset) candidates, rewrite the MAC
    at the discovered byte offset for each file.

    Returns
    -------
    int
        Number of files successfully updated (or that would be updated in dry-run).
    """
    changed_count = 0
    new_mac_bytes = new_mac.to_bytes()

    for path, pnm_type, old_mac, offset in candidates:
        try:
            data = path.read_bytes()
        except OSError as exc:
            LOG.error("Failed to read '%s' for rewrite: %s", path, exc)
            continue

        if len(data) < offset + MAC_BYTES_LEN:
            LOG.error(
                "Refusing to rewrite '%s': computed MAC offset %d is out of bounds "
                "(file size=%d)",
                path,
                offset,
                len(data),
            )
            continue

        # Sanity check: ensure what we think is the old MAC is actually there
        old_bytes = old_mac.to_bytes()
        if data[offset : offset + MAC_BYTES_LEN] != old_bytes:
            LOG.error(
                "MAC mismatch at offset %d in '%s': expected %s, found %s; skipping.",
                offset,
                path,
                old_bytes.hex(":"),
                data[offset : offset + MAC_BYTES_LEN].hex(":"),
            )
            continue

        if dry_run:
            print(
                f"[DRY-RUN] {path}: {pnm_type.name}({pnm_type.value}) "
                f"{str(old_mac)} -> {str(new_mac)} at offset {offset}"
            )
            changed_count = changed_count + 1
            continue

        new_bytes = bytearray(data)
        new_bytes[offset : offset + MAC_BYTES_LEN] = new_mac_bytes

        try:
            path.write_bytes(new_bytes)
        except OSError as exc:
            LOG.error("Failed to write updated file '%s': %s", path, exc)
            continue

        print(
            f"Updated {path}: {pnm_type.name}({pnm_type.value}) "
            f"{str(old_mac)} -> {str(new_mac)} at offset {offset}"
        )
        changed_count = changed_count + 1

    return changed_count


# ────────────────────────────────────────────────────────────────────────────────
# Type helpers / CLI
# ────────────────────────────────────────────────────────────────────────────────

def _parse_only_types(names: Sequence[str] | None) -> set[PnmFileType] | None:
    """
    Convert a sequence of PnmFileType enum names into a set.

    Returns None if names is None or empty.
    """
    if not names:
        return None

    out: set[PnmFileType] = set()
    for name in names:
        try:
            out.add(PnmFileType[name])
        except KeyError:
            valid = ", ".join(t.name for t in PnmFileType)
            print(
                f"ERROR: Invalid PNM type name '{name}'. Valid names: {valid}",
                file=sys.stderr,
            )
            sys.exit(1)
    return out


def _list_types() -> None:
    """
    Print available PnmFileType enum members and their codes.
    """
    print("Available PNM file types:")
    for t in PnmFileType:
        print(f"  {t.name:<45} {t.value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite the MAC address embedded in PNM capture files. "
            "MAC is discovered via PNM parser and located in the raw bytes; "
            "filenames are NOT used to infer or confirm MAC values."
        )
    )
    parser.add_argument(
        "--mac-address",
        help="New MAC address to write (e.g. aa:bb:cc:dd:ee:ff). "
             "Required unless using --show-info or --list-types.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--file",
        type=str,
        help="Single PNM file to process.",
    )
    group.add_argument(
        "--all-files",
        type=str,
        help="Process all PNM files under the given directory (recursively).",
    )
    parser.add_argument(
        "--only-types",
        nargs="+",
        metavar="PNM_TYPE",
        help=(
            "Restrict processing to specific PnmFileType names "
            "(e.g. RECEIVE_MODULATION_ERROR_RATIO SPECTRUM_ANALYSIS)."
        ),
    )
    parser.add_argument(
        "--show-info",
        action="store_true",
        help="Do not modify any files; only show detected PNM type and MAC.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed but do not write any files.",
    )
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="List known PNM file types and exit.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )

    args = parser.parse_args()
    _configure_logging(args.verbose)

    if args.list_types:
        _list_types()
        return

    # Determine target files
    targets: list[Path] = []
    if args.file:
        targets = [Path(args.file)]
    elif args.all_files:
        root = Path(args.all_files)
        if not root.exists():
            print(f"ERROR: Path does not exist: {root}", file=sys.stderr)
            sys.exit(1)
        targets = list(_iter_files_from_root(root))
    else:
        if not args.show_info:
            print(
                "ERROR: You must specify either --file or --all-files when rewriting MACs.\n"
                "       Or use --show-info with one of those to inspect without modifying.",
                file=sys.stderr,
            )
        else:
            print(
                "ERROR: --show-info requires either --file or --all-files to specify input files.",
                file=sys.stderr,
            )
        sys.exit(1)

    only_types = _parse_only_types(args.only_types)

    # Show-info mode: no mac-address required, no writes.
    if args.show_info:
        _show_info(targets, only_types)
        return

    # Rewrite mode: require mac-address.
    if not args.mac_address:
        print(
            "ERROR: --mac-address is required when not using --show-info or --list-types.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        new_mac = MacAddress(args.mac_address)
    except Exception as exc:
        print(f"ERROR: Invalid --mac-address '{args.mac_address}': {exc}", file=sys.stderr)
        sys.exit(1)

    # Discover all candidates *once* using the same logic as --show-info
    candidates = list(_iter_candidate_files(targets, only_types))

    if not candidates:
        print("No PNM files with a discoverable MAC/address offset were found for the given inputs.")
        print("Hint: run again with --show-info to see what the parser can detect.")
        sys.exit(0)

    changed_count = _rewrite_mac_candidates(candidates, new_mac, args.dry_run)

    if args.dry_run:
        print(f"[DRY-RUN] Files that would be updated: {changed_count}")
    else:
        print(f"Files updated: {changed_count}")


if __name__ == "__main__":
    main()
