# PyPNM Agent API Routes
# SPDX-License-Identifier: Apache-2.0

from fastapi import APIRouter, WebSocket, HTTPException, Depends
from fastapi.responses import JSONResponse
from typing import Optional
import logging
import os

from pypnm.api.agent.manager import get_agent_manager, init_agent_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Initialize agent manager on module import
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
init_agent_manager(_auth_token)
logger.info(f"Agent manager initialized with token: {_auth_token[:8]}...")


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


@router.post("/{agent_id}/task")
async def send_task(agent_id: str, command: str, params: dict, timeout: Optional[float] = 30.0):
    """
    Send a task to a specific agent.
    
    Args:
        agent_id: The ID of the agent
        command: The command to execute
        params: Command parameters
        timeout: Task timeout in seconds
    
    Returns:
        task_id: ID of the created task
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    try:
        task_id = await agent_manager.send_task(agent_id, command, params, timeout)
        return {"task_id": task_id, "status": "sent"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send task: {str(e)}")


@router.get("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    """
    Ping an agent to verify it's responsive.
    
    Args:
        agent_id: The ID of the agent
    
    Returns:
        Status of the ping operation
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    agent = agent_manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    try:
        task_id = await agent_manager.send_task(agent_id, "ping", {}, timeout=5.0)
        result = agent_manager.wait_for_task(task_id, timeout=5.0)
        
        if result:
            return {"status": "ok", "result": result}
        else:
            return {"status": "timeout", "message": "Agent did not respond"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
