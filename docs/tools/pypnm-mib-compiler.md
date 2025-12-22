# PyPNM MIB Compiler

Command-Line Utility To Precompile SNMP OIDs Into A Python Dictionary.

## Purpose

Convert all MIB definitions in `mibs/` into a flat Python dictionary (`COMPILED_OIDS`) and write it to:

```
src/pypnm/snmp/compiled_oids.py
```

The file is overwritten on each run and includes a UTC timestamp. Precompiling avoids runtime MIB parsing, reduces startup latency, and improves stability.

## How It Works

1. Runs `snmptranslate -Tz` against local MIBs in `mibs/`.
2. Captures raw symbol→OID output.
3. Parses into a de-duplicated `{name: numeric_oid}` map.
4. Emits `compiled_oids.py` with the `COMPILED_OIDS` constant and a generated-on timestamp.

## Directory Structure

```
PyPNM/
├── mibs/                         # Input MIB files (.txt/.my)
├── src/pypnm/snmp/               # Target module
│   └── compiled_oids.py          # Auto-generated dictionary
└── tools/
    └── update_snmp_oid_dict.py   # Compiler script
```

## Prerequisites

### Python

* Python 3.6 or newer.

### Net-SNMP (`snmptranslate`)

Debian/Ubuntu:

```bash
sudo apt update && sudo apt install -y snmp snmp-mibs-downloader
```

RHEL/Fedora:

```bash
sudo dnf install -y net-snmp-utils
```

Verify:

```bash
which snmptranslate
snmptranslate -V
```

### curl (optional, for fetching MIBs)

```bash
sudo apt install -y curl
```

## Populate `mibs/` (Top Level Only)

Fetch current CableLabs DOCSIS MIBs into `mibs/` without descending into subdirectories (e.g., `archive/`):

```bash
curl -s https://mibs.cablelabs.com/MIBs/DOCSIS/ \
| grep -oP '(?<=href=")[^"/]+\.(my|txt)(?=")' \
| while read -r file; do
  wget -nc "https://mibs.cablelabs.com/MIBs/DOCSIS/$file" -P mibs/
done
```

> You may also place vendor/private MIBs in `mibs/`; they will be included automatically.

## Usage

From the repository root:

```bash
python3 tools/snmp/update-snmp-oid-dict.py
```

Example output:

```
Generating compiled OIDs from MIBs...
Compiled 782 OIDs to src/pypnm/snmp/compiled_oids.py
```

## Output Format

`compiled_oids.py` contains a single map with a timestamp header:

```python
# Auto-generated OID dictionary from snmptranslate -Tz
# Do not modify manually. Generated on: 2025-07-06T20:15:45.123456Z

COMPILED_OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1",
    "docsIf3CmtsCmUsStatusRxPower": "1.3.6.1.4.1.1166.1.19.2.3.1.6",
    ...
}
```

## Verifying The Result

Quick sanity checks:

```bash
python3 - <<'PY'
from src.pypnm.snmp.compiled_oids import COMPILED_OIDS
assert "sysDescr" in COMPILED_OIDS
assert COMPILED_OIDS["sysDescr"].startswith(("1.", ".1."))
print(f"OK: {len(COMPILED_OIDS)} OIDs loaded")
PY
```

Optional cross-check with `snmptranslate`:

```bash
snmptranslate -On sysDescr
# Expect: .1.3.6.1.2.1.1.1
```

## Environment & Options

If your `snmptranslate` environment requires explicit MIB paths, set:

```bash
export MIBDIRS=./mibs
export MIBS=+ALL
```

For vendor MIBs in additional directories:

```bash
export MIBDIRS="./mibs:/opt/vendor/mibs"
```

> The compiler script prefers local `mibs/` and does not need system-wide MIBs when your set is complete.

## Troubleshooting

* **`snmptranslate: cannot find module`**
  Ensure files exist in `mibs/`, and set `MIBDIRS=./mibs` and `MIBS=+ALL`.

* **Zero OIDs compiled**
  Check tool output for errors; confirm `snmptranslate -Tz` runs successfully on your host.

* **Name collisions**
  If different MIBs export the same symbol, the last win applies. Prefer authoritative MIBs in `mibs/` and remove stale/duplicate vendor variants.

* **Non-DOCSIS environments**
  The compiler is generic; place any MIB set into `mibs/` to generate a unified dictionary.

## Notes

* `compiled_oids.py` is generated; do not edit manually.
* Re-run the compiler after adding or updating MIB files to refresh the dictionary.
