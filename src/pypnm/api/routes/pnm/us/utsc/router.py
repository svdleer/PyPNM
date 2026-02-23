# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for CMTS Upstream Triggered Spectrum Capture (UTSC) operations.

This module provides FastAPI endpoints for CMTS-side UTSC measurements.

Endpoints:
- GET  /ports:     List available RF ports for UTSC
- GET  /config:    Get current UTSC configuration
- POST /configure: Configure UTSC test parameters
- POST /start:     Start UTSC test
- POST /stop:      Stop UTSC test
- POST /clear:     Clear/reset UTSC configuration
- GET  /status:    Get UTSC test status
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter

import asyncio

from pypnm.api.routes.pnm.us.utsc.schemas import (
    UtscListPortsRequest,
    UtscListPortsResponse,
    UtscGetConfigRequest,
    UtscGetConfigResponse,
    UtscConfigureRequest,
    UtscConfigureResponse,
    UtscStartRequest,
    UtscStartResponse,
    UtscStopRequest,
    UtscStopResponse,
    UtscStatusRequest,
    UtscStatusResponse,
)
from pypnm.api.routes.pnm.us.utsc.service import CmtsUtscService


class UtscRouter:
    """Router for CMTS Upstream Triggered Spectrum Capture operations."""
    
    def __init__(self) -> None:
        prefix = "/pnm/us/utsc"
        self.router = APIRouter(
            prefix=prefix,
            tags=["PNM Operations - CMTS Upstream Triggered Spectrum Capture (UTSC)"]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__routes()
    
    def __routes(self) -> None:
        
        @self.router.get(
            "/ports",
            summary="List RF ports available for UTSC",
            response_model=UtscListPortsResponse,
        )
        async def list_rf_ports(
            cmts_ip: str,
            community: str = "public",
            write_community: Optional[str] = None
        ) -> UtscListPortsResponse:
            """
            List available RF ports for UTSC tests.

            Returns a list of RF port ifIndexes that can be used for
            upstream triggered spectrum capture measurements.
            """
            self.logger.info(f"Listing RF ports on CMTS {cmts_ip}")
            service = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.list_rf_ports()
                return UtscListPortsResponse(**result)
            finally:
                service.close()
        
        @self.router.get(
            "/config",
            summary="Get current UTSC configuration",
            response_model=UtscGetConfigResponse,
        )
        async def get_config(
            cmts_ip: str,
            rf_port_ifindex: int,
            community: str = "public",
            write_community: Optional[str] = None,
            cfg_index: int = 1
        ) -> UtscGetConfigResponse:
            """
            Get current UTSC configuration for an RF port.

            Returns the current settings including trigger mode, frequency range,
            output format, timing parameters, and filename.
            """
            self.logger.info(
                f"Getting UTSC config for RF port {rf_port_ifindex} on CMTS {cmts_ip}"
            )
            service = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.get_config(
                    rf_port_ifindex=rf_port_ifindex,
                    cfg_index=cfg_index
                )
                return UtscGetConfigResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/configure",
            summary="Configure UTSC test parameters",
            response_model=UtscConfigureResponse,
        )
        async def configure(
            request: UtscConfigureRequest
        ) -> UtscConfigureResponse:
            """
            Configure UTSC test parameters.
            
            Sets up the upstream triggered spectrum capture with the specified
            trigger mode, frequency range, output format, timing, and filename.
            
            SNMP OIDs used (docsPnmCmtsUtscCfgTable):
            - docsPnmCmtsUtscCfgTriggerMode: Trigger type (freeRunning, cmMac, etc.)
            - docsPnmCmtsUtscCfgCenterFreq: Center frequency in Hz
            - docsPnmCmtsUtscCfgSpan: Frequency span in Hz
            - docsPnmCmtsUtscCfgNumBins: Number of FFT bins
            - docsPnmCmtsUtscCfgOutputFormat: Output format (fftPower, etc.)
            - docsPnmCmtsUtscCfgRepeatPeriod: Repeat period in microseconds
            - docsPnmCmtsUtscCfgFreeRunDuration: Duration in milliseconds
            - docsPnmCmtsUtscCfgFilename: Output filename
            """
            self.logger.info(
                f"Configuring UTSC for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.configure(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index,
                    trigger_mode=request.trigger_mode,
                    cm_mac_address=request.cm_mac_address,
                    logical_ch_ifindex=request.logical_ch_ifindex,
                    center_freq_hz=request.center_freq_hz,
                    span_hz=request.span_hz,
                    num_bins=request.num_bins,
                    output_format=request.output_format,
                    window_function=request.window_function,
                    repeat_period_us=request.repeat_period_us,
                    freerun_duration_ms=request.freerun_duration_ms,
                    trigger_count=request.trigger_count,
                    filename=request.filename,
                    destination_index=request.destination_index
                )
                return UtscConfigureResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/start",
            summary="Start UTSC test",
            response_model=UtscStartResponse,
        )
        async def start(
            request: UtscStartRequest
        ) -> UtscStartResponse:
            """
            Start UTSC test on an RF port.
            
            Sets docsPnmCmtsUtscCtrlInitiateTest to true to begin the
            spectrum capture. Use /status to poll for completion.
            """
            self.logger.info(
                f"Starting UTSC for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.start(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index,
                    trigger_mode=request.trigger_mode
                )
                return UtscStartResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/stop",
            summary="Stop UTSC test",
            response_model=UtscStopResponse,
        )
        async def stop(
            request: UtscStopRequest
        ) -> UtscStopResponse:
            """
            Stop UTSC test on an RF port.
            
            Sets docsPnmCmtsUtscCtrlInitiateTest to false to stop the
            spectrum capture.
            """
            self.logger.info(
                f"Stopping UTSC for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.stop(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index
                )
                return UtscStopResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/clear",
            summary="Clear/reset UTSC configuration",
            response_model=UtscStopResponse,
        )
        async def clear_config(
            request: UtscStopRequest
        ) -> UtscStopResponse:
            """
            Clear/reset UTSC configuration by destroying the row.
            
            Sets docsPnmCmtsUtscCfgRowStatus to destroy(6) to remove
            the configuration entry. Use this to force reconfiguration
            with updated parameters.
            """
            self.logger.info(
                f"Clearing UTSC config for RF port {request.rf_port_ifindex} "
                f"on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUtscService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.clear_config(
                    rf_port_ifindex=request.rf_port_ifindex,
                    cfg_index=request.cfg_index
                )
                return UtscStopResponse(**result)
            finally:
                service.close()
        
        @self.router.get(
            "/status",
            summary="Get UTSC test status",
            response_model=UtscStatusResponse,
        )
        async def get_status(
            cmts_ip: str,
            rf_port_ifindex: int,
            community: str = "public",
            write_community: Optional[str] = None,
            cfg_index: int = 1
        ) -> UtscStatusResponse:
            """
            Get UTSC test status.

            Returns the measurement status, average power, and filename.
            Poll this endpoint after starting a test to check for completion.

            Status values:
            - OTHER (1): Unknown state
            - INACTIVE (2): No test running
            - BUSY (3): Test in progress
            - SAMPLE_READY (4): Test complete, data available
            - ERROR (5): Test failed
            - RESOURCE_UNAVAILABLE (6): Resources not available
            - SAMPLE_TRUNCATED (7): Data was truncated
            """
            self.logger.debug(f"Getting UTSC status for RF port {rf_port_ifindex}")
            service = CmtsUtscService(
                cmts_ip=cmts_ip,
                community=community,
                write_community=write_community or community
            )
            try:
                result = await service.get_status(
                    rf_port_ifindex=rf_port_ifindex,
                    cfg_index=cfg_index
                )
                return UtscStatusResponse(**result)
            finally:
                service.close()


# Required for dynamic auto-registration
router = UtscRouter().router
