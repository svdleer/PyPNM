from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
import logging
from collections.abc import Callable

from pydantic import BaseModel

from pypnm.lib.constants import INVALID_CHANNEL_ID
from pypnm.lib.types import ChannelId, FrequencyHz
from pypnm.snmp.snmp_v2c import Snmp_v2c


class DocsIfDownstreamEntry(BaseModel):
    """
    DOCSIS downstream SC-QAM signal/quality metrics for a single channel.

    Notes
    -----
    - Values are sourced from symbolic OIDs in DOCSIS-IF(-EXT3)-MIB (e.g.,
      ``docsIfDownChannelId``, ``docsIfSigQCorrecteds``, etc.).
    - ``docsIfDownChannelPower`` is converted from tenths-of-dBmV (SNMP integer)
      to a float in dBmV.
    - Presence of fields depends on CM/CMTS support and MIB implementation.

    Attributes
    ----------
    docsIfDownChannelId : Optional[int]
        Channel ID (SC-QAM), from ``docsIfDownChannelId``.
    docsIfDownChannelFrequency : Optional[int]
        Center frequency in Hz, from ``docsIfDownChannelFrequency``.
    docsIfDownChannelWidth : Optional[int]
        Channel width in Hz, from ``docsIfDownChannelWidth``.
    docsIfDownChannelModulation : Optional[int]
        Modulation enum value, from ``docsIfDownChannelModulation``.
    docsIfDownChannelInterleave : Optional[int]
        Interleave depth/setting, from ``docsIfDownChannelInterleave``.
    docsIfDownChannelPower : Optional[float]
        Average channel power in dBmV (float), converted from tenths-of-dBmV.
    docsIfSigQUnerroreds : Optional[int]
        Legacy unerrored codewords, from ``docsIfSigQUnerroreds``.
    docsIfSigQCorrecteds : Optional[int]
        Corrected codewords, from ``docsIfSigQCorrecteds``.
    docsIfSigQUncorrectables : Optional[int]
        Uncorrectable codewords, from ``docsIfSigQUncorrectables``.
    docsIfSigQMicroreflections : Optional[int]
        Micro-reflections metric, from ``docsIfSigQMicroreflections``.
    docsIfSigQExtUnerroreds : Optional[int]
        Extended unerrored codewords, from ``docsIfSigQExtUnerroreds``.
    docsIfSigQExtCorrecteds : Optional[int]
        Extended corrected codewords, from ``docsIfSigQExtCorrecteds``.
    docsIfSigQExtUncorrectables : Optional[int]
        Extended uncorrectable codewords, from ``docsIfSigQExtUncorrectables``.
    docsIf3SignalQualityExtRxMER : Optional[float]
        Extended RxMER (dB), from ``docsIf3SignalQualityExtRxMER``.
    """
    docsIfDownChannelId: ChannelId = INVALID_CHANNEL_ID
    docsIfDownChannelFrequency: FrequencyHz | None = None
    docsIfDownChannelWidth: FrequencyHz | None = None
    docsIfDownChannelModulation: int | None = None
    docsIfDownChannelInterleave: int | None = None
    docsIfDownChannelPower: float | None = None
    docsIfSigQUnerroreds: int | None = None
    docsIfSigQCorrecteds: int | None = None
    docsIfSigQUncorrectables: int | None = None
    docsIfSigQMicroreflections: int | None = None
    docsIfSigQExtUnerroreds: int | None = None
    docsIfSigQExtCorrecteds: int | None = None
    docsIfSigQExtUncorrectables: int | None = None
    docsIf3SignalQualityExtRxMER: float | None = None


class DocsIfDownstreamChannelEntry(BaseModel):
    """
    Container for a single downstream SC-QAM channel record retrieved via SNMP.

    Attributes
    ----------
    index : int
        Table index used to query SNMP (e.g., the instance suffix).
    channel_id : int
        The channel ID mirrored from the retrieved entry (0 if missing).
    entry : DocsIfDownstreamEntry
        The populated downstream metrics for the given index.

    Examples
    --------
    Basic one-off fetch:

    >>> snmp = Snmp_v2c(host="192.168.0.100", community="public", timeout=2.0, retries=1)
    >>> entry = await DocsIfDownstreamChannelEntry.from_snmp(index=1, snmp=snmp)
    >>> entry.channel_id
    1

    Batch fetch for multiple indices:

    >>> indices = [1, 2, 3, 4]
    >>> entries = await DocsIfDownstreamChannelEntry.get(snmp, indices)
    >>> len(entries)
    4
    """
    index: int
    channel_id: int
    entry: DocsIfDownstreamEntry

    @classmethod
    async def from_snmp(cls, index: int, snmp: Snmp_v2c) -> DocsIfDownstreamChannelEntry:
        """
        Build an instance by querying SNMP for a single downstream SC-QAM index.

        Parameters
        ----------
        index : int
            The SNMP table index (instance) to query (e.g., ``docsIfDownChannelId.<index>``).
        snmp : Snmp_v2c
            Initialized SNMP v2c client used to perform ``GET`` operations.

        Returns
        -------
        DocsIfDownstreamChannelEntry
            A populated channel container with metrics under ``entry`` and
            ``channel_id`` mirrored from ``docsIfDownChannelId`` (or 0 if absent).

        Notes
        -----
        - Uses symbolic OIDs (no compiled numeric OIDs required).
        - Gracefully handles missing/invalid values; non-parsable fields become ``None``.
        - ``docsIfDownChannelPower`` is converted from tenths-of-dBmV to float dBmV.

        Examples
        --------
        >>> snmp = Snmp_v2c(host="192.168.0.100", community="public")
        >>> result = await DocsIfDownstreamChannelEntry.from_snmp(5, snmp)
        >>> result.entry.docsIf3SignalQualityExtRxMER  # may be None if unsupported
        """
        logger = logging.getLogger(cls.__name__)

        def tenthdBmV_to_float(value: str) -> float | None:
            try:
                return float(value) / 10.0
            except Exception:
                return None

        def to_float(value: str) -> float | None:
            try:
                return float(value)
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
                logger.warning(f"Failed to fetch {field}.{index}: {e}")
                return None

        # Try bulk_get if available (agent transport optimization)
        if hasattr(snmp, 'bulk_get'):
            fields_to_fetch = [
                "docsIfDownChannelId",
                "docsIfDownChannelFrequency",
                "docsIfDownChannelWidth",
                "docsIfDownChannelModulation",
                "docsIfDownChannelInterleave",
                "docsIfDownChannelPower",
                "docsIfSigQUnerroreds",
                "docsIfSigQCorrecteds",
                "docsIfSigQUncorrectables",
                "docsIfSigQMicroreflections",
                "docsIfSigQExtUnerroreds",
                "docsIfSigQExtCorrecteds",
                "docsIfSigQExtUncorrectables",
                "docsIf3SignalQualityExtRxMER",
            ]
            
            oids = [f"{field}.{index}" for field in fields_to_fetch]
            bulk_results = await snmp.bulk_get(oids)
            
            logger.debug(f"bulk_get returned {len(bulk_results) if bulk_results else 0} results for index {index}")
            if bulk_results:
                logger.debug(f"bulk_results keys: {list(bulk_results.keys())[:3]}")
            
            def get_bulk_val(field: str, cast: Callable | None = None):
                try:
                    oid_key = f"{field}.{index}"
                    raw = bulk_results.get(oid_key) if bulk_results else None
                    if not raw:
                        logger.warning(f"No bulk result for {oid_key}, available keys: {list(bulk_results.keys())[:3] if bulk_results else []}")
                        return None
                    val = Snmp_v2c.get_result_value(raw) if raw else None
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
                except Exception:
                    return None
            
            entry = DocsIfDownstreamEntry(
                docsIfDownChannelId         =   get_bulk_val("docsIfDownChannelId", int),
                docsIfDownChannelFrequency  =   get_bulk_val("docsIfDownChannelFrequency", int),
                docsIfDownChannelWidth      =   get_bulk_val("docsIfDownChannelWidth", int),
                docsIfDownChannelModulation =   get_bulk_val("docsIfDownChannelModulation", int),
                docsIfDownChannelInterleave =   get_bulk_val("docsIfDownChannelInterleave", int),
                docsIfDownChannelPower      =   get_bulk_val("docsIfDownChannelPower", tenthdBmV_to_float),
                docsIfSigQUnerroreds        =   get_bulk_val("docsIfSigQUnerroreds", int),
                docsIfSigQCorrecteds        =   get_bulk_val("docsIfSigQCorrecteds", int),
                docsIfSigQUncorrectables    =   get_bulk_val("docsIfSigQUncorrectables", int),
                docsIfSigQMicroreflections  =   get_bulk_val("docsIfSigQMicroreflections", int),
                docsIfSigQExtUnerroreds     =   get_bulk_val("docsIfSigQExtUnerroreds", int),
                docsIfSigQExtCorrecteds     =   get_bulk_val("docsIfSigQExtCorrecteds", int),
                docsIfSigQExtUncorrectables =   get_bulk_val("docsIfSigQExtUncorrectables", int),
                docsIf3SignalQualityExtRxMER =  get_bulk_val("docsIf3SignalQualityExtRxMER", to_float)
            )
        else:
            # Fallback: use individual fetch calls
            entry = DocsIfDownstreamEntry(
                docsIfDownChannelId         =   await fetch("docsIfDownChannelId", int),
                docsIfDownChannelFrequency  =   await fetch("docsIfDownChannelFrequency", int),
                docsIfDownChannelWidth      =   await fetch("docsIfDownChannelWidth", int),
                docsIfDownChannelModulation =   await fetch("docsIfDownChannelModulation", int),
                docsIfDownChannelInterleave =   await fetch("docsIfDownChannelInterleave", int),
                docsIfDownChannelPower      =   await fetch("docsIfDownChannelPower", tenthdBmV_to_float),
                docsIfSigQUnerroreds        =   await fetch("docsIfSigQUnerroreds", int),
                docsIfSigQCorrecteds        =   await fetch("docsIfSigQCorrecteds", int),
                docsIfSigQUncorrectables    =   await fetch("docsIfSigQUncorrectables", int),
                docsIfSigQMicroreflections  =   await fetch("docsIfSigQMicroreflections", int),
                docsIfSigQExtUnerroreds     =   await fetch("docsIfSigQExtUnerroreds", int),
                docsIfSigQExtCorrecteds     =   await fetch("docsIfSigQExtCorrecteds", int),
                docsIfSigQExtUncorrectables =   await fetch("docsIfSigQExtUncorrectables", int),
                docsIf3SignalQualityExtRxMER =  await fetch("docsIf3SignalQualityExtRxMER", to_float)
            )


        return cls(
            index=index,
            channel_id=entry.docsIfDownChannelId or 0,
            entry=entry
        )

    @classmethod
    async def get(cls, snmp: Snmp_v2c, indices: list[int]) -> list[DocsIfDownstreamChannelEntry]:
        """
        Fetch multiple downstream SC-QAM entries in a single call.

        Parameters
        ----------
        snmp : Snmp_v2c
            Initialized SNMP v2c client.
        indices : List[int]
            Table indices (instances) to retrieve.

        Returns
        -------
        List[DocsIfDownstreamChannelEntry]
            A list of populated entries. If ``indices`` is empty or any index
            fails to fetch, the method logs a warning and continues.

        Examples
        --------
        >>> snmp = Snmp_v2c(host="192.168.0.100", community="public")
        >>> entries = await DocsIfDownstreamChannelEntry.get(snmp, [1, 2, 3])
        >>> [e.channel_id for e in entries]
        [1, 2, 3]
        """
        logger = logging.getLogger(cls.__name__)
        results: list[DocsIfDownstreamChannelEntry] = []

        if not indices:
            logger.warning("No downstream SC-QAM channel indices provided.")
            return results

        # Parallelize from_snmp calls for all indices
        import asyncio
        tasks = [cls.from_snmp(index, snmp) for index in indices]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        print(f"DEBUG: DocsIfDownstreamChannel.get() received {len(responses)} responses")
        print(f"DEBUG: Response types: {[type(r).__name__ for r in responses[:5]]}")
        print(f"DEBUG: First response: {responses[0] if responses else None}")
        
        for index, response in zip(indices, responses):
            if isinstance(response, Exception):
                logger.warning(f"Failed to retrieve downstream channel {index}: {response}")
            elif response is not None:
                results.append(response)
            else:
                print(f"DEBUG: Response for index {index} is None")

        return results
