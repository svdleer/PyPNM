# PyPNM Agent SNMP Transport
# SPDX-License-Identifier: Apache-2.0
#
# Routes SNMP operations through the agent WebSocket connection

from __future__ import annotations

import logging
import asyncio
from typing import Any, Optional

from pypnm.lib.inet import Inet
from pypnm.lib.types import SnmpReadCommunity, SnmpWriteCommunity
from pypnm.api.agent.manager import get_agent_manager


class AgentSnmpTransport:
    """
    SNMP transport that routes operations through a connected agent.
    
    This transport replaces direct UDP SNMP with agent-based SNMP,
    allowing PyPNM to use remote agents for SNMP operations.
    """
    
    SNMP_PORT = 161
    
    def __init__(
        self,
        host: Inet,
        community: str | None = None,
        read_community: SnmpReadCommunity | None = None,
        write_community: SnmpWriteCommunity | None = None,
        port: int = SNMP_PORT,
        timeout: int = 10,
        retries: int = 3,
    ) -> None:
        """
        Initialize agent SNMP transport.
        
        Args:
            host: Target IP address
            community: SNMP community string (legacy)
            read_community: Read community override
            write_community: Write community override
            port: SNMP port (usually 161)
            timeout: Operation timeout in seconds
            retries: Number of retries
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self._host = host.inet if hasattr(host, 'inet') else str(host)
        self._port = port
        self._timeout = timeout
        self._retries = retries
        
        if read_community is not None:
            self._read_community = str(read_community)
        elif community is not None:
            self._read_community = str(community)
        else:
            self._read_community = 'public'
            
        if write_community is not None:
            self._write_community = str(write_community)
        elif community is not None:
            self._write_community = str(community)
        else:
            self._write_community = self._read_community
    
    async def get(self, oid: str, timeout: Optional[int] = None, retries: Optional[int] = None) -> list:
        """
        Perform SNMP GET via agent.
        
        Args:
            oid: OID to query
            timeout: Optional timeout override
            retries: Optional retries override
            
        Returns:
            List of (oid, value) tuples
        """
        agent_manager = get_agent_manager()
        if not agent_manager:
            raise RuntimeError("Agent manager not initialized")
        
        # Find agent with snmp_get capability
        agent = agent_manager.get_agent_for_capability('snmp_get')
        if not agent:
            raise RuntimeError("No agent available with snmp_get capability")
        
        # Send task to agent
        task_id = await agent_manager.send_task(
            agent.agent_id,
            'snmp_get',
            {
                'modem_ip': self._host,
                'oid': oid,
                'community': self._read_community,
            },
            timeout=timeout or self._timeout
        )
        
        # Wait for response
        result = agent_manager.wait_for_task(task_id, timeout=timeout or self._timeout)
        
        if not result:
            return []
        
        # Parse agent response
        if result.get('type') == 'response':
            response_data = result.get('result', {})
            if response_data.get('success'):
                results = response_data.get('results', [])
                return [(r['oid'], r['value']) for r in results]
        
        return []
    
    async def walk(self, oid: str, timeout: Optional[int] = None, retries: Optional[int] = None) -> list:
        """
        Perform SNMP WALK via agent.
        
        Args:
            oid: Starting OID for walk
            timeout: Optional timeout override
            retries: Optional retries override
            
        Returns:
            List of (oid, value) tuples
        """
        agent_manager = get_agent_manager()
        if not agent_manager:
            raise RuntimeError("Agent manager not initialized")
        
        agent = agent_manager.get_agent_for_capability('snmp_walk')
        if not agent:
            raise RuntimeError("No agent available with snmp_walk capability")
        
        task_id = await agent_manager.send_task(
            agent.agent_id,
            'snmp_walk',
            {
                'modem_ip': self._host,
                'oid': oid,
                'community': self._read_community,
            },
            timeout=timeout or self._timeout
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=timeout or self._timeout)
        
        if not result:
            return []
        
        if result.get('type') == 'response':
            response_data = result.get('result', {})
            if response_data.get('success'):
                results = response_data.get('results', [])
                return [(r['oid'], r['value']) for r in results]
        
        return []
    
    async def set(self, oid: str, value: Any, value_type: str = 's', timeout: Optional[int] = None) -> dict:
        """
        Perform SNMP SET via agent.
        
        Args:
            oid: OID to set
            value: Value to set
            value_type: SNMP type ('i'=integer, 's'=string, 'x'=hex, etc.)
            timeout: Optional timeout override
            
        Returns:
            Result dictionary
        """
        agent_manager = get_agent_manager()
        if not agent_manager:
            raise RuntimeError("Agent manager not initialized")
        
        agent = agent_manager.get_agent_for_capability('snmp_set')
        if not agent:
            raise RuntimeError("No agent available with snmp_set capability")
        
        task_id = await agent_manager.send_task(
            agent.agent_id,
            'snmp_set',
            {
                'modem_ip': self._host,
                'oid': oid,
                'value': value,
                'type': value_type,
                'community': self._write_community,
            },
            timeout=timeout or self._timeout
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=timeout or self._timeout)
        
        if not result:
            return {'success': False, 'error': 'Timeout waiting for agent response'}
        
        if result.get('type') == 'response':
            return result.get('result', {'success': False, 'error': 'Invalid response'})
        
        return {'success': False, 'error': 'Unknown error'}
    
    def close(self) -> None:
        """Close transport (no-op for agent transport)."""
        pass
