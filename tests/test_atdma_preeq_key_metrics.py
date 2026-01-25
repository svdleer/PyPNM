# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import math

import pytest

from pypnm.lib.types import ImginaryInt, PreEqAtdmaCoefficients, RealInt
from pypnm.pnm.analysis.atdma_preeq_key_metrics import EqualizerMetrics


def _coeff(real: int, imag: int) -> PreEqAtdmaCoefficients:
    return (RealInt(real), ImginaryInt(imag))


def _coeff_list() -> list[PreEqAtdmaCoefficients]:
    return [_coeff(0, 0) for _ in range(EqualizerMetrics.EXPECTED_TAP_COUNT)]


def test_pre_post_tap_symmetry_ratio_uses_pre_over_post() -> None:
    coefficients = _coeff_list()
    coefficients[6] = _coeff(2, 0)  # F7 energy = 4
    coefficients[8] = _coeff(1, 0)  # F9 energy = 1

    metrics = EqualizerMetrics(coefficients=coefficients)
    expected = 10 * math.log10(4.0)
    assert metrics.pre_post_tap_symmetry_ratio() == pytest.approx(expected, abs=1e-6)


def test_frequency_response_impulse_is_flat() -> None:
    coefficients = _coeff_list()
    coefficients[0] = _coeff(1, 0)

    response = EqualizerMetrics(coefficients=coefficients).frequency_response()
    assert response.fft_size == EqualizerMetrics.EXPECTED_TAP_COUNT
    assert all(value == pytest.approx(1.0, abs=1e-12) for value in response.magnitude)
    assert response.magnitude_power_db[0] == pytest.approx(0.0, abs=1e-12)
    assert all(value == pytest.approx(0.0, abs=1e-12) for value in response.magnitude_power_db_normalized)
