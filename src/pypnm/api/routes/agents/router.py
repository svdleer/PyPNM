# PyPNM Agent API Routes
# SPDX-License-Identifier: Apache-2.0

from fastapi import APIRouter, WebSocket, HTTPException, Depends, Query
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


@router.post("/{agent_id}/task")
async def send_task(agent_id: str, command: str, params: dict, timeout: Optional[float] = 30.0, wait: Optional[bool] = True):
    """
    Send a task to a specific agent.
    
    Args:
        agent_id: The ID of the agent
        command: The command to execute
        params: Command parameters
        timeout: Task timeout in seconds
        wait: If True, wait for task result (default True)
    
    Returns:
        task_id: ID of the created task
        result: Task result if wait=True
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")
    
    try:
        task_id = await agent_manager.send_task(agent_id, command, params, timeout)
        pending_task = agent_manager.pending_tasks.get(task_id)
        effective_timeout = pending_task.timeout if pending_task is not None else timeout
        
        if wait:
            # Honor the effective timeout selected by the manager.
            result = await agent_manager.wait_for_task_async(task_id, timeout=effective_timeout)
            if result:
                return {"task_id": task_id, "status": "completed", "success": True, "result": result}
            else:
                return {"task_id": task_id, "status": "timeout", "success": False, "error": "Task timed out"}
        
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


@router.delete("/{agent_id}")
async def disconnect_agent(agent_id: str):
    """
    Disconnect and remove an agent from the pool.

    The agent's WebSocket is closed and it is removed from the available pool.
    The agent process itself is not stopped — it will reconnect unless stopped manually.
    """
    agent_manager = get_agent_manager()
    if not agent_manager:
        raise HTTPException(status_code=503, detail="Agent manager not initialized")

    agent = agent_manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        await agent.websocket.close(code=1001, reason="Disconnected by admin")
    except Exception:
        pass  # already closed

    agent_manager.agents.pop(agent_id, None)
    agent_manager._agent_timeouts.pop(agent_id, None)
    agent_manager._agent_quarantine.pop(agent_id, None)
    logger.info(f"Agent '{agent_id}' disconnected and removed from pool by admin request")

    return {"status": "disconnected", "agent_id": agent_id}
