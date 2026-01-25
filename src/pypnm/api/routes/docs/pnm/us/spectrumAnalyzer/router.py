from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 PyPNM Upstream Spectrum Integration

import asyncio
import logging

from fastapi import APIRouter

from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.schemas import (
    UtscRequest,
    UtscResponse,
    UtscDiscoverRequest,
    UtscDiscoverResponse,
)
from pypnm.api.routes.docs.pnm.us.spectrumAnalyzer.service import CmtsUtscService, UtscRfPortDiscoveryService
from pypnm.config.system_config_settings import SystemConfigSettings
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
        # Get TFTP IP from request or fall back to system config
        tftp_ip = request.tftp.ipv4 if request.tftp.ipv4 else SystemConfigSettings.bulk_tftp_ip_v4()
        if not tftp_ip:
            return UtscResponse(success=False, error="TFTP IPv4 address required but not provided in request or system config")
        
        service = CmtsUtscService(
            cmts_ip=Inet(request.cmts.cmts_ip),
            rf_port_ifindex=request.cmts.rf_port_ifindex,
            community=request.cmts.community
        )
        
        # Step 1: Reset port to clean state (stop any active capture, wait for ready)
        reset_result = await asyncio.wait_for(
            service.reset_port_state(),
            timeout=15.0
        )
        if not reset_result.get("success"):
            logger.warning(f"Port reset warning: {reset_result.get('error')}")
            # Continue anyway - the port might still be usable
        
        # Step 2: Configure UTSC with 60 second timeout
        result = await asyncio.wait_for(
            service.configure(
                center_freq_hz=request.capture_parameters.center_freq_hz,
                span_hz=request.capture_parameters.span_hz,
                num_bins=request.capture_parameters.num_bins,
                trigger_mode=request.capture_parameters.trigger_mode,
                filename=request.capture_parameters.filename,
                tftp_ip=str(tftp_ip),
                cm_mac=request.trigger.cm_mac,
                logical_ch_ifindex=request.trigger.logical_ch_ifindex,
                repeat_period_ms=request.capture_parameters.repeat_period_ms,
                freerun_duration_ms=request.capture_parameters.freerun_duration_ms,
                trigger_count=request.capture_parameters.trigger_count
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


@router.post("/discoverRfPort", response_model=UtscDiscoverResponse)
async def discover_rf_port(request: UtscDiscoverRequest) -> UtscDiscoverResponse:
    """
    Discover the correct UTSC RF port for a cable modem.
    
    Uses the modem's upstream logical channel to find which RF port it belongs to.
    This is much faster than manual discovery as it tests the logical channel
    against each RF port until it finds a match.
    """
    logger.info(f"UTSC RF Port Discovery: CMTS={request.cmts_ip}, MAC={request.cm_mac_address}")
    
    try:
        service = UtscRfPortDiscoveryService(
            cmts_ip=Inet(request.cmts_ip),
            community=request.community
        )
        
        result = await asyncio.wait_for(
            service.discover(request.cm_mac_address),
            timeout=60.0
        )
        
        return UtscDiscoverResponse(
            success=result.get("success", False),
            rf_port_ifindex=result.get("rf_port_ifindex"),
            rf_port_description=result.get("rf_port_description"),
            cm_index=result.get("cm_index"),
            us_channels=result.get("us_channels", []),
            error=result.get("error")
        )
        
    except asyncio.TimeoutError:
        error_msg = "RF port discovery timed out"
        logger.error(error_msg)
        return UtscDiscoverResponse(success=False, error=error_msg)
    except Exception as e:
        error_msg = f"RF port discovery failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return UtscDiscoverResponse(success=False, error=error_msg)
