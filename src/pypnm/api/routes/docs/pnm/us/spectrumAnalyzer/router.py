from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

import asyncio
import logging

from fastapi import APIRouter

from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.schemas import (
    UtscRequest,
    UtscResponse,
)
from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.service import CmtsUtscService
from pypnm.lib.inet import Inet

router = APIRouter(prefix="/docs/pnm/us/spectrumAnalyzer", tags=["PNM - Upstream Spectrum (UTSC)"])
logger = logging.getLogger(__name__)


@router.post("/getCapture", response_model=UtscResponse)
async def get_utsc_capture(request: UtscRequest) -> UtscResponse:
    """
    Perform Upstream Triggered Spectrum Capture (UTSC) on CMTS.
    
    UTSC is CMTS-based, not modem-based. Sends SNMP to CMTS using RF port ifIndex.
    Supports FreeRunning and CM MAC Address trigger modes.
    """
    logger.info(f"UTSC: CMTS={request.cmts.cmts_ip}, RF Port={request.cmts.rf_port_ifindex}")
    
    try:
        service = CmtsUtscService(
            cmts_ip=Inet(request.cmts.cmts_ip),
            rf_port_ifindex=request.cmts.rf_port_ifindex,
            community=request.cmts.community
        )
        
        # Configure UTSC with 60 second timeout
        result = await asyncio.wait_for(
            service.configure(
                center_freq_hz=request.capture_parameters.center_freq_hz,
                span_hz=request.capture_parameters.span_hz,
                num_bins=request.capture_parameters.num_bins,
                trigger_mode=request.capture_parameters.trigger_mode,
                filename=request.capture_parameters.filename,
                tftp_ip=str(request.tftp.ipv4),
                cm_mac=request.trigger.cm_mac,
                logical_ch_ifindex=request.trigger.logical_ch_ifindex
            ),
            timeout=60.0
        )
        
        if not result.get("success"):
            logger.error(f"UTSC configuration failed: {result.get('error')}")
            return UtscResponse(success=False, error=result.get("error"))
        
        # Start capture with 15 second timeout
        start_result = await asyncio.wait_for(
            service.start(),
            timeout=15.0
        )
        
        if not start_result.get("success"):
            logger.error(f"UTSC start failed: {start_result.get('error')}")
            return UtscResponse(success=False, error=start_result.get("error"))
        
        logger.info("UTSC capture completed successfully")
        return UtscResponse(
            success=True,
            cmts_ip=str(request.cmts.cmts_ip),
            rf_port_ifindex=request.cmts.rf_port_ifindex,
            filename=request.capture_parameters.filename,
            data={"message": "UTSC started", "tftp_path": "./"}
        )
        
    except asyncio.TimeoutError:
        error_msg = "UTSC operation timed out after 75 seconds"
        logger.error(error_msg)
        return UtscResponse(success=False, error=error_msg)
    except Exception as e:
        error_msg = f"UTSC operation failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return UtscResponse(success=False, error=error_msg)
