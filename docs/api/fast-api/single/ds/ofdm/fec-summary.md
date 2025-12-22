# PNM Operations - Downstream OFDM FEC Summary

Forward Error Correction Trends For Proactive Monitoring Of OFDM Downstream Health.

## Overview

Retrieves DOCSIS 3.1 OFDM Forward Error Correction (FEC) summary statistics per modulation profile, suitable for
dashboards and automation. Each profile contains a time‑series of codeword counters: total, corrected, and
uncorrectable. Use this to separate transient bursts from persistent issues and to validate error‑protection efficacy.

## Endpoint

`POST /docs/pnm/ds/ofdm/fecSummary/getCapture`

## Request

Refer to [Common → Request](../../../common/request.md).  
**Deltas (Analysis‑Only Additions):** optional `analysis`, `analysis.output`, and `analysis.plot.ui` controls
(same pattern as RxMER).

### Delta Table

| JSON path                | Type   | Allowed values / format | Default | Description                                                                                               |
| ------------------------ | ------ | ----------------------- | ------- | --------------------------------------------------------------------------------------------------------- |
| `analysis.type`          | string | "basic"                 | "basic" | Selects the analysis mode used during capture processing.                                                 |
| `analysis.output.type`   | string | "json", "archive"       | "json"  | Output format: **`json`** returns inline `data`; **`archive`** returns a ZIP (CSV exports and PNG plots). |
| `analysis.plot.ui.theme` | string | "light", "dark"         | "dark"  | Theme hint for plot generation (colors, grid, ticks). Does not affect raw metrics/CSV.                    |

### Capture Settings

| JSON path                             | Type | Example | Description                                                                                  |
| ------------------------------------- | ---- | ------- | -------------------------------------------------------------------------------------------- |
| `capture_settings.fec_summary_type`   | int  | 2       | Summary type per SNMP `docsPnmCmDsOfdmFecSumType`. **2 = 24‑hour**, **3 = 10‑minute**.      |

### Notes

* Your project setting: **Type 2 corresponds to a 24‑hour interval**; **Type 3 corresponds to a 10‑minute interval**.  
* The time‑series set count depends on the type (see *Return Structure* → `number_of_sets`).  
* Profile `255` commonly refers to **NCP** (Next Codeword Pointer).
* To capture specific channels, set `cable_modem.pnm_parameters.capture.channel_ids`. Empty or missing means all channels.

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
  },
  "capture_settings": {
    "fec_summary_type": 2
  }
}
```

## Response

Standard envelope with payload under `data`.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "analysis": [
      {
        "device_details": {
          "system_description": {
            "HW_REV": "1.0",
            "VENDOR": "LANCity",
            "BOOTR": "NONE",
            "SW_REV": "1.0.0",
            "MODEL": "LCPET-3"
          }
        },
        "channel_id": 159,
        "profiles": [
          {
            "profile": 255,
            "number_of_sets": 600,
            "codewords": {
              "timestamps": [],
              "total_codewords": [],
              "corrected": [],
              "uncorrectable": []
            }
          }
        ]
      }
    ],
    "primative": [
      {
        "status": "SUCCESS",
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 8,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1762466502
        },
        "channel_id": 159,
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "summary_type": 2,
        "num_profiles": 5,
        "fec_summary_data": [
          {
            "profile_id": 255,
            "number_of_sets": 600,
            "codeword_entries": {
              "timestamp": [],
              "total_codewords": [],
              "corrected": [],
              "uncorrectable": []
            }
          }
        ],
        "summary_type_label": "24-hour interval"
      }
    ],
    "measurement_stats": [
      {
        "index": 3,
        "entry": {
          "docsPnmCmDsOfdmFecSumType": "24-hour",
          "docsPnmCmDsOfdmFecFileEnable": true,
          "docsPnmCmDsOfdmFecMeasStatus": "sample_ready",
          "docsPnmCmDsOfdmFecFileName": "ds_ofdm_codeword_error_rate_aabbccddeeff_159_1762468766.bin"
        }
      },
      {
        "index": 48,
        "entry": {
          "docsPnmCmDsOfdmFecSumType": "10-minute",
          "docsPnmCmDsOfdmFecFileEnable": true,
          "docsPnmCmDsOfdmFecMeasStatus": "sample_ready",
          "docsPnmCmDsOfdmFecFileName": "ds_ofdm_codeword_error_rate_aabbccddeeff_160_1762468768.bin"
        }
      }
    ]
  }
}
```

## Return Structure

### Top‑Level Envelope

| Field         | Type          | Description                                                               |
| ------------- | ------------- | ------------------------------------------------------------------------- |
| `mac_address` | string        | Request echo of the modem MAC.                                            |
| `status`      | int           | 0 on success, non‑zero on error.                                          |
| `message`     | string\|null | Optional message describing status.                                       |
| `data`        | object        | Container for results (`analysis`, `primative`, `measurement_stats`).     |

### `data.analysis[]`

Analysis view per channel, grouped by profile.

| Field                      | Type    | Description                                                                 |
| -------------------------- | ------- | --------------------------------------------------------------------------- |
| device_details.*           | object  | System descriptor at analysis time.                                         |
| channel_id                 | int     | OFDM downstream channel ID.                                                 |
| profiles[].profile         | int     | Modulation profile identifier (`0..N`, `255` for NCP in many deployments).  |
| profiles[].number_of_sets  | int     | Number of time samples in this capture (depends on summary type).           |
| profiles[].codewords.*     | arrays  | Parallel arrays: `timestamps`, `total_codewords`, `corrected`, `uncorrectable`. |

### `data.primative[]`

Normalized raw capture for export/plotting.

| Field                               | Type    | Description                                                       |
| ----------------------------------- | ------- | ----------------------------------------------------------------- |
| status                              | string  | Result for this capture (e.g., `SUCCESS`).                        |
| pnm_header.*                        | object  | PNM header (type, version, capture time).                         |
| channel_id                          | int     | Channel ID.                                                       |
| mac_address                         | string  | MAC address.                                                      |
| summary_type                        | int     | SNMP value (2 or 3).                                              |
| num_profiles                        | int     | Number of profiles present in the payload.                        |
| fec_summary_data[]                  | array   | Raw profile entries as captured.                                  |
| fec_summary_data[].profile_id       | int     | Profile ID (e.g., `0..N`, `255`).                                 |
| fec_summary_data[].number_of_sets   | int     | Number of time samples in the series.                             |
| fec_summary_data[].codeword_entries.* | arrays | `timestamp`, `total_codewords`, `corrected`, `uncorrectable`.     |
| summary_type_label                  | string  | Human‑readable label (e.g., `24-hour interval`).                  |

### `data.measurement_stats[]`

Snapshot of CM FEC‑summary configuration and state via SNMP at capture time.

| Field                                         | Type    | Description                                                              |
| --------------------------------------------- | ------- | ------------------------------------------------------------------------ |
| index                                         | int     | SNMP table row index.                                                    |
| entry.docsPnmCmDsOfdmFecSumType               | string  | Selected summary type (`24-hour`, `10-minute`).                          |
| entry.docsPnmCmDsOfdmFecFileEnable            | boolean | Whether CM capture‑to‑file was enabled.                                  |
| entry.docsPnmCmDsOfdmFecMeasStatus            | string  | Measurement status (e.g., `sample_ready`).                               |
| entry.docsPnmCmDsOfdmFecFileName              | string  | Device‑side filename of the summary payload.                             |

## Matplot Plotting

| Plot                                                                          | Description                                                                                          |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Uncorrectable Rate vs Time      | Line or area plot of uncorrectable codewords to visualize bursts and persistent tails.               |
| Corrected vs Uncorrectable (Stacked)    | Stacked area of corrected/uncorrectable counts to show protection effectiveness over time.           |
| Profile Comparison                 | Multiple lines by profile to identify outliers (e.g., NCP vs data profiles).                         |

## Notes

* **Summary Type Mapping (Project Standard):** `2 → 24‑hour` (1 record/min, up to 1440), `3 → 10‑minute` (1 record/sec, up to 600).  
* Use per‑profile trends to identify *when* and *where* errors occur (e.g., profile‑specific ingress or plant issues).  
* For NCP display questions, align with current ECN/SPEC guidance when interpreting corrected counters.
