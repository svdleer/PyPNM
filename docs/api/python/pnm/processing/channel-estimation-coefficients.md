# DOCSIS Downstream OFDM Channel Estimation Coefficients (CmDsOfdmChanEstimateCoef)

Parser/adapter for DOCSIS 3.1+ **OFDM Downstream Channel Estimation Coefficients**. Renders correctly in both **MkDocs** and **GitHub**.

## Overview

[`CmDsOfdmChanEstimateCoef`](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py) validates that the input PNM payload is an OFDM *Channel Estimation Coefficients* file, unpacks header fields, decodes complex per-subcarrier coefficients from a signed-magnitude fixed-point format, and returns a typed model (`CmDsOfdmChanEstimateCoefModel`) with frequency metadata and a rounded view for downstream consumers.

* **PNM File Type Required:** `OFDM_CHANNEL_ESTIMATE_COEFFICIENT`
* **Coefficient Encoding:** 4 bytes per subcarrier (2 bytes real + 2 bytes imag), signed-magnitude fixed-point `N=int_bits`, `F=frac_bits` (default `N=2`, `F=13`)
* **Frequencies:** Derived from zero frequency, first active index, and subcarrier spacing (Hz)

## Binary Layout (Header)

Unpacked with `struct` format `>B6sIHBI` (big-endian):

| Field                           | Type | Description                                             |
| ------------------------------- | ---- | ------------------------------------------------------- |
| `channel_id`                    | `B`  | DOCSIS downstream channel ID                            |
| `mac`                           | `6s` | Cable-modem MAC address (6 bytes)                       |
| `subcarrier_zero_frequency`     | `I`  | Frequency of subcarrier 0 (Hz)                          |
| `first_active_subcarrier_index` | `H`  | Index of the first active subcarrier                    |
| `subcarrier_spacing_khz`        | `B`  | Spacing in kHz; converted to Hz as `spacing_khz * 1000` |
| `data_length`                   | `I`  | Coefficient payload length (bytes, multiple of 4)       |

Payload bytes immediately after the header contain `data_length` bytes: each subcarrier contributes `real:int16` + `imag:int16` encoded in signed-magnitude fixed point.

## Model Output (CmDsOfdmChanEstimateCoefModel)

| Field                        | Type           | Description                                                                |
| ---------------------------- | -------------- | -------------------------------------------------------------------------- |
| `data_length`                | `int`          | Coefficient payload length (bytes)                                         |
| `occupied_channel_bandwidth` | `int`          | `(#points) * subcarrier_spacing` (Hz)                                      |
| `value_units`                | `str`          | Always `"complex"`                                                         |
| `values`                     | `ComplexArray` | Per-subcarrier `[real, imag]` pairs; rounded when `round_precision` is set |

> The model also carries PNM header metadata via the base model (`PnmBaseModel`).

## Fixed-Point Decoding And Precision

* Decoding uses `FixedPointDecoder.decode_complex_data(...)` with signed-magnitude `(IntegerBits, FractionalBits)`; default `(2, 13)`.
* When `round_precision` is not `None`, each `[real, imag]` is rounded to the given number of decimal places in the model’s `values`.

## Public API

| Method                                  | Type     | Usage                          | Brief Description                                              |
| --------------------------------------- | -------- | ------------------------------ | -------------------------------------------------------------- |
| `get_coefficients(precision="rounded")` | instance | `coef.get_coefficients()`      | Return `[ [real, imag], ... ]` with optional rounding applied. |
| `get_coefficients(precision="raw")`     | instance | `coef.get_coefficients("raw")` | Return raw `list[complex]` decoded from the payload.           |
| `to_model()`                            | instance | `model = coef.to_model()`      | Return the typed Pydantic model.                               |
| `to_dict()`                             | instance | `coef.to_dict()`               | Serialize model to a Python dict.                              |
| `to_json(indent=2)`                     | instance | `coef.to_json()`               | Serialize model to JSON string.                                |

### Visibility Notes

* `__process()` is a **strict one-off** internal helper (double underscore).
* Private state and helpers are prefixed with a single underscore (class-internal use).

## Behavior And Edge Cases

* Rejects non-matching PNM file type with an error.
* Validates header size and payload length.
* Ensures `data_length` is a multiple of 4 (2 bytes real + 2 bytes imag).
* Computes occupied bandwidth as `len(coefficients) * subcarrier_spacing` (Hz).

## Example

```python
from pypnm.pnm.parser.CmDsOfdmChanEstimateCoef import CmDsOfdmChanEstimateCoef
from pypnm.pnm.lib.fixed_point_decoder import IntegerBits, FractionalBits

# binary_bytes must contain a valid PNM OFDM Channel Estimation Coef payload.
coef = CmDsOfdmChanEstimateCoef(
    binary_data=binary_bytes,
    sm_n_format=(IntegerBits(2), FractionalBits(13)),  # default
    round_precision=6,                                 # rounded view in model.values
)

rounded_pairs = coef.get_coefficients()               # [[real, imag], ...]
raw_complex   = coef.get_coefficients("raw")          # [complex, ...]

model = coef.to_model()
print(model.data_length, model.value_units, len(model.values))

as_dict = coef.to_dict()
as_json = coef.to_json()
print(as_json[:120], "...")
```

## Link To Code: [CmDsOfdmChanEstimateCoef](https://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py)
