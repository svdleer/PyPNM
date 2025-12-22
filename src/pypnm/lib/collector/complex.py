# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

from pypnm.lib.types import ComplexArray


class ComplexCollector:
    """
    Container for storing complex numbers as (real, imag) tuples.

    Features:
    - Add complex numbers by real/imag parts or as a Python complex.
    - Retrieve stored values as a list of (real, imag) tuples.
    - Retrieve stored values as separate lists of real and imaginary parts.
    """

    def __init__(self) -> None:
        self._values: ComplexArray = []

    def add(self, real: float, imag: float) -> None:
        """Insert a new complex number (real, imag)."""
        self._values.append((float(real), float(imag)))

    def add_complex(self, value: complex) -> None:
        """Insert a Python complex number directly."""
        self._values.append((float(value.real), float(value.imag)))

    def to_complex_array(self) -> ComplexArray:
        """Retrieve all stored complex numbers as a list of (real, imag) tuples."""
        return list(self._values)

    def as_parts(self) -> tuple[list[float], list[float]]:
        """
        Retrieve real and imaginary parts separately.

        Returns:
            (real_parts, imag_parts)
        """
        if not self._values:
            return [], []
        reals, imags = zip(*self._values, strict=False)  # unzip tuples
        return list(reals), list(imags)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"ComplexCollector({self._values})"
