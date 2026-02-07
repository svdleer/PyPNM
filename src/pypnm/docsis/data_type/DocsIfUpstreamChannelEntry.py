
from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import logging
from collections.abc import Callable

from pydantic import BaseModel

from pypnm.snmp.snmp_v2c import Snmp_v2c


class DocsIfUpstreamEntry(BaseModel):
    docsIfUpChannelId: int | None = None
    docsIfUpChannelFrequency: int | None = None
    docsIfUpChannelWidth: int | None = None
    docsIfUpChannelModulationProfile: int | None = None
    docsIfUpChannelSlotSize: int | None = None
    docsIfUpChannelTxTimingOffset: int | None = None
    docsIfUpChannelRangingBackoffStart: int | None = None
    docsIfUpChannelRangingBackoffEnd: int | None = None
    docsIfUpChannelTxBackoffStart: int | None = None
    docsIfUpChannelTxBackoffEnd: int | None = None
    docsIfUpChannelType: int | None = None
    docsIfUpChannelCloneFrom: int | None = None
    docsIfUpChannelUpdate: bool | None = None
    docsIfUpChannelStatus: int | None = None
    docsIfUpChannelPreEqEnable: bool | None = None

    # DOCS-IF3-MIB extensions
    docsIf3CmStatusUsTxPower: float | None = None
    docsIf3CmStatusUsT3Timeouts: int | None = None
    docsIf3CmStatusUsT4Timeouts: int | None = None
    docsIf3CmStatusUsRangingAborteds: int | None = None
    docsIf3CmStatusUsModulationType: int | None = None
    docsIf3CmStatusUsEqData: str | None = None
    docsIf3CmStatusUsT3Exceededs: int | None = None
    docsIf3CmStatusUsIsMuted: bool | None = None
    docsIf3CmStatusUsRangingStatus: int | None = None

class DocsIfUpstreamChannelEntry(BaseModel):
    index: int
    channel_id: int
    entry: DocsIfUpstreamEntry

    @classmethod
    async def from_snmp(cls, index: int, snmp: Snmp_v2c) -> DocsIfUpstreamChannelEntry | None:
        logger = logging.getLogger(cls.__name__)

        def tenthdBmV_to_float(value: str) -> float | None:
            try:
                return float(value) / 10.0
            except Exception:
                return None

        def safe_cast(value: str, cast: Callable) -> int | float | str | bool | None:
            try:
                return cast(value)
            except Exception:
                return None

        async def fetch(field: str, cast: Callable | None = None) -> None | int | float | str | bool:
            try:
                raw = await snmp.get(f"{field}.{index}")
                val = Snmp_v2c.get_result_value(raw)
                if val is None or val == "":
                    return None
                if cast:
                    return safe_cast(val, cast)
                val = val.strip()
                if val.isdigit():
                    return int(val)
                if val.lower() in ("true", "false"):
                    return val.lower() == "true"
                try:
                    return float(val)
                except ValueError:
                    return val
            except Exception as e:
                logger.warning(f"Failed to fetch {field}: {e}")
                return None

        entry = DocsIfUpstreamEntry(
            docsIfUpChannelId                   =   await fetch("docsIfUpChannelId", int),
            docsIfUpChannelFrequency            =   await fetch("docsIfUpChannelFrequency", int),
            docsIfUpChannelWidth                =   await fetch("docsIfUpChannelWidth", int),
            docsIfUpChannelModulationProfile    =   await fetch("docsIfUpChannelModulationProfile", int),
            docsIfUpChannelSlotSize             =   await fetch("docsIfUpChannelSlotSize", int),
            docsIfUpChannelTxTimingOffset       =   await fetch("docsIfUpChannelTxTimingOffset", int),
            docsIfUpChannelRangingBackoffStart =   await fetch("docsIfUpChannelRangingBackoffStart", int),
            docsIfUpChannelRangingBackoffEnd   =   await fetch("docsIfUpChannelRangingBackoffEnd", int),
            docsIfUpChannelTxBackoffStart      =   await fetch("docsIfUpChannelTxBackoffStart", int),
            docsIfUpChannelTxBackoffEnd        =   await fetch("docsIfUpChannelTxBackoffEnd", int),
            docsIfUpChannelType                =   await fetch("docsIfUpChannelType", int),
            docsIfUpChannelCloneFrom           =   await fetch("docsIfUpChannelCloneFrom", int),
            docsIfUpChannelUpdate              =   await fetch("docsIfUpChannelUpdate", Snmp_v2c.truth_value),
            docsIfUpChannelStatus              =   await fetch("docsIfUpChannelStatus", int),
            docsIfUpChannelPreEqEnable         =   await fetch("docsIfUpChannelPreEqEnable", Snmp_v2c.truth_value),

            docsIf3CmStatusUsTxPower           =   await fetch("docsIf3CmStatusUsTxPower", tenthdBmV_to_float),
            docsIf3CmStatusUsT3Timeouts        =   await fetch("docsIf3CmStatusUsT3Timeouts", int),
            docsIf3CmStatusUsT4Timeouts        =   await fetch("docsIf3CmStatusUsT4Timeouts", int),
            docsIf3CmStatusUsRangingAborteds   =   await fetch("docsIf3CmStatusUsRangingAborteds", int),
            docsIf3CmStatusUsModulationType    =   await fetch("docsIf3CmStatusUsModulationType", int),
            docsIf3CmStatusUsEqData            =   await fetch("docsIf3CmStatusUsEqData", str),
            docsIf3CmStatusUsT3Exceededs       =   await fetch("docsIf3CmStatusUsT3Exceededs", int),
            docsIf3CmStatusUsIsMuted           =   await fetch("docsIf3CmStatusUsIsMuted", Snmp_v2c.truth_value),
            docsIf3CmStatusUsRangingStatus     =   await fetch("docsIf3CmStatusUsRangingStatus", int)
        )

        return cls(
            index=index,
            channel_id=entry.docsIfUpChannelId or 0,
            entry=entry
        )

    @classmethod
    async def get(cls, snmp: Snmp_v2c, indices: list[int]) -> list[DocsIfUpstreamChannelEntry]:
        logger = logging.getLogger(cls.__name__)
        results: list[DocsIfUpstreamChannelEntry] = []

        if not indices:
            logger.warning("No upstream ATDMA indices found.")
            return results

        # Check if bulk_get is available (agent transport optimization)
        if hasattr(snmp, 'bulk_get'):
            # OPTIMIZATION: Use ONE bulk_get call for ALL channels at once
            fields_to_fetch = [
                "docsIfUpChannelId",
                "docsIfUpChannelFrequency",
                "docsIfUpChannelWidth",
                "docsIfUpChannelModulationProfile",
                "docsIfUpChannelSlotSize",
                "docsIfUpChannelTxTimingOffset",
                "docsIfUpChannelRangingBackoffStart",
                "docsIfUpChannelRangingBackoffEnd",
                "docsIfUpChannelTxBackoffStart",
                "docsIfUpChannelTxBackoffEnd",
                "docsIfUpChannelType",
                "docsIfUpChannelCloneFrom",
                "docsIfUpChannelUpdate",
                "docsIfUpChannelStatus",
                "docsIfUpChannelPreEqEnable",
                "docsIf3CmStatusUsTxPower",
                "docsIf3CmStatusUsT3Timeouts",
                "docsIf3CmStatusUsT4Timeouts",
                "docsIf3CmStatusUsRangingAborteds",
                "docsIf3CmStatusUsModulationType",
                "docsIf3CmStatusUsEqData",
                "docsIf3CmStatusUsT3Exceededs",
                "docsIf3CmStatusUsIsMuted",
                "docsIf3CmStatusUsRangingStatus",
            ]
            
            # Build ALL OIDs for all indices in one list
            all_oids = [f"{field}.{index}" for index in indices for field in fields_to_fetch]
            
            bulk_results = await snmp.bulk_get(all_oids)
            
            # Parse results for each channel
            for index in indices:
                try:
                    entry = cls._parse_bulk_results(index, bulk_results, fields_to_fetch)
                    if entry:
                        results.append(cls(
                            index=index,
                            channel_id=entry.docsIfUpChannelId or 0,
                            entry=entry
                        ))
                except Exception as e:
                    logger.warning(f"Failed to parse upstream channel {index}: {e}")
            
            return results

        # Fallback: use individual from_snmp calls in parallel
        import asyncio
        tasks = [cls.from_snmp(index, snmp) for index in indices]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for index, response in zip(indices, responses):
            if isinstance(response, Exception):
                logger.warning(f"Failed to retrieve upstream channel {index}: {response}")
            elif response is not None:
                results.append(response)

        return results

    @classmethod
    def _parse_bulk_results(cls, index: int, bulk_results: dict, fields: list[str]) -> DocsIfUpstreamEntry | None:
        """Parse bulk_get results for a single upstream channel index."""
        
        def tenthdBmV_to_float(value: str) -> float | None:
            try:
                return float(value) / 10.0
            except Exception:
                return None

        def safe_cast(value: str, cast) -> int | float | str | bool | None:
            try:
                return cast(value)
            except Exception:
                return None

        def get_bulk_val(field: str, cast=None):
            try:
                oid_key = f"{field}.{index}"
                raw = bulk_results.get(oid_key) if bulk_results else None
                if not raw:
                    return None
                val = Snmp_v2c.get_result_value(raw)
                if val is None or val == "":
                    return None
                if cast:
                    return safe_cast(val, cast)
                val = str(val).strip()
                if val.isdigit():
                    return int(val)
                if val.lower() in ("true", "false"):
                    return val.lower() == "true"
                try:
                    return float(val)
                except ValueError:
                    return val
            except Exception:
                return None

        return DocsIfUpstreamEntry(
            docsIfUpChannelId                   =   get_bulk_val("docsIfUpChannelId", int),
            docsIfUpChannelFrequency            =   get_bulk_val("docsIfUpChannelFrequency", int),
            docsIfUpChannelWidth                =   get_bulk_val("docsIfUpChannelWidth", int),
            docsIfUpChannelModulationProfile    =   get_bulk_val("docsIfUpChannelModulationProfile", int),
            docsIfUpChannelSlotSize             =   get_bulk_val("docsIfUpChannelSlotSize", int),
            docsIfUpChannelTxTimingOffset       =   get_bulk_val("docsIfUpChannelTxTimingOffset", int),
            docsIfUpChannelRangingBackoffStart  =   get_bulk_val("docsIfUpChannelRangingBackoffStart", int),
            docsIfUpChannelRangingBackoffEnd    =   get_bulk_val("docsIfUpChannelRangingBackoffEnd", int),
            docsIfUpChannelTxBackoffStart       =   get_bulk_val("docsIfUpChannelTxBackoffStart", int),
            docsIfUpChannelTxBackoffEnd         =   get_bulk_val("docsIfUpChannelTxBackoffEnd", int),
            docsIfUpChannelType                 =   get_bulk_val("docsIfUpChannelType", int),
            docsIfUpChannelCloneFrom            =   get_bulk_val("docsIfUpChannelCloneFrom", int),
            docsIfUpChannelUpdate               =   get_bulk_val("docsIfUpChannelUpdate", Snmp_v2c.truth_value),
            docsIfUpChannelStatus               =   get_bulk_val("docsIfUpChannelStatus", int),
            docsIfUpChannelPreEqEnable          =   get_bulk_val("docsIfUpChannelPreEqEnable", Snmp_v2c.truth_value),
            docsIf3CmStatusUsTxPower            =   get_bulk_val("docsIf3CmStatusUsTxPower", tenthdBmV_to_float),
            docsIf3CmStatusUsT3Timeouts         =   get_bulk_val("docsIf3CmStatusUsT3Timeouts", int),
            docsIf3CmStatusUsT4Timeouts         =   get_bulk_val("docsIf3CmStatusUsT4Timeouts", int),
            docsIf3CmStatusUsRangingAborteds    =   get_bulk_val("docsIf3CmStatusUsRangingAborteds", int),
            docsIf3CmStatusUsModulationType     =   get_bulk_val("docsIf3CmStatusUsModulationType", int),
            docsIf3CmStatusUsEqData             =   get_bulk_val("docsIf3CmStatusUsEqData", str),
            docsIf3CmStatusUsT3Exceededs        =   get_bulk_val("docsIf3CmStatusUsT3Exceededs", int),
            docsIf3CmStatusUsIsMuted            =   get_bulk_val("docsIf3CmStatusUsIsMuted", Snmp_v2c.truth_value),
            docsIf3CmStatusUsRangingStatus      =   get_bulk_val("docsIf3CmStatusUsRangingStatus", int),
        )
