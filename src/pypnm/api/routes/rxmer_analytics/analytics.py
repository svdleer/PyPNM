# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass

CODEC = "rxmer-u8-qdb-zlib-v1"
_MAX_QDB = 254  # The existing parser clamps RxMER to 63.5 dB.


@dataclass(frozen=True)
class ChannelMetrics:
    channel_id: int
    ifindex: int
    zero_frequency_hz: int
    first_active_index: int
    spacing_hz: int
    sample_count: int
    sum_qdb: int
    avg_db: float
    best_qdb: int
    best_subcarrier_index: int
    best_frequency_hz: int
    vector_sha256: bytes
    normalized_vector: bytes
    compressed_vector: bytes


def analyze_channel(
    vector: bytes,
    *,
    channel_id: int,
    ifindex: int,
    zero_frequency_hz: int,
    first_active_index: int,
    spacing_hz: int,
) -> ChannelMetrics:
    """Calculate deterministic channel metrics from native quarter-dB bytes."""
    if not vector:
        raise ValueError("RxMER vector must not be empty")
    if spacing_hz <= 0:
        raise ValueError("subcarrier spacing must be positive")
    if first_active_index < 0:
        raise ValueError("first active subcarrier index must not be negative")

    normalized = bytes(min(value, _MAX_QDB) for value in vector)
    sample_count = len(normalized)
    sum_qdb = sum(normalized)
    best_qdb = max(normalized)
    best_offset = normalized.index(best_qdb)
    best_index = first_active_index + best_offset
    digest = hashlib.sha256(normalized).digest()

    return ChannelMetrics(
        channel_id=int(channel_id),
        ifindex=int(ifindex),
        zero_frequency_hz=int(zero_frequency_hz),
        first_active_index=int(first_active_index),
        spacing_hz=int(spacing_hz),
        sample_count=sample_count,
        sum_qdb=sum_qdb,
        avg_db=sum_qdb / (4.0 * sample_count),
        best_qdb=best_qdb,
        best_subcarrier_index=best_index,
        best_frequency_hz=int(zero_frequency_hz) + best_index * int(spacing_hz),
        vector_sha256=digest,
        normalized_vector=normalized,
        compressed_vector=zlib.compress(normalized, level=3),
    )


def decode_vector(payload: bytes, *, expected_sha256: bytes, expected_size: int) -> bytes:
    """Decode and verify an immutable stored vector."""
    vector = zlib.decompress(payload)
    if len(vector) != expected_size:
        raise ValueError("decoded RxMER vector length does not match metadata")
    if hashlib.sha256(vector).digest() != expected_sha256:
        raise ValueError("decoded RxMER vector checksum mismatch")
    return vector
