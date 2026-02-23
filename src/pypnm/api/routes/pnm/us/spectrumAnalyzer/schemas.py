# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel, Field

from pypnm.api.routes.common.classes.common_endpoint_classes.common_req_resp import (
    CableModemPnmConfig,
    CommonSingleCaptureAnalysisType,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.schemas import (
    PnmAnalysisResponse,
)
from pypnm.lib.types import FrequencyHz
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import WindowFunction


class UsSpecAnCapturePara(BaseModel):
    inactivity_timeout: int = Field(
        default=60, 
        description="Timeout in seconds for inactivity during upstream spectrum analysis."
    )
    first_segment_center_freq: FrequencyHz = Field(
        default=FrequencyHz(15_000_000), 
        description="First segment center frequency in Hz (upstream range: 5-85 MHz typical)."
    )
    last_segment_center_freq: FrequencyHz = Field(
        default=FrequencyHz(85_000_000), 
        description="Last segment center frequency in Hz (upstream range)."
    )
    segment_freq_span: FrequencyHz = Field(
        default=FrequencyHz(1_000_000), 
        description="Frequency span of each segment in Hz."
    )
    num_bins_per_segment: int = Field(
        default=256, 
        description="Number of FFT bins per segment."
    )
    noise_bw: int = Field(
        default=150, 
        description="Equivalent noise bandwidth in kHz."
    )
    window_function: WindowFunction = Field(
        default=WindowFunction.HANN, 
        description="FFT window function to apply."
    )
    num_averages: int = Field(
        default=1, 
        description="Number of averages per segment."
    )


class SpectrumAnalysisExtention(BaseModel):
    pass


class ExtendCommonSingleCaptureAnalysisType(CommonSingleCaptureAnalysisType):
    spectrum_analysis: SpectrumAnalysisExtention = Field(
        default=SpectrumAnalysisExtention(), 
        description="Spectrum Analysis Extension"
    )


class ExtendSingleCaptureSpecAnaRequest(BaseModel):
    cable_modem: CableModemPnmConfig = Field(description="Cable modem configuration")
    analysis: ExtendCommonSingleCaptureAnalysisType = Field(description="Analysis type to perform")


# -------------- MAIN UPSTREAM REQUEST ------------------

class SingleCaptureUsSpectrumAnalyzer(ExtendSingleCaptureSpecAnaRequest):
    capture_parameters: UsSpecAnCapturePara = Field(
        default=UsSpecAnCapturePara(), 
        description="Upstream spectrum capture parameters (UTSC)."
    )


# -------------- UPSTREAM OFDMA REQUEST ------------------

class UsOfdmaSpecAna(BaseModel):
    number_of_averages: int = Field(
        default=10, 
        description="Number of samples to calculate the average per-bin for OFDMA upstream."
    )


class UsOfdmaSpecAnaAnalysisRequest(ExtendSingleCaptureSpecAnaRequest):
    capture_parameters: UsOfdmaSpecAna = Field(
        default=UsOfdmaSpecAna(), 
        description="OFDMA upstream capture parameters."
    )


class UsOfdmaSpecAnaAnalysisResponse(PnmAnalysisResponse):
    pass


# -------------- UPSTREAM ATDMA REQUEST ------------------

class UsAtdmaSpecAna(BaseModel):
    number_of_averages: int = Field(
        default=10, 
        description="Number of samples to calculate the average per-bin for ATDMA upstream."
    )


class UsAtdmaSpecAnaAnalysisRequest(ExtendSingleCaptureSpecAnaRequest):
    capture_parameters: UsAtdmaSpecAna = Field(
        default=UsAtdmaSpecAna(), 
        description="ATDMA upstream capture parameters."
    )


class UsAtdmaSpecAnaAnalysisResponse(PnmAnalysisResponse):
    pass


# -------------- UTSC CMTS-BASED REQUEST/RESPONSE ------------------

class CmtsUtscRequest(BaseModel):
    cmts_ip: str = Field(description="CMTS IP address")
    community: str = Field(default="private", description="SNMP community string")


class UtscRequest(CmtsUtscRequest):
    rf_port_ifindex: int = Field(description="RF port interface index for UTSC")
    center_freq_hz: int = Field(default=30000000, description="Center frequency in Hz")
    span_hz: int = Field(default=80000000, description="Frequency span in Hz")
    num_bins: int = Field(default=800, description="Number of FFT bins")


class UtscResponse(BaseModel):
    success: bool
    error: str | None = None
    message: str | None = None


class UtscDiscoverRequest(CmtsUtscRequest):
    cm_mac_address: str = Field(description="Cable modem MAC address")


class UtscDiscoverResponse(BaseModel):
    success: bool
    rf_port_ifindex: int | None = None
    rf_port_description: str | None = None
    cm_index: int | None = None
    us_channels: list[int] = Field(default_factory=list)
    logical_channel: int | None = None
    error: str | None = None

