# SPDX-License-Identifier: Apache-2.0
# PNM Upstream Diagnostics Router

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager
from pypnm.api.routes.pnm.schemas import (
    PNMModemRequest,
    PreEqResponse,
    USRxMERStartRequest,
    USRxMERStartResponse,
    USRxMERStatusRequest,
    USRxMERStatusResponse,
    USRxMERDataRequest,
    USRxMERDataResponse,
)
from pypnm.api.routes.pnm.service import PNMDiagnosticsService, USRxMERService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pnm/us", tags=["PNM - Upstream"])


@router.post("/pre-eq", response_model=PreEqResponse)
async def get_pre_eq(request: PNMModemRequest) -> PreEqResponse:
    """
    **Get Pre-Equalization Coefficients**
    
    Retrieves upstream pre-equalization coefficient data from a cable modem.
    
    Pre-equalization compensates for linear distortions in the upstream path.
    The coefficients indicate the adjustments the modem is making to transmit
    a clean signal.
    
    **Returns:**
    - Hex-encoded coefficient data per upstream channel
    - Can be parsed for in-depth plant analysis
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"Pre-eq request for modem {request.modem_ip}")
    
    service = PNMDiagnosticsService(
        modem_ip=request.modem_ip,
        community=request.community,
        mac_address=request.mac_address
    )
    
    try:
        result = await service.get_pre_eq()
        return PreEqResponse(**result)
    except Exception as e:
        logger.exception(f"Pre-eq error: {e}")
        return PreEqResponse(
            success=False,
            modem_ip=request.modem_ip,
            mac_address=request.mac_address,
            error=str(e)
        )


# ============================================
# Upstream RxMER (OFDMA) - CMTS-based
# ============================================

@router.post("/rxmer/start", response_model=USRxMERStartResponse)
async def start_us_rxmer(request: USRxMERStartRequest) -> USRxMERStartResponse:
    """
    **Start Upstream OFDMA RxMER Measurement**
    
    Initiates an upstream RxMER measurement on the CMTS for a specific
    cable modem and OFDMA channel.
    
    **Parameters:**
    - cmts_ip: CMTS IP address
    - ofdma_ifindex: OFDMA upstream channel interface index
    - cm_mac_address: Target cable modem MAC address
    
    **Note:** Requires SNMP write access to the CMTS.
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"US RxMER start request for CM {request.cm_mac_address} on CMTS {request.cmts_ip}")
    
    service = USRxMERService(
        cmts_ip=request.cmts_ip,
        community=request.community
    )
    
    try:
        result = await service.start(
            ofdma_ifindex=request.ofdma_ifindex,
            cm_mac_address=request.cm_mac_address,
            filename=request.filename,
            pre_eq=request.pre_eq
        )
        return USRxMERStartResponse(**result)
    except Exception as e:
        logger.exception(f"US RxMER start error: {e}")
        return USRxMERStartResponse(
            success=False,
            error=str(e)
        )


@router.post("/rxmer/status", response_model=USRxMERStatusResponse)
async def get_us_rxmer_status(request: USRxMERStatusRequest) -> USRxMERStatusResponse:
    """
    **Get Upstream RxMER Measurement Status**
    
    Retrieves the current status of an upstream RxMER measurement.
    
    **Status values:**
    - 2 = inactive (not running)
    - 3 = busy (measurement in progress)
    - 4 = sampleReady (data available)
    - 5 = error (measurement failed)
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"US RxMER status request for CMTS {request.cmts_ip}")
    
    service = USRxMERService(
        cmts_ip=request.cmts_ip,
        community=request.community
    )
    
    try:
        result = await service.get_status(ofdma_ifindex=request.ofdma_ifindex)
        return USRxMERStatusResponse(**result)
    except Exception as e:
        logger.exception(f"US RxMER status error: {e}")
        return USRxMERStatusResponse(
            success=False,
            error=str(e)
        )


@router.post("/rxmer/data", response_model=USRxMERDataResponse)
async def get_us_rxmer_data(request: USRxMERDataRequest) -> USRxMERDataResponse:
    """
    **Get Upstream RxMER Data**
    
    Retrieves and parses the upstream OFDMA RxMER measurement data.
    
    **Returns:**
    - Subcarrier indices
    - RxMER values in dB per subcarrier
    
    **Note:** Requires TFTP access to be configured in the agent.
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"US RxMER data request for CMTS {request.cmts_ip}")
    
    service = USRxMERService(
        cmts_ip=request.cmts_ip,
        community=request.community
    )
    
    try:
        result = await service.get_data(
            ofdma_ifindex=request.ofdma_ifindex,
            filename=request.filename
        )
        
        if not result.get('success'):
            return USRxMERDataResponse(
                success=False,
                error=result.get('error', 'Data retrieval failed')
            )
        
        data = result.get('data')
        if data:
            from pypnm.api.routes.pnm.schemas import USRxMERData
            rxmer_data = USRxMERData(
                subcarriers=data.get('subcarriers', []),
                rxmer_values=data.get('rxmer_values', []),
                ofdma_ifindex=data.get('ofdma_ifindex'),
                found_file=data.get('found_file')
            )
            return USRxMERDataResponse(
                success=True,
                data=rxmer_data
            )
        
        return USRxMERDataResponse(success=True)
        
    except Exception as e:
        logger.exception(f"US RxMER data error: {e}")
        return USRxMERDataResponse(
            success=False,
            error=str(e)
        )
