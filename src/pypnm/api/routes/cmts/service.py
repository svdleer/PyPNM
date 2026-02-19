# SPDX-License-Identifier: Apache-2.0
# CMTS Modem Discovery Service

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Any

from pypnm.api.agent.manager import get_agent_manager


# ── In-memory enrichment cache ──────────────────────────────────────────────
# Keyed by cmts_ip → {modems, enriched, enriching, timestamp}
_enrichment_cache: Dict[str, Dict[str, Any]] = {}
_enrichment_lock = asyncio.Lock()

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
        """Send command to agent via agent manager."""
        agent_manager = get_agent_manager()
        if not agent_manager:
            raise Exception("Agent manager not available")
        
        agents = agent_manager.get_available_agents()
        if not agents:
            raise Exception("No agents available")
        
        agent_id = agents[0]['agent_id']
        
        task_id = await agent_manager.send_task(
            agent_id=agent_id,
            command=command,
            params=params,
            timeout=timeout
        )
        
        result = await agent_manager.wait_for_task_async(task_id, timeout=timeout)
        if result and 'result' in result:
            return result['result']
        return {}

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
        into ``aa:bb:cc:dd:ee:ff`` format.  Returns *None* on failure."""
        mac_hex = str(raw)
        if mac_hex.startswith('0x'):
            mac_hex = mac_hex[2:]
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
        modem_community: str = "private"
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

        # ── Check cache first ────────────────────────────────────────
        if enrich and cmts_ip in _enrichment_cache:
            cached = _enrichment_cache[cmts_ip]
            age = time.time() - cached.get('timestamp', 0)
            
            if cached.get('enriched') and age < 300:  # enriched data < 5 min old
                self.logger.info(f"Returning cached enriched data for {cmts_ip} (age={age:.0f}s)")
                return {
                    'success': True,
                    'modems': cached['modems'],
                    'count': len(cached['modems']),
                    'cmts_ip': cmts_ip,
                    'enriched': True,
                    'enriching': False,
                    'cached': True,
                }
            
            if cached.get('enriching') and age < 120:  # enrichment still in progress
                # Return whatever we have so far (base modems) with enriching=True
                self.logger.info(f"Enrichment in progress for {cmts_ip} (age={age:.0f}s)")
                return {
                    'success': True,
                    'modems': cached.get('modems', []),
                    'count': len(cached.get('modems', [])),
                    'cmts_ip': cmts_ip,
                    'enriched': False,
                    'enriching': True,
                    'cached': True,
                }
        
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
                 'community': community, 'timeout': 30},
                timeout=120,
            )
            if not walk_result.get('success'):
                return {'success': False,
                        'error': f"SNMP walks failed: {walk_result.get('error', 'unknown')}",
                        'modems': [], 'count': 0}

            raw = walk_result.get('results', {})

            # ── Step 2: Parse raw results into lookup maps ───────────────
            modems = self._correlate_modem_data(raw, limit)
            self.logger.info(f"Discovered {len(modems)} modems from CMTS {cmts_ip}")

            # ── Step 3: Enrichment ───────────────────────────────────────
            if enrich and modems:
                # Store base modems in cache and kick off background enrichment
                _enrichment_cache[cmts_ip] = {
                    'modems': modems,
                    'enriched': False,
                    'enriching': True,
                    'timestamp': time.time(),
                }
                
                # Fire-and-forget background enrichment
                asyncio.create_task(
                    self._background_enrich(cmts_ip, modems, modem_community)
                )
                
                self.logger.info(f"Returning {len(modems)} modems immediately, enrichment started in background")
                return {
                    'success': True,
                    'modems': modems,
                    'count': len(modems),
                    'cmts_ip': cmts_ip,
                    'enriched': False,
                    'enriching': True,
                }

            return {
                'success': True,
                'modems': modems,
                'count': len(modems),
                'cmts_ip': cmts_ip,
                'enriched': False,
                'enriching': False,
            }
                
        except Exception as e:
            self.logger.exception(f"Error discovering modems from CMTS {cmts_ip}")
            return {'success': False, 'error': str(e),
                    'modems': [], 'count': 0}

    async def _background_enrich(self, cmts_ip: str, modems: list, modem_community: str):
        """Run enrichment in background and update the cache when done."""
        global _enrichment_cache
        try:
            self.logger.info(f"Background enrichment started for {cmts_ip} ({len(modems)} modems)")
            enriched_modems = await self._enrich_modems_direct(modems, modem_community)
            await self._enrich_cmts_interfaces(enriched_modems)
            
            _enrichment_cache[cmts_ip] = {
                'modems': enriched_modems,
                'enriched': True,
                'enriching': False,
                'timestamp': time.time(),
            }
            enriched_count = sum(1 for m in enriched_modems if m.get('model'))
            self.logger.info(f"Background enrichment complete for {cmts_ip}: {enriched_count}/{len(modems)} enriched")
        except Exception as e:
            self.logger.exception(f"Background enrichment failed for {cmts_ip}: {e}")
            # Mark as done (failed) so we don't block forever
            if cmts_ip in _enrichment_cache:
                _enrichment_cache[cmts_ip]['enriching'] = False

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
                    # INTEGER encoding: 0 = no partial service
                    partial_svc_map[idx] = val != 0
                elif isinstance(val, str) and val:
                    # BITS encoded as string — check if any byte is non-zero
                    try:
                        partial_svc_map[idx] = int(val, 16) != 0
                    except ValueError:
                        # Raw bytes that decoded as UTF-8 (e.g. '\x00', '@')
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

        # ---- build modem list ----
        modems: list[dict] = []
        for index, mac in mac_map.items():
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

            # DOCSIS version → filled during per-modem enrichment
            modem['docsis_version'] = 'Unknown'

            if index in partial_svc_map:
                modem['partial_service'] = partial_svc_map[index]

            # Upstream interface resolution
            us_ifindex = mac_to_us_ch_if.get(mac) or us_ch_map.get(index)
            if us_ifindex:
                modem['upstream_ifindex'] = us_ifindex
                modem['upstream_interface'] = if_name_map.get(us_ifindex, f'US-CH {us_ifindex}')
            else:
                modem['upstream_interface'] = 'SC-QAM'

            if index in us_ch_map:
                modem['upstream_channel_id'] = us_ch_map[index]

            # Skip modems that are offline: status=other(1) with no IP assigned.
            # Casa CCAP and some other vendors report status=1 for all unreachable
            # modems and never populate their IP — these are not worth showing.
            if modem.get('status_code') == 1 and modem.get('ip_address', '0.0.0.0') in ('0.0.0.0', '', None):
                continue

            modems.append(modem)
            if limit and len(modems) >= limit:
                break

        return modems

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
        
        # Run all bulk walks via agent
        try:
            md_if_result = await self._send_agent_command('snmp_walk', {'target_ip': self.cmts_ip, 'oid': OID_MD_IF_INDEX, 'community': self.community}, 30)
            if_name_result = await self._send_agent_command('snmp_walk', {'target_ip': self.cmts_ip, 'oid': OID_IF_NAME, 'community': self.community}, 30) 
            ofdma_result = await self._send_agent_command('snmp_walk', {'target_ip': self.cmts_ip, 'oid': OID_CM_OFDMA_TIMING, 'community': self.community}, 30)
        except Exception as e:
            self.logger.exception(f"SNMP walks failed: {e}")
            return {'success': False, 'enriched_count': 0, 'total_count': len(modems)}
        
        # Parse results into (index, value) tuples like agent does
        def parse_snmp_results(result, base_oid):
            parsed = []
            if result and result.get('success'):
                for item in result.get('results', []):
                    oid = item.get('oid', '')
                    value = item.get('value')
                    if oid.startswith(base_oid):
                        index = oid[len(base_oid)+1:]  # Remove base OID and dot
                        parsed.append((index, value))
            return parsed
        
        md_if_results = parse_snmp_results(md_if_result, OID_MD_IF_INDEX)
        if_name_results = parse_snmp_results(if_name_result, OID_IF_NAME)
        ofdma_results = parse_snmp_results(ofdma_result, OID_CM_OFDMA_TIMING)
        
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
        
        self.logger.info(f"Resolved {len(md_if_map)} MD-IF-INDEX, {len(if_name_map)} interface names")
        
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
                if_descr_result = await self._send_agent_command('snmp_walk', {'target_ip': self.cmts_ip, 'oid': OID_IF_DESCR, 'community': self.community}, 30)
                if_descr_results = parse_snmp_results(if_descr_result, OID_IF_DESCR)
                for index, value in if_descr_results:
                    try:
                        ifidx = int(index)
                        if ifidx in ofdma_ifindexes:
                            descr = str(value)
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
            
            # Add cable_mac from MD-IF-INDEX -> ifName
            if idx in md_if_map:
                md_if_idx = md_if_map[idx]
                if md_if_idx in if_name_map:
                    modem['cable_mac'] = if_name_map[md_if_idx]
                    enriched_count += 1
            
            # Add OFDMA upstream interface if discovered 
            if idx in ofdma_if_map:
                ofdma_ifidx = ofdma_if_map[idx]
                modem['ofdma_ifindex'] = ofdma_ifidx
                modem['ofdma_enabled'] = True
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
            
            # Add OFDM flag (assume DOCSIS 3.1+ has OFDM downstream)
            docsis = modem.get('docsis_version', '')
            modem['ofdm_enabled'] = '3.1' in docsis or '4.0' in docsis
        
        self.logger.info(f"Enriched {enriched_count} modems with cable-mac, {len(ofdma_if_map)} with OFDMA")
        
        return {
            'success': True,
            'enriched_count': len([m for m in modems if m.get('model') or m.get('cable_mac')]),
            'total_count': len(modems)
        }

    async def _enrich_modems_direct(self, modems: list, modem_community: str = 'private') -> list:
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
        online_modems = [m for m in modems
                         if m.get('ip_address') and m.get('ip_address') != 'N/A'
                         and m.get('ip_address') != '0.0.0.0'
                         and m.get('status') in online_statuses][:200]

        self.logger.info(f"Direct enrichment: {len(online_modems)} modems (parallel, max_concurrent=50)")
        if not online_modems:
            return modems

        enriched_count = 0

        async def _enrich_one(modem: dict):
            """Enrich a single modem using snmp_bulk_get (1 agent call for 3 OIDs)."""
            nonlocal enriched_count
            ip = modem.get('ip_address')
            try:
                result = await self._send_agent_command(
                    command='snmp_bulk_get',
                    params={
                        'target_ip': ip,
                        'oids': ALL_OIDS,
                        'community': modem_community,
                        'timeout': 5,
                        'max_concurrent': 3,
                    },
                    timeout=30,
                )
                if not result or not result.get('success'):
                    return

                oid_results = result.get('results', {})

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
                self.logger.debug(f"Failed to enrich modem {ip}: {e}")

        # ── Send tasks with bounded concurrency ─────────────────────────
        # Limit to 15 in-flight at once: agent processes them quickly enough
        # that later tasks don't time out waiting in the queue.
        MAX_CONCURRENT = 15
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def _enrich_one_sem(modem: dict):
            async with sem:
                await _enrich_one(modem)

        await asyncio.gather(*[_enrich_one_sem(m) for m in online_modems])

        self.logger.info(f"Direct enrichment done: {enriched_count}/{len(online_modems)} modems enriched")

        # Merge enriched modems back
        enriched_map = {m['mac_address']: m for m in online_modems}
        for modem in modems:
            if modem['mac_address'] in enriched_map:
                modem.update(enriched_map[modem['mac_address']])

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