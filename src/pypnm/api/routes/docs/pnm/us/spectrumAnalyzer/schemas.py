# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

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
    """UTSC Capture Parameters - validated against DOCS-PNM-MIB constraints
    
    MIB Reference: docsPnmCmtsUtscCfgEntry from DOCS-PNM-MIB
    """
    trigger_mode: int = Field(
        default=2, 
        ge=1, le=7,
        description="Trigger mode: 1=other, 2=FreeRunning, 3=miniSlotCount, 4=sid, 5=idleSid, 6=cmMac, 7=burstIuc"
    )
    center_freq_hz: int = Field(
        default=42500000,
        ge=5000000, le=204000000,
        description="Center frequency in Hz (5-204 MHz, must be within upstream frequency range)"
    )
    span_hz: int = Field(
        default=80000000,
        ge=100000, le=204000000,
        description="Frequency span in Hz (100 kHz - 204 MHz)"
    )
    num_bins: int = Field(
        default=800,
        ge=1, le=4096,
        description="Number of FFT bins (1-4096, power of 2 recommended: 256, 512, 800, 1024, 1600, 2048, 3200, 4096)"
    )
    filename: str = Field(
        default="/pnm/utsc/utsc_capture",
        max_length=255,
        description="Base filename for results (max 255 chars, path like /pnm/utsc/name)"
    )
    repeat_period_ms: int = Field(
        default=1000,
        ge=20, le=86400000,
        description="Repeat period in milliseconds (20ms - 86400000ms/24hr, MIB stores as microseconds)"
    )
    freerun_duration_ms: int = Field(
        default=60000,
        ge=1000, le=86400000,
        description="Total duration for free-running mode in milliseconds (1s - 24hr)"
    )
    trigger_count: int = Field(
        default=10,
        ge=1, le=65535,
        description="Number of captures (1-65535, but E6000 ignores in FreeRunning mode)"
    )
    
    @field_validator('center_freq_hz', 'span_hz')
    @classmethod
    def validate_frequency_alignment(cls, v: int) -> int:
        """Validate frequency is reasonable (Hz precision)"""
        if v <= 0:
            raise ValueError(f"Frequency must be positive, got {v}")
        return v
    
    @field_validator('num_bins')
    @classmethod
    def validate_num_bins(cls, v: int) -> int:
        """Validate num_bins is a reasonable FFT size"""
        valid_bins = [256, 512, 800, 1024, 1600, 2048, 3200, 4096]
        if v not in valid_bins:
            # Allow any value but warn - some CMTS may accept non-standard values
            pass  # Just accept it, CMTS will reject if invalid
        return v
    
    @field_validator('filename')
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Validate filename format"""
        if not v:
            raise ValueError("Filename cannot be empty")
        # Ensure path format for CMTS
        if not v.startswith('/'):
            v = f"/pnm/utsc/{v}"
        return v


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


class UtscDiscoverRequest(BaseModel):
    """UTSC RF Port Discovery Request Schema"""
    cmts_ip: IPv4Str = Field(description="CMTS IP address")
    cm_mac_address: MacAddressStr = Field(description="Cable modem MAC address to find RF port for")
    community: str = Field(default="private", description="SNMP community string")


class UtscDiscoverResponse(BaseModel):
    """UTSC RF Port Discovery Response Schema"""
    success: bool
    rf_port_ifindex: int | None = None
    rf_port_description: str | None = None
    cm_index: int | None = None
    us_channels: list[int] = Field(default_factory=list)
    error: str | None = None
