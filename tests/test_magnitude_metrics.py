# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import math
from typing import cast

import numpy as np
import pytest

from pypnm.lib.signal_processing.magnitude_metrics import (
    MagnitudeSummaryMetrics,
    compute_magnitude_summary,
)
from pypnm.lib.types import ComplexArray, FloatSeries, FrequencyHz


def _build_complex_from_db(y_db: FloatSeries) -> ComplexArray:
    """
    Given desired dB magnitude per subcarrier, synthesize [re, im] pairs
    whose power equals 10^(y_db/10). Use re = sqrt(power), im = 0.
    """
    pow_lin = (10.0 ** (np.asarray(y_db, dtype=float) / 10.0)).tolist()
    return cast(ComplexArray, [[math.sqrt(p), 0.0] for p in pow_lin])


def test_magnitude_metrics_perfect_line() -> None:
    """
    Synthetic data on a perfect line: y_db = a + b*x, no ripple.
    Expect slope≈b, mean≈mean(y), RMS ripple≈0, P2P≈0.
    """
    x_mhz = np.linspace(100.0, 200.0, 101)  # 100..200 MHz
    x_hz: FrequencyHz = cast(FrequencyHz, (x_mhz * 1e6).tolist())

    a = -20.0
    b = -0.0128  # dB/MHz
    y_db: FloatSeries = (a + b * x_mhz).tolist()

    coeffs: ComplexArray = _build_complex_from_db(y_db)

    metrics = compute_magnitude_summary(x_hz, coeffs)
    assert isinstance(metrics, MagnitudeSummaryMetrics)
    assert metrics.slope_db_per_mhz == pytest.approx(b, rel=1e-6, abs=1e-6)
    assert metrics.mean_db == pytest.approx(float(np.mean(y_db)), rel=1e-12)
    assert metrics.rms_ripple_db == pytest.approx(0.0, abs=1e-12)
    assert metrics.p2p_ripple_db == pytest.approx(0.0, abs=1e-12)
    assert len(metrics.fitted_line_db) == len(y_db)


def test_magnitude_metrics_line_plus_sinusoidal_ripple() -> None:
    """
    y_db = a + b*x + A*sin(2πk * normalized_index)

    We compare:
      - slope to OLS on the actual synthesized (x, y) data
      - RMS ripple to ~A/sqrt(2) (allowing tolerance)
      - P2P ripple to the OLS residual peak-to-peak
    """
    x_mhz = np.linspace(50.0, 85.0, 141)
    x_hz: FrequencyHz = cast(FrequencyHz, (x_mhz * 1e6).tolist())

    a = -20.2224
    b = -0.0128
    A = 0.5
    k = 3.0

    idx = np.arange(len(x_mhz), dtype=float)
    ripple = A * np.sin(2.0 * math.pi * k * (idx / max(1.0, (len(idx) - 1))))
    y_db: FloatSeries = (a + b * x_mhz + ripple).tolist()

    coeffs: ComplexArray = _build_complex_from_db(y_db)
    m = compute_magnitude_summary(x_hz, coeffs)

    # OLS on the synthetic (x, y) used
    X = np.column_stack([np.ones_like(x_mhz), x_mhz])
    beta, *_ = np.linalg.lstsq(X, np.asarray(y_db, dtype=float), rcond=None)
    a_hat, b_hat = float(beta[0]), float(beta[1])
    assert m.slope_db_per_mhz == pytest.approx(b_hat, rel=1e-6, abs=1e-8)

    # Mean of y_db
    assert m.mean_db == pytest.approx(float(np.mean(y_db)), rel=1e-12)

    # RMS ripple ~ A/sqrt(2)
    expected_rms = A / math.sqrt(2.0)
    assert m.rms_ripple_db == pytest.approx(expected_rms, rel=0.05)

    # P2P ripple from OLS residuals
    y_hat_np = a_hat + b_hat * x_mhz
    residuals = np.asarray(y_db, dtype=float) - y_hat_np
    p2p_expected = float(np.max(residuals) - np.min(residuals))
    assert m.p2p_ripple_db == pytest.approx(p2p_expected, rel=1e-6, abs=1e-8)


def test_magnitude_metrics_noncontiguous_frequencies() -> None:
    """
    Ensure it works with non-contiguous subcarrier frequencies.
    """
    x_mhz = np.array([101.0, 103.5, 110.0, 150.0, 151.6])
    x_hz: FrequencyHz = cast(FrequencyHz, (x_mhz * 1e6).tolist())

    a = -18.0
    b = -0.02
    y_db: FloatSeries = (a + b * x_mhz).tolist()

    coeffs: ComplexArray = _build_complex_from_db(y_db)
    m = compute_magnitude_summary(x_hz, coeffs)

    assert m.slope_db_per_mhz == pytest.approx(b, rel=1e-6)
    assert m.mean_db == pytest.approx(float(np.mean(y_db)), rel=1e-12)
    assert m.rms_ripple_db == pytest.approx(0.0, abs=1e-12)
    assert m.p2p_ripple_db == pytest.approx(0.0, abs=1e-12)
