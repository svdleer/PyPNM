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
    }
    
    # Fields that need /10 conversion
    TENTH_FIELDS = {'power', 'snr', 'rxmer', 'mer', 'rxPower', 'rxMer', 'txPower'}
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
                    is_tenth = field_name in TENTH_FIELDS and not is_quarter
                    
                    if isinstance(value, (int, float)):
                        if is_quarter:
                            value = value / 4.0
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
    for idx in sorted(ds_ofdm.keys()):
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
                
                # Current profile is typically the lowest numbered active profile
                if profiles:
                    current_profile = min(profiles)
            except (ValueError, TypeError):
                pass
        
        ofdm_ch = {
            'index': idx,
            'channel_id': channel_id,
            'plc_freq': plc_freq,
            'plc_freq_mhz': plc_freq / 1_000_000 if plc_freq else None,
            'power': power_data.get('rxPower'),
            'mer': power_data.get('rxMer'),
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
    for idx in sorted(us_up.keys()):
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
    for idx in sorted(us_ofdma.keys()):
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
