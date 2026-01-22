## Agent Review Bundle Summary
- Goal: Add a CmUsOfdmaPreEq programming example to the processing docs.
- Changes: Document a Python example that parses an upstream OFDMA pre-eq capture and prints JSON.
- Files: docs/api/python/pnm/processing/pnm-processing.md
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: would reformat many files); pytest -q
- Notes: Ruff format --check reports existing formatting drift across the repository.

# FILE: docs/api/python/pnm/processing/pnm-processing.md
# Processing Documentation

## Guides

| Guide | Description |
| ----- | ------------|
| [CmDsOfdmRxMer](rxmer.md)                                      | Parser and model for downstream OFDM RxMER with per-subcarrier metrics.   |
| [CmDsOfdmChanEstimateCoef](channel-estimation-coefficients.md) | Parser and model for OFDM channel-estimation coefficients.                |
| [CmDsOfdmFecSummary](fec-summary.md)                           | Parser and model for downstream OFDM FEC summary statistics.              |
| [CmDsOfdmHistogram](histogram.md)                              | Parser and model for downstream OFDM histogram data.                      |
| [CmDsOfdmConstellationDisplay](constellation-display.md)       | Parser and model for downstream OFDM constellation display data.          |

## CmUsOfdmaPreEq Programming Example

Use the upstream OFDMA pre-equalization parser to decode a capture file and emit JSON.

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pypnm.lib.file_processor import FileProcessor
from pypnm.pnm.parser.CmUsOfdmaPreEq import CmUsOfdmaPreEq


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse upstream OFDMA pre-eq capture and print JSON."
    )
    parser.add_argument("path", type=Path, help="Path to upstream pre-eq capture file.")
    args = parser.parse_args()

    raw_payload = FileProcessor(args.path).read_file()
    model = CmUsOfdmaPreEq(raw_payload).to_model()

    print(json.dumps(model.model_dump(), indent=2))


if __name__ == "__main__":
    main()
```

