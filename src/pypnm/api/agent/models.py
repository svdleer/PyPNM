# PyPNM Agent Models
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field
from typing import Optional, Any, Callable
import time


@dataclass
class PendingTask:
    """Represents a task waiting for agent response."""
    task_id: str
    command: str
    params: dict
    callback: Optional[Callable] = None
    created_at: float = field(default_factory=time.time)
    timeout: float = 30.0
    result: Optional[dict] = None
    completed: bool = False
    error: Optional[str] = None


@dataclass
class ConnectedAgent:
    """Represents a connected remote agent."""
    agent_id: str
    websocket: Any  # FastAPI WebSocket connection
    capabilities: list[str]
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    authenticated: bool = False
    
    def is_alive(self, max_silence_s: float = 90.0) -> bool:
        """True if the agent sent a message within the last *max_silence_s* seconds."""
        return (time.time() - self.last_seen) < max_silence_s

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            'agent_id': self.agent_id,
            'capabilities': self.capabilities,
            'connected_at': self.connected_at,
            'last_seen': self.last_seen,
            'authenticated': self.authenticated,
            'is_alive': self.is_alive()
        }
