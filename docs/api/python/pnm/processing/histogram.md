# CmDsOfdmHistogram — downstream OFDM histogram

Parser for downstream OFDM histogram captures (power-level distributions).

> **Module location**
> `src/pypnm/pnm/parser/CmDsOfdmHistogram.py`

## Inputs

- DOCSIS histogram payload captured via the histogram endpoint.

## Outputs

`CmDsOfdmHistogramModel` exposes:

- `bins`: `[start_dbmv, end_dbmv, count]` tuples for each histogram bucket.
- `header`: timestamps, total codewords, and bin width.

## Usage

```python
from pathlib import Path
from pypnm.pnm.parser.CmDsOfdmHistogram import CmDsOfdmHistogram

payload = Path("histogram.bin").read_bytes()
hist = CmDsOfdmHistogram(payload)

bins = hist.get_bins()
```
