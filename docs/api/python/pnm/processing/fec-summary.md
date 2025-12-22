# CmDsOfdmFecSummary — downstream OFDM FEC summary

Parser and helper for DOCSIS downstream OFDM forward error correction (FEC) summary records.

> **Module location**
> `src/pypnm/pnm/parser/CmDsOfdmFecSummary.py`

## Inputs

- Raw binary payload captured via the FEC summary endpoint.
- Optional scaling/rounding parameters (defaults match CableLabs specs).

## Outputs

`CmDsOfdmFecSummaryModel` provides:

- `header`: capture metadata (timestamp, profile ID, codeword counts).
- `summary`: per-profile counters for corrected/uncorrectables, codeword totals, and error ratios.

## Usage

```python
from pathlib import Path
from pypnm.pnm.parser.CmDsOfdmFecSummary import CmDsOfdmFecSummary

payload = Path("fec_summary.bin").read_bytes()
fec = CmDsOfdmFecSummary(payload)

summary = fec.get_summary()
```
