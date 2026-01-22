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
