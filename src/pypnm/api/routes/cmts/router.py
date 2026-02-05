# SPDX-License-Identifier: Apache-2.0
# CMTS Discovery API Routes

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging
import os

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmts", tags=["CMTS Discovery"])

# Ensure agent manager is initialized (may already be done by agents router)
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)


class CMTSModemRequest(BaseModel):
    """Request model for CMTS modem discovery."""
    cmts_ip: str
    community: str = "public"
    limit: int = 10000
    enrich: bool = False  # Whether to enrich modems with firmware/model
    modem_community: str = "private"  # SNMP community for modem enrichment


class ModemInfo(BaseModel):
    """Basic modem information from CMTS."""
    mac_address: str
    index: Optional[int] = None


class CMTSModemResponse(BaseModel):
    """Response model for CMTS modem discovery."""
    success: bool
    modems: List[Dict[str, Any]]
    count: int
    timestamp: Optional[str] = None
    error: Optional[str] = None
    enriched: Optional[bool] = False
    cached: Optional[bool] = False
    enriching: Optional[bool] = False


@router.post("/modems", response_model=CMTSModemResponse)
async def get_cmts_modems(request: CMTSModemRequest):
    """
    Get all modems from a CMTS via agent SNMP bulk walk.
    
    This endpoint routes the SNMP request to an available agent which performs
    a bulk walk of the DOCSIS modem MAC address table (docsIfCmtsCmStatusMacAddress).
    
    The agent must have network access to the CMTS and appropriate SNMP credentials.
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not available")
    
    # Get an agent capable of SNMP operations
    agents = agent_manager.get_available_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents available")
    
    # Use first available agent
    agent = agents[0]
    agent_id = agent.get('agent_id') if isinstance(agent, dict) else agent.agent_id
    
    logger.info(f"Routing CMTS modem discovery to agent {agent_id}: {request.cmts_ip}")
    
    try:
        # Send CMTS modem discovery task to agent
        # Uses cmts_get_modems which does parallel walks for MAC, IP, Status
        task_id = await agent_manager.send_task(
            agent_id=agent_id,
            command='cmts_get_modems',
            params={
                'cmts_ip': request.cmts_ip,
                'community': request.community,
                'limit': request.limit,
                'enrich': request.enrich,
                'modem_community': request.modem_community,
                'use_bulk': True,
                'use_cache': True
            },
            timeout=120
        )
        
        # Wait for agent response (use async version!)
        result = await agent_manager.wait_for_task_async(task_id, timeout=120)
        
        if not result:
            return CMTSModemResponse(
                success=False,
                modems=[],
                count=0,
                error="Timeout waiting for agent response"
            )
        
        if result.get('result', {}).get('success'):
            modems = result.get('result', {}).get('modems', [])
            agent_result = result.get('result', {})
            return CMTSModemResponse(
                success=True,
                modems=modems,
                count=len(modems),
                timestamp=result.get('timestamp'),
                enriched=agent_result.get('enriched', False),
                cached=agent_result.get('cached', False),
                enriching=agent_result.get('enriching', False)
            )
        else:
            error_msg = result.get('result', {}).get('error', 'Unknown agent error')
            return CMTSModemResponse(
                success=False,
                modems=[],
                count=0,
                error=error_msg
            )
    
    except Exception as e:
        logger.error(f"Error in CMTS modem discovery: {e}")
        return CMTSModemResponse(
            success=False,
            modems=[],
            count=0,
            error=str(e)
        )
