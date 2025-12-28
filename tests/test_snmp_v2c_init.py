# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

from pypnm.lib.inet import Inet
from pypnm.lib.types import SnmpReadCommunity, SnmpWriteCommunity
from pypnm.snmp.snmp_v2c import Snmp_v2c


def test_snmp_v2c_prefers_explicit_read_write() -> None:
    snmp = Snmp_v2c(
        host=Inet("127.0.0.1"),
        read_community=SnmpReadCommunity("read"),
        write_community=SnmpWriteCommunity("write"),
    )

    assert snmp._read_community == "read"
    assert snmp._write_community == "write"


def test_snmp_v2c_legacy_community_sets_both() -> None:
    snmp = Snmp_v2c(
        host=Inet("127.0.0.1"),
        community="legacy",
    )

    assert snmp._read_community == "legacy"
    assert snmp._write_community == "legacy"


def test_snmp_v2c_write_falls_back_to_read() -> None:
    snmp = Snmp_v2c(
        host=Inet("127.0.0.1"),
        read_community=SnmpReadCommunity("read"),
        write_community=SnmpWriteCommunity(""),
    )

    assert snmp._read_community == "read"
    assert snmp._write_community == "read"
