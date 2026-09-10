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
from threading import Lock, Timer
from typing import Optional
from fastapi import WebSocket

from pypnm.api.agent.models import ConnectedAgent, PendingTask

logger = logging.getLogger(__name__)


class AgentCapacityError(RuntimeError):
    """Raised before send when an agent priority pool has no free slots."""


class AgentManager:
    """Manages WebSocket connections to remote agents."""
    
    def __init__(self, auth_token: str = 'dev-token-change-me'):
        self.agents: dict[str, ConnectedAgent] = {}
        self.pending_tasks: dict[str, PendingTask] = {}
        self._task_agent_ids: dict[str, str] = {}
        self.auth_token = auth_token
        self._task_queues: dict[str, Queue] = {}
        self._async_task_queues: dict[str, asyncio.Queue] = {}
        self._task_lock = Lock()
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
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def _describe_task(self, task_id: str) -> str:
        """Build a concise task description for timeout/error diagnostics."""
        with self._task_lock:
            task = self.pending_tasks.get(task_id)
            agent_id = self._task_agent_ids.get(task_id, '-')
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
        """Cleanup task bookkeeping and release its reserved agent slot."""
        timeout_handle = None
        with self._task_lock:
            self._task_queues.pop(task_id, None)
            self._async_task_queues.pop(task_id, None)
            task = self.pending_tasks.pop(task_id, None)
            self._task_agent_ids.pop(task_id, None)
            if task:
                timeout_handle = task.timeout_handle
            if task:
                agent = task.agent_connection
                if agent is not None:
                    current = int(agent.in_flight.get(task.priority, 0))
                    agent.in_flight[task.priority] = max(0, current - 1)
        if timeout_handle is not None:
            timeout_handle.cancel()

    @staticmethod
    def _invoke_task_callback(task: PendingTask, event: dict) -> None:
        if task.callback is None:
            return
        try:
            task.callback(event)
        except Exception:
            logger.exception("Agent task callback failed for %s", task.task_id)

    def _deliver_task_event(self, data: dict, *, success: bool = False) -> bool:
        """Deliver one terminal event to a callback or waiter exactly once."""
        request_id = str(data.get('request_id') or '')
        with self._task_lock:
            task = self.pending_tasks.get(request_id)
            agent_id = self._task_agent_ids.get(request_id)
            sync_queue = self._task_queues.get(request_id)
            async_queue = self._async_task_queues.get(request_id)
            if task and task.completed:
                return False
            if task:
                task.completed = True
                task.result = data.get('result')
                task.error = data.get('error')
                callback = task.callback
            else:
                callback = None

        if not task:
            return False
        if success and agent_id and task.priority != "identity":
            self._record_agent_success(agent_id)

        if callback is not None:
            self._cleanup_task(request_id)
            self._invoke_task_callback(task, data)
            return True

        if sync_queue is not None:
            sync_queue.put(data)
        if async_queue is not None:
            try:
                async_queue.put_nowait(data)
            except asyncio.QueueFull:
                self.logger.error("Async queue full for task: %s", request_id)
        return True

    def _timeout_callback_task(self, task_id: str) -> None:
        with self._task_lock:
            task = self.pending_tasks.get(task_id)
            agent_id = self._task_agent_ids.get(task_id)
        if not task or task.completed or task.callback is None:
            return
        if agent_id and task.priority != "identity":
            self._record_agent_timeout(agent_id)
        event = {
            'type': 'error',
            'request_id': task_id,
            'error': f'Agent task timeout after {task.timeout}s',
            'terminal_reason': 'timeout',
        }
        self._deliver_task_event(event)
    
    async def handle_websocket(self, websocket: WebSocket):
        """Handle WebSocket connection from agent."""
        self._event_loop = asyncio.get_running_loop()
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
        raw_limits = data.get('limits') or {}
        limits: dict[str, int] = {}
        for priority, default in (("interactive", 50), ("bulk", 2), ("long", 10)):
            try:
                limits[priority] = max(1, min(int(raw_limits.get(priority, default)), 512))
            except (TypeError, ValueError):
                limits[priority] = default
        try:
            limits["identity"] = max(
                0,
                min(int(raw_limits.get("identity", 0)), 512),
            )
        except (TypeError, ValueError):
            limits["identity"] = 0
        
        if token != self.auth_token:
            self.logger.warning(f"Auth failed for {agent_id}: invalid token")
            return json.dumps({
                'type': 'auth_response',
                'success': False,
                'error': 'Invalid token'
            })
        
        previous = self.agents.get(agent_id)
        if previous is not None and previous.websocket is not websocket:
            with self._task_lock:
                previous_task_ids = [
                    task_id
                    for task_id, task in self.pending_tasks.items()
                    if task.agent_connection is previous
                ]
            for task_id in previous_task_ids:
                self._deliver_task_event(
                    {
                        'type': 'error',
                        'request_id': task_id,
                        'error': f"Agent connection replaced: {agent_id}",
                        'terminal_reason': 'agent_reconnected',
                    }
                )
            self.logger.warning(
                "Replacing existing connection for agent %s; retired %s tasks",
                agent_id,
                len(previous_task_ids),
            )

        # Register the new connection generation only after retiring the old one.
        agent = ConnectedAgent(
            agent_id=agent_id,
            websocket=websocket,
            capabilities=capabilities,
            limits=limits,
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
        """Handle a successful task response from an agent."""
        request_id = data.get('request_id')
        if not self._deliver_task_event(data, success=True):
            self.logger.warning(
                "Response for unknown/expired task: %s — task may have timed out",
                request_id,
            )
            return
        self.logger.info("Task completed: %s", request_id)
    
    def _handle_pong(self, websocket: WebSocket):
        """Handle pong from agent."""
        for agent in self.agents.values():
            if agent.websocket == websocket:
                agent.last_seen = time.time()
                break
    
    def _handle_error(self, data: dict):
        """Handle a terminal task error from an agent."""
        request_id = data.get('request_id')
        if not self._deliver_task_event(data):
            self.logger.warning("Error for unknown/expired task: %s", request_id)

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
        disconnected_agent = None
        for agent_id, agent in self.agents.items():
            if agent.websocket == websocket:
                to_remove = agent_id
                disconnected_agent = agent
                break

        if to_remove and disconnected_agent is not None:
            del self.agents[to_remove]
            with self._task_lock:
                task_ids = [
                    task_id
                    for task_id, task in self.pending_tasks.items()
                    if task.agent_connection is disconnected_agent
                ]
            for task_id in task_ids:
                self._deliver_task_event(
                    {
                        'type': 'error',
                        'request_id': task_id,
                        'error': f"Agent disconnected: {to_remove}",
                        'terminal_reason': 'agent_disconnected',
                    }
                )
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

    def get_agent_free_slots(self, agent_id: str, priority: str = "bulk") -> int:
        """Return advertised free executor slots for one connected agent."""
        agent = self.agents.get(agent_id)
        if not agent:
            return 0
        with self._task_lock:
            limit = int(agent.limits.get(priority, 1))
            used = int(agent.in_flight.get(priority, 0))
        return max(0, limit - used)

    def get_agent_id_for_capability(
        self,
        capability: str,
        *,
        priority: str | None = None,
        warn_if_unavailable: bool = True,
    ) -> Optional[str]:
        """
        Return agent_id of the next agent advertising *capability*, round-robin.

        Routing rules:
        - CM task  → agent that advertises the required CM capability
        - CMTS task → agent that advertises the required CMTS capability
        - An agent advertising both will match either
        - No fallback to unrelated agents
        - Multiple agents with the same capability are load-balanced round-robin
        """
        capable = [
            a.agent_id
            for a in self.agents.values()
            if a.authenticated
            and a.is_alive()
            and capability in a.capabilities
            and (
                priority is None
                or self.get_agent_free_slots(a.agent_id, priority) > 0
            )
        ]
        if not capable:
            log = self.logger.warning if warn_if_unavailable else self.logger.debug
            log(
                "No agent with free %s capacity for capability '%s' — connected agents: %s",
                priority or "any",
                capability,
                list(self.agents.keys()),
            )
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
    
    async def send_task(
        self,
        agent_id: str,
        command: str,
        params: dict,
        timeout: float = 30.0,
        priority: str = 'interactive',
        *,
        task_id: str | None = None,
        callback=None,
        sent_callback=None,
        create_waiters: bool = True,
        send_deadline: float | None = None,
        claim_send_outcome=None,
    ) -> str:
        """Send a task with optional sent and terminal event callbacks."""
        if send_deadline is not None and time.monotonic() >= send_deadline:
            raise TimeoutError(f"Agent task {task_id or '<new>'} send deadline expired")
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

        task_id = task_id or str(uuid.uuid4())
        task = PendingTask(
            task_id=task_id,
            command=command,
            params=params,
            callback=callback,
            timeout=timeout,
            priority=priority,
            agent_connection=agent,
        )
        with self._task_lock:
            if task_id in self.pending_tasks:
                raise ValueError(f"Agent task already exists: {task_id}")
            limit = int(agent.limits.get(priority, 1))
            used = int(agent.in_flight.get(priority, 0))
            if used >= limit:
                raise AgentCapacityError(
                    f"Agent {agent_id} has no free {priority} slots ({used}/{limit})"
                )
            agent.in_flight[priority] = used + 1
            self.pending_tasks[task_id] = task
            self._task_agent_ids[task_id] = agent_id
            if create_waiters:
                self._task_queues[task_id] = Queue()
                self._async_task_queues[task_id] = asyncio.Queue(maxsize=1)

        msg = json.dumps({
            'type': 'command',
            'request_id': task_id,
            'command': command,
            'params': params,
            'priority': priority,
        })

        try:
            await agent.websocket.send_text(msg)
        except asyncio.CancelledError:
            self.logger.warning("Cancelled pending send for task %s", task_id)
            self._cleanup_task(task_id)
            raise
        except BaseException as exc:
            self.logger.error(f"Failed to send task {task_id} to '{agent_id}': {exc}")
            if callback is not None:
                if claim_send_outcome is None or claim_send_outcome("failed"):
                    self._deliver_task_event({
                        'type': 'error',
                        'request_id': task_id,
                        'error': str(exc),
                        'terminal_reason': 'send_failed',
                    })
                else:
                    self._cleanup_task(task_id)
            else:
                self._cleanup_task(task_id)
                raise
        else:
            if claim_send_outcome is not None and not claim_send_outcome("sent"):
                self._cleanup_task(task_id)
                return task_id
            if sent_callback is not None:
                try:
                    sent_callback({
                        'type': 'sent',
                        'request_id': task_id,
                        'agent_id': agent_id,
                    })
                except Exception:
                    self.logger.exception(
                        "Sent callback failed for task %s",
                        task_id,
                    )
            if callback is not None:
                loop = asyncio.get_running_loop()
                timeout_handle = loop.call_later(
                    timeout,
                    self._timeout_callback_task,
                    task_id,
                )
                with self._task_lock:
                    registered = self.pending_tasks.get(task_id)
                    if registered is not None:
                        registered.timeout_handle = timeout_handle
                    else:
                        timeout_handle.cancel()
            self.logger.info(f"Sent task {task_id} ({command}) to agent '{agent_id}'")

        return task_id

    def send_task_fire_and_forget(
        self,
        agent_id: str,
        command: str,
        params: dict,
        *,
        task_id: str,
        callback,
        timeout: float = 10.0,
        priority: str = "bulk",
    ) -> str:
        """Schedule callback-driven work without blocking for an agent response."""
        loop = self._event_loop
        if loop is None or not loop.is_running():
            raise RuntimeError("Agent manager event loop is unavailable")
        callback_timeout = float(timeout)
        if callback_timeout <= 0:
            raise ValueError("Agent task timeout must be greater than zero")
        send_timeout = min(10.0, callback_timeout)
        send_deadline = time.monotonic() + send_timeout
        outcome_lock = Lock()
        send_outcome: str | None = None

        def _claim_send_outcome(outcome: str) -> bool:
            nonlocal send_outcome
            with outcome_lock:
                if send_outcome is not None:
                    return False
                send_outcome = outcome
                return True

        future = asyncio.run_coroutine_threadsafe(
            self.send_task(
                agent_id,
                command,
                params,
                timeout=callback_timeout,
                priority=priority,
                task_id=task_id,
                callback=callback,
                sent_callback=callback,
                create_waiters=False,
                send_deadline=send_deadline,
                claim_send_outcome=_claim_send_outcome,
            ),
            loop,
        )

        def _send_timed_out() -> None:
            if not _claim_send_outcome("timeout"):
                return
            future.cancel()
            callback({
                'type': 'error',
                'request_id': task_id,
                'error': f'Agent task send timeout after {send_timeout}s',
                'terminal_reason': 'send_failed',
            })

        send_timeout_handle = Timer(send_timeout, _send_timed_out)
        send_timeout_handle.daemon = True

        def _send_completed(send_future) -> None:
            send_timeout_handle.cancel()
            if send_future.cancelled():
                return
            try:
                send_future.result()
            except Exception as exc:
                if _claim_send_outcome("failed"):
                    callback({
                        'type': 'error',
                        'request_id': task_id,
                        'error': str(exc),
                        'terminal_reason': 'send_failed',
                    })

        future.add_done_callback(_send_completed)
        send_timeout_handle.start()
        return task_id

    def send_task_and_wait(
        self,
        agent_id: str,
        command: str,
        params: dict,
        *,
        timeout: float = 30.0,
        priority: str = "interactive",
    ) -> Optional[dict]:
        """Send on the API event loop and block a worker thread for the result."""
        loop = self._event_loop
        if loop is None or not loop.is_running():
            raise RuntimeError("Agent manager event loop is unavailable")
        future = asyncio.run_coroutine_threadsafe(
            self.send_task(
                agent_id,
                command,
                params,
                timeout=timeout,
                priority=priority,
            ),
            loop,
        )
        try:
            task_id = future.result(timeout=10)
        except Exception:
            future.cancel()
            raise
        return self.wait_for_task(task_id, timeout=timeout)

    def wait_for_task(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for task result (blocking - for sync code only)."""
        with self._task_lock:
            task_queue = self._task_queues.get(task_id)
            agent_id = self._task_agent_ids.get(task_id)
        if task_queue is None:
            return None

        try:
            result = task_queue.get(timeout=timeout)
            if agent_id:
                self._record_agent_success(agent_id)
            return result
        except Empty:
            task_desc = self._describe_task(task_id)
            if agent_id:
                self._record_agent_timeout(agent_id)
            self.logger.error(
                f"Timeout ({timeout}s) waiting (sync) for task {task_id} — "
                f"{task_desc}; agent is still running"
            )
            return None
        finally:
            self._cleanup_task(task_id)
    
    async def wait_for_task_async(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for task result (async - for async code)."""
        with self._task_lock:
            task_queue = self._async_task_queues.get(task_id)
            agent_id = self._task_agent_ids.get(task_id)
        if task_queue is None:
            return None

        try:
            result = await asyncio.wait_for(
                task_queue.get(),
                timeout=timeout
            )
            # Success — reset timeout counter for this agent
            if agent_id:
                self._record_agent_success(agent_id)
            return result
        except asyncio.TimeoutError:
            task_desc = self._describe_task(task_id)
            # Record timeout for quarantine tracking
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
