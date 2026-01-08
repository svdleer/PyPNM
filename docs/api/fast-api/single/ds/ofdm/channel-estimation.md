# PNM Operations - Downstream OFDM Channel Estimation Coefficients

Deep visibility into the downstream physical layer of DOCSIS 3.1+ OFDM channels via **per-subcarrier complex channel-estimation coefficients** and derived characteristics (magnitude, group delay, echoes). This page follows the same structure and conventions as the RxMER doc.

## Overview

[`CmDsOfdmChanEstimateCoef`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py) parses the binary payload into complex coefficients (2 bytes real + 2 bytes imag per subcarrier), normalizes frequency metadata, and exposes a typed model for downstream analysis and export.

## Endpoint

`POST /docs/pnm/ds/ofdm/channelEstCoeff/getCapture`

## Request

Refer to [Common → Request](../../../common/request.md).  
**Deltas (Analysis-only additions):** optional `analysis`, `analysis.output`, and `analysis.plot.ui` controls (same pattern as RxMER).

### Delta Table

| JSON path                  | Type     | Allowed values / format   | Default   | Description                                                                                   |
|---------------------------|----------|---------------------------|-----------|-----------------------------------------------------------------------------------------------|
| `analysis.type`           | string   | `"basic"`                 | `"basic"` | Selects the analysis mode used during capture processing.                                     |
| `analysis.output.type`    | string   | `"json"`, `"archive"`     | `"json"`  | Output format. `"json"` returns inline under `data`; `"archive"` returns a ZIP (CSV + plots). |
| `analysis.plot.ui.theme`  | string   | `"light"`, `"dark"`       | `"dark"`  | Plot theme hint (colors, grid, ticks). Does not affect raw metrics/CSV.                       |

### Notes

- When `analysis.output.type = "archive"`, the HTTP response body is the file (no `data` JSON payload).
- The `primative` section is the normalized raw payload with added metadata.
- The `measurement_stats` section summarizes one-shot SNMP statistics collected at capture time.
- To capture specific channels, set `cable_modem.pnm_parameters.capture.channel_ids`. Empty or missing means all channels.

### Example Request

```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.10",
        "ipv6": "2001:db8::10"
      },
      "capture": {
        "channel_ids": []
      }
    },
    "snmp": { "snmpV2C": { "community": "private" } }
  },
  "analysis": {
    "type": "basic",
    "output": { "type": "json" },
    "plot": { "ui": { "theme": "dark" } }
  }
}
```

## Response

Standard envelope with payload under `data`.

### When `output.type = "json"`

```json
"output": { "type": "json" }
```

#### Abbreviated Example — Analysis + Primitive + Measurement Stats

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "analysis": [
      {
        "frequency_unit": "Hz",
        "magnitude_unit": "dB",
        "group_delay_unit": "microsecond",
        "complex_unit": "[Real, Imaginary]",
        "carrier_values": {
          "occupied_channel_bandwidth": 190000000,
          "carrier_count": 3800,
          "frequency": [],
          "magnitude": [],
          "group_delay": [],
          "complex": [],
          "complex_dimension": "2"
        },
        "signal_statistics_target": "magnitude",
        "signal_statistics": {
          "mean": 8.72, "median": 10.03, "std": 4.64, "variance": 21.49, "power": 97.55,
          "peak_to_peak": 41.23, "mean_abs_deviation": 3.40, "skewness": -1.86,
          "kurtosis": 8.07, "crest_factor": 2.66, "zero_crossing_rate": 0.113, "zero_crossings": 430
        },
        "echo": {
            "type": 0,
            "report": {
                "channel_id": 197,
                "dataset": {
                    "subcarriers": 3800,
                    "snapshots": 1,
                    "subcarrier_spacing_hz": 50000.0,
                    "sample_rate_hz": 190000000.0
                },
                "cable_type": "RG6",
                "velocity_factor": 0.87,
                "prop_speed_mps": 260819438.46,
                "direct_path": {
                    "bin_index": 1669,
                    "time_s": 9.46842105263158e-06,
                    "amplitude": 0.16922362601561589,
                    "distance_m": 0.0,
                    "distance_ft": 0.0
                },
                "echoes": [
                    { "bin_index": 2800, "time_s": 1.588421052631579e-05, "amplitude": 0.14946724502489767, "distance_m": 836.6813, "distance_ft": 2745.0174 },
                    { "bin_index": 2523, "time_s": 1.431578947368421e-05, "amplitude": 0.13743558197116454, "distance_m": 632.1440, "distance_ft": 2073.9631 },
                    { "bin_index": 3637, "time_s": 2.0631578947368422e-05, "amplitude": 0.1355237604633048, "distance_m": 1455.7843, "distance_ft": 4776.1952 },
                    { "bin_index": 3601, "time_s": 2.043157894736842e-05, "amplitude": 0.1354512671455663, "distance_m": 1429.7023, "distance_ft": 4690.6245 },
                    { "bin_index": 1995, "time_s": 1.131578947368421e-05, "amplitude": 0.13187935631740205, "distance_m": 240.9148, "distance_ft": 790.4029 }
                ],
                "threshold_frac": 0.2,
                "guard_bins": 2,
                "min_separation_s": 0.0,
                "max_delay_s": null,
                "max_peaks": 5,
                "time_response": null
            }
        }
      }
    ],
    "primative": [
      {
        "status": "SUCCESS",
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 2,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1751835648
        },
        "channel_id": 197,
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "subcarrier_zero_frequency": 1217600000,
        "first_active_subcarrier_index": 148,
        "subcarrier_spacing": 50000,
        "data_length": 15200,
        "occupied_channel_bandwidth": 190000000,
        "value_units": "[Real(I),Imaginary(Q)]",
        "values": [[...]]
      }
    ],
    "measurement_stats": [
      {
        "index": 48,
        "channel_id": 197,
        "entry": {
          "docsPnmCmOfdmChEstCoefTrigEnable": false,
          "docsPnmCmOfdmChEstCoefAmpRipplePkToPk": 1484,
          "docsPnmCmOfdmChEstCoefAmpRippleRms": 379,
          "docsPnmCmOfdmChEstCoefAmpSlope": 1,
          "docsPnmCmOfdmChEstCoefGrpDelayRipplePkToPk": 112741,
          "docsPnmCmOfdmChEstCoefGrpDelayRippleRms": 3164,
          "docsPnmCmOfdmChEstCoefMeasStatus": 4,
          "docsPnmCmOfdmChEstCoefFileName": "ds_ofdm_chan_est_coef_aabbccddeeff_193_1761517070.bin",
          "docsPnmCmOfdmChEstCoefAmpMean": 4468,
          "docsPnmCmOfdmChEstCoefGrpDelaySlope": 5,
          "docsPnmCmOfdmChEstCoefGrpDelayMean": 1558514
        }
      }
    ]
  }
}
```

### When `output.type = "archive"`

```json
"output": { "type": "archive" }
```

The response is a downloadable ZIP file containing:

- CSV exports per subcarrier: `complex.csv`, `magnitude.csv`, `group_delay.csv`.
- PNG plots: `magnitude.png`, `group_delay.png`, `complex_phase.png` (optional).

| DARK                          | Light                         | Description                       |
|------------------------------|-------------------------------|-----------------------------------|
| `magnitude_dark.png`         | `magnitude_light.png`         | Magnitude vs. Subcarrier Index    |
| `group_delay_dark.png`       | `group_delay_light.png`       | Group Delay vs. Subcarrier Index  |
| `complex_phase_dark.png`     | `complex_phase_light.png`     | Complex Phase vs. Subcarrier Index|

### Echo Detection

When `analysis` includes echo processing, the response may include an `echo` object with a summarized report. The fields below
describe the structure and interpretation.

**Echo Report Schema** (`data.analysis[].echo.report`)

| Field                               | Type          | Description                                                                                     |
|-------------------------------------|---------------|-------------------------------------------------------------------------------------------------|
| channel_id                          | int           | Channel ID used for the analysis.                                                               |
| dataset.subcarriers                 | int           | Number of active subcarriers used to compute the time-domain response.                          |
| dataset.snapshots                   | int           | Count of snapshots/averages across captures (1 for single-capture).                             |
| dataset.subcarrier_spacing_hz       | number        | Subcarrier spacing in Hz (e.g., 50,000).                                                        |
| dataset.sample_rate_hz              | number        | Effective sample rate in Hz (≈ subcarriers × spacing).                                          |
| cable_type                          | string        | Plant cable type assumption (affects velocity factor).                                          |
| velocity_factor                     | number        | Fraction of the speed of light used for distance conversion (e.g., 0.87 for RG6).              |
| prop_speed_mps                      | number        | Propagation speed in meters per second derived from `velocity_factor`.                          |
| direct_path.bin_index               | int           | FFT bin of the dominant/direct path peak.                                                       |
| direct_path.time_s                  | number        | Time of direct path peak in seconds.                                                            |
| direct_path.amplitude               | number        | Magnitude of the direct path peak (normalized units).                                           |
| direct_path.distance_m              | number        | Reference distance in meters (0 for direct path).                                               |
| direct_path.distance_ft             | number        | Reference distance in feet (0 for direct path).                                                 |
| echoes[]                            | array of objects | Detected echo peaks sorted by amplitude or delay (implementation-defined).                      |
| echoes[].bin_index                  | int           | FFT bin index of the echo peak.                                                                 |
| echoes[].time_s                     | number        | Echo peak time in seconds.                                                                      |
| echoes[].amplitude                  | number        | Echo peak magnitude (normalized units).                                                         |
| echoes[].distance_m                 | number        | One-way distance estimate in meters.                                                            |
| echoes[].distance_ft                | number        | One-way distance estimate in feet.                                                              |
| threshold_frac                      | number        | Detection threshold as a fraction of the direct-path amplitude (0-1).                           |
| guard_bins                          | int           | Number of bins ignored around each detected peak to avoid double-counting.                      |
| min_separation_s                    | number        | Minimum separation between peaks in seconds.                                                     |
| max_delay_s                         | number/null   | Optional maximum delay search window in seconds.                                                |
| max_peaks                           | int           | Maximum number of echoes to report.                                                             |
| time_response                       | array\|null    | Optional time-domain response samples (implementation-dependent; may be null for brevity).      |

### Echo Distance Calculation Notes

- Distance is computed from time via `distance = time_s × prop_speed_mps`. Values are one-way estimates.
- The `direct_path` is used as the reference for thresholding and distance zero; echoes are relative to this peak.
- Choice of `velocity_factor` should match plant assumptions (e.g., RG6≈0.87, hardline may differ).

## Field Tables

**Payload: `data.analysis[]`**

| Field                                     | Type            | Description                                 |
|-------------------------------------------|-----------------|---------------------------------------------|
| frequency_unit                            | string          | Unit for frequency arrays (Hz).             |
| magnitude_unit                            | string          | Unit for magnitude (dB).                    |
| group_delay_unit                          | string          | Unit for group delay (microsecond).         |
| complex_unit                              | string          | Label for complex pairs.                    |
| carrier_values.occupied_channel_bandwidth | int (Hz)        | Active bandwidth.                           |
| carrier_values.carrier_count              | int             | Subcarrier count.                           |
| carrier_values.frequency                  | array(int)      | Frequency per subcarrier (Hz).              |
| carrier_values.magnitude                  | array(float)    | Magnitude per subcarrier (dB).              |
| carrier_values.group_delay                | array(float)    | Group delay per subcarrier (µs).            |
| carrier_values.complex                    | array(array)    | Complex pairs `[real, imag]`.               |
| signal_statistics_target                  | string          | Which array stats were computed on.         |
| signal_statistics.*                       | object          | Aggregate stats (mean, std, variance, …).   |

**Payload: `data.primative[]`**

| Field                        | Type        | Description                                           |
|-----------------------------|-------------|-------------------------------------------------------|
| status                      | string      | Result for this capture (e.g., `SUCCESS`).            |
| pnm_header.*                | object      | PNM file header (type, version, capture time).        |
| channel_id                  | int         | Downstream OFDM channel ID.                           |
| mac_address                 | string      | MAC address of the modem.                             |
| subcarrier_zero_frequency   | int (Hz)    | Subcarrier 0 frequency.                               |
| first_active_subcarrier_index| int        | First active subcarrier index.                        |
| subcarrier_spacing          | int (Hz)    | Subcarrier spacing.                                   |
| data_length                 | int (bytes) | Coefficient payload length (multiple of 4).           |
| occupied_channel_bandwidth  | int (Hz)    | Active bandwidth.                                     |
| value_units                 | string      | Complex pair label, e.g., `"[Real(I),Imaginary(Q)]"`. |
| values                      | array(array)| Complex pairs per subcarrier.                         |

**Payload: `data.measurement_stats[]`**

SNMP snapshot for each channel at capture time.

| Field                                                | Type     | Description                                  |
|------------------------------------------------------|----------|----------------------------------------------|
| index                                                | int      | SNMP table row index (per device).           |
| channel_id                                           | int      | OFDM downstream channel ID.                  |
| entry.docsPnmCmOfdmChEstCoefTrigEnable              | boolean  | Whether CM trigger was enabled.              |
| entry.docsPnmCmOfdmChEstCoefAmpRipplePkToPk         | int      | Pk‑to‑Pk amplitude ripple (vendor units).    |
| entry.docsPnmCmOfdmChEstCoefAmpRippleRms            | int      | RMS amplitude ripple (vendor units).         |
| entry.docsPnmCmOfdmChEstCoefAmpSlope                | int      | Amplitude slope (vendor units).              |
| entry.docsPnmCmOfdmChEstCoefGrpDelayRipplePkToPk    | int      | Group delay ripple Pk‑to‑Pk (vendor units).  |
| entry.docsPnmCmOfdmChEstCoefGrpDelayRippleRms       | int      | Group delay ripple RMS (vendor units).       |
| entry.docsPnmCmOfdmChEstCoefMeasStatus              | int      | Measurement status code.                     |
| entry.docsPnmCmOfdmChEstCoefFileName                | string   | Device‑side filename of the sample.          |
| entry.docsPnmCmOfdmChEstCoefAmpMean                 | int      | Amplitude mean (vendor units).               |
| entry.docsPnmCmOfdmChEstCoefGrpDelaySlope           | int      | Group delay slope (vendor units).            |
| entry.docsPnmCmOfdmChEstCoefGrpDelayMean            | int      | Group delay mean (vendor units).             |
