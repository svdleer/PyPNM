
# DOCSIS Downstream OFDM RxMER (CmDsOfdmRxMer)

Parser and container for cable-modem **Receive Modulation Error Ratio (RxMER)** captured from a DOCSIS 3.1+ downstream OFDM channel. This guide renders correctly in both **MkDocs** and **GitHub**.

## Overview

[`CmDsOfdmRxMer`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmRxMer.py) validates that the input PNM payload is an RxMER file, unpacks header fields, decodes per-subcarrier RxMER in quarter-dB steps, and provides a typed model (`CmDsOfdmRxMerModel`) with statistics and Shannon-based modulation metrics.

* **PNM File Type Required:** `RECEIVE_MODULATION_ERROR_RATIO`
* **RxMER Value Encoding:** 1 byte per subcarrier, quarter-dB units → value = `min(max(byte / 4.0, 0.0), 63.5)`
* **Frequencies:** Derived from zero frequency, first active index, and subcarrier spacing (Hz)

## Binary Layout (Header)

Unpacked with `struct` format `!B6sIHBI` (network byte order):

| Field                           | Type | Description                                             |
| ------------------------------- | ---- | ------------------------------------------------------- |
| `channel_id`                    | `B`  | DOCSIS downstream channel ID                            |
| `mac`                           | `6s` | Cable-modem MAC address (6 bytes)                       |
| `subcarrier_zero_frequency`     | `I`  | Frequency of subcarrier 0 (Hz)                          |
| `first_active_subcarrier_index` | `H`  | Index of the first active subcarrier                    |
| `subcarrier_spacing_khz`        | `B`  | Spacing in kHz; converted to Hz as `spacing_khz * 1000` |
| `data_length`                   | `I`  | Number of RxMER bytes to follow                         |

Payload bytes immediately after the header contain `data_length` quarter-dB samples.

## Model Output (CmDsOfdmRxMerModel)

`CmDsOfdmRxMerModel` (Pydantic) captures decoded values and derived metrics:

| Field                        | Type                    | Description                                        |
| ---------------------------- | ----------------------- | -------------------------------------------------- |
| `data_length`                | `int`                   | Number of RxMER points (subcarriers)               |
| `occupied_channel_bandwidth` | `int`                   | `data_length * subcarrier_spacing` (Hz)            |
| `value_units`                | `str`                   | Always `"dB"`                                      |
| `values`                     | `FloatSeries`           | RxMER values per active subcarrier (dB)            |
| `signal_statistics`          | `SignalStatisticsModel` | Aggregate stats computed from `values`             |
| `modulation_statistics`      | `Dict[str, Any]`        | Shannon-based metrics from `ShannonSeries(values)` |

> The model also carries PNM header metadata via the base model (`PnmBaseModel`).

## Public API

| Method               | Type     | Usage                      | Brief Description                               |
| -------------------- | -------- | -------------------------- | ----------------------------------------------- |
| `get_rxmer_values()` | instance | `rxmer.get_rxmer_values()` | Decode quarter-dB bytes into clamped dB floats. |
| `get_frequencies()`  | instance | `rxmer.get_frequencies()`  | Compute per-subcarrier center frequencies (Hz). |
| `to_model()`         | instance | `model = rxmer.to_model()` | Return the typed Pydantic model.                |
| `to_dict()`          | instance | `rxmer.to_dict()`          | Serialize model to a Python dict.               |
| `to_json()`          | instance | `rxmer.to_json()`          | Serialize model to JSON string.                 |

### Visibility Notes

* `_process()` and `_update_model()` are private helpers (single underscore) used internally.
* There are no double-underscore (`__`) name-mangled methods in this class.

## Behavior And Edge Cases

* Rejects non-RxMER files with a clear error containing both expected and actual file-type canonical names.
* Validates header size before unpacking; raises `ValueError` for undersized payloads.
* Validates that payload length is at least `data_length` bytes.
* Frequency generation returns an empty list when spacing or `data_length` are non-positive.

### Frequency Computation

Let `spacing = subcarrier_spacing (Hz)`, `f0 = subcarrier_zero_frequency (Hz)`, `i0 = first_active_subcarrier_index`, `n = data_length`:

* `start = f0 + spacing * i0`
* `f[i] = start + i * spacing`, for `i = 0..n-1`

## Example

```python
from pypnm.pnm.parser.CmDsOfdmRxMer import CmDsOfdmRxMer

# binary_bytes must contain a valid PNM RxMER payload.
rxmer = CmDsOfdmRxMer(binary_bytes)

values_db = rxmer.get_rxmer_values()     # [dB, ...]
freqs_hz  = rxmer.get_frequencies()      # [Hz, ...]

// or:
model = rxmer.to_model()
print(model.data_length, model.value_units)

as_dict = rxmer.to_dict()
as_json = rxmer.to_json()
print(as_json[:120], "...")
```

## Link To Code: [CmDsOfdmRxMer](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmRxMer.py)
