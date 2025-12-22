# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import math

from pypnm.lib.collector.complex import ComplexCollector


def test_add_and_to_complex_array() -> None:
    cc = ComplexCollector()
    cc.add(1.0, -2.5)
    cc.add(0.0, 3.25)

    out = cc.to_complex_array()
    assert out == [(1.0, -2.5), (0.0, 3.25)]
    assert len(cc) == 2


def test_add_complex() -> None:
    cc = ComplexCollector()
    cc.add_complex(1 + 2j)
    cc.add_complex(-3.5 - 0.25j)

    out = cc.to_complex_array()
    assert out == [(1.0, 2.0), (-3.5, -0.25)]
    assert len(cc) == 2


def test_as_parts_empty_and_nonempty() -> None:
    cc = ComplexCollector()
    # empty
    re, im = cc.as_parts()
    assert re == [] and im == []

    # non-empty
    cc.add(1.0, 2.0)
    cc.add(-0.5, 0.25)
    re, im = cc.as_parts()
    assert re == [1.0, -0.5]
    assert im == [2.0, 0.25]

    # sanity checks
    assert math.isclose(sum(re), 0.5)
    assert math.isclose(sum(im), 2.25)


def test_repr_contains_class_name_and_values() -> None:
    cc = ComplexCollector()
    cc.add(1.0, -1.0)
    s = repr(cc)
    assert "ComplexCollector" in s
    assert "(1.0, -1.0)" in s
