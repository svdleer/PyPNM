
from __future__ import annotations

import asyncio
from collections.abc import Callable

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
from enum import IntEnum

from pydantic import BaseModel

from pypnm.snmp.modules import DocsisIfType
from pypnm.snmp.snmp_v2c import Snmp_v2c


class IfAdminStatus(IntEnum):
    up = 1
    down = 2
    testing = 3

class IfOperStatus(IntEnum):
    up = 1
    down = 2
    testing = 3

class IfEntry(BaseModel):
    ifIndex: int
    ifDescr: str
    ifType: DocsisIfType
    ifMtu: int
    ifSpeed: int
    ifPhysAddress: str
    ifAdminStatus: IfAdminStatus
    ifOperStatus: IfOperStatus
    ifLastChange: int
    ifInOctets: int
    ifInUcastPkts: int
    ifInNUcastPkts: int | None = None
    ifInDiscards: int
    ifInErrors: int
    ifInUnknownProtos: int
    ifOutOctets: int
    ifOutUcastPkts: int
    ifOutNUcastPkts: int | None = None
    ifOutDiscards: int
    ifOutErrors: int
    ifOutQLen: int | None = None
    ifSpecific: str | None = None

class IfXEntry(BaseModel):
    ifName: str
    ifInMulticastPkts: int
    ifInBroadcastPkts: int
    ifOutMulticastPkts: int
    ifOutBroadcastPkts: int
    ifHCInOctets: int
    ifHCInUcastPkts: int
    ifHCInMulticastPkts: int
    ifHCInBroadcastPkts: int
    ifHCOutOctets: int
    ifHCOutUcastPkts: int
    ifHCOutMulticastPkts: int
    ifHCOutBroadcastPkts: int
    ifLinkUpDownTrapEnable: int
    ifHighSpeed: int
    ifPromiscuousMode: bool
    ifConnectorPresent: bool
    ifAlias: str
    ifCounterDiscontinuityTime: int

class InterfaceStats(BaseModel):
    ifEntry: IfEntry
    ifXEntry: IfXEntry | None = None

    @classmethod
    async def from_snmp(cls, snmp: Snmp_v2c, if_type_filter: DocsisIfType) -> list[InterfaceStats]:
        """Optimized to reduce SNMP queries - batch gets instead of individual."""
        stats_list = []

        # First get all interface indexes matching the type filter
        matching_indexes = []
        for if_index in await snmp.walk("ifIndex"):
            index = Snmp_v2c.get_oid_index(str(if_index[0]))
            if index is None:
                continue

            if_type = await snmp.get(f"ifType.{index}")
            type_val = Snmp_v2c.get_result_value(if_type)

            if type_val is None or int(type_val) != if_type_filter:
                continue
            
            matching_indexes.append(index)
        
        # If no matching interfaces, return early
        if not matching_indexes:
            return []

        # For each matching interface, fetch all required fields in batches
        for index in matching_indexes:
            # Try bulk_get if available (agent transport optimization)
            if hasattr(snmp, 'bulk_get'):
                oid_list = [
                    f"ifDescr.{index}",
                    f"ifMtu.{index}",
                    f"ifSpeed.{index}",
                    f"ifPhysAddress.{index}",
                    f"ifAdminStatus.{index}",
                    f"ifOperStatus.{index}",
                    f"ifLastChange.{index}",
                    f"ifInOctets.{index}",
                    f"ifInUcastPkts.{index}",
                    f"ifInNUcastPkts.{index}",
                    f"ifInDiscards.{index}",
                    f"ifInErrors.{index}",
                    f"ifInUnknownProtos.{index}",
                    f"ifOutOctets.{index}",
                    f"ifOutUcastPkts.{index}",
                    f"ifOutNUcastPkts.{index}",
                    f"ifOutDiscards.{index}",
                    f"ifOutErrors.{index}",
                    f"ifOutQLen.{index}",
                    f"ifSpecific.{index}",
                ]
                
                bulk_results = await snmp.bulk_get(oid_list)
                if bulk_results:
                    field_values = {
                        "ifDescr": bulk_results.get(f"ifDescr.{index}"),
                        "ifMtu": bulk_results.get(f"ifMtu.{index}"),
                        "ifSpeed": bulk_results.get(f"ifSpeed.{index}"),
                        "ifPhysAddress": bulk_results.get(f"ifPhysAddress.{index}"),
                        "ifAdminStatus": bulk_results.get(f"ifAdminStatus.{index}"),
                        "ifOperStatus": bulk_results.get(f"ifOperStatus.{index}"),
                        "ifLastChange": bulk_results.get(f"ifLastChange.{index}"),
                        "ifInOctets": bulk_results.get(f"ifInOctets.{index}"),
                        "ifInUcastPkts": bulk_results.get(f"ifInUcastPkts.{index}"),
                        "ifInNUcastPkts": bulk_results.get(f"ifInNUcastPkts.{index}"),
                        "ifInDiscards": bulk_results.get(f"ifInDiscards.{index}"),
                        "ifInErrors": bulk_results.get(f"ifInErrors.{index}"),
                        "ifInUnknownProtos": bulk_results.get(f"ifInUnknownProtos.{index}"),
                        "ifOutOctets": bulk_results.get(f"ifOutOctets.{index}"),
                        "ifOutUcastPkts": bulk_results.get(f"ifOutUcastPkts.{index}"),
                        "ifOutNUcastPkts": bulk_results.get(f"ifOutNUcastPkts.{index}"),
                        "ifOutDiscards": bulk_results.get(f"ifOutDiscards.{index}"),
                        "ifOutErrors": bulk_results.get(f"ifOutErrors.{index}"),
                        "ifOutQLen": bulk_results.get(f"ifOutQLen.{index}"),
                        "ifSpecific": bulk_results.get(f"ifSpecific.{index}"),
                    }
                else:
                    # Fallback if bulk_get fails
                    field_values = {}
            else:
                # Fallback: Batch fetch all IfEntry fields (reduces ~20 individual GETs to parallel fetches)
                tasks = {
                    "ifDescr": snmp.get(f"ifDescr.{index}"),
                    "ifMtu": snmp.get(f"ifMtu.{index}"),
                    "ifSpeed": snmp.get(f"ifSpeed.{index}"),
                    "ifPhysAddress": snmp.get(f"ifPhysAddress.{index}"),
                    "ifAdminStatus": snmp.get(f"ifAdminStatus.{index}"),
                    "ifOperStatus": snmp.get(f"ifOperStatus.{index}"),
                    "ifLastChange": snmp.get(f"ifLastChange.{index}"),
                    "ifInOctets": snmp.get(f"ifInOctets.{index}"),
                    "ifInUcastPkts": snmp.get(f"ifInUcastPkts.{index}"),
                    "ifInNUcastPkts": snmp.get(f"ifInNUcastPkts.{index}"),
                    "ifInDiscards": snmp.get(f"ifInDiscards.{index}"),
                    "ifInErrors": snmp.get(f"ifInErrors.{index}"),
                    "ifInUnknownProtos": snmp.get(f"ifInUnknownProtos.{index}"),
                    "ifOutOctets": snmp.get(f"ifOutOctets.{index}"),
                    "ifOutUcastPkts": snmp.get(f"ifOutUcastPkts.{index}"),
                    "ifOutNUcastPkts": snmp.get(f"ifOutNUcastPkts.{index}"),
                    "ifOutDiscards": snmp.get(f"ifOutDiscards.{index}"),
                    "ifOutErrors": snmp.get(f"ifOutErrors.{index}"),
                    "ifOutQLen": snmp.get(f"ifOutQLen.{index}"),
                    "ifSpecific": snmp.get(f"ifSpecific.{index}"),
                }
                
                # Await all in parallel
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                field_values = dict(zip(tasks.keys(), results))
            
            def get_val(field: str, cast=None):
                result = field_values.get(field)
                if isinstance(result, Exception) or result is None:
                    return None
                val = Snmp_v2c.get_result_value(result)
                if val is None or val == "":
                    return None
                if cast:
                    try:
                        return cast(val)
                    except:
                        return None
                return val

            entry = IfEntry(
                ifIndex=index,
                ifDescr=get_val("ifDescr", str) or "",
                ifType=if_type_filter,
                ifMtu=get_val("ifMtu", int) or 0,
                ifSpeed=get_val("ifSpeed", int) or 0,
                ifPhysAddress=get_val("ifPhysAddress", str) or "",
                ifAdminStatus=IfAdminStatus(get_val("ifAdminStatus", int) or 1),
                ifOperStatus=IfOperStatus(get_val("ifOperStatus", int) or 1),
                ifLastChange=get_val("ifLastChange", int) or 0,
                ifInOctets=get_val("ifInOctets", int) or 0,
                ifInUcastPkts=get_val("ifInUcastPkts", int) or 0,
                ifInNUcastPkts=get_val("ifInNUcastPkts", int),
                ifInDiscards=get_val("ifInDiscards", int) or 0,
                ifInErrors=get_val("ifInErrors", int) or 0,
                ifInUnknownProtos=get_val("ifInUnknownProtos", int) or 0,
                ifOutOctets=get_val("ifOutOctets", int) or 0,
                ifOutUcastPkts=get_val("ifOutUcastPkts", int) or 0,
                ifOutNUcastPkts=get_val("ifOutNUcastPkts", int),
                ifOutDiscards=get_val("ifOutDiscards", int) or 0,
                ifOutErrors=get_val("ifOutErrors", int) or 0,
                ifOutQLen=get_val("ifOutQLen", int),
                ifSpecific=get_val("ifSpecific", str),
            )

            # Try to fetch IfXEntry fields (optional)
            try:
                xtasks = {
                    field: snmp.get(f"{field}.{index}")
                    for field in IfXEntry.__annotations__
                }
                xresults = await asyncio.gather(*xtasks.values(), return_exceptions=True)
                xdata = {
                    field: Snmp_v2c.get_result_value(result) if not isinstance(result, Exception) else None
                    for field, result in zip(xtasks.keys(), xresults)
                }
                xentry = IfXEntry(**xdata)
            except Exception:
                xentry = None

            stats_list.append(cls(ifEntry=entry, ifXEntry=xentry))

        return stats_list
