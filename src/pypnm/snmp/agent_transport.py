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


def _parse_results_to_varbinds(results: list[dict]) -> list[AgentVarBind]:
    """
    Convert agent structured results to AgentVarBind objects.

    The agent walk/get returns structured dicts::

        [{'oid': '1.3.6.1...', 'value': 33, 'type': 'Integer32'}, ...]

    This converts them to AgentVarBind objects compatible with pysnmp.
    """
    varbinds: list[AgentVarBind] = []
    if not results:
        return varbinds

    for item in results:
        oid_str = item.get('oid', '')
        value = item.get('value')
        value_type = item.get('type', '')

        if not oid_str:
            continue

        # Convert value to pysnmp type based on agent's type hint
        if value_type in ('Integer32', 'Integer', 'int'):
            typed_val = Integer32(int(value))
        elif value_type in ('Unsigned32', 'Gauge32', 'Counter32'):
            from pysnmp.proto.rfc1902 import Unsigned32
            typed_val = Unsigned32(int(value))
        elif value_type in ('Counter64',):
            from pysnmp.proto.rfc1902 import Counter64
            typed_val = Counter64(int(value))
        elif value_type in ('OctetString',) and isinstance(value, str) and value.startswith('0x'):
            raw = bytes.fromhex(value[2:])
            typed_val = OctetString(hexValue=raw.hex())
        elif value_type in ('IpAddress',):
            from pysnmp.proto.rfc1902 import IpAddress
            typed_val = IpAddress(str(value))
        elif isinstance(value, int):
            typed_val = Integer32(value)
        elif isinstance(value, str):
            typed_val = OctetString(value)
        else:
            typed_val = OctetString(str(value) if value is not None else '')

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
        agent_id: str | None = None,
        priority: str = 'interactive',
        target_role: str = 'cm',
    ) -> None:
        if target_role not in {'cm', 'cmts'}:
            raise ValueError("target_role must be 'cm' or 'cmts'")

        self.logger = logging.getLogger(self.__class__.__name__)
        self._host = host.inet if hasattr(host, 'inet') else str(host)
        self._port = port
        self._timeout = timeout
        self._retries = retries
        self._agent_id = agent_id  # pin to a specific agent when set
        self._priority = priority  # 'interactive' (GUI) or 'bulk' (background jobs)
        self._target_role = target_role

        read_value = read_community if read_community is not None else community
        self._read_community = str(read_value) if read_value else None

        if write_community is not None:
            self._write_community = str(write_community) if write_community else None
        elif community is not None:
            self._write_community = str(community) if community else None
        else:
            self._write_community = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_manager_and_agent(target_role: str, agent_id: str | None = None):
        """Return the manager and an agent reachable for the requested role."""
        from pypnm.api.agent.manager import get_agent_manager

        mgr = get_agent_manager()
        if not mgr:
            raise RuntimeError("Agent manager not initialized")
        capability = f'{target_role}_reachable'
        # A pinned agent must remain pinned for every operation, including bulk walks.
        if agent_id:
            agent = mgr.get_agent(agent_id)
            if not agent:
                raise RuntimeError(f"Pinned agent '{agent_id}' is not connected")
            if not agent.authenticated or not agent.is_alive():
                raise RuntimeError(
                    f"Pinned agent '{agent_id}' is not authenticated and alive"
                )
            if capability not in agent.capabilities:
                raise RuntimeError(
                    f"Pinned agent '{agent_id}' lacks '{capability}' capability"
                )
            return mgr, agent
        agent = mgr.get_agent_for_capability(capability)
        if not agent:
            raise RuntimeError(f"No agent available with '{capability}' capability")
        return mgr, agent

    @staticmethod
    def _task_timeout_budget(timeout: float, retries: int, *, operations: int = 1,
                             sleep_seconds: float = 0.0) -> float:
        """Return an outer task deadline that covers the agent's SNMP retry budget."""
        per_operation = max(float(timeout), 0.1) * (max(int(retries), 0) + 1)
        return max(5.0, (per_operation * max(int(operations), 1)) + sleep_seconds + 5.0)

    async def _send_and_wait(self, capability: str, command: str,
                             params: dict, timeout: float) -> dict | None:
        """Send a role-routed command and async-wait for the response."""
        mgr, agent = self._get_manager_and_agent(self._target_role, self._agent_id)
        task_params = dict(params)
        task_params['target_role'] = self._target_role
        if not task_params.get('community'):
            task_params.pop('community', None)
        task_id = await mgr.send_task(
            agent.agent_id, command, task_params, timeout=timeout,
            priority=self._priority,
        )
        # send_task may have bumped the timeout (e.g. LONG_COMMANDS → 90s).
        # Always wait as long as the task itself is configured for.
        actual_timeout = mgr.pending_tasks.get(task_id)
        if actual_timeout is not None:
            timeout = actual_timeout.timeout
        result = await mgr.wait_for_task_async(task_id, timeout=timeout)
        if not result:
            raise TimeoutError(f"Agent task timed out after {timeout:g}s")
        if result.get('type') == 'response':
            return result.get('result', {})
        error = str(result.get('error') or 'unknown agent error')
        if 'timeout' in error.lower() or 'timed out' in error.lower():
            raise TimeoutError(error)
        if result.get('type') == 'error':
            self.logger.error(f"Agent error for {command}: {error}")
            raise RuntimeError(f"Agent task failed: {error}")
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
        r = retries if retries is not None else self._retries
        task_timeout = self._task_timeout_budget(t, r)
        
        start_time = time.time()
        print(f"DEBUG: AgentSnmpTransport.get() called with oid='{oid}' -> resolved='{resolved}'")

        data = await self._send_and_wait(
            'snmp_get', 'snmp_get',
            {
                'target_ip': self._host,
                'oid': resolved,
                'community': self._read_community,
                'timeout': t,
                'retries': r,
            },
            timeout=task_timeout,
        )
        
        elapsed = time.time() - start_time
        print(f"DEBUG: Agent get response: success={data.get('success') if data else None}, elapsed={elapsed:.3f}s")
        
        if not data or not data.get('success'):
            self.logger.warning(f"Agent GET failed for {resolved}: {data}")
            return None

        # Handle both response formats from agent
        results = data.get('results')
        if results and isinstance(results, list):
            varbinds = _parse_results_to_varbinds(results)
        else:
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
        
        # For bulk operations, use longer timeout: ~0.1s per OID with overhead
        # 336 OIDs (24 channels × 14 fields) needs ~40s
        default_bulk_timeout = max(30.0, len(oids) * 0.15)
        t = timeout if timeout is not None else default_bulk_timeout
        
        start_time = time.time()
        print(f"DEBUG: AgentSnmpTransport.bulk_get() called with {len(oids)} OIDs, timeout={t:.1f}s")

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
        r = retries if retries is not None else self._retries
        task_timeout = self._task_timeout_budget(t, r)
        
        start_time = time.time()
        print(f"DEBUG: AgentSnmpTransport.walk() called with oid='{oid}' -> resolved='{resolved}'")

        data = await self._send_and_wait(
            'snmp_walk', 'snmp_walk',
            {
                'target_ip': self._host,
                'oid': resolved,
                'community': self._read_community,
                'timeout': t,
                'retries': r,
            },
            timeout=task_timeout,
        )
        
        elapsed = time.time() - start_time
        print(f"DEBUG: Agent walk response: success={data.get('success') if data else None}, elapsed={elapsed:.3f}s")
        
        if not data or not data.get('success'):
            print(f"DEBUG: Agent WALK failed for {resolved}: {data}")
            self.logger.warning(f"Agent WALK failed for {resolved}: {data}")
            return None

        # Handle both response formats from agent:
        # 1. 'results' list of dicts (structured) - from pysnmp-based agent
        # 2. 'output' text string (legacy) - from CLI-based agent
        results = data.get('results')
        if results and isinstance(results, list):
            varbinds = _parse_results_to_varbinds(results)
            print(f"DEBUG: Parsed {len(varbinds)} varbinds from results, total time={time.time()-start_time:.3f}s")
        else:
            output = data.get('output', '')
            print(f"DEBUG: Agent walk output length: {len(output)} chars")
            varbinds = _parse_output_to_varbinds(output)
            print(f"DEBUG: Parsed {len(varbinds)} varbinds from output, total time={time.time()-start_time:.3f}s")
        
        return varbinds if varbinds else None

    async def bulk_walk(
        self,
        oid: str,
        non_repeaters: int = 0,
        max_repetitions: int = 25,
        suppress_no_such_name: bool = True,
    ) -> list[AgentVarBind] | None:
        """SNMP BULK WALK via the same role-selected or pinned agent."""
        resolved = _resolve_oid(oid)
        try:
            data = await self._send_and_wait(
                'snmp_bulk_walk',
                'snmp_bulk_walk',
                {
                    'target_ip': self._host,
                    'oid': resolved,
                    'community': self._read_community,
                    'max_repetitions': max_repetitions,
                },
                timeout=self._timeout,
            )
        except RuntimeError as exc:
            self.logger.debug("Agent bulk walk unavailable, using regular walk: %s", exc)
            data = None

        if data and data.get('success'):
            results = data.get('results')
            if results and isinstance(results, list):
                varbinds = _parse_results_to_varbinds(results)
            else:
                varbinds = _parse_output_to_varbinds(data.get('output', ''))
            return varbinds if varbinds else None

        # The fallback remains on the same pinned agent or target role.
        return await self.walk(oid)

    async def set(
        self,
        oid: str,
        value: Any,
        value_type: Any = 's',
        timeout: float | None = None,
    ) -> dict:
        """
        Perform SNMP SET via agent.

        Accepts value_type as either:
        - A string code: 'i', 's', 'u', 'a', etc.
        - A pysnmp type class: Integer32, OctetString, etc.
        
        Returns:
            Result dictionary with 'success' key.
        """
        resolved = _resolve_oid(oid)
        t = timeout if timeout is not None else self._timeout
        r = self._retries
        task_timeout = self._task_timeout_budget(t, r)

        # Convert pysnmp type classes to agent string codes
        type_str = value_type
        if isinstance(value_type, type):
            type_map = {
                Integer32: 'i',
                OctetString: 's',
            }
            # Also check by name for types we don't import directly
            type_name = value_type.__name__
            name_map = {
                'Integer32': 'i',
                'OctetString': 's',
                'Unsigned32': 'u',
                'Counter32': 'c',
                'Counter64': 'C',
                'Gauge32': 'g',
                'TimeTicks': 't',
                'IpAddress': 'a',
            }
            type_str = type_map.get(value_type, name_map.get(type_name, 's'))

        # Convert OctetString/bytes values to hex string for agent
        if isinstance(value, bytes):
            value = value.hex()
            type_str = 'x'  # Use hex type so agent's _to_snmp_value handles it correctly
        elif isinstance(value, OctetString):
            raw = value.asOctets()
            if any(b > 127 or b < 32 for b in raw):
                # Non-printable bytes → send as hex
                value = raw.hex()
                type_str = 'x'
            else:
                value = str(value)

        data = await self._send_and_wait(
            'snmp_set', 'snmp_set',
            {
                'target_ip': self._host,
                'oid': resolved,
                'value': value,
                'type': type_str,
                'community': self._write_community,
                'timeout': t,
                'retries': r,
            },
            timeout=task_timeout,
        )
        if not data:
            return None
        if not data.get('success'):
            self.logger.warning(f"Agent SET failed for {resolved}: {data}")
            return None

        # Parse response to match Snmp_v2c.set() return format: list[AgentVarBind]
        # so Snmp_v2c.snmp_set_result_value() can iterate over it
        results = data.get('results')
        if results and isinstance(results, list):
            return _parse_results_to_varbinds(results)
        
        output = data.get('output', '')
        if output:
            return _parse_output_to_varbinds(output)
        
        # If no parseable output, return a synthetic varbind with the set value
        return [AgentVarBind(resolved, OctetString(str(value)))]

    async def set_sequence(
        self,
        items: list[dict],
        timeout: float | None = None,
    ) -> dict | None:
        """Execute a sequence of SNMP SETs as a single agent task.

        Each item is ``{'oid': str, 'value': Any, 'type': str, 'sleep_after': float}``.
        ``sleep_after`` is optional seconds to pause between SETs (e.g. toggle delay).

        Returns the agent result dict, or None on timeout/error.
        """
        t = timeout if timeout is not None else self._timeout
        r = self._retries

        # Convert pysnmp type classes to string codes and normalise values
        type_map = {
            'Integer32': 'i', 'OctetString': 's', 'Unsigned32': 'u',
            'Counter32': 'c', 'Counter64': 'C', 'Gauge32': 'g',
            'TimeTicks': 't', 'IpAddress': 'a',
        }
        normalised = []
        for item in items:
            vtype = item.get('type', 'i')
            if isinstance(vtype, type):
                vtype = type_map.get(vtype.__name__, 's')
            val = item['value']
            if isinstance(val, bytes):
                val = val.hex()
                vtype = 'x'
            elif hasattr(val, 'asOctets'):
                raw = val.asOctets()
                if any(b > 127 or b < 32 for b in raw):
                    val = raw.hex()
                    vtype = 'x'
                else:
                    val = str(val)
            else:
                val = str(val)
            normalised.append({
                'oid': _resolve_oid(item['oid']),
                'value': val,
                'type': vtype,
                'sleep_after': item.get('sleep_after', 0),
            })

        sleep_seconds = sum(max(float(item.get('sleep_after', 0) or 0), 0.0) for item in normalised)
        task_timeout = self._task_timeout_budget(
            t, r, operations=len(normalised), sleep_seconds=sleep_seconds,
        )
        data = await self._send_and_wait(
            'snmp_set_sequence', 'snmp_set_sequence',
            {
                'target_ip': self._host,
                'community': self._write_community,
                'sets': normalised,
                'timeout': t,
                'retries': r,
            },
            timeout=task_timeout,
        )
        return data

    def close(self) -> None:
        """Close transport (no-op for agent transport)."""
        pass
