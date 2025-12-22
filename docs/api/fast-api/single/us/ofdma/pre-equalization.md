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
