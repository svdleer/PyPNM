# Python API

Use these guides when you are importing PyPNM modules directly in Python scripts, notebooks, or back-end jobs.

> **Before you start**
> - Install PyPNM in a virtual environment (`pip install -e .[dev,docs]` or `pip install pypnm-docsis`) so the modules below resolve.
> - Most helpers live under `pypnm.snmp.*` and `pypnm.pnm.*`. Check each guide for exact import paths and example snippets.
> - Configuration-sensitive modules (for example, PNM parsers that read `.data/` paths) expect `system.json` to be populated. See the [system configuration reference](../../system/system-config.md).

## Pick a guide

| Section | When to use it |
|---------|----------------|
| [SNMP](snmp/index.md) | Asynchronous SNMP client helpers for GET/WALK/SET and MIB handling. |
| [PNM](pnm/index.md) | Binary decoders, signal-processing helpers, and diagnostics for DOCSIS PNM data. |
