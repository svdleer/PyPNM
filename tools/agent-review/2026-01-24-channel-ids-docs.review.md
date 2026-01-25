## Agent Review Bundle Summary
- Goal: Align channel_ids documentation with endpoints that support channel scoping.
- Changes: Add channel_ids notes and examples for DS histogram and US OFDMA pre-equalization endpoints.
- Files: docs/api/fast-api/single/ds/histogram.md, docs/api/fast-api/single/us/ofdma/pre-equalization.md
- Tests: Not run.
- Notes: Review bundle includes full contents of modified files.

# FILE: docs/api/fast-api/single/ds/histogram.md
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
        "channel_ids": [193, 194]
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

# FILE: docs/api/fast-api/single/us/ofdma/pre-equalization.md
# PNM Operations - Upstream OFDMA Pre-Equalization

This API retrieves DOCSIS 3.1 upstream OFDMA pre-equalization data, which is crucial for identifying plant impairments such as group delay, micro-reflections, and impedance mismatch. It captures and decodes the in-channel frequency response of a modem's upstream OFDMA transmission.

Use this interface for proactive diagnostics and signal integrity assessments across active upstream channels.

In practical terms, the modem applies a transmit-side pre-equalizer to shape its upstream signal, while the CMTS runs an adaptive equalizer on the received signal. Together, these two equalizers describe the linear behavior of the upstream plant for a given modem. PyPNM focuses on exposing the modem-side pre-equalization coefficients and mapping them into frequency-domain views (magnitude, group delay, and complex I/Q) that are easier to interpret than raw fixed‑point taps.

## Table of Contents

* [Get Capture](#get-capture)
* [Request](#request)
* [Response](#response)
* [Plots](#plots)
* [Notes](#notes)

## Get Capture

### Endpoint

**POST** `/docs/pnm/us/ofdma/preEqualization/getCapture`

Retrieves OFDMA upstream pre-equalization complex coefficients from a DOCSIS 3.1 cable modem for PNM diagnostics.

## Request

The request follows the standard structure described in [Common → Request](../../../common/request.md).  
This endpoint is SNMP-based; TFTP parameters are not required for capture, but may still be present in the common schema.

### Example Request Body

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
        "channel_ids": [42]
      }
    },
    "snmp": {
      "snmpV2C": {
        "community": "private"
      }
    }
  },
  "analysis": {
    "type": "basic",
    "output": {
      "type": "json"
    },
    "plot": {
      "ui": {
        "theme": "dark"
      }
    }
  }
}
```

### Request Fields

| Field                                    | Type   | Description                                               |
|------------------------------------------|--------|-----------------------------------------------------------|
| mac_address                              | string | MAC address of the cable modem                            |
| ip_address                               | string | IP address of the cable modem                             |
| pnm_parameters.capture.channel_ids       | array  | Optional list of OFDMA upstream channel IDs to capture    |
| snmp                                     | object | SNMPv2c or SNMPv3 credentials                             |
| analysis                                 | object | Optional analysis and plot configuration for this capture |

For additional shared fields (timeouts, retries, etc.), see [Common → Request](../../../common/request.md).

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../common/response.md) (`mac_address`, `status`, `message`, `data` or `measurement`).

### Example Response Body

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "measurement": {
    "data": [
      {
        "status": "SUCCESS",
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 6,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1751781817
        },
        "upstream_channel_id": 42,
        "cm_mac_address": "aa:bb:cc:dd:ee:ff",
        "cmts_mac_address": "aa:bb:cc:dd:ee:ff",
        "subcarrier_zero_frequency": 104800000,
        "first_active_subcarrier_index": 74,
        "subcarrier_spacing": 50000,
        "value_length": 7584,
        "value_unit": "[Real, Imaginary]",
        "values": [
          [1.0764, 0.6097],
          ["...", "..."]
        ]
      }
    ]
  }
}
```

### Key Response Fields

| Field                           | Type    | Description                                         |
|---------------------------------|---------|-----------------------------------------------------|
| mac_address                     | string  | MAC address used in the request                     |
| status                          | integer | 0 = success                                         |
| measurement.data                | array   | List of measurement entries per capture             |
| ↳ status                        | string  | Capture status (for example, `SUCCESS`)             |
| ↳ upstream_channel_id           | integer | Channel ID associated with this capture             |
| ↳ cm_mac_address                | string  | Cable modem MAC address                             |
| ↳ cmts_mac_address              | string  | CMTS MAC address                                    |
| ↳ subcarrier_zero_frequency     | integer | Base frequency (Hz) of subcarrier 0                 |
| ↳ first_active_subcarrier_index | integer | Index of first active subcarrier                    |
| ↳ subcarrier_spacing            | integer | Frequency spacing between subcarriers in Hz         |
| ↳ value_length                  | integer | Total number of subcarriers represented             |
| ↳ value_unit                    | string  | Format of data (for example, `[Real, Imaginary]`)   |
| ↳ values                        | array   | List of complex coefficient pairs per subcarrier    |

Each `values` entry represents a decoded complex tap coefficient used for plant characterization.

## Plots

When `analysis` and `analysis.plot.ui` are provided, this endpoint also generates per-channel plots from the captured OFDMA pre-equalization data. Internally, PyPNM can present both the **pre-equalizer coefficients** and any **equalizer coefficient updates** using the same plot families, although the current implementation focuses on the CM pre-equalizer side.

### Pre-Equalizer Coefficient Views

| View Type  | Description |
|------------|-------------|
| [Magnitude with Fit](images/pre-eq/42_us_preeq_magnitude.png) | Magnitude vs. Frequency with regression line overlay, showing overall tilt or slope               |
| [Group Delay](images/pre-eq/42_us_preeq_groupdelay.png)       | Group delay vs. Frequency derived from the complex carrier values                                 |
| [IFFT Impulse Response](images/pre-eq/42_us_preeq_ifft.png)   | Time-domain impulse response \|h(t)\| (first 5 µs) derived from the pre-equalization coefficients |
| [IQ Scatter](images/pre-eq/42_us_preeq_iqscatter.png)         | Complex scatter of in-phase (I) vs. quadrature (Q) coefficients                                   |

### Pre-Equalizer Coefficient Update Views

In systems where CMTS equalizer update taps are available, the same plot families can be used to visualize how the network requests the modem to adjust its pre-equalizer:

| View Type  | Description |
|------------|-------------|
| [Magnitude with Fit](images/pre-eq/42_us_preeq_magnitude.png) | Magnitude vs. Frequency with regression line overlay, showing overall tilt or slope               |
| [Group Delay](images/pre-eq/42_us_preeq_groupdelay.png)       | Group delay vs. Frequency derived from the complex carrier values                                 |
| [IFFT Impulse Response](images/pre-eq/42_us_preeq_ifft.png)   | Time-domain impulse response \|h(t)\| (first 5 µs) derived from the pre-equalization coefficients |
| [IQ Scatter](images/pre-eq/42_us_preeq_iqscatter.png)         | Complex scatter of in-phase (I) vs. quadrature (Q) coefficients                                   |

Details:

- **Magnitude with Regression Line** - Uses the raw magnitude series and a per-subcarrier regression fit to show overall tilt or slope across the upstream OFDMA band.
- **Group Delay** - Plots group delay (microseconds) derived from the pre-equalization coefficients, useful for detecting echoes and dispersion.
- **IQ Complex Scatter Plot** - Visualizes the complex coefficient distribution in the I/Q plane, highlighting asymmetries or clustering caused by plant impairments or correction requests.

Plot theme (dark or light) and styling are controlled via the common `analysis.plot.ui` block, consistent with other PyPNM analysis endpoints.

## Notes

* This endpoint is part of the proactive diagnostics suite used to assess in-channel echo and group delay distortion.
* Each element of `values` contains I/Q (real/imaginary) components per subcarrier.
* Timing information and versioning are provided via the `pnm_header` block, which follows the standard PNN header format.
* To capture specific channels, set `cable_modem.pnm_parameters.capture.channel_ids`. Empty or missing means all channels.
