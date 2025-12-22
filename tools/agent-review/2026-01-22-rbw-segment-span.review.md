## Agent Review Bundle Summary
- Goal: Complete RBW segment span conversion and add tests for new behavior.
- Changes: Implement getSegementFreqSpan with validation; add RBW conversion tests.
- Files: src/pypnm/lib/conversions/rbw.py; tests/test_rbw_conversion.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: many files would reformat); pytest -q (passed, 513 passed, 3 skipped: PNM_CM_IT)
- Notes: Ruff format check shows widespread formatting drift in repo; pytest skips hardware integration tests.

# FILE: src/pypnm/lib/conversions/rbw.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from math import ceil, floor

from pypnm.lib.types import FrequencyHz


class RBWConversion:
    """Conversion utilities for Resolution Bandwidth (RBW) values."""

    DEFAULT_SEGMENT_SPAN_HZ: FrequencyHz = FrequencyHz(1_000_000)
    DEFAULT_RBW_HZ: FrequencyHz = FrequencyHz(300_000)
    DEFAULT_NUM_BINS: int = 256

    @staticmethod
    def getNumBin(
        rbw: FrequencyHz,
        segment_freq_span: FrequencyHz = DEFAULT_SEGMENT_SPAN_HZ,
        to_floor: bool = True,
    ) -> int:
        """
        Calculate the number of bins for a given RBW and segment frequency span.

        Args:
            rbw: Resolution bandwidth for the segment in Hz.
            segment_freq_span: Segment span in Hz to divide into bins.
            to_floor: When True, floor the bin count; otherwise, ceil it.

        Returns:
            The computed number of bins.

        Raises:
            ValueError: When rbw or segment_freq_span is non-positive.
        """
        if rbw <= 0:
            raise ValueError("rbw must be positive.")
        if segment_freq_span <= 0:
            raise ValueError("segment_freq_span must be positive.")

        raw_bins = float(segment_freq_span) / float(rbw)
        bins = int(floor(raw_bins)) if to_floor else int(ceil(raw_bins))

        return bins

    @staticmethod
    def getSegementFreqSpan(rbw: FrequencyHz, num_of_bins: int) -> FrequencyHz:
        """
        Calculate segment frequency span from RBW and bin count.

        Args:
            rbw: Resolution bandwidth for the segment in Hz.
            num_of_bins: Number of bins in the segment.

        Returns:
            The computed segment frequency span in Hz.

        Raises:
            ValueError: When rbw or num_of_bins is non-positive.
        """
        if rbw <= 0:
            raise ValueError("rbw must be positive.")
        if num_of_bins <= 0:
            raise ValueError("num_of_bins must be positive.")

        return FrequencyHz(int(rbw) * num_of_bins)

# FILE: tests/test_rbw_conversion.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026

from __future__ import annotations

import pytest

from pypnm.lib.conversions.rbw import RBWConversion
from pypnm.lib.types import FrequencyHz


def test_rbw_conversion_segment_span() -> None:
    """
    Ensure segment span is computed from RBW and bin count.
    """
    span = RBWConversion.getSegementFreqSpan(FrequencyHz(300_000), 10)

    assert span == FrequencyHz(3_000_000)


def test_rbw_conversion_segment_span_rejects_invalid_rbw() -> None:
    """
    Ensure non-positive RBW values are rejected.
    """
    with pytest.raises(ValueError, match="rbw must be positive"):
        RBWConversion.getSegementFreqSpan(FrequencyHz(0), 10)


def test_rbw_conversion_segment_span_rejects_invalid_bins() -> None:
    """
    Ensure non-positive bin counts are rejected.
    """
    with pytest.raises(ValueError, match="num_of_bins must be positive"):
        RBWConversion.getSegementFreqSpan(FrequencyHz(300_000), 0)
