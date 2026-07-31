# SPDX-License-Identifier: Apache-2.0
# CMTS Discovery API Routes

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager
from pypnm.api.routes.cmts.schemas import CMTSModemRequest, CMTSModemResponse
from pypnm.api.routes.cmts.service import CMTSModemService, cancel_enrichment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmts", tags=["CMTS Discovery"])

# Ensure agent manager is initialized
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)


@router.get("/modems", response_model=CMTSModemResponse)
async def get_cmts_modems(
    cmts_ip: str,
    community: str = "public",
    limit: int | None = None,
    enrich: bool = False,
    modem_community: str = "private",
    cmts_hostname: str = "",
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

    if limit is None:
        raw = os.environ.get("CM_MODEM_LIMIT", "10000")
        try:
            limit = max(1, min(int(raw), 50000))
        except (TypeError, ValueError):
            limit = 10000

    try:
        result = await service.discover_modems(
            cmts_ip=cmts_ip,
            community=community,
            limit=limit,
            enrich=enrich,
            modem_community=modem_community,
            cmts_hostname=cmts_hostname or "",
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
            enrichment_progress=result.get('enrich_progress'),
        )
        
    except Exception as e:
        logger.exception(f"Error in CMTS modem discovery: {e}")
        return CMTSModemResponse(
            success=False,
            modems=[],
            count=0,
            error=str(e)
        )


@router.post("/modems/query", response_model=CMTSModemResponse)
async def query_cmts_modems(payload: CMTSModemRequest) -> CMTSModemResponse:
    """Discover CMTS modems without placing SNMP credentials in the URL."""
    return await get_cmts_modems(
        cmts_ip=payload.cmts_ip,
        community=payload.community,
        limit=payload.limit,
        enrich=payload.enrich,
        modem_community=payload.modem_community,
        cmts_hostname=payload.cmts_hostname,
    )


@router.post("/enrich/cancel")
async def cancel_enrich(cmts_ip: str):
    """Cancel an in-progress background enrichment for the given CMTS."""
    cancelled = cancel_enrichment(cmts_ip)
    return {"status": "cancelled" if cancelled else "not_running", "cmts_ip": cmts_ip}
