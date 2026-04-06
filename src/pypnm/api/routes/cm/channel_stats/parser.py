# Channel Stats Parser - ALL PARSING LOGIC FROM AGENT
# COPIED 1:1 FROM AGENT

def parse_channel_stats_raw(raw_results: dict, walk_time: float, mac_address: str, modem_ip: str) -> dict:
    """Parse raw SNMP walk results into structured channel stats.
    
    This is a 1:1 copy of parsing logic from agent.
    """
    import time
    from datetime import datetime
    
    start_parse = time.time()
    
    # Table OID mappings (from agent)
    TABLES = {
        'docsIfDownChannelTable': '1.3.6.1.2.1.10.127.1.1.1',
        'docsIfSigQTable': '1.3.6.1.2.1.10.127.1.1.4',
        'docsIf3SignalQualityExtTable': '1.3.6.1.4.1.4491.2.1.20.1.24',
        'docsIf31CmDsOfdmChanTable': '1.3.6.1.4.1.4491.2.1.28.1.9',
        'docsIf31CmDsOfdmChannelPowerTable': '1.3.6.1.4.1.4491.2.1.28.1.11',
        'docsIf31RxChStatusTable': '1.3.6.1.4.1.4491.2.1.28.1.2',
        'docsIf31CmDsOfdmProfileStatsTable': '1.3.6.1.4.1.4491.2.1.28.1.10',
        'docsIfUpChannelTable': '1.3.6.1.2.1.10.127.1.1.2',
        'docsIf3CmStatusUsTable': '1.3.6.1.4.1.4491.2.1.20.1.2',
        'docsIf31CmUsOfdmaChanTable': '1.3.6.1.4.1.4491.2.1.28.1.13',
        'docsIf31CmStatusOfdmaUsTable': '1.3.6.1.4.1.4491.2.1.28.1.12',
        'docsIf31CmUsOfdmaProfileStatsTable': '1.3.6.1.4.1.4491.2.1.28.1.14',
        'docsPnmCmDsOfdmRxMerTable': '1.3.6.1.4.1.4491.2.1.27.1.2.5',
    }
    
    # Column mappings (from agent)
    COLUMN_MAPS = {
        'docsIfDownChannelTable': {
            1: 'channelId', 2: 'frequency', 3: 'width', 
            4: 'modulation', 5: 'interleave', 6: 'power'
        },
        'docsIfSigQTable': {
            2: 'unerroreds', 3: 'correcteds', 4: 'uncorrectables',
            5: 'snr', 6: 'microreflections'
        },
        'docsIf3SignalQualityExtTable': {
            1: 'rxmer'
        },
        'docsIf31CmDsOfdmChanTable': {
            1: 'channelId', 3: 'subcarrierZeroFreq', 4: 'firstActiveSubcarrier',
            5: 'lastActiveSubcarrier', 6: 'numActiveSubcarriers',
            7: 'subcarrierSpacing', 10: 'plcFreq'
        },
        'docsIf31CmDsOfdmChannelPowerTable': {
            2: 'centerFrequency', 3: 'rxPower'
        },
        'docsIf31RxChStatusTable': {
            2: 'ofdmProfiles', 4: 'primaryDsChIfIndex'
        },
        'docsIfUpChannelTable': {
            1: 'channelId', 2: 'frequency', 3: 'width',
            4: 'modulationProfile', 15: 'type'
        },
        'docsIf3CmStatusUsTable': {
            1: 'txPower', 2: 't3Timeouts', 3: 't4Timeouts',
            4: 'rangingAborteds', 5: 'modulationType'
        },
        'docsIf31CmUsOfdmaChanTable': {
            2: 'subcarrierZeroFreq', 3: 'firstActiveSubcarrier',
            4: 'lastActiveSubcarrier', 5: 'numActiveSubcarriers',
            6: 'subcarrierSpacing', 10: 'txPower', 12: 'channelId'
        },
        'docsIf31CmStatusOfdmaUsTable': {
            2: 't3Timeouts', 3: 't4Timeouts', 4: 'rangingAborteds',
            5: 't3Exceededs', 6: 'isMuted', 7: 'rangingStatus'
        },
        'docsIf31CmDsOfdmProfileStatsTable': {
            2: 'totalCodewords', 3: 'correctedCodewords', 4: 'uncorrectableCodewords',
            6: 'inOctets'
        },
        'docsIf31CmUsOfdmaProfileStatsTable': {
            1: 'outOctets'
        },
        'docsPnmCmDsOfdmRxMerTable': {
            # col 3: rxMerMean (in 1/10 dB), col 4: rxMerStdDev
            3: 'rxMerMean', 4: 'rxMerStdDev'
        },
    }
    
    # Fields that need /10 conversion
    TENTH_FIELDS = {'power', 'snr', 'rxmer', 'rxPower', 'txPower'}
    HUNDREDTH_FIELDS = {'rxMerMean', 'rxMerStdDev'}  # docsPnmCmDsOfdmRxMerTable values in 1/100 dB
    QUARTER_FIELDS_BY_TABLE = {
        'docsIf31CmUsOfdmaChanTable': {'txPower'}
    }
    
    def parse_table(table_name: str, base_oid: str, raw_data: list) -> dict:
        """Parse raw SNMP results."""
        columns = COLUMN_MAPS.get(table_name, {})
        parsed = {}
        
        for item in raw_data:
            oid = item.get('oid', '')
            value = item.get('value')
            
            suffix = oid.replace(base_oid + '.', '').lstrip('.')
            parts = suffix.split('.')
            
            if len(parts) >= 2:
                try:
                    if parts[0] == '1':
                        col = int(parts[1])
                        idx = int(parts[2]) if len(parts) > 2 else 0
                    else:
                        col = int(parts[0])
                        idx = int(parts[1]) if len(parts) > 1 else 0
                except (ValueError, IndexError):
                    continue
                
                field_name = columns.get(col)
                if field_name:
                    if idx not in parsed:
                        parsed[idx] = {}
                    
                    quarter_fields = QUARTER_FIELDS_BY_TABLE.get(table_name, set())
                    is_quarter = field_name in quarter_fields
                    is_hundredth = field_name in HUNDREDTH_FIELDS
                    is_tenth = field_name in TENTH_FIELDS and not is_quarter and not is_hundredth

                    if isinstance(value, (int, float)):
                        if is_quarter:
                            value = value / 4.0
                        elif is_hundredth:
                            value = round(value / 100.0, 2)
                        elif is_tenth:
                            value = value / 10.0
                    elif isinstance(value, str):
                        if ' dB' in value or 'TenthdB' in value or 'QuarterdB' in value:
                            import re
                            match = re.search(r'[-+]?\d+\.?\d*', value)
                            if match:
                                value = float(match.group())
                        elif value.lstrip('-').replace('.', '').isdigit():
                            num = float(value)
                            if is_quarter:
                                value = num / 4.0
                            elif is_tenth:
                                value = num / 10.0
                            else:
                                value = int(num) if num == int(num) else num
                    
                    parsed[idx][field_name] = value
        
        return parsed
    
    def parse_profile_stats_table(base_oid: str, raw_data: list) -> dict:
        """Parse profile stats tables with compound index (ifIndex.profileId).
        
        Returns: {ifIndex: {profileId: {field: value, ...}, ...}, ...}
        """
        parsed = {}
        
        for item in raw_data:
            oid = item.get('oid', '')
            value = item.get('value')
            
            suffix = oid.replace(base_oid + '.', '').lstrip('.')
            parts = suffix.split('.')
            
            # Format: 1.{column}.{ifIndex}.{profileId}
            if len(parts) >= 4 and parts[0] == '1':
                try:
                    col = int(parts[1])
                    if_index = int(parts[2])
                    profile_id = int(parts[3])
                except (ValueError, IndexError):
                    continue
                
                if if_index not in parsed:
                    parsed[if_index] = {}
                if profile_id not in parsed[if_index]:
                    parsed[if_index][profile_id] = {}
                
                # Convert value to int if it's a number
                if isinstance(value, str) and value.isdigit():
                    value = int(value)
                
                parsed[if_index][profile_id][col] = value
        
        return parsed
    
    # Parse all tables
    tables_data = {}
    profile_stats_tables = {'docsIf31CmDsOfdmProfileStatsTable', 'docsIf31CmUsOfdmaProfileStatsTable'}
    
    for table_name, base_oid in TABLES.items():
        raw_data = raw_results.get(base_oid, [])
        if table_name in profile_stats_tables:
            # These tables have compound indexes (ifIndex.profileId)
            tables_data[table_name] = parse_profile_stats_table(base_oid, raw_data)
        else:
            tables_data[table_name] = parse_table(table_name, base_oid, raw_data)
    
    # Build response
    ds_down = tables_data.get('docsIfDownChannelTable', {})
    ds_sigq = tables_data.get('docsIfSigQTable', {})
    ds_rxmer = tables_data.get('docsIf3SignalQualityExtTable', {})
    ds_ofdm = tables_data.get('docsIf31CmDsOfdmChanTable', {})
    ds_ofdm_power = tables_data.get('docsIf31CmDsOfdmChannelPowerTable', {})
    ds_rx_status = tables_data.get('docsIf31RxChStatusTable', {})
    ds_ofdm_profile_stats = tables_data.get('docsIf31CmDsOfdmProfileStatsTable', {})
    ds_ofdm_rxmer = tables_data.get('docsPnmCmDsOfdmRxMerTable', {})
    us_up = tables_data.get('docsIfUpChannelTable', {})
    us_status = tables_data.get('docsIf3CmStatusUsTable', {})
    us_ofdma = tables_data.get('docsIf31CmUsOfdmaChanTable', {})
    us_ofdma_status = tables_data.get('docsIf31CmStatusOfdmaUsTable', {})
    us_ofdma_profile_stats = tables_data.get('docsIf31CmUsOfdmaProfileStatsTable', {})
    
    # Build SC-QAM downstream
    ds_scqam_channels = []
    for idx in sorted(ds_down.keys()):
        down = ds_down.get(idx, {})
        sigq = ds_sigq.get(idx, {})
        rxmer_data = ds_rxmer.get(idx, {})
        
        channel_id = down.get('channelId')
        if not channel_id:
            continue
        
        freq = down.get('frequency')
        ds_scqam_channels.append({
            'index': idx,
            'channel_id': channel_id,
            'frequency': freq,
            'frequency_mhz': freq / 1_000_000 if freq else None,
            'power': down.get('power'),
            'modulation': down.get('modulation'),
            'snr': sigq.get('snr'),
            'rxmer': rxmer_data.get('rxmer'),
            'unerroreds': sigq.get('unerroreds'),
            'correcteds': sigq.get('correcteds'),
            'uncorrectables': sigq.get('uncorrectables'),
        })
    
    # Build OFDM downstream
    ds_ofdm_channels = []
    # docsIf31CmDsOfdmChanTable can be CMTS-wide on some platforms.
    # docsIf31RxChStatusTable is modem-scoped; use those indices when present.
    ds_ofdm_valid_idx = set(ds_rx_status.keys()) if ds_rx_status else None
    for idx in sorted(ds_ofdm.keys()):
        if ds_ofdm_valid_idx is not None and idx not in ds_ofdm_valid_idx:
            continue
        ofdm = ds_ofdm.get(idx, {})
        channel_id = ofdm.get('channelId')
        if not channel_id:
            continue
        
        plc_freq = ofdm.get('plcFreq')
        num_sc = ofdm.get('numActiveSubcarriers', 0)
        sc_spacing = ofdm.get('subcarrierSpacing', 2)
        sc_hz = 25000 if sc_spacing == 1 else 50000
        bandwidth = num_sc * sc_hz if num_sc else 0
        
        power_data = ds_ofdm_power.get(idx, {})
        rx_status = ds_rx_status.get(idx, {})
        rxmer_data = ds_ofdm_rxmer.get(idx, {})
        # mer: docsPnmCmDsOfdmRxMerTable col 3 = rxMerMean (already /10 by TENTH_FIELDS)
        # fallback to docsIf31CmDsOfdmChannelPowerRxMer if present
        ofdm_mer = rxmer_data.get('rxMerMean') or power_data.get('rxMer')
        
        # Parse OFDM profiles from BITS value
        profiles = []
        current_profile = None
        profile_raw = rx_status.get('ofdmProfiles')
        if profile_raw:
            # profile_raw can be bytes, hex string like 'F0 00', or list [0xF0, 0x00]
            try:
                if isinstance(profile_raw, bytes):
                    profile_bytes = profile_raw
                elif isinstance(profile_raw, str):
                    # Handle 'F0 00' or 'f0:00' or 'F000' formats
                    profile_raw = profile_raw.replace(':', ' ').replace('-', ' ')
                    profile_bytes = bytes.fromhex(profile_raw.replace(' ', ''))
                elif isinstance(profile_raw, (list, tuple)):
                    profile_bytes = bytes(profile_raw)
                else:
                    profile_bytes = b''
                
                # Parse BITS - each bit corresponds to a profile (0-15)
                if len(profile_bytes) >= 2:
                    for byte_idx, byte_val in enumerate(profile_bytes[:2]):
                        for bit in range(8):
                            if byte_val & (0x80 >> bit):
                                profile_num = byte_idx * 8 + bit
                                profiles.append(profile_num)
                
                # Current profile business logic is resolved from the CMTS
                # registration list (DsProfileIdList) in router.py.
            except (ValueError, TypeError):
                pass
        
        ofdm_ch = {
            'index': idx,
            'channel_id': channel_id,
            'plc_freq': plc_freq,
            'plc_freq_mhz': plc_freq / 1_000_000 if plc_freq else None,
            'power': power_data.get('rxPower'),
            'mer': ofdm_mer,
            'num_subcarriers': num_sc,
            'subcarrier_spacing_khz': sc_hz / 1000,
            'bandwidth_mhz': bandwidth / 1_000_000 if bandwidth else None,
            'profiles': profiles,
            'current_profile': current_profile,
        }
        
        # Add profile stats (codewords per profile) if available
        # ds_ofdm_profile_stats format: {ifIndex: {profileId: {col: value}}}
        if idx in ds_ofdm_profile_stats:
            profile_stats = []
            for profile_id, stats in sorted(ds_ofdm_profile_stats[idx].items()):
                if profile_id != 255:  # Skip aggregate profile
                    profile_stats.append({
                        'profile_id': profile_id,
                        'total_codewords': stats.get(3, 0),  # column 3: totalCodewords
                        'corrected_codewords': stats.get(4, 0),  # column 4: correctedCodewords  
                        'uncorrectable_codewords': stats.get(5, 0),  # column 5: uncorrectableCodewords
                    })
            if profile_stats:
                ofdm_ch['profile_stats'] = profile_stats
        
        ds_ofdm_channels.append(ofdm_ch)
    
    # Build ATDMA upstream
    us_atdma_channels = []
    # docsIfUpChannelTable can contain all CMTS channels on some platforms.
    # docsIf3CmStatusUsTable is modem-scoped, so use its indices as the modem filter.
    us_atdma_valid_idx = set(us_status.keys()) if us_status else None
    for idx in sorted(us_up.keys()):
        if us_atdma_valid_idx is not None and idx not in us_atdma_valid_idx:
            continue
        up = us_up.get(idx, {})
        status = us_status.get(idx, {})
        
        channel_id = up.get('channelId')
        freq = up.get('frequency')
        if not channel_id or not freq:
            continue
        
        ch_type = up.get('type', 0)
        type_name = {1: 'TDMA', 2: 'ATDMA', 3: 'SCDMA'}.get(ch_type, str(ch_type))
        width = up.get('width')
        
        us_atdma_channels.append({
            'index': idx,
            'channel_id': channel_id,
            'frequency': freq,
            'frequency_mhz': freq / 1_000_000 if freq else None,
            'width': width,
            'width_mhz': width / 1_000_000 if width else None,
            'type': type_name,
            'tx_power': status.get('txPower'),
            't3_timeouts': status.get('t3Timeouts'),
            't4_timeouts': status.get('t4Timeouts'),
            'modulation_type': status.get('modulationType'),
        })
    
    # Build OFDMA upstream
    us_ofdma_channels = []
    # Same issue for OFDMA: channel table may be CMTS-wide while
    # docsIf31CmStatusOfdmaUsTable is modem-scoped.
    us_ofdma_valid_idx = set(us_ofdma_status.keys()) if us_ofdma_status else None
    for idx in sorted(us_ofdma.keys()):
        if us_ofdma_valid_idx is not None and idx not in us_ofdma_valid_idx:
            continue
        ofdma = us_ofdma.get(idx, {})
        channel_id = ofdma.get('channelId')
        if not channel_id:
            continue
        
        zero_freq = ofdma.get('subcarrierZeroFreq')
        num_sc = ofdma.get('numActiveSubcarriers', 0)
        sc_spacing = ofdma.get('subcarrierSpacing', 2)
        sc_hz = 25000 if sc_spacing == 1 else 50000
        bandwidth = num_sc * sc_hz if num_sc else 0
        
        status_data = us_ofdma_status.get(idx, {})
        
        ofdma_ch = {
            'index': idx,
            'channel_id': channel_id,
            'zero_freq': zero_freq,
            'zero_freq_mhz': zero_freq / 1_000_000 if zero_freq else None,
            'tx_power': ofdma.get('txPower'),
            't3_timeouts': status_data.get('t3Timeouts'),
            't4_timeouts': status_data.get('t4Timeouts'),
            'num_subcarriers': num_sc,
            'subcarrier_spacing_khz': sc_hz / 1000,
            'bandwidth_mhz': bandwidth / 1_000_000 if bandwidth else None,
        }
        
        # Add IUC stats if available
        # us_ofdma_profile_stats format: {ifIndex: {iucId: {col: value}}}
        if idx in us_ofdma_profile_stats:
            iuc_stats = []
            for iuc_id, stats in sorted(us_ofdma_profile_stats[idx].items()):
                out_octets = stats.get(1, 0)  # column 1: outOctets
                if out_octets > 0:  # Only include IUCs with data
                    iuc_stats.append({
                        'iuc': iuc_id,
                        'out_octets': out_octets,
                    })
            if iuc_stats:
                ofdma_ch['iuc_stats'] = iuc_stats
                # List active IUCs
                ofdma_ch['active_iucs'] = [s['iuc'] for s in iuc_stats]
        
        us_ofdma_channels.append(ofdma_ch)
    
    parse_time = time.time() - start_parse
    
    return {
        'success': True,
        'status': 0,
        'mac_address': mac_address,
        'modem_ip': modem_ip,
        'timestamp': datetime.now().isoformat(),
        'timing': {
            'walk_time': round(walk_time, 2),
            'parse_time': round(parse_time, 2),
            'total_time': round(walk_time + parse_time, 2),
        },
        'downstream': {
            'scqam': {
                'channels': ds_scqam_channels,
                'count': len(ds_scqam_channels),
            },
            'ofdm': {
                'channels': ds_ofdm_channels,
                'count': len(ds_ofdm_channels),
            },
        },
        'upstream': {
            'atdma': {
                'channels': us_atdma_channels,
                'count': len(us_atdma_channels),
            },
            'ofdma': {
                'channels': us_ofdma_channels,
                'count': len(us_ofdma_channels),
            },
        },
    }


# ── Partial channel reason code descriptions ──────────────────────────────────
_PARTIAL_REASON = {
    0:  'No partial service',
    1:  'T4 timeout',
    2:  'T3 timeout',
    3:  'Ranging abort',
    4:  'Invalid configuration',
    5:  'MAC error',
    6:  'Ranging failure',
    7:  'DS signal degraded',
    8:  'US signal degraded',
    9:  'Service flow removed',
    10: 'Modem requested',
    11: 'CMTS initiated',
}

# Main modulation codes (docsIf31CmtsDsOfdmSubcarrierStatusMainModulation)
_MODULATION_CODE = {
    0: 'unknown', 1: 'zeroValued', 2: 'qam16', 3: 'qam32', 4: 'qam64',
    5: 'qam128', 6: 'qam256', 7: 'qam512', 8: 'qam1024', 9: 'qam2048',
    10: 'qam4096', 11: 'qam8192', 12: 'qam16384',
}


def _extract_result_entries(task_result) -> list:
    """Safely pull the results list from an agent task response."""
    if not task_result:
        return []
    r = task_result.get('result', {})
    if not r or not r.get('success'):
        return []
    return r.get('results', []) or []


def parse_ofdm_stats_raw(
    cm_index,
    partial_reason_result,
    us_iuc_stats_result,
    ds_ofdm_speed_result,
    ds_subcarrier_result,
    cm_ds_ofdm_channels: list,
    cm_us_ofdma_channels: list | None = None,
    ifname_result=None,
    cmts_profile_result=None,
) -> dict:
    """
    Parse CMTS-side OFDM/OFDMA statistics into a structured dict for the GUI.

    Returns a dict with:
      ds_profiles   - per DS-channel, per-profile: codewords (CM) + speed (CMTS) + partial reason
      us_iuc_stats  - per US-OFDMA channel ifIndex, per IUC: total/corrected/unreliable codewords
      ds_subcarrier - per DS-channel ifIndex, per range: main modulation
    """

    # ── 0. Build ifIndex → ifName map from CMTS ifXTable walk ──
    ifname_base = '1.3.6.1.2.1.31.1.1.1.1'
    ifname_map = {}  # {ifindex: name}
    for e in _extract_result_entries(ifname_result):
        oid = e.get('oid', '')
        if oid.startswith(ifname_base + '.'):
            try:
                ifidx = int(oid[len(ifname_base) + 1:])
                name = e.get('value', '')
                if name:
                    ifname_map[ifidx] = str(name)
            except (ValueError, TypeError):
                pass

    # ── 0b. Resolve valid ifIndices for this modem from scoped CMTS walks ──
    # US OFDMA: from cmts_profile_result (walked as .5.1.1.{cm_index}) —
    #   OID suffix: {cm_index}.{ofdma_ifindex}.{iuc_id}
    prof_base = '1.3.6.1.4.1.4491.2.1.28.1.5.1.1'
    valid_us_ifindices: set = set()
    for e in _extract_result_entries(cmts_profile_result):
        oid = e.get('oid', '')
        if oid.startswith(prof_base + '.'):
            parts = oid[len(prof_base) + 1:].split('.')
            if len(parts) == 3:
                try:
                    entry_cm_index = int(parts[0])
                    if cm_index is not None and entry_cm_index == cm_index:
                        valid_us_ifindices.add(int(parts[1]))
                except (ValueError, TypeError):
                    pass

    # DS OFDM: from partial_reason_result (walked as .7.1.1.{cm_index}) —
    #   OID suffix after col: {cm_index}.{ds_ifindex}.{profile_id}
    _partial_base = '1.3.6.1.4.1.4491.2.1.28.1.7.1'
    valid_ds_ifindices: set = set()
    for e in _extract_result_entries(partial_reason_result):
        oid = e.get('oid', '')
        for col in ('1', '3'):
            prefix = f'{_partial_base}.{col}.'
            if oid.startswith(prefix):
                parts = oid[len(prefix):].split('.')
                if len(parts) == 3:
                    try:
                        entry_cm_index = int(parts[0])
                        if cm_index is not None and entry_cm_index == cm_index:
                            valid_ds_ifindices.add(int(parts[1]))
                    except (ValueError, TypeError):
                        pass

    # ── 1. DS profile stats — already parsed from CM walk (in cm_ds_ofdm_channels) ──
    ds_profiles = []
    for ch in cm_ds_ofdm_channels:
        entry = {
            'channel_id': ch.get('channel_id'),
            'plc_freq_mhz': ch.get('plc_freq_mhz'),
            'profiles': [],
        }
        for ps in ch.get('profile_stats', []):
            total     = ps.get('total_codewords', 0)
            corrected = ps.get('corrected_codewords', 0)
            uncorr    = ps.get('uncorrectable_codewords', 0)
            corr_pct   = round(corrected / total * 100, 4) if total else 0
            uncorr_pct = round(uncorr / total * 100, 6) if total else 0
            entry['profiles'].append({
                'profile_id':             ps.get('profile_id'),
                'total_codewords':        total,
                'corrected':              corrected,
                'corrected_pct':          corr_pct,
                'uncorrectable':          uncorr,
                'uncorrectable_pct':      uncorr_pct,
                'full_channel_speed_bps': None,
                'partial_reason_code':    None,
                'partial_reason_text':    None,
                'last_partial_reason_code': None,
                'last_partial_reason_text': None,
            })
        ds_profiles.append(entry)

    # ── 2. Inject CMTS DS OFDM profile full channel speed ──
    #    OID: 1.3.6.1.4.1.4491.2.1.28.1.20.1.3.{ifIndex}.{profileId}
    speed_base = '1.3.6.1.4.1.4491.2.1.28.1.20.1.3'
    speed_map = {}  # {ifIndex: {profileId: speed_bps}}
    for e in _extract_result_entries(ds_ofdm_speed_result):
        oid = e.get('oid', '')
        if oid.startswith(speed_base + '.'):
            parts = oid[len(speed_base) + 1:].split('.')
            if len(parts) == 2:
                try:
                    speed_map.setdefault(int(parts[0]), {})[int(parts[1])] = int(e.get('value') or 0)
                except (ValueError, TypeError):
                    pass

    # Constrain to only the DS ifIndices this modem is registered on (from partial_reason
    # scoped walk); fall back to positional limit by CM channel count if unknown.
    n_ds_ch = len(cm_ds_ofdm_channels)
    all_speed_ifindices = sorted(speed_map.keys())
    if valid_ds_ifindices:
        sorted_speed_ifindices = sorted(valid_ds_ifindices & speed_map.keys())
    else:
        sorted_speed_ifindices = all_speed_ifindices[:n_ds_ch] if n_ds_ch else all_speed_ifindices
    for i, ch_entry in enumerate(sorted(ds_profiles, key=lambda c: c.get('channel_id') or 0)):
        if i < len(sorted_speed_ifindices):
            ifidx = sorted_speed_ifindices[i]
            for prof in ch_entry['profiles']:
                pid = prof['profile_id']
                if pid in speed_map.get(ifidx, {}):
                    prof['full_channel_speed_bps'] = speed_map[ifidx][pid]

    # ── 3. Inject CMTS partial channel reason codes (scoped to cm_index) ──
    #    OID: 1.3.6.1.4.1.4491.2.1.28.1.7.1.{col}.{cm_index}.{ifIndex}.{profileId}
    #    col 1 = PartialChanReasonCode, col 3 = LastPartialChanReasonCode
    partial_base = '1.3.6.1.4.1.4491.2.1.28.1.7.1'
    partial_map      = {}  # {ifIndex: {profileId: code}}
    last_partial_map = {}
    for e in _extract_result_entries(partial_reason_result):
        oid = e.get('oid', '')
        for col, target_map in [('1', partial_map), ('3', last_partial_map)]:
            prefix = f'{partial_base}.{col}.'
            if oid.startswith(prefix):
                parts = oid[len(prefix):].split('.')
                # parts: [cm_index, ifIndex, profileId]
                if len(parts) == 3:
                    try:
                        entry_cm_index = int(parts[0])
                        # Filter to this modem's rows when cm_index is known
                        if cm_index is not None and entry_cm_index != cm_index:
                            continue
                        target_map.setdefault(int(parts[1]), {})[int(parts[2])] = int(e.get('value') or 0)
                    except (ValueError, TypeError):
                        pass

    for i, ch_entry in enumerate(sorted(ds_profiles, key=lambda c: c.get('channel_id') or 0)):
        if i < len(sorted_speed_ifindices):
            ifidx = sorted_speed_ifindices[i]
            for prof in ch_entry['profiles']:
                pid = prof['profile_id']
                code = partial_map.get(ifidx, {}).get(pid)
                if code is not None:
                    prof['partial_reason_code'] = code
                    prof['partial_reason_text'] = _PARTIAL_REASON.get(code, f'code {code}')
                last_code = last_partial_map.get(ifidx, {}).get(pid)
                if last_code is not None:
                    prof['last_partial_reason_code'] = last_code
                    prof['last_partial_reason_text'] = _PARTIAL_REASON.get(last_code, f'code {last_code}')

    # ── 4. US OFDMA IUC data stats ──
    #    OID: 1.3.6.1.4.1.4491.2.1.28.1.24.1.{col}.{ifIndex}.{iuc}
    #    col 4=total, 5=corrected, 6=unreliable
    iuc_base = '1.3.6.1.4.1.4491.2.1.28.1.24.1'
    col_field = {'4': 'total', '5': 'corrected', '6': 'unreliable'}
    iuc_stats_map = {}  # {ifIndex: {iuc: {field: val}}}
    for e in _extract_result_entries(us_iuc_stats_result):
        oid = e.get('oid', '')
        for col, field in col_field.items():
            prefix = f'{iuc_base}.{col}.'
            if oid.startswith(prefix):
                parts = oid[len(prefix):].split('.')
                if len(parts) == 2:
                    try:
                        iuc_stats_map.setdefault(int(parts[0]), {}).setdefault(int(parts[1]), {})[field] = int(e.get('value') or 0)
                    except (ValueError, TypeError):
                        pass

    us_iuc_channels = []
    n_us_ch = len(cm_us_ofdma_channels or [])
    all_us_ifindices = sorted(iuc_stats_map.keys())
    if valid_us_ifindices:
        selected_us_ifindices = sorted(valid_us_ifindices & iuc_stats_map.keys())
    else:
        selected_us_ifindices = all_us_ifindices[:n_us_ch] if n_us_ch else all_us_ifindices
    for ifidx in selected_us_ifindices:
        iucs = []
        for iuc in sorted(iuc_stats_map[ifidx].keys()):
            row = iuc_stats_map[ifidx][iuc]
            total   = row.get('total', 0)
            corr    = row.get('corrected', 0)
            unrelia = row.get('unreliable', 0)
            iucs.append({
                'iuc':             iuc,
                'total':           total,
                'corrected':       corr,
                'corrected_pct':   round(corr / total * 100, 4) if total else 0,
                'unreliable':      unrelia,
                'unreliable_pct':  round(unrelia / total * 100, 6) if total else 0,
            })
        us_iuc_channels.append({
            'ifindex':  ifidx,
            'ifname':   ifname_map.get(ifidx),
            'iuc_stats': iucs,
        })

    # ── 5. DS subcarrier status (main modulation per range) ──
    #    OID: 1.3.6.1.4.1.4491.2.1.28.1.21.1.3.{ifIndex}.{rangeIndex}
    subcarrier_base = '1.3.6.1.4.1.4491.2.1.28.1.21.1.3'
    subcarrier_map = {}  # {ifIndex: {rangeIndex: code}}
    for e in _extract_result_entries(ds_subcarrier_result):
        oid = e.get('oid', '')
        if oid.startswith(subcarrier_base + '.'):
            parts = oid[len(subcarrier_base) + 1:].split('.')
            if len(parts) == 2:
                try:
                    subcarrier_map.setdefault(int(parts[0]), {})[int(parts[1])] = int(e.get('value') or 0)
                except (ValueError, TypeError):
                    pass

    ds_subcarrier = []
    all_ds_ifindices = sorted(subcarrier_map.keys())
    if valid_ds_ifindices:
        selected_ds_ifindices = sorted(valid_ds_ifindices & subcarrier_map.keys())
    else:
        selected_ds_ifindices = all_ds_ifindices[:n_ds_ch] if n_ds_ch else all_ds_ifindices
    for ifidx in selected_ds_ifindices:
        ranges = []
        for ridx in sorted(subcarrier_map[ifidx].keys()):
            code = subcarrier_map[ifidx][ridx]
            ranges.append({
                'range_index':     ridx,
                'modulation_code': code,
                'modulation':      _MODULATION_CODE.get(code, f'code {code}'),
            })
        ds_subcarrier.append({
            'ifindex': ifidx,
            'ifname':  ifname_map.get(ifidx),
            'ranges':  ranges,
        })

    return {
        'ds_profiles':   ds_profiles,
        'us_iuc_stats':  us_iuc_channels,
        'ds_subcarrier': ds_subcarrier,
    }
