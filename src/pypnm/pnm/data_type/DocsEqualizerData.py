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
