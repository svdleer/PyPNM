# PyPNM FastAPI - PNM Capture cURL Examples

This guide shows how to invoke PyPNM **PNM capture** endpoints using `curl`. Each example
sends a `POST` request with a JSON body that mirrors the common FastAPI request models.

## Table Of Contents

[Overview](#overview)

[Common Request Template](#common-request-template)

[Downstream OFDM Capture Endpoints](#downstream-ofdm-capture-endpoints)

- [Downstream OFDM RxMER](#downstream-ofdm-rxmer)
- [Downstream OFDM Channel Estimation](#downstream-ofdm-channel-estimation)
- [Downstream OFDM FEC Summary](#downstream-ofdm-fec-summary)
- [Downstream OFDM Modulation Profile](#downstream-ofdm-modulation-profile)
- [Downstream OFDM Constellation Display](#downstream-ofdm-constellation-display)
- [Downstream Spectrum Analysis](#downstream-spectrum-analysis)

[Upstream OFDMA Capture Endpoints](#upstream-ofdma-capture-endpoints)

- [Upstream OFDMA Pre-Equalization](#upstream-ofdma-pre-equalization)

[Programming Notes](#programming-notes)

## Overview

PNM capture endpoints in PyPNM are all **`POST`** operations that accept a JSON body based
on a shared request model (for example, `CommonRequest` / `PnmSingleCaptureRequest`).

Representative routers and services:

- [`CmDsOfdmRxMerService`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/api/routes/docs/pnm/ds/ofdm/rxmer/service.py)
- [`CmDsOfdmChanEstimateCoef`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmChanEstimateCoef.py)
- [`CmDsOfdmFecSummary`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmFecSummary.py)
- [`CmDsOfdmModulationProfile`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsOfdmModulationProfile.py)
- [`CmSpectrumAnalysis`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmSpectrumAnalysis.py)
- [`CmUsOfdmaPreEq`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/pnm/parser/CmUsOfdmaPreEq.py)

The examples focus on **how to structure the JSON** and **how to invoke the endpoints**
with `curl`. Response payloads are typically JSON containing PNM metadata and capture
file information. Archive/plot outputs follow the same request shape but use a different
`analysis.output.type` value.

For all examples below, generic addresses are used:

- Example CM MAC address: `aa:bb:cc:dd:ee:ff`
- Example CM IP address: `192.168.0.100`
- Example TFTP server (IPv4): `192.168.0.200`
- Example TFTP server (IPv6): `::1` (dummy placeholder)

## Common Request Template

Most PNM capture endpoints accept a request with this common structure (simplified).

Key details for the current implementation:

- `analysis.output.type` uses lowercase strings (`"json"`, `"archive"`, etc.).
- `analysis.plot` is required for single-capture analysis routes; RxMER needs at least
  `plot.ui.theme`.
- `pnm_parameters.tftp.ipv6` can safely use a dummy address `::1` if IPv6 is not otherwise used.

```bash
curl -X POST "http://127.0.0.1:8000/<endpoint>"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
      },
      "capture": {
        "channel_ids": []
      }
    }
  },
  "analysis": {
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
JSON
```

You can reuse this block and only change the `<endpoint>` path for each PNM capture.

## Downstream OFDM Capture Endpoints

### Downstream OFDM RxMER

Endpoint:

- `POST /docs/pnm/ds/ofdm/rxMer/getCapture`

This is a **validated RxMER pattern** using the generic MAC/IP/TFTP and the required
`analysis.plot.ui.theme` field:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/ds/ofdm/rxMer/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
      },
      "capture": {
        "channel_ids": []
      }
    }
  },
  "analysis": {
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
JSON
```

The response payload corresponds to the RxMER analysis model returned by your
`Analysis(AnalysisType.BASIC, msg_rsp)` path, combined with RxMER measurement stats.

### Downstream OFDM Channel Estimation

Endpoint:

- `POST /docs/pnm/ds/ofdm/chanEstimate/getCapture`

Channel estimation uses the same overall request shape. If the underlying route uses the
same `CommonAnalysisRequest`, this template should validate:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/ds/ofdm/chanEstimate/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
      },
      "capture": {
        "channel_ids": []
      }
    }
  },
  "analysis": {
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
JSON
```

The JSON response will contain channel-estimation taps and related metadata, aligned with
your `CmDsOfdmChanEstimateCoef` / analysis models.

### Downstream OFDM FEC Summary

Endpoint:

- `POST /docs/pnm/ds/ofdm/fecSummary/getCapture`

Example:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/ds/ofdm/fecSummary/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
      },
      "capture": {
        "channel_ids": []
      }
    }
  },
  "analysis": {
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
JSON
```

The response payload typically includes per-profile and per-subcarrier summary counters
(total codewords, corrected, uncorrectable, etc.).

### Downstream OFDM Modulation Profile

Endpoint:

- `POST /docs/pnm/ds/ofdm/modulationProfile/getCapture`

Example:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/ds/ofdm/modulationProfile/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
      }
    }
  },
  "analysis": {
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
JSON
```

### Downstream OFDM Constellation Display

Endpoint:

- `POST /docs/pnm/ds/ofdm/constellationDisplay/getCapture`

Constellation Display extends the same analysis block with additional plot options
(such as `display_cross_hair`). The example below matches your UI fields:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/ds/ofdm/constellationDisplay/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
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
      },
      "options": {
        "display_cross_hair": true
      }
    }
  },
  "capture_settings": {
    "modulation_order_offset": 0,
    "number_sample_symbol": 8192
  }
}
JSON
```

If you switch the output type to a plot/archive-oriented value in your `OutputType` enum,
you can have this endpoint generate MatPlot reports instead of pure JSON.

### Downstream Spectrum Analysis

Endpoint:

- `POST /docs/pnm/ds/spectrumAnalysis/getCapture`

Example:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/ds/spectrumAnalysis/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
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
    },
    "spectrum_analysis": {
      "moving_average": {
        "points": 10
      }
    }
  },
  "capture_parameters": {
    "inactivity_timeout": 60,
    "first_segment_center_freq": 300000000,
    "last_segment_center_freq": 900000000,
    "segment_freq_span": 1000000,
    "num_bins_per_segment": 256,
    "noise_bw": 150,
    "window_function": 1,
    "num_averages": 1,
    "spectrum_retrieval_type": 1
  }
}
JSON
```

The JSON response will contain spectrum sweep configuration and amplitude bins that map
directly onto the `CmSpectrumAnalysis` / `CmSpectrumAnalysisSnmp` models.

## Upstream OFDMA Capture Endpoints

### Upstream OFDMA Pre-Equalization

Endpoint:

- `POST /docs/pnm/us/ofdma/preEqualization/getCapture`

Example:

```bash
curl -X POST "http://127.0.0.1:8000/docs/pnm/us/ofdma/preEqualization/getCapture"   -H "Content-Type: application/json"   -d @- << 'JSON'
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "snmp": {
      "snmp_v2c": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.200",
        "ipv6": "::1",
        "dest_dir": ""
      }
    }
  },
  "analysis": {
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
JSON
```

The response will include decoded upstream pre-equalizer taps which correspond to the
`CmUsOfdmaPreEqModel` used by the parser examples.

## Programming Notes

- When scripting against these endpoints, it is often convenient to **template** the common
  request body and just substitute MAC/IP/TFTP values.
- The same JSON payloads shown here can be used directly in Postman, Python `requests`,
  or any other HTTP client.
- For automation, you can combine these `curl` invocations with the parser examples in
  `src/pypnm/examples/python/parsers/` to build end-to-end workflows:
  1. Trigger capture via FastAPI.
  2. Download or reference the PNM binary.
  3. Parse with a `Cm*` parser and feed into additional analysis utilities.
