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
