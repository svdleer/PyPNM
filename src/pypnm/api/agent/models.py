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
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            'agent_id': self.agent_id,
            'capabilities': self.capabilities,
            'connected_at': self.connected_at,
            'last_seen': self.last_seen,
            'authenticated': self.authenticated,
            'is_alive': (time.time() - self.last_seen) < 90
        }
