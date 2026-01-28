# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Schemas for CMTS Upstream Triggered Spectrum Capture (UTSC) operations.

This module provides Pydantic models for CMTS-side UTSC measurements
as defined in DOCS-PNM-MIB (docsPnmCmtsUtscCfgTable, docsPnmCmtsUtscCtrlTable,
docsPnmCmtsUtscStatusTable).
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional, List
from pydantic import BaseModel, Field


class TriggerMode(IntEnum):
    """UTSC Trigger Mode (docsPnmCmtsUtscCfgTriggerMode)"""
    OTHER = 1
    FREE_RUNNING = 2
    MINI_SLOT_COUNT = 3
    SID = 4
    IUC = 5
    CM_MAC = 6


class OutputFormat(IntEnum):
    """UTSC Output Format (docsPnmCmtsUtscCfgOutputFormat)"""
    TIME_IQ = 1
    FFT_POWER = 2
    FFT_IQ = 3
    FFT_AMPLITUDE = 4
    FFT_POWER_AND_PHASE = 5
    RAW_ADC = 6


class WindowFunction(IntEnum):
    """UTSC Window Function (docsPnmCmtsUtscCfgWindow)"""
    OTHER = 1
    RECTANGULAR = 2
    HANN = 3
    BLACKMAN_HARRIS = 4
    HAMMING = 5
    FLAT_TOP = 6
    GAUSSIAN = 7
    CHEBYSHEV = 8


class MeasStatus(IntEnum):
    """Measurement Status (docsPnmCmtsUtscStatusMeasStatus)"""
    OTHER = 1
    INACTIVE = 2
    BUSY = 3
    SAMPLE_READY = 4
    ERROR = 5
    RESOURCE_UNAVAILABLE = 6
    SAMPLE_TRUNCATED = 7


class CmtsSnmpConfig(BaseModel):
    """CMTS SNMP configuration."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    community: str = Field(default="private", description="SNMP community string")
    write_community: Optional[str] = Field(default=None, description="SNMP write community (defaults to community)")


class UtscRfPort(BaseModel):
    """RF Port information."""
    rf_port_ifindex: int = Field(..., description="RF Port ifIndex")
    description: Optional[str] = Field(None, description="Port description")
    cfg_index: int = Field(default=1, description="Config table index (usually 1)")


class UtscListPortsRequest(BaseModel):
    """Request to list available RF ports for UTSC."""
    cmts: CmtsSnmpConfig


class UtscListPortsResponse(BaseModel):
    """Response with list of RF ports."""
    success: bool
    rf_ports: List[UtscRfPort] = Field(default_factory=list)
    error: Optional[str] = None


class UtscConfigureRequest(BaseModel):
    """Request to configure UTSC test parameters."""
    cmts: CmtsSnmpConfig
    rf_port_ifindex: int = Field(..., description="RF Port ifIndex")
    cfg_index: int = Field(default=1, description="Config table index (usually 1)")
    
    # Trigger settings
    trigger_mode: int = Field(default=2, ge=1, le=6, description="Trigger mode: 1=other, 2=freeRunning, 3=minislotCount, 4=sid, 5=iuc, 6=cmMac")
    cm_mac_address: Optional[str] = Field(None, description="CM MAC address (required for trigger_mode=6)")
    logical_ch_ifindex: Optional[int] = Field(None, description="Logical channel ifIndex for CM MAC trigger")
    
    # Spectrum settings
    center_freq_hz: int = Field(default=50000000, description="Center frequency in Hz")
    span_hz: int = Field(default=80000000, description="Frequency span in Hz")
    num_bins: int = Field(default=800, description="Number of FFT bins")
    
    # Output settings
    output_format: int = Field(default=2, ge=1, le=6, description="Output format: 1=timeIq, 2=fftPower, 3=fftIq, 4=fftAmplitude, 5=fftPowerAndPhase, 6=rawAdc")
    window_function: int = Field(default=2, ge=1, le=8, description="Window function: 1=other, 2=rectangular, 3=hann, 4=blackmanHarris, 5=hamming, 6=flatTop, 7=gaussian, 8=chebyshev")
    
    # Timing settings
    repeat_period_us: int = Field(default=1000000, description="Repeat period in microseconds")
    freerun_duration_ms: int = Field(default=60000, description="Free run duration in milliseconds")
    trigger_count: int = Field(default=1, description="Trigger count (number of captures)")
    
    # File settings
    filename: str = Field(default="utsc_capture", description="Output filename")
    destination_index: int = Field(default=0, ge=0, description="Bulk transfer destination index (0=local only)")


class UtscConfigureResponse(BaseModel):
    """Response from configuring UTSC."""
    success: bool
    rf_port_ifindex: Optional[int] = None
    cfg_index: Optional[int] = None
    trigger_mode: Optional[int] = None
    filename: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class UtscStartRequest(BaseModel):
    """Request to start UTSC test."""
    cmts: CmtsSnmpConfig
    rf_port_ifindex: int = Field(..., description="RF Port ifIndex")
    cfg_index: int = Field(default=1, description="Config table index")


class UtscStartResponse(BaseModel):
    """Response from starting UTSC test."""
    success: bool
    rf_port_ifindex: Optional[int] = None
    cfg_index: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class UtscStopRequest(BaseModel):
    """Request to stop UTSC test."""
    cmts: CmtsSnmpConfig
    rf_port_ifindex: int = Field(..., description="RF Port ifIndex")
    cfg_index: int = Field(default=1, description="Config table index")


class UtscStopResponse(BaseModel):
    """Response from stopping UTSC test."""
    success: bool
    rf_port_ifindex: Optional[int] = None
    cfg_index: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class UtscStatusRequest(BaseModel):
    """Request to get UTSC status."""
    cmts: CmtsSnmpConfig
    rf_port_ifindex: int = Field(..., description="RF Port ifIndex")
    cfg_index: int = Field(default=1, description="Config table index")


class UtscStatusResponse(BaseModel):
    """Response with UTSC status."""
    success: bool
    rf_port_ifindex: Optional[int] = None
    cfg_index: Optional[int] = None
    meas_status: Optional[int] = None
    meas_status_name: Optional[str] = None
    is_ready: bool = False
    is_busy: bool = False
    is_error: bool = False
    avg_power: Optional[float] = Field(None, description="Average power in dB")
    filename: Optional[str] = None
    error: Optional[str] = None


class UtscGetConfigRequest(BaseModel):
    """Request to get current UTSC configuration."""
    cmts: CmtsSnmpConfig
    rf_port_ifindex: int = Field(..., description="RF Port ifIndex")
    cfg_index: int = Field(default=1, description="Config table index")


class UtscGetConfigResponse(BaseModel):
    """Response with current UTSC configuration."""
    success: bool
    rf_port_ifindex: Optional[int] = None
    cfg_index: Optional[int] = None
    trigger_mode: Optional[int] = None
    trigger_mode_name: Optional[str] = None
    center_freq_hz: Optional[int] = None
    span_hz: Optional[int] = None
    num_bins: Optional[int] = None
    output_format: Optional[int] = None
    output_format_name: Optional[str] = None
    window_function: Optional[int] = None
    repeat_period_us: Optional[int] = None
    freerun_duration_ms: Optional[int] = None
    trigger_count: Optional[int] = None
    filename: Optional[str] = None
    destination_index: Optional[int] = None
    row_status: Optional[int] = None
    error: Optional[str] = None
