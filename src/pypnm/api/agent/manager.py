# PyPNM Agent Manager
# SPDX-License-Identifier: Apache-2.0
#
# Manages WebSocket connections to remote agents

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
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
        self._task_agent_ids: dict[str, str] = {}
        self.auth_token = auth_token
        self._task_queues: dict[str, Queue] = {}
        self._async_task_queues: dict[str, asyncio.Queue] = {}
        self._rr_counters: dict[str, int] = {}  # round-robin index per capability
        self._agent_timeouts: dict[str, int] = {}  # consecutive timeout count per agent
        self._agent_quarantine: dict[str, float] = {}  # agent_id → quarantine-until timestamp
        self.QUARANTINE_AFTER = max(1, int(os.environ.get('PYPNM_AGENT_QUARANTINE_AFTER', '6')))
        self.QUARANTINE_SECS = max(1, int(os.environ.get('PYPNM_AGENT_QUARANTINE_SECS', '30')))
        self.logger = logging.getLogger(f'{__name__}.AgentManager')
        # Commands that involve large file transfers or long SNMP captures.
        # These get a higher default timeout and are routed to the agent's
        # dedicated long-running thread pool so they never starve SNMP workers.
        self.LONG_COMMANDS: frozenset[str] = frozenset({
            'file_get', 'pnm_file_get', 'pnm_file_delete',
            'pnm_file_housekeeping', 'snmp_set_sequence',
        })
        self.LONG_TASK_TIMEOUT: float = 90.0   # default timeout for long commands
        # Per-agent log ring buffers — populated by agents streaming type=log messages
        self.AGENT_LOG_BUFFER_SIZE: int = 1000
        self._agent_logs: dict[str, deque[dict]] = {}

    def _describe_task(self, task_id: str) -> str:
        """Build a concise task description for timeout/error diagnostics."""
        task = self.pending_tasks.get(task_id)
        if not task:
            return "unknown task"

        params = task.params or {}
        target_ip = params.get('target_ip') or params.get('ip') or params.get('cmts_ip') or '-'
        if 'oid' in params:
            oid_desc = f"oid={params.get('oid')}"
        elif 'oids' in params:
            oids = params.get('oids') or []
            oid_desc = f"oids={len(oids)}"
        else:
            oid_desc = "oid=-"

        agent_id = self._task_agent_ids.get(task_id, '-')
        return f"agent={agent_id} command={task.command} target={target_ip} {oid_desc}"

    def _record_agent_success(self, agent_id: str):
        """Reset timeout counter on successful result."""
        if agent_id in self._agent_timeouts:
            del self._agent_timeouts[agent_id]

    def _record_agent_timeout(self, agent_id: str):
        """Track consecutive timeout; quarantine after threshold."""
        count = self._agent_timeouts.get(agent_id, 0) + 1
        self._agent_timeouts[agent_id] = count
        if count >= self.QUARANTINE_AFTER:
            until = time.time() + self.QUARANTINE_SECS
            self._agent_quarantine[agent_id] = until
            self.logger.warning(
                f"Agent '{agent_id}' quarantined for {self.QUARANTINE_SECS}s "
                f"after {count} consecutive timeouts"
            )

    def _is_quarantined(self, agent_id: str) -> bool:
        """Check if agent is currently quarantined."""
        until = self._agent_quarantine.get(agent_id)
        if until is None:
            return False
        if time.time() >= until:
            # Quarantine expired — give it another chance
            del self._agent_quarantine[agent_id]
            self._agent_timeouts.pop(agent_id, None)
            self.logger.info(f"Agent '{agent_id}' quarantine expired, re-enabling")
            return False
        return True

    def _cleanup_task(self, task_id: str):
        """Cleanup all task bookkeeping structures."""
        if task_id in self._task_queues:
            del self._task_queues[task_id]
        if task_id in self._async_task_queues:
            del self._async_task_queues[task_id]
        if task_id in self.pending_tasks:
            del self.pending_tasks[task_id]
        if task_id in self._task_agent_ids:
            del self._task_agent_ids[task_id]
    
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
            
            elif msg_type == 'log':
                self._handle_log(data)
                return None
            
            elif msg_type == 'log_batch':
                self._handle_log_batch(data)
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
            self.logger.warning(f"Response for unknown/expired task: {request_id} — task may have timed out before agent responded")
            return

        task = self.pending_tasks[request_id]
        task.completed = True
        task.result = data.get('result')
        task.error = data.get('error')

        in_sync  = request_id in self._task_queues
        in_async = request_id in self._async_task_queues
        self.logger.debug(f"Task {request_id} response received — sync_waiter={in_sync} async_waiter={in_async}")

        # Put in queue if waiting
        if in_sync:
            self._task_queues[request_id].put(data)

        # Put in async queue if waiting
        if in_async:
            try:
                self._async_task_queues[request_id].put_nowait(data)
            except asyncio.QueueFull:
                self.logger.error(f"Async queue full for task: {request_id}")

        if not in_sync and not in_async:
            self.logger.warning(f"Task {request_id} has no waiters — response dropped (caller already timed out)")

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
            if request_id in self._async_task_queues:
                try:
                    self._async_task_queues[request_id].put_nowait(data)
                except asyncio.QueueFull:
                    self.logger.error(f"Async queue full for errored task: {request_id}")

    def _handle_log(self, data: dict) -> None:
        """Store a streamed log entry from an agent in its ring buffer."""
        agent_id = data.get("agent_id", "unknown")
        entry = data.get("entry", {})
        if not entry:
            return
        buf = self._agent_logs.get(agent_id)
        if buf is None:
            buf = deque(maxlen=self.AGENT_LOG_BUFFER_SIZE)
            self._agent_logs[agent_id] = buf
        buf.append(entry)

    def _handle_log_batch(self, data: dict) -> None:
        """Store a batch of log entries from an agent."""
        agent_id = data.get("agent_id", "unknown")
        entries = data.get("entries", [])
        if not entries:
            return
        buf = self._agent_logs.get(agent_id)
        if buf is None:
            buf = deque(maxlen=self.AGENT_LOG_BUFFER_SIZE)
            self._agent_logs[agent_id] = buf
        for entry in entries:
            if isinstance(entry, dict):
                buf.append(entry)

    def get_agent_logs(
        self,
        agent_id: str | None = None,
        level: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return recent log entries, optionally filtered by agent and level."""
        level_upper = level.upper() if level else None
        level_order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        min_level = level_order.get(level_upper, 0) if level_upper else 0

        entries: list[dict] = []
        sources = (
            [(agent_id, self._agent_logs.get(agent_id, deque()))]
            if agent_id
            else list(self._agent_logs.items())
        )
        for aid, buf in sources:
            for e in buf:
                elevel = level_order.get((e.get("level") or "").upper(), 0)
                if elevel >= min_level:
                    entries.append({**e, "agent_id": aid})

        entries.sort(key=lambda x: x.get("ts", 0))
        return entries[-limit:]
    
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
        """Find agent with required capability, round-robin across all alive agents."""
        agent_id = self.get_agent_id_for_capability(capability)
        if agent_id:
            return self.agents.get(agent_id)
        return None

    def get_all_agent_ids_for_capability(self, capability: str) -> list[str]:
        """Return all agent IDs advertising *capability* (round-robin ordered, skipping quarantined)."""
        capable = [a.agent_id for a in self.agents.values()
                   if a.authenticated and a.is_alive() and capability in a.capabilities]
        healthy = [aid for aid in capable if not self._is_quarantined(aid)]
        pool = healthy if healthy else capable
        # Rotate list to start from next round-robin position
        if pool:
            idx = self._rr_counters.get(capability, 0) % len(pool)
            pool = pool[idx:] + pool[:idx]
        return pool

    def get_agent_id_for_capability(self, capability: str) -> Optional[str]:
        """
        Return agent_id of the next agent advertising *capability*, round-robin.

        Routing rules:
        - CM task  → agent that advertises the required CM capability
        - CMTS task → agent that advertises the required CMTS capability
        - An agent advertising both will match either
        - No fallback to unrelated agents
        - Multiple agents with the same capability are load-balanced round-robin
        """
        capable = [a.agent_id for a in self.agents.values()
                   if a.authenticated and a.is_alive() and capability in a.capabilities]
        if not capable:
            self.logger.warning(f"No agent available for capability '{capability}' — connected agents: {list(self.agents.keys())}")
            return None
        # Filter out quarantined agents (but keep at least one)
        healthy = [aid for aid in capable if not self._is_quarantined(aid)]
        pool = healthy if healthy else capable
        if len(healthy) < len(capable):
            quarantined = [aid for aid in capable if aid not in healthy]
            self.logger.debug(f"Skipping quarantined agents {quarantined} for '{capability}'")
        idx = self._rr_counters.get(capability, 0) % len(pool)
        self._rr_counters[capability] = idx + 1
        agent_id = pool[idx]
        self.logger.debug(f"Routing '{capability}' task → agent '{agent_id}' (round-robin {idx+1}/{len(pool)})")
        return agent_id
    
    async def send_task(self, agent_id: str, command: str, params: dict, timeout: float = 30.0, priority: str = 'interactive') -> str:
        """Send task to agent. Returns task_id.

        For commands in LONG_COMMANDS (file_get, pnm_file_get) the timeout is
        automatically raised to LONG_TASK_TIMEOUT and priority set to 'long'
        so the agent routes them to its dedicated long-running thread pool.
        The caller may still pass an explicit timeout > LONG_TASK_TIMEOUT to
        override further.
        """
        if command in self.LONG_COMMANDS:
            if timeout < self.LONG_TASK_TIMEOUT:
                timeout = self.LONG_TASK_TIMEOUT
            if priority == 'interactive':
                priority = 'long'
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
        self._task_agent_ids[task_id] = agent_id
        self._task_queues[task_id] = Queue()
        self._async_task_queues[task_id] = asyncio.Queue(maxsize=1)
        
        # Send command to agent
        msg = json.dumps({
            'type': 'command',
            'request_id': task_id,
            'command': command,
            'params': params,
            'priority': priority,
        })
        
        try:
            await agent.websocket.send_text(msg)
            self.logger.info(f"Sent task {task_id} ({command}) to agent '{agent_id}'")
        except Exception as e:
            self.logger.error(f"Failed to send task {task_id} to '{agent_id}': {e}")
            self._cleanup_task(task_id)
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
            task_desc = self._describe_task(task_id)
            self.logger.error(f"Timeout ({timeout}s) waiting (sync) for task {task_id} — {task_desc}")
            return None
        finally:
            self._cleanup_task(task_id)
    
    async def wait_for_task_async(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for task result (async - for async code)."""
        if task_id not in self._async_task_queues:
            return None
        
        try:
            result = await asyncio.wait_for(
                self._async_task_queues[task_id].get(),
                timeout=timeout
            )
            # Success — reset timeout counter for this agent
            agent_id = self._task_agent_ids.get(task_id)
            if agent_id:
                self._record_agent_success(agent_id)
            return result
        except asyncio.TimeoutError:
            task_desc = self._describe_task(task_id)
            # Record timeout for quarantine tracking
            agent_id = self._task_agent_ids.get(task_id)
            if agent_id:
                self._record_agent_timeout(agent_id)
            self.logger.error(
                f"Timeout ({timeout}s) waiting for task {task_id} — {task_desc}; "
                "agent is still running; increase timeout or reduce SNMP repetitions"
            )
            return {'success': False, 'error': f'Agent task timeout after {timeout}s'}
        finally:
            self._cleanup_task(task_id)


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
