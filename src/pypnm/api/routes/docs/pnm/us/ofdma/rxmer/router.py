# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

"""
Router for CMTS Upstream OFDMA RxMER operations.

This module provides FastAPI endpoints for CMTS-side US OFDMA RxMER
measurements. These are CMTS-based measurements that require SNMP
access to the CMTS, not the cable modem.

Endpoints:
- POST /discover: Discover modem's OFDMA channel ifIndex on CMTS
- POST /start: Start US OFDMA RxMER measurement
- POST /status: Get measurement status
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from pypnm.api.routes.docs.pnm.us.ofdma.rxmer.schemas import (
    UsOfdmaRxMerDiscoverRequest,
    UsOfdmaRxMerDiscoverResponse,
    UsOfdmaRxMerStartRequest,
    UsOfdmaRxMerStartResponse,
    UsOfdmaRxMerStatusRequest,
    UsOfdmaRxMerStatusResponse,
    BulkDestinationsRequest,
    BulkDestinationsResponse,
)
from pypnm.api.routes.docs.pnm.us.ofdma.rxmer.service import CmtsUsOfdmaRxMerService


class UsOfdmaRxMerRouter:
    """Router for CMTS Upstream OFDMA RxMER operations."""
    
    def __init__(self) -> None:
        prefix = "/docs/pnm/us/ofdma/rxmer"
        self.router = APIRouter(
            prefix=prefix,
            tags=["PNM Operations - CMTS Upstream OFDMA RxMER"]
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__routes()
    
    def __routes(self) -> None:
        
        @self.router.post(
            "/discover",
            summary="Discover modem's OFDMA channel on CMTS",
            response_model=UsOfdmaRxMerDiscoverResponse,
        )
        async def discover_ofdma(
            request: UsOfdmaRxMerDiscoverRequest
        ) -> UsOfdmaRxMerDiscoverResponse:
            """
            Discover a cable modem's OFDMA channel ifIndex on the CMTS.
            
            This endpoint queries the CMTS via SNMP to:
            1. Find the CM registration index from MAC address
            2. Find the OFDMA channel ifIndex for that CM
            3. Get the OFDMA channel description
            
            The returned ofdma_ifindex is required for starting US RxMER measurements.
            """
            self.logger.info(
                f"Discovering OFDMA for CM {request.cm_mac_address} on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.discover_modem_ofdma(request.cm_mac_address)
                return UsOfdmaRxMerDiscoverResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/start",
            summary="Start US OFDMA RxMER measurement",
            response_model=UsOfdmaRxMerStartResponse,
        )
        async def start_measurement(
            request: UsOfdmaRxMerStartRequest
        ) -> UsOfdmaRxMerStartResponse:
            """
            Start an Upstream OFDMA RxMER measurement on the CMTS.
            
            This endpoint triggers the CMTS to measure the RxMER (Receive MER)
            per subcarrier on the specified OFDMA channel for the given cable modem.
            
            The measurement runs asynchronously. Use the /status endpoint to poll
            for completion, then retrieve the results via TFTP.
            
            SNMP OIDs used (docsPnmCmtsUsOfdmaRxMerTable):
            - docsPnmCmtsUsOfdmaRxMerEnable: Start/stop measurement
            - docsPnmCmtsUsOfdmaRxMerPreEq: Pre-equalization on/off
            - docsPnmCmtsUsOfdmaRxMerNumAvgs: Number of averages
            - docsPnmCmtsUsOfdmaRxMerFileName: Output filename
            - docsPnmCmtsUsOfdmaRxMerCmMac: Target CM MAC address
            """
            self.logger.info(
                f"Starting US RxMER for CM {request.cm_mac_address}, "
                f"OFDMA ifIndex {request.ofdma_ifindex} on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.start_measurement(
                    ofdma_ifindex=request.ofdma_ifindex,
                    cm_mac=request.cm_mac_address,
                    filename=request.filename,
                    pre_eq=request.pre_eq,
                    num_averages=request.num_averages,
                    destination_index=request.destination_index
                )
                return UsOfdmaRxMerStartResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/status",
            summary="Get US OFDMA RxMER measurement status",
            response_model=UsOfdmaRxMerStatusResponse,
        )
        async def get_status(
            request: UsOfdmaRxMerStatusRequest
        ) -> UsOfdmaRxMerStatusResponse:
            """
            Get the status of an Upstream OFDMA RxMER measurement.
            
            Poll this endpoint after starting a measurement to check when
            it completes. Status values:
            - INACTIVE (2): No measurement running
            - BUSY (3): Measurement in progress
            - SAMPLE_READY (4): Measurement complete, data available
            - ERROR (5): Measurement failed
            """
            self.logger.debug(
                f"Getting US RxMER status for OFDMA ifIndex {request.ofdma_ifindex}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.get_status(request.ofdma_ifindex)
                return UsOfdmaRxMerStatusResponse(**result)
            finally:
                service.close()
        
        @self.router.post(
            "/destinations",
            summary="Get bulk transfer destinations",
            response_model=BulkDestinationsResponse,
        )
        async def get_bulk_destinations(
            request: BulkDestinationsRequest
        ) -> BulkDestinationsResponse:
            """
            Get list of configured bulk data transfer destinations.
            
            Returns the available destination indexes that can be used with
            the destination_index parameter in the /start endpoint to enable
            automatic TFTP upload of measurement results.
            
            Destination index 0 means local storage only. Non-zero values
            reference rows in the docsPnmBulkDataTransferCfgTable.
            """
            self.logger.info(
                f"Getting bulk destinations on CMTS {request.cmts.cmts_ip}"
            )
            
            service = CmtsUsOfdmaRxMerService(
                cmts_ip=request.cmts.cmts_ip,
                community=request.cmts.community,
                write_community=request.cmts.write_community
            )
            
            try:
                result = await service.get_bulk_destinations()
                return BulkDestinationsResponse(**result)
            finally:
                service.close()


# Required for dynamic auto-registration
router = UsOfdmaRxMerRouter().router
