# PyPNM Agent SNMP Transport
# SPDX-License-Identifier: Apache-2.0
#
# Routes SNMP operations through the agent WebSocket connection.
#
# The remote pyPNMAgent executes the actual pysnmp calls and returns
# results as ``{'success': True, 'output': 'OID = value\n...'}``.
# This transport parses that textual output back into pysnmp
# ``ObjectType`` varbinds so that the rest of PyPNM (CmSnmpOperation,
# Snmp_v2c helpers, etc.) works without any changes.

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pysnmp.hlapi.v3arch.asyncio import ObjectIdentity, ObjectType
from pysnmp.proto.rfc1902 import Integer32, OctetString

from pypnm.lib.inet import Inet
from pypnm.lib.types import SnmpReadCommunity, SnmpWriteCommunity
from pypnm.snmp.compiled_oids import COMPILED_OIDS


# ---------------------------------------------------------------------------
#  OID resolution (mirrors Snmp_v2c.resolve_oid without importing the class)
# ---------------------------------------------------------------------------

_NUMERIC_OID_RE = re.compile(r"\.?(\d+\.)+\d+")
_SYMBOLIC_RE = re.compile(r"^([a-zA-Z0-9_:]+)(\..+)?$")


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
#  Parsing the agent's textual output into ObjectType varbinds
# ---------------------------------------------------------------------------

def _parse_output_to_varbinds(output: str) -> list[ObjectType]:
    """
    Parse the agent's ``'OID = value'`` text lines into pysnmp ObjectType
    varbinds that CmSnmpOperation / Snmp_v2c helpers understand.

    The agent formats each varbind as::

        SNMPv2-MIB::sysDescr.0 = <<GEAR3>>...
        1.3.6.1.2.1.2.2.1.3.1 = 127

    We split on the first `` = `` and wrap both sides in ObjectType.
    Numeric values are emitted as ``Integer32``; everything else as
    ``OctetString``.
    """
    varbinds: list[ObjectType] = []
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

        # Build a simple ObjectType from raw strings.
        # ObjectIdentity with a numeric OID is the safest approach (no MIB
        # compilation required).  We strip any MIB module prefix the agent
        # may have added (e.g. ``SNMPv2-MIB::sysDescr.0``).
        if '::' in oid_str:
            oid_str = oid_str.split('::', 1)[1]  # take the part after ::
        oid_str = _resolve_oid(oid_str.strip())

        # Determine value type
        try:
            int_val = int(val_str)
            typed_val = Integer32(int_val)
        except (ValueError, TypeError):
            typed_val = OctetString(val_str)

        varbinds.append(ObjectType(ObjectIdentity(oid_str), typed_val))

    return varbinds


class AgentSnmpTransport:
    """
    SNMP transport that routes operations through a connected agent.

    Returns ``list[ObjectType]`` — the same contract as ``Snmp_v2c`` — so
    that all downstream consumers (``CmSnmpOperation``, static helpers on
    ``Snmp_v2c``, etc.) work transparently.
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
    ) -> list[ObjectType] | None:
        """
        Perform SNMP GET via agent.

        Returns:
            list[ObjectType] matching Snmp_v2c.get() contract, or None.
        """
        resolved = _resolve_oid(oid)
        t = timeout if timeout is not None else self._timeout

        data = await self._send_and_wait(
            'snmp_get', 'snmp_get',
            {
                'target_ip': self._host,
                'oid': resolved,
                'community': self._read_community,
            },
            timeout=t,
        )
        if not data or not data.get('success'):
            self.logger.warning(f"Agent GET failed for {resolved}: {data}")
            return None

        varbinds = _parse_output_to_varbinds(data.get('output', ''))
        return varbinds if varbinds else None

    async def walk(
        self,
        oid: str,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> list[ObjectType] | None:
        """
        Perform SNMP WALK via agent.

        Returns:
            list[ObjectType] matching Snmp_v2c.walk() contract, or None.
        """
        resolved = _resolve_oid(oid)
        t = timeout if timeout is not None else self._timeout

        data = await self._send_and_wait(
            'snmp_walk', 'snmp_walk',
            {
                'target_ip': self._host,
                'oid': resolved,
                'community': self._read_community,
            },
            timeout=t,
        )
        if not data or not data.get('success'):
            self.logger.warning(f"Agent WALK failed for {resolved}: {data}")
            return None

        varbinds = _parse_output_to_varbinds(data.get('output', ''))
        return varbinds if varbinds else None

    async def bulk_walk(
        self,
        oid: str,
        non_repeaters: int = 0,
        max_repetitions: int = 25,
        suppress_no_such_name: bool = True,
    ) -> list[ObjectType] | None:
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
