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
        'docsIfUpChannelTable': '1.3.6.1.2.1.10.127.1.1.2',
        'docsIf3CmStatusUsTable': '1.3.6.1.4.1.4491.2.1.20.1.2',
        'docsIf31CmUsOfdmaChanTable': '1.3.6.1.4.1.4491.2.1.28.1.13',
        'docsIf31CmStatusOfdmaUsTable': '1.3.6.1.4.1.4491.2.1.28.1.12',
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
    
    # Parse all tables
    tables_data = {}
    for table_name, base_oid in TABLES.items():
        raw_data = raw_results.get(base_oid, [])
        tables_data[table_name] = parse_table(table_name, base_oid, raw_data)
    
    # Build response
    ds_down = tables_data.get('docsIfDownChannelTable', {})
    ds_sigq = tables_data.get('docsIfSigQTable', {})
    ds_rxmer = tables_data.get('docsIf3SignalQualityExtTable', {})
    ds_ofdm = tables_data.get('docsIf31CmDsOfdmChanTable', {})
    ds_ofdm_power = tables_data.get('docsIf31CmDsOfdmChannelPowerTable', {})
    us_up = tables_data.get('docsIfUpChannelTable', {})
    us_status = tables_data.get('docsIf3CmStatusUsTable', {})
    us_ofdma = tables_data.get('docsIf31CmUsOfdmaChanTable', {})
    us_ofdma_status = tables_data.get('docsIf31CmStatusOfdmaUsTable', {})
    
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
        
        ds_ofdm_channels.append({
            'index': idx,
            'channel_id': channel_id,
            'plc_freq': plc_freq,
            'plc_freq_mhz': plc_freq / 1_000_000 if plc_freq else None,
            'power': power_data.get('rxPower'),
            'mer': power_data.get('rxMer'),
            'num_subcarriers': num_sc,
            'subcarrier_spacing_khz': sc_hz / 1000,
            'bandwidth_mhz': bandwidth / 1_000_000 if bandwidth else None,
        })
    
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
        
        us_ofdma_channels.append({
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
        })
    
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
