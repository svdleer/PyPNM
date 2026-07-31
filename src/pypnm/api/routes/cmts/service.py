# SPDX-License-Identifier: Apache-2.0
# CMTS Modem Discovery Service

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, List, Any

from pypnm.api.agent.manager import get_agent_manager


# ── In-memory enrichment cache ──────────────────────────────────────────────
# Keyed by cmts_ip → {modems, enriched, enriching, timestamp, cancelled}
_enrichment_cache: Dict[str, Dict[str, Any]] = {}
_enrichment_lock = asyncio.Lock()


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
# Old (DOCSIS 3.0) CM status table
OID_OLD_MAC      = '1.3.6.1.2.1.10.127.1.3.3.1.2'       # docsIfCmtsCmStatusMacAddress
OID_OLD_IP       = '1.3.6.1.2.1.10.127.1.3.3.1.3'       # docsIfCmtsCmStatusIpAddress
OID_OLD_STATUS   = '1.3.6.1.2.1.10.127.1.3.3.1.9'       # docsIfCmtsCmStatusValue
OID_OLD_US_CH_IF = '1.3.6.1.2.1.10.127.1.3.3.1.5'       # docsIfCmtsCmStatusUpChannelIfIndex
OID_SW_REV       = '1.3.6.1.2.1.10.127.1.2.2.1.3'       # docsIfCmtsCmStatusSoftwareRev (firmware)
# DOCSIS 3.1 supplementary
OID_US_CH_ID     = '1.3.6.1.4.1.4491.2.1.20.1.4.1.3'    # docsIf3CmtsCmUsStatusChIfIndex
OID_IF_NAME      = '1.3.6.1.2.1.31.1.1.1.1'              # IF-MIB::ifName
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
        """Return the OID suffix after *base_oid* (without leading dot)."""
        if full_oid.startswith(base_oid + '.'):
            return full_oid[len(base_oid) + 1:]
        return full_oid.rsplit('.', 1)[-1]

    @staticmethod
    def _parse_mac(raw: str) -> str | None:
        """Normalise a MAC value (hex‑string / 0x‑prefixed / colon‑separated)
        into ``aa:bb:cc:dd:ee:ff`` format.  Returns *None* on failure.

        Handles short octets like ``0:7:11:14:3c:27`` (SNMP strips leading
        zeros per octet) by zero-padding each octet before joining.
        """
        mac_hex = str(raw).strip()
        if mac_hex.startswith('0x'):
            mac_hex = mac_hex[2:]
        # If colon/hyphen separated, zero-pad each octet then rejoin
        sep = ':' if ':' in mac_hex else ('-' if '-' in mac_hex else None)
        if sep:
            parts = mac_hex.split(sep)
            if len(parts) == 6:
                mac_hex = ''.join(p.zfill(2) for p in parts)
        mac_hex = mac_hex.replace(' ', '').replace(':', '').replace('-', '')
        if len(mac_hex) >= 12:
            return ':'.join(mac_hex[i:i + 2] for i in range(0, 12, 2)).lower()
        return None

    # ── core discovery ──────────────────────────────────────────────────────

    async def discover_modems(
        self, 
        cmts_ip: str, 
        community: str = "public", 
        limit: int = 10000,
        enrich: bool = False,
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
        if enrich and cmts_ip in _enrichment_cache:
            cached = _enrichment_cache[cmts_ip]
            age = time.time() - cached.get('timestamp', 0)
            cached_count = len(cached.get('modems', []))
            cached_req_limit = cached.get('requested_limit') or 0
            cache_sufficient = (
                not limit
                or cached_count >= int(limit)
                or (
                    cached.get('complete') is True
                    and cached_req_limit
                    and cached_req_limit >= int(limit)
                )
            )

            if cached.get('enriched') and age < 7200 and cache_sufficient:
                self.logger.info(f"Returning cached enriched data for {cmts_ip} (age={age:.0f}s)")
                return {
                    'success': True,
                    'modems': cached['modems'],
                    'count': len(cached['modems']),
                    'cmts_ip': cmts_ip,
                    'enriched': True,
                    'enriching': False,
                    'cached': True,
                    'source': cached.get('source', 'snmp-live'),
                    'complete': cached.get('complete', False),
                    'truncated': cached.get('truncated', True),
                }

            if cached.get('enriching') and age < 1800 and cache_sufficient:
                self.logger.info(f"Enrichment in progress for {cmts_ip} (age={age:.0f}s)")
                return {
                    'success': True,
                    'modems': cached.get('modems', []),
                    'count': len(cached.get('modems', [])),
                    'cmts_ip': cmts_ip,
                    'enriched': False,
                    'enriching': True,
                    'cmts_enriched': cached.get('cmts_enriched', False),
                    'cached': True,
                    'source': cached.get('source', 'snmp-live'),
                    'complete': cached.get('complete', False),
                    'truncated': cached.get('truncated', True),
                    'enrich_progress': cached.get('enrich_progress', {'completed': 0, 'total': 0}),
                }

        # ── Tier 2: MySQL inventory (survives restarts) ──────────────
        try:
            from pypnm.api.routes.poller.service import poller_service
            inv_modems = poller_service.list_inventory_modems(
                cmts=cmts_ip, limit=limit,
            )
            if inv_modems:
                # Check freshness: oldest updated_at within 2 hours
                from datetime import datetime, timezone as tz
                timestamps = []
                for m in inv_modems:
                    ts = m.get('updated_at') or m.get('last_seen_at')
                    if ts:
                        try:
                            if isinstance(ts, str):
                                dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                            else:
                                dt = ts
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=tz.utc)
                            timestamps.append(dt)
                        except Exception:
                            pass
                if timestamps:
                    oldest = min(timestamps)
                    age_s = (datetime.now(tz.utc) - oldest).total_seconds()
                else:
                    age_s = float('inf')

                is_fresh = age_s < 7200
                requested_limit = int(limit or 0)
                inventory_covers_request = (
                    requested_limit <= 200
                    or len(inv_modems) >= requested_limit
                )
                sample = inv_modems[:200]
                enriched_count = sum(
                    1 for m in sample
                    if (m.get('vendor') or '').strip().lower() not in ('', 'unknown')
                    and (m.get('software_version') or m.get('model') or '').strip()
                )
                is_enriched = (enriched_count / max(len(sample), 1)) >= 0.40

                if is_fresh and not inventory_covers_request:
                    self.logger.info(
                        f"MySQL inventory for {cmts_ip} has {len(inv_modems)} rows, "
                        f"below requested limit {requested_limit} — falling through to SNMP"
                    )

                # Preview requests can use a smaller fresh snapshot. Larger
                # requests require enough rows to cover the requested footprint.
                if is_fresh and inventory_covers_request and not enrich:
                    self.logger.info(
                        f"Returning {len(inv_modems)} modems for {cmts_ip} "
                        f"from MySQL inventory (age={age_s:.0f}s, non-enrich request)"
                    )
                    return {
                        'success': True,
                        'modems': inv_modems,
                        'count': len(inv_modems),
                        'cmts_ip': cmts_ip,
                        'enriched': False,
                        'enriching': False,
                        'cached': True,
                        'source': 'mysql-inventory',
                    }

                # Enrich requests require both inventory coverage and quality.
                if is_fresh and inventory_covers_request and enrich and is_enriched:
                    self.logger.info(
                        f"Returning {len(inv_modems)} modems for {cmts_ip} "
                        f"from MySQL inventory (age={age_s:.0f}s, enriched)"
                    )
                    # Warm the in-memory cache so next hit is Tier 1
                    _enrichment_cache[cmts_ip] = {
                        'modems': inv_modems,
                        'enriched': True,
                        'enriching': False,
                        'timestamp': time.time(),
                        'requested_limit': limit,
                    }
                    return {
                        'success': True,
                        'modems': inv_modems,
                        'count': len(inv_modems),
                        'cmts_ip': cmts_ip,
                        'enriched': True,
                        'enriching': False,
                        'cached': True,
                        'source': 'mysql-inventory',
                    }

                if is_fresh and inventory_covers_request and enrich and not is_enriched:
                    self.logger.info(
                        f"MySQL inventory for {cmts_ip} is fresh but not enriched "
                        f"({enriched_count}/{len(sample)}) — falling through to SNMP"
                    )
        except Exception as exc:
            self.logger.warning(f"MySQL inventory lookup skipped for {cmts_ip}: {exc}")

        # ── Tier 3: Live SNMP walk (slow, last resort) ───────────────
        try:
            # ── Step 1: Parallel SNMP walks via agent ────────────────────
            walk_oids = [
                OID_D3_MAC, OID_OLD_MAC, OID_OLD_IP, OID_OLD_STATUS,
                OID_OLD_US_CH_IF, OID_SW_REV,
                OID_US_CH_ID, OID_IF_NAME, OID_PARTIAL_SVC,
            ]
            walk_result = await self._send_agent_command(
                'snmp_parallel_walk',
                {'ip': cmts_ip, 'oids': walk_oids,
                 'community': community, 'timeout': 5, 'limit': limit},  # apply limit at walk source for fast preload
                timeout=300,  # 300s server wait — 9 concurrent trees each up to 120s
            )
            if not walk_result.get('success'):
                return {'success': False,
                        'error': f"SNMP walks failed: {walk_result.get('error', 'unknown')}",
                        'modems': [], 'count': 0}

            raw = walk_result.get('results', {})
            legacy_mac_rows = len(raw.get(OID_OLD_MAC, []))
            d3_mac_rows = len(raw.get(OID_D3_MAC, []))
            inventory_truncated = bool(
                limit and (legacy_mac_rows >= int(limit) or d3_mac_rows >= int(limit))
            )
            inventory_meta = {
                'source': 'snmp-live',
                'complete': not inventory_truncated,
                'truncated': inventory_truncated,
                'raw_legacy_mac_count': legacy_mac_rows,
                'raw_d3_mac_count': d3_mac_rows,
            }

            # ── Step 2: Parse raw results into lookup maps ───────────────
            modems = self._correlate_modem_data(raw, limit)
            self.logger.info(f"Discovered {len(modems)} modems from CMTS {cmts_ip}")

            # ── Step 3: Enrichment ───────────────────────────────────────
            if enrich and modems:
                # Guard: don't start a second enrichment if one is already running
                existing = _enrichment_cache.get(cmts_ip, {})
                existing_req_limit = existing.get('requested_limit') or 0
                existing_sufficient = (
                    not limit
                    or len(existing.get('modems', [])) >= int(limit)
                    or (
                        existing.get('complete') is True
                        and existing_req_limit
                        and existing_req_limit >= int(limit)
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
        # docsIf31CmtsCmRegStatusPartialSvcState is BITS { dsPartialSvc(0), usPartialSvc(1) }
        # BITS are encoded as OctetString.  The agent may return:
        #   - an int (0 = no partial, non-zero = partial)
        #   - a hex string like '80' (0x80 = dsPartialSvc bit set)
        #   - a raw UTF-8 decoded string (e.g. '\x00' for no partial, '@' for 0x40)
        partial_svc_map: dict[str, bool] = {}
        for item in raw.get(OID_PARTIAL_SVC, []):
            try:
                idx = self._extract_index(item['oid'], OID_PARTIAL_SVC)
                val = item['value']
                if isinstance(val, int):
                    # INTEGER encoding per DOCS-IF31-MIB PartialServiceType:
                    # 1=other, 2=none, 3=partialSvcDsOnlyImpaired, 4=partialSvcUsOnlyImpaired, 5=partialSvcDsAndUsImpaired
                    # Only 3,4,5 indicate actual partial service
                    partial_svc_map[idx] = val >= 3
                elif isinstance(val, str) and val:
                    # BITS/INTEGER encoded as string — try decimal first, then hex
                    try:
                        int_val = int(val)  # decimal string e.g. "2" (none) or "3" (partial)
                        partial_svc_map[idx] = int_val >= 3
                    except ValueError:
                        try:
                            partial_svc_map[idx] = int(val, 16) != 0  # hex OctetString e.g. "80"
                        except ValueError:
                            # Raw bytes decoded as UTF-8 (e.g. '\x00', '@')
                            partial_svc_map[idx] = any(ord(c) != 0 for c in val)
                else:
                    partial_svc_map[idx] = False
            except (ValueError, TypeError):
                pass

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

            if mac in mac_to_ip:
                modem['ip_address'] = mac_to_ip[mac]

            if mac in mac_to_status:
                sc = mac_to_status[mac]
                modem['status_code'] = sc
                modem['status'] = STATUS_MAP.get(sc, 'unknown')

            if mac in mac_to_firmware:
                modem['firmware'] = mac_to_firmware[mac]

            if d3_index is not None and d3_index in partial_svc_map:
                modem['partial_service'] = partial_svc_map[d3_index]
                # docsIf31CmtsCmRegStatusTable is D3.1-only → modem is DOCSIS 3.1
                modem['docsis_version'] = 'DOCSIS 3.1'
            else:
                modem['docsis_version'] = 'Unknown'

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
        """Enrich modems with cable-mac and OFDMA upstream interfaces from CMTS SNMP walks."""
        if not modems:
            return {'success': True, 'enriched_count': 0, 'total_count': 0}
            
        self.logger.info(f"Enriching cable-mac/upstream for {len(modems)} modems from CMTS {self.cmts_ip}")
        
        # Build index -> modem map
        index_to_modem = {str(m.get('cmts_index')): m for m in modems if m.get('cmts_index')}
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
            idx = str(modem.get('cmts_index'))
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
                # OFDMA upstream ⟹ DOCSIS 3.1 ⟹ OFDM downstream is present
                modem['ofdm_enabled'] = True
                if not modem.get('docsis_version') or modem.get('docsis_version') in ('Unknown', ''):
                    modem['docsis_version'] = 'DOCSIS 3.1'
                if ofdma_ifidx in ofdma_descr_map:
                    descr = ofdma_descr_map[ofdma_ifidx]
                    # Ensure 'ofdma' appears in the interface name so the GUI
                    # badge check (upstream_interface.includes('ofdma')) works
                    # for all vendors (Cisco names like C1/0/6/UB lack it)
                    if 'ofdma' not in descr.lower():
                        descr = f'cable-us-ofdma {descr}'
                    modem['upstream_interface'] = descr
            else:
                modem['ofdma_enabled'] = False
                # Collect SC-QAM US-CH ifIndexes for later resolution
                us_ifidx = modem.get('upstream_ifindex')
                if us_ifidx and us_ifidx in if_name_map:
                    modem['upstream_interface'] = if_name_map[us_ifidx]
                    us_ch_resolved += 1
                # Non-OFDMA: derive ofdm_enabled from docsis_version (sysDescr enrichment)
                docsis = modem.get('docsis_version', '')
                modem['ofdm_enabled'] = '3.1' in docsis or '4.0' in docsis

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