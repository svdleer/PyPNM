## Agent Review Bundle Summary
- Goal: Remove channel scoping from downstream histogram requests.
- Changes: Add endpoint-specific request model without capture channel IDs, update router usage, adjust docs, and add pytest coverage.
- Files: src/pypnm/api/routes/docs/pnm/ds/histogram/schemas.py, src/pypnm/api/routes/docs/pnm/ds/histogram/router.py, docs/api/fast-api/single/ds/histogram.md, tests/test_histogram_single_capture_schema.py
- Tests: Not run.
- Notes: Review bundle includes full contents of modified files.

# FILE: src/pypnm/api/routes/docs/pnm/ds/histogram/schemas.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from pypnm.api.routes.common.classes.common_endpoint_classes.common_req_resp import (
    CommonSingleCaptureAnalysisType,
    TftpConfig,
    default_ip,
    default_mac,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.schema.base_snmp import (
    SNMPConfig,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.schemas import (
    PnmMeasurementResponse,
    PnmRequest,
    PnmSingleCaptureRequest,
)
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import InetAddressStr, MacAddressStr


class HistogramCaptureSettings(BaseModel):
    sample_duration:int = Field(default=10, description="Histogram Sample Duration in seconds")

class PnmHistogramRequest(PnmRequest):
    capture_settings: HistogramCaptureSettings = Field(description="Histogram Capture Settings")

class PnmHistogramResponse(PnmMeasurementResponse):
    """Generic response container for most PNM operations."""

class HistogramPnmParameters(BaseModel):
    tftp: TftpConfig = Field(..., description="TFTP configuration")
    model_config = {"extra": "forbid"}

class HistogramCableModemConfig(BaseModel):
    mac_address: MacAddressStr             = Field(default=default_mac, description="MAC address of the cable modem")
    ip_address: InetAddressStr             = Field(default=default_ip, description="Inet address of the cable modem")
    pnm_parameters: HistogramPnmParameters = Field(description="PNM parameters such as TFTP server configuration")
    snmp: SNMPConfig                       = Field(description="SNMP configuration")

    @field_validator("mac_address")
    def validate_mac(cls, v: str) -> MacAddressStr:
        try:
            return MacAddress(v).mac_address
        except Exception as e:
            raise ValueError(f"Invalid MAC address: {v}, reason: ({e})") from e

class PnmHistogramSingleCaptureRequest(BaseModel):
    cable_modem: HistogramCableModemConfig     = Field(description="Cable modem configuration")
    analysis: CommonSingleCaptureAnalysisType  = Field(description="Single capture analysis configuration")
    capture_settings: HistogramCaptureSettings = Field(description="Histogram Capture Settings")

class PnmHistogramAnalysisRequest(PnmSingleCaptureRequest):
    capture_settings: HistogramCaptureSettings = Field(description="Histogram Capture Settings")

# FILE: src/pypnm/api/routes/docs/pnm/ds/histogram/router.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter
from starlette.responses import FileResponse

from pypnm.api.routes.basic.abstract.analysis_report import AnalysisRptMatplotConfig
from pypnm.api.routes.basic.histrogram_analysis_rpt import DsHistrogramReport
from pypnm.api.routes.common.classes.analysis.analysis import Analysis, AnalysisType
from pypnm.api.routes.common.classes.common_endpoint_classes.common.enum import (
    OutputType,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.request_defaults import (
    RequestDefaultsResolver,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.schemas import (
    PnmAnalysisResponse,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.snmp.schemas import (
    SnmpResponse,
)
from pypnm.api.routes.common.classes.operation.cable_modem_precheck import (
    CableModemServicePreCheck,
)
from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.extended.common_process_service import CommonProcessService
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.ds.histogram.schemas import PnmHistogramSingleCaptureRequest
from pypnm.api.routes.docs.pnm.ds.histogram.service import CmDsHistogramService
from pypnm.api.routes.docs.pnm.files.service import FileType, PnmFileService
from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.data_type.pnm.DocsPnmCmDsHistEntry import DocsPnmCmDsHistEntry
from pypnm.lib.dict_utils import DictGenerate
from pypnm.lib.fastapi_constants import FAST_API_RESPONSE
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import InetAddressStr, MacAddressStr


class DsHistogramRouter:
    """
    Router for DOCSIS Downstream Histogram operations following the RxMER design pattern.

    A single endpoint `/getCapture` performs the capture and, based on `request.analysis.output.type`,
    returns either a JSON payload with processed results or an archive (ZIP) report.
    """

    def __init__(self) -> None:
        prefix = "/docs/pnm/ds"
        self.base_endpoint = "/histogram"
        self.router = APIRouter(prefix=prefix, tags=["PNM Operations - Downstream Histogram"])
        self.logger = logging.getLogger(f'DsHistogramRouter.{self.base_endpoint.strip("/")}')
        self.__routes()

    def __routes(self) -> None:
        @self.router.post(
            f"{self.base_endpoint}/getCapture",
            summary="Get Downstream Histogram PNM Capture",
            response_model=None,
            responses=FAST_API_RESPONSE,)

        async def get_capture(request: PnmHistogramSingleCaptureRequest) -> SnmpResponse | PnmAnalysisResponse | FileResponse:
            """
            Capture DOCSIS Downstream Histogram and return results as JSON or archive.

            The endpoint triggers a histogram capture on the cable modem using SNMP

            [API Guide](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/single/ds/histogram.md)
            """
            mac: MacAddressStr = request.cable_modem.mac_address
            ip: InetAddressStr = request.cable_modem.ip_address
            community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
            tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(request.cable_modem.pnm_parameters.tftp)

            sample_duration: int = request.capture_settings.sample_duration

            self.logger.info(
                f"Starting Histogram measurement for MAC: {mac}, IP: {ip}, "
                f"Sample Duration: {request.capture_settings.sample_duration}"
            )

            cm = CableModem(mac_address=MacAddress(mac),
                            inet=Inet(ip),
                            write_community=community)

            status, msg = await CableModemServicePreCheck(cable_modem=cm).run_precheck()
            if status != ServiceStatusCode.SUCCESS:
                self.logger.error(msg)
                return SnmpResponse(mac_address=mac, status=status, message=msg)

            service = CmDsHistogramService(cable_modem=cm,
                                           sample_duration=sample_duration,
                                           tftp_servers=tftp_servers)

            msg_rsp: MessageResponse = await service.set_and_go()

            if msg_rsp.status != ServiceStatusCode.SUCCESS:
                err = "Unable to complete Histogram measurement."
                self.logger.error(err)
                return SnmpResponse(mac_address=mac, message=err, status=msg_rsp.status)

            channel_ids = None
            measurement_stats:list[DocsPnmCmDsHistEntry] = \
                cast(list[DocsPnmCmDsHistEntry],
                    await service.getPnmMeasurementStatistics(channel_ids=channel_ids))

            cps = CommonProcessService(msg_rsp)
            msg_rsp = cps.process()

            analysis = Analysis(AnalysisType.BASIC, msg_rsp)

            if request.analysis.output.type == OutputType.JSON:
                payload: dict[str, Any] = cast(dict[str, Any], analysis.get_results())
                DictGenerate.pop_keys_recursive(payload, ["channel_id"])
                payload.update(DictGenerate.models_to_nested_dict(measurement_stats, 'measurement_stats',))

                return PnmAnalysisResponse(
                    mac_address =   mac,
                    status      =   ServiceStatusCode.SUCCESS,
                    data        =   payload,)

            elif request.analysis.output.type == OutputType.ARCHIVE:
                theme = request.analysis.plot.ui.theme
                plot_config = AnalysisRptMatplotConfig(theme = theme)
                analysis_rpt = DsHistrogramReport(analysis, plot_config)
                rpt: Path = cast(Path, analysis_rpt.build_report())
                return PnmFileService().get_file(FileType.ARCHIVE, rpt.name)

            else:
                return PnmAnalysisResponse(
                    mac_address =   mac,
                    status      =   ServiceStatusCode.INVALID_OUTPUT_TYPE,
                    data        =   {},)


# Required for dynamic auto-registration
router = DsHistogramRouter().router

# FILE: docs/api/fast-api/single/ds/histogram.md
# PNM Operations - Downstream OFDM Histogram

Nonlinearity Insight From Time‑Domain Sample Distributions (Amplifier Compression, Laser Clipping).

## Overview

[`CmDsHistogram`](http://github.com/svdleer/PyPNM/blob/main/src/pypnm/pnm/parser/CmDsHist.py)
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

# FILE: tests/test_histogram_single_capture_schema.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pypnm.api.routes.docs.pnm.ds.histogram.schemas import (
    PnmHistogramSingleCaptureRequest,
)


def test_histogram_schema_rejects_capture_channel_ids() -> None:
    payload = {
        "cable_modem": {
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "ip_address": "192.168.0.100",
            "pnm_parameters": {
                "tftp": {
                    "ipv4": "192.168.0.10",
                    "ipv6": "2001:db8::10",
                },
                "capture": {
                    "channel_ids": [1, 2],
                },
            },
            "snmp": {
                "snmpV2C": {
                    "community": "private",
                },
            },
        },
        "analysis": {
            "type": "basic",
            "output": {"type": "json"},
            "plot": {"ui": {"theme": "dark"}},
        },
        "capture_settings": {
            "sample_duration": 10,
        },
    }

    with pytest.raises(ValidationError):
        PnmHistogramSingleCaptureRequest.model_validate(payload)
