## Agent Review Bundle Summary
- Goal: Add file locking to capture group/operation JSON DBs to prevent concurrent overwrite.
- Changes: Added JsonFileLock helper; wrapped capture group and operation DB reads/writes with locks; added lock timeout test; tightened capture group typing; ensured operation DB auto-creates on load; added concurrent-process capture group test (250 processes).
- Files: src/pypnm/lib/db/json_file_lock.py; src/pypnm/api/routes/common/classes/file_capture/capture_group.py; src/pypnm/api/routes/advance/common/operation_manager.py; tests/test_json_file_lock.py; tests/test_capture_group_concurrency.py.
- Tests: Not run (not requested).
- Notes: Lock uses sidecar .lock file with fcntl.

# FILE: src/pypnm/lib/db/json_file_lock.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TextIO

import fcntl


class JsonFileLock:
    """
    Cross-process lock for JSON DB files using a sidecar lock file.
    """
    def __init__(self, target_path: Path, timeout: float = 5.0, poll_interval: float = 0.05) -> None:
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
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return None
            except BlockingIOError:
                if time.monotonic() - start >= self._timeout:
                    raise TimeoutError(f"Timed out acquiring lock for {self._lock_path}")
                time.sleep(self._poll_interval)

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

# FILE: src/pypnm/api/routes/common/classes/file_capture/capture_group.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import json
import logging
import time
import uuid
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pypnm.config.system_config_settings import SystemConfigSettings
from pypnm.lib.db.json_file_lock import JsonFileLock
from pypnm.lib.types import GroupId, TransactionId


class CaptureGroup:
    """
    Manage sessions of capture operations (e.g., multi-RxMER runs) by grouping
    multiple file-transfer transactions under a single UUID-based group ID.

    Features:
      - Persist groups and their transaction lists in a JSON file across runs.
      - Generate or load a 16-character hexadecimal group ID per session.
      - Add, list, delete transactions; prune stale groups.

    JSON schema (DB file):
    {
        "<group_id>": {
            "created": <unix_epoch_seconds>,
            "transactions": ["<txn1>", "<txn2>", ...]
        },
        ...
    }

    Example:
        # New session
        cg = CaptureGroup()
        group_id = cg.create_group()

        # Existing session
        cg2 = CaptureGroup(group_id=group_id)
        txns = cg2.get_transactions()
    """

    def __init__(self, group_id: GroupId | None = None,
                 db_path: Path | None = None) -> None:
        """
        Initialize the CaptureGroup manager.

        Args:
            group_id: Optional existing group ID to load; generates a new one if None.
            db_path: Optional Path for the JSON DB file. Defaults to config [PnmFileRetrieval].capture_group_db.

        Raises:
            OSError: If the parent directory cannot be created.
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        # Resolve DB file path
        if db_path:
            self.db_path = Path(db_path)
        else:
            cfg_db_path = SystemConfigSettings.capture_group_db()
            self.db_path = Path(cfg_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create empty DB if missing
        if not self.db_path.exists():
            self._atomic_write_db({})

        # Load in-memory state
        self._db: dict[str, Any] = {}
        self._grp_id: GroupId = group_id
        self._load_db()
        self._create_group_id()

    def _load_db(self) -> None:
        """
        Load the JSON DB into memory; resets on error.
        """
        try:
            with self.db_path.open('r', encoding='utf-8') as f:
                self._db = json.load(f)
        except (ValueError, JSONDecodeError):
            self.logger.warning("Corrupt DB file; resetting to empty")
            self._db = {}
        except Exception as e:
            self.logger.error(f"Error loading DB: {e}")
            self._db = {}

    def _atomic_write_db(self, data: dict[str, Any]) -> None:
        """
        Atomically write the given data dict to the JSON DB file.
        """
        temp_path = self.db_path.with_suffix('.tmp')
        with temp_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(self.db_path)

    def _save_db(self) -> None:
        """
        Persist the in-memory DB to disk using atomic write.
        """
        try:
            self._atomic_write_db(self._db)
        except Exception as e:
            self.logger.error(f"Failed to save DB: {e}")

    def _create_group_id(self) -> str:
        """
        Ensure a group ID is set (use existing or generate new).
        Returns the active group ID.
        """
        if not self._grp_id:
            self._grp_id = uuid.uuid4().hex[:16]
        return self._grp_id

    def get_group_id(self) -> GroupId:
        """
        Get the current active group ID.
        Raises AssertionError if uninitialized.
        """
        assert self._grp_id, "Group ID not initialized"
        return self._grp_id

    def create_group(self) -> GroupId:
        """
        Add the current group to the DB (no-op if exists).
        Returns the group ID.
        """
        gid = self.get_group_id()
        with JsonFileLock(self.db_path):
            self._load_db()
            if gid not in self._db:
                self._db[gid] = {"created": int(time.time()), "transactions": []}
                self._save_db()
                self.logger.info(f"Created new group: {gid}")
            else:
                self.logger.debug(f"Group {gid} already exists")
        return gid

    def add_transaction(self, txn_id: TransactionId) -> None:
        """
        Append a transaction ID to this group, saving the DB.
        Raises ValueError if group missing.
        """
        gid = self.get_group_id()
        with JsonFileLock(self.db_path):
            self._load_db()
            if gid not in self._db:
                raise ValueError("Group not found; create_group() first")
            txns = self._db[gid].setdefault("transactions", [])
            if txn_id not in txns:
                txns.append(txn_id)
                self._save_db()
                self.logger.debug(f"Added txn {txn_id} to group {gid}")

    def getTransactionIds(self) -> list[TransactionId]:
        """
        Return all transaction IDs for this group (empty list if none).
        """
        with JsonFileLock(self.db_path):
            self._load_db()
            return list(self._db.get(self.get_group_id(), {}).get("transactions", []))

    def delete_group(self) -> None:
        """
        Remove this group and its transactions from the DB; resets group ID.
        """
        gid = self.get_group_id()
        with JsonFileLock(self.db_path):
            self._load_db()
            if gid in self._db:
                del self._db[gid]
                self._save_db()
                self.logger.info(f"Deleted group: {gid}")
        self._grp_id = None

    def list_groups(self) -> list[GroupId]:
        """
        List all group IDs currently in the DB.
        """
        with JsonFileLock(self.db_path):
            self._load_db()
            return list(self._db.keys())

    def prune_older_than(self, seconds: int) -> None:
        """
        Remove groups older than the given age (seconds).
        """
        cutoff = int(time.time()) - seconds
        with JsonFileLock(self.db_path):
            self._load_db()
            to_delete = [gid for gid, info in self._db.items() if info.get("created", 0) < cutoff]
            for gid in to_delete:
                del self._db[gid]
            if to_delete:
                self._save_db()
                self.logger.info(f"Pruned groups: {to_delete}")

# FILE: src/pypnm/api/routes/advance/common/operation_manager.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from pypnm.config.system_config_settings import SystemConfigSettings
from pypnm.lib.db.json_file_lock import JsonFileLock
from pypnm.lib.constants import cast
from pypnm.lib.types import GroupId, OperationId


class OperationManager:
    """
    Manager for mapping background capture operations to their capture group IDs.

    Each operation is assigned a unique operation_id and linked to a
    capture_group_id. Mappings are persisted in a JSON file so that
    captures can be looked up later by operation ID.

    JSON schema:
    {
        "<operation_id>": {
            "capture_group_id": "<group_id>",
            "created": <unix_epoch_seconds>
        },
        ...
    }
    """
    def __init__(self, capture_group_id: GroupId, db_path: Path | None = None) -> None:
        """
        Initialize a new operation manager for a given capture group.

        Args:
            capture_group_id: The ID of the capture group to associate.
            db_path: Optional path to the operations DB file; if None,
                     retrieves from ConfigManager under
                     [PnmFileRetrieval].operation_db.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.capture_group_id: GroupId = capture_group_id
        self.operation_id: OperationId = cast(OperationId, uuid.uuid4().hex[:16])

        # Resolve DB file path
        if db_path:
            self.db_path = db_path
        else:
            db_str = SystemConfigSettings.operation_db()
            self.db_path = Path(db_str)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure DB exists
        if not self.db_path.exists():
            self._atomic_write({})

    def _load(self) -> dict[str, Any]:
        """
        Load the operations DB from disk.

        Returns:
            Dict of operation mappings, or empty dict on parse error.
        """
        try:
            if not self.db_path.exists():
                self._atomic_write({})
                return {}
            with self.db_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load operation DB, resetting: {e}")
            return {}

    def _atomic_write(self, data: dict[str, Any]) -> None:
        """
        Atomically write the given data to the DB file.
        """
        temp = self.db_path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        temp.replace(self.db_path)

    def _save(self, data: dict[str, Any]) -> None:
        """
        Persist the given operations dict to disk with atomic write.
        """
        try:
            self._atomic_write(data)
        except Exception as e:
            self.logger.error(f"Failed to save operation DB: {e}")

    def register(self) -> OperationId:
        """
        Register this operation with its capture group ID in the DB.

        Verifies that the associated capture group exists before registration.

        Returns:
            The operation_id assigned.

        Raises:
            ValueError: If the capture_group_id is not present in the CaptureGroup database.
        """
        # Verify that the capture group exists, or fail hard
        from pypnm.api.routes.common.classes.file_capture.capture_group import (
            CaptureGroup,
        )
        cg = CaptureGroup(group_id=self.capture_group_id)
        if self.capture_group_id not in cg.list_groups():
            raise ValueError(
                f"CaptureGroup '{self.capture_group_id}' does not exist"
            )

        with JsonFileLock(self.db_path):
            db = self._load()
            db[self.operation_id] = {
                "capture_group_id": self.capture_group_id,
                "created": int(time.time())
            }
            self._save(db)
            self.logger.info(
                f"Registered operation {self.operation_id} for group {self.capture_group_id}"
            )
        return self.operation_id

    @classmethod
    def get_capture_group(cls, operation_id: OperationId, db_path: Path | None = None) -> GroupId:
        """
        Retrieve the capture_group_id for a given operation_id.

        Args:
            operation_id: The operation ID to look up.
            db_path: Optional override for the operations DB file.

        Returns:
            capture_group_id if found, otherwise None.
            Exception thrown
        """

        if not db_path:
            db_str = SystemConfigSettings.operation_db()
            db_path = Path(db_str)
        try:
            with JsonFileLock(db_path):
                with db_path.open("r", encoding="utf-8") as f:
                    db = json.load(f)
            rec = db.get(operation_id)
            return rec.get("capture_group_id") if isinstance(rec, dict) else None
        except Exception as e:
            cls.logger = logging.getLogger(cls.__name__)
            cls.logger.error(f"Error retrieving capture group for {operation_id}: {e}")
            return ""

    @classmethod
    def list_operations(cls, db_path: Path | None = None) -> list[str]:
        """
        List all registered operation IDs.

        Args:
            db_path: Optional override for the operations DB file.

        Returns:
            List of operation_id strings.
        """
        if not db_path:
            db_str = SystemConfigSettings.operation_db()
            db_path = Path(db_str)
        try:
            with JsonFileLock(db_path):
                with db_path.open("r", encoding="utf-8") as f:
                    return list(json.load(f).keys())
        except Exception as e:
            logging.getLogger(cls.__name__).error(f"Error listing operations: {e}")
            return []

# FILE: tests/test_json_file_lock.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from pypnm.lib.db.json_file_lock import JsonFileLock


def _hold_lock(target: Path, ready: threading.Event, release: threading.Event) -> None:
    with JsonFileLock(target, timeout=1.0, poll_interval=0.01):
        ready.set()
        release.wait(1.0)


def test_json_file_lock_timeout(tmp_path: Path) -> None:
    target = tmp_path / "capture_group.json"
    target.write_text("{}", encoding="utf-8")

    ready = threading.Event()
    release = threading.Event()
    thread = threading.Thread(target=_hold_lock, args=(target, ready, release))
    thread.start()

    assert ready.wait(1.0)
    with pytest.raises(TimeoutError):
        with JsonFileLock(target, timeout=0.1, poll_interval=0.01):
            pass

    release.set()
    thread.join()

# FILE: tests/test_capture_group_concurrency.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from multiprocessing import get_context
from multiprocessing.synchronize import Event
from pathlib import Path

import pytest

from pypnm.api.routes.common.classes.file_capture.capture_group import CaptureGroup
from pypnm.lib.types import GroupId, TransactionId


def _add_transaction_worker(
    db_path: str,
    group_id: GroupId,
    txn_id: TransactionId,
    ready_event: Event,
    start_event: Event,
) -> None:
    ready_event.set()
    start_event.wait(5.0)
    capture_group = CaptureGroup(group_id=group_id, db_path=Path(db_path))
    capture_group.add_transaction(txn_id)


def test_capture_group_add_transaction_concurrent_processes(tmp_path: Path) -> None:
    ctx = get_context("fork")
    process_count = 250
    db_path = tmp_path / "capture_group.json"
    group_id = GroupId("group-250")

    CaptureGroup(group_id=group_id, db_path=db_path).create_group()

    start_event = ctx.Event()
    ready_events: list[Event] = []
    processes = []
    txn_ids = [TransactionId(f"txn-{idx}") for idx in range(process_count)]

    for txn_id in txn_ids:
        ready_event = ctx.Event()
        proc = ctx.Process(
            target=_add_transaction_worker,
            args=(str(db_path), group_id, txn_id, ready_event, start_event),
        )
        proc.start()
        ready_events.append(ready_event)
        processes.append(proc)

    assert all(ev.wait(5.0) for ev in ready_events)
    start_event.set()

    for proc in processes:
        proc.join(10.0)
        assert proc.exitcode == 0

    capture_group = CaptureGroup(group_id=group_id, db_path=db_path)
    collected = set(capture_group.getTransactionIds())
    assert collected == set(txn_ids)
