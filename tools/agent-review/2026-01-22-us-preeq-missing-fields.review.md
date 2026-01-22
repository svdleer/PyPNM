## Agent Review Bundle Summary
- Goal: Prevent US PreEq SNMP validation warnings by skipping incomplete entries and documenting the fix.
- Changes: Validate required SNMP fields before model creation, add tests for scaling and missing fields, document FAQ entry.
- Files: src/pypnm/docsis/data_type/pnm/DocsPnmCmUsPreEqEntry.py; tests/test_docs_pnm_us_preeq_entry_casts.py; docs/issues/index.md
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: would reformat many files); pytest -q
- Notes: Ruff format --check reports existing formatting drift across the repository.

# FILE: src/pypnm/docsis/data_type/pnm/DocsPnmCmUsPreEqEntry.py
from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia
import logging
from collections.abc import Callable
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel

from pypnm.lib.types import ChannelId
from pypnm.snmp.casts import measurement_status
from pypnm.snmp.snmp_v2c import Snmp_v2c

T = TypeVar("T")


class PreEqCoAdjStatus(Enum):
    """
    Enumeration of docsPnmCmUsPreEqPreEqCoAdjStatus.

    docsPnmCmUsPreEqPreEqCoAdjStatus OBJECT-TYPE
        SYNTAX      INTEGER {
                        other(1),
                        success(2),
                        clipped(3),
                        rejected(4)
                    }

    This represents whether the last set of Pre-Equalization coefficient
    adjustments were fully applied, clipped, rejected, or in some other state.

    Reference:
        CM-SP-CM-OSSI, CmUsPreEq::PreEqCoAdjStatus
    """

    OTHER    = 1  # Any state not described below
    SUCCESS  = 2  # Adjustments fully applied
    CLIPPED  = 3  # Partially applied due to excessive ripple/tilt
    REJECTED = 4  # Rejected / not applied

    def __str__(self) -> str:
        return self.name.lower()


class DocsPnmCmUsPreEqFields(BaseModel):
    docsPnmCmUsPreEqFileEnable: bool
    docsPnmCmUsPreEqAmpRipplePkToPk: float
    docsPnmCmUsPreEqAmpRippleRms: float
    docsPnmCmUsPreEqAmpSlope: float
    docsPnmCmUsPreEqGrpDelayRipplePkToPk: float
    docsPnmCmUsPreEqGrpDelayRippleRms: float
    docsPnmCmUsPreEqPreEqCoAdjStatus: str
    docsPnmCmUsPreEqMeasStatus: str
    docsPnmCmUsPreEqLastUpdateFileName: str
    docsPnmCmUsPreEqFileName: str
    docsPnmCmUsPreEqAmpMean: float
    docsPnmCmUsPreEqGrpDelaySlope: float
    docsPnmCmUsPreEqGrpDelayMean: float

class DocsPnmCmUsPreEqEntry(BaseModel):
    index: int
    channel_id: ChannelId
    entry: DocsPnmCmUsPreEqFields

    @staticmethod
    def thousandth_db(value: str | int | float) -> float:
        """
        Converts a ThousandthdB value (integer or string) to a float in dB.
        Example: 12345 -> 12.345 dB
        """
        try:
            return float(value) / 1000.0
        except (ValueError, TypeError):
            return float("nan")

    @staticmethod
    def thousandth_db_per_mhz(value: str | int | float) -> float:
        """
        Converts a ThousandthdB/MHz value to a float in dB/MHz.
        Example: 12345 -> 12.345 dB/MHz
        """
        try:
            return float(value) / 1000.0
        except (ValueError, TypeError):
            return float("nan")

    @staticmethod
    def thousandth_ns(value: str | int | float) -> float:
        """
        Converts a value expressed in units of 0.001 nsec to nsec.
        Example: 12345 -> 12.345 nsec
        """
        try:
            return float(value) / 1000.0
        except (ValueError, TypeError):
            return float("nan")

    @staticmethod
    def thousandth_ns_per_mhz(value: str | int | float) -> float:
        """
        Converts a ThousandthNsec/MHz value to nsec/MHz.
        Example: 12345 -> 12.345 nsec/MHz
        """
        try:
            return float(value) / 1000.0
        except (ValueError, TypeError):
            return float("nan")

    @staticmethod
    def to_pre_eq_status(value: str | int) -> PreEqCoAdjStatus:
        """
        Converts an integer value to PreEqCoAdjStatus enum.
        """
        try:
            return PreEqCoAdjStatus(int(value))
        except (ValueError, KeyError):
            return PreEqCoAdjStatus.OTHER

    @staticmethod
    def to_pre_eq_status_str(value: str | int) -> str:
        """
        Convert integer status to a lowercase string label (e.g. 'success').
        """
        return str(DocsPnmCmUsPreEqEntry.to_pre_eq_status(value))

    @classmethod
    async def from_snmp(cls, index: int, snmp: Snmp_v2c) -> DocsPnmCmUsPreEqEntry:
        logger = logging.getLogger(cls.__name__)
        async def fetch(oid: str, cast_fn: Callable[[object], T] | None = None) -> T | object | None:
            try:
                result = await snmp.get(f"{oid}.{index}")
                value = Snmp_v2c.get_result_value(result)
            except Exception as e:
                logger.warning("Fetch error for %s.%s: %s", oid, index, e)
                return None
            if value is None:
                return None
            if cast_fn is None:
                return value
            return cast_fn(value)

        raw_fields: dict[str, object | None] = {
            "docsPnmCmUsPreEqFileEnable": await fetch("docsPnmCmUsPreEqFileEnable", Snmp_v2c.truth_value),
            "docsPnmCmUsPreEqAmpRipplePkToPk": await fetch("docsPnmCmUsPreEqAmpRipplePkToPk", cls.thousandth_db),
            "docsPnmCmUsPreEqAmpRippleRms": await fetch("docsPnmCmUsPreEqAmpRippleRms", cls.thousandth_db),
            "docsPnmCmUsPreEqAmpSlope": await fetch("docsPnmCmUsPreEqAmpSlope", cls.thousandth_db_per_mhz),
            "docsPnmCmUsPreEqGrpDelayRipplePkToPk": await fetch("docsPnmCmUsPreEqGrpDelayRipplePkToPk", cls.thousandth_ns),
            "docsPnmCmUsPreEqGrpDelayRippleRms": await fetch("docsPnmCmUsPreEqGrpDelayRippleRms", cls.thousandth_ns),
            "docsPnmCmUsPreEqPreEqCoAdjStatus": await fetch("docsPnmCmUsPreEqPreEqCoAdjStatus", cls.to_pre_eq_status_str),
            "docsPnmCmUsPreEqMeasStatus": await fetch("docsPnmCmUsPreEqMeasStatus", measurement_status),
            "docsPnmCmUsPreEqLastUpdateFileName": await fetch("docsPnmCmUsPreEqLastUpdateFileName", str),
            "docsPnmCmUsPreEqFileName": await fetch("docsPnmCmUsPreEqFileName", str),
            "docsPnmCmUsPreEqAmpMean": await fetch("docsPnmCmUsPreEqAmpMean", cls.thousandth_db),
            "docsPnmCmUsPreEqGrpDelaySlope": await fetch("docsPnmCmUsPreEqGrpDelaySlope", cls.thousandth_ns_per_mhz),
            "docsPnmCmUsPreEqGrpDelayMean": await fetch("docsPnmCmUsPreEqGrpDelayMean", cls.thousandth_ns),
        }
        missing_fields = [key for key, value in raw_fields.items() if value is None]
        if missing_fields:
            raise ValueError(f"Missing required SNMP fields: {', '.join(missing_fields)}")

        fields_payload: dict[str, object] = {
            key: value for key, value in raw_fields.items() if value is not None
        }
        fields = DocsPnmCmUsPreEqFields(**fields_payload)

        channel_id = await fetch("docsIf31CmUsOfdmaChanChannelId", ChannelId) or ChannelId(index)
        return cls(index=index, channel_id=channel_id, entry=fields)

    @classmethod
    async def get(cls, snmp: Snmp_v2c, indices: list[int]) -> list[DocsPnmCmUsPreEqEntry]:
        logger = logging.getLogger(cls.__name__)
        results: list[DocsPnmCmUsPreEqEntry] = []

        async def fetch_entry(idx: int) -> DocsPnmCmUsPreEqEntry | None:
            try:
                return await cls.from_snmp(idx, snmp)
            except Exception as e:
                logger.warning("Failed to fetch US PreEq entry for index %s: %s", idx, e)
                return None

        for idx in indices:
            entry = await fetch_entry(idx)
            if entry is not None:
                results.append(entry)

        return results


# FILE: tests/test_docs_pnm_us_preeq_entry_casts.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026

from __future__ import annotations

import pytest

from pypnm.docsis.data_type.pnm.DocsPnmCmUsPreEqEntry import (
    DocsPnmCmUsPreEqEntry,
    DocsPnmCmUsPreEqFields,
)
from pypnm.snmp.snmp_v2c import Snmp_v2c


class _FakeSnmp:
    def __init__(self, idx: int, table: dict[str, object]):
        self._idx = idx
        self._t = table

    async def get(self, oq: str):
        sym, _, sfx = oq.rpartition(".")
        assert int(sfx) == self._idx
        return self._t[sym]


@pytest.mark.asyncio
async def test_from_snmp_scaling_and_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Happy-path test:
      • get_result_value is pass-through
      • fixed-point fields scale by /1000.0
      • status values are mapped to lowercase strings
      • channel_id pulls from OFDMA channel ID when present
    """
    monkeypatch.setattr(Snmp_v2c, "get_result_value", staticmethod(lambda x: x))

    idx = 83
    fake = _FakeSnmp(idx, {
        "docsPnmCmUsPreEqFileEnable": 1,
        "docsPnmCmUsPreEqAmpRipplePkToPk": 12345,
        "docsPnmCmUsPreEqAmpRippleRms": 2000,
        "docsPnmCmUsPreEqAmpSlope": 500,
        "docsPnmCmUsPreEqGrpDelayRipplePkToPk": 9000,
        "docsPnmCmUsPreEqGrpDelayRippleRms": 11000,
        "docsPnmCmUsPreEqPreEqCoAdjStatus": 2,
        "docsPnmCmUsPreEqMeasStatus": 4,
        "docsPnmCmUsPreEqLastUpdateFileName": "pre_eq_last.bin",
        "docsPnmCmUsPreEqFileName": "pre_eq.bin",
        "docsPnmCmUsPreEqAmpMean": 4000,
        "docsPnmCmUsPreEqGrpDelaySlope": 2500,
        "docsPnmCmUsPreEqGrpDelayMean": 3000,
        "docsIf31CmUsOfdmaChanChannelId": 9,
    })

    entry = await DocsPnmCmUsPreEqEntry.from_snmp(idx, fake)  # type: ignore[arg-type]
    assert entry.index == idx
    assert entry.channel_id == 9

    fields: DocsPnmCmUsPreEqFields = entry.entry
    assert fields.docsPnmCmUsPreEqFileEnable is True
    assert fields.docsPnmCmUsPreEqPreEqCoAdjStatus == "success"
    assert fields.docsPnmCmUsPreEqMeasStatus == "sample_ready"
    assert fields.docsPnmCmUsPreEqLastUpdateFileName == "pre_eq_last.bin"
    assert fields.docsPnmCmUsPreEqFileName == "pre_eq.bin"

    assert fields.docsPnmCmUsPreEqAmpRipplePkToPk == pytest.approx(12.345, abs=0.0)
    assert fields.docsPnmCmUsPreEqAmpRippleRms == pytest.approx(2.0, abs=0.0)
    assert fields.docsPnmCmUsPreEqAmpSlope == pytest.approx(0.5, abs=0.0)
    assert fields.docsPnmCmUsPreEqGrpDelayRipplePkToPk == pytest.approx(9.0, abs=0.0)
    assert fields.docsPnmCmUsPreEqGrpDelayRippleRms == pytest.approx(11.0, abs=0.0)
    assert fields.docsPnmCmUsPreEqAmpMean == pytest.approx(4.0, abs=0.0)
    assert fields.docsPnmCmUsPreEqGrpDelaySlope == pytest.approx(2.5, abs=0.0)
    assert fields.docsPnmCmUsPreEqGrpDelayMean == pytest.approx(3.0, abs=0.0)


@pytest.mark.asyncio
async def test_from_snmp_missing_required_fields_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Missing any required SNMP field should raise ValueError and skip the entry.
    """
    monkeypatch.setattr(Snmp_v2c, "get_result_value", staticmethod(lambda x: x))

    idx = 3
    fake = _FakeSnmp(idx, {
        "docsPnmCmUsPreEqFileEnable": 1,
        "docsPnmCmUsPreEqAmpRipplePkToPk": 1000,
        "docsPnmCmUsPreEqAmpRippleRms": 2000,
        # Missing docsPnmCmUsPreEqAmpSlope
        "docsPnmCmUsPreEqGrpDelayRipplePkToPk": 1000,
        "docsPnmCmUsPreEqGrpDelayRippleRms": 1000,
        "docsPnmCmUsPreEqPreEqCoAdjStatus": 1,
        "docsPnmCmUsPreEqMeasStatus": 2,
        "docsPnmCmUsPreEqLastUpdateFileName": "pre_eq_last.bin",
        "docsPnmCmUsPreEqFileName": "pre_eq.bin",
        "docsPnmCmUsPreEqAmpMean": 1000,
        "docsPnmCmUsPreEqGrpDelaySlope": 1000,
        "docsPnmCmUsPreEqGrpDelayMean": 1000,
    })

    with pytest.raises(ValueError) as exc:
        await DocsPnmCmUsPreEqEntry.from_snmp(idx, fake)  # type: ignore[arg-type]

    assert "docsPnmCmUsPreEqAmpSlope" in str(exc.value)


# FILE: docs/issues/index.md
# Reporting Issues

If you encounter a bug or unexpected behavior while using PyPNM, please report it
so we can investigate and resolve the issue. This document outlines the steps to
create a support bundle that captures the necessary data for debugging.

[REPORTING ISSUES](reporting-issues.md)

## Support Bundle Script

PyPNM includes a support bundle script that collects relevant logs, database
entries, and configuration files related to your issue. This script helps
sanitize sensitive information before sharing it with the PyPNM support team.

[Support Bundle Builder](support-bundle.md)

## FAQ

Q: Why is extension data missing after processing a PNM transaction record?  
A: Ensure the transaction record includes an `extension` mapping and that the update helper merges the extension into the PNM data before returning the result.

Q: Why does US PreEq SNMP retrieval log validation errors about missing fields?  
A: Some modems return sparse or empty entries for certain indices. Ensure the device supports the table and that the entry is populated; missing required fields will cause the entry to be skipped.

## TODO

- Add or update a FAQ entry whenever an error is fixed so the resolution is documented.
- Add FAQ entries when SNMP validation errors are addressed to capture the resolution.

