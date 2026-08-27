# PyPNM Agent API Routes
# SPDX-License-Identifier: Apache-2.0

from fastapi import APIRouter, WebSocket, HTTPException, Query
from fastapi.responses import JSONResponse
import logging
import os

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Initialize agent manager on module import
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)
logger.info("Agent manager initialized")


@router.websocket("/ws")
async def agent_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for remote agent connections.
    
    Agents connect here to receive commands from PyPNM.
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        await websocket.close(code=1011, reason="Agent manager not initialized")
        return
    
    await agent_manager.handle_websocket(websocket)


@router.get("")
async def list_agents():
    """
    List all connected remote agents.
    
    Returns information about each connected agent including:
    - agent_id
    - capabilities
    - connection time
    - alive status
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        return JSONResponse(
            status_code=503,
            content={"error": "Agent manager not initialized"}
        )
    
    agents = agent_manager.get_available_agents()
    return {
        "agents": agents,
        "count": len(agents),
        "status": "success"
    }


@router.get("/logs")
async def get_agent_logs(
    agent_id: str | None = Query(default=None, description="Filter by agent ID"),
    level: str | None = Query(default=None, description="Minimum log level (DEBUG/INFO/WARNING/ERROR)"),
    limit: int = Query(default=200, ge=1, le=5000, description="Max entries to return"),
):
    """Return recent log entries streamed from connected agents."""
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    entries = agent_manager.get_agent_logs(agent_id=agent_id, level=level, limit=limit)
    return {"status": "success", "logs": entries, "count": len(entries)}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get information about a specific agent."""
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    agent = agent_manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    return agent.to_dict()
