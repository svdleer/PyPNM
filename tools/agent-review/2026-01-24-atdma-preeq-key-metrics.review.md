## Agent Review Bundle Summary
- Goal: Refactor ATDMA pre-eq key metrics implementation to align with repo rules.
- Changes: Added constants and expanded docstrings; updated SPDX year; clarified tap energy math.
- Files: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py.
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: existing repo drift); pytest -q.
- Notes: No behavior change intended.

# FILE: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import math
from typing import Final


class EqualizerMetrics:
    EXPECTED_TAP_COUNT: Final[int] = 24
    DEFAULT_NOMINAL_AMPLITUDE: Final[int] = 2047
    DEFAULT_MAIN_TAP_INDEX: Final[int] = 7

    def __init__(
        self,
        coefficients: list[tuple[int, int]],
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
            Symmetry ratio in dB, or NaN when adjacent taps are unavailable.
        """
        idx_prev = self.main_tap_index - 1
        idx_next = self.main_tap_index + 1
        if idx_prev < 0 or idx_next >= len(self.coefficients):
            return float('nan')  # Not enough data around main tap

        energy_prev = self._tap_energy(self.coefficients[idx_prev])
        energy_next = self._tap_energy(self.coefficients[idx_next])
        return 10 * math.log10(energy_next / energy_prev) if energy_prev != 0 else float('inf')
