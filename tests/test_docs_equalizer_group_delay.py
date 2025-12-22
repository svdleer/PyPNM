# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pypnm.lib.types import BandwidthHz
from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData


def _encode_i16(value: int) -> bytes:
    if value < 0:
        value = (1 << 16) + value
    return value.to_bytes(2, byteorder="little", signed=False)


def _build_payload(num_taps: int, taps_per_symbol: int) -> bytes:
    header = bytes([8, taps_per_symbol, num_taps, 0])
    taps = bytearray()
    for _ in range(num_taps):
        taps.extend(_encode_i16(1))
        taps.extend(_encode_i16(0))
    return header + taps


def test_group_delay_included_with_channel_width() -> None:
    payload = _build_payload(num_taps=24, taps_per_symbol=1)
    ded = DocsEqualizerData()

    added = ded.add_from_bytes(80, payload, channel_width_hz=BandwidthHz(1_600_000))
    assert added is True

    record = ded.get_record(80)
    assert record is not None
    assert record.group_delay is not None
    assert int(record.group_delay.channel_width_hz) == 1_600_000
    assert record.group_delay.taps_per_symbol == 1
    assert record.group_delay.fft_size == 24
    assert len(record.group_delay.delay_samples) == 24
    assert len(record.group_delay.delay_us) == 24


def test_group_delay_missing_without_channel_width() -> None:
    payload = _build_payload(num_taps=24, taps_per_symbol=1)
    ded = DocsEqualizerData()

    added = ded.add_from_bytes(81, payload)
    assert added is True

    record = ded.get_record(81)
    assert record is not None
    assert record.group_delay is None
