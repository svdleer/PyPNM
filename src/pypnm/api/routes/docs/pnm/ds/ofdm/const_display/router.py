# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter
from starlette.responses import FileResponse

from pypnm.api.routes.basic.abstract.analysis_report import Analysis
from pypnm.api.routes.basic.constellation_display_analysis_rpt import (
    ConstDisplayAnalysisRptMatplotConfig,
    ConstellationDisplayReport,
)
from pypnm.api.routes.common.classes.analysis.analysis import AnalysisType
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
from pypnm.api.routes.common.classes.operation.cable_modem_precheck import (
    CableModemServicePreCheck,
)
from pypnm.api.routes.common.extended.common_measure_schema import (
    DownstreamOfdmParameters,
)
from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.extended.common_process_service import CommonProcessService
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.ds.ofdm.const_display.schemas import (
    PnmConstellationDisplayAnalysisRequest,
)
from pypnm.api.routes.docs.pnm.ds.ofdm.const_display.service import (
    CmDsOfdmConstDisplayService,
)
from pypnm.api.routes.docs.pnm.files.service import FileType, PnmFileService
from pypnm.docsis.cable_modem import CableModem
from pypnm.docsis.data_type.pnm.DocsPnmCmDsConstDispMeasEntry import (
    DocsPnmCmDsConstDispMeasEntry,
)
from pypnm.lib.dict_utils import DictGenerate
from pypnm.lib.fastapi_constants import FAST_API_RESPONSE
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import InetAddressStr, MacAddressStr


class ConstellationDisplayRouter:
    """
    FastAPI router for Downstream OFDM Constellation Display.

    [API Guide](https://github.com/PyPNMApps/PyPNM/blob/main/documentation/api/fast-api/single/ds/ofdm/constellation-display.md)

    """

    def __init__(self) -> None:
        """
        Initialize router with consistent prefix/tags and register routes.
        """
        prefix: str = "/docs/pnm/ds/ofdm"
        self.base_endpoint: str = "/constellationDisplay"
        self.router: APIRouter = APIRouter(prefix=prefix, tags=["PNM Operations - Downstream OFDM Constellation Display"])
        self.logger: logging.Logger = logging.getLogger(f'ConstellationDisplayRouter.{self.base_endpoint.strip("/")}')
        self.__routes()

    def __routes(self) -> None:
        """
        Register FastAPI routes for this router.
        """
        @self.router.post(
            f"{self.base_endpoint}/getCapture",
            summary="Get Constellation Display PNM Capture File",
            response_model=None,
            responses=FAST_API_RESPONSE,
        )

        async def get_capture(request: PnmConstellationDisplayAnalysisRequest) -> SnmpResponse | PnmAnalysisResponse | FileResponse:
            """
            Capture Downstream OFDM Constellation Display Samples And Return Analysis Results.

            [API Guide](https://github.com/PyPNMApps/PyPNM/blob/main/docs/api/fast-api/single/ds/ofdm/constellation-display.md)

            """
            import sys
            import traceback
            try:
                print("=== ENTERED get_capture ===", flush=True)
                sys.stderr.write("=== STDERR: Entered get_capture ===\n")
                sys.stderr.flush()
                mac: MacAddressStr = request.cable_modem.mac_address
                ip: InetAddressStr = request.cable_modem.ip_address
                sys.stderr.write(f"=== Processing constellation for MAC: {mac} ===\n")
                sys.stderr.flush()
                community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
                tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(request.cable_modem.pnm_parameters.tftp)

                self.logger.info(f"Starting Constellation Display capture for MAC: {mac}, IP: {ip}")

                cm = CableModem(mac_address=MacAddress(mac), inet=Inet(ip), write_community=community)

                status, msg = await CableModemServicePreCheck(cable_modem=cm, validate_ofdm_exist=True).run_precheck()
                print(f"=== Precheck status: {status}, msg: {msg} ===", flush=True)
                if status != ServiceStatusCode.SUCCESS:
                    self.logger.error(msg)
                    print("=== EARLY RETURN: Precheck failed ===", flush=True)
                    return SnmpResponse(mac_address=mac, status=status, message=msg)

                modulation_order_offset: int = request.capture_settings.modulation_order_offset
                number_sample_symbol: int = request.capture_settings.number_sample_symbol

                service: CmDsOfdmConstDisplayService = CmDsOfdmConstDisplayService(
                    cable_modem             =   cm,
                    tftp_servers            =   tftp_servers,
                    modulation_order_offset =   modulation_order_offset,
                    number_sample_symbol    =   number_sample_symbol,
                )

                channel_ids = request.cable_modem.pnm_parameters.capture.channel_ids
                interface_parameters = None
                if channel_ids:
                    interface_parameters = DownstreamOfdmParameters(channel_id=list(channel_ids))

                msg_rsp: MessageResponse = await service.set_and_go(interface_parameters=interface_parameters)
                print(f"=== set_and_go status: {msg_rsp.status} ===", flush=True)
                if msg_rsp.status != ServiceStatusCode.SUCCESS:
                    err = "Unable to complete Constellation Display capture."
                    self.logger.error(err)
                    print("=== EARLY RETURN: set_and_go failed ===", flush=True)
                    return SnmpResponse(mac_address=mac, message=err, status=msg_rsp.status)

                measurement_stats:list[DocsPnmCmDsConstDispMeasEntry] = \
                    cast(list[DocsPnmCmDsConstDispMeasEntry],
                        await service.getPnmMeasurementStatistics(channel_ids=channel_ids))

                cps = CommonProcessService(msg_rsp)
                msg_rsp = cps.process()

                # Debug: Check payload structure to diagnose empty plots
                print(f"\n=== CONSTELLATION DEBUG for {mac} ===", flush=True)
                print(f"Payload type: {type(msg_rsp.payload)}", flush=True)
                
                # Check if payload is a list
                if isinstance(msg_rsp.payload, list):
                    print(f"Payload is a list with length: {len(msg_rsp.payload)}", flush=True)
                    if len(msg_rsp.payload) > 0:
                        print(f"First item type: {type(msg_rsp.payload[0])}", flush=True)
                        print(f"First item: {msg_rsp.payload[0]}", flush=True)
                    else:
                        print("ERROR: Payload list is EMPTY - modem returned no constellation data", flush=True)
                else:
                    print(f"Payload keys: {msg_rsp.payload.keys() if hasattr(msg_rsp.payload, 'keys') else 'No keys'}", flush=True)
                    if hasattr(msg_rsp.payload, 'measurements'):
                        print(f"Number of measurements: {len(msg_rsp.payload.measurements)}", flush=True)
                        if msg_rsp.payload.measurements:
                            first_meas = msg_rsp.payload.measurements[0]
                            if hasattr(first_meas, 'keys'):
                                print(f"First measurement keys: {first_meas.keys()}", flush=True)
                                if 'samples' in first_meas:
                                    samples = first_meas.get('samples')
                                    print(f"Samples present: {samples is not None}, Type: {type(samples) if samples else 'None'}", flush=True)
                                    if samples and hasattr(samples, '__len__'):
                                        print(f"Samples length: {len(samples)}", flush=True)
                print("=== END DEBUG ===\n", flush=True)

                # Verify that samples exist before attempting constellation analysis
                try:
                    analysis = Analysis(AnalysisType.BASIC, msg_rsp)
                except (ValueError, KeyError) as e:
                    err = f"Constellation analysis failed: {str(e)}. The modem may not support constellation capture or returned empty data."
                    self.logger.error(err)
                    return SnmpResponse(
                        mac_address=mac, 
                        message=err, 
                        status=ServiceStatusCode.DS_OFDM_RXMER_NOT_AVAILABLE
                    )

                if request.analysis.output.type == OutputType.JSON:
                    payload: dict[str, Any] = cast(dict[str, Any], analysis.get_results())
                    payload.update({k: v for k, v in msg_rsp.payload_to_dict().items() if isinstance(k, str)})

                    DictGenerate.pop_keys_recursive(payload, ["pnm_header", "data"])
                    primative = msg_rsp.payload_to_dict('primative')
                    DictGenerate.pop_keys_recursive(primative, ["device_details"])
                    payload.update({k: v for k, v in primative.items() if isinstance(k, str)})
                    payload.update(DictGenerate.models_to_nested_dict(measurement_stats, 'measurement_stats',))

                    return PnmAnalysisResponse(
                        mac_address =   mac,
                        status      =   ServiceStatusCode.SUCCESS,
                        data        =   payload,)

                elif request.analysis.output.type == OutputType.ARCHIVE:
                    theme = request.analysis.plot.ui.theme
                    crosshair = request.analysis.plot.options.display_cross_hair
                    plot_config = ConstDisplayAnalysisRptMatplotConfig(theme = theme, display_crosshair=crosshair)
                    analysis_rpt = ConstellationDisplayReport(analysis, plot_config)
                    rpt: Path = cast(Path, analysis_rpt.build_report())
                    return PnmFileService().get_file(FileType.ARCHIVE, rpt.name)

                else:
                    return PnmAnalysisResponse(
                        mac_address =   mac,
                        status      =   ServiceStatusCode.INVALID_OUTPUT_TYPE,
                        data        =   {},)
            except Exception as e:
                import sys
                import traceback
                sys.stderr.write(f"\n=== EXCEPTION IN get_capture ===\n")
                sys.stderr.write(f"Exception type: {type(e).__name__}\n")
                sys.stderr.write(f"Exception message: {str(e)}\n")
                sys.stderr.write(f"Traceback:\n{traceback.format_exc()}\n")
                sys.stderr.flush()
                raise

# Required for dynamic auto-registration
router = ConstellationDisplayRouter().router
