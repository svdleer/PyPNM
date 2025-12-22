# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import numpy as np


class HeatmapAnomalyDetector:
    """
    Detect anomalies in a 2D array via global z-score thresholding
    and extract bounding boxes around each connected component.

    Attributes:
        data (np.ndarray): 2D input array of measurements.
        threshold (float): z-score cutoff; defaults to 3.0.
        zmap (np.ndarray): computed z-score map.
        mask (np.ndarray): boolean mask where |z| > threshold.
        boxes (List[Tuple[int, int, int, int]]): list of
            (row_min, col_min, row_max, col_max) bounding boxes.
    """

    def __init__(self, data: np.ndarray, threshold: float = 3.0) -> None:
        self.data = np.asarray(data, dtype=float)
        if self.data.ndim != 2:
            raise ValueError("Input must be a 2-D array.")
        self.threshold: float = threshold
        self.zmap: np.ndarray = None  # will be computed
        self.mask: np.ndarray = None
        self.boxes: list[tuple[int, int, int, int]] = []

    def compute_zmap(self) -> np.ndarray:
        """
        Compute the z-score map of the input data.

        Returns:
            np.ndarray: z-score normalized array.
        """
        mu = self.data.mean()
        sigma = self.data.std()
        # Avoid division by zero
        if sigma == 0:
            self.zmap = np.zeros_like(self.data)
        else:
            self.zmap = (self.data - mu) / sigma
        return self.zmap

    def detect(self) -> np.ndarray:
        """
        Apply the threshold to form a boolean anomaly mask.

        Returns:
            np.ndarray: boolean mask where anomalies are True.
        """
        if self.zmap is None:
            self.compute_zmap()
        self.mask = np.abs(self.zmap) > self.threshold
        return self.mask

    def find_boxes(self) -> list[tuple[int, int, int, int]]:
        """
        Identify connected components in the anomaly mask (4-connectivity)
        and compute their bounding boxes.

        Returns:
            List[Tuple[int, int, int, int]]: list of bounding boxes
            as (row_min, col_min, row_max, col_max).
        """
        if self.mask is None:
            self.detect()

        visited = np.zeros_like(self.mask, dtype=bool)
        rows, cols = self.data.shape
        boxes: list[tuple[int, int, int, int]] = []

        def neighbors(r: int, c: int) -> Generator[tuple[int, int], Any, None]:
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    yield nr, nc

        for i in range(rows):
            for j in range(cols):
                if self.mask[i, j] and not visited[i, j]:
                    rmin = rmax = i
                    cmin = cmax = j
                    stack = [(i, j)]
                    visited[i, j] = True

                    while stack:
                        r, c = stack.pop()
                        rmin = min(rmin, r)
                        rmax = max(rmax, r)
                        cmin = min(cmin, c)
                        cmax = max(cmax, c)
                        for nr, nc in neighbors(r, c):
                            if self.mask[nr, nc] and not visited[nr, nc]:
                                visited[nr, nc] = True
                                stack.append((nr, nc))

                    boxes.append((rmin, cmin, rmax, cmax))

        self.boxes = boxes
        return boxes

    def to_json(self) -> dict[str, Any]:
        """
        Convert the detected boxes into a JSON-friendly dictionary.

        Returns:
            Dict[str, Any]: dictionary with threshold and boxes list.
        """
        return {
            "threshold": self.threshold,
            "boxes": [
                {"row_min": r0, "col_min": c0, "row_max": r1, "col_max": c1}
                for r0, c0, r1, c1 in self.boxes
            ],
        }
