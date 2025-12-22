## Agent Review Bundle Summary
- Goal: Add pytest coverage for RBW settings floor/ceil behavior.
- Changes: Add tests for getSpectrumRbwSetttings to validate to_floor behavior.
- Files: tests/test_rbw_conversion.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: many files would reformat); pytest -q (passed, 515 passed, 3 skipped: PNM_CM_IT)
- Notes: Ruff format check shows widespread formatting drift in repo; pytest skips hardware integration tests.

# FILE: tests/test_rbw_conversion.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026

from __future__ import annotations

import pytest

from pypnm.lib.conversions.rbw import RBWConversion
from pypnm.lib.types import NumBins, ResolutionBw, SegmentFreqSpan


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
