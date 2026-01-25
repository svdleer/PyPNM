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
Each value contains decoded tap configuration, coefficient arrays, and optional group delay.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "80": {
      "main_tap_location": 8,
      "taps_per_symbol": 1,
      "num_taps": 24,
      "reserved": 0,
      "header_hex": "08 01 18 00",
      "payload_hex": "08 01 18 00 FE FF FE FF 03 00 FF FF 00 00 01 00",
      "payload_preview_hex": "08 01 18 00 FE FF FE FF 03 00 FF FF 00 00 01 00",
      "taps": [
        { "real": -257, "imag": -257, "magnitude": 363.45, "magnitude_power_dB": 51.21, "real_hex": "FEFF", "imag_hex": "FEFF" },
        { "real": 768, "imag": -1, "magnitude": 768.0, "magnitude_power_dB": 57.71, "real_hex": "0300", "imag_hex": "FFFF" }
      ],
      "metrics": {
        "main_tap_energy": 4190209.0,
        "total_tap_energy": 4190741.0,
        "main_tap_ratio": 38.96
      },
      "group_delay": {
        "channel_width_hz": 1600000,
        "rolloff": 0.25,
        "taps_per_symbol": 1,
        "symbol_rate": 1280000.0,
        "symbol_time_us": 0.78125,
        "sample_period_us": 0.78125,
        "fft_size": 24,
        "delay_samples": [0.1, 0.2, 0.3],
        "delay_us": [0.08, 0.16, 0.23]
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
