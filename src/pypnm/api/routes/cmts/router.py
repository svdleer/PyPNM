# SPDX-License-Identifier: Apache-2.0
# CMTS Discovery API Routes

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager
from pypnm.api.routes.cmts.schemas import (
    CMTSModemRequest,
    CMTSModemResponse,
)
from pypnm.api.routes.cmts.service import CMTSModemService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmts", tags=["CMTS Discovery"])

# Ensure agent manager is initialized
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)


@router.post("/modems", response_model=CMTSModemResponse)
async def get_cmts_modems(request: CMTSModemRequest) -> CMTSModemResponse:
    """
    **CMTS Modem Discovery**
    
    Discover all cable modems registered on a CMTS via SNMP bulk walk.
    
    The request is routed to an available PyPNM agent which performs
    parallel SNMP walks of the DOCSIS modem registration tables.
    
    **Returns for each modem:**
    - MAC address, IP address, registration status
    - DOCSIS version (1.0, 1.1, 2.0, 3.0, 3.1)
    - Upstream interface and channel information
    - Partial service state (D3.1)
    - Vendor from MAC OUI lookup
    
    **Optional enrichment** (enrich=true):
    - Model name from modem sysDescr
    - Software/firmware version from modem sysDescr
    - DOCSIS capability from modem MIB
    
    **Performance:**
    - Base discovery: ~3 seconds for 1000+ modems
    - With enrichment: ~30-60 seconds (queries each modem)
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    logger.info(f"CMTS modem discovery request: {request.cmts_ip} (enrich={request.enrich})")
    
    # Create service instance
    service = CMTSModemService()
    
    try:
        # Get modems from CMTS
        result = await service.discover_modems(
            cmts_ip=request.cmts_ip,
            community=request.community,
            limit=request.limit,
            enrich=request.enrich,
            modem_community=request.modem_community
        )
        
        if not result.get('success'):
            return CMTSModemResponse(
                success=False,
                modems=[],
                count=0,
                error=result.get('error', 'Discovery failed')
            )
        
        modems = result.get('modems', [])
        enriched = result.get('enriched', False)
        
        return CMTSModemResponse(
            success=True,
            modems=modems,
            count=len(modems),
            enriched=enriched,
            cached=result.get('cached', False),
            enriching=result.get('enriching', False),
        )
        
    except Exception as e:
        logger.exception(f"Error in CMTS modem discovery: {e}")
        return CMTSModemResponse(
            success=False,
            modems=[],
            count=0,
            error=str(e)
        )
