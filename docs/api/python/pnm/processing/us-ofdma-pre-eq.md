# DOCSIS Upstream OFDMA Pre-Equalization (CmUsOfdmaPreEq)

Parser and container for upstream OFDMA pre-equalization coefficients captured from a DOCSIS 3.1+ cable modem. This guide renders correctly in both MkDocs and GitHub.

## Overview

[`CmUsOfdmaPreEq`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmUsOfdmaPreEq.py) validates that the payload is an upstream pre-equalization PNM file, decodes fixed-point complex coefficients, and returns a typed model (`CmUsOfdmaPreEqModel`) that includes header metadata, channel information, and complex coefficient pairs.

* PNM File Type Required: `UPSTREAM_PRE_EQUALIZER_COEFFICIENTS` or `UPSTREAM_PRE_EQUALIZER_COEFFICIENTS_LAST_UPDATE`
* Coefficient Encoding: 16-bit two's complement fixed-point values (I/Q pairs)
* Frequencies: Derived from zero frequency, first active index, and subcarrier spacing (Hz)

## Binary Layout (Header)

Unpacked with `struct` format `!B6s6sIHBI` (network byte order):

| Field                           | Type | Description                                             |
| ------------------------------- | ---- | ------------------------------------------------------- |
| `channel_id`                    | `B`  | DOCSIS upstream channel ID                              |
| `cm_mac`                        | `6s` | Cable-modem MAC address (6 bytes)                       |
| `cmts_mac`                      | `6s` | CMTS MAC address (6 bytes)                              |
| `subcarrier_zero_frequency`     | `I`  | Frequency of subcarrier 0 (Hz)                          |
| `first_active_subcarrier_index` | `H`  | Index of the first active subcarrier                    |
| `subcarrier_spacing_khz`        | `B`  | Spacing in kHz; converted to Hz as `spacing_khz * 1000` |
| `data_length`                   | `I`  | Number of coefficient bytes to follow                   |

Payload bytes immediately after the header contain interleaved fixed-point I/Q coefficients.

## Model Output (CmUsOfdmaPreEqModel)

`CmUsOfdmaPreEqModel` (Pydantic) captures decoded values and derived metrics:

| Field                        | Type            | Description                                        |
| ---------------------------- | --------------- | -------------------------------------------------- |
| `channel_id`                 | `int`           | Upstream channel ID                                |
| `mac_address`                | `str`           | Cable-modem MAC address                            |
| `cmts_mac_address`           | `str`           | CMTS MAC address                                   |
| `subcarrier_zero_frequency`  | `int`           | Frequency of subcarrier 0 (Hz)                     |
| `first_active_subcarrier_index` | `int`        | Index of first active subcarrier                   |
| `subcarrier_spacing`         | `int`           | Subcarrier spacing (Hz)                            |
| `occupied_channel_bandwidth` | `int`           | `len(values) * subcarrier_spacing` (Hz)            |
| `value_length`               | `int`           | Coefficient payload size (bytes)                   |
| `value_unit`                 | `str`           | Always `"[Real, Imaginary]"`                       |
| `values`                     | `ComplexArray`  | Complex coefficients as `[real, imag]` pairs       |

## Public API

| Method             | Type     | Usage                         | Brief Description                         |
| ------------------ | -------- | ----------------------------- | ----------------------------------------- |
| `get_coefficients()` | instance | `pre_eq.get_coefficients()` | Decode or return cached complex samples. |
| `to_model()`       | instance | `model = pre_eq.to_model()`   | Return the typed Pydantic model.          |
| `to_dict()`        | instance | `pre_eq.to_dict()`            | Serialize model to a Python dict.         |
| `to_json()`        | instance | `pre_eq.to_json()`            | Serialize model to JSON string.           |

## Example

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

## Link To Code: [CmUsOfdmaPreEq](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmUsOfdmaPreEq.py)
