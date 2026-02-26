# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Schemas for CMTS Upstream OFDMA RxMER operations.

This module provides Pydantic models for CMTS-side US OFDMA RxMER
measurements as defined in DOCS-PNM-MIB (docsPnmCmtsUsOfdmaRxMerTable).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CmtsSnmpConfig(BaseModel):
    """CMTS SNMP configuration."""
    cmts_ip: str = Field(..., description="CMTS IP address")
    community: str = Field(default="private", description="SNMP community string")
    write_community: Optional[str] = Field(default=None, description="SNMP write community (defaults to community)")


class UsOfdmaRxMerDiscoverRequest(BaseModel):
    """Request to discover modem's OFDMA channel on CMTS."""
    cmts: CmtsSnmpConfig
    cm_mac_address: str = Field(..., description="Cable modem MAC address")


class UsOfdmaRxMerDiscoverResponse(BaseModel):
    """Response from OFDMA channel discovery."""
    success: bool
    cm_mac_address: str
    cm_index: Optional[int] = None
    ofdma_ifindex: Optional[int] = None          # legacy single-channel field
    ofdma_description: Optional[str] = None
    ofdma_channels: List[Dict[str, Any]] = []    # all active OFDMA channels [{ifindex, description}]
    error: Optional[str] = None


class UsOfdmaRxMerStartRequest(BaseModel):
    """Request to start US OFDMA RxMER measurement."""
    cmts: CmtsSnmpConfig
    ofdma_ifindex: int = Field(..., description="OFDMA channel ifIndex on CMTS")
    cm_mac_address: str = Field(..., description="Cable modem MAC address")
    filename: str = Field(default="us_rxmer", description="Output filename")
    pre_eq: bool = Field(default=True, description="Enable pre-equalization")
    num_averages: int = Field(default=1, ge=1, le=255, description="Number of averages")
    destination_index: int = Field(
        default=0,
        ge=0,
        description="Bulk transfer destination index. 0=auto-create row 1 when tftp_server given"
    )
    tftp_server: Optional[str] = Field(
        default=None,
        description="TFTP server IP for bulk upload. Required on Cisco cBR-8 to trigger measurement."
    )


class UsOfdmaRxMerStartResponse(BaseModel):
    """Response from starting US OFDMA RxMER measurement."""
    success: bool
    ofdma_ifindex: Optional[int] = None
    cm_mac_address: Optional[str] = None
    filename: Optional[str] = None
    destination_index: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


class UsOfdmaRxMerStatusRequest(BaseModel):
    """Request to get US OFDMA RxMER measurement status."""
    cmts: CmtsSnmpConfig
    ofdma_ifindex: int = Field(..., description="OFDMA channel ifIndex on CMTS")


class UsOfdmaRxMerStatusResponse(BaseModel):
    """Response with US OFDMA RxMER measurement status."""
    success: bool
    ofdma_ifindex: Optional[int] = None
    meas_status: Optional[int] = None
    meas_status_name: Optional[str] = None
    is_ready: bool = False
    is_busy: bool = False
    is_error: bool = False
    error: Optional[str] = None
    filename: Optional[str] = Field(None, description="Filename of the captured data when is_ready=True")


class BulkDestination(BaseModel):
    """Bulk data transfer destination configuration."""
    index: int = Field(..., description="Destination index for use in destination_index parameter")
    ip_address: Optional[str] = Field(None, description="Destination IP address")
    port: int = Field(default=69, description="Destination port (default 69 for TFTP)")
    protocol: str = Field(default="tftp", description="Transfer protocol")
    local_store: bool = Field(default=True, description="Whether to also store locally")


class BulkDestinationsRequest(BaseModel):
    """Request to get bulk transfer destinations."""
    cmts: CmtsSnmpConfig


class CasaBulkDestination(BaseModel):
    """Casa docsPnmCcapBulkDataControlTable entry."""
    index: int
    ip_address: Optional[str] = None
    dest_path: Optional[str] = None
    pnm_test_selector_hex: Optional[str] = None


class BulkDestinationsResponse(BaseModel):
    """Response with list of bulk transfer destinations."""
    success: bool
    destinations: list[BulkDestination] = Field(default_factory=list)
    casa_destinations: list[CasaBulkDestination] = Field(
        default_factory=list,
        description="Casa-only: docsPnmCcapBulkDataControlTable entries with PnmTestSelector"
    )
    error: Optional[str] = None


# ============================================================
# Pre-Equalization / Group Delay schemas
# ============================================================

class PreEqChannelMetrics(BaseModel):
    """Pre-equalization key metrics for one upstream channel."""
    main_tap_ratio: Optional[float] = None
    tap_energy_ratio: Optional[float] = None
    mtc_dB: Optional[float] = Field(None, description="Main Tap to Composite ratio (dB)")
    nmter_dB: Optional[float] = Field(None, description="Non Main Tap Energy Ratio (dB)")
    pcter: Optional[float] = Field(None, description="Pre/Post Cursor Tap Energy Ratio")
    pre_main_tap_energy_ratio: Optional[float] = None
    post_main_tap_energy_ratio: Optional[float] = None


class PreEqGroupDelay(BaseModel):
    """Group delay metrics from pre-equalization taps."""
    channel_width_hz: int = Field(..., description="ATDMA channel width in Hz")
    symbol_rate: float = Field(..., description="Symbol rate (sym/s)")
    symbol_time_us: float = Field(..., description="Symbol period (µs)")
    sample_period_us: float = Field(..., description="Tap sample period (µs)")
    fft_size: int = Field(..., description="FFT size used for frequency domain analysis")
    delay_us: List[float] = Field(default_factory=list, description="Group delay per FFT bin (µs), truncated")
    delay_min_us: float = Field(..., description="Minimum group delay (µs)")
    delay_max_us: float = Field(..., description="Maximum group delay (µs)")
    delay_pp_us: float = Field(..., description="Peak-to-peak group delay variation (µs)")
    delay_rms_us: float = Field(..., description="RMS group delay variation (µs)")


class PreEqTapDelaySummary(BaseModel):
    """Tap delay summary with cable length equivalents."""
    main_tap_index: int
    max_pre_main_delay_us: Optional[float] = None
    max_post_main_delay_us: Optional[float] = None
    pre_main_cable_ft: Optional[float] = Field(None, description="Cable length equivalent (feet) for pre-main reflection")
    post_main_cable_ft: Optional[float] = Field(None, description="Cable length equivalent (feet) for post-main reflection")


class PreEqChannelData(BaseModel):
    """Pre-equalization data for one upstream channel."""
    us_ifindex: int = Field(..., description="Upstream channel ifIndex")
    num_taps: int = Field(..., description="Number of equalizer taps")
    main_tap_location: int = Field(..., description="Main tap index")
    taps_per_symbol: int = Field(..., description="Taps per symbol from header")
    metrics: Optional[PreEqChannelMetrics] = None
    group_delay: Optional[PreEqGroupDelay] = None
    tap_delay_summary: Optional[PreEqTapDelaySummary] = None


class PreEqDataRequest(BaseModel):
    """Request to get pre-equalization data for a cable modem."""
    cmts: CmtsSnmpConfig
    cm_mac_address: str = Field(..., description="Cable modem MAC address")
    cm_index: Optional[int] = Field(None, description="CM registration index (if already known)")
    channel_width_hz: int = Field(default=6_400_000, description="ATDMA channel width in Hz (default 6.4 MHz)")


class PreEqDataResponse(BaseModel):
    """Response with pre-equalization data and group delay."""
    success: bool
    cm_mac_address: str
    cm_index: Optional[int] = None
    num_channels: int = 0
    channels: List[PreEqChannelData] = Field(default_factory=list)
    error: Optional[str] = None


class CreateBulkDestinationRequest(BaseModel):
    """Request to create or configure a bulk transfer destination."""
    cmts: CmtsSnmpConfig
    tftp_ip: str = Field(..., description="TFTP server IP address")
    port: int = Field(default=69, description="TFTP port (default 69)")
    local_store: bool = Field(default=True, description="Also store locally on CMTS")
    dest_index: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Destination index (1-10). If None, finds first available."
    )


class CreateBulkDestinationResponse(BaseModel):
    """Response from creating a bulk transfer destination."""
    success: bool
    destination_index: Optional[int] = None
    tftp_ip: Optional[str] = None
    port: Optional[int] = None
    local_store: Optional[bool] = None
    message: Optional[str] = None
    created: Optional[bool] = None
    error: Optional[str] = None


class UsOfdmaRxMerCaptureRequest(BaseModel):
    """Request to get and parse US OFDMA RxMER capture file."""
    filename: str = Field(..., description="Filename of the RxMER capture (e.g., 'us_rxmer_2026-01-28_12.13.25.870')")
    tftp_server: Optional[str] = Field(default=None, description="TFTP server IP. If None, uses local file path.")
    tftp_path: str = Field(default="/var/lib/tftpboot", description="Local TFTP root path")


class UsOfdmaRxMerComparisonRequest(BaseModel):
    """Request to compare pre-eq ON vs OFF captures (convenience wrapper around FiberNodeAnalysisRequest)."""
    filename_preeq_on: str = Field(..., description="Filename of the pre-eq ON capture")
    filename_preeq_off: str = Field(..., description="Filename of the pre-eq OFF capture")
    tftp_path: str = Field(default="/var/lib/tftpboot", description="Local TFTP root path")


# ============================================================
# Unified Fiber Node Analysis model
# ============================================================

class RxMerCapture(BaseModel):
    """Parsed RxMER data for one modem/capture."""
    cm_mac_address: str
    preeq_enabled: bool
    filename: Optional[str] = None
    values: List[float] = []
    frequencies_mhz: List[float] = []
    rxmer_avg_db: Optional[float] = None
    rxmer_min_db: Optional[float] = None
    rxmer_max_db: Optional[float] = None
    rxmer_std_db: Optional[float] = None


class SubcarrierGroupStats(BaseModel):
    """Per-subcarrier statistics across all captures in a fiber node group."""
    frequency_mhz: float
    index: int
    values_db: List[float] = Field(default=[], description="RxMER dB per capture (same order as captures[])")
    mean_db: float
    std_db: float
    min_db: float
    max_db: float
    p10_db: float
    p90_db: float
    outlier_macs: List[str] = Field(default=[], description="MACs where value is >2σ below group mean")


class ModemAssessment(BaseModel):
    """Per-modem assessment within a fiber node analysis."""
    cm_mac_address: str
    preeq_enabled: Optional[bool] = None
    rxmer_avg_db: float
    delta_from_group_avg_db: float = Field(description="This modem avg minus group avg (negative = worse)")
    unique_bad_subcarriers: int = Field(description="Subcarriers bad on THIS modem but <50% of others")
    shared_bad_subcarriers: int = Field(description="Subcarriers bad on >50% of all modems (network)")
    outlier_score: float = Field(description="0.0–1.0 — fraction of subcarriers where this modem is an outlier")
    assessment: str = Field(description="'in-home' | 'network' | 'clean' | 'outlier' | 'inconclusive'")
    # Pre-eq comparison (populated when preeq ON+OFF exist for same MAC)
    preeq_delta_avg_db: Optional[float] = Field(default=None, description="Mean(pre_eq_on) − Mean(pre_eq_off)")
    preeq_num_improved: Optional[int] = Field(default=None, description="Subcarriers improved by pre-eq")
    preeq_assessment: Optional[str] = Field(default=None, description="'in-home' | 'network' | 'clean' | 'inconclusive'")


class FiberNodeSummary(BaseModel):
    """Aggregate summary of a fiber node group analysis."""
    num_captures: int
    num_modems: int
    group_avg_db: float
    group_std_db: float
    pct_network_impaired: float = Field(description="% of subcarriers bad on >50% of modems")
    network_impaired_frequencies_mhz: List[float] = []
    pct_modems_in_home: float = Field(description="% of modems with in-home impairment")
    worst_modem_mac: Optional[str] = None
    worst_modem_delta_db: Optional[float] = None


class FiberNodeAnalysis(BaseModel):
    """
    Unified fiber node RxMER analysis — covers single-modem pre-eq comparison
    and multi-modem group analysis with the same response shape.
    """
    success: bool
    captures: List[RxMerCapture] = []
    subcarrier_stats: List[SubcarrierGroupStats] = []
    modem_assessments: List[ModemAssessment] = []
    summary: Optional[FiberNodeSummary] = None
    error: Optional[str] = None


class FiberNodeCaptureEntry(BaseModel):
    """One capture entry for a fiber node analysis request."""
    cm_mac_address: str
    filename: str
    preeq_enabled: bool = Field(default=True)


class FiberNodeAnalysisRequest(BaseModel):
    """
    Request a fiber node RxMER group analysis.

    Provide one entry per capture file. The engine will:
    - Group entries by cm_mac_address
    - Compute per-subcarrier statistics across all captures
    - Assess each modem (in-home / network / clean / outlier)
    - If a modem has both preeq_enabled=True and preeq_enabled=False captures,
      compute pre-eq delta and preeq_assessment automatically.
    """
    captures: List[FiberNodeCaptureEntry] = Field(..., min_length=1)
    tftp_path: str = Field(default="/var/lib/tftpboot")
    ofdma_ifindex: Optional[int] = None
    cmts_ip: Optional[str] = None


class UsOfdmaRxMerCaptureResponse(BaseModel):
    """Response with parsed US OFDMA RxMER data."""
    success: bool
    cm_mac_address: Optional[str] = None
    filename: Optional[str] = None
    ccap_id: Optional[str] = None
    num_active_subcarriers: Optional[int] = None
    first_active_subcarrier_index: Optional[int] = None
    subcarrier_zero_frequency_hz: Optional[int] = None
    subcarrier_spacing_hz: Optional[int] = None
    occupied_bandwidth_mhz: Optional[float] = None
    num_averages: Optional[int] = None
    preeq_enabled: Optional[bool] = None
    rxmer_min_db: Optional[float] = None
    rxmer_avg_db: Optional[float] = None
    rxmer_max_db: Optional[float] = None
    rxmer_std_db: Optional[float] = None
    values: Optional[list[float]] = None
    frequencies_mhz: Optional[list[float]] = None
    error: Optional[str] = None
