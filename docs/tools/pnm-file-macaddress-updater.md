# PNM Tools - PNM MAC Address Rewriter

Rewrite Embedded MAC Addresses In PNM Capture Files For Testing And Sharing.

## Overview

The `pnm-mac-updater.py` helper script rewrites the MAC address embedded inside PNM capture files produced by DOCSIS
Proactive Network Maintenance (PNM) tests. It is intended for two primary use cases:

1. Anonymizing real capture data before sharing (for example, attaching to a bug report or uploading to a public repo).
2. Normalizing legacy test files so they all use the same synthetic MAC during regression testing.

The script never relies on the filename to infer the MAC address. Instead, it:

- Parses the PNM header to determine the file type.
- Instantiates the appropriate PNM parser (for example, RxMER, Spectrum Analysis).
- Asks the parser for the MAC address (when available).
- Searches the raw byte stream for that MAC and rewrites it in-place.

All non-MAC data in the file is preserved exactly as-is.

## Script Location

The script lives in the tools directory of the PyPNM repo:

- Script: [`tools/pnm/pnm-mac-updater.py`](http://github.com/svdleer/PyPNM/blob/main/tools/pnm/pnm-mac-updater.py)

It assumes PyPNM is installed in editable/development mode so it can import the internal PNM parsers and enums.

## Safety And Behavior

- Only files that the PNM parser can successfully classify *and* that expose a MAC address are rewritten.
- SNMP amplitude-data pseudo-files (for example, `spectrum_analyzer_snmp_amp_data_*.bin`) are skipped:
  - They are detected by filename pattern and never modified.
- For each supported file, the script:
  - Locates the MAC bytes once.
  - Validates that the offset is inside the file.
  - Overwrites exactly 6 bytes with the new MAC value.
- If anything looks wrong (parse failure, missing MAC, offset out of range), the file is left untouched and an error is
  logged.

To inspect what the script sees without modifying anything, use `--show-info` or `--dry-run`.

## CLI Summary

```bash
tools/pnm/pnm-mac-updater.py [OPTIONS]
```

### Key Options

- `--mac-address <mac>`  
  New MAC address to write (for example, `aa:bb:cc:dd:ee:ff`). Required for rewrite operations.

- `--file <path>`  
  Rewrite a single PNM file.

- `--all-files <directory>`  
  Rewrite all PNM files under a directory (recursively). Hidden files and directories are ignored.

- `--only-types <PNM_TYPE ...>`  
  Restrict processing to specific `PnmFileType` names (for example, `RECEIVE_MODULATION_ERROR_RATIO`,
  `SPECTRUM_ANALYSIS`).

- `--show-info`  
  Do not change any files. For each discoverable PNM file, print the type and the current MAC address.

- `--dry-run`  
  Show what *would* be changed (including offsets) but do not write any files.

- `--list-types`  
  List all known `PnmFileType` enum values and their PNN/LLD codes, then exit.

- `--verbose`  
  Enable verbose logging (DEBUG level).

## Argument Reference

| Option                | Required | Description                                                                                             |
|-----------------------|----------|---------------------------------------------------------------------------------------------------------|
| `--mac-address`       | Yes (rewrite) / No (show/list) | New MAC address to apply, in any common format (colon, hyphen, Cisco, or flat hex).                |
| `--file`              | No       | Path to a single PNM file to inspect or rewrite.                                                        |
| `--all-files`         | No       | Directory root to search recursively for PNM files; hidden paths are ignored.                          |
| `--only-types`        | No       | One or more `PnmFileType` names used to filter which files are processed.                              |
| `--show-info`         | No       | Inspect mode: show PNM type and MAC for each file; never modifies files.                               |
| `--dry-run`           | No       | Simulation mode: log every planned change, including byte offset, without writing to disk.             |
| `--list-types`        | No       | Print the list of known PNM file types and exit (no input files needed).                               |
| `--verbose`           | No       | Enable verbose logging to help troubleshoot parser issues or understand why a file was skipped.        |

`--file` and `--all-files` are mutually exclusive. At least one of them is required for inspection or rewrite
operations.

## Examples

### Show Detected MAC Addresses For A Directory

Inspect all PNM captures under `.data/pnm` without changing anything:

```bash
tools/pnm/pnm-mac-updater.py   --show-info   --all-files .data/pnm
```

Typical output:

```text
.data/pnm/ds_ofdm_rxmer_per_subcar_0050f1120360_193_1764694042.bin: RECEIVE_MODULATION_ERROR_RATIO(PNN4) mac_address=aa:bb:cc:dd:ee:ff
.data/pnm/spectrum_analyzer_0050f1120360_0_1764630868.bin: SPECTRUM_ANALYSIS(PNN9) mac_address=aa:bb:cc:dd:ee:ff
```

SNMP amplitude-data files (for example, `spectrum_analyzer_snmp_amp_data_*.bin`) will be logged and skipped.

### List Supported PNM File Types

To see all known `PnmFileType` names and their codes:

```bash
tools/pnm/pnm-mac-updater.py --list-types
```

Example (truncated):

```text
Available PNM file types:
  SYMBOL_CAPTURE                                  PNN1
  OFDM_CHANNEL_ESTIMATE_COEFFICIENT               PNN2
  DOWNSTREAM_CONSTELLATION_DISPLAY                PNN3
  RECEIVE_MODULATION_ERROR_RATIO                  PNN4
  ...
```

Use these names with `--only-types`.

### Anonymize Only RxMER And Spectrum Analyzer Files

Rewrite only RxMER (PNN4) and Spectrum Analysis (PNN9) PNM files in `.data/pnm`, but first do a dry-run so you can
verify offsets and planned changes:

```bash
tools/pnm/pnm-mac-updater.py   --mac-address aa:bb:cc:dd:ee:ff   --all-files .data/pnm   --only-types RECEIVE_MODULATION_ERROR_RATIO SPECTRUM_ANALYSIS   --dry-run
```

Example output:

```text
[DRY-RUN] .data/pnm/ds_ofdm_rxmer_per_subcar_0050f1120360_193_1764694042.bin: RECEIVE_MODULATION_ERROR_RATIO(PNN4) aa:bb:cc:dd:ee:ff -> aa:bb:cc:dd:ee:ff at offset 11
[DRY-RUN] .data/pnm/spectrum_analyzer_0050f1120360_0_1764630868.bin: SPECTRUM_ANALYSIS(PNN9) aa:bb:cc:dd:ee:ff -> aa:bb:cc:dd:ee:ff at offset 11
[DRY-RUN] Files that would be updated: 16
```

If everything looks correct, run the same command without `--dry-run`:

```bash
tools/pnm/pnm-mac-updater.py   --mac-address aa:bb:cc:dd:ee:ff   --all-files .data/pnm   --only-types RECEIVE_MODULATION_ERROR_RATIO SPECTRUM_ANALYSIS
```

### Anonymize All Discoverable PNM Files In A Tree

In a test environment, you may want to normalize all captures under a root directory to a known synthetic MAC
(for example, `de:ad:be:ef:00:bb`):

```bash
tools/pnm/pnm-mac-updater.py   --mac-address de:ad:be:ef:00:bb   --all-files .data/pnm
```

Any file for which the parser cannot determine a type or MAC (including unsupported PNM types) will be skipped and
logged.

### Rewrite A Single File

To rewrite the MAC address in one specific PNM capture file:

```bash
tools/pnm/pnm-mac-updater.py   --mac-address aa:bb:cc:dd:ee:ff   --file .data/pnm/ds_ofdm_rxmer_per_subcar_0050f1120360_193_1764694042.bin
```

You can combine `--file` with `--dry-run` to verify the change before actually writing it.

## PNM File Types And Filtering

The script uses the `PnmFileType` enum to classify PNM captures and optionally filter them with `--only-types`.

| Enum Name                                      | Code   | Description                                      |
|-----------------------------------------------|--------|--------------------------------------------------|
| `SYMBOL_CAPTURE`                              | PNN1   | Downstream OFDM symbol capture (not implemented) |
| `OFDM_CHANNEL_ESTIMATE_COEFFICIENT`           | PNN2   | Downstream OFDM channel estimate coefficients    |
| `DOWNSTREAM_CONSTELLATION_DISPLAY`            | PNN3   | Downstream OFDM constellation display            |
| `RECEIVE_MODULATION_ERROR_RATIO`              | PNN4   | Downstream OFDM RxMER per subcarrier            |
| `DOWNSTREAM_HISTOGRAM`                        | PNN5   | Downstream histogram                             |
| `UPSTREAM_PRE_EQUALIZER_COEFFICIENTS`         | PNN6   | Upstream OFDMA pre-equalizer coefficients        |
| `UPSTREAM_PRE_EQUALIZER_COEFFICIENTS_LAST_UPDATE` | PNN7 | Upstream pre-equalizer last-update snapshot      |
| `OFDM_FEC_SUMMARY`                            | PNN8   | Downstream OFDM FEC summary                      |
| `SPECTRUM_ANALYSIS`                           | PNN9   | Downstream spectrum analysis (DOCSIS PNM)        |
| `OFDM_MODULATION_PROFILE`                     | PNN10  | Downstream OFDM modulation profile               |
| `LATENCY_REPORT`                              | LLD01  | Latency report                                   |
| `CM_SPECTRUM_ANALYSIS_SNMP_AMP_DATA`          | PXX9   | Internal SNMP amplitude-data pseudo-file         |

Notes:

- SNMP `CM_SPECTRUM_ANALYSIS_SNMP_AMP_DATA` entries are *not* true PNM binary captures. The script skips these files
  based on filename pattern and, when possible, by type.
- For new or experimental PNM file types, ensure the corresponding parser exposes a MAC address attribute (for example,
  `_mac_address` or `mac_address`) so the script can discover and rewrite it.

## Troubleshooting

- If a file does not appear in `--show-info` output, the PNM header may be malformed or the parser may not yet support
  that type.
- If `--dry-run` reports zero files, confirm that:
  - The directory path is correct and non-empty.
  - You did not over-filter with `--only-types`.
- Use `--verbose` to see detailed log messages, including parse failures and skip reasons.

