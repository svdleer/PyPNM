from pypnm.api.routes.cm.channel_stats.parser import parse_channel_stats_raw


DSID_BASE = '1.3.6.1.4.1.4491.2.1.21.1.22'


def test_docs_qos3_dsid_stats_are_exposed_in_ofdm_stats() -> None:
    raw = {
        DSID_BASE: [
            {'oid': f'{DSID_BASE}.1.100', 'value': 100},
            {'oid': f'{DSID_BASE}.2.100', 'value': 3},
            {'oid': f'{DSID_BASE}.3.100', 'value': 4},
            {'oid': f'{DSID_BASE}.4.100', 'value': 5},
            {'oid': f'{DSID_BASE}.5.100', 'value': 9876543210},
            {'oid': f'{DSID_BASE}.1.200', 'value': '200'},
            {'oid': f'{DSID_BASE}.2.200', 'value': '0'},
            {'oid': f'{DSID_BASE}.3.200', 'value': '1'},
            {'oid': f'{DSID_BASE}.4.200', 'value': '2'},
            {'oid': f'{DSID_BASE}.5.200', 'value': '42'},
        ],
    }

    result = parse_channel_stats_raw(raw, 0.1, '00:11:22:33:44:55', '192.0.2.10')

    assert result['success'] is True
    expected = [
        {
            'dsid': 100,
            'seq_num_missing': 3,
            'skew_thresh_exceeds': 4,
            'out_of_range_packets': 5,
            'num_packets': 9876543210,
        },
        {
            'dsid': 200,
            'seq_num_missing': 0,
            'skew_thresh_exceeds': 1,
            'out_of_range_packets': 2,
            'num_packets': 42,
        },
    ]
    assert result['ds_dsid_stats'] == expected

    from pypnm.api.routes.cm.channel_stats.parser import parse_ofdm_stats_raw
    ofdm_stats = parse_ofdm_stats_raw(
        cm_index=None,
        partial_reason_result=None,
        us_iuc_stats_result=None,
        ds_ofdm_speed_result=None,
        ds_subcarrier_result=None,
        cm_ds_ofdm_channels=[],
        ds_dsid_stats=result['ds_dsid_stats'],
    )
    assert ofdm_stats['ds_dsid_stats'] == expected
