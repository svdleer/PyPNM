"""Authoritative parser for normalized UTSC spectrum capture samples."""
from __future__ import annotations

import struct
from typing import Any


HEADER_SIZE = 328


def parse_utsc_file(
    content: bytes,
    *,
    filename: str,
    vendor: str | None,
    center_freq_hz: int,
    span_hz: int,
    max_bins: int = 1600,
) -> dict[str, Any]:
    """Parse the deployed 328-byte-header FFT amplitude format."""
    if len(content) < HEADER_SIZE + 2:
        raise ValueError("UTSC file is too small to contain spectrum samples")

    vendor_lc = (vendor or '').strip().lower()
    is_cisco = 'cisco' in vendor_lc or 'cbr' in vendor_lc or 'PNMCcap' in filename
    endian = '>' if is_cisco else '<'
    payload = content[HEADER_SIZE:]
    sample_count = min(len(payload) // 2, max_bins)
    if sample_count <= 0:
        raise ValueError("UTSC file contains no complete spectrum samples")

    raw = struct.unpack(f'{endian}{sample_count}h', payload[:sample_count * 2])
    bins = [round(value / 100.0, 2) for value in raw]
    frequency_start = center_freq_hz - (span_hz / 2.0)
    frequency_step = span_hz / sample_count
    return {
        'filename': filename,
        'file_size': len(content),
        'vendor': vendor_lc or 'unknown',
        'num_bins': sample_count,
        'center_freq_hz': center_freq_hz,
        'span_hz': span_hz,
        'freq_start_hz': frequency_start,
        'freq_step_hz': frequency_step,
        'bins': bins,
        'units': 'dBmV',
    }
