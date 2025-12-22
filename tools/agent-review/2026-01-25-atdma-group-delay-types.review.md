## Agent Review Bundle Summary
- Goal: Integrate ATDMA pre-equalization metrics and tap delay annotations.
- Changes: Emit cable type names in tap delay summaries, align docs example fields, and document nested response objects.
- Files: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py; src/pypnm/pnm/data_type/DocsEqualizerData.py; src/pypnm/lib/constants.py; docs/api/fast-api/single/us/atdma/chan/pre-equalization.md
- Tests: Not run (not requested).
- Notes: None.

# FILE: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Final

import numpy as np
from pydantic import BaseModel, Field

from pypnm.lib.constants import CableType, FEET_PER_METER, SPEED_OF_LIGHT
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


# FILE: src/pypnm/pnm/data_type/DocsEqualizerData.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import json
import math
from typing import Final, Literal

from pydantic import BaseModel, Field

from pypnm.lib.constants import DOCSIS_ROLL_OFF_FACTOR
from pypnm.lib.types import BandwidthHz, ImginaryInt, PreEqAtdmaCoefficients, RealInt
from pypnm.pnm.analysis.atdma_group_delay import GroupDelayCalculator, GroupDelayModel
from pypnm.pnm.analysis.atdma_preeq_key_metrics import (
    EqualizerMetrics,
    EqualizerMetricsModel,
    EqualizerTapDelayAnnotator,
    EqualizerTapDelaySummaryModel,
)


class UsEqTapModel(BaseModel):
    real: int = Field(..., description="Tap real coefficient decoded as 2's complement.")
    imag: int = Field(..., description="Tap imag coefficient decoded as 2's complement.")
    magnitude: float = Field(..., description="Magnitude computed from real/imag.")
    magnitude_power_dB: float | None = Field(..., description="Magnitude power in dB (10*log10(mag^2)); None when magnitude is 0.")
    real_hex: str = Field(..., description="Raw 2-byte real coefficient as received, shown as 4 hex chars.")
    imag_hex: str = Field(..., description="Raw 2-byte imag coefficient as received, shown as 4 hex chars.")

    model_config = {"frozen": True}


class UsEqDataModel(BaseModel):
    main_tap_location: int      = Field(..., description="Main tap location (header byte 0; HEX value).")
    taps_per_symbol: int        = Field(..., description="Taps per symbol (header byte 1; HEX value).")
    num_taps: int               = Field(..., description="Number of taps (header byte 2; HEX value).")
    reserved: int               = Field(..., description="Reserved (header byte 3; HEX value).")
    header_hex: str             = Field(..., description="Header bytes as hex (4 bytes).")
    payload_hex: str            = Field(..., description="Full payload as hex (space-separated bytes).")
    payload_preview_hex: str    = Field(..., description="Header + first N taps as hex preview (space-separated bytes).")
    taps: list[UsEqTapModel]    = Field(..., description="Decoded taps in order (real/imag pairs).")
    metrics: EqualizerMetricsModel | None   = Field(None, description="ATDMA pre-equalization key metrics when available.")
    group_delay: GroupDelayModel | None = Field(None, description="ATDMA group delay derived from taps when channel_width_hz is provided.")
    tap_delay_summary: EqualizerTapDelaySummaryModel | None = Field(
        None,
        description="Annotated tap delays and cable-length equivalents when channel_width_hz is provided.",
    )

    model_config = {"frozen": True}


class DocsEqualizerData:
    """
    Parse DOCS-IF3 upstream pre-equalization tap data.

    Notes:
    - CM deployments have two common coefficient interpretations:
      * four-nibble 2's complement (16-bit signed)
      * three-nibble 2's complement (12-bit signed; upper nibble unused)
    - Some deployments can be handled with a "universal" decoder: drop the first nibble and decode as 12-bit.

    IMPORTANT:
    - Pass raw SNMP OctetString bytes via add_from_bytes() whenever possible.
    - If you pass a hex string, it must be real hex (e.g., 'FF FC 00 04 ...'), not a Unicode pretty string.
    """

    HEADER_SIZE: Final[int] = 4
    COEFF_BYTES: Final[int] = 2
    COMPLEX_TAP_SIZE: Final[int] = 4
    MAX_TAPS: Final[int] = 64

    U16_MASK: Final[int] = 0xFFFF
    U12_MASK: Final[int] = 0x0FFF
    U16_MSN_MASK: Final[int] = 0xF000

    I16_SIGN: Final[int] = 0x8000
    I12_SIGN: Final[int] = 0x0800
    I16_RANGE: Final[int] = 0x10000
    I12_RANGE: Final[int] = 0x1000

    AUTO_ENDIAN_SAMPLE_MAX_TAPS: Final[int] = 16
    AUTO_ENDIAN_BYTE_GOOD_0: Final[int] = 0x00
    AUTO_ENDIAN_BYTE_GOOD_FF: Final[int] = 0xFF

    def __init__(self) -> None:
        self._coefficients_found: bool = False
        self.equalizer_data: dict[int, UsEqDataModel] = {}

    def add(
        self,
        us_idx: int,
        payload_hex: str,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"] = "auto",
        coeff_endianness: Literal["little", "big", "auto"] = "auto",
        preview_taps: int = 8,
        channel_width_hz: BandwidthHz | None = None,
        rolloff: float = DOCSIS_ROLL_OFF_FACTOR,
    ) -> bool:
        """
        Parse/store from a hex string payload.

        payload_hex MUST be actual hex bytes (e.g., 'FF FC 00 04 ...').
        If payload_hex contains non-hex characters (like 'ÿ'), this will return False.

        coeff_encoding:
        - four-nibble: decode as signed 16-bit (2's complement)
        - three-nibble: decode as signed 12-bit (2's complement) after masking to 0x0FFF
        - auto: prefer 16-bit when the upper nibble is used; otherwise decode as 12-bit ("universal" behavior)

        coeff_endianness:
        - little: interpret each 2-byte coefficient as little-endian
        - big: interpret each 2-byte coefficient as big-endian
        - auto: heuristic selection based on common small-coefficient patterns
        """
        try:
            payload = self._hex_to_bytes_strict(payload_hex)
            return self._add_parsed(
                us_idx,
                payload,
                coeff_encoding=coeff_encoding,
                coeff_endianness=coeff_endianness,
                preview_taps=preview_taps,
                channel_width_hz=channel_width_hz,
                rolloff=rolloff,
            )
        except Exception:
            return False

    def add_from_bytes(
        self,
        us_idx: int,
        payload: bytes,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"] = "auto",
        coeff_endianness: Literal["little", "big", "auto"] = "auto",
        preview_taps: int = 8,
        channel_width_hz: BandwidthHz | None = None,
        rolloff: float = DOCSIS_ROLL_OFF_FACTOR,
    ) -> bool:
        """
        Parse/store from raw bytes (preferred for SNMP OctetString values).
        """
        try:
            return self._add_parsed(
                us_idx,
                payload,
                coeff_encoding=coeff_encoding,
                coeff_endianness=coeff_endianness,
                preview_taps=preview_taps,
                channel_width_hz=channel_width_hz,
                rolloff=rolloff,
            )
        except Exception:
            return False

    def coefficients_found(self) -> bool:
        return self._coefficients_found

    def get_record(self, us_idx: int) -> UsEqDataModel | None:
        return self.equalizer_data.get(us_idx)

    def to_dict(self) -> dict[int, dict]:
        return {k: v.model_dump() for k, v in self.equalizer_data.items()}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def _add_parsed(
        self,
        us_idx: int,
        payload: bytes,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"],
        coeff_endianness: Literal["little", "big", "auto"],
        preview_taps: int,
        channel_width_hz: BandwidthHz | None,
        rolloff: float,
    ) -> bool:
        if len(payload) < self.HEADER_SIZE:
            return False

        main_tap_location = payload[0]
        taps_per_symbol = payload[1]
        num_taps = payload[2]
        reserved = payload[3]

        if num_taps == 0:
            return False

        if num_taps > self.MAX_TAPS:
            return False

        expected_len = self.HEADER_SIZE + (num_taps * self.COMPLEX_TAP_SIZE)
        if len(payload) < expected_len:
            return False

        header_hex = payload[: self.HEADER_SIZE].hex(" ", 1).upper()
        payload_hex = payload[:expected_len].hex(" ", 1).upper()

        preview_taps_clamped = preview_taps
        if preview_taps_clamped < 0:
            preview_taps_clamped = 0
        if preview_taps_clamped > num_taps:
            preview_taps_clamped = num_taps

        preview_len = self.HEADER_SIZE + (preview_taps_clamped * self.COMPLEX_TAP_SIZE)
        payload_preview_hex = payload[:preview_len].hex(" ", 1).upper()

        taps_blob = payload[self.HEADER_SIZE : expected_len]
        taps = self._parse_taps(
            taps_blob,
            coeff_encoding=coeff_encoding,
            coeff_endianness=coeff_endianness,
        )

        metrics = self._build_metrics(taps)
        group_delay = self._build_group_delay(
            taps,
            channel_width_hz=channel_width_hz,
            taps_per_symbol=taps_per_symbol,
            rolloff=rolloff,
        )
        tap_delay_summary = self._build_tap_delay_summary(
            taps,
            channel_width_hz=channel_width_hz,
            taps_per_symbol=taps_per_symbol,
            rolloff=rolloff,
        )
        self.equalizer_data[us_idx] = UsEqDataModel(
            main_tap_location      =   main_tap_location,
            taps_per_symbol        =   taps_per_symbol,
            num_taps               =   num_taps,
            reserved               =   reserved,
            header_hex             =   header_hex,
            payload_hex            =   payload_hex,
            payload_preview_hex    =   payload_preview_hex,
            taps                   =   taps,
            metrics                =   metrics,
            group_delay            =   group_delay,
            tap_delay_summary      =   tap_delay_summary,
        )

        self._coefficients_found = True
        return True

    def _parse_taps(
        self,
        data: bytes,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"],
        coeff_endianness: Literal["little", "big", "auto"],
    ) -> list[UsEqTapModel]:
        taps: list[UsEqTapModel] = []
        step = self.COMPLEX_TAP_SIZE

        endian = coeff_endianness
        if endian == "auto":
            endian = self._detect_coeff_endianness(data)

        encoding = coeff_encoding
        if encoding == "auto":
            encoding = self._detect_coeff_encoding(data, coeff_endianness=endian)

        tap_count = len(data) // step
        for tap_idx in range(tap_count):
            base = tap_idx * step
            real_b = data[base : base + self.COEFF_BYTES]
            imag_b = data[base + self.COEFF_BYTES : base + step]

            real_u16 = int.from_bytes(real_b, byteorder=endian, signed=False)
            imag_u16 = int.from_bytes(imag_b, byteorder=endian, signed=False)

            real = self._decode_coeff(real_u16, coeff_encoding=encoding)
            imag = self._decode_coeff(imag_u16, coeff_encoding=encoding)

            magnitude = math.hypot(float(real), float(imag))
            if magnitude > 0.0:
                power_db = 10.0 * math.log10(magnitude * magnitude)
            else:
                power_db = None

            taps.append(
                UsEqTapModel(
                    real=real,
                    imag=imag,
                    magnitude=round(magnitude, 2),
                    magnitude_power_dB=(round(power_db, 2) if power_db is not None else None),
                    real_hex=real_b.hex().upper(),
                    imag_hex=imag_b.hex().upper(),
                )
            )

        return taps

    def _build_metrics(self, taps: list[UsEqTapModel]) -> EqualizerMetricsModel | None:
        if len(taps) != EqualizerMetrics.EXPECTED_TAP_COUNT:
            return None

        coefficients: list[PreEqAtdmaCoefficients] = [
            (RealInt(tap.real), ImginaryInt(tap.imag)) for tap in taps
        ]
        return EqualizerMetrics(coefficients=coefficients).to_model()

    def _build_group_delay(
        self,
        taps: list[UsEqTapModel],
        *,
        channel_width_hz: BandwidthHz | None,
        taps_per_symbol: int,
        rolloff: float,
    ) -> GroupDelayModel | None:
        if channel_width_hz is None:
            return None
        if len(taps) == 0:
            return None
        if taps_per_symbol <= 0:
            return None

        coefficients: list[PreEqAtdmaCoefficients] = [
            (RealInt(tap.real), ImginaryInt(tap.imag)) for tap in taps
        ]
        try:
            calculator = GroupDelayCalculator(
                channel_width_hz=channel_width_hz,
                taps_per_symbol=taps_per_symbol,
                rolloff=rolloff,
            )
            return calculator.compute(coefficients)
        except Exception:
            return None

    def _build_tap_delay_summary(
        self,
        taps: list[UsEqTapModel],
        *,
        channel_width_hz: BandwidthHz | None,
        taps_per_symbol: int,
        rolloff: float,
    ) -> EqualizerTapDelaySummaryModel | None:
        if channel_width_hz is None:
            return None
        if taps_per_symbol <= 0:
            return None
        if len(taps) != EqualizerTapDelayAnnotator.DEFAULT_TAP_COUNT:
            return None
        if rolloff < 0.0:
            return None

        coefficients: list[PreEqAtdmaCoefficients] = [
            (RealInt(tap.real), ImginaryInt(tap.imag)) for tap in taps
        ]
        symbol_rate = float(int(channel_width_hz)) / (1.0 + float(rolloff))
        try:
            annotator = EqualizerTapDelayAnnotator(
                symbol_rate=symbol_rate,
                taps_per_symbol=taps_per_symbol,
            )
            return annotator.to_model(coefficients)
        except Exception:
            return None

    def _detect_coeff_endianness(self, data: bytes) -> Literal["little", "big"]:
        """
        Heuristic endianness detection.

        Many deployed pre-EQ taps are small-magnitude, so the MSB of each 16-bit word is often 0x00 (positive)
        or 0xFF (negative). We score both interpretations by counting how often the MSB matches {0x00, 0xFF}.
        """
        if len(data) < self.COMPLEX_TAP_SIZE:
            return "little"

        max_taps = self.AUTO_ENDIAN_SAMPLE_MAX_TAPS
        tap_count = len(data) // self.COMPLEX_TAP_SIZE
        if tap_count < max_taps:
            max_taps = tap_count

        good = (self.AUTO_ENDIAN_BYTE_GOOD_0, self.AUTO_ENDIAN_BYTE_GOOD_FF)

        score_little = 0
        score_big = 0

        for tap_idx in range(max_taps):
            base = tap_idx * self.COMPLEX_TAP_SIZE

            r0 = data[base]
            r1 = data[base + 1]
            i0 = data[base + 2]
            i1 = data[base + 3]

            if r1 in good:
                score_little += 1
            if i1 in good:
                score_little += 1

            if r0 in good:
                score_big += 1
            if i0 in good:
                score_big += 1

        if score_big > score_little:
            return "big"
        return "little"

    def _detect_coeff_encoding(
        self,
        data: bytes,
        *,
        coeff_endianness: Literal["little", "big"],
    ) -> Literal["four-nibble", "three-nibble"]:
        """
        Auto-select coefficient decoding:

        - If any coefficient uses the upper nibble (0xF000 mask != 0), assume 16-bit signed (four-nibble).
        - Otherwise, default to 12-bit signed (three-nibble), which matches the "universal" decoding guidance.
        """
        step = self.COMPLEX_TAP_SIZE
        tap_count = len(data) // step

        for tap_idx in range(tap_count):
            base = tap_idx * step
            real_b = data[base : base + self.COEFF_BYTES]
            imag_b = data[base + self.COEFF_BYTES : base + step]

            real_u16 = int.from_bytes(real_b, byteorder=coeff_endianness, signed=False)
            imag_u16 = int.from_bytes(imag_b, byteorder=coeff_endianness, signed=False)

            if (real_u16 & self.U16_MSN_MASK) != 0:
                return "four-nibble"
            if (imag_u16 & self.U16_MSN_MASK) != 0:
                return "four-nibble"

        return "three-nibble"

    def _decode_coeff(self, raw_u16: int, *, coeff_encoding: Literal["four-nibble", "three-nibble"]) -> int:
        match coeff_encoding:
            case "four-nibble":
                return self._decode_int16(raw_u16)
            case "three-nibble":
                return self._decode_int12(raw_u16)
            case _:
                raise ValueError(f"Unsupported coeff_encoding: {coeff_encoding}")

    def _decode_int16(self, raw_u16: int) -> int:
        value = raw_u16 & self.U16_MASK
        if value & self.I16_SIGN:
            return value - self.I16_RANGE
        return value

    def _decode_int12(self, raw_u16: int) -> int:
        value = raw_u16 & self.U12_MASK
        if value & self.I12_SIGN:
            return value - self.I12_RANGE
        return value

    def _hex_to_bytes_strict(self, payload_hex: str) -> bytes:
        text = payload_hex.strip()
        text = text.replace("Hex-STRING:", "")
        text = text.replace("0x", "")
        text = " ".join(text.split())

        if text == "":
            return b""

        for ch in text:
            if ch == " ":
                continue
            if "0" <= ch <= "9":
                continue
            if "a" <= ch <= "f":
                continue
            if "A" <= ch <= "F":
                continue
            return b""

        return bytes.fromhex(text)


# FILE: src/pypnm/lib/constants.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026

from __future__ import annotations

from typing import Final, Literal, TypeAlias, TypeVar, cast

from pypnm.lib.types import (
    STATUS,
    CaptureTime,
    ChannelId,
    FloatEnum,
    FrequencyHz,
    Number,
    ProfileId,
    StringEnum,
)

DEFAULT_SSH_PORT: int   = 22

HZ:  Final[int] = 1
KHZ: Final[int] = 1_000
MHZ: Final[int] = 1_000_000
GHZ: Final[int] = 1_000_000_000

FEET_PER_METER: Final[float] = 3.280839895013123
SPEED_OF_LIGHT: Final[float] = 299_792_458.0  # m/s

NULL_ARRAY_NUMBER: Final[list[Number]] = [0]

ZERO_FREQUENCY: Final[FrequencyHz]                  = cast(FrequencyHz, 0)

INVALID_CHANNEL_ID: Final[ChannelId]                = cast(ChannelId, -1)
INVALID_PROFILE_ID: Final[ProfileId]                = cast(ProfileId, -1)
INVALID_SUB_CARRIER_ZERO_FREQ: Final[FrequencyHz]   = cast(FrequencyHz, 0)
INVALID_START_VALUE: Final[int]                     = -1
INVALID_SCHEMA_TYPE: Final[int]                     = -1
INVALID_CAPTURE_TIME: Final[CaptureTime]            = cast(CaptureTime, -1)

DEFAULT_CAPTURE_TIME: Final[CaptureTime]            = cast(CaptureTime, 19700101)  # epoch start

CableTypes: TypeAlias = Literal["RG6", "RG59", "RG11"]

DOCSIS_ROLL_OFF_FACTOR: Final[float] = 0.25

# Velocity Factor (VF) by cable type (fraction of c0)
CABLE_VF: Final[dict[CableTypes, float]] = {
    "RG6":  0.85,
    "RG59": 0.82,
    "RG11": 0.87,
}

class CableType(FloatEnum):
    RG6  = 0.85
    RG59 = 0.82
    RG11 = 0.87

class MediaType(StringEnum):
    """
    Canonical Media Type Enumeration Used For File And HTTP Responses.

    Values
    ------
    APPLICATION_JSON
        JSON payloads (FastAPI JSONResponse, .json files).
    APPLICATION_ZIP
        ZIP archives (analysis bundles, multi-file exports).
    APPLICATION_OCTET_STREAM
        Raw binary streams (PNM files, generic downloads).
    TEXT_CSV
        Comma-separated values (tabular exports).
    """

    APPLICATION_JSON         = "application/json"
    APPLICATION_ZIP          = "application/zip"
    APPLICATION_OCTET_STREAM = "application/octet-stream"
    TEXT_CSV                 = "text/csv"

T = TypeVar("T")

DEFAULT_SPECTRUM_ANALYZER_INDICES: Final[list[int]] = [0]


FEC_SUMMARY_TYPE_STEP_SECONDS: dict[int, int] = {
    2: 1,      # interval10min(2): 600 samples, 1 sec apart
    3: 60,     # interval24hr(3): 1440 samples, 60 sec apart
    # other(1): unknown / device-specific, do not enforce
}

FEC_SUMMARY_TYPE_LABEL: dict[int, str] = {
    1: "other",
    2: "10-minute interval (1s cadence)",
    3: "24-hour interval (60s cadence)",
}

STATUS_OK:STATUS = True
STATUS_NOK:STATUS = False

__all__ = [
    "DOCSIS_ROLL_OFF_FACTOR",
    "STATUS_OK", "STATUS_NOK",
    "DEFAULT_SSH_PORT",
    "HZ", "KHZ", "MHZ", "GHZ",
    "ZERO_FREQUENCY",
    "FEET_PER_METER", "SPEED_OF_LIGHT",
    "NULL_ARRAY_NUMBER",
    "INVALID_CHANNEL_ID", "INVALID_PROFILE_ID", "INVALID_SUB_CARRIER_ZERO_FREQ",
    "INVALID_START_VALUE", "INVALID_SCHEMA_TYPE", "INVALID_CAPTURE_TIME",
    "DEFAULT_CAPTURE_TIME",
    "CableTypes", "CABLE_VF",
    "DEFAULT_SPECTRUM_ANALYZER_INDICES",
    "FEC_SUMMARY_TYPE_STEP_SECONDS", "FEC_SUMMARY_TYPE_LABEL",
]


# FILE: docs/api/fast-api/single/us/atdma/chan/pre-equalization.md
# DOCSIS 3.0 Upstream ATDMA Pre-Equalization

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Pre-Equalization Tap Data For Plant Analysis (Reflections, Group Delay, Pre-Echo).

## Endpoint

**POST** `/docs/if30/us/atdma/chan/preEqualization`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **object** keyed by the **SNMP table index** of each upstream channel.  
Each value contains decoded tap configuration, coefficients, metrics, group delay, and tap delay annotations when available.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": "Successfully retrieved upstream pre-equalization coefficients",
  "results": {
    "4": {
      "main_tap_location": 8,
      "taps_per_symbol": 1,
      "num_taps": 24,
      "reserved": 0,
      "header_hex": "08 01 18 00",
      "payload_hex": "08 01 18 00 00 00 00 04 00 07 FF FC FF FD 00 07 00 04",
      "payload_preview_hex": "08 01 18 00 00 00 00 04 00 07 FF FC FF FD 00 07 00 04",
      "taps": [
        { "real": 0, "imag": 4, "magnitude": 4.0, "magnitude_power_dB": 12.04, "real_hex": "0000", "imag_hex": "0004" },
        { "real": 7, "imag": -4, "magnitude": 8.06, "magnitude_power_dB": 18.13, "real_hex": "0007", "imag_hex": "FFFC" }
        /* ... taps elided ... */
      ],
      "metrics": {
        "main_tap_energy": 4177985.0,
        "main_tap_nominal_energy": 8380418.0,
        "pre_main_tap_energy": 10737.0,
        "post_main_tap_energy": 1568.0,
        "total_tap_energy": 4190290.0,
        "main_tap_compression": 0.012772040716584596,
        "main_tap_ratio": 25.308852583836106,
        "frequency_response": {
          "fft_size": 24,
          "frequency_bins": [0.0, 0.041666666666666664, 0.08333333333333333],
          "magnitude": [2051.872315715576, 2003.9331033353867, 1990.4489950200837],
          "magnitude_power_db": [66.24300663848884, 66.03766439043883, 65.97902106653461],
          "magnitude_power_db_normalized": [0.0, -0.20534224805000179, -0.26398557195422256],
          "phase_radians": [0.061445988511636136, -1.7860293780783445, 2.66760487568281]
        }
      },
      "group_delay": {
        "channel_width_hz": 6400000,
        "rolloff": 0.25,
        "taps_per_symbol": 1,
        "symbol_rate": 5120000.0,
        "symbol_time_us": 0.1953125,
        "sample_period_us": 0.1953125,
        "fft_size": 24,
        "delay_samples": [7.0568360839993645, 7.0226031674860145, 7.0170470754941],
        "delay_us": [1.378288297656126, 1.3716021811496122, 1.3705170069324413]
      },
      "tap_delay_summary": {
        "symbol_rate": 5120000.0,
        "taps_per_symbol": 1,
        "symbol_time_us": 0.1953125,
        "sample_period_us": 0.1953125,
        "main_tap_index": 7,
        "main_echo_tap_index": 8,
        "main_echo_tap_offset": 1,
        "main_echo_magnitude": 36.22154055254967,
        "taps": [
          {
            "tap_index": 0,
            "tap_offset": -7,
            "is_main_tap": false,
            "real": 0,
            "imag": 4,
            "magnitude": 4.0,
            "magnitude_power_db": 12.041199826559248,
            "delay_samples": -7.0,
            "delay_us": -1.3671875,
            "cable_delays": [
              {
                "cable_type": "RG6",
                "velocity_factor": 0.85,
                "propagation_speed_m_s": 254823589.29999998,
                "delay_us": -1.3671875,
                "one_way_length_m": -348.3916259960937,
                "one_way_length_ft": -1143.0171456564753,
                "echo_length_m": -174.19581299804685,
                "echo_length_ft": -571.5085728282377
              },
              {
                "cable_type": "RG59",
                "velocity_factor": 0.82,
                "propagation_speed_m_s": 245829815.55999997,
                "delay_us": -1.3671875,
                "one_way_length_m": -336.09545096093746,
                "one_way_length_ft": -1102.6753640450702,
                "echo_length_m": -168.04772548046873,
                "echo_length_ft": -551.3376820225351
              },
              {
                "cable_type": "RG11",
                "velocity_factor": 0.87,
                "propagation_speed_m_s": 260819438.46,
                "delay_us": -1.3671875,
                "one_way_length_m": -356.58907601953126,
                "one_way_length_ft": -1169.9116667307455,
                "echo_length_m": -178.29453800976563,
                "echo_length_ft": -584.9558333653728
              }
            ]
          }
          /* ... taps elided ... */
        ]
      }
    }
    /* ... other upstream channel indices elided ... */
  }
}
```

## Container Keys

| Key (top-level under `data`) | Type   | Description                                                       |
| ---------------------------- | ------ | ----------------------------------------------------------------- |
| `"4"`, `"80"`, …             | string | **SNMP table index** for the upstream channel row (OID instance). |

## Channel-Level Fields

| Field               | Type    | Description                                                 |
| ------------------- | ------- | ----------------------------------------------------------- |
| `main_tap_location` | integer | Location of the main tap (typically near the filter center) |
| `taps_per_symbol`   | integer | Taps per symbol from the pre-EQ header                      |
| `num_taps`          | integer | Total number of taps                                        |
| `reserved`          | integer | Reserved header byte                                        |
| `header_hex`        | string  | Header bytes in hex                                         |
| `payload_hex`       | string  | Full payload hex                                            |
| `payload_preview_hex` | string | Header plus a preview window of taps in hex                 |
| `taps`              | array   | Complex tap coefficients (real/imag pairs)                  |
| `metrics`           | object  | ATDMA pre-equalization key metrics when available           |
| `group_delay`       | object  | Group delay results when channel bandwidth is available     |
| `tap_delay_summary` | object  | Tap delay annotations and cable-length estimates            |

## Coefficient Object Fields

| Field                | Type  | Units | Description                          |
| -------------------- | ----- | ----- | ------------------------------------ |
| `real`               | int   | —     | Real part of the complex coefficient |
| `imag`               | int   | —     | Imaginary part of the coefficient    |
| `magnitude`          | float | —     | Magnitude of the complex tap         |
| `magnitude_power_dB` | float | dB    | Power of the tap in dB               |
| `real_hex`           | string | —    | Raw 2-byte real coefficient (hex)    |
| `imag_hex`           | string | —    | Raw 2-byte imag coefficient (hex)    |

## Metrics Object Fields

| Field                              | Type   | Units | Description                                                |
| ---------------------------------- | ------ | ----- | ---------------------------------------------------------- |
| `main_tap_energy`                  | float  | —     | Main tap energy (MTE).                                     |
| `main_tap_nominal_energy`          | float  | —     | Main tap nominal energy (MTNE).                            |
| `pre_main_tap_energy`              | float  | —     | Pre-main tap energy (PreMTE).                              |
| `post_main_tap_energy`             | float  | —     | Post-main tap energy (PostMTE).                            |
| `total_tap_energy`                 | float  | —     | Total tap energy (TTE).                                    |
| `main_tap_compression`             | float  | dB    | Main tap compression (MTC).                                |
| `main_tap_ratio`                   | float  | dB    | Main tap ratio (MTR).                                      |
| `non_main_tap_energy_ratio`        | float  | dB    | Non-main tap to total energy ratio (NMTER).                |
| `pre_main_tap_total_energy_ratio`  | float  | dB    | Pre-main tap to total energy ratio (PreMTTER).             |
| `post_main_tap_total_energy_ratio` | float  | dB    | Post-main tap to total energy ratio (PostMTTER).           |
| `pre_post_energy_symmetry_ratio`   | float  | dB    | Pre-post energy symmetry ratio (PPESR).                    |
| `pre_post_tap_symmetry_ratio`      | float  | dB    | Pre-post tap symmetry ratio (PPTSR).                       |
| `frequency_response`               | object | —     | Frequency response derived from tap coefficients.          |

## Frequency Response Object Fields

| Field                         | Type  | Units | Description                                               |
| ----------------------------- | ----- | ----- | --------------------------------------------------------- |
| `fft_size`                    | int   | —     | FFT size used to compute the frequency response.          |
| `frequency_bins`              | array | —     | Normalized frequency bins (0 to 1).                       |
| `magnitude`                   | array | —     | Magnitude response for each frequency bin.                |
| `magnitude_power_db`          | array | dB    | Magnitude power in dB for each bin.                       |
| `magnitude_power_db_normalized` | array | dB  | Magnitude power normalized to DC (bin 0).                 |
| `phase_radians`               | array | rad   | Phase response in radians for each frequency bin.         |

## Group Delay Object Fields

| Field             | Type  | Units | Description                                              |
| ----------------- | ----- | ----- | -------------------------------------------------------- |
| `channel_width_hz` | int  | Hz    | Upstream channel width.                                  |
| `rolloff`         | float | —     | DOCSIS roll-off factor used for symbol rate.             |
| `taps_per_symbol` | int   | —     | Taps per symbol from the pre-EQ header.                  |
| `symbol_rate`     | float | sym/s | Symbol rate derived from channel width and roll-off.     |
| `symbol_time_us`  | float | us    | Symbol time in microseconds.                             |
| `sample_period_us` | float | us   | Tap sample period in microseconds.                       |
| `fft_size`        | int   | —     | FFT size used to compute group delay.                    |
| `delay_samples`   | array | —     | Group delay expressed in tap-sample units.               |
| `delay_us`        | array | us    | Group delay expressed in microseconds.                   |

## Tap Delay Summary Object Fields

| Field                 | Type   | Units | Description                                              |
| --------------------- | ------ | ----- | -------------------------------------------------------- |
| `symbol_rate`         | float  | sym/s | Symbol rate used for tap delay mapping.                  |
| `taps_per_symbol`     | int    | —     | Taps per symbol from the pre-EQ header.                  |
| `symbol_time_us`      | float  | us    | Symbol time in microseconds.                             |
| `sample_period_us`    | float  | us    | Tap sample period in microseconds.                       |
| `main_tap_index`      | int    | —     | Main tap index (0-based).                                |
| `main_echo_tap_index` | int    | —     | Strongest post-main tap index when present.              |
| `main_echo_tap_offset` | int   | —     | Offset from main tap for the main echo tap.              |
| `main_echo_magnitude` | float | —     | Magnitude of the main echo tap.                          |
| `taps`                | array | —     | Annotated taps with delay and cable-length estimates.    |

## Tap Delay Entry Fields

| Field             | Type  | Units | Description                                              |
| ----------------- | ----- | ----- | -------------------------------------------------------- |
| `tap_index`       | int   | —     | Tap index in the coefficient array (0-based).            |
| `tap_offset`      | int   | —     | Offset from the main tap (0 is main tap).                |
| `is_main_tap`     | bool  | —     | True when the tap is the main tap.                       |
| `real`            | int   | —     | Tap real component.                                      |
| `imag`            | int   | —     | Tap imaginary component.                                 |
| `magnitude`       | float | —     | Magnitude of the complex tap.                            |
| `magnitude_power_db` | float | dB  | Tap power in dB; null when magnitude is 0.               |
| `delay_samples`   | float | —     | Tap delay relative to the main tap in tap-samples.       |
| `delay_us`        | float | us    | Tap delay relative to the main tap in microseconds.      |
| `cable_delays`    | array | —     | Cable-length equivalents for the tap delay.              |

## Cable Delay Entry Fields

| Field                   | Type  | Units | Description                                              |
| ----------------------- | ----- | ----- | -------------------------------------------------------- |
| `cable_type`            | string | —    | Cable type name (velocity-factor class).                 |
| `velocity_factor`       | float | —     | Velocity factor (fraction of speed of light).            |
| `propagation_speed_m_s` | float | m/s   | Propagation speed for the cable type.                    |
| `delay_us`              | float | us    | Tap delay relative to the main tap in microseconds.      |
| `one_way_length_m`      | float | m     | One-way length equivalent for the tap delay.             |
| `one_way_length_ft`     | float | ft    | One-way length equivalent for the tap delay.             |
| `echo_length_m`         | float | m     | Echo-path length equivalent (round-trip assumed).        |
| `echo_length_ft`        | float | ft    | Echo-path length equivalent (round-trip assumed).        |

## Notes

* Each top-level key under `data` is the DOCSIS **SNMP index** for an upstream SC-QAM (ATDMA) channel.
* Group delay is included only when the upstream channel bandwidth is available.
* Use tap shapes and main-tap offset to infer echo path delay and alignment health.
* Tap coefficients are signed integers; convert to floating-point as needed for analysis.

