# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest

import pypnm.snmp.snmp_v2c as snmp_v2c_module
from pypnm.lib.inet import Inet
from pypnm.snmp.snmp_v2c import Snmp_v2c


@pytest.mark.asyncio
async def test_bulk_walk_returns_results_until_subtree_exit(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    snmp = Snmp_v2c(Inet("192.168.0.100"), community="public")
    oid = "1.3.6.1.2.1"

    in_subtree = ("1.3.6.1.2.1.1.0", "value-1")
    out_of_subtree = ("1.3.6.1.3.1.0", "value-2")

    class FakeIdentity:
        def __init__(self, oid_value: str) -> None:
            self._oid_value = oid_value

        def __str__(self) -> str:
            return self._oid_value

    def fake_object_type(identity: object) -> tuple[str, object]:
        return ("object", identity)

    async def fake_create(*_args: object, **_kwargs: object) -> object:
        return object()

    async def fake_bulk_cmd(*_args: object, **_kwargs: object):
        yield (None, None, 0, [in_subtree])
        yield (None, None, 0, [out_of_subtree])

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)

    results = await snmp.bulk_walk(oid)

    assert results is not None
    assert results == [in_subtree]


@pytest.mark.asyncio
async def test_bulk_walk_returns_none_on_empty_payload(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    snmp = Snmp_v2c(Inet("192.168.0.100"), community="public")

    class FakeIdentity:
        def __init__(self, oid_value: str) -> None:
            self._oid_value = oid_value

        def __str__(self) -> str:
            return self._oid_value

    def fake_object_type(identity: object) -> tuple[str, object]:
        return ("object", identity)

    async def fake_create(*_args: object, **_kwargs: object) -> object:
        return object()

    async def fake_bulk_cmd(*_args: object, **_kwargs: object):
        yield (None, None, 0, [])

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)

    results = await snmp.bulk_walk("1.3.6.1.2.1")

    assert results is None
