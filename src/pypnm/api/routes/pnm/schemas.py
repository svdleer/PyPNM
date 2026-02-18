# SPDX-License-Identifier: Apache-2.0
# PNM Modem Diagnostics Schemas

from __future__ import annotations

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================
# Common Request/Response Models
# ============================================

class PNMModemRequest(BaseModel):
    """Base request model for PNM modem diagnostics."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    community: str = Field(default="public", description="SNMP community string")


# ============================================
# RxMER (Receive Modulation Error Ratio)
# ============================================

class RxMERMeasurement(BaseModel):
    """Single RxMER measurement."""
    channel_id: int = Field(..., description="Channel ID")
    mer_db: float = Field(..., description="MER value in dB")


class RxMERResponse(BaseModel):
    """Response model for RxMER data."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    measurements: List[RxMERMeasurement] = Field(default_factory=list, description="RxMER measurements")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# FEC (Forward Error Correction)
# ============================================

class FECChannel(BaseModel):
    """FEC statistics for a single channel."""
    channel_id: int = Field(..., description="Channel ID")
    unerrored: int = Field(default=0, description="Unerrored codewords")
    corrected: int = Field(default=0, description="Corrected codewords")
    uncorrectable: int = Field(default=0, description="Uncorrectable codewords")
    total_codewords: int = Field(default=0, description="Total codewords")
    snr_db: float = Field(default=0.0, description="Signal-to-noise ratio in dB")


class FECResponse(BaseModel):
    """Response model for FEC statistics."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    channels: List[FECChannel] = Field(default_factory=list, description="FEC stats per channel")
    total_uncorrectable: int = Field(default=0, description="Total uncorrectable codewords")
    total_corrected: int = Field(default=0, description="Total corrected codewords")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Channel Power
# ============================================

class DownstreamChannel(BaseModel):
    """Downstream channel power information."""
    channel_id: int = Field(..., description="Channel ID")
    frequency_hz: int = Field(..., description="Frequency in Hz")
    power_dbmv: float = Field(..., description="Power in dBmV")


class UpstreamChannel(BaseModel):
    """Upstream channel power information."""
    channel_id: int = Field(..., description="Channel ID")
    power_dbmv: float = Field(..., description="Transmit power in dBmV")


class ChannelPowerResponse(BaseModel):
    """Response model for channel power data."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    downstream_channels: List[DownstreamChannel] = Field(default_factory=list, description="DS channels")
    upstream_channels: List[UpstreamChannel] = Field(default_factory=list, description="US channels")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Pre-Equalization Coefficients
# ============================================

class PreEqCoefficient(BaseModel):
    """Pre-equalization coefficient for a channel."""
    channel_id: int = Field(..., description="Channel ID")
    hex_data: str = Field(..., description="Hex-encoded coefficient data")
    length: int = Field(..., description="Length of coefficient data in bytes")


class PreEqResponse(BaseModel):
    """Response model for pre-equalization data."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    coefficients: List[PreEqCoefficient] = Field(default_factory=list, description="Pre-eq coefficients")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Upstream RxMER (OFDMA)
# ============================================

class USRxMERStartRequest(BaseModel):
    """Request to start Upstream OFDMA RxMER measurement."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    ofdma_ifindex: int = Field(..., description="OFDMA channel interface index")
    cm_mac_address: str = Field(..., description="Cable modem MAC address")
    community: str = Field(default="public", description="SNMP write community string")
    filename: str = Field(default="us_rxmer", description="Output filename")
    pre_eq: bool = Field(default=True, description="Include pre-equalization")


class USRxMERStartResponse(BaseModel):
    """Response from starting US RxMER measurement."""
    success: bool = Field(..., description="Whether the request was successful")
    message: Optional[str] = Field(default=None, description="Status message")
    ofdma_ifindex: Optional[int] = Field(default=None, description="OFDMA channel ifindex")
    cm_mac: Optional[str] = Field(default=None, description="Cable modem MAC")
    filename: Optional[str] = Field(default=None, description="Output filename")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class USRxMERStatusRequest(BaseModel):
    """Request to get US RxMER measurement status."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    ofdma_ifindex: int = Field(..., description="OFDMA channel interface index")
    community: str = Field(default="public", description="SNMP community string")


class USRxMERStatusResponse(BaseModel):
    """Response with US RxMER measurement status."""
    success: bool = Field(..., description="Whether the request was successful")
    ofdma_ifindex: Optional[int] = Field(default=None, description="OFDMA channel ifindex")
    meas_status: Optional[int] = Field(default=None, description="Measurement status code")
    meas_status_name: Optional[str] = Field(default=None, description="Measurement status name")
    is_ready: bool = Field(default=False, description="Whether sample is ready")
    is_busy: bool = Field(default=False, description="Whether measurement is in progress")
    is_error: bool = Field(default=False, description="Whether an error occurred")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class USRxMERDataRequest(BaseModel):
    """Request to fetch US RxMER data."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    ofdma_ifindex: Optional[int] = Field(default=None, description="OFDMA channel interface index")
    filename: str = Field(default="us_rxmer", description="Capture filename")
    community: str = Field(default="public", description="SNMP community string")


class USRxMERData(BaseModel):
    """Parsed US RxMER data."""
    subcarriers: List[int] = Field(default_factory=list, description="Subcarrier indices")
    rxmer_values: List[float] = Field(default_factory=list, description="RxMER values in dB")
    ofdma_ifindex: Optional[int] = Field(default=None, description="OFDMA channel ifindex")
    found_file: Optional[str] = Field(default=None, description="File path that was read")


class USRxMERDataResponse(BaseModel):
    """Response with US RxMER data."""
    success: bool = Field(..., description="Whether the request was successful")
    data: Optional[USRxMERData] = Field(default=None, description="Parsed RxMER data")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Spectrum Analyzer
# ============================================

class SpectrumRequest(BaseModel):
    """Request to trigger spectrum analyzer capture."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    community: str = Field(default="public", description="SNMP write community string")
    tftp_server: Optional[str] = Field(default=None, description="TFTP server IP for file upload")


class SpectrumResponse(BaseModel):
    """Response from spectrum capture trigger."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    message: Optional[str] = Field(default=None, description="Status message")
    filename: Optional[str] = Field(default=None, description="Output filename")
    status_polled: Optional[bool] = Field(default=None, description="Whether status was polled")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Channel Info
# ============================================

class DSChannel(BaseModel):
    """Downstream channel info."""
    channel_id: int = Field(..., description="Channel ID")
    type: str = Field(..., description="Channel type (SC-QAM or OFDM)")
    frequency_mhz: float = Field(default=0, description="Center frequency in MHz")
    power_dbmv: float = Field(default=0, description="Receive power in dBmV")
    snr_db: Optional[float] = Field(default=None, description="SNR in dB (SC-QAM only)")
    # OFDM-specific
    ifindex: Optional[int] = Field(default=None, description="Interface index (OFDM only)")
    subcarrier_zero_freq_mhz: Optional[float] = Field(default=None, description="Subcarrier 0 frequency (OFDM)")
    first_active_subcarrier: Optional[int] = Field(default=None, description="First active subcarrier (OFDM)")
    last_active_subcarrier: Optional[int] = Field(default=None, description="Last active subcarrier (OFDM)")
    num_active_subcarriers: Optional[int] = Field(default=None, description="Number of active subcarriers (OFDM)")
    profiles: Optional[List[int]] = Field(default=None, description="Active modulation profiles (OFDM)")
    current_profile: Optional[int] = Field(default=None, description="Current modulation profile (OFDM)")


class USChannel(BaseModel):
    """Upstream channel info."""
    channel_id: int = Field(..., description="Channel ID")
    type: str = Field(..., description="Channel type (ATDMA or OFDMA)")
    power_dbmv: float = Field(default=0, description="Transmit power in dBmV")


class ChannelInfoRequest(BaseModel):
    """Request for comprehensive channel info."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    community: str = Field(default="public", description="SNMP community string")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")


class ChannelInfoResponse(BaseModel):
    """Response with comprehensive channel info."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of query")
    downstream: List[DSChannel] = Field(default_factory=list, description="Downstream channels")
    upstream: List[USChannel] = Field(default_factory=list, description="Upstream channels")
    error: Optional[str] = Field(default=None, description="Error message if failed")

# ============================================
# Channel Estimation Coefficients
# ============================================

class ChannelEstimationRequest(BaseModel):
    """Request for OFDM channel estimation coefficients."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    community: str = Field(default="private", description="SNMP write community string")
    channel_ids: Optional[List[int]] = Field(default=None, description="Specific channel IDs (empty = all)")
    tftp_server: Optional[str] = Field(default="172.22.147.18", description="TFTP server IP")


class ChannelEstimationCoeff(BaseModel):
    """Channel estimation coefficient data."""
    channel_id: int = Field(..., description="Channel ID")
    coefficients: List[float] = Field(..., description="Coefficient values")
    frequency_mhz: Optional[float] = Field(default=None, description="Channel frequency in MHz")


class ChannelEstimationResponse(BaseModel):
    """Response for channel estimation coefficients."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    channels: List[ChannelEstimationCoeff] = Field(default_factory=list, description="Channel estimation data")
    filename: Optional[str] = Field(default=None, description="Generated filename")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Modulation Profile
# ============================================

class ModulationProfileRequest(BaseModel):
    """Request for OFDM modulation profile."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    community: str = Field(default="private", description="SNMP write community string")
    channel_ids: Optional[List[int]] = Field(default=None, description="Specific channel IDs (empty = all)")
    tftp_server: Optional[str] = Field(default="172.22.147.18", description="TFTP server IP")


class ModulationProfileData(BaseModel):
    """Modulation profile data for a channel."""
    channel_id: int = Field(..., description="Channel ID")
    profiles: List[Dict[str, Any]] = Field(..., description="Modulation profile data")
    active_profile: Optional[int] = Field(default=None, description="Currently active profile ID")


class ModulationProfileResponse(BaseModel):
    """Response for modulation profile data."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    channels: List[ModulationProfileData] = Field(default_factory=list, description="Modulation profile data")
    filename: Optional[str] = Field(default=None, description="Generated filename")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Histogram
# ============================================

class HistogramRequest(BaseModel):
    """Request for downstream histogram."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    community: str = Field(default="private", description="SNMP write community string")
    channel_ids: Optional[List[int]] = Field(default=None, description="Specific channel IDs (empty = all)")
    tftp_server: Optional[str] = Field(default="172.22.147.18", description="TFTP server IP")


class HistogramData(BaseModel):
    """Histogram data for a channel."""
    channel_id: int = Field(..., description="Channel ID")
    bins: List[int] = Field(..., description="Histogram bin values")
    counts: List[int] = Field(..., description="Count values for each bin")
    total_samples: Optional[int] = Field(default=None, description="Total sample count")


class HistogramResponse(BaseModel):
    """Response for histogram data."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    channels: List[HistogramData] = Field(default_factory=list, description="Histogram data")
    filename: Optional[str] = Field(default=None, description="Generated filename")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Constellation Display
# ============================================

class ConstellationRequest(BaseModel):
    """Request for constellation display."""
    modem_ip: str = Field(..., description="Cable modem IP address")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    community: str = Field(default="private", description="SNMP write community string")
    channel_ids: Optional[List[int]] = Field(default=None, description="Specific channel IDs (empty = all)")
    tftp_server: Optional[str] = Field(default="172.22.147.18", description="TFTP server IP")


class ConstellationPoint(BaseModel):
    """Single constellation point."""
    i: float = Field(..., description="I (in-phase) component")
    q: float = Field(..., description="Q (quadrature) component")


class ConstellationData(BaseModel):
    """Constellation data for a channel."""
    channel_id: int = Field(..., description="Channel ID")
    points: List[ConstellationPoint] = Field(..., description="Constellation points")
    modulation: Optional[str] = Field(default=None, description="Modulation type (e.g., QAM256)")
    mer_db: Optional[float] = Field(default=None, description="MER in dB")


class ConstellationResponse(BaseModel):
    """Response for constellation display data."""
    success: bool = Field(..., description="Whether the request was successful")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC address")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP address")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of measurement")
    channels: List[ConstellationData] = Field(default_factory=list, description="Constellation data")
    filename: Optional[str] = Field(default=None, description="Generated filename")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ============================================
# Async Measurement Tracking
# ============================================

class AsyncMeasurementResponse(BaseModel):
    """Response for starting an async measurement."""
    measurement_id: str = Field(..., description="Unique measurement identifier")
    status: str = Field(..., description="Measurement status: in_progress, completed, failed")
    estimated_completion: Optional[str] = Field(default=None, description="Estimated completion time")
    progress: Optional[int] = Field(default=0, description="Progress percentage (0-100)")
    message: Optional[str] = Field(default=None, description="Status message")


class MeasurementStatusResponse(BaseModel):
    """Response for measurement status check."""
    measurement_id: str = Field(..., description="Measurement identifier")
    status: str = Field(..., description="Measurement status: in_progress, completed, failed")
    progress: int = Field(..., description="Progress percentage (0-100)")
    started_at: str = Field(..., description="Measurement start time")
    completed_at: Optional[str] = Field(default=None, description="Measurement completion time")
    estimated_completion: Optional[str] = Field(default=None, description="Estimated completion time")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    
    # Measurement results (populated when completed)
    measurements: Optional[List[Dict[str, Any]]] = Field(default=None, description="Measurement data")
    filename: Optional[str] = Field(default=None, description="Generated filename")
    mac_address: Optional[str] = Field(default=None, description="Cable modem MAC")
    modem_ip: Optional[str] = Field(default=None, description="Cable modem IP")