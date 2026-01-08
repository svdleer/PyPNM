# PNM Operations - Downstream OFDM Modulation Profile

Per-Subcarrier Modulation Mapping And Shannon Context For DOCSIS 3.1+ OFDM Downstream Channels.

## Overview

[`CmDsOfdmModulationProfile`](http://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmModulationProfile.py)
retrieves raw modulation profile structures and normalizes them into frequency-aligned carrier mappings. Analysis expands
this into per-subcarrier modulation with optional Shannon limits for capacity context. Results are export-friendly for
automation and visualization.

## Endpoint

`POST /docs/pnm/ds/ofdm/modulationProfile/getCapture`

## Request

Refer to [Common → Request](../../../common/request.md).  
**Deltas (Analysis-Only Additions):** optional `analysis`, `analysis.output`, and `analysis.plot.ui` controls
(same pattern as RxMER).

### Delta Table

| JSON path                | Type   | Allowed values / format | Default | Description                                                                                               |
| ------------------------ | ------ | ----------------------- | ------- | --------------------------------------------------------------------------------------------------------- |
| `analysis.type`          | string | "basic"               | "basic" | Selects the analysis mode used during processing.                                                         |
| `analysis.output.type`   | string | "json", "archive"   | "json"  | Output format: **`json`** returns inline `data`; **`archive`** returns a ZIP (CSV exports and PNG plots). |
| `analysis.plot.ui.theme` | string | "light", "dark"     | "dark"  | Theme hint for plots (colors, grid, ticks). Does not affect raw metrics/CSV.                              |

### Notes

* To capture specific channels, set `cable_modem.pnm_parameters.capture.channel_ids`. Empty or missing means all channels.

### Example Request - `/getCapture`

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
    "snmp": {
      "snmpV2C": { "community": "private" }
    }
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

### Abbreviated Example - `/getCapture`

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
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 10,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1762618532
        },
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "channel_id": 160,
        "frequency_unit": "Hz",
        "shannon_min_unit": "dB",
        "profiles": [
          {
            "profile_id": 3,
            "carrier_values": {
              "layout": "split",
              "frequency": [],
              "modulation": [],
              "shannon_min_mer": []
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
          "file_type_version": 10,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1762618532
        },
        "channel_id": 160,
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "subcarrier_zero_frequency": 683600000,
        "first_active_subcarrier_index": 1108,
        "subcarrier_spacing": 50000,
        "num_profiles": 4,
        "profile_data_length_bytes": 1084,
        "profiles": [
          {
            "profile_id": 3,
            "schemes": [
              {
                "schema_type": 0,
                "modulation_order": "qam_4096",
                "num_subcarriers": 37
              },
              {
                "schema_type": 0,
                "modulation_order": "continuous_pilot",
                "num_subcarriers": 1
              }
            ]
          }
        ]
      }
    ],
    "measurement_stats": [
      {
        "index": 160,
        "channel_id": 160,
        "entry": {
          "docsPnmCmDsOfdmModProfFileEnable": true,
          "docsPnmCmDsOfdmModProfMeasStatus": "sample_ready",
          "docsPnmCmDsOfdmModProfFileName": "ds_ofdm_modulation_profile_aabbccddeeff_160_1762618536.bin"
        }
      }
    ]
  }
}
```

## Return Structure

### Top-Level Envelope

| Field         | Type         | Description                                                               |
| ------------- | ------------ | ------------------------------------------------------------------------- |
| `mac_address` | string       | Request echo of the modem MAC.                                            |
| `status`      | int          | 0 on success, non-zero on error.                                          |
| `message`     | string\|null | Optional message describing status.                                       |
| `data`        | object       | Container for results (`analysis`, `primative`, `measurement_stats`).     |

### `data.analysis[]`

Per-channel analysis view aligned to your typed modulation-profile model.

| Field                                     | Type    | Description                                                                |
| ----------------------------------------- | ------- | -------------------------------------------------------------------------- |
| device_details.*                          | object  | System descriptor captured at analysis time.                               |
| pnm_header.*                              | object  | PNM header (type, version, capture time).                                  |
| mac_address                               | string  | MAC address (`aa:bb:cc:dd:ee:ff`).                                         |
| channel_id                                | int     | OFDM downstream channel ID.                                                |
| frequency_unit                            | string  | Unit for `carrier_values.frequency` (e.g., `"Hz"`).                        |
| shannon_min_unit                          | string  | Unit for `carrier_values.shannon_min_mer` (typically `"dB"`).              |
| profiles[].profile_id                     | int     | Profile identifier (e.g., `0`, `3`, `4`, `255`).                           |
| profiles[].carrier_values.layout          | string  | Layout hint (e.g., `"split"` for multi-array layout).                      |
| profiles[].carrier_values.frequency       | array   | Per-carrier center frequency values.                                       |
| profiles[].carrier_values.modulation      | array   | Per-carrier modulation (e.g., `"qam_256"`, `"qam_4096"`, `"continuous_pilot"`). |
| profiles[].carrier_values.shannon_min_mer | array   | Per-carrier minimum MER required to support the configured modulation.     |

### `data.primative[]`

Normalized raw capture for export/plotting.

| Field                         | Type     | Description                                       |
| ----------------------------- | -------- | ------------------------------------------------- |
| status                        | string   | Result for this capture (e.g., `SUCCESS`).        |
| pnm_header.*                  | object   | PNM header (type, version, capture time).         |
| channel_id                    | int      | Channel ID.                                       |
| mac_address                   | string   | MAC address.                                      |
| num_profiles                  | int      | Number of profiles present.                       |
| subcarrier_zero_frequency     | int (Hz) | Frequency of subcarrier index 0.                  |
| first_active_subcarrier_index | int      | Index of first active subcarrier.                 |
| subcarrier_spacing            | int (Hz) | Spacing between subcarriers (e.g., 50 kHz).       |
| profile_data_length_bytes     | int      | Length of encoded profile payload in bytes.       |
| profiles[]                    | array    | Raw profile schemes (per profile).                |
| profiles[].profile_id         | int      | Profile identifier.                               |
| profiles[].schemes[]          | array    | Modulation partitions within this profile.        |
| profiles[].schemes[].schema_type | int   | Internal type (commonly `0`).                     |
| profiles[].schemes[].modulation_order | string | Modulation/carry type string. Values map to `ModulationOrderType`. |
| profiles[].schemes[].num_subcarriers | int | Number of subcarriers using this scheme.          |

#### ModulationOrderType enum

`profiles[].schemes[].modulation_order` corresponds to these symbolic names:

| Name               | Value |
| ------------------ | ----- |
| `zero_bit_loaded`  | 0     |
| `continuous_pilot` | 1     |
| `qpsk`             | 2     |
| `reserved_3`       | 3     |
| `qam_16`           | 4     |
| `reserved_5`       | 5     |
| `qam_64`           | 6     |
| `qam_128`          | 7     |
| `qam_256`          | 8     |
| `qam_512`          | 9     |
| `qam_1024`         | 10    |
| `qam_2048`         | 11    |
| `qam_4096`         | 12    |
| `qam_8192`         | 13    |
| `qam_16384`        | 14    |
| `exclusion`        | 16    |
| `plc`              | 20    |

### `data.measurement_stats[]`

Snapshot of CM modulation-profile capture state via SNMP at capture time.

| Field                                        | Type    | Description                                             |
| -------------------------------------------- | ------- | ------------------------------------------------------- |
| index                                        | int     | SNMP table row index.                                   |
| channel_id                                   | int     | OFDM downstream channel ID.                             |
| entry.docsPnmCmDsOfdmModProfFileEnable      | boolean | Whether CM capture-to-file was enabled.                 |
| entry.docsPnmCmDsOfdmModProfMeasStatus      | string  | Measurement status (e.g., `"sample_ready"`).            |
| entry.docsPnmCmDsOfdmModProfFileName        | string  | Device-side filename of the profile payload.            |

## Analysis

The same `/getCapture` endpoint returns both:

* `data.primative[]` - normalized raw profile structures (subcarrier ranges, schemes, counts).  
* `data.analysis[]` - frequency-aligned per-carrier view with layout and Shannon-min MER context.

### Example Request - With Analysis Controls

```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": { "snmpV2C": { "community": "private" } }
  },
  "analysis": {
    "type": "basic",
    "output": { "type": "json" },
    "plot": { "ui": { "theme": "dark" } }
  }
}
```

### Abbreviated Example - Analysis-Focused View

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "data": {
    "analysis": [
      {
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 10,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1762501000
        },
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "channel_id": 197,
        "frequency_unit": "Hz",
        "shannon_min_unit": "dB",
        "profiles": [
          {
            "profile_id": 4,
            "carrier_values": {
              "layout": "split",
              "frequency": [1225000000],
              "modulation": ["qam_4096"],
              "shannon_min_mer": [36.12]
            }
          }
        ]
      }
    ]
  }
}
```

### Output Types

| JSON path              | Allowed values    | Description                                                                    |
| ---------------------- | ----------------- | ------------------------------------------------------------------------------ |
| `analysis.type`        | "basic"         | Static profile decoding with optional Shannon/MER context.                     |
| `analysis.output.type` | "json", "archive" | `json` returns structured data; `archive` returns ZIP (CSV + PNG plots).      |

## Matplot Plotting

These images are generated when `analysis.output.type = "archive"` and plotting is enabled.

| Plot type           | Examples (Profiles 0 and 3)                                                                                                         | Description                                          |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Bits-Per-Symbol     | [Profile 0](./images/modulation-profile/profile-0-bps-modulation-profile.png) &#124; [Profile 3](./images/modulation-profile/profile-3-bps-modulation-profile.png) | Bits-per-symbol vs subcarrier or frequency.         |
| Profile Segments    | [Profile 0](./images/modulation-profile/profile-0-mqam-modulation-profile.png) &#124; [Profile 3](./images/modulation-profile/profile-3-mqam-modulation-profile.png) | Modulation partitions across the OFDM carriers.     |
| Shannon-MER Context | [Profile 0](./images/modulation-profile/profile-0-shannon-mer-modulation-profile.png) &#124; [Profile 3](./images/modulation-profile/profile-3-shannon-mer-modulation-profile.png) | Shannon / minimum MER requirement versus frequency. |

Additional images for other profiles (for example, `profile-1-*.png`) follow the same naming pattern:
`profile-<profile_id>-<plot>-modulation-profile.png`.

## Differences Between Capture And Analysis

| Feature               | `/getCapture`                                | Analysis View (`data.analysis[]`)                          |
| --------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| Primary Output        | Raw profile structures and scheme partitions | Per-carrier frequency, modulation, Shannon-min MER         |
| Channel Coverage      | Captures all OFDM profiles                   | Breaks down per-profile to subcarrier-level detail         |
| Output Format Options | JSON (or Archive via analysis controls)      | Same envelope; JSON or Archive (CSV + PNG)                 |
| Analysis Mode         | Not applicable without `analysis.*`          | "basic" (additional analysis types planned)              |
| Best Use Case         | Profile decoding and metadata inspection     | Visualization, modeling, advanced modulation diagnostics   |
