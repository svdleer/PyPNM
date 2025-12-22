## Agent Review Bundle Summary
- Goal: Fix Ruff import order issues after schema updates.
- Changes: Reorder imports in spectrum analyzer schema and move future import in RBW conversion module.
- Files: src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/schemas.py, src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/router.py, src/pypnm/lib/conversions/rbw.py
- Tests: ruff check src
- Notes: Review bundle includes full contents of modified files.

# FILE: src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/schemas.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from pypnm.api.routes.common.classes.common_endpoint_classes.common_req_resp import (
    CableModemPnmConfig,
    CommonSingleCaptureAnalysisType,
    TftpConfig,
    default_ip,
    default_mac,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.schema.base_snmp import (
    SNMPConfig,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.schemas import (
    PnmAnalysisResponse,
    PnmDataResponse,
    PnmSingleCaptureRequest,
)
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import FrequencyHz, InetAddressStr, MacAddressStr
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import (
    SpectrumRetrievalType,
    WindowFunction,
)


class SpecAnMovingAvgParameters(BaseModel):
    points:int                                          = Field(default=10, description="")

class SpecAnCapturePara(BaseModel):
    inactivity_timeout       : int                      = Field(default=60, description="Timeout in seconds for inactivity during spectrum analysis.")
    first_segment_center_freq: FrequencyHz              = Field(default=FrequencyHz(300_000_000), description="First segment center frequency in Hz.")
    last_segment_center_freq : FrequencyHz              = Field(default=FrequencyHz(900_000_000), description="Last segment center frequency in Hz.")
    segment_freq_span        : FrequencyHz              = Field(default=FrequencyHz(1_000_000), description="Frequency span of each segment in Hz.")
    num_bins_per_segment     : int                      = Field(default=256, description="Number of FFT bins per segment.")
    noise_bw                 : int                      = Field(default=150, description="Equivalent noise bandwidth in kHz.")
    window_function          : WindowFunction           = Field(default=WindowFunction.HANN, description="FFT window function to apply. See WindowFunction enum for options.")
    num_averages             : int                      = Field(default=1, description="Number of averages per segment.")
    spectrum_retrieval_type  : SpectrumRetrievalType    = Field(default=SpectrumRetrievalType.FILE,
                                                                description=f"Method of spectrum data retrieval: "
                                                                            f"PNM ({SpectrumRetrievalType.FILE}) | "
                                                                            f"SNMP({SpectrumRetrievalType.SNMP}).")

class SpectrumAnalysisExtention(BaseModel):
    moving_average:SpecAnMovingAvgParameters = Field(default=SpecAnMovingAvgParameters(), description="")

class ExtendCommonSingleCaptureAnalysisType(CommonSingleCaptureAnalysisType):
    spectrum_analysis: SpectrumAnalysisExtention = Field(description="Spectrum Analysis Extension")

class ExtendSingleCaptureSpecAnaRequest(BaseModel):
    cable_modem: CableModemPnmConfig                    = Field(description="Cable modem configuration")
    analysis: ExtendCommonSingleCaptureAnalysisType     = Field(description="Analysis type to perform")

class ExtendPnmSingleCaptureRequest(PnmSingleCaptureRequest):
    moving_average:int = Field(...,description="")

# -------------- MAIN REQUEST ------------------

class SpectrumAnalyzerPnmParameters(BaseModel):
    tftp: TftpConfig = Field(..., description="TFTP configuration")

class SpectrumAnalyzerCableModemConfig(BaseModel):
    mac_address: MacAddressStr                    = Field(default=default_mac, description="MAC address of the cable modem")
    ip_address: InetAddressStr                    = Field(default=default_ip, description="Inet address of the cable modem")
    pnm_parameters: SpectrumAnalyzerPnmParameters = Field(description="PNM parameters such as TFTP server configuration")
    snmp: SNMPConfig                              = Field(description="SNMP configuration")

    @field_validator("mac_address")
    def validate_mac(cls, v: str) -> MacAddressStr:
        try:
            return MacAddress(v).mac_address
        except Exception as e:
            raise ValueError(f"Invalid MAC address: {v}, reason: ({e})") from e

class SingleCaptureSpectrumAnalyzerRequest(BaseModel):
    cable_modem: SpectrumAnalyzerCableModemConfig       = Field(description="Cable modem configuration")
    analysis: ExtendCommonSingleCaptureAnalysisType     = Field(description="Analysis type to perform")
    capture_parameters: SpecAnCapturePara               = Field(description="Spectrum capture Parameters.")

class SingleCaptureSpectrumAnalyzer(ExtendSingleCaptureSpecAnaRequest):
    capture_parameters: SpecAnCapturePara       = Field(..., description="Spectrum capture Parameters.")

class CmSpecAnaAnalysisRequest(ExtendPnmSingleCaptureRequest):
    capture_parameters: SpecAnCapturePara       = Field(..., description="Spectrum capture Parameters.")

# -------------- MAIN-RESPONSE------------------

class CmSpecAnaAnalysisResponse(PnmDataResponse):
    """Generic response container for most PNM operations."""

# -------------- MAIN-OFDM-REQUEST ------------------

class OfdmSpecAna(BaseModel):
    number_of_averages: int  = Field(default=10, description="Number of samples to calculate the average per-bin")
    resolution_bandwidth_hz: FrequencyHz = Field(default=FrequencyHz(25_000), description="Resolution Bandwidth in Hz")
    spectrum_retrieval_type: SpectrumRetrievalType = Field(default=SpectrumRetrievalType.FILE,
                                                           description=f"Method of spectrum data retrieval: "
                                                                       f"PNM ({SpectrumRetrievalType.FILE}) | "
                                                                       f"SNMP({SpectrumRetrievalType.SNMP}).")
class OfdmSpecAnaAnalysisRequest(ExtendSingleCaptureSpecAnaRequest):
    capture_parameters:OfdmSpecAna = Field(default=OfdmSpecAna(), description="")

# -------------- MAIN-OFDM-RESPONSE------------------

class OfdmSpecAnaAnalysisResponse(PnmAnalysisResponse):
    pass

# -------------- MAIN-SCQAM-REQUEST ------------------

class ScQamSpecAna(BaseModel):
    number_of_averages: int  = Field(default=10, description="Number of samples to calculate the average per-bin")
    resolution_bandwidth_hz: FrequencyHz = Field(default=FrequencyHz(25_000), description="Resolution Bandwidth in Hz")
    spectrum_retrieval_type: SpectrumRetrievalType = Field(default=SpectrumRetrievalType.FILE,
                                                           description=f"Method of spectrum data retrieval: "
                                                                       f"PNM ({SpectrumRetrievalType.FILE}) | "
                                                                       f"SNMP({SpectrumRetrievalType.SNMP}).")

class ScQamSpecAnaAnalysisRequest(ExtendSingleCaptureSpecAnaRequest):
    capture_parameters:ScQamSpecAna = Field(default=ScQamSpecAna(), description="")

# -------------- MAIN-SCQAM-RESPONSE------------------

class ScQamSpecAnaAnalysisResponse(PnmAnalysisResponse):
    pass

# FILE: src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/router.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter
from starlette.responses import FileResponse

from pypnm.api.routes.basic.abstract.analysis_report import AnalysisRptMatplotConfig
from pypnm.api.routes.basic.ofdm_spec_analyzer_rpt import OfdmSpecAnalyzerAnalysisReport
from pypnm.api.routes.basic.scqam_spec_analyzer_rpt import (
    ScQamSpecAnalyzerAnalysisReport,
)
from pypnm.api.routes.basic.spec_analyzer_analysis_rpt import SpectrumAnalyzerReport
from pypnm.api.routes.common.classes.analysis.analysis import Analysis, AnalysisType
from pypnm.api.routes.common.classes.analysis.model.process import (
    AnalysisProcessParameters,
)
from pypnm.api.routes.common.classes.analysis.multi_analysis import MultiAnalysis
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
from pypnm.api.routes.common.classes.file_capture.file_type import FileType
from pypnm.api.routes.common.classes.operation.cable_modem_precheck import (
    CableModemServicePreCheck,
)
from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.extended.common_process_service import CommonProcessService
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.files.service import PnmFileService
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.schemas import (
    OfdmSpecAnaAnalysisRequest,
    OfdmSpecAnaAnalysisResponse,
    ScQamSpecAnaAnalysisRequest,
    ScQamSpecAnaAnalysisResponse,
    SingleCaptureSpectrumAnalyzerRequest,
)
from pypnm.api.routes.docs.pnm.spectrumAnalyzer.service import (
    CmSpectrumAnalysisService,
    DsOfdmChannelSpectrumAnalyzer,
    DsScQamChannelSpectrumAnalyzer,
)
from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.data_type.pnm.DocsIf3CmSpectrumAnalysisEntry import (
    DocsIf3CmSpectrumAnalysisEntry,
)
from pypnm.lib.dict_utils import DictGenerate
from pypnm.lib.fastapi_constants import FAST_API_RESPONSE
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import ChannelId, FrequencyHz, InetAddressStr, MacAddressStr, Path


class SpectrumAnalyzerRouter:
    def __init__(self) -> None:
        prefix = "/docs/pnm/ds"
        self.base_endpoint = "/spectrumAnalyzer"
        self.router = APIRouter(prefix=prefix, tags=["PNM Operations - Spectrum Analyzer"])
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.__routes()

    def __routes(self) -> None:
        @self.router.post(
            f"{self.base_endpoint}/getCapture",
            summary="Get Spectrum Analyzer Capture",
            response_model=None,
            responses=FAST_API_RESPONSE,
        )
        async def get_capture(request: SingleCaptureSpectrumAnalyzerRequest) -> SnmpResponse | PnmAnalysisResponse | FileResponse:
            """
            Perform Spectrum Analyzer Capture And Return Analysis Results.

            This endpoint triggers a spectrum capture on the requested cable modem using the
            provided capture parameters. The measurement response is then processed through
            the common analysis pipeline and returned as either:

            - A JSON analysis payload containing decoded amplitude data and summary metrics.
            - An archive file containing plots and related report artifacts (ZIP).

            The cable modem must be PNM-ready and the capture parameters must respect the
            diplexer configuration and platform constraints (DOCSIS 3.x and DOCSIS 4.0 FDD).

            [API Guide](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/single/spectrum-analyzer.md)

            """
            mac: MacAddressStr = request.cable_modem.mac_address
            ip: InetAddressStr = request.cable_modem.ip_address
            community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
            tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(request.cable_modem.pnm_parameters.tftp)

            self.logger.info("Starting Spectrum Analyzer capture for MAC: %s, IP: %s, Output Type: %s",
                mac, ip, request.analysis.output.type,)

            cm = CableModem(mac_address=MacAddress(mac),
                            inet=Inet(ip),
                            write_community=community,)

            status, msg = await CableModemServicePreCheck(
                cable_modem=cm, validate_pnm_ready_status=True,).run_precheck()

            if status != ServiceStatusCode.SUCCESS:
                self.logger.error(msg)
                return SnmpResponse(mac_address=mac, status=status, message=msg)

            service = CmSpectrumAnalysisService(
                cable_modem=cm,
                tftp_servers=tftp_servers,
                capture_parameters=request.capture_parameters,)

            msg_rsp: MessageResponse = await service.set_and_go()

            if msg_rsp.status != ServiceStatusCode.SUCCESS:
                err = "Unable to complete Spectrum Analyzer capture."
                self.logger.error("%s Status: %s", err, msg_rsp.status.name)
                return SnmpResponse(mac_address=mac, status=msg_rsp.status, message=err)

            channel_ids = None
            measurement_stats: list[DocsIf3CmSpectrumAnalysisEntry] = cast(
                list[DocsIf3CmSpectrumAnalysisEntry],
                await service.getPnmMeasurementStatistics(channel_ids=channel_ids),)

            cps = CommonProcessService(msg_rsp)
            msg_rsp = cps.process()

            analysis = Analysis(AnalysisType.BASIC, msg_rsp, skip_automatic_process=True)
            analysis.process(cast(AnalysisProcessParameters, request.analysis.spectrum_analysis))

            if request.analysis.output.type == OutputType.JSON:
                payload: dict[str, Any] = cast(dict[str, Any], analysis.get_results())
                DictGenerate.pop_keys_recursive(payload, ["pnm_header", "mac_address", "channel_id"])

                primative = msg_rsp.payload_to_dict("primative")
                DictGenerate.pop_keys_recursive(
                    primative,
                    ["device_details", "channel_id", "amplitude_bin_segments_float"],
                )
                payload.update(cast(dict[str, Any], primative))
                payload.update(
                    DictGenerate.models_to_nested_dict(
                        measurement_stats,
                        "measurement_stats",
                    )
                )

                return PnmAnalysisResponse(
                    mac_address=mac,
                    status=ServiceStatusCode.SUCCESS,
                    data=payload,
                )

            if request.analysis.output.type == OutputType.ARCHIVE:
                theme = request.analysis.plot.ui.theme
                plot_config = AnalysisRptMatplotConfig(theme=theme)
                analysis_rpt = SpectrumAnalyzerReport(analysis, plot_config)
                rpt: Path = cast(Path, analysis_rpt.build_report())
                return PnmFileService().get_file(FileType.ARCHIVE, rpt.name)

            return PnmAnalysisResponse(
                mac_address=mac,
                status=ServiceStatusCode.INVALID_OUTPUT_TYPE,
                data={},
            )

        @self.router.post(
            f"{self.base_endpoint}/getCapture/ofdm",
            summary="Get OFDM Channels Spectrum Analyzer Capture",
            response_model=None,
            responses=FAST_API_RESPONSE,
        )
        async def get_ofdm_ds_channels_analysis(request: OfdmSpecAnaAnalysisRequest) -> OfdmSpecAnaAnalysisResponse | FileResponse:
            """
            Perform OFDM Downstream Spectrum Capture Across All DS OFDM Channels.

            This endpoint triggers spectrum capture operations on each DOCSIS 3.1 OFDM
            downstream channel of the requested cable modem. Each per-channel response is
            processed through the common analysis pipeline, aggregated into a multi-analysis
            structure, and then returned as either JSON or an archive.

            The cable modem must support OFDM downstream channels and be PNM-ready, and
            the spectrum capture parameters must be valid for the underlying platform and
            diplexer configuration.

            [API Guide](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/single/spectrum-analyzer.md)

            """
            mac: MacAddressStr = request.cable_modem.mac_address
            ip: InetAddressStr = request.cable_modem.ip_address
            community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
            tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(request.cable_modem.pnm_parameters.tftp)

            cm = CableModem(mac_address=MacAddress(mac),
                            inet=Inet(ip),
                            write_community=community)
            multi_analysis = MultiAnalysis()

            self.logger.info("DOCSIS 3.1 OFDM Downstream Spectrum Capture for MAC %s, IP %s", mac, ip,)

            status, msg = await CableModemServicePreCheck(
                cable_modem=cm, validate_ofdm_exist=True, validate_pnm_ready_status=True,).run_precheck()

            if status != ServiceStatusCode.SUCCESS:
                self.logger.error(msg)
                return OfdmSpecAnaAnalysisResponse(
                    mac_address=mac, status=status, message=msg, data={},)

            service = DsOfdmChannelSpectrumAnalyzer(
                cable_modem             =   cm,
                tftp_servers            =   tftp_servers,
                number_of_averages      =   request.capture_parameters.number_of_averages,
                resolution_bandwidth_hz =   request.capture_parameters.resolution_bandwidth_hz,
                spectrum_retrieval_type =   request.capture_parameters.spectrum_retrieval_type)

            msg_responses: list[tuple[ChannelId, MessageResponse]] = await service.start()

            measurement_stats: list[DocsIf3CmSpectrumAnalysisEntry] = cast(
                list[DocsIf3CmSpectrumAnalysisEntry],
                await service.getPnmMeasurementStatisticsFlat(),
            )

            primative: dict[str, dict[Any, Any]] = {"primative": {}}

            for idx, (chan_id, msg_rsp) in enumerate(msg_responses):
                cps_msg_rsp = CommonProcessService(msg_rsp).process()

                analysis = Analysis(AnalysisType.BASIC, cps_msg_rsp, skip_automatic_process=True,)
                analysis.process(cast(AnalysisProcessParameters, request.analysis.spectrum_analysis))
                multi_analysis.add(chan_id, analysis)

                primative_entry = cps_msg_rsp.payload_to_dict(idx)
                primative["primative"].update(primative_entry)

            analyzer_rpt = OfdmSpecAnalyzerAnalysisReport(multi_analysis)
            analyzer_rpt.build_report()

            if request.analysis.output.type == OutputType.JSON:
                analyzer_rpt_dict = analyzer_rpt.to_dict()
                analyzer_rpt_dict.update(primative)
                analyzer_rpt_dict.update(
                    DictGenerate.models_to_nested_dict(measurement_stats, "measurement_stats",))

                return OfdmSpecAnaAnalysisResponse(
                    mac_address =   mac,
                    status      =   ServiceStatusCode.SUCCESS,
                    data        =   analyzer_rpt_dict,
                )

            if request.analysis.output.type == OutputType.ARCHIVE:
                return PnmFileService().get_file(
                    FileType.ARCHIVE, analyzer_rpt.get_archive(),
                )

            return OfdmSpecAnaAnalysisResponse(
                mac_address =   mac,
                status      =   ServiceStatusCode.INVALID_OUTPUT_TYPE,
                message     =   f"Unsupported output type: {request.analysis.output.type}",
                data={},
            )

        @self.router.post(
            f"{self.base_endpoint}/getCapture/scqam",
            summary="Get SC-QAM Downstream Channels Spectrum Analysis",
            response_model=None,
            responses=FAST_API_RESPONSE,
        )
        async def get_scqam_ds_channels_analysis(request: ScQamSpecAnaAnalysisRequest) -> ScQamSpecAnaAnalysisResponse | FileResponse:
            """
            Perform SC-QAM Downstream Spectrum Capture Across All DS SC-QAM Channels.

            This endpoint triggers spectrum capture operations on each DOCSIS 3.0 SC-QAM
            downstream channel of the requested cable modem. Each per-channel response is
            processed through the common analysis pipeline, aggregated into a multi-analysis
            structure, and then returned as either JSON or an archive.

            The cable modem must support SC-QAM downstream channels and be PNM-ready, and
            the spectrum capture parameters must be valid for the underlying platform and
            diplexer configuration.

            [API Guide](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/single/spectrum-analyzer.md)

            """
            mac: MacAddressStr = request.cable_modem.mac_address
            ip: InetAddressStr = request.cable_modem.ip_address
            community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
            tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(request.cable_modem.pnm_parameters.tftp)

            cm = CableModem(mac_address=MacAddress(mac), inet=Inet(ip), write_community=community)
            multi_analysis = MultiAnalysis()

            self.logger.info("DOCSIS 3.0 SC-QAM downstream spectrum capture for MAC %s, IP %s", mac, ip)

            status, msg = await CableModemServicePreCheck(
                cable_modem=cm,
                validate_scqam_exist=True, validate_pnm_ready_status=True,).run_precheck()

            if status != ServiceStatusCode.SUCCESS:
                self.logger.error(msg)
                return ScQamSpecAnaAnalysisResponse(
                    mac_address=mac,
                    status=status, message=msg, data={}, )

            number_of_averages: int = request.capture_parameters.number_of_averages
            spectrum_retrieval_type = request.capture_parameters.spectrum_retrieval_type
            resolution_bandwidth: FrequencyHz = request.capture_parameters.resolution_bandwidth_hz

            service = DsScQamChannelSpectrumAnalyzer(
                cable_modem             =   cm,
                tftp_servers            =   tftp_servers,
                number_of_averages      =   number_of_averages,
                resolution_bandwidth_hz =   resolution_bandwidth,
                spectrum_retrieval_type =   spectrum_retrieval_type,
            )

            msg_responses: list[tuple[ChannelId, MessageResponse]] = await service.start()

            measurement_stats: list[DocsIf3CmSpectrumAnalysisEntry] = cast(
                list[DocsIf3CmSpectrumAnalysisEntry],
                await service.getPnmMeasurementStatisticsFlat(),
            )

            primative: dict[str, dict[Any, Any]] = {"primative": {}}

            for idx, (chan_id, msg_rsp) in enumerate(msg_responses):
                cps_msg_rsp = CommonProcessService(msg_rsp).process()

                analysis = Analysis(AnalysisType.BASIC, cps_msg_rsp, skip_automatic_process=True,)
                analysis.process(cast(AnalysisProcessParameters, request.analysis.spectrum_analysis))
                multi_analysis.add(chan_id, analysis)

                primative_entry = cps_msg_rsp.payload_to_dict(idx)
                primative["primative"].update(primative_entry)

            analyzer_rpt = ScQamSpecAnalyzerAnalysisReport(multi_analysis)
            analyzer_rpt.build_report()

            if request.analysis.output.type == OutputType.JSON:
                analyzer_rpt_dict = analyzer_rpt.to_dict()
                analyzer_rpt_dict.update(primative)
                analyzer_rpt_dict.update(
                    DictGenerate.models_to_nested_dict(measurement_stats, "measurement_stats",))

                return ScQamSpecAnaAnalysisResponse(
                    mac_address =   mac,
                    status      =   ServiceStatusCode.SUCCESS,
                    data        =   analyzer_rpt_dict,
                )

            if request.analysis.output.type == OutputType.ARCHIVE:
                return PnmFileService().get_file(FileType.ARCHIVE, analyzer_rpt.get_archive(),)

            return ScQamSpecAnaAnalysisResponse(
                mac_address=mac,
                status=ServiceStatusCode.INVALID_OUTPUT_TYPE,
                message=f"Unsupported output type: {request.analysis.output.type}",
                data={},
            )


# Required for dynamic auto-registration
router = SpectrumAnalyzerRouter().router

# FILE: src/pypnm/lib/conversions/rbw.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from math import ceil, floor

from pypnm.lib.types import (
    FrequencyHz,
    NumBins,
    ResolutionBw,
    ResolutionBwSettings,
    SegmentFreqSpan,
)

DEFAULT_FREQUENCY_SPAN_HZ: FrequencyHz = FrequencyHz(0)


class RBWConversion:
    """Conversion utilities for Resolution Bandwidth (RBW) values."""

    DEFAULT_SEGMENT_SPAN_HZ: SegmentFreqSpan = SegmentFreqSpan(1_000_000)
    DEFAULT_RBW_HZ: ResolutionBw = ResolutionBw(300_000)
    DEFAULT_NUM_BINS: NumBins = NumBins(256)
    DEFAULT_NUM_BINS_300_KHZ: NumBins = NumBins(3)

    @staticmethod
    def getNumBin(
        rbw: ResolutionBw = DEFAULT_RBW_HZ,
        segment_freq_span: SegmentFreqSpan = DEFAULT_SEGMENT_SPAN_HZ,
        to_floor: bool = True,
    ) -> NumBins:
        """
        Calculate the number of bins for a given RBW and segment frequency span.

        Args:
            rbw: Resolution bandwidth for the segment in Hz.
            segment_freq_span: Segment span in Hz to divide into bins.
            to_floor: When True, floor the bin count; otherwise, ceil it.

        Returns:
            The computed number of bins.

        Raises:
            ValueError: When rbw or segment_freq_span is non-positive.
        """
        if rbw <= 0:
            raise ValueError("rbw must be positive.")
        if segment_freq_span <= 0:
            raise ValueError("segment_freq_span must be positive.")

        raw_bins = float(segment_freq_span) / float(rbw)
        bins = int(floor(raw_bins)) if to_floor else int(ceil(raw_bins))

        return NumBins(bins)

    @staticmethod
    def getSegementFreqSpan(
        rbw: ResolutionBw = DEFAULT_RBW_HZ,
        num_of_bins: NumBins = DEFAULT_NUM_BINS_300_KHZ,
    ) -> SegmentFreqSpan:
        """
        Calculate segment frequency span from RBW and bin count.

        Args:
            rbw: Resolution bandwidth for the segment in Hz.
            num_of_bins: Number of bins in the segment.

        Returns:
            The computed segment frequency span in Hz.

        Raises:
            ValueError: When rbw or num_of_bins is non-positive.
        """
        if rbw <= 0:
            raise ValueError("rbw must be positive.")
        if num_of_bins <= 0:
            raise ValueError("num_of_bins must be positive.")

        return SegmentFreqSpan(int(rbw) * int(num_of_bins))

    @staticmethod
    def getSpectrumRbwSetttings(
        rbw: ResolutionBw,
        frequency_span: FrequencyHz = DEFAULT_FREQUENCY_SPAN_HZ,
        to_floor: bool = True,
    ) -> ResolutionBwSettings:
        """
        Build RBW settings tuple for the provided resolution bandwidth.

        Args:
            rbw: Resolution bandwidth in Hz.
            frequency_span: Frequency span in Hz (defaults to the standard span).
            to_floor: When True, floor the bin count; otherwise, ceil it.

        Returns:
            Tuple of (rbw, num_bins, segment_freq_span).
        """
        segment_span = RBWConversion.DEFAULT_SEGMENT_SPAN_HZ
        if frequency_span > 0:
            span_hz = max(int(frequency_span), int(segment_span))
            segment_span = SegmentFreqSpan(span_hz)

        bins = RBWConversion.getNumBin(
            rbw=rbw,
            segment_freq_span=segment_span,
            to_floor=to_floor,
        )

        return (rbw, bins, segment_span)
