# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from pypnm.lib.constants import DOCSIS_ROLL_OFF_FACTOR
from pypnm.lib.types import (
    BandwidthHz,
    FloatSeries,
    Microseconds,
    PreEqAtdmaCoefficients,
)

MIN_CHANNEL_WIDTH_HZ: BandwidthHz = BandwidthHz(0)
MIN_TAPS_PER_SYMBOL: int = 0
MIN_ROLLOFF: float = 0.0
ONE: float = 1.0
TWO_PI: float = 2.0 * math.pi
MICROSECONDS_PER_SECOND: float = 1_000_000.0


class GroupDelayModel(BaseModel):
    """Immutable ATDMA group delay results derived from pre-equalization taps.

    Stores derived timing and delay series used for analysis and reporting.
    """

    channel_width_hz: BandwidthHz   = Field(..., description="ATDMA channel width in Hz.")
    rolloff: float                  = Field(..., description=f"RRC roll-off factor α (typical DOCSIS = {DOCSIS_ROLL_OFF_FACTOR}).")
    taps_per_symbol: int            = Field(..., description="Taps per symbol from the pre-EQ header.")
    symbol_rate: float              = Field(..., description="Derived symbol rate (sym/s): BW / (1 + rolloff).")
    symbol_time_us: Microseconds    = Field(..., description="Derived symbol time in microseconds (µs): 1/symbol_rate.")
    sample_period_us: Microseconds  = Field(..., description="Sample period in microseconds (µs): Tsym / taps_per_symbol.")
    fft_size: int                   = Field(..., description="FFT size used to evaluate the frequency response (N taps).")
    delay_samples: FloatSeries      = Field(..., description="Group delay in samples per FFT bin (tap-period units).")
    delay_us: FloatSeries           = Field(..., description="Group delay in microseconds per FFT bin.")
    model_config = {"frozen": True}


@dataclass(frozen=True, slots=True)
class GroupDelayCalculator:
    """Compute ATDMA group delay from upstream pre-equalization coefficients.

    This calculator derives **group delay** (the negative slope of the unwrapped
    phase response) from a 24-tap ATDMA upstream FIR equalizer. The input taps are
    complex coefficients (real, imag) taken from `docsIf3CmStatusUsEqData.*`
    after decoding to signed integers (your existing `DocsEqualizerData` class
    already handles endianness + 12/16-bit interpretation and yields taps).

    Conceptually, the equalizer taps represent a discrete-time FIR filter:

        h[n] = re[n] + j·im[n]    for n = 0..N-1

    The processing steps are:

    1) **Time → Frequency conversion**
       Compute the N-point FFT to obtain the complex frequency response:

           H[k] = FFT{ h[n] } ,  k = 0..N-1

    2) **Phase extraction and unwrap**
       Extract the phase angle of each bin and unwrap it to remove 2π discontinuities:

           φ[k] = unwrap(angle(H[k]))

    3) **Group delay in samples**
       Group delay is defined as:

           τ(ω) = - dφ(ω) / dω

       With FFT bins, ω[k] = 2π·k/N. We approximate the derivative numerically,
       resulting in group delay measured in **tap-sample periods** (i.e., "samples").

    4) **Convert delay from samples → microseconds**
       To express delay in time units, we need the tap sample period.

       For DOCSIS ATDMA upstream channels, symbol rate is typically derived from
       channel width and roll-off (root-raised cosine shaping):

           Rs = BW / (1 + α)

       Then:

           Tsym = 1 / Rs
           Tsamp = Tsym / taps_per_symbol

       Finally:

           delay_us[k] = delay_samples[k] · Tsamp(µs)

    Notes and expectations:

    - This class does **not** assume the main tap location is centered; it reports
      the group delay implied by the taps as provided.
    - The FFT size is set to **N = number of taps** by default. If you later want
      a smoother curve, you can zero-pad (e.g., 128/256 points) without changing
      the underlying physics—only the sampling density in frequency.
    - `taps_per_symbol` comes from the pre-EQ header byte (often 1).
    - `channel_width_hz` must be provided to compute absolute time units (µs).
      Without it, you can still compute delay in samples, but not in seconds.

    Attributes:
        channel_width_hz: ATDMA upstream channel width in Hz (e.g., 1_600_000).
        taps_per_symbol: Tap sampling density per symbol from the pre-EQ header.
                         Used to convert symbol time to tap-sample time.
        rolloff: DOCSIS shaping roll-off factor α. Typical default is 0.25.

    Returns:
        A `GroupDelayModel` containing:
        - derived symbol rate/time and sample period
        - group delay arrays per FFT bin in samples and microseconds
    """

    channel_width_hz: BandwidthHz
    taps_per_symbol: int
    rolloff: float = DOCSIS_ROLL_OFF_FACTOR

    def __post_init__(self) -> None:
        if int(self.channel_width_hz) <= MIN_CHANNEL_WIDTH_HZ:
            raise ValueError("channel_width_hz must be > 0.")
        if self.taps_per_symbol <= MIN_TAPS_PER_SYMBOL:
            raise ValueError("taps_per_symbol must be > 0.")
        if not math.isfinite(self.rolloff):
            raise ValueError("rolloff must be finite.")
        if self.rolloff < MIN_ROLLOFF:
            raise ValueError("rolloff must be >= 0.")

    @staticmethod
    def _to_complex_array(coefficients: list[PreEqAtdmaCoefficients]) -> NDArray[np.complex128]:
        taps: NDArray[np.complex128] = np.empty(len(coefficients), dtype=np.complex128)
        for i, (re, im) in enumerate(coefficients):
            taps[i] = complex(float(re), float(im))
        return taps

    def symbol_rate(self) -> float:
        bw = float(int(self.channel_width_hz))
        return bw / (ONE + self.rolloff)

    def symbol_time_us(self) -> Microseconds:
        sr = self.symbol_rate()
        ts = ONE / sr
        return Microseconds(ts * MICROSECONDS_PER_SECOND)

    def sample_period_us(self) -> Microseconds:
        tsym_us = float(self.symbol_time_us())
        return Microseconds(tsym_us / float(self.taps_per_symbol))

    def compute(self, coefficients: list[PreEqAtdmaCoefficients]) -> GroupDelayModel:
        if len(coefficients) == 0:
            raise ValueError("coefficients cannot be empty.")

        h_time = self._to_complex_array(coefficients)

        n = int(h_time.shape[0])
        h_freq = np.fft.fft(h_time, n=n)

        phase = np.unwrap(np.angle(h_freq))
        omega = TWO_PI * (np.arange(n, dtype=np.float64) / float(n))

        dphi_domega = np.gradient(phase, omega)
        delay_samples = -dphi_domega

        tsamp_us = float(self.sample_period_us())
        delay_us = delay_samples * tsamp_us

        delay_samples_list: FloatSeries = [float(x) for x in delay_samples.tolist()]
        delay_us_list: FloatSeries      = [float(x) for x in delay_us.tolist()]

        sr = self.symbol_rate()
        tsym_us = float(self.symbol_time_us())
        tsamp = float(self.sample_period_us())

        return GroupDelayModel(
            channel_width_hz    =   BandwidthHz(int(self.channel_width_hz)),
            rolloff             =   float(self.rolloff),
            taps_per_symbol     =   int(self.taps_per_symbol),
            symbol_rate         =   float(sr),
            symbol_time_us      =   Microseconds(tsym_us),
            sample_period_us    =   Microseconds(tsamp),
            fft_size            =   int(n),
            delay_samples       =   delay_samples_list,
            delay_us            =   delay_us_list,
        )
