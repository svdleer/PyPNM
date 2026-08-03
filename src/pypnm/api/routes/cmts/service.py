# SPDX-License-Identifier: Apache-2.0
# CMTS Modem Discovery Service

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Any

from pypnm.api.agent.manager import get_agent_manager


# ── In-memory enrichment cache ──────────────────────────────────────────────
# Keyed by cmts_ip → {modems, enriched, capability_enriched, enriching,
#                       timestamp, cancelled}
_enrichment_cache: Dict[str, Dict[str, Any]] = {}
_enrichment_lock = asyncio.Lock()
_live_walk_locks: Dict[str, asyncio.Lock] = {}
_LIVE_CACHE_TTL_SECONDS = 7200
_LIVE_REFRESH_COOLDOWN_SECONDS = 300


async def _get_live_walk_lock(cmts_ip: str) -> asyncio.Lock:
    """Return the process-local single-flight lock for one CMTS."""
    async with _enrichment_lock:
        lock = _live_walk_locks.get(cmts_ip)
        if lock is None:
            lock = asyncio.Lock()
            _live_walk_locks[cmts_ip] = lock
        return lock


def _int_env(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    if maximum is not None:
        value = min(value, maximum)
    return max(minimum, value)


def cancel_enrichment(cmts_ip: str) -> bool:
    """Signal a running background enrichment to stop. Returns True if one was running."""
    entry = _enrichment_cache.get(cmts_ip)
    if entry and entry.get('enriching'):
        entry['cancelled'] = True
        entry['enriching'] = False
        entry['enriched'] = True   # stop polling loop on GUI side
        return True
    return False

# ── CMTS SNMP OIDs ──────────────────────────────────────────────────────────
# DOCSIS 3.1 registration table
OID_D3_MAC       = '1.3.6.1.4.1.4491.2.1.20.1.3.1.2'   # docsIf3CmtsCmRegStatusMacAddr
# DOCS-SUBMGT3 CPE address table, indexed by docsIf3 registration ID + CPE ID.
OID_CPE_ADDR_TYPE = '1.3.6.1.4.1.4491.2.1.10.1.3.1.2'
OID_CPE_ADDR      = '1.3.6.1.4.1.4491.2.1.10.1.3.1.3'
OID_CPE_PREFIX    = '1.3.6.1.4.1.4491.2.1.10.1.3.1.4'
# Old (DOCSIS 3.0) CM status table
OID_OLD_MAC      = '1.3.6.1.2.1.10.127.1.3.3.1.2'       # docsIfCmtsCmStatusMacAddress
OID_OLD_IP       = '1.3.6.1.2.1.10.127.1.3.3.1.3'       # docsIfCmtsCmStatusIpAddress
OID_OLD_STATUS   = '1.3.6.1.2.1.10.127.1.3.3.1.9'       # docsIfCmtsCmStatusValue
OID_OLD_US_CH_IF = '1.3.6.1.2.1.10.127.1.3.3.1.5'       # docsIfCmtsCmStatusUpChannelIfIndex
OID_SW_REV       = '1.3.6.1.2.1.10.127.1.2.2.1.3'       # docsIfCmtsCmStatusSoftwareRev (firmware)
# DOCSIS 3.1 supplementary
OID_US_CH_ID     = '1.3.6.1.4.1.4491.2.1.20.1.4.1.3'    # docsIf3CmtsCmUsStatusChIfIndex
OID_IF_NAME      = '1.3.6.1.2.1.31.1.1.1.1'              # IF-MIB::ifName
OID_DS_PROFILE_LIST = '1.3.6.1.4.1.4491.2.1.28.1.3.1.2'  # docsIf31CmtsCmRegStatusDsProfileIdList
OID_US_PROFILE_LIST = '1.3.6.1.4.1.4491.2.1.28.1.3.1.3'  # docsIf31CmtsCmRegStatusUsProfileIucList
OID_PARTIAL_SVC  = '1.3.6.1.4.1.4491.2.1.28.1.3.1.9'    # docsIf31CmtsCmRegStatusPartialSvcState

# Status code mapping (docsIfCmtsCmStatusValue)
# 6 = registrationComplete → mapped to 'operational' since modem is fully online
STATUS_MAP = {
    1: 'other', 2: 'ranging', 3: 'rangingAborted', 4: 'rangingComplete',
    5: 'ipComplete', 6: 'operational', 7: 'accessDenied',
    8: 'operational', 9: 'registeredBPIInitializing',
}


class CMTSModemService:
    """
    Service for discovering and enriching cable modems from a CMTS.

    All business logic lives here.  The agent is used only as a dumb SNMP
    proxy via ``snmp_parallel_walk``, ``snmp_walk`` and ``snmp_get``.
    """
    
    def __init__(self, cmts_ip: str = None, community: str = "public"):
        self.logger = logging.getLogger(__name__)
        self.cmts_ip = cmts_ip
        self.community = community
    
    async def _send_agent_command(self, command: str, params: dict, timeout: float = 60) -> dict:
        """Send command to CMTS-reachable agent."""
        agent_manager = get_agent_manager()
        if not agent_manager:
            raise Exception("Agent manager not available")

        agent_id = agent_manager.get_agent_id_for_capability('cmts_reachable')
        if not agent_id:
            raise Exception("No cmts_reachable agent available")

        task_id = await agent_manager.send_task(
            agent_id=agent_id,
            command=command,
            params=params,
            timeout=timeout
        )

        result = await agent_manager.wait_for_task_async(task_id, timeout=timeout)
        if result and 'result' in result:
            return result['result']
        # Propagate timeout/error from manager
        if result and not result.get('success'):
            return result
        return {'success': False, 'error': 'No result from agent'}

    async def _send_cm_agent_command(self, command: str, params: dict, timeout: float = 30, priority: str = 'bulk') -> dict:
        """Send command to CM-reachable agent (for direct modem SNMP)."""
        agent_manager = get_agent_manager()
        if not agent_manager:
            raise Exception("Agent manager not available")

        agent_id = agent_manager.get_agent_id_for_capability('cm_reachable')
        if not agent_id:
            raise Exception("No cm_reachable agent available")

        task_id = await agent_manager.send_task(
            agent_id=agent_id,
            command=command,
            params=params,
            timeout=timeout,
            priority=priority,
        )

        result = await agent_manager.wait_for_task_async(task_id, timeout=timeout)
        if result and 'result' in result:
            return result['result']
        # Propagate timeout/error from manager
        if result and not result.get('success'):
            return result
        return {'success': False, 'error': 'No result from agent'}

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_index(full_oid: str, base_oid: str) -> str:
        """Return the complete OID suffix for a proper child of *base_oid*."""
        full = str(full_oid or '').strip().lstrip('.')
        base = str(base_oid or '').strip().lstrip('.').rstrip('.')
        prefix = f'{base}.'
        if base and full.startswith(prefix):
            return full[len(prefix):]
        return ''

    @staticmethod
    def _parse_mac(raw: Any) -> str | None:
        """Normalise a six-octet SNMP value into canonical MAC notation."""
        payload: bytes | None = None
        if isinstance(raw, (bytes, bytearray, memoryview)):
            candidate = bytes(raw)
            if len(candidate) == 6:
                payload = candidate
        elif isinstance(raw, str):
            # pysnmp OctetString values can arrive as six Latin-1 characters,
            # including non-printable characters, rather than rendered hex.
            if len(raw) == 6:
                try:
                    payload = raw.encode('latin-1')
                except UnicodeEncodeError:
                    return None
            else:
                text = raw.strip()
                lowered = text.lower()
                if lowered.startswith('hex-string:'):
                    text = text.split(':', 1)[1].strip()
                elif lowered.startswith('0x'):
                    text = text[2:]

                sep = ':' if ':' in text else ('-' if '-' in text else None)
                if sep:
                    parts = text.split(sep)
                    if len(parts) == 6 and all(
                        1 <= len(part) <= 2
                        and all(ch in '0123456789abcdefABCDEF' for ch in part)
                        for part in parts
                    ):
                        text = ''.join(part.zfill(2) for part in parts)

                mac_hex = ''.join(
                    ch for ch in text if ch not in ' \t\r\n:-'
                )
                if len(mac_hex) == 12 and all(
                    ch in '0123456789abcdefABCDEF' for ch in mac_hex
                ):
                    try:
                        payload = bytes.fromhex(mac_hex)
                    except ValueError:
                        return None

        if payload is None or len(payload) != 6:
            return None
        return ':'.join(f'{octet:02x}' for octet in payload)

    @staticmethod
    def _enum_code(value: Any) -> int | None:
        text = str(value or '').strip()
        if '(' in text and text.endswith(')'):
            text = text.rsplit('(', 1)[-1][:-1].strip()
        try:
            return int(text)
        except (TypeError, ValueError):
            return {'ipv4': 1, 'ipv6': 2}.get(str(value or '').strip().lower())

    @staticmethod
    def _decode_inet_address(value: Any, address_type: int) -> str | None:
        expected_length = 4 if address_type == 1 else 16 if address_type == 2 else 0
        if not expected_length:
            return None
        if isinstance(value, (bytes, bytearray, memoryview)):
            payload = bytes(value)
        else:
            text = str(value or '').strip()
            if not text:
                return None
            try:
                parsed = ipaddress.ip_address(text)
                return parsed.compressed if parsed.version == address_type else None
            except ValueError:
                pass
            lowered = text.lower()
            if lowered.startswith('hex-string:'):
                text = text.split(':', 1)[1]
            elif lowered.startswith('0x'):
                text = text[2:]
            hex_text = ''.join(ch for ch in text if ch not in ' \t\r\n:-')
            if len(hex_text) == expected_length * 2 and all(
                ch in '0123456789abcdefABCDEF' for ch in hex_text
            ):
                try:
                    payload = bytes.fromhex(hex_text)
                except ValueError:
                    return None
            else:
                try:
                    payload = value.encode('latin-1') if isinstance(value, str) else b''
                except UnicodeEncodeError:
                    return None
        if len(payload) != expected_length:
            return None
        try:
            return ipaddress.ip_address(payload).compressed
        except ValueError:
            return None

    def _correlate_cpe_data(
        self,
        raw: dict,
        modems: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], int]:
        """Join valid CPE rows to CMs and count skipped individual entries."""
        modem_by_index = {
            str(modem.get('docsif3_index')): str(modem.get('mac_address'))
            for modem in modems
            if modem.get('docsif3_index') is not None and modem.get('mac_address')
        }

        def indexed_rows(
            oid: str,
            value_getter,
        ) -> tuple[Dict[str, Any], set[str], int]:
            mapped: Dict[str, Any] = {}
            duplicate_indexes: set[str] = set()
            invalid_rows = 0
            for item in raw.get(oid, []) or []:
                if not isinstance(item, dict):
                    invalid_rows += 1
                    continue
                row_index = self._extract_index(item.get('oid', ''), oid)
                if not row_index:
                    invalid_rows += 1
                    continue
                if row_index in mapped or row_index in duplicate_indexes:
                    mapped.pop(row_index, None)
                    duplicate_indexes.add(row_index)
                    continue
                mapped[row_index] = value_getter(item)
            return mapped, duplicate_indexes, invalid_rows

        type_by_index, type_duplicates, invalid_type_rows = indexed_rows(
            OID_CPE_ADDR_TYPE,
            lambda item: self._enum_code(item.get('value')),
        )
        prefix_by_index, prefix_duplicates, invalid_prefix_rows = indexed_rows(
            OID_CPE_PREFIX,
            lambda item: self._enum_code(item.get('value')),
        )
        address_rows, address_duplicates, invalid_address_rows = indexed_rows(
            OID_CPE_ADDR,
            lambda item: item,
        )
        duplicate_indexes = type_duplicates | prefix_duplicates | address_duplicates
        all_indexes = list(dict.fromkeys([
            *address_rows,
            *type_by_index,
            *prefix_by_index,
            *duplicate_indexes,
        ]))
        skipped_count = invalid_type_rows + invalid_prefix_rows + invalid_address_rows
        entries: List[Dict[str, Any]] = []
        for row_index in all_indexes:
            if (
                row_index in duplicate_indexes
                or row_index not in address_rows
                or row_index not in type_by_index
                or row_index not in prefix_by_index
            ):
                skipped_count += 1
                continue

            item = address_rows[row_index]
            parts = row_index.split('.')
            if len(parts) < 2:
                skipped_count += 1
                continue
            docsif3_index = '.'.join(parts[:-1])
            modem_mac = modem_by_index.get(docsif3_index)
            address_type = type_by_index[row_index]
            address = self._decode_inet_address(item.get('value'), address_type or 0)
            maximum = 32 if address_type == 1 else 128 if address_type == 2 else -1
            prefix_length = prefix_by_index[row_index]
            if (
                not modem_mac
                or not address
                or maximum < 0
                or prefix_length is None
                or not 0 <= prefix_length <= maximum
            ):
                skipped_count += 1
                continue
            entries.append({
                'docsif3_index': docsif3_index,
                'cpe_id': parts[-1],
                'modem_mac': modem_mac,
                'address_family': 'ipv4' if address_type == 1 else 'ipv6',
                'ip_address': address,
                'prefix_length': prefix_length,
            })
        return entries, skipped_count

    @staticmethod
    def _decode_partial_service(value: Any) -> tuple[bool, bool, str]:
        """Decode DOCS-IF31-MIB PartialServiceType without losing direction."""
        states = {
            1: (False, False, 'other'),
            2: (False, False, 'none'),
            3: (True, False, 'downstream'),
            4: (False, True, 'upstream'),
            5: (True, True, 'both'),
        }
        symbols = {
            'other': 1,
            'none': 2,
            'partialsvcdsonlyimpaired': 3,
            'partialsvcusonlyimpaired': 4,
            'partialsvcdsandusimpaired': 5,
        }

        if isinstance(value, bool):
            code = int(value)
        elif isinstance(value, int):
            code = value
        else:
            text = str(value or '').strip()
            if '(' in text and text.endswith(')'):
                text = text.rsplit('(', 1)[-1][:-1].strip()
            try:
                code = int(text, 10)
            except (TypeError, ValueError):
                code = symbols.get(text.lower())

        return states.get(code, (False, False, 'unknown'))

    @staticmethod
    def _parse_profile_assignments(
        value: Any,
        *,
        max_count: int,
        valid_values: set[int],
    ) -> list[tuple[int, tuple[int, ...]]] | None:
        """Decode a DOCS-IF31 per-modem profile-list OCTET STRING.

        Agents may preserve the binary octets in a decoded string or render
        them as bare/``0x``-prefixed hexadecimal. Empty values are supported
        and remain neutral; malformed values return ``None`` so they can never
        become positive OFDM/OFDMA evidence.
        """
        if value is None:
            return []
        if isinstance(value, (bytes, bytearray, memoryview)):
            payload = bytes(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            lowered = stripped.lower()
            if 'no such' in lowered or lowered in ('null', 'none'):
                return None

            explicit_hex = lowered.startswith('hex-string:')
            separated_hex = False
            if explicit_hex:
                hex_text = stripped.split(':', 1)[1]
                hex_text = ''.join(
                    ch for ch in hex_text if ch not in ' \t\r\n:-'
                )
            else:
                hex_text = stripped[2:] if lowered.startswith('0x') else stripped
                separators = {sep for sep in (':', '-') if sep in hex_text}
                if separators:
                    if len(separators) != 1:
                        return None
                    parts = hex_text.split(separators.pop())
                    if not all(
                        len(part) == 2
                        and all(ch in '0123456789abcdefABCDEF' for ch in part)
                        for part in parts
                    ):
                        return None
                    hex_text = ''.join(parts)
                    separated_hex = True
            if (
                len(hex_text) % 2 == 0
                and hex_text
                and all(ch in '0123456789abcdefABCDEF' for ch in hex_text)
            ):
                try:
                    payload = bytes.fromhex(hex_text)
                except ValueError:
                    return None
            elif explicit_hex or separated_hex:
                return None
            else:
                try:
                    # Preserve every octet: stripping a binary-decoded string
                    # could remove valid profile/IUC bytes such as 0x09-0x0d.
                    payload = value.encode('latin-1')
                except UnicodeEncodeError:
                    return None
        else:
            return None

        # DOCS-IF31-MIB permits an empty list, otherwise the complete OCTET
        # STRING is bounded to 6..72 bytes. Reject size violations before any
        # assignment can become positive capability evidence.
        if not payload:
            return []
        if len(payload) < 6 or len(payload) > 72:
            return None

        assignments: list[tuple[int, tuple[int, ...]]] = []
        offset = 0
        while offset < len(payload):
            if len(payload) - offset < 5:
                return None
            ifindex = int.from_bytes(payload[offset:offset + 4], 'big')
            count = payload[offset + 4]
            end = offset + 5 + count
            if ifindex <= 0 or count < 1 or count > max_count or end > len(payload):
                return None
            profiles = tuple(payload[offset + 5:end])
            if any(profile not in valid_values for profile in profiles):
                return None
            assignments.append((ifindex, profiles))
            offset = end
        return assignments

    @staticmethod
    def _upgrade_docsis31(modem: dict[str, Any]) -> None:
        """Apply positive DOCSIS 3.1 evidence without downgrading DOCSIS 4.0."""
        current = str(modem.get('docsis_version') or '').lower()
        if '4.0' not in current:
            modem['docsis_version'] = 'DOCSIS 3.1'

    @staticmethod
    def _cache_sufficient(entry: dict[str, Any], limit: int) -> bool:
        cached_count = len(entry.get('modems') or [])
        return bool(
            not limit
            or cached_count >= int(limit)
            or (
                entry.get('complete') is True
                and entry.get('truncated') is not True
            )
        )

    @staticmethod
    def _cache_response(
        cmts_ip: str,
        entry: dict[str, Any],
        *,
        enrich: bool,
        limit: int,
        collect_cpe: bool = False,
    ) -> Dict[str, Any]:
        modems = entry.get('modems') or []
        returned_modems = modems[:int(limit)] if limit else modems
        response = {
            'success': True,
            'modems': returned_modems,
            'count': len(returned_modems),
            'cmts_ip': cmts_ip,
            'enriched': bool(enrich and entry.get('enriched') is True),
            'enriching': bool(enrich and entry.get('enriching') is True),
            'cached': True,
        }
        for key in (
            'capability_enriched', 'source', 'complete', 'truncated',
            'requested_limit', 'collected_at', 'revision_at',
            'critical_oid_errors', 'raw_legacy_mac_count',
            'raw_d3_mac_count', 'cmts_enriched', 'enrich_progress',
        ):
            if key in entry:
                response[key] = entry[key]
        if collect_cpe:
            for key in ('cpe_addresses', 'cpe_complete', 'cpe_truncated', 'cpe_oid_errors'):
                if key in entry:
                    response[key] = entry[key]
        response['capability_enriched'] = entry.get('capability_enriched') is True
        return response

    # ── dedicated CPE collection ────────────────────────────────────────────

    async def collect_cpe_addresses(
        self,
        cmts_ip: str,
        community: str = "public",
        limit: int | None = None,
    ) -> Dict[str, Any]:
        """Collect one authoritative CPE generation without full inventory."""
        self.cmts_ip = cmts_ip
        self.community = community
        requested_limit = limit or _int_env(
            'CM_CPE_IP_LIMIT',
            max(10000, _int_env('CM_MODEM_LIMIT', 50000, maximum=50000) * 8),
            maximum=500000,
        )
        requested_limit = max(1, min(int(requested_limit), 500000))
        walk_oids = (OID_D3_MAC, OID_CPE_ADDR_TYPE, OID_CPE_ADDR, OID_CPE_PREFIX)

        live_lock = await _get_live_walk_lock(cmts_ip)
        await live_lock.acquire()
        try:
            walk_result = await self._send_agent_command(
                'snmp_parallel_walk',
                {
                    'ip': cmts_ip,
                    'oids': list(walk_oids),
                    'community': community,
                    'timeout': 5,
                    'limit': requested_limit,
                    'overall_timeout': 270,
                },
                timeout=300,
            )
        finally:
            live_lock.release()

        if not walk_result.get('success'):
            return {
                'success': False,
                'error': f"CPE SNMP walks failed: {walk_result.get('error', 'unknown')}",
                'cpe_addresses': [],
                'count': 0,
                'complete': False,
                'truncated': False,
            }

        raw = walk_result.get('results') or {}
        walk_errors = walk_result.get('errors') or {}
        completed_oids = set(walk_result.get('completed_oids') or [])
        truncated_oids = set(walk_result.get('truncated_oids') or [])
        has_completion_metadata = 'completed_oids' in walk_result
        walk_warnings_raw = walk_result.get('warnings')
        walk_warnings = (
            [str(warning) for warning in walk_warnings_raw]
            if isinstance(walk_warnings_raw, list)
            else []
        )
        walk_durations = walk_result.get('walk_durations') or {}
        relevant_errors = {
            oid: str(walk_errors[oid]) for oid in walk_oids if oid in walk_errors
        }
        truncated = bool(
            any(oid in truncated_oids for oid in walk_oids)
            or any(len(raw.get(oid, [])) >= requested_limit for oid in walk_oids)
        )
        metadata_completion_confirmed = bool(
            has_completion_metadata
            and all(oid in completed_oids for oid in walk_oids)
        )
        response_completion_confirmed = bool(
            not has_completion_metadata
            and isinstance(walk_result.get('results'), dict)
            and all(oid in raw and isinstance(raw.get(oid), list) for oid in walk_oids)
            and isinstance(walk_warnings_raw, list)
            and not walk_warnings
            and isinstance(walk_durations, dict)
            and all(oid in walk_durations for oid in walk_oids)
        )
        completion_source = (
            'completed_oids'
            if metadata_completion_confirmed
            else 'response_evidence'
            if response_completion_confirmed
            else 'unconfirmed'
        )

        modem_by_index: Dict[str, str] = {}
        ambiguous_d3_indexes: set[str] = set()
        for item in raw.get(OID_D3_MAC, []) or []:
            if not isinstance(item, dict):
                continue
            docsif3_index = self._extract_index(item.get('oid', ''), OID_D3_MAC)
            modem_mac = self._parse_mac(item.get('value'))
            if not docsif3_index or not modem_mac or docsif3_index in ambiguous_d3_indexes:
                continue
            if docsif3_index in modem_by_index:
                modem_by_index.pop(docsif3_index, None)
                ambiguous_d3_indexes.add(docsif3_index)
                continue
            modem_by_index[docsif3_index] = modem_mac

        cpe_addresses, skipped_cpe_rows = self._correlate_cpe_data(
            raw,
            [
                {'docsif3_index': index, 'mac_address': mac}
                for index, mac in modem_by_index.items()
            ],
        )
        missing_completions = [oid for oid in walk_oids if oid not in completed_oids]
        complete = bool(
            (metadata_completion_confirmed or response_completion_confirmed)
            and not relevant_errors
            and not truncated
        )
        validation_reasons = []
        if not has_completion_metadata and not response_completion_confirmed:
            validation_reasons.append(
                'agent omitted per-OID completion metadata and response evidence was insufficient'
            )
        if has_completion_metadata and missing_completions:
            validation_reasons.append('one or more required OID walks did not complete')
        if relevant_errors:
            validation_reasons.append('one or more required OID walks failed')
        if walk_warnings and not has_completion_metadata:
            validation_reasons.append('one or more required OID walks returned warnings')
        if truncated:
            validation_reasons.append('one or more required OID walks were truncated')

        self.logger.info(
            'Collected %s CPE addresses from CMTS %s '
            '(skipped=%s, complete=%s, completion_source=%s)',
            len(cpe_addresses), cmts_ip, skipped_cpe_rows, complete, completion_source,
        )
        return {
            'success': True,
            'cpe_addresses': cpe_addresses,
            'count': len(cpe_addresses),
            'skipped_cpe_rows': skipped_cpe_rows,
            'complete': complete,
            'completion_source': completion_source,
            'truncated': truncated,
            'requested_limit': requested_limit,
            'collected_at': datetime.now(timezone.utc).isoformat(),
            'oid_errors': relevant_errors,
            'validation_error': '; '.join(validation_reasons) or None,
            'raw_d3_mac_count': len(raw.get(OID_D3_MAC, [])),
            'raw_cpe_type_count': len(raw.get(OID_CPE_ADDR_TYPE, [])),
            'raw_cpe_address_count': len(raw.get(OID_CPE_ADDR, [])),
            'raw_cpe_prefix_count': len(raw.get(OID_CPE_PREFIX, [])),
        }

    # ── core discovery ──────────────────────────────────────────────────────

    async def discover_modems(
        self, 
        cmts_ip: str, 
        community: str = "public", 
        limit: int = 10000,
        enrich: bool = False,
        refresh: bool = False,
        collect_cpe: bool = False,
        modem_community: str = "private",
        cmts_hostname: str = "",
    ) -> Dict[str, Any]:
        """Discover cable modems from a CMTS.

        Uses the agent's ``snmp_parallel_walk`` to fetch all required OID
        tables in a single WebSocket round‑trip, then correlates the data
        entirely on the API side.

        When ``enrich=True``, if enriched data is already cached it is
        returned immediately.  Otherwise the base modem list is returned
        at once with ``enriching=True`` and enrichment runs in the
        background.  The GUI can poll to get the enriched result.
        """
        global _enrichment_cache
        self.cmts_ip = cmts_ip
        self.community = community
        
        agent_manager = get_agent_manager()
        if not agent_manager:
            return {'success': False, 'error': 'Agent manager not available',
                    'modems': [], 'count': 0}
        
        agents = agent_manager.get_available_agents()
        if not agents:
            return {'success': False, 'error': 'No agents available',
                    'modems': [], 'count': 0}

        # ── Tier 1: In-memory cache (Redis-like speed) ─────────────────
        if not refresh and cmts_ip in _enrichment_cache:
            cached = _enrichment_cache[cmts_ip]
            age = time.time() - cached.get('timestamp', 0)
            cache_sufficient = self._cache_sufficient(cached, limit)
            cache_usable = (
                not enrich
                or cached.get('enriched') is True
                or cached.get('enriching') is True
            )
            if (
                age < _LIVE_CACHE_TTL_SECONDS
                and cache_sufficient
                and cache_usable
                and (not collect_cpe or 'cpe_addresses' in cached)
            ):
                self.logger.info(
                    "Returning cached generation for %s (age=%.0fs, enrich=%s)",
                    cmts_ip, age, enrich,
                )
                return self._cache_response(
                    cmts_ip, cached, enrich=enrich, limit=limit,
                    collect_cpe=collect_cpe,
                )

        # ── Tier 2: MySQL inventory (survives restarts) ──────────────
        try:
            from pypnm.api.routes.poller.service import poller_service
            snapshot = None if refresh else poller_service.get_inventory_snapshot(cmts_ip)
            inv_modems = [] if refresh else poller_service.list_inventory_modems(
                cmts=cmts_ip, limit=limit,
            )
            if inv_modems:
                # Prefer the generation timestamp persisted with the inventory.
                # Legacy rows without snapshot metadata remain usable for the
                # 200-row preview but cannot prove a complete full inventory.
                age_s = float('inf')
                snapshot_collected_at = (snapshot or {}).get('collected_at')
                if snapshot_collected_at:
                    try:
                        collected = datetime.fromisoformat(
                            str(snapshot_collected_at).replace('Z', '+00:00')
                        )
                        if collected.tzinfo is None:
                            collected = collected.replace(tzinfo=timezone.utc)
                        age_s = (datetime.now(timezone.utc) - collected).total_seconds()
                    except Exception:
                        pass
                if age_s == float('inf'):
                    timestamps = []
                    for m in inv_modems:
                        ts = m.get('updated_at') or m.get('last_seen_at')
                        if not ts:
                            continue
                        try:
                            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00')) if isinstance(ts, str) else ts
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            timestamps.append(dt)
                        except Exception:
                            pass
                    if timestamps:
                        age_s = (datetime.now(timezone.utc) - min(timestamps)).total_seconds()

                is_fresh = age_s < 7200
                requested_limit = int(limit or 0)
                snapshot_complete = bool(
                    snapshot
                    and snapshot.get('complete') is True
                    and snapshot.get('truncated') is not True
                )
                inventory_covers_request = (
                    snapshot_complete
                    or requested_limit <= 200
                    or len(inv_modems) >= requested_limit
                )
                inventory_meta = {
                    'source': 'mysql-inventory',
                    'capability_enriched': (snapshot or {}).get('capability_enriched') is True,
                    'complete': snapshot_complete,
                    'truncated': (snapshot or {}).get('truncated') is True,
                    'requested_limit': (snapshot or {}).get('requested_limit'),
                    'collected_at': snapshot_collected_at,
                    'revision_at': (snapshot or {}).get('revision_at'),
                    'critical_oid_errors': (snapshot or {}).get('critical_oid_errors') or {},
                    'raw_legacy_mac_count': (snapshot or {}).get('raw_legacy_mac_count'),
                    'raw_d3_mac_count': (snapshot or {}).get('raw_d3_mac_count'),
                }
                sample = inv_modems[:200]
                enriched_count = sum(
                    1 for m in sample
                    if (m.get('vendor') or '').strip().lower() not in ('', 'unknown')
                    and (m.get('software_version') or m.get('model') or '').strip()
                )
                is_enriched = (enriched_count / max(len(sample), 1)) >= 0.40

                if is_fresh and not inventory_covers_request:
                    self.logger.info(
                        f"MySQL inventory for {cmts_ip} has {len(inv_modems)} rows "
                        f"without a complete snapshot below requested limit {requested_limit}; "
                        "falling through to SNMP"
                    )

                if is_fresh and inventory_covers_request and not enrich and not collect_cpe:
                    self.logger.info(
                        f"Returning {len(inv_modems)} modems for {cmts_ip} "
                        f"from MySQL inventory (age={age_s:.0f}s, complete={snapshot_complete})"
                    )
                    return {
                        'success': True,
                        'modems': inv_modems,
                        'count': len(inv_modems),
                        'cmts_ip': cmts_ip,
                        'enriched': False,
                        'enriching': False,
                        'cached': True,
                        **inventory_meta,
                    }

                if is_fresh and inventory_covers_request and enrich and is_enriched and not collect_cpe:
                    self.logger.info(
                        f"Returning {len(inv_modems)} modems for {cmts_ip} "
                        f"from MySQL inventory (age={age_s:.0f}s, enriched)"
                    )
                    _enrichment_cache[cmts_ip] = {
                        'modems': inv_modems,
                        'enriched': True,
                        'enriching': False,
                        'timestamp': time.time(),
                        **inventory_meta,
                    }
                    return {
                        'success': True,
                        'modems': inv_modems,
                        'count': len(inv_modems),
                        'cmts_ip': cmts_ip,
                        'enriched': True,
                        'enriching': False,
                        'cached': True,
                        **inventory_meta,
                    }

                if is_fresh and inventory_covers_request and enrich and not is_enriched:
                    self.logger.info(
                        f"MySQL inventory for {cmts_ip} is fresh but not enriched "
                        f"({enriched_count}/{len(sample)}) — falling through to SNMP"
                    )
        except Exception as exc:
            self.logger.warning(f"MySQL inventory lookup skipped for {cmts_ip}: {exc}")

        # ── Tier 3: Live SNMP walk (slow, last resort) ───────────────
        live_lock = await _get_live_walk_lock(cmts_ip)
        await live_lock.acquire()
        try:
            # Re-check after waiting. A recent sufficient generation, including
            # one whose capability tables completed with errors, starts a short
            # refresh cooldown so queued force-refresh requests do not walk again.
            cached = _enrichment_cache.get(cmts_ip)
            if (
                cached
                and self._cache_sufficient(cached, limit)
                and (not collect_cpe or 'cpe_addresses' in cached)
            ):
                age = time.time() - cached.get('timestamp', 0)
                cache_usable = (
                    not enrich
                    or cached.get('enriched') is True
                    or cached.get('enriching') is True
                )
                max_age = (
                    _LIVE_REFRESH_COOLDOWN_SECONDS
                    if refresh else _LIVE_CACHE_TTL_SECONDS
                )
                if age < max_age and cache_usable:
                    self.logger.info(
                        "Reusing single-flight generation for %s "
                        "(age=%.0fs, refresh=%s)",
                        cmts_ip, age, refresh,
                    )
                    return self._cache_response(
                        cmts_ip, cached, enrich=enrich, limit=limit,
                        collect_cpe=collect_cpe,
                    )

            # ── Step 1: Parallel SNMP walks via agent ────────────────────
            walk_oids = [
                OID_D3_MAC, OID_OLD_MAC, OID_OLD_IP, OID_OLD_STATUS,
                OID_OLD_US_CH_IF, OID_SW_REV,
                OID_US_CH_ID, OID_IF_NAME,
                OID_DS_PROFILE_LIST, OID_US_PROFILE_LIST, OID_PARTIAL_SVC,
            ]
            walk_limit = int(limit or 0)
            if collect_cpe:
                walk_oids.extend((OID_CPE_ADDR_TYPE, OID_CPE_ADDR, OID_CPE_PREFIX))
                try:
                    cpe_limit = int(os.environ.get(
                        'CM_CPE_IP_LIMIT', max(10000, walk_limit * 8),
                    ))
                except (TypeError, ValueError):
                    cpe_limit = max(10000, walk_limit * 8)
                walk_limit = max(walk_limit, min(cpe_limit, 500000))
            walk_result = await self._send_agent_command(
                'snmp_parallel_walk',
                {'ip': cmts_ip, 'oids': walk_oids,
                 'community': community, 'timeout': 5, 'limit': walk_limit,
                 'overall_timeout': 270},
                timeout=300,
            )
            if not walk_result.get('success'):
                return {'success': False,
                        'error': f"SNMP walks failed: {walk_result.get('error', 'unknown')}",
                        'modems': [], 'count': 0}

            raw = walk_result.get('results', {})
            legacy_mac_rows = len(raw.get(OID_OLD_MAC, []))
            d3_mac_rows = len(raw.get(OID_D3_MAC, []))
            walk_errors = walk_result.get('errors') or {}
            critical_oids = (OID_OLD_MAC, OID_D3_MAC)
            critical_oid_errors = {
                oid: str(walk_errors[oid])
                for oid in critical_oids
                if oid in walk_errors
            }
            completed_oids = set(walk_result.get('completed_oids') or [])
            has_completion_metadata = 'completed_oids' in walk_result
            critical_walks_complete = (
                has_completion_metadata
                and not critical_oid_errors
                and all(oid in completed_oids for oid in critical_oids)
            )
            capability_oids = (OID_DS_PROFILE_LIST, OID_US_PROFILE_LIST)
            capability_oid_errors = {
                oid: str(walk_errors[oid])
                for oid in capability_oids
                if oid in walk_errors
            }
            missing_capability_completions = [
                oid for oid in capability_oids if oid not in completed_oids
            ]
            capability_enriched = bool(
                has_completion_metadata
                and not capability_oid_errors
                and not missing_capability_completions
            )
            if not has_completion_metadata:
                self.logger.warning(
                    "%s capability collection lacks per-OID completion metadata",
                    cmts_ip,
                )
            if capability_oid_errors:
                self.logger.warning(
                    "%s capability OID collection errors: %s",
                    cmts_ip, capability_oid_errors,
                )
            if missing_capability_completions:
                self.logger.warning(
                    "%s capability OIDs missing completion: %s",
                    cmts_ip, missing_capability_completions,
                )
            truncated_oids = set(walk_result.get('truncated_oids') or [])
            inventory_truncated = bool(
                OID_OLD_MAC in truncated_oids
                or OID_D3_MAC in truncated_oids
                or (
                    limit
                    and (legacy_mac_rows >= int(limit) or d3_mac_rows >= int(limit))
                )
            )
            inventory_meta = {
                'source': 'snmp-live',
                # Empty/unsupported tables count when both walks completed
                # cleanly; errors or absent completion metadata do not.
                'capability_enriched': capability_enriched,
                'complete': critical_walks_complete and not inventory_truncated,
                'truncated': inventory_truncated,
                'requested_limit': int(limit or 0),
                'collected_at': datetime.now(timezone.utc).isoformat(),
                'critical_oid_errors': critical_oid_errors,
                'raw_legacy_mac_count': legacy_mac_rows,
                'raw_d3_mac_count': d3_mac_rows,
            }
            if not has_completion_metadata:
                self.logger.warning(
                    "CMTS inventory completion is unknown because the agent did not return per-OID completion metadata"
                )
            if critical_oid_errors:
                self.logger.warning(
                    "CMTS inventory is partial because critical MAC walks failed: %s",
                    list(critical_oid_errors),
                )

            cpe_addresses: List[Dict[str, Any]] = []
            cpe_complete = False
            cpe_truncated = False
            cpe_oid_errors: Dict[str, str] = {}
            if collect_cpe:
                cpe_oids = (OID_CPE_ADDR_TYPE, OID_CPE_ADDR, OID_CPE_PREFIX)
                cpe_oid_errors = {
                    oid: str(walk_errors[oid]) for oid in cpe_oids if oid in walk_errors
                }
                cpe_truncated = bool(
                    any(oid in truncated_oids for oid in cpe_oids)
                    or any(len(raw.get(oid, [])) >= walk_limit for oid in cpe_oids)
                    or inventory_truncated
                )
                cpe_complete = bool(
                    critical_walks_complete
                    and not cpe_oid_errors
                    and not cpe_truncated
                    and all(oid in completed_oids for oid in cpe_oids)
                )

            # ── Step 2: Parse raw results into lookup maps ───────────────
            modems = self._correlate_modem_data(raw, limit)
            if collect_cpe:
                cpe_addresses, skipped_cpe_rows = self._correlate_cpe_data(raw, modems)
                inventory_meta.update({
                    'cpe_addresses': cpe_addresses,
                    'skipped_cpe_rows': skipped_cpe_rows,
                    'cpe_complete': cpe_complete,
                    'cpe_truncated': cpe_truncated,
                    'cpe_oid_errors': cpe_oid_errors,
                })
            self.logger.info(
                "Discovered %s modems%s from CMTS %s",
                len(modems),
                f" and {len(cpe_addresses)} CPE addresses" if collect_cpe else "",
                cmts_ip,
            )

            # Cache every live base generation, including non-enrichment and
            # unsuccessful capability attempts. Completeness metadata prevents
            # a small partial preview from satisfying a larger request.
            _enrichment_cache[cmts_ip] = {
                'modems': modems,
                'enriched': False,
                'enriching': False,
                'timestamp': time.time(),
                **inventory_meta,
            }

            # GUI-triggered generations carry a hostname. Scheduled poller
            # requests intentionally omit it and persist in their own workflow.
            if str(cmts_hostname or '').strip():
                try:
                    from pypnm.api.routes.poller.service import poller_service
                    poller_service.persist_inventory_generation(
                        modems,
                        cmts_hostname=cmts_hostname,
                        cmts_ip=cmts_ip,
                        metadata=inventory_meta,
                        source_poller='live-gui',
                    )
                    persisted_snapshot = poller_service.get_inventory_snapshot(cmts_ip)
                    persisted_revision = (persisted_snapshot or {}).get('revision_at')
                    if persisted_revision:
                        inventory_meta['revision_at'] = persisted_revision
                        cached_generation = _enrichment_cache.get(cmts_ip)
                        if cached_generation is not None:
                            cached_generation['revision_at'] = persisted_revision
                except Exception as db_exc:
                    self.logger.warning(
                        "Live inventory persistence failed for %s: %s",
                        cmts_ip, db_exc,
                    )

            # ── Step 3: Enrichment ───────────────────────────────────────
            if enrich and modems:
                # Guard: don't start a second enrichment if one is already running
                existing = _enrichment_cache.get(cmts_ip, {})
                existing_sufficient = (
                    not limit
                    or len(existing.get('modems', [])) >= int(limit)
                    or (
                        existing.get('complete') is True
                        and existing.get('truncated') is not True
                    )
                )
                if existing.get('enriching') and (time.time() - existing.get('timestamp', 0)) < 1800 and existing_sufficient:
                    self.logger.info(f"Enrichment already in progress for {cmts_ip}, skipping new launch")
                    return {
                        'success': True,
                        'modems': existing.get('modems', modems),
                        'count': len(existing.get('modems', modems)),
                        'cmts_ip': cmts_ip,
                        'enriched': False,
                        'enriching': True,
                        'capability_enriched': existing.get('capability_enriched') is True,
                        'source': existing.get('source', 'snmp-live'),
                        'complete': existing.get('complete', False),
                        'truncated': existing.get('truncated', True),
                        'enrich_progress': existing.get('enrich_progress', {'completed': 0, 'total': len(modems)}),
                    }

                # Store base modems in cache and kick off background enrichment
                _enrichment_cache[cmts_ip] = {
                    'modems': modems,
                    'enriched': False,
                    'enriching': True,
                    'timestamp': time.time(),
                    'requested_limit': limit,
                    **inventory_meta,
                    'enrich_progress': {'completed': 0, 'total': 0},
                }
                
                # Fire-and-forget background enrichment
                asyncio.create_task(
                    self._background_enrich(cmts_ip, modems, modem_community, cmts_hostname=cmts_hostname)
                )
                
                self.logger.info(f"Returning {len(modems)} modems immediately, enrichment started in background")
                return {
                    'success': True,
                    'modems': modems,
                    'count': len(modems),
                    'cmts_ip': cmts_ip,
                    'enriched': False,
                    'enriching': True,
                    **inventory_meta,
                }

            return {
                'success': True,
                'modems': modems,
                'count': len(modems),
                'cmts_ip': cmts_ip,
                'enriched': False,
                'enriching': False,
                **inventory_meta,
            }
                
        except Exception as e:
            self.logger.exception(f"Error discovering modems from CMTS {cmts_ip}")
            return {'success': False, 'error': str(e),
                    'modems': [], 'count': 0}
        finally:
            live_lock.release()

    async def _background_enrich(self, cmts_ip: str, modems: list, modem_community: str, cmts_hostname: str = ""):
        """Run background enrichment and update the cache in two steps."""
        global _enrichment_cache
        try:
            self.logger.info(f"Background enrichment started for {cmts_ip} ({len(modems)} modems)")

            # Step 1: fast CMTS-level enrichment.
            await self._enrich_cmts_interfaces(modems)
            # Update cache immediately and preserve inventory-completion metadata.
            existing_cache = _enrichment_cache.get(cmts_ip, {})
            _enrichment_cache[cmts_ip] = {
                **existing_cache,
                'modems': modems,
                'enriched': False,
                'enriching': True,
                'cmts_enriched': True,
                'timestamp': time.time(),
                'enrich_progress': {'completed': 0, 'total': len(modems)},
            }
            self.logger.info(f"CMTS interface enrichment done for {cmts_ip} — OFDMA/cable-mac visible")

            # Step 2: slower per-modem enrichment.
            await self._enrich_modems_direct(modems, modem_community, cmts_ip=cmts_ip)

            existing_cache = _enrichment_cache.get(cmts_ip, {})
            _enrichment_cache[cmts_ip] = {
                **existing_cache,
                'modems': modems,
                'enriched': True,
                'enriching': False,
                'timestamp': time.time(),
            }
            enriched_count = sum(1 for m in modems if m.get('model'))
            self.logger.info(f"Background enrichment complete for {cmts_ip}: {enriched_count}/{len(modems)} enriched")

            # Stamp cmts/cmts_ip on every modem for MySQL inventory.
            # cmts_hostname comes from the BFF (ISW API); fall back to IP.
            cmts_label = cmts_hostname or cmts_ip
            for m in modems:
                if not m.get('cmts') or m['cmts'] == 'unknown':
                    m['cmts'] = cmts_label
                if not m.get('cmts_ip'):
                    m['cmts_ip'] = cmts_ip

            # Persist to MySQL so Tier 2 survives container restarts
            try:
                from pypnm.api.routes.poller.service import poller_service
                written = poller_service._upsert_inventory_rows(modems, source_poller='live-enrich')
                self.logger.info(f"Wrote {written} enriched modems to MySQL inventory for {cmts_ip}")
            except Exception as db_exc:
                self.logger.warning(f"MySQL inventory write-back failed for {cmts_ip}: {db_exc}")
        except Exception as e:
            self.logger.exception(f"Background enrichment failed for {cmts_ip}: {e}")
            # Stop retry loops and keep partial data.
            if cmts_ip in _enrichment_cache:
                existing_cache = _enrichment_cache[cmts_ip]
                _enrichment_cache[cmts_ip] = {
                    **existing_cache,
                    'modems': existing_cache.get('modems', modems),
                    'enriched': True,
                    'enriching': False,
                    'timestamp': time.time(),
                    'partial': True,    # flag so callers can tell data is incomplete
                    'complete': False,
                    'truncated': True,
                }

    # ── correlation logic (moved from agent._async_cmts_get_modems) ─────

    def _correlate_modem_data(self, raw: dict, limit: int = 10000) -> List[Dict[str, Any]]:
        """Build the modem list from raw parallel-walk results.

        ``raw`` is ``{oid_base: [{'oid': full, 'value': parsed, 'type': t}, …]}``.
        """
        # ---- MAC addresses (docsIf3 table → index) ----
        mac_map: dict[str, str] = {}  # d3_index → mac
        for item in raw.get(OID_D3_MAC, []):
            mac = self._parse_mac(item['value'])
            if mac:
                index = self._extract_index(item['oid'], OID_D3_MAC)
                mac_map[index] = mac

        self.logger.info(f"Parsed {len(mac_map)} MACs from docsIf3 table")

        # ---- old table lookups (keyed by old_index) ----
        old_mac_map: dict[str, str] = {}
        for item in raw.get(OID_OLD_MAC, []):
            mac = self._parse_mac(item['value'])
            if mac:
                old_mac_map[self._extract_index(item['oid'], OID_OLD_MAC)] = mac

        old_ip_map: dict[str, str] = {}
        for item in raw.get(OID_OLD_IP, []):
            old_ip_map[self._extract_index(item['oid'], OID_OLD_IP)] = str(item['value'])

        old_status_map: dict[str, int] = {}
        for item in raw.get(OID_OLD_STATUS, []):
            try:
                old_status_map[self._extract_index(item['oid'], OID_OLD_STATUS)] = int(item['value'])
            except (ValueError, TypeError):
                pass

        old_us_ch_if_map: dict[str, int] = {}
        for item in raw.get(OID_OLD_US_CH_IF, []):
            try:
                ifidx = int(item['value'])
                if ifidx > 0:
                    old_us_ch_if_map[self._extract_index(item['oid'], OID_OLD_US_CH_IF)] = ifidx
            except (ValueError, TypeError):
                pass

        sw_rev_map: dict[str, str] = {}
        for item in raw.get(OID_SW_REV, []):
            fw = str(item['value'])
            if fw and 'No Such' not in fw and fw != '0':
                sw_rev_map[self._extract_index(item['oid'], OID_SW_REV)] = fw

        # ---- IF-MIB::ifName ----
        if_name_map: dict[int, str] = {}
        for item in raw.get(OID_IF_NAME, []):
            name = str(item['value'])
            if name and 'No Such' not in name:
                try:
                    if_name_map[int(self._extract_index(item['oid'], OID_IF_NAME))] = name
                except (ValueError, TypeError):
                    pass
        self.logger.info(f"Resolved {len(if_name_map)} interface names")

        # ---- partial service state ----
        # DOCS-IF31-MIB defines this object as the INTEGER textual convention
        # PartialServiceType: 1=other, 2=none, 3=DS-only, 4=US-only, 5=both.
        # Preserve direction; collapsing 3/4/5 into one Boolean makes the GUI
        # incorrectly report both OFDM and OFDMA as impaired.
        partial_svc_map: dict[str, tuple[bool, bool, str]] = {}
        for item in raw.get(OID_PARTIAL_SVC, []):
            try:
                idx = self._extract_index(item['oid'], OID_PARTIAL_SVC)
                partial_svc_map[idx] = self._decode_partial_service(item['value'])
            except (ValueError, TypeError):
                pass

        # ---- authoritative per-modem OFDM/OFDMA profile assignments ----
        # These DOCS-IF31 augmentation rows use the docsIf3 registration index.
        # Only fully valid, non-empty assignment lists become positive evidence.
        ds_profile_map: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
        for item in raw.get(OID_DS_PROFILE_LIST, []):
            assignments = self._parse_profile_assignments(
                item.get('value'), max_count=4, valid_values=set(range(16)),
            )
            if assignments:
                idx = self._extract_index(item.get('oid', ''), OID_DS_PROFILE_LIST)
                ds_profile_map[idx] = assignments

        us_profile_map: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
        valid_iucs = {5, 6, 9, 10, 11, 12, 13}
        for item in raw.get(OID_US_PROFILE_LIST, []):
            assignments = self._parse_profile_assignments(
                item.get('value'), max_count=2, valid_values=valid_iucs,
            )
            if assignments:
                idx = self._extract_index(item.get('oid', ''), OID_US_PROFILE_LIST)
                us_profile_map[idx] = assignments

        # ---- US channel mapping (docsIf3, compound index) ----
        us_ch_map: dict[str, int] = {}
        for item in raw.get(OID_US_CH_ID, []):
            try:
                index = self._extract_index(item['oid'], OID_US_CH_ID)
                parts = index.split('.')
                if len(parts) >= 2:
                    modem_index = parts[0]
                    ch_ifindex = int(parts[1])
                    if modem_index not in us_ch_map or ch_ifindex < us_ch_map[modem_index]:
                        us_ch_map[modem_index] = ch_ifindex
            except (ValueError, TypeError):
                pass

        # ---- correlate old table → MAC-keyed lookups ----
        mac_to_ip: dict[str, str] = {}
        mac_to_status: dict[str, int] = {}
        mac_to_firmware: dict[str, str] = {}
        mac_to_us_ch_if: dict[str, int] = {}
        for old_index, mac in old_mac_map.items():
            if old_index in old_ip_map:
                mac_to_ip[mac] = old_ip_map[old_index]
            if old_index in old_status_map:
                mac_to_status[mac] = old_status_map[old_index]
            if old_index in sw_rev_map:
                mac_to_firmware[mac] = sw_rev_map[old_index]
            if old_index in old_us_ch_if_map:
                mac_to_us_ch_if[mac] = old_us_ch_if_map[old_index]

        self.logger.info(
            f"Correlated: {len(mac_to_ip)} IPs, {len(mac_to_status)} statuses, "
            f"{len(mac_to_firmware)} firmware, {len(mac_to_us_ch_if)} D3.0 US-CH, "
            f"{len(us_ch_map)} D3.1 US-CH"
        )

        # ---- build modem list from the union of both registration tables ----
        # Some CMTS platforms expose only DOCSIS 3.1 modems in the docsIf3
        # table while the legacy docsIf table contains the complete registered
        # population. Keep each table's index for table-specific lookups, but
        # deduplicate and correlate the returned inventory by MAC address.
        d3_index_by_mac = {mac: index for index, mac in mac_map.items()}
        modem_rows: list[tuple[str, str, str | None]] = []
        seen_macs: set[str] = set()

        for old_index, mac in old_mac_map.items():
            if mac in seen_macs:
                continue
            seen_macs.add(mac)
            modem_rows.append((mac, old_index, d3_index_by_mac.get(mac)))

        for d3_index, mac in mac_map.items():
            if mac in seen_macs:
                continue
            seen_macs.add(mac)
            modem_rows.append((mac, d3_index, d3_index))

        self.logger.info(
            f"Building inventory from {len(modem_rows)} unique MACs "
            f"({len(old_mac_map)} legacy rows, {len(mac_map)} docsIf3 rows)"
        )

        modems: list[dict] = []
        for mac, index, d3_index in modem_rows:
            modem: dict[str, Any] = {
                'mac_address': mac,
                'cmts_index': index,
            }
            if d3_index is not None:
                # Keep the DOCS-IF3 augmentation index distinct from the
                # legacy/display registration index used by existing clients.
                modem['docsif3_index'] = d3_index

            if mac in mac_to_ip:
                modem['ip_address'] = mac_to_ip[mac]

            if mac in mac_to_status:
                sc = mac_to_status[mac]
                modem['status_code'] = sc
                modem['status'] = STATUS_MAP.get(sc, 'unknown')

            if mac in mac_to_firmware:
                modem['firmware'] = mac_to_firmware[mac]

            # Positive DOCS-IF31 per-modem state proves DOCSIS 3.1 capability,
            # including state=none (healthy, not partial service). Operational
            # rows without 3.1 evidence fall back to the online DOCSIS 3.0
            # bucket; an online modem must never leave discovery as Unknown.
            modem['docsis_version'] = 'Unknown'
            if d3_index is not None and d3_index in partial_svc_map:
                partial_ds, partial_us, partial_state = partial_svc_map[d3_index]
                modem['docsis_version'] = 'DOCSIS 3.1'
                modem['partial_service'] = partial_ds or partial_us
                modem['partial_service_downstream'] = partial_ds
                modem['partial_service_upstream'] = partial_us
                modem['partial_service_state'] = partial_state
            elif modem.get('status') == 'operational':
                modem['docsis_version'] = 'DOCSIS 3.0'

            if d3_index is not None:
                ds_assignments = ds_profile_map.get(d3_index) or []
                if ds_assignments:
                    ds_ifindexes = list(dict.fromkeys(ifindex for ifindex, _ in ds_assignments))
                    modem['ofdm_enabled'] = True
                    modem['ofdm_ifindex'] = ds_ifindexes[0]
                    modem['ofdm_channel_count'] = len(ds_ifindexes)
                    self._upgrade_docsis31(modem)

                us_assignments = us_profile_map.get(d3_index) or []
                if us_assignments:
                    us_ifindexes = list(dict.fromkeys(ifindex for ifindex, _ in us_assignments))
                    modem['ofdma_enabled'] = True
                    modem['ofdma_ifindex'] = us_ifindexes[0]
                    modem['ofdma_channel_count'] = len(us_ifindexes)
                    self._upgrade_docsis31(modem)

            # Upstream interface resolution. D3 metadata must use the docsIf3
            # index, which is not guaranteed to match the legacy table index.
            us_ifindex = mac_to_us_ch_if.get(mac)
            if not us_ifindex and d3_index is not None:
                us_ifindex = us_ch_map.get(d3_index)
            if us_ifindex:
                modem['upstream_ifindex'] = us_ifindex
                modem['upstream_interface'] = if_name_map.get(us_ifindex, f'US-CH {us_ifindex}')
            else:
                modem['upstream_interface'] = None

            if d3_index is not None and d3_index in us_ch_map:
                modem['upstream_channel_id'] = us_ch_map[d3_index]

            # Skip modems that are offline: status=other(1) with no IP assigned.
            # Casa CCAP and some other vendors report status=1 for all unreachable
            # modems and never populate their IP — these are not worth showing.
            if modem.get('status_code') == 1 and modem.get('ip_address', '0.0.0.0') in ('0.0.0.0', '', None):
                continue

            modems.append(modem)
            if limit and len(modems) >= limit:
                break

        # Sort by CMTS table index (numeric) so the modem order is always
        # deterministic and matches the SNMP registration order regardless of
        # dict insertion quirks or OID string vs. numeric ordering differences.
        modems.sort(key=self._sort_key_cmts_index)

        return modems

    @staticmethod
    def _sort_key_cmts_index(modem: dict):
        """Sort key: numeric cmts_index so modem order matches SNMP registration order."""
        try:
            return int(modem.get('cmts_index') or 0)
        except (ValueError, TypeError):
            return 0

    async def _enrich_cmts_interfaces(self, modems: list) -> dict:
        """Join DOCSIS 3.1 CMTS interface tables using each modem's DOCS-IF3 index."""
        if not modems:
            return {'success': True, 'enriched_count': 0, 'total_count': 0}
            
        self.logger.info(f"Enriching cable-mac/upstream for {len(modems)} modems from CMTS {self.cmts_ip}")
        
        # DOCS-IF3/31 tables share only the docsIf3 registration index.
        # Legacy indexes are intentionally excluded because cross-table values
        # can differ and a guessed join can enrich the wrong modem.
        index_to_modem = {}
        for modem in modems:
            index = modem.get('docsif3_index')
            if index is not None and str(index):
                index_to_modem[str(index)] = modem
        modem_indexes = set(index_to_modem.keys())
        
        if not modem_indexes:
            self.logger.warning("No modem indexes to enrich")
            return {'success': True, 'enriched_count': 0, 'total_count': len(modems)}
        
        # OIDs
        OID_MD_IF_INDEX = '1.3.6.1.4.1.4491.2.1.20.1.3.1.7'  # docsIf3CmtsCmRegStatusMdIfIndex
        OID_IF_NAME = '1.3.6.1.2.1.31.1.1.1.1'  # IF-MIB::ifName
        OID_CM_OFDMA_TIMING = '1.3.6.1.4.1.4491.2.1.28.1.4.1.2'  # OFDMA timing offset
        OID_IF_DESCR = '1.3.6.1.2.1.2.2.1.2'  # IF-MIB::ifDescr
        OID_MD_NODE_DS_SG = '1.3.6.1.4.1.4491.2.1.20.1.12.1.3'  # docsIf3MdNodeStatusMdDsSgId
        
        # Single parallel_walk for all 4 OIDs — same as modem discovery.
        # max_repetitions=500 → 8756 rows / 500 = ~18 PDUs total, completes in <5s on LAN.
        walk_oids = [OID_MD_IF_INDEX, OID_IF_NAME, OID_CM_OFDMA_TIMING, OID_MD_NODE_DS_SG]
        try:
            walk_result = await self._send_agent_command(
                'snmp_parallel_walk',
                {'ip': self.cmts_ip, 'oids': walk_oids, 'community': self.community,
                 'timeout': 5, 'max_repetitions': 500},
                timeout=120,
            )
        except Exception as e:
            self.logger.exception(f"Interface parallel_walk failed: {e}")
            return {'success': False, 'enriched_count': 0, 'total_count': len(modems)}

        if not walk_result.get('success'):
            self.logger.warning(f"Interface parallel_walk returned no data: {walk_result.get('error')}")
            return {'success': False, 'enriched_count': 0, 'total_count': len(modems)}

        raw = walk_result.get('results', {})
        self.logger.info(
            f"Interface parallel_walk raw keys: {list(raw.keys())} "
            f"sizes: md_if={len(raw.get(OID_MD_IF_INDEX, []))} "
            f"if_name={len(raw.get(OID_IF_NAME, []))} "
            f"ofdma={len(raw.get(OID_CM_OFDMA_TIMING, []))} "
            f"fn_node={len(raw.get(OID_MD_NODE_DS_SG, []))}"
        )

        # Parse (index, value) pairs from parallel_walk result dict
        def parse_oid(base_oid):
            return [
                (item['oid'][len(base_oid) + 1:], item['value'])
                for item in raw.get(base_oid, [])
                if item.get('oid', '').startswith(base_oid + '.')
            ]

        md_if_results   = parse_oid(OID_MD_IF_INDEX)
        if_name_results = parse_oid(OID_IF_NAME)
        ofdma_results   = parse_oid(OID_CM_OFDMA_TIMING)
        fn_node_results = raw.get(OID_MD_NODE_DS_SG, [])
        
        # Parse MD-IF-INDEX: modem_index -> md_if_index (COPY-PASTE from agent)
        md_if_map = {}
        for index, value in md_if_results:
            if index in modem_indexes:
                try:
                    md_if_map[index] = int(value)
                except:
                    pass
        
        # Parse IF-MIB::ifName: ifindex -> name (COPY-PASTE from agent)
        if_name_map = {}
        for index, value in if_name_results:
            name = str(value)
            if name and 'No Such' not in name:
                try:
                    if_name_map[int(index)] = name
                except:
                    pass
        
        # Parse docsIf3MdNodeStatusMdDsSgId: mdIfIndex → fiber_node_name
        # OID index format: {mdIfIndex}.{strLen}.{char0}...{charN}.{mCmSgId}
        md_if_to_fn = {}  # mdIfIndex (int) → fiber_node_name (str)
        _fn_skip_short = 0
        _fn_skip_len_mismatch = 0
        _fn_skip_nul = 0
        _fn_skip_exc = 0
        _fn_extended_ascii = 0
        for item in fn_node_results:
            oid = item.get('oid', '')
            if not oid.startswith(OID_MD_NODE_DS_SG + '.'):
                continue
            suffix = oid[len(OID_MD_NODE_DS_SG) + 1:]
            parts = suffix.split('.')
            if len(parts) < 4:
                _fn_skip_short += 1
                continue
            try:
                fn_md_if = int(parts[0])
                str_len = int(parts[1])
                if len(parts) < 2 + str_len + 1:
                    _fn_skip_len_mismatch += 1
                    continue
                byte_vals = [int(p) for p in parts[2:2 + str_len]]
                # Accept printable ASCII (32-126) AND extended Latin-1 (128-255).
                # Old strict range (32-126) silently rejects fiber node names that
                # contain extended characters (e.g. Dutch/EU operator naming conventions).
                # Reject NUL bytes (0) and DEL (127) but allow everything else.
                if any(v == 0 or v == 127 for v in byte_vals):
                    _fn_skip_nul += 1
                    continue
                fn_name = ''.join(chr(v) for v in byte_vals)
                if any(v > 126 for v in byte_vals):
                    _fn_extended_ascii += 1
                if fn_md_if not in md_if_to_fn:
                    md_if_to_fn[fn_md_if] = fn_name
            except (ValueError, IndexError):
                _fn_skip_exc += 1

        self.logger.info(
            f"Resolved {len(md_if_map)} MD-IF-INDEX, {len(if_name_map)} interface names, "
            f"{len(md_if_to_fn)} fiber nodes from {len(fn_node_results)} FN-table rows "
            f"(skipped: short={_fn_skip_short} len_mismatch={_fn_skip_len_mismatch} "
            f"nul={_fn_skip_nul} exc={_fn_skip_exc} extended_ascii_names={_fn_extended_ascii})"
        )
        if not md_if_to_fn and fn_node_results:
            self.logger.warning(
                f"{self.cmts_ip}: docsIf3MdNodeStatusMdDsSgId returned {len(fn_node_results)} rows "
                f"but ALL were rejected by the name parser — check FN name encoding on this CMTS"
            )
        elif not md_if_to_fn:
            self.logger.warning(
                f"{self.cmts_ip}: docsIf3MdNodeStatusMdDsSgId returned 0 rows — "
                f"fiber nodes not configured on this CMTS or OID not supported (Remote PHY?)"
            )
        
        # Parse OFDMA: modem_index -> ofdma_ifindex
        # Uses vendor-agnostic timing offset check (0 = no OFDMA, >0 = active OFDMA)
        # Works for all DOCSIS 3.1 CMTS vendors:
        #  - Cisco cBR-8: ifIndexes ~488334
        #  - CommScope E6000: ifIndexes ~843087xxx
        #  - Casa CMTS: Similar to CommScope
        ofdma_if_map = {}
        ofdma_ifindexes = set()
        for index, value in ofdma_results:
            try:
                parts = index.split('.')
                if len(parts) >= 2:
                    cm_idx = parts[0]
                    ofdma_ifidx = int(parts[1])
                    # Timing offset > 0 indicates active OFDMA channel (vendor-agnostic)
                    try:
                        timing_offset = int(value)
                        if cm_idx in modem_indexes and timing_offset > 0:
                            ofdma_if_map[cm_idx] = ofdma_ifidx
                            ofdma_ifindexes.add(ofdma_ifidx)
                    except (ValueError, TypeError):
                        pass
            except:
                pass
        
        self.logger.info(f"Discovered {len(ofdma_if_map)} OFDMA upstream interfaces")
        
        # Get OFDMA interface descriptions (COPY-PASTE from agent)
        ofdma_descr_map = {}
        if ofdma_ifindexes:
            try:
                descr_walk = await self._send_agent_command(
                    'snmp_parallel_walk',
                    {'ip': self.cmts_ip, 'oids': [OID_IF_DESCR], 'community': self.community,
                     'timeout': 5, 'max_repetitions': 500},
                    timeout=60,
                )
                if descr_walk.get('success'):
                    for item in descr_walk.get('results', {}).get(OID_IF_DESCR, []):
                        raw_oid = item.get('oid', '')
                        if not raw_oid.startswith(OID_IF_DESCR + '.'):
                            continue
                        try:
                            ifidx = int(raw_oid[len(OID_IF_DESCR) + 1:])
                            if ifidx in ofdma_ifindexes:
                                descr = str(item.get('value', ''))
                                if descr and 'No Such' not in descr:
                                    ofdma_descr_map[ifidx] = descr
                        except:
                            pass
                self.logger.info(f"Resolved {len(ofdma_descr_map)} OFDMA interface descriptions")
            except Exception as e:
                self.logger.debug(f"Failed to get OFDMA descriptions: {e}")
        
        # Apply to modems (COPY-PASTE from agent)
        enriched_count = 0
        us_ch_resolved = 0
        for modem in modems:
            index = modem.get('docsif3_index')
            idx = str(index) if index is not None else ''
            if not idx:
                continue
            
            # Add cable_mac and fiber_node from MD-IF-INDEX -> ifName / fnName
            if idx in md_if_map:
                md_if_idx = md_if_map[idx]
                if md_if_idx in if_name_map:
                    modem['cable_mac'] = if_name_map[md_if_idx]
                    enriched_count += 1
                if md_if_idx in md_if_to_fn:
                    modem['fiber_node'] = md_if_to_fn[md_if_idx]
            
            # Add OFDMA upstream interface if discovered 
            if idx in ofdma_if_map:
                ofdma_ifidx = ofdma_if_map[idx]
                modem['ofdma_ifindex'] = ofdma_ifidx
                modem['ofdma_enabled'] = True
                # OFDMA upstream is positive DOCSIS >=3.1 evidence; it
                # does not establish downstream OFDM support. Preserve 4.0.
                self._upgrade_docsis31(modem)
                if ofdma_ifidx in ofdma_descr_map:
                    descr = ofdma_descr_map[ofdma_ifidx]
                    # Ensure 'ofdma' appears in the interface name so the GUI
                    # badge check (upstream_interface.includes('ofdma')) works
                    # for all vendors (Cisco names like C1/0/6/UB lack it)
                    if 'ofdma' not in descr.lower():
                        descr = f'cable-us-ofdma {descr}'
                    modem['upstream_interface'] = descr
            else:
                # Absence from this positive OFDMA timing table is not an
                # authoritative negative. Preserve tri-state capability so a
                # missing vendor row cannot paint a healthy modem red or
                # override stronger evidence from inventory/channel discovery.
                us_ifidx = modem.get('upstream_ifindex')
                if us_ifidx and us_ifidx in if_name_map:
                    modem['upstream_interface'] = if_name_map[us_ifidx]
                    us_ch_resolved += 1

        self.logger.info(f"Enriched {enriched_count} modems with cable-mac, {len(ofdma_if_map)} with OFDMA")
        
        return {
            'success': True,
            'enriched_count': len([m for m in modems if m.get('model') or m.get('cable_mac')]),
            'total_count': len(modems)
        }

    async def _enrich_modems_direct(self, modems: list, modem_community: str = 'private', cmts_ip: str = None) -> list:
        """
        Query each modem directly via agent SNMP to get sysDescr + DOCSIS cap.
        Uses snmp_bulk_get (all OIDs per modem in one call) and asyncio.gather
        to run up to BATCH_SIZE modems in parallel.
        """
        import asyncio

        OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'
        OID_DOCSIS_CAP_31 = '1.3.6.1.4.1.4491.2.1.28.1.1.5'
        OID_DOCSIS_CAP_30 = '1.3.6.1.2.1.10.127.1.1.5.0'
        ALL_OIDS = [OID_SYS_DESCR, OID_DOCSIS_CAP_31, OID_DOCSIS_CAP_30]

        online_statuses = {'operational', 'registrationComplete', 'ipComplete', 'online'}
        skip_prefixes = ('10.160.', '10.254.', '10.255.')
        online_modems = [m for m in modems
                         if m.get('ip_address') and m.get('ip_address') != 'N/A'
                         and m.get('ip_address') != '0.0.0.0'
                         and not m.get('ip_address', '').startswith(skip_prefixes)
                         and m.get('status') in online_statuses]

        MAX_CONCURRENT = _int_env('CM_ENRICH_MAX_CONCURRENT', 8, minimum=1, maximum=64)
        FLUSH_EVERY = _int_env('CM_ENRICH_FLUSH_EVERY', 40, minimum=1, maximum=1000)
        MAX_ENRICHMENT_SECS = _int_env('CM_ENRICH_MAX_SECS', 1800, minimum=60, maximum=7200)
        AGENT_WAIT_TIMEOUT_SECS = _int_env('CM_ENRICH_AGENT_WAIT_TIMEOUT_SECS', 20, minimum=5, maximum=120)
        SNMP_TIMEOUT_SECS = _int_env('CM_ENRICH_SNMP_TIMEOUT_SECS', 3, minimum=1, maximum=30)
        SNMP_MAX_CONCURRENT = _int_env('CM_ENRICH_SNMP_MAX_CONCURRENT', 2, minimum=1, maximum=10)

        self.logger.info(
            f"Direct enrichment: {len(online_modems)} modems "
            f"(max_concurrent={MAX_CONCURRENT}, flush_every={FLUSH_EVERY}, "
            f"max_secs={MAX_ENRICHMENT_SECS}, agent_wait_timeout={AGENT_WAIT_TIMEOUT_SECS}, "
            f"snmp_timeout={SNMP_TIMEOUT_SECS}, snmp_max_concurrent={SNMP_MAX_CONCURRENT})"
        )
        if not online_modems:
            return modems

        # ── Pre-filter: ICMP ping sweep to skip unreachable modems ───
        # Eliminates ~50% of 3s SNMP timeouts, cutting enrichment time in half.
        all_ips = [m.get('ip_address') for m in online_modems]
        try:
            sweep_result = await self._send_cm_agent_command(
                command='ping_sweep',
                params={
                    'targets': all_ips,
                    'count': 1,
                    'timeout': 1,
                    'concurrent_tasks': 200,
                },
                timeout=60,
            )
            if sweep_result and sweep_result.get('success'):
                reachable_set = set(sweep_result.get('reachable', []))
                before = len(online_modems)
                if reachable_set:
                    online_modems = [m for m in online_modems if m.get('ip_address') in reachable_set]
                    skipped = before - len(online_modems)
                    self.logger.info(
                        f"Ping sweep: {len(reachable_set)}/{before} reachable, "
                        f"skipping {skipped} unreachable modems"
                    )
                else:
                    # Some agents can return success with an empty reachable list
                    # when ping_sweep is unsupported/misconfigured. Do not drop all
                    # modems in that case; continue with SNMP enrichment.
                    self.logger.warning(
                        "Ping sweep returned success but zero reachable targets; "
                        "proceeding with all modems"
                    )
            else:
                self.logger.warning(
                    f"Ping sweep failed ({sweep_result.get('error') if sweep_result else 'no result'}), "
                    "proceeding with all modems"
                )
        except Exception as e:
            self.logger.warning(f"Ping sweep unavailable ({e}), proceeding with all modems")

        # Initialise progress in cache so polling clients can track it
        if cmts_ip and cmts_ip in _enrichment_cache:
            _enrichment_cache[cmts_ip]['enrich_progress'] = {'completed': 0, 'total': len(online_modems)}

        enriched_count = 0
        completed_count = 0  # modems attempted (success + failure)
        _first_failure_logged = False
        _first_success_logged = False

        async def _enrich_one(modem: dict):
            """Enrich a single modem using snmp_bulk_get (1 agent call for 3 OIDs)."""
            nonlocal enriched_count, completed_count, _first_failure_logged, _first_success_logged
            # Honour cancel signal — skip SNMP call entirely
            if cmts_ip and _enrichment_cache.get(cmts_ip, {}).get('cancelled'):
                return
            ip = modem.get('ip_address')
            try:
                result = await self._send_cm_agent_command(
                    command='snmp_bulk_get',
                    params={
                        'target_ip': ip,
                        'oids': ALL_OIDS,
                        # Do NOT pass community — let the CM agent use its own
                        # configured cm_community (the API-side modem_community
                        # is the BFF/CMTS community, not the modem community).
                        'timeout': SNMP_TIMEOUT_SECS,
                        'retries': 0,   # enrichment — don't retry; skip and move on
                        'max_concurrent': SNMP_MAX_CONCURRENT,
                    },
                    timeout=AGENT_WAIT_TIMEOUT_SECS,
                )
                if not result or not result.get('success'):
                    if not _first_failure_logged:
                        _first_failure_logged = True
                        self.logger.warning(
                            f"Direct enrichment snmp_bulk_get failed for first sample modem {ip}: "
                            f"{result.get('error') if result else 'no result/timeout'}"
                        )
                    return

                oid_results = result.get('results', {})
                if not oid_results:
                    return

                # ── sysDescr ──
                sys_r = oid_results.get(OID_SYS_DESCR, {})
                if sys_r.get('success') and sys_r.get('output'):
                    raw = sys_r['output']
                    sys_descr = raw.split('=', 1)[-1].strip() if '=' in raw else raw
                    if sys_descr and 'No Such' not in sys_descr:
                        info = self._parse_sys_descr(sys_descr)
                        modem['model'] = info.get('model', 'Unknown')
                        modem['software_version'] = info.get('software', '')
                        if info.get('vendor'):
                            modem['vendor'] = info['vendor']
                        enriched_count += 1
                        if not _first_success_logged:
                            _first_success_logged = True
                            self.logger.info(f"Enrichment sample: {ip} → model={modem['model']} vendor={modem.get('vendor')} sw={modem.get('software_version')}")

                # ── DOCSIS capability (try 3.1 first, fallback 3.0) ──
                docsis_version = None
                for oid in (OID_DOCSIS_CAP_31, OID_DOCSIS_CAP_30):
                    dr = oid_results.get(oid, {})
                    if dr.get('success') and dr.get('output'):
                        raw = dr['output']
                        cap = raw.split('=')[-1].strip() if '=' in raw else raw
                        if 'No Such' not in cap:
                            docsis_version = self._parse_docsis_cap(cap)
                            if docsis_version:
                                break
                if docsis_version:
                    # Never let a weaker fallback capability overwrite stronger
                    # positive evidence already learned from OFDMA/OFDM or an
                    # earlier capability probe.
                    version_rank = {
                        'DOCSIS 1.0': 10,
                        'DOCSIS 1.1': 11,
                        'DOCSIS 2.0': 20,
                        'DOCSIS 3.0': 30,
                        'DOCSIS 3.1': 31,
                        'DOCSIS 4.0': 40,
                    }
                    current_version = modem.get('docsis_version')
                    if version_rank.get(docsis_version, 0) >= version_rank.get(current_version, 0):
                        modem['docsis_version'] = docsis_version

            except Exception as e:
                if not _first_failure_logged:
                    _first_failure_logged = True
                    self.logger.warning(f"Direct enrichment exception for first sample modem {ip}: {e}")
                self.logger.debug(f"Failed to enrich modem {ip}: {e}")
            finally:
                # Always count this modem as done so the progress bar advances
                completed_count += 1
                if cmts_ip and cmts_ip in _enrichment_cache:
                    cache_entry = _enrichment_cache[cmts_ip]
                    if not cache_entry.get('cancelled'):
                        progress = cache_entry.setdefault(
                            'enrich_progress',
                            {'completed': 0, 'total': len(online_modems)}
                        )
                        progress['completed'] = completed_count
                        # Flush enriched modem data every FLUSH_EVERY completions
                        # so the GUI poll sees continuously updated vendor/model fields
                        if completed_count % FLUSH_EVERY == 0:
                            cache_entry['timestamp'] = time.time()

        # ── Process ALL modems at once — semaphore caps concurrency ──────────
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def _enrich_one_sem(modem: dict):
            async with sem:
                await _enrich_one(modem)

        # Hard time cap: cancel remaining tasks after MAX_ENRICHMENT_SECS
        # so huge CMTSes (10k+ modems) don't block the enrichment pipeline.
        try:
            await asyncio.wait_for(
                asyncio.gather(*[_enrich_one_sem(m) for m in online_modems]),
                timeout=MAX_ENRICHMENT_SECS,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                f"Direct enrichment hit {MAX_ENRICHMENT_SECS}s time cap: "
                f"{enriched_count}/{len(online_modems)} enriched so far, finishing with partial results"
            )

        # Final timestamp flush
        if cmts_ip and cmts_ip in _enrichment_cache:
            _enrichment_cache[cmts_ip]['timestamp'] = time.time()

        cancelled = cmts_ip and _enrichment_cache.get(cmts_ip, {}).get('cancelled')
        self.logger.info(
            f"Direct enrichment {'cancelled' if cancelled else 'done'}: "
            f"{enriched_count}/{len(online_modems)} modems enriched"
        )
        return modems

    def _parse_sys_descr(self, sys_descr: str) -> dict:
        """Parse sysDescr to extract vendor, model, and software version."""
        import re
        result = {}
        
        # Check for structured format: <<KEY: value; KEY: value>>
        # Example: "FAST3896 Wireless Voice Gateway <<HW_REV: 1.2; VENDOR: SAGEMCOM; SW_REV: LG-RDK_11.10.26; MODEL: F3896LG>>"
        structured_match = re.search(r'<<(.+?)>>', sys_descr)
        if structured_match:
            fields = structured_match.group(1)
            for pair in fields.split(';'):
                if ':' in pair:
                    key, value = pair.split(':', 1)
                    key = key.strip().upper()
                    value = value.strip()
                    if key == 'MODEL':
                        result['model'] = value
                    elif key == 'VENDOR':
                        result['vendor'] = value
                    elif key == 'SW_REV':
                        result['software'] = value
            if result.get('model'):
                return result
        
        # Fallback: pattern matching for non-structured sysDescr
        descr = sys_descr.lower()
        
        if 'arris' in descr or 'touchstone' in descr:
            result['vendor'] = 'ARRIS Group, Inc.'
        elif 'technicolor' in descr:
            result['vendor'] = 'Technicolor'
        elif 'sagemcom' in descr:
            result['vendor'] = 'SAGEMCOM'
        elif 'hitron' in descr:
            result['vendor'] = 'Hitron'
        elif 'motorola' in descr:
            result['vendor'] = 'Motorola'
        elif 'cisco' in descr:
            result['vendor'] = 'Cisco'
        elif 'ubee' in descr:
            result['vendor'] = 'Ubee'
        elif 'compal' in descr:
            result['vendor'] = 'Compal Broadband Networks'
        
        # Model patterns
        model_match = re.search(r'(FAST\d+|F\d{4}[A-Z]*|TG\d+|TC\d+|SB\d+|DPC\d+|EPC\d+|CM\d+|SBG\d+|CGM\d+|CH\d+[A-Z]*|UBC\d+[A-Z]*)', sys_descr, re.I)
        if model_match:
            result['model'] = model_match.group(1).upper()
        
        # Software version
        version_match = re.search(r'(\d+\.\d+\.\d+[\.\d\-a-zA-Z]*)', sys_descr)
        if version_match:
            result['software'] = version_match.group(1)
        
        return result

    def _parse_docsis_cap(self, cap_str: str) -> str:
        """Parse DOCSIS capability value from docsIf31DocsisBaseCapability.
        Values: docsis10(1), docsis11(2), docsis20(3), docsis30(4), docsis31(5), docsis40(6)
        """
        try:
            cap_str = cap_str.strip().lower()
            if 'docsis31' in cap_str or cap_str == '5':
                return 'DOCSIS 3.1'
            elif 'docsis30' in cap_str or cap_str == '4':
                return 'DOCSIS 3.0'
            elif 'docsis40' in cap_str or cap_str == '6':
                return 'DOCSIS 4.0'
            elif 'docsis20' in cap_str or cap_str == '3':
                return 'DOCSIS 2.0'
            elif 'docsis11' in cap_str or cap_str == '2':
                return 'DOCSIS 1.1'
            elif 'docsis10' in cap_str or cap_str == '1':
                return 'DOCSIS 1.0'
            # Try parsing as integer
            cap = int(cap_str.split('(')[-1].rstrip(')'))
            docsis_map = {1: 'DOCSIS 1.0', 2: 'DOCSIS 1.1', 3: 'DOCSIS 2.0', 
                         4: 'DOCSIS 3.0', 5: 'DOCSIS 3.1', 6: 'DOCSIS 4.0'}
            return docsis_map.get(cap)
        except:
            pass
        return None