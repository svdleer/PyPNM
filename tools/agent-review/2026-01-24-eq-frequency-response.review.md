## Agent Review Bundle Summary
- Goal: Add frequency response computation for pre-eq tap IQ data.
- Changes: Add FFT-based frequency response classes/models and tests; expose response via metrics.
- Files: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py; tests/test_atdma_preeq_key_metrics.py
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: repo drift); pytest -q
- Notes: Ruff format would reformat many existing files; no formatting applied.

# FILE: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import math
from typing import Final

import numpy as np
from pydantic import BaseModel, Field

from pypnm.lib.types import PreEqAtdmaCoefficients


class EqualizerMetrics:
    EXPECTED_TAP_COUNT: Final[int] = 24
    DEFAULT_NOMINAL_AMPLITUDE: Final[int] = 2047
    DEFAULT_MAIN_TAP_INDEX: Final[int] = 7

    def __init__(
        self,
        coefficients: list[PreEqAtdmaCoefficients],
        nominal_amplitude: int = DEFAULT_NOMINAL_AMPLITUDE,
        main_tap_index: int = DEFAULT_MAIN_TAP_INDEX,
    ) -> None:
        """
        Initialize EqualizerMetrics.

        Args:
            coefficients: A list of 24 (real, imag) coefficient pairs.
            nominal_amplitude: CM implementation nominal amplitude.
            main_tap_index: Main tap index (0-based). Defaults to F8 for ATDMA.
        """
        if len(coefficients) != self.EXPECTED_TAP_COUNT:
            raise ValueError("Exactly 24 complex (real, imag) coefficients are required.")
        self.coefficients = coefficients
        self.nominal_amplitude = nominal_amplitude
        self.main_tap_index = main_tap_index

    def _tap_energy(self, tap: tuple[int, int]) -> float:
        """Compute energy of a single complex tap as real^2 + imag^2."""
        real, imag = tap
        return real**2 + imag**2

    def main_tap_energy(self) -> float:
        """
        6.3.1: Main Tap Energy (MTE).

        Returns:
            Energy of the main tap derived from its real/imag coefficient pair.
        """
        return self._tap_energy(self.coefficients[self.main_tap_index])

    def main_tap_nominal_energy(self) -> float:
        """
        6.3.2: Main Tap Nominal Energy (MTNE).

        Returns:
            Nominal tap energy based on the configured nominal amplitude.
        """
        return self.nominal_amplitude**2 * 2

    def pre_main_tap_energy(self) -> float:
        """
        6.3.3: Pre-Main Tap Energy (PreMTE).

        Returns:
            Total energy of taps before the main tap.
        """
        return sum(self._tap_energy(tap) for tap in self.coefficients[:self.main_tap_index])

    def post_main_tap_energy(self) -> float:
        """
        6.3.4: Post-Main Tap Energy (PostMTE).

        Returns:
            Total energy of taps after the main tap.
        """
        return sum(self._tap_energy(tap) for tap in self.coefficients[self.main_tap_index + 1:])

    def total_tap_energy(self) -> float:
        """
        6.3.5: Total Tap Energy (TTE).

        Returns:
            Total energy across all taps.
        """
        return sum(self._tap_energy(tap) for tap in self.coefficients)

    def main_tap_compression(self) -> float:
        """
        6.3.6: Main Tap Compression (MTC), in dB.

        Returns:
            Compression ratio of total tap energy to main tap energy in dB.
        """
        mte = self.main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(tte / mte) if mte != 0 else float('inf')

    def main_tap_ratio(self) -> float:
        """
        6.3.7: Main Tap Ratio (MTR), in dB.

        Returns:
            Ratio of main tap energy to all other taps in dB.
        """
        mte = self.main_tap_energy()
        other = self.total_tap_energy() - mte
        return 10 * math.log10(mte / other) if other != 0 else float('inf')

    def non_main_tap_energy_ratio(self) -> float:
        """
        6.3.8: Non-Main Tap to Total Energy Ratio (NMTER), in dB.

        Returns:
            Ratio of non-main tap energy to total energy in dB.
        """
        non_main = self.pre_main_tap_energy() + self.post_main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(non_main / tte) if tte != 0 else float('-inf')

    def pre_main_tap_total_energy_ratio(self) -> float:
        """
        6.3.9: Pre-Main Tap to Total Energy Ratio (PreMTTER), in dB.

        Returns:
            Ratio of pre-main tap energy to total energy in dB.
        """
        pre = self.pre_main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(pre / tte) if tte != 0 else float('-inf')

    def post_main_tap_total_energy_ratio(self) -> float:
        """
        6.3.10: Post-Main Tap to Total Energy Ratio (PostMTTER), in dB.

        Returns:
            Ratio of post-main tap energy to total energy in dB.
        """
        post = self.post_main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(post / tte) if tte != 0 else float('-inf')

    def pre_post_energy_symmetry_ratio(self) -> float:
        """
        6.3.11: Pre-Post Energy Symmetry Ratio (PPESR), in dB.

        Returns:
            Ratio of post-main tap energy to pre-main tap energy in dB.
        """
        pre = self.pre_main_tap_energy()
        post = self.post_main_tap_energy()
        return 10 * math.log10(post / pre) if pre != 0 else float('inf')

    def pre_post_tap_symmetry_ratio(self) -> float:
        """
        6.3.11 (approx): Pre-Post Tap Symmetry Ratio (PPTSR), in dB.

        Uses only taps adjacent to the main tap (main-1 and main+1).

        Returns:
            Symmetry ratio in dB (pre/post), or NaN when adjacent taps are unavailable.
        """
        idx_prev = self.main_tap_index - 1
        idx_next = self.main_tap_index + 1
        if idx_prev < 0 or idx_next >= len(self.coefficients):
            return float('nan')  # Not enough data around main tap

        energy_prev = self._tap_energy(self.coefficients[idx_prev])
        energy_next = self._tap_energy(self.coefficients[idx_next])
        return 10 * math.log10(energy_prev / energy_next) if energy_next != 0 else float('inf')

    def frequency_response(self) -> EqualizerFrequencyResponseModel:
        """
        Compute the frequency response from the time-domain tap coefficients.

        Returns:
            EqualizerFrequencyResponseModel with normalized frequency bins and response metrics.
        """
        return EqualizerFrequencyResponse(coefficients=self.coefficients).to_model()

    def to_model(self) -> EqualizerMetricsModel:
        """
        Build a serialized metrics model with all computed values.

        Returns:
            EqualizerMetricsModel populated from the current coefficient set.
        """
        return EqualizerMetricsModel(
            main_tap_energy=self.main_tap_energy(),
            main_tap_nominal_energy=self.main_tap_nominal_energy(),
            pre_main_tap_energy=self.pre_main_tap_energy(),
            post_main_tap_energy=self.post_main_tap_energy(),
            total_tap_energy=self.total_tap_energy(),
            main_tap_compression=self.main_tap_compression(),
            main_tap_ratio=self.main_tap_ratio(),
            non_main_tap_energy_ratio=self.non_main_tap_energy_ratio(),
            pre_main_tap_total_energy_ratio=self.pre_main_tap_total_energy_ratio(),
            post_main_tap_total_energy_ratio=self.post_main_tap_total_energy_ratio(),
            pre_post_energy_symmetry_ratio=self.pre_post_energy_symmetry_ratio(),
            pre_post_tap_symmetry_ratio=self.pre_post_tap_symmetry_ratio(),
            frequency_response=self.frequency_response(),
        )


class EqualizerMetricsModel(BaseModel):
    main_tap_energy: float = Field(..., description="Main tap energy (MTE).")
    main_tap_nominal_energy: float = Field(..., description="Main tap nominal energy (MTNE).")
    pre_main_tap_energy: float = Field(..., description="Pre-main tap energy (PreMTE).")
    post_main_tap_energy: float = Field(..., description="Post-main tap energy (PostMTE).")
    total_tap_energy: float = Field(..., description="Total tap energy (TTE).")
    main_tap_compression: float = Field(..., description="Main tap compression (MTC) in dB.")
    main_tap_ratio: float = Field(..., description="Main tap ratio (MTR) in dB.")
    non_main_tap_energy_ratio: float = Field(..., description="Non-main tap to total energy ratio (NMTER) in dB.")
    pre_main_tap_total_energy_ratio: float = Field(..., description="Pre-main tap to total energy ratio (PreMTTER) in dB.")
    post_main_tap_total_energy_ratio: float = Field(..., description="Post-main tap to total energy ratio (PostMTTER) in dB.")
    pre_post_energy_symmetry_ratio: float = Field(..., description="Pre-post energy symmetry ratio (PPESR) in dB.")
    pre_post_tap_symmetry_ratio: float = Field(..., description="Pre-post tap symmetry ratio (PPTSR) in dB.")
    frequency_response: EqualizerFrequencyResponseModel = Field(..., description="Frequency response derived from tap coefficients.")

    model_config = {"frozen": True}


class EqualizerFrequencyResponse:
    def __init__(self, coefficients: list[PreEqAtdmaCoefficients]) -> None:
        """
        Initialize a frequency response builder.

        Args:
            coefficients: A list of (real, imag) coefficient pairs.
        """
        self.coefficients = coefficients

    def to_model(self, fft_size: int | None = None) -> EqualizerFrequencyResponseModel:
        """
        Build a frequency response model from tap coefficients.

        Args:
            fft_size: Optional FFT size. When None, uses the coefficient length.

        Returns:
            EqualizerFrequencyResponseModel with frequency bins, magnitude, dB, and phase.
        """
        taps = np.array(
            [complex(float(real), float(imag)) for real, imag in self.coefficients],
            dtype=np.complex128,
        )
        size = fft_size if fft_size is not None else int(taps.size)
        if size < int(taps.size):
            raise ValueError("fft_size must be >= number of coefficients.")

        response = np.fft.fft(taps, n=size)
        magnitude = np.abs(response).astype(float)
        magnitude_power_db = [
            (10.0 * math.log10(value * value) if value > 0.0 else None)
            for value in magnitude
        ]
        phase = np.angle(response).astype(float)
        bins = [idx / float(size) for idx in range(size)]

        return EqualizerFrequencyResponseModel(
            fft_size=size,
            frequency_bins=bins,
            magnitude=magnitude.tolist(),
            magnitude_power_db=magnitude_power_db,
            phase_radians=phase.tolist(),
        )


class EqualizerFrequencyResponseModel(BaseModel):
    fft_size: int = Field(..., description="FFT size used to compute the frequency response.")
    frequency_bins: list[float] = Field(..., description="Normalized frequency bins (0 to 1, inclusive of 0, exclusive of 1).")
    magnitude: list[float] = Field(..., description="Magnitude response for each frequency bin.")
    magnitude_power_db: list[float | None] = Field(..., description="Magnitude power in dB for each bin; None when magnitude is 0.")
    phase_radians: list[float] = Field(..., description="Phase response in radians for each frequency bin.")

    model_config = {"frozen": True}

# FILE: tests/test_atdma_preeq_key_metrics.py
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
