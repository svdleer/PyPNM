# PNM Operations - Downstream OFDM Histogram

Nonlinearity Insight From Time‑Domain Sample Distributions (Amplifier Compression, Laser Clipping).

## Overview

[`CmDsHistogram`](http://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsHist.py)
controls the CM to run a downstream histogram capture, retrieves the result file, and parses per‑bin hit counts and dwell
metadata into a typed model ready for analysis and plotting (PDF‑like two‑sided histograms, symmetry checks, and clip
detection heuristics).

## Endpoint

`POST /docs/pnm/ds/ofdm/histogram/getCapture`

## Request

Refer to [Common → Request](../../common/request.md).  
**Deltas (Analysis‑Only Additions):** optional `analysis`, `analysis.output`, and `analysis.plot.ui` controls (same pattern as RxMER).

### Delta Table

| JSON path                | Type   | Allowed values / format | Default | Description                                                                                               |
| ------------------------ | ------ | ----------------------- | ------- | --------------------------------------------------------------------------------------------------------- |
| `analysis.type`          | string | "basic"                 | "basic" | Selects the analysis mode used during capture processing.                                                 |
| `analysis.output.type`   | string | "json", "archive"       | "json"  | Output format: **`json`** returns inline `data`; **`archive`** returns a ZIP (CSV exports and PNG plots). |
| `analysis.plot.ui.theme` | string | "light", "dark"         | "dark"  | Theme hint for plot generation (colors, grid, ticks). Does not affect raw metrics/CSV.                    |

### Capture Settings

| JSON path                              | Type | Default | Description                                                                 |
| -------------------------------------- | ---- | ------- | --------------------------------------------------------------------------- |
| `capture_settings.sample_duration_sec` | int  | 10      | Time window for capture, in seconds.                                        |
| `capture_settings.bin_count`           | int  | 256     | Number of equally spaced bins (often 255 or 256 depending on CM).          |

### Notes

* The CM accumulates hits per bin across the capture window. Dwell count is typically uniform per bin for equal sampling.  
* A clipped transmitter path often shows one‑sided truncation and a spike in an end bin.  
* Capture ends on command, timeout, or 32‑bit dwell counter overflow.
* `pnm_parameters.capture.channel_ids` is not supported for this endpoint.

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
    "sample_duration_sec": 10
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
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 5,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1762408557
        },
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "symmetry": 2,
        "dwell_counts": [1406249999],
        "hit_counts": [0, 1, 3, 7, 12, 7, 3, 1, 0]
      }
    ],
    "measurement_stats": [
      {
        "index": 2,
        "entry": {
          "docsPnmCmDsHistEnable": true,
          "docsPnmCmDsHistTimeOut": 10,
          "docsPnmCmDsHistMeasStatus": "sample_ready",
          "docsPnmCmDsHistFileName": "ds_histogram_aa_bb_cc_dd_ee_ff_0_1762408548.bin"
        }
      }
    ]
  }
}
```

## Return Structure

### Top‑Level Envelope

| Field         | Type            | Description                                                               |
| ------------- | --------------- | ------------------------------------------------------------------------- |
| `mac_address` | string          | Request echo of the modem MAC.                                            |
| `status`      | int             | 0 on success, non‑zero on error.                                          |
| `message`     | string \| null | Optional message describing status.                                        |
| `data`        | object          | Container for results (`analysis`, `primative`, `measurement_stats`).     |

### `data.analysis[]`

Per‑capture analysis aligned to the typed Histogram model.

| Field            | Type            | Description                                                                 |
| ---------------- | --------------- | --------------------------------------------------------------------------- |
| device_details.* | object          | System descriptor at analysis time.                                         |
| pnm_header.*     | object          | PNM header (type, version, capture time).                                   |
| mac_address      | string          | MAC address (`aa:bb:cc:dd:ee:ff`).                                          |
| bin_count        | int             | Number of histogram bins.                                                   |
| dwell_counts     | array(integer)  | Samples per bin observed over the duration (usually uniform).               |
| symmetry         | int             | Symmetry flag from the device (implementation-defined).                     |
| hit_counts       | array(integer)  | Hit counts per bin (length = `bin_count`).                                  |

### `data.measurement_stats[]`

Snapshot of CM histogram configuration and state via SNMP at capture time.

| Field                           | Type    | Description                                         |
| ------------------------------ | ------- | --------------------------------------------------- |
| index                          | int     | SNMP table row index.                               |
| entry.docsPnmCmDsHistEnable    | boolean | Whether histogram measurement is enabled.           |
| entry.docsPnmCmDsHistTimeOut   | int     | Requested capture timeout (seconds).                |
| entry.docsPnmCmDsHistMeasStatus| string  | Measurement status (e.g., `sample_ready`).          |
| entry.docsPnmCmDsHistFileName  | string  | Device‑side filename of the capture.                |

## Matplot Plotting

| Plot                                                       | Description                                                          |
| ---------------------------------------------------------- | -------------------------------------------------------------------- |
| [Histogram (Typical)](images/histogram/ds-histogram.png) | Bell‑shaped, symmetric distribution (healthy frontend, no clipping). |

## Example Use Case

A plant engineer sees intermittent downstream packet loss. Running the histogram capture reveals a clipped right tail,
implicating laser clipping at the optical transmitter. Power is adjusted and clipping disappears in follow‑up captures.
