# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


class RequestListNormalizer:
    """
    Utility helpers for request-list normalization in API models.
    """

    @staticmethod
    def dedupe_preserve_order(values: list[T] | None) -> list[T] | None:
        """
        De-duplicate list items while preserving first-seen order.
        """
        if values is None or not values:
            return values
        seen: set[T] = set()
        deduped: list[T] = []
        for item in values:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped
