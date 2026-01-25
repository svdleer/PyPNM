# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

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
    """UTSC Capture Parameters - validated against E6000 CER I-CCAP User Guide Release 13.0
    
    Reference: docsPnmCmtsUtscCfgTable from DOCS-PNM-MIB
    E6000 supports: FreeRunning(2), IdleSID(5), cmMAC(6) trigger modes
    """
    trigger_mode: Literal[2, 5, 6] = Field(
        default=2,
        description="Trigger mode: 2=FreeRunning (Wideband FFT), 5=IdleSID (Narrowband FFT), 6=cmMAC (Narrowband FFT)"
    )
    center_freq_hz: int = Field(
        default=42500000,
        ge=0, le=204000000,
        description="Center frequency in Hz (0-204 MHz for Wideband, 0-102 MHz for Narrowband). Must be multiple of 50 kHz."
    )
    span_hz: int = Field(
        default=80000000,
        description="Frequency span in Hz. Wideband FFT: 80/160/320 MHz. Narrowband FFT: 40/80 MHz. TimeIQ: 102.4/204.8 MHz"
    )
    num_bins: Literal[200, 256, 400, 512, 800, 1024, 1600, 2048, 3200] = Field(
        default=800,
        description="Number of FFT bins. Non-TimeIQ: 200, 400, 800, 1600, 3200. TimeIQ: 256, 512, 1024, 2048"
    )
    filename: str = Field(
        default="utsc_capture",
        max_length=255,
        description="Base filename (no path). Files saved to TFTP root. Timestamp appended automatically."
    )
    repeat_period_ms: int = Field(
        default=50,
        ge=0, le=1000,
        description="Repeat period in ms (0-1000). E6000 minimum: 50ms for FreeRunning. 0=capture once (FreeRunDuration ignored). 1-49=hardware-restricted mode. 50-1000=50ms granularity."
    )
    freerun_duration_ms: int = Field(
        default=60000,
        ge=1000, le=600000,
        description="FreeRunning duration in ms (1s-10min). Ignored if repeat_period_ms=0."
    )
    trigger_count: int = Field(
        default=1,
        ge=1, le=10,
        description="Number of captures for IdleSID/cmMAC modes (1-10). Value 0 not supported. Ignored for FreeRunning."
    )
    output_format: Literal[1, 2, 4, 5] = Field(
        default=2,
        description="Output format: 1=timeIQ, 2=fftPower (required for repeat_period 1-49ms), 4=fftIQ, 5=fftAmplitude"
    )
    window: Literal[2, 3, 4, 5] = Field(
        default=2,
        description="Window function: 2=rectangular, 3=hann, 4=blackmanHarris, 5=hamming"
    )
    
    @field_validator('center_freq_hz')
    @classmethod
    def validate_center_freq(cls, v: int) -> int:
        """Validate center frequency is multiple of 50 kHz"""
        if v % 50000 != 0:
            raise ValueError(f"Center frequency must be multiple of 50 kHz, got {v} Hz")
        return v
    
    @field_validator('span_hz')
    @classmethod
    def validate_span(cls, v: int) -> int:
        """Validate span is one of supported values"""
        # Wideband FFT (non-TimeIQ): 80, 160, 320 MHz
        # Narrowband FFT (non-TimeIQ): 40, 80 MHz
        # TimeIQ: 102.4, 204.8 MHz
        valid_spans_hz = [
            40000000, 80000000, 160000000, 320000000,  # Non-TimeIQ
            102400000, 204800000  # TimeIQ
        ]
        if v not in valid_spans_hz:
            raise ValueError(f"Span must be one of {[s//1000000 for s in valid_spans_hz]} MHz, got {v/1000000} MHz")
        return v
    
    @field_validator('filename')
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Validate and normalize filename format"""
        if not v:
            raise ValueError("Filename cannot be empty")
        # E6000 accepts: "", "/pnm/utsc/filename", or "filename"
        # We use just the filename - TFTP server expects files in /var/lib/tftpboot directly
        if v.startswith('/pnm/utsc/'):
            v = v.replace('/pnm/utsc/', '')
        if v.startswith('/'):
            v = v.lstrip('/')
        return v
    
    @model_validator(mode='after')
    def validate_parameter_combinations(self):
        """Cross-validate parameter combinations per E6000 constraints"""
        # fftPower is required for repeat_period 1-49ms
        if 1 <= self.repeat_period_ms <= 49 and self.output_format != 2:
            raise ValueError(f"output_format must be 2 (fftPower) when repeat_period_ms is 1-49, got {self.output_format}")
        
        # Narrowband FFT (trigger modes 5, 6) has lower center freq limit
        if self.trigger_mode in (5, 6) and self.center_freq_hz > 102000000:
            raise ValueError(f"Narrowband FFT (trigger modes 5,6) max center_freq is 102 MHz, got {self.center_freq_hz/1000000} MHz")
        
        return self


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
