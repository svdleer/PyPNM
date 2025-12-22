# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Final

import numpy as np
from pydantic import BaseModel, Field

from pypnm.lib.constants import FEET_PER_METER, SPEED_OF_LIGHT, CableType
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
        return sum(self._tap_energy(tap) for tap in self.coefficients[self.main_tap_index + 1 :])

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
        return 10 * math.log10(tte / mte) if mte != 0 else float("inf")

    def main_tap_ratio(self) -> float:
        """
        6.3.7: Main Tap Ratio (MTR), in dB.

        Returns:
            Ratio of main tap energy to all other taps in dB.
        """
        mte = self.main_tap_energy()
        other = self.total_tap_energy() - mte
        return 10 * math.log10(mte / other) if other != 0 else float("inf")

    def non_main_tap_energy_ratio(self) -> float:
        """
        6.3.8: Non-Main Tap to Total Energy Ratio (NMTER), in dB.

        Returns:
            Ratio of non-main tap energy to total energy in dB.
        """
        non_main = self.pre_main_tap_energy() + self.post_main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(non_main / tte) if tte != 0 else float("-inf")

    def pre_main_tap_total_energy_ratio(self) -> float:
        """
        6.3.9: Pre-Main Tap to Total Energy Ratio (PreMTTER), in dB.

        Returns:
            Ratio of pre-main tap energy to total energy in dB.
        """
        pre = self.pre_main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(pre / tte) if tte != 0 else float("-inf")

    def post_main_tap_total_energy_ratio(self) -> float:
        """
        6.3.10: Post-Main Tap to Total Energy Ratio (PostMTTER), in dB.

        Returns:
            Ratio of post-main tap energy to total energy in dB.
        """
        post = self.post_main_tap_energy()
        tte = self.total_tap_energy()
        return 10 * math.log10(post / tte) if tte != 0 else float("-inf")

    def pre_post_energy_symmetry_ratio(self) -> float:
        """
        6.3.11: Pre-Post Energy Symmetry Ratio (PPESR), in dB.

        Returns:
            Ratio of post-main tap energy to pre-main tap energy in dB.
        """
        pre = self.pre_main_tap_energy()
        post = self.post_main_tap_energy()
        return 10 * math.log10(post / pre) if pre != 0 else float("inf")

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
            return float("nan")

        energy_prev = self._tap_energy(self.coefficients[idx_prev])
        energy_next = self._tap_energy(self.coefficients[idx_next])
        return 10 * math.log10(energy_prev / energy_next) if energy_next != 0 else float("inf")

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
        magnitude_power_db_normalized = self._normalize_to_dc(magnitude_power_db)
        phase = np.angle(response).astype(float)
        bins = [idx / float(size) for idx in range(size)]

        return EqualizerFrequencyResponseModel(
            fft_size=size,
            frequency_bins=bins,
            magnitude=magnitude.tolist(),
            magnitude_power_db=magnitude_power_db,
            magnitude_power_db_normalized=magnitude_power_db_normalized,
            phase_radians=phase.tolist(),
        )

    def _normalize_to_dc(self, magnitude_power_db: list[float | None]) -> list[float | None]:
        if not magnitude_power_db:
            return []

        dc_value = magnitude_power_db[0]
        if dc_value is None:
            return [None for _ in magnitude_power_db]

        return [
            (value - dc_value if value is not None else None)
            for value in magnitude_power_db
        ]


class EqualizerFrequencyResponseModel(BaseModel):
    fft_size: int = Field(..., description="FFT size used to compute the frequency response.")
    frequency_bins: list[float] = Field(..., description="Normalized frequency bins (0 to 1, inclusive of 0, exclusive of 1).")
    magnitude: list[float] = Field(..., description="Magnitude response for each frequency bin.")
    magnitude_power_db: list[float | None] = Field(..., description="Magnitude power in dB for each bin; None when magnitude is 0.")
    magnitude_power_db_normalized: list[float | None] = Field(..., description="Magnitude power normalized to DC (bin 0) in dB; None when DC is 0.")
    phase_radians: list[float] = Field(..., description="Phase response in radians for each frequency bin.")

    model_config = {"frozen": True}


class TapCableDelayModel(BaseModel):
    cable_type: str = Field(..., description="Cable type name (velocity-factor class) used to map time delay to length.")
    velocity_factor: float = Field(..., description="Velocity factor (fraction of speed of light) for this cable type.")
    propagation_speed_m_s: float = Field(..., description="Propagation speed for this cable type in meters/second.")
    delay_us: float = Field(..., description="Tap delay relative to the main tap in microseconds.")
    one_way_length_m: float = Field(..., description="One-way length equivalent for the tap delay in meters.")
    one_way_length_ft: float = Field(..., description="One-way length equivalent for the tap delay in feet.")
    echo_length_m: float = Field(..., description="Echo-path length equivalent (round-trip assumed) for the tap delay in meters.")
    echo_length_ft: float = Field(..., description="Echo-path length equivalent (round-trip assumed) for the tap delay in feet.")

    model_config = {"frozen": True}


class TapDelayAnnotatedModel(BaseModel):
    tap_index: int = Field(..., description="Tap index in the equalizer coefficient array (0-based).")
    tap_offset: int = Field(..., description="Tap offset from the main tap: 0 is main tap (T0), +1 is T1, etc.")
    is_main_tap: bool = Field(..., description="True when this tap is the main tap (T0).")
    real: int = Field(..., description="Tap real component (integer).")
    imag: int = Field(..., description="Tap imaginary component (integer).")
    magnitude: float = Field(..., description="Magnitude of the complex tap: sqrt(real^2 + imag^2).")
    magnitude_power_db: float | None = Field(..., description="Tap power in dB: 10*log10(magnitude^2); None when magnitude is 0.")
    delay_samples: float = Field(..., description="Delay relative to the main tap expressed in tap-samples (offset / taps_per_symbol).")
    delay_us: float = Field(..., description="Delay relative to the main tap in microseconds.")
    cable_delays: list[TapCableDelayModel] = Field(
        ...,
        description=(
            "Per-cable delay mapping results. Each item maps the same tap time-delay to a length using the "
            "cable velocity factor. one_way_* assumes a one-way path; echo_* assumes a round-trip reflection."
        ),
    )

    model_config = {"frozen": True}


class EqualizerTapDelaySummaryModel(BaseModel):
    symbol_rate: float = Field(..., description="Symbol rate in symbols/second.")
    taps_per_symbol: int = Field(..., description="Number of equalizer taps per symbol interval (sample rate = symbol_rate * taps_per_symbol).")
    symbol_time_us: float = Field(..., description="Symbol time in microseconds (1/symbol_rate).")
    sample_period_us: float = Field(..., description="Tap sample period in microseconds (symbol_time_us / taps_per_symbol).")
    main_tap_index: int = Field(..., description="Main tap index (0-based). T0 is this index.")
    main_echo_tap_index: int | None = Field(
        ...,
        description="Index of the strongest post-main tap (largest magnitude) treated as the main echo; None when no post taps exist.",
    )
    main_echo_tap_offset: int | None = Field(
        ...,
        description="Offset (index - main_tap_index) for the main echo tap; None when main_echo_tap_index is None.",
    )
    main_echo_magnitude: float | None = Field(
        ...,
        description="Magnitude of the main echo tap; None when main_echo_tap_index is None.",
    )
    taps: list[TapDelayAnnotatedModel] = Field(..., description="All taps annotated with delay relative to the main tap and per-cable length mapping.")

    model_config = {"frozen": True}


@dataclass(frozen=True, slots=True)
class EqualizerTapDelayAnnotator:
    """
    Annotate ATDMA pre-equalization taps with time delay (relative to the main tap) and cable-length equivalents.

    Interpretation
    - The pre-equalizer coefficient list is a time-domain tap sequence.
    - The configured main tap (T0) represents the dominant/desired impulse response alignment.
    - Each tap after the main tap (T1, T2, ...) represents additional delayed energy. In practice, these can be echoes
      (reflections) or post-cursor ISI components.

    Timing Model
    - Symbol time:
        Ts = 1 / symbol_rate
    - Tap sample period:
        Ttap = Ts / taps_per_symbol
    - Tap i relative to main tap m:
        offset = i - m
        delay_seconds = offset * Ttap
      This yields:
        delay_us = delay_seconds * 1e6

    Cable-Length Mapping (Per CableType)
    - Each cable type provides a velocity factor VF (fraction of c0).
      propagation_speed = VF * SPEED_OF_LIGHT
    - One-way length equivalent:
        L_one_way = propagation_speed * delay_seconds
    - Echo-path length equivalent (round-trip reflection assumed):
        L_echo = propagation_speed * delay_seconds / 2
      Use L_echo when interpreting a post-main tap as a reflected echo.

    Main Echo Identification
    - The main echo is identified as the strongest tap (largest magnitude) strictly after the main tap.
      If there are no post-main taps, main_echo_* fields are None.
    """

    symbol_rate: float
    taps_per_symbol: int
    main_tap_index: int = 7

    DEFAULT_TAP_COUNT: ClassVar[Final[int]] = 24

    def to_model(self, coefficients: list[PreEqAtdmaCoefficients]) -> EqualizerTapDelaySummaryModel:
        if len(coefficients) != self.DEFAULT_TAP_COUNT:
            raise ValueError(f"Expected {self.DEFAULT_TAP_COUNT} ATDMA taps, got {len(coefficients)}.")
        if self.taps_per_symbol <= 0:
            raise ValueError("taps_per_symbol must be > 0.")
        if self.symbol_rate <= 0.0:
            raise ValueError("symbol_rate must be > 0.")
        if self.main_tap_index < 0 or self.main_tap_index >= len(coefficients):
            raise ValueError("main_tap_index is out of range for the coefficient list.")

        symbol_time_us = (1.0 / float(self.symbol_rate)) * 1_000_000.0
        sample_period_us = symbol_time_us / float(self.taps_per_symbol)

        annotated: list[TapDelayAnnotatedModel] = []
        mags: list[float] = []

        for idx, (real, imag) in enumerate(coefficients):
            magnitude = math.hypot(float(real), float(imag))
            mags.append(magnitude)

            magnitude_power_db: float | None = None
            if magnitude > 0.0:
                magnitude_power_db = 10.0 * math.log10(magnitude * magnitude)

            offset = int(idx - self.main_tap_index)
            delay_samples = float(offset) / float(self.taps_per_symbol)
            delay_us = delay_samples * sample_period_us

            cable_delays = self._build_cable_delays(delay_us=delay_us)

            annotated.append(
                TapDelayAnnotatedModel(
                    tap_index=idx,
                    tap_offset=offset,
                    is_main_tap=(idx == self.main_tap_index),
                    real=int(real),
                    imag=int(imag),
                    magnitude=float(magnitude),
                    magnitude_power_db=magnitude_power_db,
                    delay_samples=delay_samples,
                    delay_us=delay_us,
                    cable_delays=cable_delays,
                )
            )

        main_echo_idx = self._main_echo_index(magnitudes=mags, main_tap_index=self.main_tap_index)
        if main_echo_idx is None:
            return EqualizerTapDelaySummaryModel(
                symbol_rate=float(self.symbol_rate),
                taps_per_symbol=int(self.taps_per_symbol),
                symbol_time_us=float(symbol_time_us),
                sample_period_us=float(sample_period_us),
                main_tap_index=int(self.main_tap_index),
                main_echo_tap_index=None,
                main_echo_tap_offset=None,
                main_echo_magnitude=None,
                taps=annotated,
            )

        main_echo_offset = int(main_echo_idx - self.main_tap_index)
        return EqualizerTapDelaySummaryModel(
            symbol_rate=float(self.symbol_rate),
            taps_per_symbol=int(self.taps_per_symbol),
            symbol_time_us=float(symbol_time_us),
            sample_period_us=float(sample_period_us),
            main_tap_index=int(self.main_tap_index),
            main_echo_tap_index=int(main_echo_idx),
            main_echo_tap_offset=int(main_echo_offset),
            main_echo_magnitude=float(mags[main_echo_idx]),
            taps=annotated,
        )

    def _build_cable_delays(self, delay_us: float) -> list[TapCableDelayModel]:
        delay_s = float(delay_us) / 1_000_000.0

        items: list[TapCableDelayModel] = []
        for cable_name, cable_type in CableType.__members__.items():
            vf = float(cable_type.value)
            v = vf * float(SPEED_OF_LIGHT)

            one_way_m = v * delay_s
            echo_m = one_way_m / 2.0

            items.append(
                TapCableDelayModel(
                    cable_type=cable_name,
                    velocity_factor=vf,
                    propagation_speed_m_s=float(v),
                    delay_us=float(delay_us),
                    one_way_length_m=float(one_way_m),
                    one_way_length_ft=float(one_way_m * float(FEET_PER_METER)),
                    echo_length_m=float(echo_m),
                    echo_length_ft=float(echo_m * float(FEET_PER_METER)),
                )
            )

        return items

    def _main_echo_index(self, magnitudes: list[float], main_tap_index: int) -> int | None:
        post_indices = range(main_tap_index + 1, len(magnitudes))
        best_idx: int | None = None
        best_mag = -1.0

        for idx in post_indices:
            mag = float(magnitudes[idx])
            if mag > best_mag:
                best_mag = mag
                best_idx = idx

        return best_idx
