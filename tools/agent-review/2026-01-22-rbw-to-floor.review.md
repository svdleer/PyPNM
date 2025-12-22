## Agent Review Bundle Summary
- Goal: Wire the new to_floor parameter into RBW settings selection.
- Changes: Update getSpectrumRbwSetttings signature, docstring, and bin selection path to honor to_floor.
- Files: src/pypnm/lib/conversions/rbw.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: many files would reformat); pytest -q (passed, 513 passed, 3 skipped: PNM_CM_IT)
- Notes: Ruff format check shows widespread formatting drift in repo; pytest skips hardware integration tests.

# FILE: src/pypnm/lib/conversions/rbw.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from math import ceil, floor

from pypnm.lib.types import (
    NumBins,
    ResolutionBw,
    ResolutionBwSettings,
    SegmentFreqSpan,
)


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
        to_floor: bool,
    ) -> ResolutionBwSettings:
        """
        Build RBW settings tuple for the provided resolution bandwidth.

        Args:
            rbw: Resolution bandwidth in Hz.
            to_floor: When True, floor the bin count; otherwise, ceil it.

        Returns:
            Tuple of (rbw, num_bins, segment_freq_span).
        """
        bins = RBWConversion.getNumBin(
            rbw=rbw,
            segment_freq_span=RBWConversion.DEFAULT_SEGMENT_SPAN_HZ,
            to_floor=to_floor,
        )

        return (rbw, bins, RBWConversion.DEFAULT_SEGMENT_SPAN_HZ)
