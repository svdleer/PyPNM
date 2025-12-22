## Agent Review Bundle Summary
- Goal: Update RBW settings to honor frequency span with floor/ceil selection and cover with tests.
- Changes: Use frequency_span when selecting segment span, respect to_floor when binning, add tests for floor/ceil and span behavior.
- Files: src/pypnm/lib/conversions/rbw.py; tests/test_rbw_conversion.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: would reformat many files); pytest -q
- Notes: Ruff format --check fails repository-wide; not modified per instruction.

# FILE: src/pypnm/lib/conversions/rbw.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from math import ceil, floor

from pypnm.lib.types import (
    FrequencyHz,
    NumBins,
    ResolutionBw,
    ResolutionBwSettings,
    SegmentFreqSpan,
)

DEFAULT_FREQUENCY_SPAN_HZ: FrequencyHz = FrequencyHz(0)


class RBWConversion:
    """Conversion utilities for Resolution Bandwidth (RBW) values."""

    DEFAULT_SEGMENT_SPAN_HZ: SegmentFreqSpan = SegmentFreqSpan(1_000_000)
    DEFAULT_RBW_HZ: ResolutionBw = ResolutionBw(300_000)
    DEFAULT_NUM_BINS: NumBins = NumBins(256)
    DEFAULT_NUM_BINS_300_KHZ: NumBins = NumBins(3)

    @staticmethod
    def getNumBin(
        rbw: ResolutionBw = DEFAULT_RBW_HZ,
        segment_freq_span: SegmentFreqSpan = DEFAULT_SEGMENT_SPAN_HZ,
        to_floor: bool = True,
    ) -> NumBins:
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

        return NumBins(bins)

    @staticmethod
    def getSegementFreqSpan(
        rbw: ResolutionBw = DEFAULT_RBW_HZ,
        num_of_bins: NumBins = DEFAULT_NUM_BINS_300_KHZ,
    ) -> SegmentFreqSpan:
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

        return SegmentFreqSpan(int(rbw) * int(num_of_bins))

    @staticmethod
    def getSpectrumRbwSetttings(
        rbw: ResolutionBw,
        frequency_span: FrequencyHz = DEFAULT_FREQUENCY_SPAN_HZ,
        to_floor: bool = True,
    ) -> ResolutionBwSettings:
        """
        Build RBW settings tuple for the provided resolution bandwidth.

        Args:
            rbw: Resolution bandwidth in Hz.
            frequency_span: Frequency span in Hz (defaults to the standard span).
            to_floor: When True, floor the bin count; otherwise, ceil it.

        Returns:
            Tuple of (rbw, num_bins, segment_freq_span).
        """
        segment_span = RBWConversion.DEFAULT_SEGMENT_SPAN_HZ
        if frequency_span > 0:
            span_hz = max(int(frequency_span), int(segment_span))
            segment_span = SegmentFreqSpan(span_hz)

        bins = RBWConversion.getNumBin(
            rbw=rbw,
            segment_freq_span=segment_span,
            to_floor=to_floor,
        )

        return (rbw, bins, segment_span)


# FILE: tests/test_rbw_conversion.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026

from __future__ import annotations

import pytest

from pypnm.lib.conversions.rbw import RBWConversion
from pypnm.lib.types import FrequencyHz, NumBins, ResolutionBw, SegmentFreqSpan


def test_rbw_conversion_segment_span() -> None:
    """
    Ensure segment span is computed from RBW and bin count.
    """
    span = RBWConversion.getSegementFreqSpan(ResolutionBw(300_000), NumBins(10))

    assert span == SegmentFreqSpan(3_000_000)


def test_rbw_conversion_segment_span_rejects_invalid_rbw() -> None:
    """
    Ensure non-positive RBW values are rejected.
    """
    with pytest.raises(ValueError, match="rbw must be positive"):
        RBWConversion.getSegementFreqSpan(ResolutionBw(0), NumBins(10))


def test_rbw_conversion_segment_span_rejects_invalid_bins() -> None:
    """
    Ensure non-positive bin counts are rejected.
    """
    with pytest.raises(ValueError, match="num_of_bins must be positive"):
        RBWConversion.getSegementFreqSpan(ResolutionBw(300_000), NumBins(0))


def test_rbw_conversion_settings_floor() -> None:
    """
    Ensure RBW settings honor floor selection for bin count.
    """
    rbw = ResolutionBw(300_000)

    settings = RBWConversion.getSpectrumRbwSetttings(rbw, to_floor=True)

    assert settings == (rbw, NumBins(3), SegmentFreqSpan(1_000_000))


def test_rbw_conversion_settings_ceil() -> None:
    """
    Ensure RBW settings honor ceiling selection for bin count.
    """
    rbw = ResolutionBw(300_000)

    settings = RBWConversion.getSpectrumRbwSetttings(rbw, to_floor=False)

    assert settings == (rbw, NumBins(4), SegmentFreqSpan(1_000_000))


def test_rbw_conversion_settings_min_span() -> None:
    """
    Ensure frequency_span below the default uses the default span.
    """
    rbw = ResolutionBw(300_000)

    settings = RBWConversion.getSpectrumRbwSetttings(
        rbw,
        frequency_span=FrequencyHz(500_000),
        to_floor=True,
    )

    assert settings == (rbw, NumBins(3), SegmentFreqSpan(1_000_000))


def test_rbw_conversion_settings_custom_span() -> None:
    """
    Ensure frequency_span above the default is honored.
    """
    rbw = ResolutionBw(300_000)

    settings = RBWConversion.getSpectrumRbwSetttings(
        rbw,
        frequency_span=FrequencyHz(1_200_000),
        to_floor=True,
    )

    assert settings == (rbw, NumBins(4), SegmentFreqSpan(1_200_000))

