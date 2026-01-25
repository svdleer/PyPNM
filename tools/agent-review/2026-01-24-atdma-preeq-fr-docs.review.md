## Agent Review Bundle Summary
- Goal: Add DC-normalized frequency response output and document metrics.
- Changes: Compute normalized dB response, update tests, and document new fields.
- Files: src/pypnm/pnm/analysis/atdma_preeq_key_metrics.py; tests/test_atdma_preeq_key_metrics.py; docs/api/fast-api/single/us/atdma/chan/stats.md
- Tests: python3 -m compileall src; ruff check src; ruff format --check . (fails: repo drift); pytest -q; ./tools/local/local_kubernetes_smoke.sh (timeout/aborted)
- Notes: Ruff format would reformat many existing files; no formatting applied. Smoke script timed out after image load and was aborted by user.

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
    assert all(value == pytest.approx(0.0, abs=1e-12) for value in response.magnitude_power_db_normalized)

# FILE: docs/api/fast-api/single/us/atdma/chan/stats.md
# DOCSIS 3.0 Upstream ATDMA Channel Statistics

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Channel Statistics.

## Endpoint

**POST** `/docs/if30/us/atdma/chan/stats`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **array** of upstream channels. Each item contains the SNMP table `index`, the upstream `channel_id`, and an `entry` with configuration, status, and (where available) raw pre-EQ data (`docsIf3CmStatusUsEqData`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": [
    {
      "index": 80,
      "channel_id": 1,
      "entry": {
        "docsIfUpChannelId": 1,
        "docsIfUpChannelFrequency": 14600000,
        "docsIfUpChannelWidth": 6400000,
        "docsIfUpChannelModulationProfile": 0,
        "docsIfUpChannelSlotSize": 2,
        "docsIfUpChannelTxTimingOffset": 6436,
        "docsIfUpChannelRangingBackoffStart": 3,
        "docsIfUpChannelRangingBackoffEnd": 8,
        "docsIfUpChannelTxBackoffStart": 2,
        "docsIfUpChannelTxBackoffEnd": 6,
        "docsIfUpChannelType": 2,
        "docsIfUpChannelCloneFrom": 0,
        "docsIfUpChannelUpdate": false,
        "docsIfUpChannelStatus": 1,
        "docsIfUpChannelPreEqEnable": true,
        "docsIf3CmStatusUsTxPower": 49.0,
        "docsIf3CmStatusUsT3Timeouts": 0,
        "docsIf3CmStatusUsT4Timeouts": 0,
        "docsIf3CmStatusUsRangingAborteds": 0,
        "docsIf3CmStatusUsModulationType": 2,
        "docsIf3CmStatusUsEqData": "0x08011800ffff0003...00020001",
        "docsIf3CmStatusUsT3Exceededs": 0,
        "docsIf3CmStatusUsIsMuted": false,
        "docsIf3CmStatusUsRangingStatus": 4
      }
    },
    {
      "index": 81,
      "channel_id": 2,
      "entry": {
        "docsIfUpChannelId": 2,
        "docsIfUpChannelFrequency": 21000000,
        "docsIfUpChannelWidth": 6400000,
        "docsIfUpChannelModulationProfile": 0,
        "docsIfUpChannelSlotSize": 2,
        "docsIfUpChannelTxTimingOffset": 6436,
        "docsIfUpChannelRangingBackoffStart": 3,
        "docsIfUpChannelRangingBackoffEnd": 8,
        "docsIfUpChannelTxBackoffStart": 2,
        "docsIfUpChannelTxBackoffEnd": 6,
        "docsIfUpChannelType": 2,
        "docsIfUpChannelCloneFrom": 0,
        "docsIfUpChannelUpdate": false,
        "docsIfUpChannelStatus": 1,
        "docsIfUpChannelPreEqEnable": true,
        "docsIf3CmStatusUsTxPower": 48.5,
        "docsIf3CmStatusUsT3Timeouts": 0,
        "docsIf3CmStatusUsT4Timeouts": 0,
        "docsIf3CmStatusUsRangingAborteds": 0,
        "docsIf3CmStatusUsModulationType": 2,
        "docsIf3CmStatusUsEqData": "0x08011800ffff0001...0002",
        "docsIf3CmStatusUsT3Exceededs": 0,
        "docsIf3CmStatusUsIsMuted": false,
        "docsIf3CmStatusUsRangingStatus": 4
      }
    }
  ]
}
```

## Channel Fields

| Field        | Type | Description                                                                 |
| ------------ | ---- | --------------------------------------------------------------------------- |
| `index`      | int  | **SNMP table index** (OID instance) for this channel’s row in the CM table. |
| `channel_id` | int  | DOCSIS upstream SC-QAM (ATDMA) logical channel ID.                          |

## Entry Fields

| Field                                | Type   | Units | Description                                             |
| ------------------------------------ | ------ | ----- | ------------------------------------------------------- |
| `docsIfUpChannelId`                  | int    | —     | Upstream channel ID (mirrors logical ID).               |
| `docsIfUpChannelFrequency`           | int    | Hz    | Center frequency.                                       |
| `docsIfUpChannelWidth`               | int    | Hz    | Channel width.                                          |
| `docsIfUpChannelModulationProfile`   | int    | —     | Modulation profile index.                               |
| `docsIfUpChannelSlotSize`            | int    | —     | Slot size (minislot units).                             |
| `docsIfUpChannelTxTimingOffset`      | int    | —     | Transmit timing offset (implementation-specific units). |
| `docsIfUpChannelRangingBackoffStart` | int    | —     | Initial ranging backoff window start.                   |
| `docsIfUpChannelRangingBackoffEnd`   | int    | —     | Initial ranging backoff window end.                     |
| `docsIfUpChannelTxBackoffStart`      | int    | —     | Data/backoff start window.                              |
| `docsIfUpChannelTxBackoffEnd`        | int    | —     | Data/backoff end window.                                |
| `docsIfUpChannelType`                | int    | —     | Channel type enum (e.g., `2` = ATDMA).                  |
| `docsIfUpChannelCloneFrom`           | int    | —     | Clone source channel (if used).                         |
| `docsIfUpChannelUpdate`              | bool   | —     | Indicates a pending/active update.                      |
| `docsIfUpChannelStatus`              | int    | —     | Operational status enum.                                |
| `docsIfUpChannelPreEqEnable`         | bool   | —     | Whether pre-equalization is enabled.                    |
| `docsIf3CmStatusUsTxPower`           | float  | dBmV  | Upstream transmit power.                                |
| `docsIf3CmStatusUsT3Timeouts`        | int    | —     | T3 timeouts counter.                                    |
| `docsIf3CmStatusUsT4Timeouts`        | int    | —     | T4 timeouts counter.                                    |
| `docsIf3CmStatusUsRangingAborteds`   | int    | —     | Aborted ranging attempts.                               |
| `docsIf3CmStatusUsModulationType`    | int    | —     | Modulation type enum.                                   |
| `docsIf3CmStatusUsEqData`            | string | hex   | Raw pre-EQ coefficient payload (hex string; raw octets). |
| `docsIf3CmStatusUsT3Exceededs`       | int    | —     | Exceeded T3 attempts.                                   |
| `docsIf3CmStatusUsIsMuted`           | bool   | —     | Whether the upstream transmitter is muted.              |
| `docsIf3CmStatusUsRangingStatus`     | int    | —     | Ranging state enum.                                     |

## Notes

* `docsIf3CmStatusUsEqData` contains the raw equalizer payload; decode to taps (location, magnitude, phase) in analysis workflows.
* The hex string preserves original SNMP octets (for example `FF` stays `FF`, not UTF-8 encoded).
* Use the combination of `TxPower`, timeout counters, and ranging status to corroborate upstream health with pre-EQ shape.
* Channels are discovered automatically; no channel list is required in the request.
# DOCSIS 3.0 Upstream ATDMA Pre-Equalization

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Pre-Equalization Tap Data For Plant Analysis (Reflections, Group Delay, Pre-Echo).

## Endpoint

**POST** `/docs/if30/us/scqam/chan/preEqualization`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **object** keyed by the **SNMP table index** of each upstream channel.  
Each value contains decoded tap configuration and coefficient arrays.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "80": {
      "main_tap_location": 8,
      "forward_taps_per_symbol": 1,
      "num_forward_taps": 24,
      "num_reverse_taps": 0,
      "forward_coefficients": [
        { "real": 0, "imag": 4, "magnitude": 4.0, "magnitude_power_dB": 12.04 },
        { "real": 2, "imag": -15425, "magnitude": 15425.0, "magnitude_power_dB": 83.76 },
        { "real": -15426, "imag": 1, "magnitude": 15426.0, "magnitude_power_dB": 83.77 }
        /* ... taps elided ... */
      ],
      "reverse_coefficients": []
    },
    "81": {
      "main_tap_location": 8,
      "forward_taps_per_symbol": 1,
      "num_forward_taps": 24,
      "num_reverse_taps": 0,
      "forward_coefficients": [
        { "real": -15425, "imag": -15425, "magnitude": 21814.24, "magnitude_power_dB": 86.77 },
        { "real": 1, "imag": 3, "magnitude": 3.16, "magnitude_power_dB": 10.0 },
        { "real": 1, "imag": -15425, "magnitude": 15425.0, "magnitude_power_dB": 83.76 }
        /* ... taps elided ... */
      ],
      "reverse_coefficients": []
    }
    /* ... other upstream channel indices elided ... */
  }
}
```

## Container Keys

| Key (top-level under `data`) | Type   | Description                                                       |
| ---------------------------- | ------ | ----------------------------------------------------------------- |
| `"80"`, `"81"`, …            | string | **SNMP table index** for the upstream channel row (OID instance). |

## Channel-Level Fields

| Field                     | Type    | Description                                                 |
| ------------------------- | ------- | ----------------------------------------------------------- |
| `main_tap_location`       | integer | Location of the main tap (typically near the filter center) |
| `forward_taps_per_symbol` | integer | Number of forward taps per symbol                           |
| `num_forward_taps`        | integer | Total forward equalizer taps                                |
| `num_reverse_taps`        | integer | Total reverse equalizer taps (often `0` for ATDMA)          |
| `forward_coefficients`    | array   | Complex tap coefficients applied in forward direction       |
| `reverse_coefficients`    | array   | Complex tap coefficients applied in reverse direction       |
| `metrics`                 | object  | Derived equalizer metrics and frequency response            |

## Coefficient Object Fields

| Field                | Type  | Units | Description                          |
| -------------------- | ----- | ----- | ------------------------------------ |
| `real`               | int   | —     | Real part of the complex coefficient |
| `imag`               | int   | —     | Imaginary part of the coefficient    |
| `magnitude`          | float | —     | Magnitude of the complex tap         |
| `magnitude_power_dB` | float | dB    | Power of the tap in dB               |

## Equalizer Metrics Fields

| Field                           | Type  | Units | Description                                   |
| ------------------------------- | ----- | ----- | --------------------------------------------- |
| `main_tap_energy`               | float | —     | Main tap energy (MTE)                         |
| `main_tap_nominal_energy`       | float | —     | Main tap nominal energy (MTNE)                |
| `pre_main_tap_energy`           | float | —     | Pre-main tap energy (PreMTE)                  |
| `post_main_tap_energy`          | float | —     | Post-main tap energy (PostMTE)                |
| `total_tap_energy`              | float | —     | Total tap energy (TTE)                        |
| `main_tap_compression`          | float | dB    | Main tap compression (MTC)                    |
| `main_tap_ratio`                | float | dB    | Main tap ratio (MTR)                          |
| `non_main_tap_energy_ratio`     | float | dB    | Non-main tap to total energy ratio (NMTER)    |
| `pre_main_tap_total_energy_ratio` | float | dB  | Pre-main tap to total energy ratio (PreMTTER) |
| `post_main_tap_total_energy_ratio` | float | dB | Post-main tap to total energy ratio (PostMTTER) |
| `pre_post_energy_symmetry_ratio`  | float | dB | Pre-post energy symmetry ratio (PPESR)        |
| `pre_post_tap_symmetry_ratio`     | float | dB | Pre-post tap symmetry ratio (PPTSR)           |
| `frequency_response`              | object | —  | Frequency response derived from tap coefficients |

## Frequency Response Fields

| Field                         | Type          | Units | Description                                         |
| ----------------------------- | ------------- | ----- | --------------------------------------------------- |
| `fft_size`                    | integer       | —     | FFT size used to compute the response               |
| `frequency_bins`              | array[float]  | —     | Normalized bins from 0 to 1                         |
| `magnitude`                   | array[float]  | —     | Magnitude response per bin                          |
| `magnitude_power_db`          | array[float]  | dB    | Magnitude power per bin                             |
| `magnitude_power_db_normalized` | array[float] | dB    | Magnitude power normalized to the DC bin (bin 0)    |
| `phase_radians`               | array[float]  | rad   | Phase response per bin                              |

## Notes

* Each top-level key under `data` is the DOCSIS **SNMP index** for an upstream SC-QAM (ATDMA) channel.
* Forward taps pre-compensate the channel (handling pre-echo/echo paths); reverse taps are uncommon in ATDMA.
* Use tap shapes and main-tap offset to infer echo path delay and alignment health.
* Tap coefficients are signed integers; convert to floating-point as needed for analysis.
* `magnitude_power_db_normalized` references the DC bin (bin 0) as 0 dB when non-zero.
