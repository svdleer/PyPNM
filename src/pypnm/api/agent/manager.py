# PyPNM Agent Manager
# SPDX-License-Identifier: Apache-2.0
#
# Manages WebSocket connections to remote agents

import asyncio
import json
import logging
import time
import uuid
from queue import Queue, Empty
from typing import Optional
from fastapi import WebSocket

from pypnm.api.agent.models import ConnectedAgent, PendingTask

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages WebSocket connections to remote agents."""
    
    def __init__(self, auth_token: str = 'dev-token-change-me'):
        self.agents: dict[str, ConnectedAgent] = {}
        self.pending_tasks: dict[str, PendingTask] = {}
        self.auth_token = auth_token
        self._task_queues: dict[str, Queue] = {}
        self._async_task_queues: dict[str, asyncio.Queue] = {}
        self.logger = logging.getLogger(f'{__name__}.AgentManager')
    
    async def handle_websocket(self, websocket: WebSocket):
        """Handle WebSocket connection from agent."""
        await websocket.accept()
        agent_id = None
        
        try:
            # Wait for auth message
            while True:
                message = await websocket.receive_text()
                response = await self.handle_message(websocket, message)
                
                if response:
                    await websocket.send_text(response)
                
                # Check if authenticated
                for aid, agent in self.agents.items():
                    if agent.websocket == websocket and agent.authenticated:
                        agent_id = aid
                        break
                
                if agent_id:
                    break
            
            # Main message loop with periodic ping
            async def ping_loop():
                while agent_id in self.agents:
                    await asyncio.sleep(30)
                    if agent_id in self.agents:
                        try:
                            await websocket.send_text(json.dumps({'type': 'ping', 'timestamp': time.time()}))
                        except Exception:
                            break

            asyncio.ensure_future(ping_loop())

            while True:
                message = await websocket.receive_text()
                # Update last_seen on any message — agent is clearly alive
                if agent_id and agent_id in self.agents:
                    self.agents[agent_id].last_seen = time.time()
                response = await self.handle_message(websocket, message)
                if response:
                    await websocket.send_text(response)
                    
        except Exception as e:
            self.logger.error(f"WebSocket error: {e}")
        finally:
            if agent_id:
                self.remove_agent(websocket)
    
    async def handle_message(self, websocket: WebSocket, message: str) -> Optional[str]:
        """Handle incoming message from agent. Returns response message or None."""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'auth':
                return self._handle_auth(websocket, data)
            
            elif msg_type == 'response':
                self._handle_response(data)
                return None
            
            elif msg_type == 'pong':
                self._handle_pong(websocket)
                return None
            
            elif msg_type == 'error':
                self._handle_error(data)
                return None
            
            else:
                self.logger.warning(f"Unknown message type: {msg_type}")
                return None
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON: {e}")
            return json.dumps({'type': 'error', 'error': 'Invalid JSON'})
    
    def _handle_auth(self, websocket: WebSocket, data: dict) -> str:
        """Handle agent authentication."""
        agent_id = data.get('agent_id')
        token = data.get('token')
        capabilities = data.get('capabilities', [])
        
        if token != self.auth_token:
            self.logger.warning(f"Auth failed for {agent_id}: invalid token")
            return json.dumps({
                'type': 'auth_response',
                'success': False,
                'error': 'Invalid token'
            })
        
        # Register agent
        agent = ConnectedAgent(
            agent_id=agent_id,
            websocket=websocket,
            capabilities=capabilities,
            authenticated=True
        )
        self.agents[agent_id] = agent
        
        self.logger.info(f"Agent authenticated: {agent_id} with {capabilities}")
        return json.dumps({
            'type': 'auth_success',
            'agent_id': agent_id,
            'message': 'Authenticated successfully'
        })
    
    def _handle_response(self, data: dict):
        """Handle task response from agent."""
        request_id = data.get('request_id')
        
        if request_id not in self.pending_tasks:
            self.logger.warning(f"Response for unknown task: {request_id}")
            return
        
        task = self.pending_tasks[request_id]
        task.completed = True
        task.result = data.get('result')
        task.error = data.get('error')
        
        # Put in queue if waiting
        if request_id in self._task_queues:
            self._task_queues[request_id].put(data)
        
        # Put in async queue if waiting
        if request_id in self._async_task_queues:
            try:
                self._async_task_queues[request_id].put_nowait(data)
            except asyncio.QueueFull:
                self.logger.error(f"Async queue full for task: {request_id}")
        
        self.logger.info(f"Task completed: {request_id}")
    
    def _handle_pong(self, websocket: WebSocket):
        """Handle pong from agent."""
        for agent in self.agents.values():
            if agent.websocket == websocket:
                agent.last_seen = time.time()
                break
    
    def _handle_error(self, data: dict):
        """Handle error from agent."""
        request_id = data.get('request_id')
        error = data.get('error')
        
        if request_id in self.pending_tasks:
            task = self.pending_tasks[request_id]
            task.completed = True
            task.error = error
            
            if request_id in self._task_queues:
                self._task_queues[request_id].put(data)
    
    def remove_agent(self, websocket: WebSocket):
        """Remove agent by WebSocket connection."""
        to_remove = None
        for agent_id, agent in self.agents.items():
            if agent.websocket == websocket:
                to_remove = agent_id
                break
        
        if to_remove:
            del self.agents[to_remove]
            self.logger.info(f"Agent disconnected: {to_remove}")
    
    def get_available_agents(self) -> list[dict]:
        """Get list of connected agents."""
        return [agent.to_dict() for agent in self.agents.values() if agent.authenticated]
    
    def get_agent(self, agent_id: str) -> Optional[ConnectedAgent]:
        """Get agent by ID."""
        return self.agents.get(agent_id)
    
    def get_agent_for_capability(self, capability: str) -> Optional[ConnectedAgent]:
        """Find agent with required capability."""
        for agent in self.agents.values():
            if agent.authenticated and capability in agent.capabilities:
                return agent
        return None

    def get_agent_id_for_capability(self, capability: str) -> Optional[str]:
        """
        Return agent_id of the first agent advertising *capability*.
        Falls back to the first authenticated agent so single-agent deployments
        keep working even when the agent doesn't advertise fine-grained caps.
        """
        # Prefer exact capability match
        for agent in self.agents.values():
            if agent.authenticated and capability in agent.capabilities:
                return agent.agent_id
        # Fallback: any authenticated agent
        for agent in self.agents.values():
            if agent.authenticated:
                return agent.agent_id
        return None
    
    async def send_task(self, agent_id: str, command: str, params: dict, timeout: float = 30.0) -> str:
        """Send task to agent. Returns task_id."""
        if agent_id not in self.agents:
            raise ValueError(f"Agent not connected: {agent_id}")
        
        agent = self.agents[agent_id]
        if not agent.authenticated:
            raise ValueError(f"Agent not authenticated: {agent_id}")
        
        task_id = str(uuid.uuid4())
        
        task = PendingTask(
            task_id=task_id,
            command=command,
            params=params,
            timeout=timeout
        )
        self.pending_tasks[task_id] = task
        self._task_queues[task_id] = Queue()
        self._async_task_queues[task_id] = asyncio.Queue(maxsize=1)
        
        # Send command to agent
        msg = json.dumps({
            'type': 'command',
            'request_id': task_id,
            'command': command,
            'params': params
        })
        
        try:
            await agent.websocket.send_text(msg)
            self.logger.info(f"Sent task {task_id} ({command}) to {agent_id}")
        except Exception as e:
            self.logger.error(f"Failed to send task: {e}")
            del self.pending_tasks[task_id]
            del self._task_queues[task_id]
            raise
        
        return task_id
    
    def wait_for_task(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for task result (blocking - for sync code only)."""
        if task_id not in self._task_queues:
            return None
        
        try:
            result = self._task_queues[task_id].get(timeout=timeout)
            return result
        except Empty:
            return None
        finally:
            if task_id in self._task_queues:
                del self._task_queues[task_id]
            if task_id in self._async_task_queues:
                del self._async_task_queues[task_id]
            if task_id in self.pending_tasks:
                del self.pending_tasks[task_id]
    
    async def wait_for_task_async(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for task result (async - for async code)."""
        if task_id not in self._async_task_queues:
            return None
        
        try:
            result = await asyncio.wait_for(
                self._async_task_queues[task_id].get(),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout waiting for task: {task_id}")
            return None
        finally:
            if task_id in self._task_queues:
                del self._task_queues[task_id]
            if task_id in self._async_task_queues:
                del self._async_task_queues[task_id]
            if task_id in self.pending_tasks:
                del self.pending_tasks[task_id]


# Global instance
_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> Optional[AgentManager]:
    """Get the agent manager instance."""
    return _agent_manager


def init_agent_manager(auth_token: str = None) -> AgentManager:
    """Initialize the agent manager."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager(auth_token or 'dev-token-change-me')
        logger.info("Agent manager initialized")
    return _agent_manager
