# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

from __future__ import annotations

from pydantic import BaseModel, Field

from pypnm.api.routes.common.classes.common_endpoint_classes.common_req_resp import (
    TftpConfig,
)
from pypnm.lib.types import IPv4Str, MacAddressStr


class CmtsConfig(BaseModel):
    """CMTS Configuration for UTSC"""
    cmts_ip: IPv4Str = Field(description="CMTS IP address for SNMP commands")
    rf_port_ifindex: int = Field(description="RF port interface index on CMTS")
    community: str = Field(default="private", description="SNMP write community for CMTS")


class UtscTriggerConfig(BaseModel):
    """UTSC Trigger Configuration (optional for CM MAC trigger mode)"""
    cm_mac: MacAddressStr | None = Field(default=None, description="Cable modem MAC address (required for trigger mode 6)")
    logical_ch_ifindex: int | None = Field(default=None, description="Logical channel ifIndex for trigger (SC-QAM or OFDMA)")


class UtscCaptureParameters(BaseModel):
    """UTSC Capture Parameters"""
    trigger_mode: int = Field(default=2, description="Trigger mode: 2=FreeRunning, 6=CM MAC Address")
    center_freq_hz: int = Field(default=30000000, description="Center frequency in Hz (5-85 MHz typical)")
    span_hz: int = Field(default=80000000, description="Frequency span in Hz")
    num_bins: int = Field(default=800, description="Number of FFT bins")
    filename: str = Field(default="utsc_capture", description="Base filename for results")


class UtscAnalysisConfig(BaseModel):
    """Analysis output configuration"""
    output_type: str = Field(default="json", description="Output format: json or archive")


class UtscRequest(BaseModel):
    """Main UTSC Request Schema"""
    cmts: CmtsConfig = Field(description="CMTS configuration")
    tftp: TftpConfig = Field(description="TFTP server for file retrieval")
    trigger: UtscTriggerConfig = Field(default=UtscTriggerConfig(), description="Trigger configuration")
    capture_parameters: UtscCaptureParameters = Field(default=UtscCaptureParameters(), description="Capture parameters")
    analysis: UtscAnalysisConfig = Field(default=UtscAnalysisConfig(), description="Analysis configuration")


class UtscResponse(BaseModel):
    """UTSC Response Schema"""
    success: bool
    cmts_ip: str | None = None
    rf_port_ifindex: int | None = None
    filename: str | None = None
    error: str | None = None
    data: dict | None = None
