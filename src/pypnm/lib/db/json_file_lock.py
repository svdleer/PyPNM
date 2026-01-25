# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import fcntl
import logging
import time
from pathlib import Path
from typing import TextIO


class JsonFileLock:
    """
    Cross-process lock for JSON DB files using a sidecar lock file.
    """
    DEFAULT_TIMEOUT: float = 30.0
    DEFAULT_POLL_INTERVAL: float = 0.05

    def __init__(
        self,
        target_path: Path,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._lock_path = target_path.with_suffix(f"{target_path.suffix}.lock")
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._handle: TextIO | None = None
        self._logger = logging.getLogger(self.__class__.__name__)

    def __enter__(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._lock_path.open("a+", encoding="utf-8")
        start = time.monotonic()

        while True:
            if self._try_lock():
                return None
            if time.monotonic() - start >= self._timeout:
                raise TimeoutError(f"Timed out acquiring lock for {self._lock_path}") from None
            time.sleep(self._poll_interval)

    def _try_lock(self) -> bool:
        if not self._handle:
            return False
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        if not self._handle:
            return None
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except Exception as err:
            self._logger.debug("Failed to release lock %s: %s", self._lock_path, err)
        finally:
            self._handle.close()
            self._handle = None
        return None
