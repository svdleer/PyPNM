from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

import logging
from typing import Any, cast

from fastapi import APIRouter
from starlette.responses import FileResponse

from pypnm.api.routes.basic.abstract.analysis_report import AnalysisRptMatplotConfig
from pypnm.api.routes.basic.spec_analyzer_analysis_rpt import SpectrumAnalyzerReport
from pypnm.api.routes.common.classes.analysis.analysis import Analysis, AnalysisType
from pypnm.api.routes.common.classes.analysis.model.process import AnalysisProcessParameters
from pypnm.api.routes.common.classes.common_endpoint_classes.common.enum import OutputType
from pypnm.api.routes.common.classes.common_endpoint_classes.schemas import PnmAnalysisResponse
from pypnm.api.routes.common.classes.common_endpoint_classes.request_defaults import RequestDefaultsResolver
from pypnm.api.routes.common.classes.common_endpoint_classes.snmp.schemas import SnmpResponse
from pypnm.api.routes.common.classes.file_capture.file_type import FileType
from pypnm.api.routes.common.classes.operation.cable_modem_precheck import CableModemServicePreCheck
from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.extended.common_process_service import CommonProcessService
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.files.service import PnmFileService
from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.schemas import (
    UsOfdmaSpecAnaAnalysisRequest,
    UsOfdmaSpecAnaAnalysisResponse,
    UsAtdmaSpecAnaAnalysisRequest,
    UsAtdmaSpecAnaAnalysisResponse,
    SingleCaptureUsSpectrumAnalyzer,
)
from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.service import (
    CmUsSpectrumAnalysisService,
    UsOfdmaChannelSpectrumAnalyzer,
    UsAtdmaChannelSpectrumAnalyzer,
)
from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.dict_utils import DictGenerate
from pypnm.lib.fastapi_constants import FAST_API_RESPONSE
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import InetAddressStr, MacAddressStr, Path

router = APIRouter(prefix="/docs/pnm/us", tags=["PNM Operations - US Spectrum Analyzer"])
logger = logging.getLogger(__name__)


@router.post(
    "/spectrumAnalyzer/getCapture",
    summary="Get Upstream Spectrum Analyzer Capture (UTSC)",
    response_model=None,
    responses=FAST_API_RESPONSE,
)
async def get_us_capture(
    request: SingleCaptureUsSpectrumAnalyzer,
) -> SnmpResponse | PnmAnalysisResponse | FileResponse:
    """
    Perform Upstream Spectrum Analyzer Capture (UTSC) And Return Analysis Results.

    This endpoint triggers an upstream spectrum capture on the requested cable modem
    using CMTS-based UTSC measurement. The measurement response is processed through
    the common analysis pipeline and returned as JSON or archive.

    [API Guide](https://github.com/PyPNMApps/PyPNM/blob/main/docs/api/fast-api/upstream/spectrum-analyzer.md)
    """
    mac: MacAddressStr = request.cable_modem.mac_address
    ip: InetAddressStr = request.cable_modem.ip_address
    community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
    tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(
        request.cable_modem.pnm_parameters.tftp
    )

    logger.info(
        "Starting Upstream Spectrum Analyzer capture for MAC: %s, IP: %s, Output Type: %s",
        mac,
        ip,
        request.analysis.output.type,
    )

    cm = CableModem(mac_address=MacAddress(mac), inet=Inet(ip), write_community=community)

    status, msg = await CableModemServicePreCheck(
        cable_modem=cm, validate_pnm_ready_status=False
    ).run_precheck()

    if status != ServiceStatusCode.SUCCESS:
        logger.error(msg)
        return SnmpResponse(mac_address=mac, status=status, message=msg)

    service = CmUsSpectrumAnalysisService(
        cable_modem=cm,
        tftp_servers=tftp_servers,
        capture_parameters=request.capture_parameters,
    )

    msg_rsp: MessageResponse = await service.set_and_go()

    if msg_rsp.status != ServiceStatusCode.SUCCESS:
        err = "Unable to complete Upstream Spectrum Analyzer capture."
        logger.error("%s Status: %s", err, msg_rsp.status.name)
        return SnmpResponse(mac_address=mac, status=msg_rsp.status, message=err)

    cps = CommonProcessService(msg_rsp)
    msg_rsp = cps.process()

    analysis = Analysis(AnalysisType.BASIC, msg_rsp, skip_automatic_process=True)
    analysis.process(cast(AnalysisProcessParameters, request.analysis.spectrum_analysis))

    if request.analysis.output.type == OutputType.JSON:
        payload: dict[str, Any] = cast(dict[str, Any], analysis.get_results())
        DictGenerate.pop_keys_recursive(payload, ["pnm_header", "mac_address", "channel_id"])

        primative = msg_rsp.payload_to_dict("primative")
        DictGenerate.pop_keys_recursive(
            primative, ["device_details", "channel_id", "amplitude_bin_segments_float"]
        )
        payload.update(cast(dict[str, Any], primative))

        return PnmAnalysisResponse(
            mac_address=mac, status=ServiceStatusCode.SUCCESS, data=payload
        )

    if request.analysis.output.type == OutputType.ARCHIVE:
        theme = request.analysis.plot.ui.theme
        plot_config = AnalysisRptMatplotConfig(theme=theme)
        analysis_rpt = SpectrumAnalyzerReport(analysis, plot_config)
        rpt: Path = cast(Path, analysis_rpt.build_report())
        return PnmFileService().get_file(FileType.ARCHIVE, rpt.name)

    return PnmAnalysisResponse(
        mac_address=mac, status=ServiceStatusCode.INVALID_OUTPUT_TYPE, data={}
    )


@router.post(
    "/spectrumAnalyzer/getCapture/ofdma",
    summary="Get OFDMA Channels Upstream Spectrum Analyzer Capture",
    response_model=None,
    responses=FAST_API_RESPONSE,
)
async def get_ofdma_us_channels_analysis(
    request: UsOfdmaSpecAnaAnalysisRequest,
) -> UsOfdmaSpecAnaAnalysisResponse | FileResponse:
    """
    Perform OFDMA Upstream Spectrum Capture Across All US OFDMA Channels.

    This endpoint triggers upstream spectrum capture operations on each DOCSIS 3.1 OFDMA
    upstream channel of the requested cable modem via CMTS UTSC measurement.
    """
    mac: MacAddressStr = request.cable_modem.mac_address
    ip: InetAddressStr = request.cable_modem.ip_address
    community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
    tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(
        request.cable_modem.pnm_parameters.tftp
    )

    logger.info("Starting OFDMA Upstream Spectrum analysis for MAC: %s", mac)

    cm = CableModem(mac_address=MacAddress(mac), inet=Inet(ip), write_community=community)

    status, msg = await CableModemServicePreCheck(
        cable_modem=cm, validate_pnm_ready_status=False
    ).run_precheck()

    if status != ServiceStatusCode.SUCCESS:
        return UsOfdmaSpecAnaAnalysisResponse(
            mac_address=mac, status=status, message=msg, data={}
        )

    analyzer = UsOfdmaChannelSpectrumAnalyzer(
        cable_modem=cm,
        tftp_servers=tftp_servers,
        number_of_averages=request.capture_parameters.number_of_averages,
    )

    results = await analyzer.start()

    if not results:
        return UsOfdmaSpecAnaAnalysisResponse(
            mac_address=mac,
            status=ServiceStatusCode.NO_DATA,
            message="No OFDMA channels found",
            data={},
        )

    return UsOfdmaSpecAnaAnalysisResponse(
        mac_address=mac,
        status=ServiceStatusCode.SUCCESS,
        message="OFDMA US spectrum analysis complete",
        data={"channels": len(results), "results": results},
    )


@router.post(
    "/spectrumAnalyzer/getCapture/atdma",
    summary="Get ATDMA Channels Upstream Spectrum Analyzer Capture",
    response_model=None,
    responses=FAST_API_RESPONSE,
)
async def get_atdma_us_channels_analysis(
    request: UsAtdmaSpecAnaAnalysisRequest,
) -> UsAtdmaSpecAnaAnalysisResponse | FileResponse:
    """
    Perform ATDMA Upstream Spectrum Capture Across All US ATDMA Channels.

    Similar to OFDMA but for ATDMA upstream channels.
    """
    mac: MacAddressStr = request.cable_modem.mac_address
    ip: InetAddressStr = request.cable_modem.ip_address
    community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
    tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(
        request.cable_modem.pnm_parameters.tftp
    )

    logger.info("Starting ATDMA Upstream Spectrum analysis for MAC: %s", mac)

    cm = CableModem(mac_address=MacAddress(mac), inet=Inet(ip), write_community=community)

    status, msg = await CableModemServicePreCheck(
        cable_modem=cm, validate_pnm_ready_status=False
    ).run_precheck()

    if status != ServiceStatusCode.SUCCESS:
        return UsAtdmaSpecAnaAnalysisResponse(
            mac_address=mac, status=status, message=msg, data={}
        )

    analyzer = UsAtdmaChannelSpectrumAnalyzer(
        cable_modem=cm,
        tftp_servers=tftp_servers,
        number_of_averages=request.capture_parameters.number_of_averages,
    )

    results = await analyzer.start()

    if not results:
        return UsAtdmaSpecAnaAnalysisResponse(
            mac_address=mac,
            status=ServiceStatusCode.NO_DATA,
            message="No ATDMA channels found",
            data={},
        )

    return UsAtdmaSpecAnaAnalysisResponse(
        mac_address=mac,
        status=ServiceStatusCode.SUCCESS,
        message="ATDMA US spectrum analysis complete",
        data={"channels": len(results), "results": results},
    )
