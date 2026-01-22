## Agent Review Bundle Summary
- Goal: Improve RBW bin conversion utility and add validation.
- Changes: Add SPDX header, expand docstring, validate inputs, simplify bin calculation, and clean imports.
- Files: src/pypnm/lib/conversions/rbw.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: many files would reformat); pytest -q (passed, 510 passed, 3 skipped: PNM_CM_IT)
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
