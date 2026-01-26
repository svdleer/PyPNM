# DOCSIS 3.0 Upstream ATDMA Pre-Equalization

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Pre-Equalization Tap Data For Plant Analysis (Reflections, Group Delay, Pre-Echo).

## Endpoint

**POST** `/docs/if30/us/atdma/chan/preEqualization`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **object** keyed by the **SNMP table index** of each upstream channel.  
Each value contains decoded tap configuration, coefficients, metrics, and optional group delay.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": "Successfully retrieved upstream pre-equalization coefficients",
  "results": {
    "80": {
      "main_tap_location": 8,
      "taps_per_symbol": 1,
      "num_taps": 24,
      "reserved": 0,
      "header_hex": "08 01 18 00",
      "payload_hex": "08 01 18 00 00 00 00 01 00 03 FF FF FF FF 00 02 00 01",
      "payload_preview_hex": "08 01 18 00 00 00 00 01 00 03 FF FF FF FF 00 02 00 01",
      "taps": [
        { "real": 0, "imag": 1, "magnitude": 1.0, "magnitude_power_dB": 0.0, "real_hex": "0000", "imag_hex": "0001" },
        { "real": 3, "imag": -1, "magnitude": 3.16, "magnitude_power_dB": 10.0, "real_hex": "0003", "imag_hex": "FFFF" }
      ],
      "metrics": {
        "main_tap_energy": 4190209.0,
        "main_tap_nominal_energy": 8380418.0,
        "total_tap_energy": 4190713.0,
        "main_tap_ratio": 39.19,
        "frequency_response": {
          "fft_size": 24,
          "frequency_bins": [0.0, 0.041666666666666664, 0.08333333333333333],
          "magnitude": [2054.000243427444, 2025.9517291663806, 2030.7990565383996],
          "magnitude_power_db": [66.25200981462334, 66.13258187076737, 66.15333905939173],
          "magnitude_power_db_normalized": [0.0, -0.11942794385596756, -0.09867075523160906],
          "phase_radians": [-0.0004868548787686341, -1.8217247253384095, 2.620174402315228]
        }
      },
      "group_delay": {
        "channel_width_hz": 6400000,
        "rolloff": 0.25,
        "taps_per_symbol": 1,
        "symbol_rate": 5120000.0,
        "symbol_time_us": 0.1953125,
        "sample_period_us": 0.1953125,
        "fft_size": 24,
        "delay_samples": [6.956616231115412, 6.994905680977856, 7.001802249927044],
        "delay_us": [1.3587141076397289, 1.3661925158159873, 1.3675395019388759]
      }
    }
    /* ... other upstream channel indices elided ... */
  }
}
```

## Container Keys

| Key (top-level under `data`) | Type   | Description                                                       |
| ---------------------------- | ------ | ----------------------------------------------------------------- |
| `"80"`, `"81"`, …            | string | **SNMP table index** for the upstream channel row (OID instance). |

## Channel-Level Fields

| Field               | Type    | Description                                                 |
| ------------------- | ------- | ----------------------------------------------------------- |
| `main_tap_location` | integer | Location of the main tap (typically near the filter center) |
| `taps_per_symbol`   | integer | Taps per symbol from the pre-EQ header                      |
| `num_taps`          | integer | Total number of taps                                        |
| `reserved`          | integer | Reserved header byte                                        |
| `header_hex`        | string  | Header bytes in hex                                         |
| `payload_hex`       | string  | Full payload hex                                            |
| `payload_preview_hex` | string | Header plus a preview window of taps in hex                 |
| `taps`              | array   | Complex tap coefficients (real/imag pairs)                  |
| `metrics`           | object  | ATDMA pre-equalization key metrics when available           |
| `group_delay`       | object  | Group delay results when channel bandwidth is available     |

## Coefficient Object Fields

| Field                | Type  | Units | Description                          |
| -------------------- | ----- | ----- | ------------------------------------ |
| `real`               | int   | —     | Real part of the complex coefficient |
| `imag`               | int   | —     | Imaginary part of the coefficient    |
| `magnitude`          | float | —     | Magnitude of the complex tap         |
| `magnitude_power_dB` | float | dB    | Power of the tap in dB               |
| `real_hex`           | string | —    | Raw 2-byte real coefficient (hex)    |
| `imag_hex`           | string | —    | Raw 2-byte imag coefficient (hex)    |

## Notes

* Each top-level key under `data` is the DOCSIS **SNMP index** for an upstream SC-QAM (ATDMA) channel.
* Group delay is included only when the upstream channel bandwidth is available.
* Use tap shapes and main-tap offset to infer echo path delay and alignment health.
* Tap coefficients are signed integers; convert to floating-point as needed for analysis.
