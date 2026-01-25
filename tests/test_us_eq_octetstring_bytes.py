# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pysnmp.proto.rfc1902 import OctetString

from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData
from pypnm.snmp.snmp_v2c import Snmp_v2c


def test_us_eq_payload_hex_preserves_raw_bytes() -> None:
    payload = bytes([0x01, 0x02, 0x01, 0x00, 0xFF, 0xFC, 0xFF, 0xFE])
    ded = DocsEqualizerData()

    assert ded.add_from_bytes(1, payload)

    record = ded.get_record(1)
    assert record is not None
    assert "FF FC FF FE" in record.payload_hex
    assert "C3 BF" not in record.payload_hex


def test_snmp_octets_to_bytes_rejects_utf8_text() -> None:
    value = "ÿ"
    raw = Snmp_v2c.snmp_octets_to_bytes(value)

    assert raw == b""
    assert value.encode("utf-8").hex() == "c3bf"


def test_snmp_octets_to_bytes_handles_octetstring() -> None:
    raw = Snmp_v2c.snmp_octets_to_bytes(OctetString(b"\xff\xfe\xfc"))
    assert raw == b"\xff\xfe\xfc"
