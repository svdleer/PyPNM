## Agent Review Bundle Summary
- Goal: Add channel-scoped acquisition support to multi-RxMER captures.
- Changes: Pass interface parameters for channel filtering in multi-RxMER services, update docs, and add pytest coverage.
- Files: src/pypnm/api/routes/advance/multi_rxmer/router.py, src/pypnm/api/routes/advance/multi_rxmer/service.py, docs/api/fast-api/multi/multi-capture-rxmer.md, tests/test_multi_rxmer_channel_ids.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: existing drift); pytest -q
- Notes: ruff format --check . reports existing formatting drift across the repo.

# FILE: src/pypnm/api/routes/advance/multi_rxmer/router.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import io
import logging
import os
import zipfile
from typing import cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from pypnm.api.routes.advance.analysis.signal_analysis.multi_rxmer_signal_analysis import (
    MultiRxMerAnalysisResult,
    MultiRxMerAnalysisType,
    MultiRxMerSignalAnalysis,
)
from pypnm.api.routes.advance.common.abstract.service import AbstractService
from pypnm.api.routes.advance.common.capture_data_aggregator import (
    CaptureDataAggregator,
)
from pypnm.api.routes.advance.common.operation_manager import OperationManager
from pypnm.api.routes.advance.common.operation_state import OperationState
from pypnm.api.routes.advance.multi_rxmer.schemas import (
    MultiRxMerAnalysisRequest,
    MultiRxMerAnalysisResponse,
    MultiRxMerMeasureModes,
    MultiRxMerRequest,
    MultiRxMerResponseStatus,
    MultiRxMerStartResponse,
    MultiRxMerStatusResponse,
)
from pypnm.api.routes.advance.multi_rxmer.service import (
    MultiRxMer_Ofdm_Performance_1_Service,
    MultiRxMerService,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.common.enum import (
    OutputType,
)
from pypnm.api.routes.common.classes.common_endpoint_classes.request_defaults import (
    RequestDefaultsResolver,
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
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.files.service import FileType, PnmFileService
from pypnm.config.system_config_settings import SystemConfigSettings
from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.fastapi_constants import FAST_API_RESPONSE
from pypnm.lib.inet import Inet, InetAddressStr
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import ChannelId, GroupId, MacAddressStr, OperationId


class MultiRxMerRouter(AbstractService):
    """
    Router For Multi-RxMER Capture And Analysis

    Overview
    --------
    Exposes endpoints to:
      • Start a background, periodic RxMER capture on a DOCSIS cable modem
      • Poll capture status (state, collected sample count, time remaining)
      • Download all collected raw RxMER files as a ZIP archive
      • Stop an active capture early
      • Run post-capture analysis on the collected dataset

    Execution Model
    ---------------
    Each capture runs asynchronously under a managed operation. The returned `operation_id`
    is used to query status, fetch results, or trigger analysis. Pre-checks verify PNM-ready
    state and the presence of downstream OFDM.

    Inherits
    --------
    AbstractService
        Provides `loadService(...)` and `getService(...)` for service lifecycle and operation lookup.
    """
    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.router = APIRouter(
            prefix="/advance/multiRxMer",
            tags=["PNM Operations - Multi-Downstream OFDM RxMER"],)
        self._add_routes()

    def _add_routes(self) -> None:
        @self.router.post("/start",
            response_model=MultiRxMerStartResponse | SnmpResponse,
            summary="Start a Multi-RxMER capture",
            responses=FAST_API_RESPONSE,)
        async def start_multi_rxmer(request: MultiRxMerRequest) -> SnmpResponse | MultiRxMerStartResponse:
            """
            Start Multi-RxMER Capture

            Description
            -----------
            Starts an asynchronous RxMER capture on the target cable modem. Sampling cadence is
            controlled by `capture.parameters.measurement_duration` and `capture.parameters.sample_interval`.

            Modes
            -----
            • `MeasureModes.CONTINUOUS` - Continuous sampling for min/avg/max and heat-map workflows
            • `MeasureModes.OFDM_PERFORMANCE_1` - Performance study pairing RxMER with modulation-profile
              and FEC summary collection

            Returns
            -------
            • `MultiRxMerStartResponse` with `group_id` and `operation_id` on success
            • `SnmpResponse` when modem pre-checks fail (e.g., not PNM-ready or OFDM missing)

            [API Guide - Results](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/multi/multi-capture-rxmer.md#3-download-measurements)
            """

            mac_address: MacAddressStr = request.cable_modem.mac_address
            ip_address: InetAddressStr = request.cable_modem.ip_address
            community = RequestDefaultsResolver.resolve_snmp_community(request.cable_modem.snmp)
            tftp_servers = RequestDefaultsResolver.resolve_tftp_servers(request.cable_modem.pnm_parameters.tftp)
            duration = request.capture.parameters.measurement_duration
            interval = request.capture.parameters.sample_interval
            channel_ids = request.cable_modem.pnm_parameters.capture.channel_ids
            interface_parameters = self._resolve_interface_parameters(channel_ids)

            measure_modes = request.measure.mode
            msg:str = ""

            self.logger.info(
                f"Starting Multi-RxMER capture for MAC={mac_address} "
                f"(duration={duration}s, interval={interval}s)")

            cable_modem = CableModem(mac_address=MacAddress(mac_address),
                                     inet=Inet(ip_address),
                                     write_community=community)

            status, msg = await CableModemServicePreCheck(cable_modem=cable_modem,
                                                          validate_ofdm_exist=True,
                                                          validate_pnm_ready_status=True).run_precheck()
            if status != ServiceStatusCode.SUCCESS:
                self.logger.error(msg)
                return SnmpResponse(mac_address=mac_address, status=status, message=msg)

            if measure_modes == MultiRxMerMeasureModes.CONTINUOUS:
                msg=f'Starting Multi-RxMER capture for MAC={mac_address}'
                self.logger.info(f'{msg}')
                group_id, operation_id = await self.loadService(
                    MultiRxMerService,
                    cable_modem,
                    tftp_servers,
                    duration=duration,
                    interval=interval,
                    interface_parameters=interface_parameters,)

            elif measure_modes == MultiRxMerMeasureModes.OFDM_PERFORMANCE_1:
                msg=f'Starting Multi-RxMER-OFDM-Performance-1 capture for MAC={mac_address}'
                self.logger.info(f'{msg}')
                group_id, operation_id = await self.loadService(
                    MultiRxMer_Ofdm_Performance_1_Service,
                    cable_modem,
                    tftp_servers,
                    duration=duration,
                    interval=interval,
                    interface_parameters=interface_parameters,)

            else:
                self.logger.error(f'Invalid Measure Mode Selected: ({measure_modes})')
                return MultiRxMerStartResponse(
                    mac_address =   mac_address,
                    status      =   ServiceStatusCode.MEASURE_MODE_INVALID,
                    message =f"{ServiceStatusCode.MEASURE_MODE_INVALID.name}",
                    group_id="", operation_id="",)

            return MultiRxMerStartResponse(
                mac_address =   mac_address,
                status      =   OperationState.RUNNING,
                message     =   msg,
                group_id    =   group_id,
                operation_id=   operation_id,
            )

        @self.router.get("/status/{operation_id}",
            response_model=MultiRxMerStatusResponse,
            summary="Get status of a Multi-RxMER capture",
            responses=FAST_API_RESPONSE,)
        def get_status(operation_id: OperationId) -> MultiRxMerStatusResponse:
            """
            Check Multi-RxMER Capture Status

            Description
            -----------
            Returns the current state of the capture, number of samples collected, and estimated
            time remaining for the given `operation_id`.

            Path Parameters
            ---------------
            operation_id : OperationId
                Identifier returned by `/start`.

            Returns
            -------
            `MultiRxMerStatusResponse` populated with `operation.state`, `operation.collected`,
            and `operation.time_remaining`.

            Errors
            ------
            404 — Operation not found.

            [API Guide - Results](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/multi/multi-capture-rxmer.md#3-download-measurements)
            """
            try:
                service:MultiRxMerService = cast(MultiRxMerService, self.getService(operation_id))

            except KeyError as err:
                raise HTTPException(status_code=404, detail="Operation not found") from err

            status = service.status(operation_id)

            self.logger.debug(f'OpId: {operation_id} - Status: {status}')

            return MultiRxMerStatusResponse(
                mac_address =   service.cm.get_mac_address.mac_address,
                status      =   "success",
                message     =   None,
                operation   =   MultiRxMerResponseStatus(
                                    operation_id    =   operation_id,
                                    state           =   status["state"],
                                    collected       =   status["collected"],
                                    time_remaining  =   status["time_remaining"],
                                    message         =   None,
                ),
            )

        @self.router.get("/results/{operation_id}",
            summary="Download a ZIP archive of all RxMER capture files",
            responses=FAST_API_RESPONSE,)
        def download_measurements_zip(operation_id: OperationId) -> StreamingResponse:
            """
            Download Captured RxMER Measurements (ZIP)

            Description
            -----------
            Streams a ZIP archive containing all RxMER `.bin` files associated with the specified
            `operation_id`. Useful for offline analysis or archival.

            Content
            -------
            • Media Type: `application/zip`
            • Disposition: `attachment; filename=multiRxMer_<mac>_<operation_id>.zip`

            Path Parameters
            ---------------
            operation_id : OperationId
                Identifier returned by `/start`.

            Returns
            -------
            `StreamingResponse` — Streamed ZIP of all capture files found. Missing files are logged and skipped.

            [API Guide - Results](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/multi/multi-capture-rxmer.md#3-download-measurements)
            """
            svc:MultiRxMerService = cast(MultiRxMerService, self.getService(operation_id))
            samples = svc.results(operation_id)

            pnm_dir = str(SystemConfigSettings.pnm_dir())
            mac = svc.cm.get_mac_address.mac_address

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for sample in samples:
                    file_path = os.path.join(pnm_dir, sample.filename)
                    arcname = os.path.basename(sample.filename)
                    try:
                        zipf.write(file_path, arcname=arcname)
                    except FileNotFoundError:
                        self.logger.warning(f"File not found, skipping: {file_path}")
                    except Exception as e:
                        self.logger.warning(f"Skipping {file_path}: {e}")

            buf.seek(0)

            headers = {"Content-Disposition": f"attachment; filename=multiRxMer_{mac}_{operation_id}.zip"}
            return StreamingResponse(buf, media_type="application/zip", headers=headers)

        @self.router.delete("/stop/{operation_id}",
            response_model=MultiRxMerStatusResponse,
            summary="Stop a running Multi-RxMER capture early",
            responses=FAST_API_RESPONSE,)
        def stop_capture(operation_id: OperationId) -> MultiRxMerStatusResponse:
            """
            Stop Multi-RxMER Capture

            Description
            -----------
            Signals the background worker to stop sampling after the current iteration for the
            specified `operation_id`.

            Path Parameters
            ---------------
            operation_id : OperationId
                Identifier returned by `/start`.

            Returns
            -------
            `MultiRxMerStatusResponse` — Finalized state and counters at stop time.

            Errors
            ------
            404 — Operation not found.

            [API Guide - Results](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/multi/multi-capture-rxmer.md#3-download-measurements)
            """
            try:
                service:MultiRxMerService = cast(MultiRxMerService, self.getService(operation_id))
            except KeyError as err:
                raise HTTPException(status_code=404, detail="Operation not found") from err

            service.stop(operation_id)
            status = service.status(operation_id)

            return MultiRxMerStatusResponse(
                mac_address=service.cm.get_mac_address.mac_address,
                status=OperationState.STOPPED,
                message=None,
                operation=MultiRxMerResponseStatus(
                    operation_id    =   operation_id,
                    state           =   status["state"],
                    collected       =   status["collected"],
                    time_remaining  =   status["time_remaining"],
                    message         =   None,
                ),
            )

        @self.router.post("/analysis",
            response_model=MultiRxMerAnalysisResponse,
            summary="Perform signal analysis on a previously executed Multi-RxMER captures",
            responses=FAST_API_RESPONSE,)
        def analysis(request: MultiRxMerAnalysisRequest) -> MultiRxMerAnalysisResponse | FileResponse:
            """
            Multi-RxMER Analysis

            Description
            -----------
            Runs post-capture analysis for the dataset associated with `request.operation_id`.
            The capture group is derived internally from the operation.

            Analysis Types
            --------------
            • `MIN_AVG_MAX` — Per-subcarrier min/avg/max over the series
            • `RXMER_HEAT_MAP` — Heat-map oriented dataset for visualization
            • `OFDM_PROFILE_PERFORMANCE_1` — Averages RxMER, compares to modulation profiles,
              and aggregates FEC statistics over time

            Output
            ------
            Controlled by `request.analysis.output.type`:
            • `OutputType.JSON` — Typed JSON payload for UI consumption
            • `OutputType.ARCHIVE` — Generated ZIP report via `PnmFileService`

            Returns
            -------
            • `MultiRxMerAnalysisResponse` (JSON output)
            • `FileResponse` (archive report)

            Errors
            ------
            • Capture group not found for the supplied operation
            • Invalid analysis type or invalid output type

            [API Guide - Results](https://github.com/svdleer/PyPNM/blob/main/docs/api/fast-api/multi/multi-capture-rxmer.md#3-download-measurements)
            """
            try:
                capture_group_id:GroupId = OperationManager.get_capture_group(request.operation_id)
                self.logger.info(f'[analysis] - OperationID: {request.operation_id} -> CaptureGroup: {capture_group_id}')

            except KeyError:
                return MultiRxMerAnalysisResponse(
                    mac_address =   MacAddress.null(),
                    status      =   ServiceStatusCode.CAPTURE_GROUP_NOT_FOUND,
                    message     =   f"No capture group found for operation {request.operation_id}",
                    data        =   {})

            cda = CaptureDataAggregator(capture_group_id)

            try:
                atype = MultiRxMerAnalysisType(request.analysis.type)
            except ValueError:
                msg = f'Invalid Analysis Type, reason: {request.analysis.type}'
                return MultiRxMerAnalysisResponse(
                    mac_address =   MacAddress.null(),
                    status      =   ServiceStatusCode.DS_OFDM_MULIT_RXMER_ANALYSIS_TYPE,
                    message     =   msg,
                    data        =   {})
            self.logger.info(f'Performing Multi-RxMER Min/Avg/Max Analysis for group: {capture_group_id}')

            if atype == MultiRxMerAnalysisType.MIN_AVG_MAX:
                engine = MultiRxMerSignalAnalysis(cda, atype)
                multi_analysis:MultiRxMerAnalysisResult = engine.to_model()

            elif atype == MultiRxMerAnalysisType.RXMER_HEAT_MAP:
                engine = MultiRxMerSignalAnalysis(cda, MultiRxMerAnalysisType.RXMER_HEAT_MAP)
                multi_analysis = engine.to_model()

            elif atype == MultiRxMerAnalysisType.OFDM_PROFILE_PERFORMANCE_1:
                '''
                    Operation of this test:
                    -----------------------
                    * Collect a seriers of RxMER
                    * Collect at least 1 Modualtion Profile=
                    * Collect a Fec Summary at:
                        - 1 FecSummary every 10 Min
                        - At end of the test

                    OFDM_PROFILE_MEASUREMENT_1
                    --------------------------
                    * Calculate the Avg RxMER of the series
                    * Calculate Shannon for each subcarrier
                    * Compare each modualtion profile against the RxMER Average
                    * Calculate the percentage of subcarries that are outside a given profile
                    * Provide total FEC Stats for each profile over the time of the capture.
                '''
                engine = MultiRxMerSignalAnalysis(cda, MultiRxMerAnalysisType.OFDM_PROFILE_PERFORMANCE_1)
                multi_analysis = engine.to_model()

            else:
                msg = f'Invalid Analysis Type {atype}'
                return MultiRxMerAnalysisResponse(
                    mac_address =   MacAddress.null(),
                    status      =   ServiceStatusCode.DS_OFDM_MULIT_RXMER_ANALYSIS_TYPE,
                    message     =   msg,
                    data        =   {})

            # 4) Map analysis output to response fields
            analysis_name = MultiRxMerAnalysisType(atype).name
            message = f"Analysis {analysis_name} completed for group {capture_group_id}"

            try:
                output_type = request.analysis.output.type
            except ValueError:
                msg = f'Invalid Output Type Selected: ({request.analysis.output.type})'
                return MultiRxMerAnalysisResponse(
                    mac_address =   MacAddress.null(),
                    status      =   ServiceStatusCode.INVALID_OUTPUT_TYPE,
                    message     =   msg,
                    data        =   {})

            mac_address = multi_analysis.mac_address

            if output_type == OutputType.JSON:
                data = multi_analysis.model_dump().get("data", {})
                return MultiRxMerAnalysisResponse(
                    mac_address =   mac_address,
                    status      =   ServiceStatusCode.SUCCESS,
                    message     =   message,
                    data        =   data,)

            elif output_type == OutputType.ARCHIVE:
                rpt = engine.build_report()
                return PnmFileService().get_file(FileType.ARCHIVE, rpt.name)

            else:

                # Fallback for unsupported output types
                return MultiRxMerAnalysisResponse(
                    mac_address =   mac_address,
                    status      =   ServiceStatusCode.INVALID_OUTPUT_TYPE,
                    message     =   f"Unsupported output type: {output_type}",
                    data        =   {},)

    @staticmethod
    def _resolve_interface_parameters(
        channel_ids: list[ChannelId] | None,
    ) -> DownstreamOfdmParameters | None:
        if not channel_ids:
            return None
        return DownstreamOfdmParameters(channel_id=list(channel_ids))

# For dynamic auto-registration
router = MultiRxMerRouter().router

# FILE: src/pypnm/api/routes/advance/multi_rxmer/service.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
import math
from typing import cast

from pypnm.api.routes.advance.common.capture_service import AbstractCaptureService
from pypnm.api.routes.common.extended.common_measure_schema import (
    DownstreamOfdmParameters,
)
from pypnm.api.routes.common.extended.common_messaging_service import MessageResponse
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.api.routes.docs.pnm.ds.ofdm.fec_summary.service import (
    CmDsOfdmFecSummaryService,
)
from pypnm.api.routes.docs.pnm.ds.ofdm.modulation_profile.service import (
    CmDsOfdmModProfileService,
)
from pypnm.api.routes.docs.pnm.ds.ofdm.rxmer.service import CmDsOfdmRxMerService
from pypnm.docsis.cable_modem import CableModem, PnmConfigManager
from pypnm.docsis.cm_snmp_operation import FecSummaryType
from pypnm.lib.inet import Inet


class MultiRxMerService(AbstractCaptureService):
    """
    Service to trigger a Cable Modem's RxMER capture via SNMP/TFTP and
    collect corresponding file-transfer transactions as CaptureSample objects.

    Each invocation of _capture_sample will:
      1. Send SNMP command to start RxMER capture and TFTP transfer.
      2. Await MessageResponse payload containing transaction entries.
      3. For each payload entry of type PNM_FILE_TRANSACTION with SUCCESS status:
         - Lookup the transaction record for filename retrieval.
         - Yield a CaptureSample(timestamp, transaction_id, filename).
      4. On SNMP/TFTP error or no valid entries, return a single CaptureSample
         with the appropriate error message.

    Inherited:
      - duration: total measurement duration in seconds.
      - interval: interval between captures in seconds.
    """
    def __init__(self, cm: CableModem, duration: float, interval: float,
                 tftp_servers: tuple[Inet, Inet] = PnmConfigManager.get_tftp_servers(),
                 tftp_path: str = PnmConfigManager.get_tftp_path(),
                 interface_parameters: DownstreamOfdmParameters | None = None,) -> None:
        """
        Initialize the MultiRxMerService.

        Args:
            cm: Configured CableModem instance for SNMP/TFTP operations.
            duration: Total duration (seconds) to run periodic captures.
            interval: Time (seconds) between successive captures.
        """
        super().__init__(duration, interval)
        self.cm = cm
        self.tftp_servers = tftp_servers
        self.tftp_path = tftp_path
        self.logger = logging.getLogger(self.__class__.__name__)
        self._interface_parameters = interface_parameters

    async def _capture_message_response(self) -> MessageResponse:
        """
        Perform one RxMER capture cycle.

        Returns:
            A list of CaptureSample objects. On success, one per file-transfer
            transaction; on error, a single Sample with error filled.

        Error handling:
            - Catches exceptions from SNMP/TFTP invocation.
            - Validates payload type and entry contents.
        """
        try:
            msg_rsp: MessageResponse = await CmDsOfdmRxMerService(
                self.cm,
                self.tftp_servers,
                self.tftp_path,
            ).set_and_go(interface_parameters=self._interface_parameters)

        except Exception as exc:
            err_msg = f"Exception during RxMER SNMP/TFTP operation: {exc}"
            self.logger.error(err_msg, exc_info=True)
            return MessageResponse(ServiceStatusCode.DS_OFDM_RXMER_NOT_AVAILABLE)

        if msg_rsp.status != ServiceStatusCode.SUCCESS:
            err_msg = f"SNMP/TFTP failure: status={msg_rsp.status}"
            self.logger.error(err_msg)
            return MessageResponse(ServiceStatusCode.DS_OFDM_RXMER_NOT_AVAILABLE)

        return msg_rsp

class MultiRxMer_Ofdm_Performance_1_Service(AbstractCaptureService):
    """
    Service to trigger a Cable Modem's RxMER capture via SNMP/TFTP and
    collect corresponding file-transfer transactions as CaptureSample objects.

    Each invocation of _capture_sample will:
      1. Send SNMP command to start RxMER capture and TFTP transfer.
      2. Await MessageResponse payload containing transaction entries.
      3. For each payload entry of type PNM_FILE_TRANSACTION with SUCCESS status:
         - Lookup the transaction record for filename retrieval.
         - Yield a CaptureSample(timestamp, transaction_id, filename).
      4. On SNMP/TFTP error or no valid entries, return a single CaptureSample
         with the appropriate error message.

    Inherited:
      - duration: total measurement duration in seconds.
      - interval: interval between captures in seconds.
    """
    def __init__(self, cm: CableModem,
                tftp_servers: tuple[Inet, Inet] = PnmConfigManager.get_tftp_servers(),
                tftp_path: str = PnmConfigManager.get_tftp_path(),
                duration: float = 1, interval: float = 1,
                interface_parameters: DownstreamOfdmParameters | None = None,) -> None:
        """
        Initialize the MultiRxMerService.

        Args:
            cm: Configured CableModem instance for SNMP/TFTP operations.
            duration: Total duration (seconds) to run periodic captures.
            interval: Time (seconds) between successive captures.
        """
        super().__init__(duration, interval)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cm = cm
        self.tftp_servers = tftp_servers
        self.tftp_path = tftp_path
        self._half_life = math.ceil(self.duration/2)
        self._mod_profile_done = False
        self._interface_parameters = interface_parameters

        MIN_10 = 600
        self._fec_thresholds = list(range(int(self.duration), -1, -MIN_10))
        self._handled_fec_thresholds = set()

    async def _capture_message_response(self) -> MessageResponse:
        """
        Operation:
        -----------------------
        * Collect a series of RxMER
        * Collect at least 1 Modualtion Profile at 50% duration
        * Collect a Fec Summary at:
            - 1 FecSummary every 10 Min (10 Min provides sec-by-sec accounting)
            - At end of the test

        OFDM_PROFILE_MEASUREMENT_1
        --------------------------
        * Calculate the Avg RxMER of the series
        * Calculate Shannon for each subcarrier
        * Compare each Modualtion Profile against the RxMER Average
        * Calculate the percentage of subcarries that are outside a given profile
        * Provide total FEC Stats for each profile over the time of the capture.

        Returns:
            A list of CaptureSample objects. On success, one per file-transfer
            transaction; on error, a single Sample with error filled.

        Error handling:
            - Catches exceptions from SNMP/TFTP invocation.
            - Validates payload type and entry contents.
        """
        operation_id = self.getOperationID()
        self.logger.debug(f'OperationID: {operation_id}')
        operation = self.getOperation(operation_id)
        time_remaining = cast(int, operation['time_remaining'])

        # First, perform the primary RxMER capture
        try:
            msg_rsp: MessageResponse = await CmDsOfdmRxMerService(
                self.cm,
                self.tftp_servers,
                self.tftp_path,
            ).set_and_go(interface_parameters=self._interface_parameters)
        except Exception as exc:
            self.logger.error(f"Exception during RxMER capture: {exc}", exc_info=True)
            return MessageResponse(ServiceStatusCode.DS_OFDM_RXMER_NOT_AVAILABLE)

        # 50%‐time modulation profile (only once)
        if not self._mod_profile_done and time_remaining <= self._half_life:
            self._mod_profile_done = True

            self.logger.info(f'Collecting a Modulation Profile @ {time_remaining}s')
            try:
                msg_rsp = await CmDsOfdmModProfileService(
                    self.cm,
                    self.tftp_servers,
                    self.tftp_path,
                ).set_and_go(interface_parameters=self._interface_parameters)

            except Exception as exc:
                self.logger.error(f"Exception during ModProfile capture: {exc}", exc_info=True)
                return MessageResponse(ServiceStatusCode.DS_OFDM_MOD_PROFILE_NOT_AVALAIBLE)

            if msg_rsp.status != ServiceStatusCode.SUCCESS:
                self.logger.error(f'Unable to get OFDM Modualtion Profile, status={msg_rsp.status.name}')
                return MessageResponse(ServiceStatusCode.DS_OFDM_MOD_PROFILE_NOT_AVALAIBLE)

        # Every 10 min/600 seconds (and once at end), FEC summary
        self.logger.info(f'Checking FEC Summary @ TimeRemaining={time_remaining}s')

        for thresh in self._fec_thresholds:
            self.logger.info(f'INSIDE-THRESH-LOOP({thresh}): Checking FEC Summary @ TimeRemaining={time_remaining}s - Thresholds: {self._fec_thresholds}')
            self.logger.info(f'Final-Invovcation: {self.getOperationFinalInvocation(operation_id)}')

            if self.getOperationFinalInvocation(operation_id) or (time_remaining <= thresh) and (thresh not in self._handled_fec_thresholds):

                self._handled_fec_thresholds.add(thresh)
                self.logger.info(f'Collecting a FEC Summary @ TimeRemaining={time_remaining}s (threshold={thresh})')

                try:
                    msg_rsp = await CmDsOfdmFecSummaryService(
                        self.cm,
                        FecSummaryType.TEN_MIN,
                        tftp_servers=self.tftp_servers,
                        tftp_path=self.tftp_path,
                    ).set_and_go(interface_parameters=self._interface_parameters)

                except Exception as exc:
                    self.logger.error(f"Exception during FEC summary: {exc}", exc_info=True)
                    return MessageResponse(ServiceStatusCode.DS_OFDM_FEC_SUMMARY_NOT_AVALIABLE)

                if msg_rsp.status != ServiceStatusCode.SUCCESS:
                    self.logger.error(f'Unable to get last FecSummary, status={msg_rsp.status.name}')
                    return MessageResponse(ServiceStatusCode.DS_OFDM_FEC_SUMMARY_NOT_AVALIABLE)

                break

        return msg_rsp

# FILE: docs/api/fast-api/multi/multi-capture-rxmer.md
# Multi‑RxMER Capture & Analysis API

A concise, implementation‑ready reference for orchestrating downstream OFDM RxMER captures, status polling, result retrieval,
early termination, and post‑capture analysis.

## Contents

* [At a Glance](#at-a-glance)
* [Workflow](#workflow)
* [Endpoints](#endpoints)
  * [1) Start Capture](#1-start-capture)
  * [2) Status Check](#2-status-check)
  * [3) Download Results](#3-download-results)
  * [4) Stop Capture Early](#4-stop-capture-early)
  * [5) Analysis](#5-analysis)
* [Timing & Polling](#timing--polling)
* [Plot Examples](#plot-examples)
  * [Min‑Avg‑Max Line Plot](#min-avg-max-line-plot)
  * [RxMER Heat Map](#rxmer-heat-map)
  * [OFDM Profile Performance 1 Overlay](#ofdm-profile-performance-1-overlay)
* [Response Field Reference](#response-field-reference)
  * [Start / Status / Stop](#start--status--stop)
  * [Download ZIP](#download-zip)
  * [Analysis (JSON)](#analysis-json)
* [Compatibility Matrix](#compatibility-matrix)

## At a Glance

| Step | HTTP   | Path                                         | Purpose                                  |
| ---: | :----- | :------------------------------------------- | :--------------------------------------- |
|    1 | POST   | `/advance/multiRxMer/start`                  | Begin a background capture               |
|    2 | GET    | `/advance/multiRxMer/status/{operation_id}`  | Poll capture progress                    |
|    3 | GET    | `/advance/multiRxMer/results/{operation_id}` | Download a ZIP of captured PNM files     |
|    4 | DELETE | `/advance/multiRxMer/stop/{operation_id}`    | Stop the capture after current iteration |
|    5 | POST   | `/advance/multiRxMer/analysis`               | Run post‑capture analytics               |

### Identifiers

* `group_id`: Logical grouping for related operations.
* `operation_id`: Unique handle for one capture session. Use it for status, stop, results, and analysis.

## Workflow

1. **Start Capture** → receive `group_id` and `operation_id`.
2. **Poll Status** until `state ∈ ["completed","stopped"]`.
3. **Download Results** once finished or stopped.
4. **(Optional)** **Stop Early** to end after the current iteration.
5. **Run Analysis** on the finished capture using `operation_id` + analysis type.

## Endpoints

### 1) Start Capture

Starts a background RxMER capture with a fixed duration and sample interval.

**Request** `POST /advance/multiRxMer/start`  
**Body** (`MultiRxMerRequest`):

```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.10",
        "ipv6": "2001:db8::10"
      },
      "capture": {
        "channel_ids": [193, 194]
      }
    },
    "snmp": {
      "snmpV2C": { "community": "public" }
    }
  },
  "capture": {
    "parameters": {
      "measurement_duration": 60,
      "sample_interval": 10
    }
  },
  "measure": { "mode": 1 }
}
```

When `pnm_parameters.capture.channel_ids` is omitted or empty, the capture includes all downstream OFDM channels.

#### Compatibility Matrix

| Measure Mode        | Suited Analyses                                                | Processes                                |
| ------------------- | -------------------------------------------------------------- | ---------------------------------------- |
|      `0`            | `min-avg-max`, `rxmer-heat-map`                                | RxMER                                    |
|      `1`            | `ofdm-profile-performance-1`, `min-avg-max`, `rxmer-heat-map`  | RxMER + Modulation Profile + FEC Summary |

> Use `mode=1` when you specifically want OFDM performance context; otherwise `mode=0` is recommended for continuous monitoring.

#### Response (MultiRxMerStartResponse)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": "running",
  "message": "Starting Multi-RxMER capture for MAC=aa:bb:cc:dd:ee:ff",
  "group_id": "3bd6f7c107ad465b",
  "operation_id": "4aca137c1e9d4eb6"
}
```

### 2) Status Check

**Request** `GET /advance/multiRxMer/status/{operation_id}`

#### Response (MultiRxMerStatusResponse)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": "success",
  "message": null,
  "operation": {
    "operation_id": "4aca137c1e9d4eb6",
    "state": "running",
    "collected": 2,
    "time_remaining": 50,
    "message": null
  }
}
```

### 3) Download Results

**Request** `GET /advance/multiRxMer/results/{operation_id}`

#### Response

* `Content-Type: application/zip`
* ZIP name: `<mac>_<model>_<ephoc>.zip`
* Contains files like:

```text
ds_ofdm_rxmer_per_subcar_aabbccddeeff_160_1751762613.bin
ds_ofdm_modulation_profile_aabbccddeeff_160_1762980708
ds_ofdm_codeword_error_rate_aabbccddeeff_160_1762980674.bin
aabbccddeeff_lpet3_1762980743_rxmer_min_avg_max_160.csv
aabbccddeeff_lpet3_1762981896_ofdm_profile_perf_1_ch160_pid0.csv
aabbccddeeff_lpet3_1762981556_rxmer_ofdm_heat_map_160.csv
aabbccddeeff_lpet3_1763007607_160_profile_0_ofdm_profile_perf_1.png
aabbccddeeff_lpet3_1763007680_160_rxmer_min_avg_max.png
aabbccddeeff_lpet3_1763007737_160_rxmer_heat_map.png 
```

### 4) Stop Capture Early

**Request** `DELETE /advance/multiRxMer/stop/{operation_id}`

#### Stop Response (MultiRxMerStatusResponse)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": "stopped",
  "message": null,
  "operation": {
    "operation_id": "4aca137c1e9d4eb6",
    "state": "stopped",
    "collected": 4,
    "time_remaining": 42,
    "message": null
  }
}
```

### 5) Analysis

**Request** `POST /advance/multiRxMer/analysis`  
**Body** (`MultiRxMerAnalysisRequest` - preferred string enums):

```json
{
  "analysis": {
    "type": "min-avg-max",
    "output": { "type": "json" }
  },
  "operation_id": "4aca137c1e9d4eb6"
}
```

**Analysis Types** (`analysis.type`)

| Type                         | Description                          | `measure.mode`|
| ---------------------------- | ------------------------------------ | ------------- |
| `min-avg-max`                | Min/Avg/Max RxMER across samples     | `0` or `1`    |
| `rxmer-heat-map`             | Time × Frequency heatmap grid        | `0` or `1`    |
| `ofdm-profile-performance-1` | Per‑subcarrier performance metrics   | `1`           |

**Output Types** (`analysis.output.type`)

| Value      | Name      | Description                              | Media Type         |
| :--------- | :-------- | :--------------------------------------- | :----------------- |
| `"json"`   | `JSON`    | Structured JSON body                     | `application/json` |
| `"archive"`| `ARCHIVE` | ZIP containing multiple artifacts        | `application/zip`  |

## Timing & Polling {#timing--polling}

### Capture Timing

* `measurement_duration` *(s)* → total run length. Example: `60` means one minute.
* `sample_interval` *(s)* → period between samples. Example: `10` over `60` seconds → **6** samples.

### Polling Strategy

* Poll **no more than once per** `sample_interval`.
* Stop polling when `time_remaining == 0` **and** `state == "completed"`.

### Results Availability

* When `state ∈ ["completed","stopped"]`, the ZIP is immediately available.
* Files are produced at sampling time; the archive is just a bundle step.

### Stop Semantics

1. Current iteration finishes.  
2. Final PNM for that iteration is written.  
3. `state → "stopped"` (remaining time may be > 0 if mid‑interval).

## Plot Examples

### Min-Avg-Max Line Plot

| Plot | Description | Note |
| ---- | ----------- | ---- |
| [Min‑Avg‑Max](./images/multi-rxmer/160_rxmer_min_avg_max.png) | Min/Avg/Max RxMER across samples. | Constant line indicates low RxMER @ 750MHz |

### RxMER Heat Map

| Plot | Description | Note |
| ---- | ----------- | ---- |
| [Heat-Map](./images/multi-rxmer/160_rxmer_heat_map.png) | Time × Frequency heatmap grid. | Constant dark Line indicating low RxMER |

### OFDM Profile Performance 1 Overlay

| Plot | Profile | Description |
| ---- | :-----: | ----------- |
| [256‑QAM](./images/multi-rxmer/160_profile_0_ofdm_profile_perf_1.png) | `0` | Avg‑RxMER with modulation profile overlay and FEC summary across sample time. |
| [1K‑QAM](./images/multi-rxmer/160_profile_1_ofdm_profile_perf_1.png)  | `1` | Avg‑RxMER with modulation profile overlay and FEC summary across sample time. |
| [2K‑QAM](./images/multi-rxmer/160_profile_2_ofdm_profile_perf_1.png)  | `2` | Avg‑RxMER with modulation profile overlay and FEC summary across sample time. |
| [4K‑QAM](./images/multi-rxmer/160_profile_3_ofdm_profile_perf_1.png)  | `3` | Avg‑RxMER with modulation profile overlay and FEC summary across sample time. |

## Response Field Reference

### Start / Status / Stop {#start--status--stop}

| Field                       | Type    | Description                                                                 |
| -------------------------- | ------- | --------------------------------------------------------------------------- |
| `mac_address`              | string  | Cable modem MAC address.                                                    |
| `status`                   | string  | Start: `"running"`; Status/Stop: high‑level status string.                |
| `message`                  | string  | Optional detail text.                                                       |
| `group_id`                 | string  | Logical grouping for related operations (Start only).                       |
| `operation_id`             | string  | Unique capture handle used with status/results/stop/analysis.               |
| `operation.state`          | string  | Current state: `running`, `completed`, or `stopped`.                        |
| `operation.collected`      | integer | Number of captured samples.                                                 |
| `operation.time_remaining` | integer | Estimated seconds left.                                                     |

### Download ZIP

| Aspect                | Value / Format                                           |
| -------------------- | --------------------------------------------------------- |
| `Content-Type`       | `application/zip`                                         |
| ZIP name             | `multiRxMer_<mac>_<operation_id>.zip`                     |
| PNM file name format | `ds_ofdm_rxmer_per_subcar_<mac>_<channel_id>_<epoch>.bin` |

### Analysis (JSON)

These keys appear under the `data` object of `MultiRxMerAnalysisResponse`. Per‑type models differ, but common fields include:

| Field/Path                                       | Type/Example             | Meaning                                                                              |
| ------------------------------------------------ | ------------------------ | ------------------------------------------------------------------------------------ |
| `<channel_id>`                                   | string/int key           | Map key representing a single OFDM channel’s results.                                |
| `channel_id`                                     | int                      | Channel identifier repeated in the model.                                            |
| `frequency`                                      | array[int] (Hz)          | Per‑subcarrier center frequency.                                                     |
| `min` / `avg` / `max`                            | array[float] (dB)        | Min/avg/max RxMER per subcarrier (MIN_AVG_MAX).                                      |
| `timestamps`                                     | array[int] (epoch sec)   | Capture timestamps for heat map rows (RXMER_HEAT_MAP).                               |
| `values`                                         | array[array[float]] (dB) | Heat map matrix rows aligned to `timestamps` (RXMER_HEAT_MAP).                       |
| `avg_mer`                                        | array[float] (dB)        | Average MER across captures per subcarrier (OFDM_PROFILE_PERFORMANCE_1).             |
| `mer_shannon_limits`                             | array[float] (dB)        | Derived MER (min SNR) per subcarrier (OFDM_PROFILE_PERFORMANCE_1).                   |
| `profiles[].profile_id`                          | int                      | Modulation profile index.                                                            |
| `profiles[].profile_min_mer`                     | array[float] (dB)        | Minimum MER allowed by the profile per subcarrier.                                   |
| `profiles[].capacity_delta`                      | array[float] (dB)        | `avg_mer - profile_min_mer` per subcarrier.                                          |
| `profiles[].fec_summary.start/end`               | int (epoch sec)          | FEC observation window boundaries.                                                   |
| `profiles[].fec_summary.summary[].summary.total_codewords` | int            | Total FEC codewords counted.                                                         |
| `profiles[].fec_summary.summary[].summary.corrected`       | int            | FEC corrected codewords.                                                             |
| `profiles[].fec_summary.summary[].summary.uncorrectable`   | int            | Uncorrectable codewords.                                                             |

# FILE: tests/test_multi_rxmer_channel_ids.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest

from pypnm.api.routes.advance.common.operation_state import OperationState
from pypnm.api.routes.advance.multi_rxmer import service as rxmer_service
from pypnm.api.routes.advance.multi_rxmer.service import (
    MultiRxMer_Ofdm_Performance_1_Service,
    MultiRxMerService,
)
from pypnm.api.routes.common.extended.common_measure_schema import (
    DownstreamOfdmParameters,
)
from pypnm.api.routes.common.extended.common_messaging_service import (
    MessageResponse,
)
from pypnm.api.routes.common.service.status_codes import ServiceStatusCode
from pypnm.lib.types import ChannelId, OperationId


@pytest.mark.asyncio
async def test_multi_rxmer_passes_channel_ids_to_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[DownstreamOfdmParameters | None] = []

    class _FakeRxMerService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def set_and_go(
            self,
            interface_parameters: DownstreamOfdmParameters | None = None,
        ) -> MessageResponse:
            captured.append(interface_parameters)
            return MessageResponse(ServiceStatusCode.SUCCESS)

    monkeypatch.setattr(rxmer_service, "CmDsOfdmRxMerService", _FakeRxMerService)

    interface_parameters = DownstreamOfdmParameters(channel_id=[ChannelId(193)])
    service = MultiRxMerService(
        cm=object(),
        duration=1,
        interval=1,
        interface_parameters=interface_parameters,
    )

    await service._capture_message_response()

    assert captured == [interface_parameters]


@pytest.mark.asyncio
async def test_multi_rxmer_perf_mode_passes_channel_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[DownstreamOfdmParameters | None] = []

    class _FakeRxMerService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def set_and_go(
            self,
            interface_parameters: DownstreamOfdmParameters | None = None,
        ) -> MessageResponse:
            captured.append(interface_parameters)
            return MessageResponse(ServiceStatusCode.SUCCESS)

    class _FakeModProfileService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def set_and_go(
            self,
            interface_parameters: DownstreamOfdmParameters | None = None,
        ) -> MessageResponse:
            return MessageResponse(ServiceStatusCode.SUCCESS)

    class _FakeFecSummaryService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def set_and_go(
            self,
            interface_parameters: DownstreamOfdmParameters | None = None,
        ) -> MessageResponse:
            return MessageResponse(ServiceStatusCode.SUCCESS)

    monkeypatch.setattr(rxmer_service, "CmDsOfdmRxMerService", _FakeRxMerService)
    monkeypatch.setattr(rxmer_service, "CmDsOfdmModProfileService", _FakeModProfileService)
    monkeypatch.setattr(rxmer_service, "CmDsOfdmFecSummaryService", _FakeFecSummaryService)

    interface_parameters = DownstreamOfdmParameters(channel_id=[ChannelId(193)])
    service = MultiRxMer_Ofdm_Performance_1_Service(
        cm=object(),
        duration=1,
        interval=1,
        interface_parameters=interface_parameters,
    )

    operation_id = OperationId("op")
    service._operation_id = operation_id
    service._ops[operation_id] = {
        "group_id": "group",
        "state": OperationState.RUNNING,
        "start_time": 0.0,
        "duration": 1,
        "interval": 1,
        "time_remaining": 2,
        "samples": [],
        "final_invocation": False,
    }

    await service._capture_message_response()

    assert captured == [interface_parameters]
