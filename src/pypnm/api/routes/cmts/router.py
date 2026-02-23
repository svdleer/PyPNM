# SPDX-License-Identifier: Apache-2.0
# CMTS Discovery API Routes

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager
from pypnm.api.routes.cmts.schemas import CMTSModemResponse
from pypnm.api.routes.cmts.service import CMTSModemService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmts", tags=["CMTS Discovery"])

# Ensure agent manager is initialized
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)


@router.get("/modems", response_model=CMTSModemResponse)
async def get_cmts_modems(
    cmts_ip: str,
    community: str = "public",
    limit: int = 10000,
    enrich: bool = False,
    modem_community: str = "private",
) -> CMTSModemResponse:
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
    - ofdma_enabled / ofdm_enabled flags

    **Optional enrichment** (enrich=true):
    - Model name from modem sysDescr
    - Software/firmware version from modem sysDescr

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

    logger.info(f"CMTS modem discovery request: {cmts_ip} (enrich={enrich})")

    service = CMTSModemService()

    try:
        result = await service.discover_modems(
            cmts_ip=cmts_ip,
            community=community,
            limit=limit,
            enrich=enrich,
            modem_community=modem_community
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
