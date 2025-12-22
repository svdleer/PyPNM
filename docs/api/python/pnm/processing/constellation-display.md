# CmDsOfdmConstellationDisplay — downstream OFDM constellation display

Parser and helper for DOCSIS downstream OFDM constellation snapshots captured in the CmDsOfdmConstellationDisplay PNM format.

> **Module location**
> `src/pypnm/pnm/parser/CmDsOfdmConstellationDisplay.py`

## Inputs

- Binary payload produced by the cable modem when requesting a constellation display capture (see FastAPI single-capture guide).
- Optional `DecimalPrecision` parameters to control rounding when exposing values.

## Outputs

`CmDsOfdmConstellationDisplayModel` exposes:

- `header`: metadata (capture time, modulation profile, etc.).
- `points`: list of `[real, imag]` coordinates per subcarrier.
- `dimensions`: axes scaling for plotting helpers.

## Usage

```python
from pathlib import Path
from pypnm.pnm.parser.CmDsOfdmConstellationDisplay import CmDsOfdmConstellationDisplay

payload = Path("constellation.bin").read_bytes()
constellation = CmDsOfdmConstellationDisplay(payload)

points = constellation.get_points()  # [[real, imag], ...]
header = constellation.get_header()
```
