# SPDX-License-Identifier: Apache-2.0
# CMTS Discovery API Routes

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from pypnm.api.agent.manager import get_agent_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmts", tags=["CMTS Discovery"])


class CMTSModemRequest(BaseModel):
    """Request model for CMTS modem discovery."""
    cmts_ip: str
    community: str = "public"
    limit: int = 10000


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
    agent_id = agent.agent_id
    
    logger.info(f"Routing CMTS modem discovery to agent {agent_id}: {request.cmts_ip}")
    
    try:
        # Send SNMP bulk walk task to agent
        # DOCSIS 3.0 Cable Modem MAC Table OID
        task_id = await agent_manager.send_task(
            agent_id=agent_id,
            command='snmp_bulk_walk',
            params={
                'target_ip': request.cmts_ip,
                'oid': '1.3.6.1.2.1.10.127.1.3.3.1.2',  # docsIfCmtsCmStatusMacAddress
                'community': request.community,
                'max_repetitions': 25,
                'limit': request.limit
            },
            timeout=60
        )
        
        # Wait for agent response
        result = await agent_manager.wait_for_task(task_id, timeout=60)
        
        if not result:
            return CMTSModemResponse(
                success=False,
                modems=[],
                count=0,
                error="Timeout waiting for agent response"
            )
        
        if result.get('result', {}).get('success'):
            modems = result.get('result', {}).get('modems', [])
            return CMTSModemResponse(
                success=True,
                modems=modems,
                count=len(modems),
                timestamp=result.get('timestamp')
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
