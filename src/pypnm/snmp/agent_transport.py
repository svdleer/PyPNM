# PyPNM Agent SNMP Transport
# SPDX-License-Identifier: Apache-2.0
#
# Routes SNMP operations through the agent WebSocket connection.
#
# The remote pyPNMAgent executes the actual pysnmp calls and returns
# results as ``{'success': True, 'output': 'OID = value\n...'}``.
# This transport parses that textual output back into pysnmp
# ``AgentVarBind`` objects so that the rest of PyPNM (CmSnmpOperation,
# Snmp_v2c helpers, etc.) works without any changes.

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from pysnmp.proto.rfc1902 import Integer32, OctetString
from pysnmp.smi.rfc1902 import ObjectIdentity, ObjectType

from pypnm.lib.inet import Inet
from pypnm.lib.types import SnmpReadCommunity, SnmpWriteCommunity
from pypnm.snmp.compiled_oids import COMPILED_OIDS


# ---------------------------------------------------------------------------
#  Lightweight varbind that mimics pysnmp ObjectType[0] / ObjectType[1]
# ---------------------------------------------------------------------------

class AgentVarBind:
    """
    Varbind wrapper that mimics pysnmp ObjectType behavior.

    Behaves like pysnmp ``ObjectType`` for indexing:
        varbind[0] -> OID (ObjectIdentity-like object with prettyPrint())
        varbind[1] -> typed value (``OctetString`` / ``Integer32``)

    This provides full compatibility with code expecting ObjectType without
    requiring MIB resolution on every operation.
    """

    __slots__ = ('_oid', '_value', '_oid_identity')

    def __init__(self, oid: str, value: OctetString | Integer32) -> None:
        self._oid = oid
        self._value = value
        # Create a minimal ObjectIdentity for [0] access
        self._oid_identity = _MinimalObjectIdentity(oid)

    def __getitem__(self, idx: int):
        if idx == 0:
            return self._oid_identity  # Return OID as ObjectIdentity-like
        if idx == 1:
            return self._value
        raise IndexError(idx)

    def __len__(self) -> int:
        return 2
    
    def __iter__(self):
        return iter([self._oid_identity, self._value])

    def __repr__(self) -> str:
        return f"AgentVarBind({self._oid!r}, {self._value!r})"


class _MinimalObjectIdentity:
    """
    Minimal ObjectIdentity-like class that provides OID string access.
    
    This allows AgentVarBind[0] to behave like a real ObjectIdentity
    with .prettyPrint() and str() methods.
    """
    
    __slots__ = ('_oid',)
    
    def __init__(self, oid: str):
        self._oid = oid
    
    def __str__(self) -> str:
        return self._oid
    
    def prettyPrint(self) -> str:
        return self._oid
    
    def __repr__(self) -> str:
        return f"OID({self._oid})"


# ---------------------------------------------------------------------------
#  OID resolution (mirrors Snmp_v2c.resolve_oid without importing the class)
# ---------------------------------------------------------------------------

_NUMERIC_OID_RE = re.compile(r"\.?(\d+\.)+\d+")
_SYMBOLIC_RE = re.compile(r"^([a-zA-Z0-9_:-]+)(\..+)?$")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")


def _resolve_oid(oid: str) -> str:
    """Resolve a symbolic OID name to its numeric form."""
    if _NUMERIC_OID_RE.fullmatch(oid):
        return oid
    m = _SYMBOLIC_RE.match(oid)
    if not m:
        return oid
    base_sym, suffix = m.groups()
    base_num = COMPILED_OIDS.get(base_sym, base_sym)
    return f"{base_num}{suffix or ''}"


# ---------------------------------------------------------------------------
#  Parsing the agent's textual output into AgentVarBind objects
# ---------------------------------------------------------------------------

def _parse_output_to_varbinds(output: str) -> list[AgentVarBind]:
    """
    Parse the agent's SNMP output into AgentVarBind objects.

    The agent can return different formats:
    1. pysnmp prettyPrint() format::
        SNMPv2-MIB::sysDescr.0 = <<GEAR3>>...
        IF-MIB::ifType.1 = 127
        IF-MIB::ifPhysAddress.1 = 0xac22053ad5c0
        
    2. snmpwalk format::
        iso.3.6.1.2.1.69.1.5.8.1.2.32 = Hex-STRING: 07 EA 02 05 05 1F 33 00
        iso.3.6.1.2.1.1.1.0 = STRING: "<<GEAR3>>"

    We normalize both to AgentVarBind objects.
    """
    varbinds: list[AgentVarBind] = []
    if not output:
        return varbinds

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # Split on first ' = '
        parts = line.split(' = ', 1)
        if len(parts) != 2:
            continue
        oid_str, val_str = parts

        # Normalize OID: handle both 'iso.' prefix and MIB module prefixes
        if oid_str.startswith('iso.'):
            # Convert iso.3.6.1... to 1.3.6.1...
            oid_str = '1' + oid_str[3:]
        elif '::' in oid_str:
            # Handle SNMPv2-MIB::sysDescr.0 -> sysDescr.0, then resolve
            oid_str = oid_str.split('::', 1)[1]
            oid_str = _resolve_oid(oid_str.strip())
        elif not _NUMERIC_OID_RE.match(oid_str):
            # Symbolic OID without MIB prefix, resolve it
            oid_str = _resolve_oid(oid_str.strip())
        # else: already numeric, use as-is

        # Parse value based on format
        val_str_stripped = val_str.strip()
        
        # Handle snmpwalk type prefixes: "Hex-STRING: ...", "STRING: ...", "INTEGER: ..."
        if ':' in val_str_stripped and any(prefix in val_str_stripped for prefix in ['Hex-STRING:', 'STRING:', 'INTEGER:', 'Gauge32:']):
            # snmpwalk format: "TYPE: value"
            type_part, value_part = val_str_stripped.split(':', 1)
            value_part = value_part.strip()
            
            if type_part.strip() == 'Hex-STRING':
                # "Hex-STRING: 07 EA 02 05 05 1F 33 00" -> bytes
                hex_bytes = value_part.replace(' ', '')
                raw = bytes.fromhex(hex_bytes)
                typed_val = OctetString(hexValue=raw.hex())
            elif type_part.strip() in ['INTEGER', 'Gauge32']:
                # "INTEGER: 127" -> Use appropriate type based on value
                from pysnmp.proto.rfc1902 import Unsigned32, Counter64
                int_val = int(value_part)
                # Use Unsigned32 for positive values that might exceed Integer32 range
                if int_val >= 0 and int_val <= 4294967295:
                    typed_val = Unsigned32(int_val)
                elif int_val > 4294967295:
                    typed_val = Counter64(int_val)
                else:
                    typed_val = Integer32(int_val)
            elif type_part.strip() == 'STRING':
                # "STRING: "text"" -> OctetString, strip quotes
                if value_part.startswith('"') and value_part.endswith('"'):
                    value_part = value_part[1:-1]
                typed_val = OctetString(value_part)
            else:
                # Fallback to text
                typed_val = OctetString(value_part)
        elif _HEX_RE.fullmatch(val_str_stripped):
            # pysnmp prettyPrint() hex format: "0xac22053ad5c0"
            raw = bytes.fromhex(val_str_stripped[2:])
            typed_val = OctetString(hexValue=raw.hex())
        else:
            # Try integer, fallback to string
            try:
                from pysnmp.proto.rfc1902 import Unsigned32, Counter64
                int_val = int(val_str_stripped)
                # Use Unsigned32 for positive values that might exceed Integer32 range
                if int_val >= 0 and int_val <= 4294967295:
                    typed_val = Unsigned32(int_val)
                elif int_val > 4294967295:
                    typed_val = Counter64(int_val)
                else:
                    typed_val = Integer32(int_val)
            except (ValueError, TypeError):
                typed_val = OctetString(val_str_stripped)

        varbinds.append(AgentVarBind(oid_str, typed_val))

    return varbinds


class AgentSnmpTransport:
    """
    SNMP transport that routes operations through a connected agent.

    Returns ``list[AgentVarBind]`` — indexable like pysnmp ObjectType
    (``varbind[0]`` = OID, ``varbind[1]`` = typed value) so that all
    downstream consumers (``CmSnmpOperation``, ``Snmp_v2c`` helpers, etc.)
    work transparently.
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_manager_and_agent(capability: str = 'snmp_get'):
        """Return (agent_manager, agent) or raise RuntimeError."""
        from pypnm.api.agent.manager import get_agent_manager

        mgr = get_agent_manager()
        if not mgr:
            raise RuntimeError("Agent manager not initialized")
        agent = mgr.get_agent_for_capability(capability)
        if not agent:
            raise RuntimeError(f"No agent available with '{capability}' capability")
        return mgr, agent

    async def _send_and_wait(self, capability: str, command: str,
                             params: dict, timeout: float) -> dict | None:
        """Send a command and async-wait for the response."""
        mgr, agent = self._get_manager_and_agent(capability)
        task_id = await mgr.send_task(
            agent.agent_id, command, params, timeout=timeout,
        )
        result = await mgr.wait_for_task_async(task_id, timeout=timeout)
        if not result:
            return None
        if result.get('type') == 'response':
            return result.get('result', {})
        if result.get('type') == 'error':
            err = result.get('error', 'unknown agent error')
            self.logger.error(f"Agent error for {command}: {err}")
        return None

    # ------------------------------------------------------------------
    # Public API — same signatures as Snmp_v2c
    # ------------------------------------------------------------------

    async def get(
        self,
        oid: str,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> list[AgentVarBind] | None:
        """
        Perform SNMP GET via agent.

        Returns:
            list[AgentVarBind] matching Snmp_v2c.get() contract, or None.
        """
        resolved = _resolve_oid(oid)
        t = timeout if timeout is not None else self._timeout
        
        start_time = time.time()
        print(f"DEBUG: AgentSnmpTransport.get() called with oid='{oid}' -> resolved='{resolved}'")

        data = await self._send_and_wait(
            'snmp_get', 'snmp_get',
            {
                'target_ip': self._host,
                'oid': resolved,
                'community': self._read_community,
            },
            timeout=t,
        )
        
        elapsed = time.time() - start_time
        print(f"DEBUG: Agent get response: success={data.get('success') if data else None}, elapsed={elapsed:.3f}s")
        
        if not data or not data.get('success'):
            self.logger.warning(f"Agent GET failed for {resolved}: {data}")
            return None

        output = data.get('output', '')
        print(f"DEBUG: Agent get output: {repr(output[:200])}")
        
        varbinds = _parse_output_to_varbinds(output)
        print(f"DEBUG: Parsed {len(varbinds) if varbinds else 0} varbinds, total time={time.time()-start_time:.3f}s")
        
        return varbinds if varbinds else None

    async def bulk_get(
        self,
        oids: list[str],
        timeout: float | None = None,
    ) -> dict[str, list[AgentVarBind]] | None:
        """
        Perform multiple SNMP GET operations in one batch via agent.
        
        Args:
            oids: List of OID strings to retrieve
            timeout: Optional timeout override
            
        Returns:
            dict mapping each OID to its result list, or None on failure
        """
        if not oids:
            return {}
            
        resolved_oids = [_resolve_oid(oid) for oid in oids]
        t = timeout if timeout is not None else self._timeout
        
        start_time = time.time()
        print(f"DEBUG: AgentSnmpTransport.bulk_get() called with {len(oids)} OIDs")

        data = await self._send_and_wait(
            'snmp_bulk_get', 'snmp_bulk_get',
            {
                'target_ip': self._host,
                'oids': resolved_oids,
                'community': self._read_community,
            },
            timeout=t,
        )
        
        elapsed = time.time() - start_time
        print(f"DEBUG: Agent bulk_get response: success={data.get('success') if data else None}, elapsed={elapsed:.3f}s")
        
        if not data or not data.get('success'):
            self.logger.warning(f"Agent BULK_GET failed: {data}")
            return None

        # Parse results for each OID
        results = {}
        raw_results = data.get('results', {})
        
        print(f"DEBUG: bulk_get raw_results keys: {list(raw_results.keys())[:3]}")
        print(f"DEBUG: bulk_get resolved_oids: {resolved_oids[:3]}")
        print(f"DEBUG: bulk_get original oids: {oids[:3]}")
        
        # Create mapping from resolved OID back to original OID
        oid_mapping = dict(zip(resolved_oids, oids))
        
        for resolved_oid, oid_data in raw_results.items():
            original_oid = oid_mapping.get(resolved_oid, resolved_oid)
            if oid_data.get('success'):
                output = oid_data.get('output', '')
                varbinds = _parse_output_to_varbinds(output)
                results[original_oid] = varbinds if varbinds else []
            else:
                results[original_oid] = []
        
        print(f"DEBUG: bulk_get results keys: {list(results.keys())[:3]}")
        print(f"DEBUG: Parsed {len(results)} OID results, total time={time.time()-start_time:.3f}s")
        return results

    async def walk(
        self,
        oid: str,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> list[AgentVarBind] | None:
        """
        Perform SNMP WALK via agent.

        Returns:
            list[AgentVarBind] matching Snmp_v2c.walk() contract, or None.
        """
        resolved = _resolve_oid(oid)
        t = timeout if timeout is not None else self._timeout
        
        start_time = time.time()
        print(f"DEBUG: AgentSnmpTransport.walk() called with oid='{oid}' -> resolved='{resolved}'")

        data = await self._send_and_wait(
            'snmp_walk', 'snmp_walk',
            {
                'target_ip': self._host,
                'oid': resolved,
                'community': self._read_community,
            },
            timeout=t,
        )
        
        elapsed = time.time() - start_time
        print(f"DEBUG: Agent walk response: success={data.get('success') if data else None}, elapsed={elapsed:.3f}s")
        
        if not data or not data.get('success'):
            print(f"DEBUG: Agent WALK failed for {resolved}: {data}")
            self.logger.warning(f"Agent WALK failed for {resolved}: {data}")
            return None

        output = data.get('output', '')
        print(f"DEBUG: Agent walk output length: {len(output)} chars")
        print(f"DEBUG: Agent walk output preview: {repr(output[:200])}")
        
        varbinds = _parse_output_to_varbinds(output)
        print(f"DEBUG: Parsed {len(varbinds)} varbinds, total time={time.time()-start_time:.3f}s")
        
        return varbinds if varbinds else None

    async def bulk_walk(
        self,
        oid: str,
        non_repeaters: int = 0,
        max_repetitions: int = 25,
        suppress_no_such_name: bool = True,
    ) -> list[AgentVarBind] | None:
        """
        SNMP BULK WALK via agent (uses the agent's snmp_bulk_walk command).

        Falls back to regular walk if bulk_walk capability is not available.
        """
        resolved = _resolve_oid(oid)

        from pypnm.api.agent.manager import get_agent_manager
        mgr = get_agent_manager()
        if not mgr:
            raise RuntimeError("Agent manager not initialized")

        # Try bulk_walk first, fall back to regular walk
        agent = mgr.get_agent_for_capability('snmp_bulk_walk')
        if agent:
            task_id = await mgr.send_task(
                agent.agent_id, 'snmp_bulk_walk',
                {
                    'target_ip': self._host,
                    'oid': resolved,
                    'community': self._read_community,
                    'max_repetitions': max_repetitions,
                },
                timeout=self._timeout,
            )
            result = await mgr.wait_for_task_async(task_id, timeout=self._timeout)
            if result and result.get('type') == 'response':
                data = result.get('result', {})
                if data.get('success'):
                    varbinds = _parse_output_to_varbinds(data.get('output', ''))
                    return varbinds if varbinds else None

        # Fallback to regular walk
        return await self.walk(oid)

    async def set(
        self,
        oid: str,
        value: Any,
        value_type: str = 's',
        timeout: float | None = None,
    ) -> dict:
        """
        Perform SNMP SET via agent.

        Returns:
            Result dictionary with 'success' key.
        """
        resolved = _resolve_oid(oid)
        t = timeout if timeout is not None else self._timeout

        data = await self._send_and_wait(
            'snmp_set', 'snmp_set',
            {
                'target_ip': self._host,
                'oid': resolved,
                'value': value,
                'type': value_type,
                'community': self._write_community,
            },
            timeout=t,
        )
        if not data:
            return {'success': False, 'error': 'Timeout waiting for agent response'}
        return data

    def close(self) -> None:
        """Close transport (no-op for agent transport)."""
        pass
