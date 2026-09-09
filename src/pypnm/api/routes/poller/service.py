# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_for_futures
from datetime import datetime, timedelta, timezone
from datetime import time as datetime_time
from queue import Empty, Queue
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pymysql
import pymysql.cursors
import requests

logger = logging.getLogger(__name__)

_CPE_TASK_TYPE = "cpe_address_refresh"
_CPE_TASK_SYSTEM_KEY = "cpe-address-refresh"
_CPE_TASK_NAME = "CPE address refresh"
_CPE_TASK_SCHEDULE = (datetime_time(hour=0), datetime_time(hour=12))
_INVENTORY_RECONCILE_TASK_TYPE = "inventory_reconcile"
_INVENTORY_RECONCILE_SYSTEM_KEY = "inventory-light-reconcile"
_INVENTORY_RECONCILE_NAME = "Inventory light reconciliation"
_INVENTORY_FULL_TASK_TYPE = "inventory_full"
_INVENTORY_FULL_SYSTEM_KEY = "inventory-daily-full"
_INVENTORY_FULL_NAME = "Inventory daily full refresh"
_INVENTORY_FULL_SCHEDULE = datetime_time(hour=1)
_INVENTORY_TASK_TYPES = frozenset(
    {
        "inventory",
        _INVENTORY_RECONCILE_TASK_TYPE,
        _INVENTORY_FULL_TASK_TYPE,
    }
)
_INVENTORY_TARGET_MANIFEST_VERSION = 2
_IDENTITY_SYSDESCR_OID = "1.3.6.1.2.1.1.1.0"
_IDENTITY_FIRMWARE_OID = "1.3.6.1.2.1.69.1.3.2.0"
_IDENTITY_DOCSIS_CAPABILITY_OID = "1.3.6.1.4.1.4491.2.1.28.1.1.0"
_IDENTITY_REQUEST_SOURCE = "inventory-identity"


class _IdentityDispatchBlocked(RuntimeError):
    """Identity dispatch is paused until a timed-out agent reconnects."""


class _PollerJobNotRunning(RuntimeError):
    """Raised when a cancelled poller job must not persist fetched data."""


class _PollerRunAlreadyActive(RuntimeError):
    """Raised when an explicit run loses a race to another active job."""

    def __init__(self, job_id: int) -> None:
        self.job_id = int(job_id)
        super().__init__(f"Poller job {self.job_id} is already active")


class _PollerOutsideRunWindow(RuntimeError):
    """Raised when an explicit run is outside its locked setting window."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class PollerService:
    def __init__(self) -> None:
        self._db_lock = threading.Lock()
        # Thread-local storage for persistent connections (one per thread).
        # Avoids the overhead of a new TCP handshake per query while remaining
        # thread-safe without an external pool library.
        self._tls = threading.local()
        self.backend = "mysql"
        scheduler_enabled_default = (os.environ.get("DATA_STORE_SCHEDULER_ENABLED", "true").strip().lower() == "true")

        self._scheduler: Dict[str, Any] = {
            "enabled": scheduler_enabled_default,
            "running": False,
            "last_tick": None,
            "poll_sec": 60,
            "decisions": [],
        }
        self._worker_started = False
        self._identity_agent_lock = threading.Lock()
        self._identity_blocked_agents: set[tuple[str, int]] = set()
        self._identity_events: Queue = Queue()

        self._init_db()
        self._start_worker()

    def _db_name(self) -> str:
        return os.environ.get("DATA_DB_NAME") or os.environ.get("AUTH_DB_NAME") or "pypnm_auth"

    @staticmethod
    def _cm_modem_limit_default() -> int:
        raw = os.environ.get("CM_MODEM_LIMIT", "50000")
        try:
            value = int(raw)
            return max(1, min(value, 50000))
        except (TypeError, ValueError):
            return 50000

    @staticmethod
    def _db_timeout_seconds(name: str, default: int) -> int:
        try:
            return max(10, min(int(os.environ.get(name, str(default))), 600))
        except (TypeError, ValueError):
            return default

    def _connect(self):
        return pymysql.connect(
            host=os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DATA_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306")),
            user=os.environ.get("DATA_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm"),
            password=os.environ.get("DATA_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm"),
            database=self._db_name(),
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=self._db_timeout_seconds("DATA_DB_READ_TIMEOUT_SEC", 120),
            write_timeout=self._db_timeout_seconds("DATA_DB_WRITE_TIMEOUT_SEC", 120),
        )

    def _get_conn(self):
        """Return a thread-local persistent connection, reconnecting if stale."""
        conn = getattr(self._tls, "conn", None)
        if conn is not None:
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                self._tls.conn = None
        self._tls.conn = self._connect()
        return self._tls.conn

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        compact = (
            (mac or "").strip().lower()
            .replace(":", "")
            .replace("-", "")
            .replace(".", "")
            .replace(" ", "")
        )
        if len(compact) != 12 or any(ch not in "0123456789abcdef" for ch in compact):
            return ""
        return ":".join(compact[i : i + 2] for i in range(0, 12, 2))

    def _rows(self, cur):
        return cur.fetchall()

    def _execute(self, sql: str, params=None):
        params = params or ()
        with self._db_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                try:
                    last_id = cur.lastrowid
                except Exception:
                    last_id = None
            except Exception:
                # Discard the thread-local connection on error so next call reconnects.
                try:
                    conn.close()
                except Exception:
                    pass
                self._tls.conn = None
                raise
            return last_id

    def _query(self, sql: str, params=None):
        # Reads use the same thread-local connection (no write lock needed —
        # each thread has its own connection so reads never contend with writes
        # happening on a different thread's connection).
        params = params or ()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = self._rows(cur)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            self._tls.conn = None
            raise
        return rows

    def _init_db(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS modem_inventory_current (
                mac VARCHAR(17) NOT NULL,
                ip VARCHAR(45) NULL,
                cmts VARCHAR(128) NOT NULL,
                cmts_ip VARCHAR(45) NULL,
                cmts_index VARCHAR(128) NULL,
                docsif3_index VARCHAR(128) NULL,
                fiber_node VARCHAR(128) NULL,
                cable_mac VARCHAR(128) NULL,
                mac_domain VARCHAR(128) NULL,
                status VARCHAR(64) NULL,
                docsis_version VARCHAR(32) NULL,
                vendor VARCHAR(64) NULL,
                model VARCHAR(128) NULL,
                upstream_interface VARCHAR(128) NULL,
                upstream_ifindex BIGINT NULL,
                ofdm_ifindex BIGINT NULL,
                ofdma_ifindex BIGINT NULL,
                ofdm_channel_count INT NULL,
                ofdma_channel_count INT NULL,
                ofdma_rf_port_ifindex BIGINT NULL,
                ofdm_enabled BOOLEAN NULL,
                ofdma_enabled BOOLEAN NULL,
                partial_service BOOLEAN NULL,
                partial_service_downstream BOOLEAN NULL,
                partial_service_upstream BOOLEAN NULL,
                partial_service_state VARCHAR(16) NULL,
                software_version VARCHAR(128) NULL,
                first_seen_at DATETIME NOT NULL,
                last_seen_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                source_poller VARCHAR(64) NULL,
                snapshot_id CHAR(36) NULL,
                inventory_state VARCHAR(24) NOT NULL DEFAULT 'active',
                missing_since DATETIME NULL,
                consecutive_full_misses INT NOT NULL DEFAULT 0,
                retired_at DATETIME NULL,
                PRIMARY KEY (mac),
                INDEX idx_inv_cmts (cmts, mac),
                INDEX idx_inv_cmts_ip (cmts_ip),
                INDEX idx_inv_fiber_node (fiber_node),
                INDEX idx_inv_vendor (vendor),
                INDEX idx_inv_model (model),
                INDEX idx_inv_software_version (software_version),
                INDEX idx_inv_docsis_version (docsis_version),
                INDEX idx_inv_cmts_state (cmts_ip, inventory_state, mac),
                INDEX idx_inv_retired (inventory_state, retired_at),
                INDEX idx_inv_ip_state (ip, inventory_state, mac),
                INDEX idx_inv_state_order (inventory_state, cmts, mac)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS modem_cpe_ip_current (
                cmts_ip VARCHAR(45) NOT NULL,
                docsif3_index VARCHAR(128) NOT NULL,
                cpe_id VARCHAR(32) NOT NULL,
                modem_mac VARCHAR(17) NOT NULL,
                address_family VARCHAR(4) NOT NULL,
                ip_address VARCHAR(45) NOT NULL,
                prefix_length SMALLINT UNSIGNED NOT NULL,
                snapshot_id CHAR(36) NULL,
                first_seen_at DATETIME NOT NULL,
                last_seen_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (cmts_ip, docsif3_index, cpe_id),
                INDEX idx_cpe_address (address_family, ip_address, modem_mac),
                INDEX idx_cpe_modem (modem_mac, address_family, ip_address)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS poller_setting (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(64) NOT NULL,
                task_type VARCHAR(32) NOT NULL DEFAULT 'inventory',
                system_key VARCHAR(64) NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                scope_type VARCHAR(16) NOT NULL DEFAULT 'all_cmts',
                scope_json JSON NULL,
                collect_identity BOOLEAN NOT NULL DEFAULT TRUE,
                collect_scqam BOOLEAN NOT NULL DEFAULT FALSE,
                collect_rxmer BOOLEAN NOT NULL DEFAULT FALSE,
                interval_minutes INT NOT NULL DEFAULT 360,
                run_window_start TIME NULL,
                run_window_end TIME NULL,
                max_concurrency INT NOT NULL DEFAULT 1,
                max_agent_queue_depth INT NOT NULL DEFAULT 20,
                retention_days INT NOT NULL DEFAULT 30,
                heavy_window_start TIME NULL,
                heavy_window_end TIME NULL,
                heavy_max_modems INT NOT NULL DEFAULT 300,
                heavy_delay_ms INT NOT NULL DEFAULT 0,
                max_runtime_sec INT NOT NULL DEFAULT 3600,
                last_target_offset INT NOT NULL DEFAULT 0,
                last_scheduled_slot_utc DATETIME NULL,
                last_interval_enqueue_utc DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_poller_setting_name (name),
                UNIQUE KEY uk_poller_setting_system_key (system_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS poller_job (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                poller_id BIGINT NOT NULL,
                trigger_type VARCHAR(24) NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'queued',
                rows_collected INT NOT NULL DEFAULT 0,
                modems_attempted INT NOT NULL DEFAULT 0,
                modems_succeeded INT NOT NULL DEFAULT 0,
                modems_failed INT NOT NULL DEFAULT 0,
                requested_by VARCHAR(64) NULL,
                request_payload JSON NULL,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                error_text TEXT NULL,
                cmts_breakdown JSON NULL,
                scheduled_slot_utc DATETIME NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_job_status_created (status, created_at),
                UNIQUE KEY uk_job_scheduled_slot (poller_id, scheduled_slot_utc)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS cmts_inventory_snapshot (
                cmts_ip VARCHAR(45) NOT NULL,
                cmts VARCHAR(128) NOT NULL,
                area VARCHAR(16) NOT NULL DEFAULT 'unknown',
                snapshot_id CHAR(36) NOT NULL,
                complete BOOLEAN NOT NULL DEFAULT FALSE,
                truncated BOOLEAN NOT NULL DEFAULT FALSE,
                capability_enriched BOOLEAN NOT NULL DEFAULT FALSE,
                requested_limit INT NOT NULL,
                row_count INT NOT NULL DEFAULT 0,
                collected_at DATETIME NOT NULL,
                source VARCHAR(32) NOT NULL DEFAULT 'snmp-live',
                source_poller VARCHAR(64) NULL,
                critical_oid_errors JSON NULL,
                raw_legacy_mac_count INT NULL,
                raw_d3_mac_count INT NULL,
                authoritative BOOLEAN NOT NULL DEFAULT FALSE,
                quarantined BOOLEAN NOT NULL DEFAULT FALSE,
                quarantine_reason VARCHAR(255) NULL,
                quarantine_candidate_count INT NULL,
                quarantine_candidate_fingerprint CHAR(64) NULL,
                collection_mode VARCHAR(16) NOT NULL DEFAULT 'full',
                revision_at DATETIME NOT NULL,
                PRIMARY KEY (cmts_ip),
                INDEX idx_inventory_snapshot_cmts (cmts),
                INDEX idx_inventory_snapshot_area (area, cmts_ip),
                INDEX idx_inventory_snapshot_collected (collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_shrink_candidate (
                cmts_ip VARCHAR(45) NOT NULL,
                collection_mode VARCHAR(16) NOT NULL,
                candidate_count INT NOT NULL,
                candidate_fingerprint CHAR(64) NULL,
                candidate_macs MEDIUMTEXT NOT NULL,
                observed_at DATETIME NOT NULL,
                PRIMARY KEY (cmts_ip, collection_mode),
                INDEX idx_shrink_candidate_observed (observed_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_summary_status (
                cmts_ip VARCHAR(45) NOT NULL,
                cmts VARCHAR(128) NOT NULL,
                area VARCHAR(16) NOT NULL DEFAULT 'unknown',
                active_total BIGINT NOT NULL DEFAULT 0,
                enriched_count BIGINT NOT NULL DEFAULT 0,
                last_updated DATETIME NULL,
                refreshed_at DATETIME NOT NULL,
                PRIMARY KEY (cmts_ip),
                INDEX idx_summary_status_cmts (cmts),
                INDEX idx_summary_status_area (area, cmts_ip)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_summary_count (
                cmts_ip VARCHAR(45) NOT NULL,
                dimension VARCHAR(32) NOT NULL,
                value VARCHAR(255) NOT NULL,
                row_count BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (cmts_ip, dimension, value),
                INDEX idx_summary_dimension_value (dimension, value),
                INDEX idx_summary_value_dimension (value, dimension)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_summary_daily (
                snapshot_date DATE NOT NULL,
                cmts_ip VARCHAR(45) NOT NULL,
                cmts VARCHAR(128) NOT NULL,
                area VARCHAR(16) NOT NULL DEFAULT 'unknown',
                dimension VARCHAR(32) NOT NULL,
                value VARCHAR(255) NOT NULL,
                row_count BIGINT NOT NULL DEFAULT 0,
                collected_at DATETIME NOT NULL,
                refreshed_at DATETIME NOT NULL,
                PRIMARY KEY (snapshot_date, cmts_ip, dimension, value),
                INDEX idx_daily_dimension_date (dimension, snapshot_date),
                INDEX idx_daily_area_date (area, snapshot_date, dimension),
                INDEX idx_daily_cmts_date (cmts_ip, snapshot_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_decision_log (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                tick_at DATETIME NOT NULL,
                poller_id BIGINT NULL,
                poller_name VARCHAR(64) NULL,
                decision VARCHAR(16) NOT NULL,
                reason VARCHAR(64) NULL,
                effective_load INT NULL,
                threshold INT NULL,
                detail VARCHAR(255) NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_scheduler_tick (tick_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        # Backward-compatible upgrades for already-existing inventory tables.
        # Add all missing columns in one ALTER so a large table is rebuilt at
        # most once on MySQL versions that cannot apply ADD COLUMN instantly.
        inventory_columns = {
            "software_version": "VARCHAR(128) NULL",
            "partial_service_downstream": "BOOLEAN NULL",
            "partial_service_upstream": "BOOLEAN NULL",
            "partial_service_state": "VARCHAR(16) NULL",
            "cmts_index": "VARCHAR(128) NULL",
            "docsif3_index": "VARCHAR(128) NULL",
            "ofdm_ifindex": "BIGINT NULL",
            "ofdm_channel_count": "INT NULL",
            "ofdma_channel_count": "INT NULL",
            "snapshot_id": "CHAR(36) NULL",
            "inventory_state": "VARCHAR(24) NOT NULL DEFAULT 'active'",
            "missing_since": "DATETIME NULL",
            "consecutive_full_misses": "INT NOT NULL DEFAULT 0",
            "retired_at": "DATETIME NULL",
        }
        existing_inventory_columns = {
            str(row.get("Field"))
            for row in self._query("SHOW COLUMNS FROM modem_inventory_current")
        }
        missing_inventory_columns = [
            name for name in inventory_columns if name not in existing_inventory_columns
        ]
        if missing_inventory_columns:
            clauses = ", ".join(
                f"ADD COLUMN `{name}` {inventory_columns[name]}"
                for name in missing_inventory_columns
            )
            try:
                self._execute(f"ALTER TABLE modem_inventory_current {clauses}")
            except Exception as exc:
                remaining = {
                    str(row.get("Field"))
                    for row in self._query("SHOW COLUMNS FROM modem_inventory_current")
                }
                still_missing = [
                    name for name in missing_inventory_columns if name not in remaining
                ]
                if still_missing:
                    raise RuntimeError(
                        "Failed to add required modem inventory columns: "
                        + ", ".join(still_missing)
                    ) from exc

        for ddl in [
            "ALTER TABLE scheduler_decision_log ADD COLUMN poller_id BIGINT NULL",
            "ALTER TABLE scheduler_decision_log ADD COLUMN poller_name VARCHAR(64) NULL",
            "ALTER TABLE scheduler_decision_log ADD COLUMN reason VARCHAR(64) NULL",
            "ALTER TABLE scheduler_decision_log ADD COLUMN effective_load INT NULL",
            "ALTER TABLE scheduler_decision_log ADD COLUMN threshold INT NULL",
            "ALTER TABLE scheduler_decision_log ADD COLUMN detail VARCHAR(255) NULL",
            "ALTER TABLE scheduler_decision_log ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        ]:
            try:
                self._execute(ddl)
            except Exception:
                pass

        setting_columns = {
            str(row.get("Field"))
            for row in self._query("SHOW COLUMNS FROM poller_setting")
        }
        missing_setting_columns = []
        if "task_type" not in setting_columns:
            missing_setting_columns.append(
                "ADD COLUMN `task_type` VARCHAR(32) NOT NULL DEFAULT 'inventory'"
            )
        if "system_key" not in setting_columns:
            missing_setting_columns.append("ADD COLUMN `system_key` VARCHAR(64) NULL")
        if "last_scheduled_slot_utc" not in setting_columns:
            missing_setting_columns.append(
                "ADD COLUMN `last_scheduled_slot_utc` DATETIME NULL"
            )
        if "last_interval_enqueue_utc" not in setting_columns:
            missing_setting_columns.append(
                "ADD COLUMN `last_interval_enqueue_utc` DATETIME NULL"
            )
        if missing_setting_columns:
            self._execute(
                "ALTER TABLE poller_setting " + ", ".join(missing_setting_columns)
            )
        self._execute(
            """
            UPDATE poller_setting p
            LEFT JOIN (
                SELECT poller_id, MAX(created_at) AS last_created_at
                FROM poller_job
                GROUP BY poller_id
            ) j ON j.poller_id = p.id
            SET p.last_interval_enqueue_utc = j.last_created_at
            WHERE p.task_type = 'inventory'
              AND j.last_created_at IS NOT NULL
              AND (
                  p.last_interval_enqueue_utc IS NULL
                  OR p.last_interval_enqueue_utc < j.last_created_at
              )
            """
        )

        job_columns = {
            str(row.get("Field"))
            for row in self._query("SHOW COLUMNS FROM poller_job")
        }
        if "scheduled_slot_utc" not in job_columns:
            self._execute(
                "ALTER TABLE poller_job "
                "ADD COLUMN `scheduled_slot_utc` DATETIME NULL"
            )

        required_indexes = {
            "poller_setting": (
                "uk_poller_setting_system_key",
                "CREATE UNIQUE INDEX uk_poller_setting_system_key "
                "ON poller_setting (system_key)",
            ),
            "poller_job": (
                "uk_job_scheduled_slot",
                "CREATE UNIQUE INDEX uk_job_scheduled_slot "
                "ON poller_job (poller_id, scheduled_slot_utc)",
            ),
        }
        for table, (index_name, ddl) in required_indexes.items():
            indexes = {
                str(row.get("Key_name"))
                for row in self._query(f"SHOW INDEX FROM {table}")
            }
            if index_name not in indexes:
                self._execute(ddl)
        for table, (index_name, _) in required_indexes.items():
            indexes = {
                str(row.get("Key_name"))
                for row in self._query(f"SHOW INDEX FROM {table}")
            }
            if index_name not in indexes:
                raise RuntimeError(
                    f"Required database index {table}.{index_name} is missing"
                )

        cpe_by_key = self._query(
            "SELECT id FROM poller_setting WHERE system_key=%s LIMIT 1",
            (_CPE_TASK_SYSTEM_KEY,),
        )
        cpe_by_name = self._query(
            "SELECT id FROM poller_setting WHERE name=%s LIMIT 1",
            (_CPE_TASK_NAME,),
        )
        if (
            cpe_by_key
            and cpe_by_name
            and int(cpe_by_key[0]["id"]) != int(cpe_by_name[0]["id"])
        ):
            raise RuntimeError(
                "Conflicting CPE system task rows exist; refusing unsafe adoption"
            )
        existing_cpe_task = cpe_by_key or cpe_by_name
        if existing_cpe_task:
            self._execute(
                "UPDATE poller_setting SET task_type=%s, system_key=%s, name=%s, "
                "scope_type='all_cmts', scope_json=NULL, collect_identity=FALSE, "
                "collect_scqam=FALSE, collect_rxmer=FALSE, interval_minutes=720, "
                "max_concurrency=10, max_runtime_sec=43200, updated_at=%s WHERE id=%s",
                (
                    _CPE_TASK_TYPE,
                    _CPE_TASK_SYSTEM_KEY,
                    _CPE_TASK_NAME,
                    self._now(),
                    int(existing_cpe_task[0]["id"]),
                ),
            )
        else:
            now = self._now()
            self._execute(
                """
                INSERT INTO poller_setting
                    (name, task_type, system_key, enabled, scope_type, scope_json,
                     collect_identity, collect_scqam, collect_rxmer,
                     interval_minutes, max_concurrency, max_agent_queue_depth,
                     retention_days, heavy_max_modems, heavy_delay_ms,
                     max_runtime_sec, last_target_offset, created_at, updated_at)
                VALUES (%s,%s,%s,TRUE,'all_cmts',NULL,FALSE,FALSE,FALSE,
                        720,10,20,30,300,0,43200,0,%s,%s)
                """,
                (_CPE_TASK_NAME, _CPE_TASK_TYPE, _CPE_TASK_SYSTEM_KEY, now, now),
            )

        def _ensure_inventory_system_task(
            *,
            name: str,
            task_type: str,
            system_key: str,
            interval_minutes: int,
            max_runtime_sec: int,
        ) -> None:
            now = self._now()
            self._execute(
                """
                INSERT INTO poller_setting
                    (name, task_type, system_key, enabled, scope_type, scope_json,
                     collect_identity, collect_scqam, collect_rxmer,
                     interval_minutes, max_concurrency, max_agent_queue_depth,
                     retention_days, heavy_max_modems, heavy_delay_ms,
                     max_runtime_sec, last_target_offset, created_at, updated_at)
                VALUES (%s,%s,%s,TRUE,'all_cmts',NULL,FALSE,FALSE,FALSE,
                        %s,4,20,30,300,0,%s,0,%s,%s)
                ON DUPLICATE KEY UPDATE id=id
                """,
                (
                    name,
                    task_type,
                    system_key,
                    interval_minutes,
                    max_runtime_sec,
                    now,
                    now,
                ),
            )
            by_key = self._query(
                "SELECT id, system_key FROM poller_setting "
                "WHERE system_key=%s LIMIT 1",
                (system_key,),
            )
            by_name = self._query(
                "SELECT id, system_key FROM poller_setting WHERE name=%s LIMIT 1",
                (name,),
            )
            if (
                by_key
                and by_name
                and int(by_key[0]["id"]) != int(by_name[0]["id"])
            ):
                raise RuntimeError(
                    f"Conflicting {name} system task rows exist; refusing unsafe adoption"
                )
            if (
                by_name
                and by_name[0].get("system_key")
                and str(by_name[0]["system_key"]) != system_key
            ):
                raise RuntimeError(
                    f"{name} is already assigned to another protected system task"
                )
            existing = by_key or by_name
            if not existing:
                raise RuntimeError(f"Failed to create or adopt {name} system task")
            self._execute(
                "UPDATE poller_setting SET task_type=%s, system_key=%s, name=%s, "
                "scope_type='all_cmts', scope_json=NULL, collect_identity=FALSE, "
                "collect_scqam=FALSE, collect_rxmer=FALSE, interval_minutes=%s, "
                "run_window_start=NULL, run_window_end=NULL, "
                "max_concurrency=4, max_runtime_sec=%s, updated_at=%s WHERE id=%s",
                (
                    task_type,
                    system_key,
                    name,
                    interval_minutes,
                    max_runtime_sec,
                    now,
                    int(existing[0]["id"]),
                ),
            )

        _ensure_inventory_system_task(
            name=_INVENTORY_RECONCILE_NAME,
            task_type=_INVENTORY_RECONCILE_TASK_TYPE,
            system_key=_INVENTORY_RECONCILE_SYSTEM_KEY,
            interval_minutes=60,
            max_runtime_sec=14400,
        )
        _ensure_inventory_system_task(
            name=_INVENTORY_FULL_NAME,
            task_type=_INVENTORY_FULL_TASK_TYPE,
            system_key=_INVENTORY_FULL_SYSTEM_KEY,
            interval_minutes=1440,
            max_runtime_sec=43200,
        )

        snapshot_columns = {
            "revision_at": "DATETIME NULL",
            "area": "VARCHAR(16) NOT NULL DEFAULT 'unknown'",
            "capability_enriched": "BOOLEAN NOT NULL DEFAULT FALSE",
            "authoritative": "BOOLEAN NOT NULL DEFAULT FALSE",
            "quarantined": "BOOLEAN NOT NULL DEFAULT FALSE",
            "quarantine_reason": "VARCHAR(255) NULL",
            "quarantine_candidate_count": "INT NULL",
            "quarantine_candidate_fingerprint": "CHAR(64) NULL",
            "collection_mode": "VARCHAR(16) NOT NULL DEFAULT 'full'",
        }
        existing_snapshot_columns = {
            str(row.get("Field"))
            for row in self._query("SHOW COLUMNS FROM cmts_inventory_snapshot")
        }
        missing_snapshot_columns = [
            name for name in snapshot_columns if name not in existing_snapshot_columns
        ]
        if missing_snapshot_columns:
            clauses = ", ".join(
                f"ADD COLUMN `{name}` {snapshot_columns[name]}"
                for name in missing_snapshot_columns
            )
            try:
                self._execute(f"ALTER TABLE cmts_inventory_snapshot {clauses}")
            except Exception as exc:
                remaining = {
                    str(row.get("Field"))
                    for row in self._query("SHOW COLUMNS FROM cmts_inventory_snapshot")
                }
                still_missing = [
                    name for name in missing_snapshot_columns if name not in remaining
                ]
                if still_missing:
                    raise RuntimeError(
                        "Failed to add required inventory snapshot columns: "
                        + ", ".join(still_missing)
                    ) from exc
        self._execute(
            "UPDATE cmts_inventory_snapshot "
            "SET revision_at=collected_at WHERE revision_at IS NULL"
        )

        summary_status_columns = {
            str(row.get("Field"))
            for row in self._query("SHOW COLUMNS FROM inventory_summary_status")
        }
        summary_area_needs_backfill = "area" not in summary_status_columns
        if summary_area_needs_backfill:
            try:
                self._execute(
                    "ALTER TABLE inventory_summary_status "
                    "ADD COLUMN `area` VARCHAR(16) NOT NULL DEFAULT 'unknown'"
                )
            except Exception as exc:
                remaining = {
                    str(row.get("Field"))
                    for row in self._query(
                        "SHOW COLUMNS FROM inventory_summary_status"
                    )
                }
                if "area" not in remaining:
                    raise RuntimeError(
                        "Failed to add required inventory summary area column"
                    ) from exc

        # Repair interrupted area migrations one unknown CMTS at a time. The
        # existing cmts_ip index bounds each aggregate and each autocommitted
        # update makes the migration restart-safe without one long DB query that
        # can time out and prevent the poller router from loading.
        area_sql = self._inventory_area_aggregate_sql("m")
        pending_area_rows = self._query(
            "SELECT cmts_ip FROM inventory_summary_status "
            "WHERE area='unknown' AND COALESCE(cmts_ip,'')<>'' "
            "ORDER BY cmts_ip"
        )
        for pending_area_row in pending_area_rows:
            cmts_ip = str(pending_area_row.get("cmts_ip") or "").strip()
            if not cmts_ip:
                continue
            classified_rows = self._query(
                f"SELECT {area_sql} AS area FROM modem_inventory_current m "
                "WHERE m.inventory_state='active' AND m.cmts_ip=%s",
                (cmts_ip,),
            )
            classified_area = str(
                (classified_rows[0] if classified_rows else {}).get("area")
                or "unknown"
            ).strip().lower()
            if classified_area not in {"fziggo", "fupc"}:
                continue
            self._execute(
                "UPDATE inventory_summary_status SET area=%s "
                "WHERE cmts_ip=%s AND area='unknown'",
                (classified_area, cmts_ip),
            )
        self._execute(
            "UPDATE cmts_inventory_snapshot snap "
            "JOIN inventory_summary_status s ON s.cmts_ip=snap.cmts_ip "
            "SET snap.area=s.area WHERE snap.area='unknown' "
            "AND s.area<>'unknown'"
        )

        for idx_ddl in [
            "CREATE INDEX idx_inventory_snapshot_area "
            "ON cmts_inventory_snapshot (area, cmts_ip)",
            "CREATE INDEX idx_summary_status_area "
            "ON inventory_summary_status (area, cmts_ip)",
        ]:
            try:
                self._execute(idx_ddl)
            except Exception:
                pass

        # Repair only today's rows before seeding. Historical area assignments are
        # unknowable, and INSERT IGNORE cannot correct an already-seeded unknown.
        self._execute(
            "UPDATE inventory_summary_daily d "
            "JOIN inventory_summary_status s ON s.cmts_ip=d.cmts_ip "
            "SET d.area=s.area WHERE d.snapshot_date=UTC_DATE() "
            "AND d.area='unknown' AND s.area<>'unknown'"
        )

        # Current distributions are the only safe source for startup history.
        # Seed only absent rows for today's UTC date; older dates are unknowable.
        self._execute(
            "INSERT IGNORE INTO inventory_summary_daily "
            "(snapshot_date, cmts_ip, cmts, area, dimension, value, row_count, "
            "collected_at, refreshed_at) "
            "SELECT UTC_DATE(), c.cmts_ip, s.cmts, s.area, c.dimension, c.value, "
            "c.row_count, COALESCE(s.last_updated, s.refreshed_at, UTC_TIMESTAMP()), "
            "s.refreshed_at FROM inventory_summary_count c "
            "JOIN inventory_summary_status s ON s.cmts_ip=c.cmts_ip"
        )

        # Existing deployments must apply these indexes as a serialized schema
        # migration before starting the API. Runtime verification is deliberately
        # read-only so module import never performs multi-million-row DDL.
        required_inventory_indexes = {
            "idx_inv_cmts",
            "idx_inv_cmts_ip",
            "idx_inv_fiber_node",
            "idx_inv_vendor",
            "idx_inv_model",
            "idx_inv_software_version",
            "idx_inv_docsis_version",
            "idx_inv_cmts_state",
            "idx_inv_retired",
            "idx_inv_ip_state",
            "idx_inv_state_order",
        }
        inventory_indexes = {
            str(row.get("Key_name"))
            for row in self._query("SHOW INDEX FROM modem_inventory_current")
        }
        missing_inventory_indexes = sorted(
            required_inventory_indexes - inventory_indexes
        )
        if missing_inventory_indexes:
            raise RuntimeError(
                "Required modem inventory indexes are missing; apply the schema "
                "migration before starting the API: "
                + ", ".join(missing_inventory_indexes)
            )

        self._execute(
            """
            CREATE TABLE IF NOT EXISTS modem_rf_snapshot (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                mac VARCHAR(17) NOT NULL,
                cmts VARCHAR(128) NOT NULL,
                collected_at DATETIME NOT NULL,
                scqam_json JSON NULL,
                rxmer_json JSON NULL,
                poller_name VARCHAR(64) NOT NULL,
                INDEX idx_snapshot_collected (collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS modem_refresh_request (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                mac VARCHAR(17) NOT NULL,
                cmts VARCHAR(128) NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'queued',
                requested_by VARCHAR(64) NULL,
                created_at DATETIME NOT NULL,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                error_text TEXT NULL,
                attempt_count INT NOT NULL DEFAULT 0,
                next_attempt_at DATETIME NULL,
                last_attempt_at DATETIME NULL,
                claim_token CHAR(36) NULL,
                agent_task_id CHAR(36) NULL,
                agent_id VARCHAR(128) NULL,
                dispatched_at DATETIME NULL,
                dispatch_deadline_at DATETIME NULL,
                response_received_at DATETIME NULL,
                target_ip VARCHAR(45) NULL,
                target_cmts_ip VARCHAR(45) NULL,
                target_inventory_updated_at DATETIME NULL,
                active_key VARCHAR(17) GENERATED ALWAYS AS (
                    CASE WHEN status IN ('queued','running') THEN mac ELSE NULL END
                ) STORED,
                INDEX idx_refresh_status (status, next_attempt_at, created_at),
                INDEX idx_refresh_mac (mac, created_at),
                UNIQUE KEY uk_refresh_active_mac (active_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_identity_cursor (
                id TINYINT PRIMARY KEY,
                cursor_mac VARCHAR(17) NOT NULL DEFAULT '',
                cycle_started_at DATETIME NOT NULL,
                next_scan_at DATETIME NULL,
                queued_count BIGINT NOT NULL DEFAULT 0,
                completed_count BIGINT NOT NULL DEFAULT 0,
                failed_count BIGINT NOT NULL DEFAULT 0,
                last_error VARCHAR(500) NULL,
                updated_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        now = self._now()
        self._execute(
            "INSERT IGNORE INTO inventory_identity_cursor "
            "(id, cursor_mac, cycle_started_at, updated_at) VALUES (1,'',%s,%s)",
            (now, now),
        )
        refresh_columns = {
            str(row.get("Field"))
            for row in self._query("SHOW COLUMNS FROM modem_refresh_request")
        }
        for column, ddl in (
            ("attempt_count", "INT NOT NULL DEFAULT 0"),
            ("next_attempt_at", "DATETIME NULL"),
            ("last_attempt_at", "DATETIME NULL"),
            ("claim_token", "CHAR(36) NULL"),
            ("agent_task_id", "CHAR(36) NULL"),
            ("agent_id", "VARCHAR(128) NULL"),
            ("dispatched_at", "DATETIME NULL"),
            ("dispatch_deadline_at", "DATETIME NULL"),
            ("response_received_at", "DATETIME NULL"),
            ("target_ip", "VARCHAR(45) NULL"),
            ("target_cmts_ip", "VARCHAR(45) NULL"),
            ("target_inventory_updated_at", "DATETIME NULL"),
        ):
            if column not in refresh_columns:
                self._execute(
                    f"ALTER TABLE modem_refresh_request ADD COLUMN {column} {ddl}"
                )
        if "active_key" not in refresh_columns:
            self._execute(
                "ALTER TABLE modem_refresh_request ADD COLUMN active_key VARCHAR(17) "
                "GENERATED ALWAYS AS (CASE WHEN status IN ('queued','running') "
                "THEN mac ELSE NULL END) STORED"
            )
        self._execute(
            "UPDATE modem_refresh_request older "
            "JOIN modem_refresh_request newer ON newer.mac=older.mac "
            "AND newer.id>older.id "
            "AND newer.status IN ('queued','running') "
            "SET older.status='cancelled', older.finished_at=COALESCE(older.finished_at,%s), "
            "older.error_text=COALESCE(older.error_text,'Deduplicated during schema upgrade') "
            "WHERE older.status IN ('queued','running')",
            (self._now(),),
        )
        refresh_index_rows = self._query("SHOW INDEX FROM modem_refresh_request")
        refresh_indexes = {
            str(row.get("Key_name"))
            for row in refresh_index_rows
        }
        status_index_columns = [
            str(row.get("Column_name"))
            for row in sorted(
                (
                    row
                    for row in refresh_index_rows
                    if str(row.get("Key_name")) == "idx_refresh_status"
                ),
                key=lambda row: int(row.get("Seq_in_index") or 0),
            )
        ]
        expected_status_index = ["status", "next_attempt_at", "created_at"]
        if status_index_columns != expected_status_index:
            if "idx_refresh_status" in refresh_indexes:
                self._execute(
                    "ALTER TABLE modem_refresh_request "
                    "DROP INDEX idx_refresh_status, "
                    "ADD INDEX idx_refresh_status "
                    "(status, next_attempt_at, created_at)"
                )
            else:
                self._execute(
                    "CREATE INDEX idx_refresh_status ON modem_refresh_request "
                    "(status, next_attempt_at, created_at)"
                )
        if "uk_refresh_active_mac" not in refresh_indexes:
            self._execute(
                "CREATE UNIQUE INDEX uk_refresh_active_mac "
                "ON modem_refresh_request (active_key)"
            )
        if "uk_refresh_agent_task" not in refresh_indexes:
            self._execute(
                "CREATE UNIQUE INDEX uk_refresh_agent_task "
                "ON modem_refresh_request (agent_task_id)"
            )
        if "idx_refresh_dispatch" not in refresh_indexes:
            self._execute(
                "CREATE INDEX idx_refresh_dispatch ON modem_refresh_request "
                "(status, dispatch_deadline_at)"
            )

    def _start_worker(self) -> None:
        if self._worker_started:
            return
        poller_thread = threading.Thread(
            target=self._worker_loop,
            name="pypnm-poller-worker",
            daemon=True,
        )
        refresh_thread = threading.Thread(
            target=self._refresh_worker_loop,
            name="pypnm-refresh-worker",
            daemon=True,
        )
        poller_thread.start()
        refresh_thread.start()
        self._worker_started = True

    def _try_acquire_worker_lock(self, worker_kind: str = "poller"):
        """Return a dedicated connection holding one singleton worker lock."""
        if worker_kind not in {"poller", "refresh"}:
            raise ValueError(f"Unsupported worker kind: {worker_kind}")
        conn = self._connect()
        lock_name = f"pypnm-{worker_kind}-worker:{self._db_name()}"[:64]
        try:
            cur = conn.cursor()
            cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
            row = cur.fetchone() or {}
            cur.close()
            if int(row.get("acquired") or 0) == 1:
                logger.info(
                    "Acquired %s worker lock for database %s",
                    worker_kind,
                    self._db_name(),
                )
                return conn
        except Exception:
            conn.close()
            raise
        conn.close()
        return None

    def _try_acquire_scheduler_lock(self):
        """Return a dedicated connection holding the scheduler singleton lock."""
        conn = self._connect()
        lock_name = f"pypnm-poller-scheduler:{self._db_name()}"[:64]
        try:
            cur = conn.cursor()
            cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
            row = cur.fetchone() or {}
            cur.close()
            if int(row.get("acquired") or 0) == 1:
                return conn
        except Exception:
            conn.close()
            raise
        conn.close()
        return None

    def _recover_interrupted_poller_work(self) -> None:
        """Requeue poller work orphaned when the poller lock owner stopped."""
        self._execute(
            """
            UPDATE poller_job
            SET status='queued', started_at=NULL, finished_at=NULL,
                error_text='Recovered after poller worker restart'
            WHERE status='running'
            """
        )

    def _recover_interrupted_refresh_work(self) -> None:
        """Recover orphaned refresh work without bypassing identity backoff."""
        now = self._now()
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, attempt_count, dispatched_at "
                    "FROM modem_refresh_request "
                    "WHERE status='running' AND requested_by=%s "
                    "AND (dispatch_deadline_at IS NULL "
                    "OR dispatch_deadline_at<=UTC_TIMESTAMP()) FOR UPDATE",
                    (_IDENTITY_REQUEST_SOURCE,),
                )
                identity_rows = cur.fetchall()
                terminal_failures = 0
                for row in identity_rows:
                    req_id = int(row["id"])
                    attempt_count = int(row.get("attempt_count") or 0)
                    if not row.get("dispatched_at"):
                        next_attempt_at = (
                            datetime.now(timezone.utc) + timedelta(seconds=2)
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute(
                            "UPDATE modem_refresh_request SET status='queued', "
                            "started_at=NULL, finished_at=NULL, next_attempt_at=%s, "
                            "claim_token=NULL, agent_task_id=NULL, agent_id=NULL, "
                            "dispatched_at=NULL, dispatch_deadline_at=NULL, "
                            "response_received_at=NULL, "
                            "error_text='Recovered unacknowledged identity claim' "
                            "WHERE id=%s AND status='running' "
                            "AND dispatched_at IS NULL",
                            (next_attempt_at, req_id),
                        )
                        continue
                    if attempt_count >= self._identity_max_attempts():
                        cur.execute(
                            "UPDATE modem_refresh_request SET status='failed', "
                            "finished_at=%s, next_attempt_at=NULL, claim_token=NULL, "
                            "agent_task_id=NULL, agent_id=NULL, dispatched_at=NULL, "
                            "dispatch_deadline_at=NULL, "
                            "error_text='Identity retry limit reached during recovery' "
                            "WHERE id=%s AND status='running'",
                            (now, req_id),
                        )
                        terminal_failures += int(cur.rowcount or 0)
                        continue
                    next_attempt_at = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=self._identity_retry_delay(attempt_count))
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    cur.execute(
                        "UPDATE modem_refresh_request SET status='queued', "
                        "started_at=NULL, finished_at=NULL, next_attempt_at=%s, "
                        "claim_token=NULL, agent_task_id=NULL, agent_id=NULL, "
                        "dispatched_at=NULL, dispatch_deadline_at=NULL, "
                        "response_received_at=NULL, "
                        "error_text='Recovered expired identity dispatch' "
                        "WHERE id=%s AND status='running'",
                        (next_attempt_at, req_id),
                    )
                if terminal_failures:
                    cur.execute(
                        "UPDATE inventory_identity_cursor SET "
                        "failed_count=failed_count+%s, "
                        "last_error='Identity retry limit reached during recovery', "
                        "updated_at=%s WHERE id=1",
                        (terminal_failures, now),
                    )
                cur.execute(
                    "UPDATE modem_refresh_request SET status='queued', "
                    "started_at=NULL, finished_at=NULL, claim_token=NULL, "
                    "error_text='Recovered after refresh worker restart' "
                    "WHERE status='running' AND COALESCE(requested_by,'')<>%s",
                    (_IDENTITY_REQUEST_SOURCE,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _worker_loop(self) -> None:
        lock_conn = None
        while True:
            if lock_conn is None:
                try:
                    lock_conn = self._try_acquire_worker_lock("poller")
                    if lock_conn is not None:
                        self._recover_interrupted_poller_work()
                except Exception as exc:
                    logger.warning("Poller worker lock/recovery failed: %s", exc)
                    if lock_conn is not None:
                        try:
                            lock_conn.close()
                        except Exception:
                            pass
                        lock_conn = None
                if lock_conn is None:
                    time.sleep(2)
                    continue

            try:
                # Never reconnect this connection implicitly: a reconnect would
                # lose the MySQL advisory lock and could create two workers.
                lock_conn.ping(reconnect=False)
            except Exception:
                try:
                    lock_conn.close()
                except Exception:
                    pass
                lock_conn = None
                continue

            try:
                self._timeout_stale_jobs()
            except Exception as exc:
                logger.warning("Poller timeout sweep failed: %s", exc)

            try:
                self._process_one_job()
            except Exception as exc:
                logger.warning("Poller queue worker failed: %s", exc)

            try:
                if self._scheduler.get("enabled") and self._scheduler_due():
                    self.run_scheduler_once()
            except Exception as exc:
                logger.warning("Poller scheduler tick failed: %s", exc)

            time.sleep(2)

    def _refresh_worker_loop(self) -> None:
        """Dispatch identity work asynchronously and keep manual refresh isolated."""
        lock_conn = None
        manual_executor: ThreadPoolExecutor | None = None
        manual_future = None
        maintenance_due = 0.0
        dispatch_due = 0.0
        manual_due = 0.0
        while True:
            if lock_conn is None:
                if manual_executor is not None:
                    manual_executor.shutdown(wait=False, cancel_futures=True)
                    manual_executor = None
                    manual_future = None
                try:
                    lock_conn = self._try_acquire_worker_lock("refresh")
                    if lock_conn is not None:
                        self._recover_interrupted_refresh_work()
                        manual_executor = ThreadPoolExecutor(
                            max_workers=1,
                            thread_name_prefix="pypnm-manual-refresh",
                        )
                except Exception as exc:
                    logger.warning("Refresh worker lock/recovery failed: %s", exc)
                    if lock_conn is not None:
                        try:
                            lock_conn.close()
                        except Exception:
                            pass
                        lock_conn = None
                if lock_conn is None:
                    time.sleep(2)
                    continue

            try:
                lock_conn.ping(reconnect=False)
            except Exception:
                try:
                    lock_conn.close()
                except Exception:
                    pass
                lock_conn = None
                continue

            completed_events = 0
            for _ in range(512):
                try:
                    event = self._identity_events.get_nowait()
                except Empty:
                    break
                try:
                    self._apply_identity_task_event(event)
                    completed_events += 1
                except Exception as exc:
                    logger.warning("Identity completion processing failed: %s", exc)

            if manual_future is not None and manual_future.done():
                try:
                    manual_future.result()
                except Exception as exc:
                    logger.warning("Manual refresh worker failed: %s", exc)
                manual_future = None

            tick = time.monotonic()
            try:
                if tick >= maintenance_due:
                    self._timeout_stale_refresh_requests()
                    self._expire_identity_dispatches()
                    self._seed_identity_refresh_queue()
                    maintenance_due = tick + 2.0
                if completed_events or tick >= dispatch_due:
                    self._dispatch_identity_tasks()
                    dispatch_due = tick + 0.25
                if (
                    manual_executor is not None
                    and manual_future is None
                    and tick >= manual_due
                ):
                    manual_future = manual_executor.submit(self._process_refresh_queue)
                    manual_due = tick + 2.0
            except Exception as exc:
                logger.warning("Refresh queue scheduling failed: %s", exc)

            time.sleep(0.1)

    def _scheduler_due(self) -> bool:
        last_tick = self._scheduler.get("last_tick")
        poll_sec = max(5, int(self._scheduler.get("poll_sec") or 60))
        if not last_tick:
            return True
        try:
            last_dt = datetime.fromisoformat(str(last_tick).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            return elapsed >= poll_sec
        except Exception:
            return True

    def _timeout_stale_jobs(self) -> None:
        max_runtime = max(60, int(os.environ.get("DATA_STORE_JOB_MAX_RUNTIME_SEC", "14400")))
        self._execute(
            """
            UPDATE poller_job j
            LEFT JOIN poller_setting p ON p.id = j.poller_id
            SET j.status=%s,
                j.finished_at=%s,
                j.error_text=CONCAT('Timed out after ', COALESCE(NULLIF(p.max_runtime_sec, 0), %s), 's')
            WHERE j.status='running' AND j.started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, j.started_at, UTC_TIMESTAMP()) > COALESCE(NULLIF(p.max_runtime_sec, 0), %s)
            """,
            ("timed_out", self._now(), max_runtime, max_runtime),
        )

    def _timeout_stale_refresh_requests(self) -> None:
        # Manual refreshes can consume 70 seconds for identity plus 180 seconds
        # for CMTS interface lookup before persistence. Keep the stale floor
        # above that complete supported path, even when configured lower.
        max_runtime = max(
            300,
            int(os.environ.get("DATA_STORE_REFRESH_MAX_RUNTIME_SEC", "300")),
        )
        max_queue_age = max(
            120,
            int(
                os.environ.get(
                    "DATA_STORE_REFRESH_MAX_QUEUE_AGE_SEC",
                    str(max_runtime),
                )
            ),
        )
        self._execute(
            """
            UPDATE modem_refresh_request
            SET status=%s,
                finished_at=%s,
                error_text=CONCAT('Timed out after ', %s, 's')
            WHERE status='running' AND started_at IS NOT NULL
              AND COALESCE(requested_by,'')<>%s
              AND TIMESTAMPDIFF(SECOND, started_at, UTC_TIMESTAMP()) > %s
            """,
            (
                "timed_out",
                self._now(),
                max_runtime,
                _IDENTITY_REQUEST_SOURCE,
                max_runtime,
            ),
        )
        self._execute(
            """
            UPDATE modem_refresh_request
            SET status=%s,
                finished_at=%s,
                error_text=CONCAT('Expired in queue after ', %s, 's')
            WHERE status='queued' AND created_at IS NOT NULL
              AND COALESCE(requested_by,'')<>%s
              AND (next_attempt_at IS NULL OR next_attempt_at <= UTC_TIMESTAMP())
              AND TIMESTAMPDIFF(
                    SECOND,
                    COALESCE(last_attempt_at, created_at),
                    UTC_TIMESTAMP()
                  ) > %s
            """,
            (
                "timed_out",
                self._now(),
                max_queue_age,
                _IDENTITY_REQUEST_SOURCE,
                max_queue_age,
            ),
        )
    def _log_scheduler_decisions(self, tick_at: str, decisions: List[Dict[str, Any]]) -> None:
        persisted_decisions = [
            decision
            for decision in decisions
            if decision.get("reason") != "outside_run_window"
        ]
        if not persisted_decisions:
            return

        try:
            with self._db_lock:
                conn = self._connect()
                cur = conn.cursor()
                for d in persisted_decisions:
                    vals = (
                        tick_at,
                        d.get("poller_id"),
                        d.get("poller_name"),
                        d.get("decision"),
                        d.get("reason"),
                        d.get("effective_load"),
                        d.get("threshold"),
                        d.get("detail"),
                        self._now(),
                    )
                    cur.execute(
                        """
                        INSERT INTO scheduler_decision_log
                        (tick_at, poller_id, poller_name, decision, reason, effective_load, threshold, detail, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        vals,
                    )
                conn.close()
        except Exception:
            # Keep scheduler operational even if decision logging has schema drift.
            return

    def _get_scheduler_decisions(self, limit: int = 100) -> List[Dict[str, Any]]:
        lim = max(1, int(limit))
        ph = "%s"
        try:
            return self._query(
                f"SELECT tick_at, poller_id, poller_name, decision, reason, effective_load, threshold, detail FROM scheduler_decision_log ORDER BY id DESC LIMIT {ph}",
                (lim,),
            )
        except Exception:
            return list(self._scheduler.get("decisions") or [])

    def clear_scheduler_decisions(self) -> int:
        try:
            before = self._query("SELECT COUNT(*) AS c FROM scheduler_decision_log")
            count_before = int((before[0] or {}).get("c") or 0) if before else 0
            self._execute("DELETE FROM scheduler_decision_log")
            self._scheduler["decisions"] = []
            return count_before
        except Exception:
            return 0

    def _fetch_appdb_cmts(self) -> List[Dict[str, Any]]:
        api_url = os.environ.get("APPDB_API_URL", "https://appdb.oss.local/isw/api").rstrip("/")
        api_user = os.environ.get("APPDB_API_USER", "isw")
        api_pass = os.environ.get("APPDB_API_PASS", "")
        try:
            r = requests.get(
                f"{api_url}/search",
                params={"type": "hostname", "q": "*"},
                auth=(api_user, api_pass) if api_user else None,
                verify=False,
                timeout=20,
            )
            r.raise_for_status()
            payload = r.json() if r.content else {}
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for key in ("data", "results", "items"):
                    val = payload.get(key)
                    if isinstance(val, list):
                        return val
            return []
        except Exception:
            return []

    def _fetch_gui_cmts(self) -> List[Dict[str, Any]]:
        """Fallback CMTS source used by lab GUI selector.

        Expected payload shape from GUI endpoint:
        {"status":"success", "cmts_list":[...]}.
        """
        base = (os.environ.get("PYPNM_GUI_BASE_URL") or "http://127.0.0.1:5050").rstrip("/")
        url = f"{base}/api/cmts"
        try:
            r = requests.get(url, timeout=20, verify=False)
            r.raise_for_status()
            payload = r.json() if r.content else {}
            if isinstance(payload, dict):
                lst = payload.get("cmts_list")
                if isinstance(lst, list):
                    return lst
            if isinstance(payload, list):
                return payload
            return []
        except Exception:
            return []

    def _fetch_inventory_cmts(self) -> List[Dict[str, Any]]:
        """Fallback CMTS source from previously discovered modem inventory."""
        try:
            rows = self._query(
                "SELECT DISTINCT cmts, cmts_ip FROM modem_inventory_current "
                "WHERE inventory_state='active' "
                "AND COALESCE(cmts_ip, '') <> '' LIMIT 2000"
            )
            out: List[Dict[str, Any]] = []
            for r in rows or []:
                ip = str(r.get("cmts_ip") or "").strip()
                if not ip:
                    continue
                out.append(
                    {
                        "HostName": str(r.get("cmts") or ip).strip(),
                        "IPAddress": ip,
                    }
                )
            return out
        except Exception:
            return []

    def _fetch_env_cmts(self) -> List[Dict[str, Any]]:
        """Fallback CMTS source from env var POLLER_CMTS_TARGETS.

        Accepted formats:
        - JSON list: ["172.16.6.200", {"name":"cmts1","ip":"172.16.6.201"}]
        - CSV text: 172.16.6.200,172.16.6.201
        """
        raw = (os.environ.get("POLLER_CMTS_TARGETS") or "").strip()
        if not raw:
            return []

        out: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def _push(name: str, ip: str) -> None:
            ipn = str(ip or "").strip()
            if not ipn or ipn in seen:
                return
            seen.add(ipn)
            out.append({"HostName": str(name or ipn).strip(), "IPAddress": ipn})

        parsed: Any
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str):
                    _push(item, item)
                elif isinstance(item, dict):
                    ip = item.get("ip") or item.get("cmts_ip") or item.get("IPAddress")
                    name = item.get("name") or item.get("HostName")
                    if ip:
                        _push(str(name or ip), str(ip))
        return out

    @staticmethod
    def _is_inventory_ccap_hostname(value: Any) -> bool:
        """Return True only for CMTS hostnames containing the CCAP role marker."""
        return "ccap" in str(value or "").strip().casefold()

    def _cmts_targets_for_poller(self, poller: Dict[str, Any]) -> List[Dict[str, str]]:
        def _norm(s: Any) -> str:
            return str(s or "").strip()

        def _is_ip_literal(v: str) -> bool:
            parts = v.split(".")
            if len(parts) != 4:
                return False
            for p in parts:
                if not p.isdigit():
                    return False
                n = int(p)
                if n < 0 or n > 255:
                    return False
            return True

        def _is_vcas_hostname(value: Any) -> bool:
            return "-vcas" in _norm(value).casefold()

        appdb_rows = self._fetch_appdb_cmts()
        if not appdb_rows:
            appdb_rows = self._fetch_gui_cmts()
        if not appdb_rows:
            appdb_rows = self._fetch_inventory_cmts()
        if not appdb_rows:
            appdb_rows = self._fetch_env_cmts()
        by_name: Dict[str, str] = {}
        all_from_appdb: List[Dict[str, str]] = []
        excluded_vcas_count = 0
        for c in appdb_rows:
            name = _norm(c.get("HostName") or c.get("hostname") or c.get("name"))
            if _is_vcas_hostname(name):
                excluded_vcas_count += 1
                continue
            ip = _norm(c.get("IPAddress") or c.get("ip") or c.get("ip_address"))
            if not ip:
                continue
            name = name or ip
            all_from_appdb.append({"name": name, "ip": ip})
            by_name[name.lower()] = ip

        if excluded_vcas_count:
            logger.info(
                "Filtered %s VCAS non-CMTS devices from poller targets",
                excluded_vcas_count,
            )

        scope_type = _norm(poller.get("scope_type") or "all_cmts").lower()
        if scope_type in {"all_cmts", "all", "all-cmts", "all_cmts_list"}:
            return all_from_appdb

        raw_scope = poller.get("scope_json")
        if not raw_scope:
            # Safe fallback for misconfigured scope in lab: if appdb has targets, use them.
            return all_from_appdb

        scope: Any
        if isinstance(raw_scope, str):
            text = raw_scope.strip()
            if not text:
                return all_from_appdb
            try:
                scope = json.loads(text)
            except Exception:
                # Accept comma/newline separated scope text as a convenience fallback.
                scope = [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]
        else:
            scope = raw_scope

        scope_items: List[Any] = []
        if isinstance(scope, list):
            scope_items = scope
        elif isinstance(scope, dict):
            for key in ("cmts", "cmts_list", "targets", "items"):
                val = scope.get(key)
                if isinstance(val, list):
                    scope_items = val
                    break
            if not scope_items and scope.get("ip"):
                scope_items = [scope]

        out: List[Dict[str, str]] = []
        seen: set[str] = set()

        def _push(name: str, ip: str) -> None:
            ipn = _norm(ip)
            if not ipn or ipn in seen:
                return
            seen.add(ipn)
            out.append({"name": _norm(name) or ipn, "ip": ipn})

        excluded_scope_vcas_count = 0
        for item in scope_items:
            if isinstance(item, str):
                token = _norm(item)
                if not token:
                    continue
                if _is_vcas_hostname(token):
                    excluded_scope_vcas_count += 1
                    continue
                if _is_ip_literal(token):
                    _push(token, token)
                else:
                    resolved = by_name.get(token.lower())
                    if resolved:
                        _push(token, resolved)
                    else:
                        # Keep hostname as target_ip if no appdb mapping; downstream may resolve DNS.
                        _push(token, token)
            elif isinstance(item, dict):
                ip = _norm(item.get("ip") or item.get("cmts_ip") or item.get("IPAddress"))
                name = _norm(item.get("name") or item.get("HostName") or item.get("hostname"))
                if _is_vcas_hostname(name):
                    excluded_scope_vcas_count += 1
                    continue
                if not ip and name:
                    ip = by_name.get(name.lower()) or ""
                if ip:
                    _push(name or ip, ip)

        if excluded_scope_vcas_count:
            logger.info(
                "Filtered %s VCAS non-CMTS devices from explicit poller scope",
                excluded_scope_vcas_count,
            )

        if out:
            return out

        # Final fallback: use all appdb targets if scope parse failed/empty.
        return all_from_appdb

    def _fetch_cmts_modems(
        self,
        cmts_ip: str,
        timeout_sec: int = 300,
        *,
        collection_mode: str = "full",
        wait_for_enrichment: bool = False,
    ) -> Dict[str, Any]:
        """Fetch a fresh base CMTS inventory and its completeness metadata."""
        base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        requested_limit = self._cm_modem_limit_default()
        payload = {
            "cmts_ip": cmts_ip,
            "agent_priority": "bulk",
            "limit": requested_limit,
            "enrich": collection_mode == "full" and wait_for_enrichment,
            "wait_for_enrichment": wait_for_enrichment,
            "collection_mode": collection_mode,
            "refresh": True,
            "collect_cpe": False,
        }
        request_timeout = max(330, int(timeout_sec or 300) + 30)
        r = requests.post(
            f"{base}/cmts/modems/query",
            json=payload,
            timeout=request_timeout,
            verify=False,
        )
        r.raise_for_status()
        response_payload = r.json() if r.content else {}
        if isinstance(response_payload, dict) and response_payload.get("success"):
            modems = response_payload.get("modems") or []
            if not isinstance(modems, list):
                modems = []
            return {
                "modems": modems,
                "complete": response_payload.get("complete") is True,
                "truncated": response_payload.get("truncated") is True,
                "requested_limit": int(response_payload.get("requested_limit") or requested_limit),
                "collected_at": response_payload.get("collected_at") or self._now(),
                "source": response_payload.get("source") or "snmp-live",
                "capability_enriched": response_payload.get("capability_enriched") is True,
                "critical_oid_errors": response_payload.get("critical_oid_errors") or {},
                "raw_legacy_mac_count": response_payload.get("raw_legacy_mac_count"),
                "raw_d3_mac_count": response_payload.get("raw_d3_mac_count"),
                "collection_mode": response_payload.get("collection_mode") or collection_mode,
                "authoritative": response_payload.get(
                    "authoritative", response_payload.get("complete") is True
                ) is True,
                "enriched": response_payload.get("enriched") is True,
            }
        raise RuntimeError(f"CMTS fetch failed for {cmts_ip}: {response_payload}")

    def _fetch_cmts_cpe(
        self,
        cmts_ip: str,
        *,
        overall_timeout_sec: int = 270,
        agent_command_timeout_sec: int = 300,
        min_remaining_tree_reserve_sec: float = 0,
        http_timeout_sec: int = 330,
    ) -> Dict[str, Any]:
        """Fetch one fresh CPE-only generation from a CMTS."""
        base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        payload = {
            "cmts_ip": cmts_ip,
            "agent_priority": "bulk",
            "overall_timeout_sec": int(overall_timeout_sec),
            "agent_command_timeout_sec": int(agent_command_timeout_sec),
            "min_remaining_tree_reserve_sec": float(
                min_remaining_tree_reserve_sec
            ),
        }
        request_timeout = max(
            int(agent_command_timeout_sec) + 30,
            int(http_timeout_sec),
        )
        response = requests.post(
            f"{base}/cmts/cpe/query",
            json=payload,
            timeout=request_timeout,
            verify=False,
        )
        response.raise_for_status()
        result = response.json() if response.content else {}
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError(f"CPE fetch failed for {cmts_ip}: {result}")
        rows = result.get("cpe_addresses") or []
        if not isinstance(rows, list):
            rows = []
        return {
            "cpe_addresses": rows,
            "skipped_cpe_rows": int(result.get("skipped_cpe_rows") or 0),
            "complete": result.get("complete") is True,
            "completion_source": result.get("completion_source"),
            "truncated": result.get("truncated") is True,
            "requested_limit": result.get("requested_limit"),
            "collected_at": result.get("collected_at") or self._now(),
            "oid_errors": result.get("oid_errors") or {},
            "validation_error": result.get("validation_error"),
            "raw_d3_mac_count": result.get("raw_d3_mac_count"),
            "raw_cpe_type_count": result.get("raw_cpe_type_count"),
            "raw_cpe_address_count": result.get("raw_cpe_address_count"),
            "raw_cpe_prefix_count": result.get("raw_cpe_prefix_count"),
        }

    def _upsert_inventory_rows(
        self,
        rows: List[Dict[str, Any]],
        source_poller: Optional[str],
        snapshot_id: Optional[str] = None,
        connection=None,
    ) -> int:
        if not rows:
            return 0
        now = self._now()
        inserted = 0

        def _to_int(value):
            if value is None or value == "":
                return None
            try:
                return int(str(value))
            except Exception:
                return None

        def _to_bool(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            normalized = str(value).strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
            return None

        all_values = []
        for r in rows:
            mac = self._normalize_mac(r.get("mac_address") or r.get("mac") or "")
            if len(mac) != 17:
                continue
            all_values.append((
                mac,
                r.get("ip_address") or r.get("ip"),
                r.get("cmts") or "unknown",
                r.get("cmts_ip"),
                r.get("cmts_index"),
                r.get("docsif3_index"),
                r.get("fiber_node"),
                r.get("cable_mac"),
                r.get("mac_domain"),
                r.get("status"),
                r.get("docsis_version"),
                r.get("vendor"),
                r.get("model"),
                r.get("upstream_interface"),
                _to_int(r.get("upstream_ifindex") or r.get("md_if_index")),
                _to_int(r.get("ofdm_ifindex")),
                _to_int(r.get("ofdma_ifindex")),
                _to_int(r.get("ofdm_channel_count")),
                _to_int(r.get("ofdma_channel_count")),
                _to_int(r.get("ofdma_rf_port_ifindex") or r.get("rf_port_ifindex")),
                _to_bool(r.get("ofdm_enabled")),
                _to_bool(r.get("ofdma_enabled")),
                _to_bool(r.get("partial_service")),
                _to_bool(r.get("partial_service_downstream")),
                _to_bool(r.get("partial_service_upstream")),
                r.get("partial_service_state"),
                r.get("software_version") or r.get("firmware") or None,
                now,
                now,
                now,
                source_poller,
                snapshot_id,
            ))

        sql = """
            INSERT INTO modem_inventory_current
                (mac, ip, cmts, cmts_ip, cmts_index, docsif3_index,
                 fiber_node, cable_mac, mac_domain, status, docsis_version, vendor, model,
                 upstream_interface, upstream_ifindex, ofdm_ifindex, ofdma_ifindex,
                 ofdm_channel_count, ofdma_channel_count, ofdma_rf_port_ifindex,
                 ofdm_enabled, ofdma_enabled, partial_service,
                 partial_service_downstream, partial_service_upstream, partial_service_state,
                 software_version, first_seen_at, last_seen_at, updated_at,
                 source_poller, snapshot_id,
                inventory_state, missing_since, consecutive_full_misses, retired_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'active',NULL,0,NULL)
            ON DUPLICATE KEY UPDATE
              ip=COALESCE(VALUES(ip), ip),
              cmts=COALESCE(NULLIF(VALUES(cmts), ''), cmts),
              cmts_ip=COALESCE(VALUES(cmts_ip), cmts_ip),
              cmts_index=COALESCE(NULLIF(VALUES(cmts_index), ''), cmts_index),
              docsif3_index=COALESCE(NULLIF(VALUES(docsif3_index), ''), docsif3_index),
              fiber_node=COALESCE(NULLIF(VALUES(fiber_node), ''), fiber_node),
              cable_mac=COALESCE(NULLIF(VALUES(cable_mac), ''), cable_mac),
              mac_domain=COALESCE(NULLIF(VALUES(mac_domain), ''), mac_domain),
              status=COALESCE(NULLIF(VALUES(status), ''), status),
              docsis_version=CASE
                WHEN docsis_version LIKE '%%4.0%%' THEN docsis_version
                WHEN VALUES(docsis_version) LIKE '%%4.0%%' THEN VALUES(docsis_version)
                WHEN docsis_version LIKE '%%3.1%%' THEN docsis_version
                WHEN VALUES(docsis_version) LIKE '%%3.1%%' THEN VALUES(docsis_version)
                ELSE COALESCE(NULLIF(VALUES(docsis_version), ''), docsis_version)
              END,
              vendor=COALESCE(NULLIF(VALUES(vendor), ''), vendor),
              model=COALESCE(NULLIF(VALUES(model), ''), model),
              upstream_interface=COALESCE(NULLIF(VALUES(upstream_interface), ''), upstream_interface),
              upstream_ifindex=COALESCE(NULLIF(VALUES(upstream_ifindex), 0), upstream_ifindex),
              ofdm_ifindex=COALESCE(NULLIF(VALUES(ofdm_ifindex), 0), ofdm_ifindex),
              ofdma_ifindex=COALESCE(NULLIF(VALUES(ofdma_ifindex), 0), ofdma_ifindex),
              ofdm_channel_count=CASE
                WHEN VALUES(ofdm_channel_count) > COALESCE(ofdm_channel_count, 0)
                THEN VALUES(ofdm_channel_count) ELSE ofdm_channel_count END,
              ofdma_channel_count=CASE
                WHEN VALUES(ofdma_channel_count) > COALESCE(ofdma_channel_count, 0)
                THEN VALUES(ofdma_channel_count) ELSE ofdma_channel_count END,
              ofdma_rf_port_ifindex=COALESCE(NULLIF(VALUES(ofdma_rf_port_ifindex), 0), ofdma_rf_port_ifindex),
              ofdm_enabled=CASE
                WHEN ofdm_enabled=TRUE OR VALUES(ofdm_enabled)=TRUE THEN TRUE
                ELSE COALESCE(VALUES(ofdm_enabled), ofdm_enabled) END,
              ofdma_enabled=CASE
                WHEN ofdma_enabled=TRUE OR VALUES(ofdma_enabled)=TRUE THEN TRUE
                ELSE COALESCE(VALUES(ofdma_enabled), ofdma_enabled) END,
              partial_service=COALESCE(VALUES(partial_service), partial_service),
              partial_service_downstream=COALESCE(VALUES(partial_service_downstream), partial_service_downstream),
              partial_service_upstream=COALESCE(VALUES(partial_service_upstream), partial_service_upstream),
              partial_service_state=COALESCE(VALUES(partial_service_state), partial_service_state),
              software_version=COALESCE(NULLIF(VALUES(software_version), ''), software_version),
              last_seen_at=VALUES(last_seen_at),
              updated_at=VALUES(updated_at), source_poller=VALUES(source_poller),
              snapshot_id=COALESCE(VALUES(snapshot_id), snapshot_id),
              inventory_state='active', missing_since=NULL,
              consecutive_full_misses=0, retired_at=NULL
        """

        batch_size = 500
        for i in range(0, len(all_values), batch_size):
            batch = all_values[i:i + batch_size]
            if connection is not None:
                cur = connection.cursor()
                cur.executemany(sql, batch)
            else:
                with self._db_lock:
                    conn = self._connect()
                    cur = conn.cursor()
                    cur.executemany(sql, batch)
                    conn.close()
            inserted += len(batch)

        return inserted

    @staticmethod
    def _identity_value_sql(column: str) -> str:
        normalized = f"LOWER(TRIM(COALESCE({column},'')))"
        return (
            f"{normalized} NOT IN "
            "('','unknown','n/a','(unknown)','none','null','not available','0') "
            f"AND {normalized} NOT REGEXP '^0+([.]0+)*$' "
            f"AND {normalized} NOT LIKE '%%no such%%' "
            f"AND {normalized} NOT LIKE '%%timeout%%' "
            f"AND {normalized} NOT LIKE '%%unknown object%%'"
        )

    @classmethod
    def _inventory_enriched_sql(cls, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        vendor = cls._identity_value_sql(f"{prefix}vendor")
        software = cls._identity_value_sql(f"{prefix}software_version")
        return f"{vendor} AND {software}"

    @staticmethod
    def _identity_eligible_sql(alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"{prefix}inventory_state='active' "
            f"AND {prefix}cmts_ip IS NOT NULL "
            f"AND TRIM({prefix}cmts_ip)<>'' "
            f"AND {prefix}ip IS NOT NULL "
            f"AND TRIM({prefix}ip) NOT IN ('','0.0.0.0','::') "
            f"AND INET6_ATON(TRIM({prefix}ip)) IS NOT NULL "
            f"AND LOWER(TRIM(COALESCE({prefix}status,''))) IN "
            "('operational','registrationcomplete','ipcomplete','online')"
        )

    @staticmethod
    def _inventory_area_aggregate_sql(alias: str = "") -> str:
        """Classify one CMTS from recognized modem management IPv4 addresses."""
        prefix = f"{alias}." if alias else ""
        management_ip = f"TRIM({prefix}ip)"
        address = f"INET_ATON({management_ip})"
        dotted_ipv4 = (
            f"LENGTH({management_ip})-"
            f"LENGTH(REPLACE({management_ip},'.',''))=3"
        )
        fziggo = (
            f"({dotted_ipv4} AND "
            f"{address} BETWEEN 2147483648 AND 2149580799)"
        )
        fupc = (
            f"({dotted_ipv4} AND ("
            f"{address} BETWEEN 2684354560 AND 2686451711 OR "
            f"{address} BETWEEN 180355072 AND 182452223))"
        )
        fziggo_count = f"SUM(CASE WHEN {fziggo} THEN 1 ELSE 0 END)"
        fupc_count = f"SUM(CASE WHEN {fupc} THEN 1 ELSE 0 END)"
        return (
            f"CASE WHEN {fziggo_count}>0 AND {fupc_count}=0 THEN 'fziggo' "
            f"WHEN {fupc_count}>0 AND {fziggo_count}=0 THEN 'fupc' "
            "ELSE 'unknown' END"
        )

    @staticmethod
    def _normalize_inventory_area(area: Optional[str]) -> str:
        normalized = "all" if area is None else str(area).strip().lower()
        if normalized not in {"all", "vfz", "fziggo", "fupc"}:
            raise ValueError("area must be one of: all, vfz, fziggo, fupc")
        return normalized

    @staticmethod
    def _area_sql_predicate(column: str, area: str) -> tuple[str, List[str]]:
        if area == "all":
            return "", []
        if area == "vfz":
            return f"{column} IN (%s,%s)", ["fziggo", "fupc"]
        return f"{column}=%s", [area]

    def _refresh_summary_for_cmts_cursor(
        self,
        cur,
        *,
        cmts_ip: str,
        cmts: str,
        refreshed_at: str,
    ) -> str:
        cur.execute(
            "DELETE FROM inventory_summary_count WHERE cmts_ip=%s",
            (cmts_ip,),
        )
        dimensions = (
            ("vendor", "vendor"),
            ("model", "model"),
            ("software_version", "software_version"),
            ("docsis_version", "docsis_version"),
        )
        for dimension, column in dimensions:
            if dimension in {"vendor", "model", "software_version"}:
                value_sql = (
                    f"CASE WHEN {self._identity_value_sql(column)} "
                    f"THEN TRIM({column}) ELSE '(unknown)' END"
                )
            else:
                value_sql = f"COALESCE(NULLIF(TRIM({column}),''), '(unknown)')"
            cur.execute(
                "INSERT INTO inventory_summary_count "
                "(cmts_ip, dimension, value, row_count) "
                f"SELECT %s, %s, {value_sql}, COUNT(*) "
                "FROM modem_inventory_current "
                "WHERE cmts_ip=%s AND inventory_state='active' GROUP BY 3",
                (cmts_ip, dimension, cmts_ip),
            )
        cur.execute(
            "SELECT COUNT(*) AS total, MAX(updated_at) AS last_updated, "
            f"SUM(CASE WHEN {self._inventory_enriched_sql()} THEN 1 ELSE 0 END) "
            "AS enriched, "
            f"{self._inventory_area_aggregate_sql()} AS area "
            "FROM modem_inventory_current "
            "WHERE cmts_ip=%s AND inventory_state='active'",
            (cmts_ip,),
        )
        status = cur.fetchone() or {}
        area = str(status.get("area") or "unknown")
        cur.execute(
            "INSERT INTO inventory_summary_status "
            "(cmts_ip, cmts, area, active_total, enriched_count, last_updated, "
            "refreshed_at) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE cmts=VALUES(cmts), area=VALUES(area), "
            "active_total=VALUES(active_total), enriched_count=VALUES(enriched_count), "
            "last_updated=VALUES(last_updated), refreshed_at=VALUES(refreshed_at)",
            (
                cmts_ip,
                cmts or cmts_ip,
                area,
                int(status.get("total") or 0),
                int(status.get("enriched") or 0),
                status.get("last_updated"),
                refreshed_at,
            ),
        )
        return area

    @staticmethod
    def _replace_daily_inventory_summary_cursor(
        cur,
        *,
        snapshot_date: str,
        cmts_ip: str,
        cmts: str,
        area: str,
        collected_at: str,
        refreshed_at: str,
    ) -> None:
        cur.execute(
            "DELETE FROM inventory_summary_daily "
            "WHERE snapshot_date=%s AND cmts_ip=%s",
            (snapshot_date, cmts_ip),
        )
        cur.execute(
            "INSERT INTO inventory_summary_daily "
            "(snapshot_date, cmts_ip, cmts, area, dimension, value, row_count, "
            "collected_at, refreshed_at) "
            "SELECT %s, c.cmts_ip, %s, %s, c.dimension, c.value, c.row_count, "
            "%s, %s FROM inventory_summary_count c WHERE c.cmts_ip=%s",
            (
                snapshot_date,
                cmts or cmts_ip,
                area,
                collected_at,
                refreshed_at,
                cmts_ip,
            ),
        )

    def _lock_inventory_snapshot_cursor(
        self,
        cur,
        *,
        cmts_ip: str,
        cmts: str,
        locked_at: str,
    ) -> Dict[str, Any]:
        """Ensure and lock one CMTS snapshot row within the caller transaction."""
        cur.execute(
            "INSERT INTO cmts_inventory_snapshot "
            "(cmts_ip, cmts, snapshot_id, complete, requested_limit, row_count, "
            "collected_at, source, authoritative, quarantined, quarantine_reason, "
            "revision_at) VALUES (%s,%s,%s,FALSE,%s,0,%s,%s,FALSE,TRUE,%s,%s) "
            "ON DUPLICATE KEY UPDATE cmts_ip=VALUES(cmts_ip)",
            (
                cmts_ip,
                cmts or cmts_ip,
                str(uuid.uuid4()),
                self._cm_modem_limit_default(),
                locked_at,
                "lock-bootstrap",
                "snapshot row created for transaction lock bootstrap",
                locked_at,
            ),
        )
        cur.execute(
            "SELECT quarantined, quarantine_candidate_count, "
            "quarantine_candidate_fingerprint, collection_mode "
            "FROM cmts_inventory_snapshot WHERE cmts_ip=%s FOR UPDATE",
            (cmts_ip,),
        )
        return cur.fetchone() or {}

    @staticmethod
    def _coerce_collected_at(value: Any, fallback: str) -> str:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return fallback

    def persist_scheduled_inventory_generation(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts_hostname: str,
        cmts_ip: str,
        metadata: Dict[str, Any],
        source_poller: Optional[str],
        task_type: str,
        job_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Atomically merge one CMTS generation, lifecycle, snapshot, and summary."""
        cmts_name = str(cmts_hostname or "").strip()
        cmts_address = str(cmts_ip or "").strip()
        if not cmts_name or not cmts_address:
            raise ValueError("cmts_hostname and cmts_ip are required")

        snapshot_id = str(uuid.uuid4())
        stamped_rows: List[Dict[str, Any]] = []
        observed_macs: List[str] = []
        incomplete_new_candidates: set[str] = set()
        for source in rows or []:
            if not isinstance(source, dict):
                continue
            mac = self._normalize_mac(source.get("mac_address") or source.get("mac") or "")
            if not mac:
                continue
            row = dict(source)
            row["mac_address"] = mac
            row["cmts"] = cmts_name
            row["cmts_ip"] = cmts_address
            stamped_rows.append(row)
            observed_macs.append(mac)
            if not row.get("cable_mac") or not row.get("fiber_node"):
                incomplete_new_candidates.add(mac)

        observed_macs = list(dict.fromkeys(observed_macs))
        row_count = len(observed_macs)
        population_fingerprint = (
            hashlib.sha256(
                "\n".join(sorted(observed_macs)).encode("ascii")
            ).hexdigest()
            if observed_macs
            else None
        )
        complete_input = metadata.get("complete") is True
        truncated = metadata.get("truncated") is True
        if task_type == _INVENTORY_RECONCILE_TASK_TYPE:
            collection_mode = "light"
        elif task_type == _INVENTORY_FULL_TASK_TYPE:
            collection_mode = "full"
        else:
            collection_mode = str(metadata.get("collection_mode") or "full")
        now = self._now()
        collected_at = self._coerce_collected_at(metadata.get("collected_at"), now)
        lifecycle_task = task_type in {
            _INVENTORY_RECONCILE_TASK_TYPE,
            _INVENTORY_FULL_TASK_TYPE,
        }

        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                if job_id is not None:
                    cur.execute(
                        "SELECT status FROM poller_job WHERE id=%s FOR UPDATE",
                        (int(job_id),),
                    )
                    job = cur.fetchone()
                    if not job or str(job.get("status") or "").lower() != "running":
                        raise _PollerJobNotRunning(
                            f"Poller job {job_id} is no longer running"
                        )

                self._lock_inventory_snapshot_cursor(
                    cur,
                    cmts_ip=cmts_address,
                    cmts=cmts_name,
                    locked_at=now,
                )
                cur.execute(
                    "SELECT COUNT(*) AS c FROM modem_inventory_current "
                    "WHERE cmts_ip=%s AND inventory_state<>'retired'",
                    (cmts_address,),
                )
                previous_count = int((cur.fetchone() or {}).get("c") or 0)
                cur.execute(
                    "SELECT candidate_count, candidate_fingerprint, candidate_macs, "
                    "TIMESTAMPDIFF(SECOND, observed_at, %s) AS candidate_age_seconds "
                    "FROM inventory_shrink_candidate "
                    "WHERE cmts_ip=%s AND collection_mode=%s FOR UPDATE",
                    (now, cmts_address, collection_mode),
                )
                shrink_candidate = cur.fetchone() or {}

                existing_macs: set[str] = set()
                for offset in range(0, len(observed_macs), 500):
                    batch = observed_macs[offset:offset + 500]
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"SELECT mac FROM modem_inventory_current WHERE mac IN ({placeholders})",
                        tuple(batch),
                    )
                    existing_macs.update(str(row.get("mac")) for row in cur.fetchall())

                producer_authoritative = metadata.get("authoritative")
                full_enrichment_complete = bool(
                    metadata.get("enriched") is True
                    and metadata.get("capability_enriched") is True
                )
                authoritative = bool(
                    complete_input
                    and not truncated
                    and row_count > 0
                    and producer_authoritative is not False
                    and (
                        task_type != _INVENTORY_FULL_TASK_TYPE
                        or full_enrichment_complete
                    )
                )
                quarantined = False
                quarantine_reason = None
                quarantine_candidate_count = None
                quarantine_candidate_fingerprint = None
                if not complete_input:
                    authoritative = False
                    quarantined = True
                    quarantine_reason = "incomplete generation"
                elif truncated:
                    authoritative = False
                    quarantined = True
                    quarantine_reason = "truncated generation"
                elif row_count == 0:
                    authoritative = False
                    quarantined = True
                    quarantine_reason = "zero-row complete generation"
                    quarantine_candidate_count = 0
                elif producer_authoritative is False:
                    authoritative = False
                    quarantined = True
                    quarantine_reason = "source marked generation non-authoritative"
                elif (
                    task_type == _INVENTORY_FULL_TASK_TYPE
                    and not full_enrichment_complete
                ):
                    authoritative = False
                    quarantined = True
                    missing_parts = []
                    if metadata.get("capability_enriched") is not True:
                        missing_parts.append("capability tables")
                    if metadata.get("enriched") is not True:
                        missing_parts.append("CMTS interface enrichment")
                    quarantine_reason = (
                        "daily full enrichment incomplete: "
                        + ", ".join(missing_parts)
                    )
                elif lifecycle_task and previous_count > 0:
                    shrink = previous_count - row_count
                    shrink_limit = max(100.0, previous_count * 0.10)
                    if shrink > shrink_limit:
                        prior_candidate_count = int(
                            shrink_candidate.get("candidate_count")
                            if shrink_candidate.get("candidate_count") is not None
                            else -1
                        )
                        candidate_tolerance = max(
                            25,
                            (max(prior_candidate_count, 0) + 99) // 100,
                        )
                        try:
                            prior_candidate_macs = set(
                                json.loads(shrink_candidate.get("candidate_macs") or "[]")
                            )
                        except (TypeError, ValueError, json.JSONDecodeError):
                            prior_candidate_macs = set()
                        current_candidate_macs = set(observed_macs)
                        overlap_denominator = max(
                            len(prior_candidate_macs),
                            len(current_candidate_macs),
                            1,
                        )
                        overlap_ratio = (
                            len(prior_candidate_macs & current_candidate_macs)
                            / overlap_denominator
                        )
                        candidate_age_seconds = int(
                            shrink_candidate.get("candidate_age_seconds")
                            if shrink_candidate.get("candidate_age_seconds") is not None
                            else -1
                        )
                        candidate_max_age_seconds = (
                            6 * 60 * 60
                            if collection_mode == "light"
                            else 48 * 60 * 60
                        )
                        candidate_matches = bool(
                            prior_candidate_count >= 0
                            and abs(row_count - prior_candidate_count)
                            <= candidate_tolerance
                            and 0 <= candidate_age_seconds <= candidate_max_age_seconds
                            and overlap_ratio >= 0.98
                        )
                        quarantine_candidate_count = row_count
                        quarantine_candidate_fingerprint = population_fingerprint
                        if not candidate_matches:
                            authoritative = False
                            quarantined = True
                            quarantine_reason = (
                                f"anomalous shrink from {previous_count} to "
                                f"{row_count} rows"
                            )
                            cur.execute(
                                "INSERT INTO inventory_shrink_candidate "
                                "(cmts_ip, collection_mode, candidate_count, "
                                "candidate_fingerprint, candidate_macs, observed_at) "
                                "VALUES (%s,%s,%s,%s,%s,%s) "
                                "ON DUPLICATE KEY UPDATE "
                                "candidate_count=VALUES(candidate_count), "
                                "candidate_fingerprint=VALUES(candidate_fingerprint), "
                                "candidate_macs=VALUES(candidate_macs), "
                                "observed_at=VALUES(observed_at)",
                                (
                                    cmts_address,
                                    collection_mode,
                                    row_count,
                                    population_fingerprint,
                                    json.dumps(sorted(current_candidate_macs)),
                                    now,
                                ),
                            )

                if authoritative:
                    cur.execute(
                        "DELETE FROM inventory_shrink_candidate "
                        "WHERE cmts_ip=%s AND collection_mode=%s",
                        (cmts_address, collection_mode),
                    )

                written = 0
                if authoritative:
                    written = self._upsert_inventory_rows(
                        stamped_rows,
                        source_poller=source_poller,
                        snapshot_id=snapshot_id,
                        connection=conn,
                    )

                if authoritative and task_type == _INVENTORY_RECONCILE_TASK_TYPE:
                    cur.execute(
                        "UPDATE modem_inventory_current SET "
                        "inventory_state='suspect_missing', "
                        "missing_since=COALESCE(missing_since,%s), updated_at=%s "
                        "WHERE cmts_ip=%s AND inventory_state='active' "
                        "AND (snapshot_id IS NULL OR snapshot_id<>%s)",
                        (now, now, cmts_address, snapshot_id),
                    )
                elif authoritative and task_type == _INVENTORY_FULL_TASK_TYPE:
                    cur.execute(
                        "UPDATE modem_inventory_current SET "
                        "inventory_state=CASE WHEN consecutive_full_misses+1>=2 "
                        "THEN 'retired' ELSE 'suspect_missing' END, "
                        "retired_at=CASE WHEN consecutive_full_misses+1>=2 "
                        "THEN COALESCE(retired_at,%s) ELSE retired_at END, "
                        "missing_since=COALESCE(missing_since,%s), "
                        "consecutive_full_misses=consecutive_full_misses+1, "
                        "updated_at=%s WHERE cmts_ip=%s "
                        "AND inventory_state<>'retired' "
                        "AND (snapshot_id IS NULL OR snapshot_id<>%s)",
                        (now, now, now, cmts_address, snapshot_id),
                    )

                if (
                    authoritative
                    and task_type == _INVENTORY_RECONCILE_TASK_TYPE
                    and written
                ):
                    try:
                        auto_limit = max(
                            1,
                            min(
                                int(os.environ.get("DATA_STORE_NEW_MODEM_ENRICH_LIMIT", "100")),
                                1000,
                            ),
                        )
                    except (TypeError, ValueError):
                        auto_limit = 100
                    new_candidates = [
                        mac for mac in observed_macs
                        if mac not in existing_macs and mac in incomplete_new_candidates
                    ][:auto_limit]
                    if new_candidates:
                        cur.executemany(
                            "INSERT IGNORE INTO modem_refresh_request "
                            "(mac, cmts, status, requested_by, created_at) "
                            "VALUES (%s,%s,'queued','inventory-light',%s)",
                            [(mac, cmts_name, now) for mac in new_candidates],
                        )

                derived_area = None
                if authoritative:
                    derived_area = self._refresh_summary_for_cmts_cursor(
                        cur,
                        cmts_ip=cmts_address,
                        cmts=cmts_name,
                        refreshed_at=now,
                    )
                    self._replace_daily_inventory_summary_cursor(
                        cur,
                        snapshot_date=collected_at[:10],
                        cmts_ip=cmts_address,
                        cmts=cmts_name,
                        area=derived_area,
                        collected_at=collected_at,
                        refreshed_at=now,
                    )
                    cur.execute(
                        "UPDATE cmts_inventory_snapshot SET area=%s "
                        "WHERE cmts_ip=%s",
                        (derived_area, cmts_address),
                    )
                cur.execute(
                    """
                    INSERT INTO cmts_inventory_snapshot
                        (cmts_ip, cmts, snapshot_id, complete, truncated,
                         capability_enriched, requested_limit, row_count,
                         collected_at, source, source_poller, critical_oid_errors,
                         raw_legacy_mac_count, raw_d3_mac_count, authoritative,
                         quarantined, quarantine_reason, quarantine_candidate_count,
                         quarantine_candidate_fingerprint, collection_mode, revision_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        cmts=VALUES(cmts), snapshot_id=VALUES(snapshot_id),
                        complete=VALUES(complete), truncated=VALUES(truncated),
                        capability_enriched=VALUES(capability_enriched),
                        requested_limit=VALUES(requested_limit), row_count=VALUES(row_count),
                        collected_at=VALUES(collected_at), source=VALUES(source),
                        source_poller=VALUES(source_poller),
                        critical_oid_errors=VALUES(critical_oid_errors),
                        raw_legacy_mac_count=VALUES(raw_legacy_mac_count),
                        raw_d3_mac_count=VALUES(raw_d3_mac_count),
                        authoritative=VALUES(authoritative),
                        quarantined=VALUES(quarantined),
                        quarantine_reason=VALUES(quarantine_reason),
                        quarantine_candidate_count=VALUES(quarantine_candidate_count),
                        quarantine_candidate_fingerprint=VALUES(
                            quarantine_candidate_fingerprint
                        ),
                        collection_mode=VALUES(collection_mode),
                        revision_at=GREATEST(
                            VALUES(revision_at),
                            DATE_ADD(COALESCE(revision_at, collected_at,
                            '1970-01-01 00:00:00'), INTERVAL 1 SECOND))
                    """,
                    (
                        cmts_address,
                        cmts_name,
                        snapshot_id,
                        1 if complete_input and not truncated else 0,
                        1 if truncated else 0,
                        1 if collection_mode == "full" and metadata.get("capability_enriched") is True else 0,
                        int(metadata.get("requested_limit") or self._cm_modem_limit_default()),
                        row_count,
                        collected_at,
                        metadata.get("source") or "snmp-live",
                        source_poller,
                        json.dumps(metadata.get("critical_oid_errors") or {}),
                        metadata.get("raw_legacy_mac_count"),
                        metadata.get("raw_d3_mac_count"),
                        1 if authoritative else 0,
                        1 if quarantined else 0,
                        quarantine_reason,
                        quarantine_candidate_count,
                        quarantine_candidate_fingerprint,
                        collection_mode,
                        now,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return {
            "snapshot_id": snapshot_id,
            "row_count": written,
            "observed_row_count": row_count,
            "authoritative": authoritative,
            "complete": bool(complete_input and not truncated),
            "quarantined": quarantined,
            "quarantine_reason": quarantine_reason,
            "quarantine_candidate_count": quarantine_candidate_count,
            "collection_mode": collection_mode,
            "area": derived_area,
        }

    def persist_enrichment_rows(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts: str,
        cmts_ip: str,
        source_poller: str,
    ) -> int:
        """Persist enrichment, refresh its summary, and advance revision atomically."""
        values = []
        now = self._now()
        for source in rows or []:
            if not isinstance(source, dict):
                continue
            mac = self._normalize_mac(
                source.get("mac_address") or source.get("mac") or ""
            )
            if len(mac) != 17:
                continue
            docsis_version = source.get("docsis_version")
            values.append(
                (
                    source.get("fiber_node"),
                    source.get("cable_mac"),
                    docsis_version,
                    docsis_version,
                    docsis_version,
                    docsis_version,
                    docsis_version,
                    now,
                    source_poller,
                    mac,
                    cmts_ip,
                )
            )
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                self._lock_inventory_snapshot_cursor(
                    cur,
                    cmts_ip=cmts_ip,
                    cmts=cmts,
                    locked_at=now,
                )
                written = 0
                if values:
                    cur.executemany(
                        "UPDATE modem_inventory_current SET "
                        "fiber_node=COALESCE(NULLIF(%s,''),fiber_node), "
                        "cable_mac=COALESCE(NULLIF(%s,''),cable_mac), "
                        "docsis_version=CASE "
                        "WHEN docsis_version LIKE '%%4.0%%' THEN docsis_version "
                        "WHEN %s LIKE '%%4.0%%' THEN %s "
                        "WHEN docsis_version LIKE '%%3.1%%' THEN docsis_version "
                        "WHEN %s LIKE '%%3.1%%' THEN %s "
                        "ELSE COALESCE(NULLIF(%s,''),docsis_version) END, "
                        "updated_at=%s, source_poller=%s "
                        "WHERE mac=%s AND cmts_ip=%s "
                        "AND inventory_state='active'",
                        values,
                    )
                    written = int(cur.rowcount or 0)
                self._refresh_summary_for_cmts_cursor(
                    cur,
                    cmts_ip=cmts_ip,
                    cmts=cmts,
                    refreshed_at=now,
                )
                cur.execute(
                    "UPDATE cmts_inventory_snapshot SET revision_at="
                    "GREATEST(UTC_TIMESTAMP(), DATE_ADD(COALESCE(revision_at, "
                    "collected_at, '1970-01-01 00:00:00'), INTERVAL 1 SECOND)) "
                    "WHERE cmts_ip=%s",
                    (cmts_ip,),
                )
                conn.commit()
                return written
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _persist_cpe_generation(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts_ip: str,
        snapshot_id: str,
        complete: bool,
        truncated: bool,
        job_id: Optional[int] = None,
    ) -> int:
        """Replace one CMTS CPE generation only after a complete walk."""
        if not complete or truncated:
            return 0
        now = self._now()
        values = []
        for position, row in enumerate(rows or []):
            if not isinstance(row, dict):
                raise ValueError(f"Invalid CPE row at position {position}")
            try:
                address = ipaddress.ip_address(str(row.get('ip_address') or ''))
                prefix_length = int(row.get('prefix_length'))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid CPE address or prefix at position {position}"
                ) from exc
            family = f'ipv{address.version}'
            if row.get('address_family') != family:
                raise ValueError(f"CPE address family mismatch at position {position}")
            maximum = 32 if address.version == 4 else 128
            if not 0 <= prefix_length <= maximum:
                raise ValueError(f"Invalid CPE prefix length at position {position}")
            docsif3_index = str(row.get('docsif3_index') or '').strip()
            cpe_id = str(row.get('cpe_id') or '').strip()
            modem_mac = self._normalize_mac(str(row.get('modem_mac') or ''))
            if not docsif3_index or not cpe_id or len(modem_mac) != 17:
                raise ValueError(f"Invalid CPE correlation at position {position}")
            values.append((
                str(cmts_ip), docsif3_index, cpe_id, modem_mac, family,
                address.compressed, prefix_length, snapshot_id, now, now, now,
            ))

        sql = """
            INSERT INTO modem_cpe_ip_current
                (cmts_ip, docsif3_index, cpe_id, modem_mac, address_family,
                 ip_address, prefix_length, snapshot_id, first_seen_at,
                 last_seen_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                modem_mac=VALUES(modem_mac), address_family=VALUES(address_family),
                ip_address=VALUES(ip_address), prefix_length=VALUES(prefix_length),
                snapshot_id=VALUES(snapshot_id), last_seen_at=VALUES(last_seen_at),
                updated_at=VALUES(updated_at)
        """
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                if job_id is not None:
                    cur.execute(
                        "SELECT status FROM poller_job WHERE id=%s FOR UPDATE",
                        (int(job_id),),
                    )
                    job = cur.fetchone()
                    if (
                        not job
                        or str(job.get("status") or "").lower() != "running"
                    ):
                        raise _PollerJobNotRunning(
                            f"Poller job {job_id} is no longer running"
                        )
                for offset in range(0, len(values), 1000):
                    cur.executemany(sql, values[offset:offset + 1000])
                cur.execute(
                    "DELETE FROM modem_cpe_ip_current "
                    "WHERE cmts_ip=%s AND (snapshot_id IS NULL OR snapshot_id<>%s)",
                    (str(cmts_ip), snapshot_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return len(values)

    def persist_inventory_generation(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts_hostname: str,
        cmts_ip: str,
        metadata: Dict[str, Any],
        source_poller: Optional[str] = "live-gui",
    ) -> Dict[str, Any]:
        """Persist one externally collected generation without triggering discovery."""
        cmts_name = str(cmts_hostname or "").strip()
        cmts_address = str(cmts_ip or "").strip()
        if not cmts_name or not cmts_address:
            raise ValueError("cmts_hostname and cmts_ip are required")

        result = self.persist_scheduled_inventory_generation(
            rows,
            cmts_hostname=cmts_name,
            cmts_ip=cmts_address,
            metadata=metadata,
            source_poller=source_poller,
            task_type="inventory",
        )
        cpe_written = self._persist_cpe_generation(
            metadata.get('cpe_addresses') or [],
            cmts_ip=cmts_address,
            snapshot_id=result["snapshot_id"],
            complete=metadata.get('cpe_complete') is True,
            truncated=metadata.get('cpe_truncated') is True,
        )
        return {
            **result,
            "cpe_row_count": cpe_written,
        }

    def _record_inventory_snapshot(
        self,
        *,
        cmts: str,
        cmts_ip: str,
        snapshot_id: str,
        metadata: Dict[str, Any],
        row_count: int,
        source_poller: Optional[str],
    ) -> None:
        collected_at = metadata.get("collected_at")
        try:
            parsed = datetime.fromisoformat(str(collected_at).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            collected_at = parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            collected_at = self._now()

        # Legacy callers publish observation metadata only. Lifecycle transitions
        # are exclusively handled by persist_scheduled_inventory_generation.

        revision_at = self._now()
        self._execute(
            """
            INSERT INTO cmts_inventory_snapshot
                (cmts_ip, cmts, snapshot_id, complete, truncated,
                 capability_enriched, requested_limit,
                 row_count, collected_at, source, source_poller, critical_oid_errors,
                 raw_legacy_mac_count, raw_d3_mac_count, revision_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                cmts=VALUES(cmts), snapshot_id=VALUES(snapshot_id),
                complete=VALUES(complete), truncated=VALUES(truncated),
                capability_enriched=VALUES(capability_enriched),
                requested_limit=VALUES(requested_limit), row_count=VALUES(row_count),
                collected_at=VALUES(collected_at), source=VALUES(source),
                source_poller=VALUES(source_poller),
                critical_oid_errors=VALUES(critical_oid_errors),
                raw_legacy_mac_count=VALUES(raw_legacy_mac_count),
                raw_d3_mac_count=VALUES(raw_d3_mac_count),
                revision_at=GREATEST(
                    VALUES(revision_at),
                    DATE_ADD(
                        COALESCE(revision_at, collected_at, '1970-01-01 00:00:00'),
                        INTERVAL 1 SECOND
                    )
                )
            """,
            (
                cmts_ip,
                cmts,
                snapshot_id,
                1 if metadata.get("complete") is True else 0,
                1 if metadata.get("truncated") is True else 0,
                1 if metadata.get("capability_enriched") is True else 0,
                int(metadata.get("requested_limit") or self._cm_modem_limit_default()),
                int(row_count),
                collected_at,
                metadata.get("source") or "snmp-live",
                source_poller,
                json.dumps(metadata.get("critical_oid_errors") or {}),
                metadata.get("raw_legacy_mac_count"),
                metadata.get("raw_d3_mac_count"),
                revision_at,
            ),
        )

    def get_inventory_snapshot(self, cmts: str) -> Optional[Dict[str, Any]]:
        cmts_value = str(cmts or "").strip()
        if not cmts_value:
            return None
        try:
            ipaddress.ip_address(cmts_value)
            column = "cmts_ip"
        except ValueError:
            column = "cmts"
        rows = self._query(
            f"SELECT * FROM cmts_inventory_snapshot WHERE {column}=%s "
            "ORDER BY collected_at DESC LIMIT 1",
            (cmts_value,),
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["complete"] = bool(row.get("complete"))
        row["truncated"] = bool(row.get("truncated"))
        row["capability_enriched"] = bool(row.get("capability_enriched"))
        row["authoritative"] = bool(row.get("authoritative"))
        row["quarantined"] = bool(row.get("quarantined"))
        errors = row.get("critical_oid_errors")
        if isinstance(errors, str):
            try:
                errors = json.loads(errors)
            except Exception:
                errors = {}
        row["critical_oid_errors"] = errors if isinstance(errors, dict) else {}
        for field in ("collected_at", "revision_at"):
            value = row.get(field)
            if isinstance(value, datetime):
                row[field] = value.replace(tzinfo=timezone.utc).isoformat()
            elif value is not None:
                row[field] = str(value)
        return row

    def list_inventory_snapshots(self) -> List[Dict[str, Any]]:
        """Return lightweight revision metadata for all current CMTS inventories."""
        rows = self._query(
            "SELECT cmts_ip, cmts, area, snapshot_id, complete, truncated, "
            "capability_enriched, authoritative, quarantined, quarantine_reason, "
            "quarantine_candidate_count, collection_mode, requested_limit, "
            "row_count, collected_at, revision_at "
            "FROM cmts_inventory_snapshot"
        )
        snapshots: List[Dict[str, Any]] = []
        for source in rows:
            row = dict(source)
            row["complete"] = bool(row.get("complete"))
            row["truncated"] = bool(row.get("truncated"))
            row["capability_enriched"] = bool(row.get("capability_enriched"))
            row["authoritative"] = bool(row.get("authoritative"))
            row["quarantined"] = bool(row.get("quarantined"))
            for field in ("collected_at", "revision_at"):
                value = row.get(field)
                if isinstance(value, datetime):
                    row[field] = value.replace(tzinfo=timezone.utc).isoformat()
                elif value is not None:
                    row[field] = str(value)
            snapshots.append(row)
        return snapshots

    def _touch_inventory_revision(self, cmts: str | None, cmts_ip: str | None = None) -> None:
        """Advance cache revision after a targeted inventory-row refresh."""
        where = []
        params: List[Any] = []
        if cmts:
            where.append("LOWER(cmts)=LOWER(%s)")
            params.append(str(cmts))
        if cmts_ip:
            where.append("cmts_ip=%s")
            params.append(str(cmts_ip))
        if where:
            self._execute(
                "UPDATE cmts_inventory_snapshot SET revision_at="
                "GREATEST(UTC_TIMESTAMP(), DATE_ADD(COALESCE(revision_at, collected_at, '1970-01-01 00:00:00'), INTERVAL 1 SECOND)) "
                f"WHERE {' OR '.join(where)}",
                tuple(params),
            )

    def _refresh_summary_and_revision(
        self,
        *,
        cmts: str | None,
        cmts_ip: str | None,
    ) -> None:
        address = str(cmts_ip or "").strip()
        name = str(cmts or "").strip()
        if not address and name:
            rows = self._query(
                "SELECT cmts_ip, cmts FROM modem_inventory_current "
                "WHERE inventory_state='active' AND "
                "(cmts=%s OR cmts_ip=%s) LIMIT 1",
                (name, name),
            )
            if rows:
                address = str(rows[0].get("cmts_ip") or "")
                name = str(rows[0].get("cmts") or name)
        if not address:
            return
        now = self._now()
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                self._lock_inventory_snapshot_cursor(
                    cur,
                    cmts_ip=address,
                    cmts=name or address,
                    locked_at=now,
                )
                self._refresh_summary_for_cmts_cursor(
                    cur,
                    cmts_ip=address,
                    cmts=name or address,
                    refreshed_at=now,
                )
                cur.execute(
                    "UPDATE cmts_inventory_snapshot SET revision_at="
                    "GREATEST(UTC_TIMESTAMP(), DATE_ADD(COALESCE(revision_at, "
                    "collected_at, '1970-01-01 00:00:00'), INTERVAL 1 SECOND)) "
                    "WHERE cmts_ip=%s",
                    (address,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _purge_retired_inventory(self, retention_days: int = 7) -> int:
        """Hard-delete retired rows only when explicitly enabled."""
        purge_enabled = os.environ.get(
            "DATA_STORE_RETIRED_PURGE_ENABLED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not purge_enabled:
            logger.info(
                "Retired inventory purge disabled; set "
                "DATA_STORE_RETIRED_PURGE_ENABLED=true to enable it"
            )
            return 0
        days = max(7, int(retention_days or 7))
        before = self._query(
            "SELECT COUNT(*) AS c FROM modem_inventory_current "
            "WHERE inventory_state='retired' AND retired_at < "
            "(UTC_TIMESTAMP() - INTERVAL %s DAY)",
            (days,),
        )
        count_before = int((before[0] or {}).get("c") or 0) if before else 0
        if count_before:
            self._execute(
                "DELETE FROM modem_inventory_current "
                "WHERE inventory_state='retired' AND retired_at < "
                "(UTC_TIMESTAMP() - INTERVAL %s DAY)",
                (days,),
            )
        self._execute(
            "DELETE FROM modem_cpe_ip_current WHERE NOT EXISTS "
            "(SELECT 1 FROM modem_inventory_current m "
            "WHERE m.mac=modem_cpe_ip_current.modem_mac "
            "AND m.cmts_ip=modem_cpe_ip_current.cmts_ip)"
        )
        return count_before

    def _process_cpe_job(
        self,
        job_id: int,
        poller: Dict[str, Any],
        targets: List[Dict[str, str]],
    ) -> None:
        """Run the protected CPE refresh task across its configured CMTS scope."""
        rows_collected = 0
        targets_attempted = 0
        targets_succeeded = 0
        targets_failed = 0
        breakdown_by_index: Dict[int, Dict[str, Any]] = {}
        fatal_error = None
        incomplete_targets = 0
        poller_id = int(poller.get("id") or 0)
        start_offset = max(0, int(poller.get("last_target_offset") or 0))
        subtask_retries = max(
            0, int(os.environ.get("DATA_STORE_SUBTASK_RETRIES", "1"))
        )
        subtask_retry_delay_sec = max(
            1,
            min(
                int(os.environ.get("DATA_STORE_SUBTASK_RETRY_DELAY_SEC", "5")),
                60,
            ),
        )
        agent_startup_grace_sec = max(
            0,
            min(
                int(os.environ.get("DATA_STORE_AGENT_STARTUP_GRACE_SEC", "30")),
                120,
            ),
        )
        try:
            incomplete_retry_backoff_sec = max(
                0,
                min(
                    int(
                        os.environ.get(
                            "DATA_STORE_CPE_INCOMPLETE_RETRY_BACKOFF_SEC", "15"
                        )
                    ),
                    300,
                ),
            )
        except (TypeError, ValueError):
            incomplete_retry_backoff_sec = 15
        first_pass_envelope = {
            "overall_timeout_sec": 270,
            "agent_command_timeout_sec": 300,
            "min_remaining_tree_reserve_sec": 0,
            "http_timeout_sec": 330,
        }
        retry_envelope = {
            "overall_timeout_sec": 600,
            "agent_command_timeout_sec": 630,
            "min_remaining_tree_reserve_sec": 120,
            "http_timeout_sec": 660,
        }
        try:
            max_concurrency = max(
                1, min(int(poller.get("max_concurrency") or 1), 10)
            )
        except (TypeError, ValueError):
            max_concurrency = 1
        total_targets = len(targets)
        if total_targets == 0:
            fatal_error = "No CMTS targets resolved (check scope/appdb config)"

        checkpoint_offset = min(start_offset, total_targets)
        finalized_indices = set(range(1, checkpoint_offset + 1))
        semantic_retry_targets = []
        cancelled = False

        def _job_is_running() -> bool:
            status_rows = self._query(
                "SELECT status FROM poller_job WHERE id=%s", (job_id,)
            )
            return bool(
                status_rows
                and str((status_rows[0] or {}).get("status") or "").lower()
                == "running"
            )

        def _wait_while_running(delay_sec: float) -> bool:
            deadline = time.monotonic() + max(0.0, delay_sec)
            while True:
                if not _job_is_running():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                time.sleep(min(1.0, remaining))

        def _cancelled_fetch_outcome(
            last_target_error: Optional[str],
            attempt_errors: List[tuple[int, str]],
        ) -> Dict[str, Any]:
            return {
                "cancelled": True,
                "fetch_result": None,
                "last_target_error": last_target_error,
                "attempt_errors": attempt_errors,
            }

        def _fetch_target(
            cmts_ip: str,
            envelope: Dict[str, Any],
        ) -> Dict[str, Any]:
            attempt_errors: List[tuple[int, str]] = []
            last_target_error = None
            attempt = 0
            startup_grace_deadline = time.monotonic() + agent_startup_grace_sec
            while attempt <= subtask_retries:
                if not _job_is_running():
                    return _cancelled_fetch_outcome(
                        last_target_error,
                        attempt_errors,
                    )
                try:
                    return {
                        "cancelled": False,
                        "fetch_result": self._fetch_cmts_cpe(
                            cmts_ip,
                            overall_timeout_sec=envelope["overall_timeout_sec"],
                            agent_command_timeout_sec=envelope[
                                "agent_command_timeout_sec"
                            ],
                            min_remaining_tree_reserve_sec=envelope[
                                "min_remaining_tree_reserve_sec"
                            ],
                            http_timeout_sec=envelope["http_timeout_sec"],
                        ),
                        "last_target_error": last_target_error,
                        "attempt_errors": attempt_errors,
                    }
                except Exception as exc:
                    last_target_error = str(exc)
                    response = getattr(exc, "response", None)
                    status_code = getattr(response, "status_code", None)
                    remaining_grace = startup_grace_deadline - time.monotonic()
                    if status_code == 503 and remaining_grace > 0:
                        if not _wait_while_running(
                            min(subtask_retry_delay_sec, remaining_grace)
                        ):
                            return _cancelled_fetch_outcome(
                                last_target_error,
                                attempt_errors,
                            )
                        continue

                    attempt += 1
                    attempt_errors.append((attempt, last_target_error))
                    if not _job_is_running():
                        return _cancelled_fetch_outcome(
                            last_target_error,
                            attempt_errors,
                        )
                    if attempt <= subtask_retries and not _wait_while_running(
                        subtask_retry_delay_sec
                    ):
                        return _cancelled_fetch_outcome(
                            last_target_error,
                            attempt_errors,
                        )
            return {
                "cancelled": False,
                "fetch_result": None,
                "last_target_error": last_target_error,
                "attempt_errors": attempt_errors,
            }

        def _finalize_target(
            idx: int,
            cmts_ip: str,
            cmts_name: str,
            outcome: Dict[str, Any],
            *,
            retry_attempted: bool,
        ) -> bool:
            nonlocal checkpoint_offset
            nonlocal incomplete_targets
            nonlocal rows_collected
            nonlocal targets_attempted
            nonlocal targets_failed
            nonlocal targets_succeeded

            if idx in finalized_indices:
                raise RuntimeError(f"CPE target index {idx} finalized more than once")
            if not _job_is_running():
                return False

            fetch_result = outcome.get("fetch_result")
            last_target_error = outcome.get("last_target_error")
            written = 0
            if fetch_result is None:
                complete = False
                truncated = False
                failure_reason = outcome.get("validation_error")
                if failure_reason:
                    validation_error = str(failure_reason)
                    progress_message = (
                        f"CPE {idx}/{total_targets}: {cmts_name} skipped "
                        f"({validation_error})"
                    )
                else:
                    validation_error = (
                        f"CPE fetch failed after {subtask_retries + 1} attempt(s): "
                        f"{last_target_error}"
                    )
                    progress_message = (
                        f"CPE {idx}/{total_targets}: {cmts_name} skipped "
                        f"after {subtask_retries + 1} failed attempt(s)"
                    )
                entry = {
                    "cmts": cmts_name,
                    "cmts_ip": cmts_ip,
                    "row_count": 0,
                    "cpe_row_count": 0,
                    "skipped_cpe_rows": 0,
                    "cpe_complete": False,
                    "completion_source": None,
                    "cpe_truncated": False,
                    "cpe_oid_errors": {},
                    "validation_error": validation_error,
                    "requested_limit": None,
                    "collected_at": None,
                    "raw_d3_mac_count": None,
                    "raw_cpe_type_count": None,
                    "raw_cpe_address_count": None,
                    "raw_cpe_prefix_count": None,
                    "retry_attempted": retry_attempted,
                }
            else:
                cpe_rows = fetch_result.get("cpe_addresses") or []
                complete = fetch_result.get("complete") is True
                truncated = fetch_result.get("truncated") is True
                validation_error = fetch_result.get("validation_error")
                if complete and not truncated:
                    try:
                        written = self._persist_cpe_generation(
                            cpe_rows,
                            cmts_ip=cmts_ip,
                            snapshot_id=str(uuid.uuid4()),
                            complete=True,
                            truncated=False,
                            job_id=job_id,
                        )
                    except _PollerJobNotRunning:
                        return False
                    except Exception as exc:
                        complete = False
                        validation_error = str(exc)

                entry = {
                    "cmts": cmts_name,
                    "cmts_ip": cmts_ip,
                    "row_count": written,
                    "cpe_row_count": written,
                    "skipped_cpe_rows": int(
                        fetch_result.get("skipped_cpe_rows") or 0
                    ),
                    "cpe_complete": complete,
                    "completion_source": fetch_result.get("completion_source"),
                    "cpe_truncated": truncated,
                    "cpe_oid_errors": fetch_result.get("oid_errors") or {},
                    "validation_error": validation_error,
                    "requested_limit": fetch_result.get("requested_limit"),
                    "collected_at": fetch_result.get("collected_at"),
                    "raw_d3_mac_count": fetch_result.get("raw_d3_mac_count"),
                    "raw_cpe_type_count": fetch_result.get("raw_cpe_type_count"),
                    "raw_cpe_address_count": fetch_result.get(
                        "raw_cpe_address_count"
                    ),
                    "raw_cpe_prefix_count": fetch_result.get(
                        "raw_cpe_prefix_count"
                    ),
                    "retry_attempted": retry_attempted,
                }
                progress_message = (
                    f"CPE {idx}/{total_targets}: {cmts_name} done "
                    f"({written} addresses, complete=True)"
                    if complete and not truncated
                    else f"CPE {idx}/{total_targets}: {cmts_name} skipped "
                    "(incomplete generation; previous rows preserved)"
                )

            targets_attempted += 1
            rows_collected += written
            if complete and not truncated:
                targets_succeeded += 1
            else:
                targets_failed += 1
                incomplete_targets += 1

            breakdown_by_index[idx] = entry
            finalized_indices.add(idx)
            ordered_breakdown = [
                value
                for _, value in sorted(breakdown_by_index.items())
            ]
            self._execute(
                "UPDATE poller_job SET cmts_breakdown=%s WHERE id=%s",
                (json.dumps(ordered_breakdown), job_id),
            )

            previous_checkpoint = checkpoint_offset
            while checkpoint_offset + 1 in finalized_indices:
                checkpoint_offset += 1
            if checkpoint_offset > previous_checkpoint:
                self._execute(
                    "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s "
                    "WHERE id=%s",
                    (checkpoint_offset, self._now(), poller_id),
                )

            self._update_running_job_progress(
                job_id,
                progress_message,
                rows_collected=rows_collected,
                modems_attempted=targets_attempted,
                modems_succeeded=targets_succeeded,
                modems_failed=targets_failed,
            )
            return True

        work_targets = []
        invalid_targets = []
        if not fatal_error:
            for idx, target in enumerate(targets, start=1):
                if idx <= start_offset:
                    continue
                cmts_ip = target.get("ip")
                cmts_name = target.get("name") or cmts_ip or f"target-{idx}"
                if not cmts_ip:
                    invalid_targets.append((idx, "", cmts_name))
                    continue
                work_targets.append((idx, cmts_ip, cmts_name))

        def _run_phase(
            phase_targets: List[tuple[int, str, str]],
            *,
            concurrency: int,
            envelope: Dict[str, Any],
            retry_attempted: bool,
        ) -> None:
            nonlocal cancelled
            executor = None
            pending = []
            next_target = 0
            try:
                if phase_targets:
                    executor = ThreadPoolExecutor(
                        max_workers=concurrency,
                        thread_name_prefix="poller-cpe-fetch",
                    )
                    while next_target < min(concurrency, len(phase_targets)):
                        idx, cmts_ip, cmts_name = phase_targets[next_target]
                        pending.append(
                            (
                                idx,
                                cmts_ip,
                                cmts_name,
                                executor.submit(_fetch_target, cmts_ip, envelope),
                            )
                        )
                        next_target += 1

                while pending:
                    idx, cmts_ip, cmts_name, future = pending[0]
                    if not _job_is_running():
                        cancelled = True
                        break
                    self._update_running_job_progress(
                        job_id,
                        f"CPE {idx}/{total_targets}: walking {cmts_name}",
                        rows_collected=rows_collected,
                        modems_attempted=targets_attempted,
                        modems_succeeded=targets_succeeded,
                        modems_failed=targets_failed,
                    )

                    while True:
                        done, _ = wait_for_futures((future,), timeout=1.0)
                        if done:
                            outcome = future.result()
                            break
                        if not _job_is_running():
                            cancelled = True
                            break
                    if cancelled:
                        break
                    if outcome.get("cancelled") or not _job_is_running():
                        cancelled = True
                        break

                    for attempt, error_text in outcome.get("attempt_errors") or []:
                        self._update_running_job_progress(
                            job_id,
                            f"CPE {idx}/{total_targets}: {cmts_name} attempt "
                            f"{attempt}/{subtask_retries + 1} failed ({error_text})",
                            rows_collected=rows_collected,
                            modems_attempted=targets_attempted,
                            modems_succeeded=targets_succeeded,
                            modems_failed=targets_failed,
                        )
                    if not _job_is_running():
                        cancelled = True
                        break

                    fetch_result = outcome.get("fetch_result")
                    if (
                        not retry_attempted
                        and fetch_result is not None
                        and fetch_result.get("complete") is not True
                        and fetch_result.get("truncated") is not True
                    ):
                        semantic_retry_targets.append(
                            (idx, cmts_ip, cmts_name)
                        )
                    elif not _finalize_target(
                        idx,
                        cmts_ip,
                        cmts_name,
                        outcome,
                        retry_attempted=retry_attempted,
                    ):
                        cancelled = True
                        break

                    pending.pop(0)
                    if next_target < len(phase_targets):
                        next_idx, next_ip, next_name = phase_targets[next_target]
                        pending.append(
                            (
                                next_idx,
                                next_ip,
                                next_name,
                                executor.submit(_fetch_target, next_ip, envelope),
                            )
                        )
                        next_target += 1
            finally:
                if executor is not None:
                    if cancelled:
                        for _, _, _, future in pending:
                            future.cancel()
                        executor.shutdown(wait=True, cancel_futures=True)
                    else:
                        executor.shutdown(wait=True)

        for idx, cmts_ip, cmts_name in invalid_targets:
            if not _finalize_target(
                idx,
                cmts_ip,
                cmts_name,
                {
                    "fetch_result": None,
                    "last_target_error": "missing CMTS IP",
                    "attempt_errors": [],
                    "validation_error": "CMTS target is missing an IP address",
                },
                retry_attempted=False,
            ):
                cancelled = True
                break

        if not cancelled:
            _run_phase(
                work_targets,
                concurrency=max_concurrency,
                envelope=first_pass_envelope,
                retry_attempted=False,
            )
        if not cancelled and semantic_retry_targets:
            self._update_running_job_progress(
                job_id,
                f"CPE retry: waiting {incomplete_retry_backoff_sec}s for "
                f"{len(semantic_retry_targets)} incomplete target(s)",
                rows_collected=rows_collected,
                modems_attempted=targets_attempted,
                modems_succeeded=targets_succeeded,
                modems_failed=targets_failed,
            )
            if not _wait_while_running(incomplete_retry_backoff_sec):
                cancelled = True
            else:
                _run_phase(
                    semantic_retry_targets,
                    concurrency=min(3, len(semantic_retry_targets)),
                    envelope=retry_envelope,
                    retry_attempted=True,
                )

        if cancelled:
            self._execute(
                "UPDATE poller_setting SET last_target_offset=0, updated_at=%s "
                "WHERE id=%s",
                (self._now(), poller_id),
            )
            return

        self._execute(
            "UPDATE poller_setting SET last_target_offset=0, updated_at=%s "
            "WHERE id=%s",
            (self._now(), poller_id),
        )
        result_status = "done"
        result_message = fatal_error
        if result_message:
            result_status = "failed"
        elif targets_attempted == 0:
            result_status = "failed"
            result_message = "No valid CMTS targets were attempted"
        elif targets_succeeded == 0:
            result_status = "failed"
            result_message = (
                f"CPE refresh failed for all {targets_attempted} attempted CMTS "
                "target(s); previous stored rows were preserved"
            )
        elif incomplete_targets:
            result_message = (
                f"CPE refresh completed with {targets_succeeded} successful and "
                f"{incomplete_targets} skipped/incomplete CMTS target(s); "
                "previous stored rows were preserved for failed targets"
            )
        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, rows_collected=%s, "
            "modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, "
            "error_text=%s WHERE id=%s AND status='running'",
            (
                result_status,
                self._now(),
                rows_collected,
                targets_attempted,
                targets_succeeded,
                targets_failed,
                result_message,
                job_id,
            ),
        )

    def _process_one_job(self) -> None:
        queued = self._query(
            "SELECT j.id, j.poller_id, j.error_text, j.request_payload, "
            "p.id AS setting_id, p.enabled, p.task_type, "
            "p.run_window_start, p.run_window_end "
            "FROM poller_job j LEFT JOIN poller_setting p ON p.id=j.poller_id "
            "WHERE j.status='queued' ORDER BY j.id ASC"
        )
        if not queued:
            return

        job = None
        for candidate in queued:
            setting_missing = candidate.get("setting_id") is None
            disabled = int(candidate.get("enabled") or 0) != 1
            is_fixed_task = str(candidate.get("task_type") or "inventory") in {
                _CPE_TASK_TYPE,
                _INVENTORY_FULL_TASK_TYPE,
            }
            inside_window = self._inside_run_window(
                candidate.get("run_window_start"),
                candidate.get("run_window_end"),
            )
            if setting_missing or disabled or is_fixed_task or inside_window:
                job = candidate
                break

            window = self._run_window_label(
                candidate.get("run_window_start"),
                candidate.get("run_window_end"),
            )
            waiting_message = f"Waiting for configured run window ({window})"
            if str(candidate.get("error_text") or "") != waiting_message:
                self._execute(
                    "UPDATE poller_job SET error_text=%s "
                    "WHERE id=%s AND status='queued'",
                    (waiting_message, int(candidate.get("id") or 0)),
                )

        if job is None:
            return

        job_id = int(job.get("id"))
        poller_id = int(job.get("poller_id") or 0)

        current_setting_rows = self._query(
            "SELECT enabled, task_type, run_window_start, run_window_end "
            "FROM poller_setting WHERE id=%s",
            (poller_id,),
        )
        if current_setting_rows:
            current_setting = current_setting_rows[0]
            is_enabled_inventory = (
                int(current_setting.get("enabled") or 0) == 1
                and str(current_setting.get("task_type") or "inventory")
                not in {_CPE_TASK_TYPE, _INVENTORY_FULL_TASK_TYPE}
            )
            if is_enabled_inventory and not self._inside_run_window(
                current_setting.get("run_window_start"),
                current_setting.get("run_window_end"),
            ):
                window = self._run_window_label(
                    current_setting.get("run_window_start"),
                    current_setting.get("run_window_end"),
                )
                waiting_message = f"Waiting for configured run window ({window})"
                self._execute(
                    "UPDATE poller_job SET error_text=%s "
                    "WHERE id=%s AND status='queued' "
                    "AND COALESCE(error_text, '')<>%s",
                    (waiting_message, job_id, waiting_message),
                )
                return

        self._execute(
            "UPDATE poller_job SET status=%s, started_at=%s WHERE id=%s",
            ("running", self._now(), job_id),
        )
        claimed = self._query("SELECT status FROM poller_job WHERE id=%s", (job_id,))
        if not claimed or str((claimed[0] or {}).get("status") or "") != "running":
            return

        rows_collected = 0
        modems_attempted = 0
        modems_succeeded = 0
        modems_failed = 0
        error_text = None
        nonfatal_rejection_text = None
        self._update_running_job_progress(
            job_id,
            "Starting poller job: loading settings",
            rows_collected=0,
            modems_attempted=0,
            modems_succeeded=0,
            modems_failed=0,
        )
        try:
            pr = self._query(
                "SELECT * FROM poller_setting WHERE id=%s",
                (poller_id,),
            )
            poller = pr[0] if pr else None
            if not poller:
                error_text = "Poller not found"
            elif int(poller.get("enabled") or 0) != 1:
                error_text = "Poller disabled"
            else:
                self._update_running_job_progress(
                    job_id,
                    "Resolving CMTS targets",
                    rows_collected=0,
                    modems_attempted=0,
                    modems_succeeded=0,
                    modems_failed=0,
                )
                task_type = str(poller.get("task_type") or "inventory")
                if task_type == _CPE_TASK_TYPE:
                    targets = self._cmts_targets_for_poller(poller)
                    self._process_cpe_job(job_id, poller, targets)
                    return

                is_inventory_task = task_type in _INVENTORY_TASK_TYPES
                collection_mode = (
                    "light"
                    if task_type == _INVENTORY_RECONCILE_TASK_TYPE
                    else "full"
                )
                wait_for_enrichment = task_type == _INVENTORY_FULL_TASK_TYPE
                start_offset = max(
                    0,
                    int(poller.get("last_target_offset") or 0),
                )
                raw_request_payload = job.get("request_payload")
                try:
                    request_payload = (
                        dict(raw_request_payload)
                        if isinstance(raw_request_payload, dict)
                        else json.loads(raw_request_payload or "{}")
                    )
                except (TypeError, ValueError):
                    request_payload = {}
                if not isinstance(request_payload, dict):
                    request_payload = {}

                def _normalize_inventory_targets(
                    raw_targets: Any,
                    *,
                    reject_duplicates: bool,
                    filter_non_ccap: bool,
                    reject_non_ccap: bool,
                ) -> tuple[List[Dict[str, str]], int]:
                    if not isinstance(raw_targets, list):
                        raise RuntimeError("Inventory target manifest is not a list")
                    normalized_targets = []
                    seen_ips = set()
                    excluded_non_ccap_count = 0
                    for target in raw_targets:
                        if not isinstance(target, dict):
                            raise RuntimeError(
                                "Inventory target manifest contains an invalid entry"
                            )
                        cmts_ip = str(target.get("ip") or "").strip()
                        if not cmts_ip:
                            raise RuntimeError(
                                "Inventory target manifest contains a blank CMTS IP"
                            )
                        cmts_name = str(
                            target.get("name") or cmts_ip
                        ).strip()
                        if not self._is_inventory_ccap_hostname(cmts_name):
                            if reject_non_ccap:
                                raise RuntimeError(
                                    "Inventory target manifest contains a non-CCAP "
                                    f"hostname: {cmts_name or '[blank]'}"
                                )
                            if filter_non_ccap:
                                excluded_non_ccap_count += 1
                                continue
                        ip_key = cmts_ip.lower()
                        if ip_key in seen_ips:
                            if reject_duplicates:
                                raise RuntimeError(
                                    "Inventory target manifest contains duplicate CMTS IPs"
                                )
                            continue
                        seen_ips.add(ip_key)
                        normalized_targets.append(
                            {
                                "name": cmts_name,
                                "ip": cmts_ip,
                            }
                        )
                    return normalized_targets, excluded_non_ccap_count

                if "inventory_targets" in request_payload:
                    manifest_version = request_payload.get(
                        "inventory_target_manifest_version"
                    )
                    supported_manifest_versions = (
                        {1, _INVENTORY_TARGET_MANIFEST_VERSION}
                        if is_inventory_task
                        else {1}
                    )
                    if manifest_version not in supported_manifest_versions:
                        raise RuntimeError(
                            "Unsupported inventory target manifest version"
                        )
                    targets, excluded_non_ccap_count = (
                        _normalize_inventory_targets(
                            request_payload.get("inventory_targets"),
                            reject_duplicates=True,
                            filter_non_ccap=(
                                is_inventory_task and manifest_version == 1
                            ),
                            reject_non_ccap=(
                                is_inventory_task
                                and manifest_version
                                == _INVENTORY_TARGET_MANIFEST_VERSION
                            ),
                        )
                    )
                    if is_inventory_task and manifest_version == 1:
                        if start_offset and excluded_non_ccap_count:
                            raise RuntimeError(
                                "Cannot safely resume a legacy inventory target "
                                "manifest containing non-CCAP hostnames"
                            )
                        request_payload["inventory_targets"] = targets
                        request_payload[
                            "inventory_target_manifest_version"
                        ] = _INVENTORY_TARGET_MANIFEST_VERSION
                        self._execute(
                            "UPDATE poller_job SET request_payload=%s "
                            "WHERE id=%s AND status='running'",
                            (json.dumps(request_payload), job_id),
                        )
                else:
                    if start_offset:
                        raise RuntimeError(
                            "Cannot safely resume inventory without a target manifest"
                        )
                    targets, excluded_non_ccap_count = (
                        _normalize_inventory_targets(
                            self._cmts_targets_for_poller(poller),
                            reject_duplicates=False,
                            filter_non_ccap=is_inventory_task,
                            reject_non_ccap=False,
                        )
                    )
                    request_payload["inventory_targets"] = targets
                    request_payload[
                        "inventory_target_manifest_version"
                    ] = (
                        _INVENTORY_TARGET_MANIFEST_VERSION
                        if is_inventory_task
                        else 1
                    )
                    self._execute(
                        "UPDATE poller_job SET request_payload=%s "
                        "WHERE id=%s AND status='running'",
                        (json.dumps(request_payload), job_id),
                    )
                if excluded_non_ccap_count:
                    logger.info(
                        "Filtered %s non-CCAP hostname(s) from inventory job %s",
                        excluded_non_ccap_count,
                        job_id,
                    )
                total_targets = len(targets)
                subtask_timeout_sec = max(
                    30,
                    int(os.environ.get("DATA_STORE_SUBTASK_TIMEOUT_SEC", "300")),
                )
                subtask_retries = max(
                    0,
                    int(os.environ.get("DATA_STORE_SUBTASK_RETRIES", "1")),
                )
                try:
                    max_concurrency = max(
                        1,
                        min(int(poller.get("max_concurrency") or 1), 6),
                    )
                except (TypeError, ValueError):
                    max_concurrency = 1
                self._update_running_job_progress(
                    job_id,
                    f"Resolved {total_targets} CMTS target(s) "
                    f"(resume offset={start_offset}, concurrency={max_concurrency})",
                    rows_collected=0,
                    modems_attempted=0,
                    modems_succeeded=0,
                    modems_failed=0,
                )
                if total_targets == 0:
                    error_text = "No CMTS targets resolved (check scope/appdb config)"

                checkpoint_offset = min(start_offset, total_targets)
                finalized_indices = set(range(1, checkpoint_offset + 1))
                breakdown_by_index: Dict[int, Dict[str, Any]] = {}
                cancelled = False

                def _job_is_running() -> bool:
                    status_rows = self._query(
                        "SELECT status FROM poller_job WHERE id=%s",
                        (job_id,),
                    )
                    return bool(
                        status_rows
                        and str((status_rows[0] or {}).get("status") or "").lower()
                        == "running"
                    )

                def _fetch_target(cmts_ip: str) -> Dict[str, Any]:
                    attempt_errors = []
                    last_target_error = None
                    if not cmts_ip:
                        return {
                            "cancelled": False,
                            "fetch_result": None,
                            "last_target_error": "missing CMTS IP",
                            "attempt_errors": [],
                        }
                    for attempt in range(1, subtask_retries + 2):
                        if not _job_is_running():
                            return {
                                "cancelled": True,
                                "fetch_result": None,
                                "last_target_error": last_target_error,
                                "attempt_errors": attempt_errors,
                            }
                        try:
                            return {
                                "cancelled": False,
                                "fetch_result": self._fetch_cmts_modems(
                                    cmts_ip,
                                    timeout_sec=subtask_timeout_sec,
                                    collection_mode=collection_mode,
                                    wait_for_enrichment=wait_for_enrichment,
                                ),
                                "last_target_error": last_target_error,
                                "attempt_errors": attempt_errors,
                            }
                        except Exception as exc:
                            last_target_error = str(exc)
                            attempt_errors.append((attempt, last_target_error))
                            timeout_text = last_target_error.lower()
                            if isinstance(exc, requests.Timeout) or any(
                                marker in timeout_text
                                for marker in ("timed out", "timeout")
                            ):
                                # The API cannot cancel a task already running on
                                # an agent. Retrying a timeout could overlap two
                                # physical walks against the same CMTS.
                                break
                    return {
                        "cancelled": False,
                        "fetch_result": None,
                        "last_target_error": last_target_error,
                        "attempt_errors": attempt_errors,
                    }

                def _finalize_target(
                    idx: int,
                    cmts_ip: str,
                    cmts_name: str,
                    outcome: Dict[str, Any],
                ) -> bool:
                    nonlocal checkpoint_offset
                    nonlocal error_text
                    nonlocal nonfatal_rejection_text
                    nonlocal modems_attempted
                    nonlocal modems_failed
                    nonlocal modems_succeeded
                    nonlocal rows_collected

                    if not _job_is_running():
                        return False
                    for attempt, attempt_error in outcome.get("attempt_errors") or []:
                        self._update_running_job_progress(
                            job_id,
                            f"CMTS {idx}/{total_targets}: {cmts_name} attempt "
                            f"{attempt}/{subtask_retries + 1} failed "
                            f"({attempt_error})",
                            rows_collected=rows_collected,
                            modems_attempted=modems_attempted,
                            modems_succeeded=modems_succeeded,
                            modems_failed=modems_failed,
                        )

                    fetch_result = outcome.get("fetch_result")
                    if fetch_result is None:
                        target_error = str(
                            outcome.get("last_target_error")
                            or "unknown CMTS fetch failure"
                        )
                        breakdown_entry = {
                            "cmts": cmts_name,
                            "cmts_ip": cmts_ip,
                            "row_count": 0,
                            "complete": False,
                            "truncated": False,
                            "capability_enriched": False,
                            "requested_limit": None,
                            "collected_at": None,
                            "critical_oid_errors": {},
                            "error": target_error,
                        }
                        modems_failed += 1
                        error_text = (
                            f"CMTS collection failed at {idx}/{total_targets} "
                            f"({cmts_name}): {target_error}"
                        )
                        failed_attempts = max(
                            1,
                            len(outcome.get("attempt_errors") or []),
                        )
                        progress_message = (
                            f"CMTS {idx}/{total_targets}: {cmts_name} skipped after "
                            f"{failed_attempts} failed attempt(s)"
                        )
                    else:
                        modems = fetch_result.get("modems") or []
                        modems_attempted += len(modems)
                        for modem in modems:
                            modem["cmts"] = cmts_name
                            modem["cmts_ip"] = cmts_ip

                        persistence = self.persist_scheduled_inventory_generation(
                            modems,
                            cmts_hostname=cmts_name,
                            cmts_ip=cmts_ip,
                            metadata=fetch_result,
                            source_poller=poller.get("name"),
                            task_type=task_type,
                            job_id=job_id,
                        )
                        written = int(persistence.get("row_count") or 0)
                        observed_count = int(
                            persistence.get("observed_row_count") or 0
                        )
                        persistence_authoritative = (
                            persistence.get("authoritative") is True
                        )
                        breakdown_entry = {
                            "cmts": cmts_name,
                            "cmts_ip": cmts_ip,
                            "row_count": written,
                            "observed_row_count": observed_count,
                            "complete": persistence.get("complete") is True,
                            "authoritative": persistence_authoritative,
                            "quarantined": persistence.get("quarantined") is True,
                            "quarantine_reason": persistence.get("quarantine_reason"),
                            "quarantine_candidate_count": persistence.get(
                                "quarantine_candidate_count"
                            ),
                            "collection_mode": persistence.get("collection_mode"),
                            "truncated": fetch_result.get("truncated") is True,
                            "capability_enriched": (
                                fetch_result.get("capability_enriched") is True
                            ),
                            "requested_limit": fetch_result.get("requested_limit"),
                            "collected_at": fetch_result.get("collected_at"),
                            "critical_oid_errors": (
                                fetch_result.get("critical_oid_errors") or {}
                            ),
                        }
                        rows_collected += written
                        if persistence_authoritative:
                            modems_succeeded += len(modems)
                            progress_message = (
                                f"CMTS {idx}/{total_targets}: {cmts_name} done "
                                f"({len(modems)} modems)"
                            )
                        else:
                            rejected_reason = str(
                                persistence.get("quarantine_reason")
                                or "non-authoritative generation"
                            )
                            modems_failed += max(1, len(modems))
                            nonfatal_rejection_text = (
                                f"CMTS collection rejected at {idx}/{total_targets} "
                                f"({cmts_name}): {rejected_reason}"
                            )
                            progress_message = (
                                f"CMTS {idx}/{total_targets}: {cmts_name} "
                                f"rejected ({rejected_reason})"
                            )

                    breakdown_by_index[idx] = breakdown_entry
                    finalized_indices.add(idx)
                    ordered_breakdown = [
                        value
                        for _, value in sorted(breakdown_by_index.items())
                    ]
                    self._execute(
                        "UPDATE poller_job SET cmts_breakdown=%s WHERE id=%s",
                        (json.dumps(ordered_breakdown), job_id),
                    )

                    previous_checkpoint = checkpoint_offset
                    while checkpoint_offset + 1 in finalized_indices:
                        checkpoint_offset += 1
                    if checkpoint_offset > previous_checkpoint:
                        self._execute(
                            "UPDATE poller_setting SET last_target_offset=%s, "
                            "updated_at=%s WHERE id=%s",
                            (checkpoint_offset, self._now(), poller_id),
                        )
                    self._update_running_job_progress(
                        job_id,
                        f"{progress_message} [checkpoint={checkpoint_offset}]",
                        rows_collected=rows_collected,
                        modems_attempted=modems_attempted,
                        modems_succeeded=modems_succeeded,
                        modems_failed=modems_failed,
                    )
                    return True

                work_targets = [
                    (
                        idx,
                        str(target.get("ip") or "").strip(),
                        target.get("name")
                        or target.get("ip")
                        or f"target-{idx}",
                    )
                    for idx, target in enumerate(targets, start=1)
                    if idx > start_offset
                ]
                executor = None
                pending: Dict[Any, tuple[int, str, str]] = {}
                next_target = 0
                try:
                    if work_targets:
                        executor = ThreadPoolExecutor(
                            max_workers=max_concurrency,
                            thread_name_prefix="poller-inventory-fetch",
                        )
                        while next_target < min(max_concurrency, len(work_targets)):
                            idx, cmts_ip, cmts_name = work_targets[next_target]
                            pending[executor.submit(_fetch_target, cmts_ip)] = (
                                idx,
                                cmts_ip,
                                cmts_name,
                            )
                            next_target += 1

                    while pending:
                        if not _job_is_running():
                            cancelled = True
                            break
                        done, _ = wait_for_futures(
                            tuple(pending.keys()),
                            timeout=1.0,
                        )
                        if not done:
                            continue
                        finished = sorted(
                            done,
                            key=lambda future: pending[future][0],
                        )
                        for future in finished:
                            idx, cmts_ip, cmts_name = pending.pop(future)
                            outcome = future.result()
                            if outcome.get("cancelled") or not _finalize_target(
                                idx,
                                cmts_ip,
                                cmts_name,
                                outcome,
                            ):
                                cancelled = True
                                break
                        if cancelled:
                            break
                        while (
                            next_target < len(work_targets)
                            and len(pending) < max_concurrency
                        ):
                            idx, cmts_ip, cmts_name = work_targets[next_target]
                            pending[executor.submit(_fetch_target, cmts_ip)] = (
                                idx,
                                cmts_ip,
                                cmts_name,
                            )
                            next_target += 1
                finally:
                    if executor is not None:
                        if cancelled:
                            for future in pending:
                                future.cancel()
                            executor.shutdown(wait=True, cancel_futures=True)
                        else:
                            executor.shutdown(wait=True)

                if cancelled:
                    self._execute(
                        "UPDATE poller_setting SET last_target_offset=0, "
                        "updated_at=%s WHERE id=%s",
                        (self._now(), poller_id),
                    )
                    return

                if (
                    task_type == _INVENTORY_FULL_TASK_TYPE
                    and not error_text
                    and not nonfatal_rejection_text
                ):
                    try:
                        self._purge_retired_inventory(7)
                    except Exception as purge_exc:
                        logger.warning(
                            "Retired inventory purge after full job %s failed: %s",
                            job_id,
                            purge_exc,
                        )

                # Every target has now been finalized (including skipped failures),
                # so the next scheduled run must start a fresh full pass.
                self._execute(
                    "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s WHERE id=%s",
                    (0, self._now(), poller_id),
                )

        except Exception as exc:
            error_text = str(exc)
            modems_failed = max(modems_failed, 1)
            try:
                self._execute(
                    "UPDATE poller_setting SET last_target_offset=0, "
                    "updated_at=%s WHERE id=%s",
                    (self._now(), poller_id),
                )
            except Exception as checkpoint_exc:
                logger.warning(
                    "Failed to reset inventory checkpoint after job %s error: %s",
                    job_id,
                    checkpoint_exc,
                )

        result_status = "failed" if error_text else "done"
        result_message = error_text
        if not error_text and nonfatal_rejection_text:
            if modems_succeeded <= 0:
                result_status = "failed"
                result_message = (
                    "Inventory collection produced no authoritative modem rows; "
                    f"last rejection: {nonfatal_rejection_text}"
                )
            else:
                result_message = (
                    "Inventory completed with quarantined generation(s); "
                    f"last rejection: {nonfatal_rejection_text}"
                )

        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, error_text=%s WHERE id=%s AND status='running'",
            (result_status, self._now(), int(rows_collected), int(modems_attempted), int(modems_succeeded), int(modems_failed), result_message, job_id),
        )

    def _update_running_job_progress(
        self,
        job_id: int,
        message: str,
        *,
        rows_collected: int,
        modems_attempted: int,
        modems_succeeded: int,
        modems_failed: int,
    ) -> None:
        self._execute(
            "UPDATE poller_job SET rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, error_text=%s WHERE id=%s AND status='running'",
            (int(rows_collected), int(modems_attempted), int(modems_succeeded), int(modems_failed), str(message), int(job_id)),
        )

    def list_pollers(self) -> List[Dict[str, Any]]:
        return self._query("SELECT * FROM poller_setting ORDER BY id ASC")

    def upsert_poller(self, payload: Dict[str, Any]) -> int:
        now = self._now()
        poller_id = payload.get("id")

        if poller_id is not None:
            protected = self._query(
                "SELECT system_key FROM poller_setting WHERE id=%s",
                (int(poller_id),),
            )
            if protected and protected[0].get("system_key"):
                if "enabled" in payload:
                    self._execute(
                        "UPDATE poller_setting SET enabled=%s, updated_at=%s WHERE id=%s",
                        (bool(payload.get("enabled")), now, int(poller_id)),
                    )
                return int(poller_id)

        if poller_id is None:
            cols = [k for k in payload.keys() if k != "id"]
            vals = [payload[k] for k in cols]
            cols += ["created_at", "updated_at"]
            vals += [now, now]

            ph = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO poller_setting ({', '.join(cols)}) VALUES ({ph})"
            return int(self._execute(sql, tuple(vals)) or 0)

        poller_id = int(poller_id)
        set_cols = [k for k in payload.keys() if k != "id"]
        assignments = ", ".join([f"{k}=%s" for k in set_cols] + ["updated_at=%s"])
        params = [payload[k] for k in set_cols] + [now, poller_id]
        sql = (
            f"UPDATE poller_setting SET {assignments} WHERE id={'%s'}"
        )
        self._execute(sql, tuple(params))
        return poller_id

    def set_poller_enabled(self, poller_id: int, enabled: bool) -> Dict[str, Any]:
        pid = int(poller_id)
        exists = self._query(
            "SELECT id, enabled FROM poller_setting WHERE id=%s", (pid,)
        )
        if not exists:
            return {"updated": 0, "state": "not_found"}
        self._execute(
            "UPDATE poller_setting SET enabled=%s, updated_at=%s WHERE id=%s",
            (bool(enabled), self._now(), pid),
        )
        return {"updated": 1, "state": "enabled" if enabled else "disabled"}

    def delete_poller(self, poller_id: int) -> Dict[str, Any]:
        pid = int(poller_id)

        exists = self._query(
            "SELECT id, system_key FROM poller_setting WHERE id=%s", (pid,)
        )
        if not exists:
            return {"deleted": 0, "state": "not_found"}
        if exists[0].get("system_key"):
            return {"deleted": 0, "state": "protected"}

        active = self._query(
            "SELECT COUNT(*) AS c FROM poller_job WHERE poller_id=%s AND status IN ('queued','running')",
            (pid,),
        )
        active_count = int((active[0] or {}).get("c") or 0) if active else 0
        if active_count > 0:
            return {"deleted": 0, "state": "active_jobs", "active_jobs": active_count}

        # Remove historical jobs first to satisfy FK fk_poller_job_setting.
        jobs_rows = self._query("SELECT COUNT(*) AS c FROM poller_job WHERE poller_id=%s", (pid,))
        jobs_count = int((jobs_rows[0] or {}).get("c") or 0) if jobs_rows else 0
        if jobs_count > 0:
            self._execute("DELETE FROM poller_job WHERE poller_id=%s", (pid,))

        self._execute("DELETE FROM poller_setting WHERE id=%s", (pid,))
        return {"deleted": 1, "state": "deleted", "deleted_jobs": jobs_count}

    def request_run(
        self,
        poller_id: int,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and queue an explicit run request."""
        pid = int(poller_id)
        pollers = self._query(
            "SELECT id, enabled, task_type, run_window_start, run_window_end "
            "FROM poller_setting WHERE id=%s",
            (pid,),
        )
        if not pollers:
            return {"state": "not_found", "job_id": 0}
        poller = pollers[0]
        if int(poller.get("enabled") or 0) != 1:
            return {"state": "disabled", "job_id": 0}

        active = self._query(
            "SELECT id FROM poller_job WHERE poller_id=%s "
            "AND status IN ('queued','running') ORDER BY id DESC LIMIT 1",
            (pid,),
        )
        if active:
            return {
                "state": "already_active",
                "job_id": int(active[0].get("id") or 0),
            }

        if (
            str(poller.get("task_type") or "inventory")
            not in {_CPE_TASK_TYPE, _INVENTORY_FULL_TASK_TYPE}
            and not self._inside_run_window(
                poller.get("run_window_start"),
                poller.get("run_window_end"),
            )
        ):
            return {
                "state": "outside_run_window",
                "job_id": 0,
                "detail": self._run_window_detail(
                    poller.get("run_window_start"),
                    poller.get("run_window_end"),
                ),
            }

        try:
            job_id = self.enqueue_run(
                pid,
                source=source,
                explicit_request=True,
            )
        except _PollerRunAlreadyActive as exc:
            return {"state": "already_active", "job_id": exc.job_id}
        except _PollerOutsideRunWindow as exc:
            return {
                "state": "outside_run_window",
                "job_id": 0,
                "detail": exc.detail,
            }
        return {"state": "queued" if job_id else "rejected", "job_id": job_id}

    def enqueue_run(
        self,
        poller_id: int,
        source: Optional[str] = None,
        scheduled_slot_utc: Optional[str] = None,
        enforce_interval_due: bool = False,
        explicit_request: bool = False,
    ) -> int:
        pid = int(poller_id)
        now = self._now()
        trigger = "scheduler" if (source or "api") == "scheduler" else "manual"
        payload = json.dumps({"source": source or "api"})
        sql = (
            "INSERT IGNORE INTO poller_job "
            "(poller_id, trigger_type, status, requested_by, request_payload, "
            "scheduled_slot_utc, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        )
        conn = self._connect()
        try:
            conn.begin()
            cur = conn.cursor()
            cur.execute(
                "SELECT enabled, task_type, interval_minutes, run_window_start, "
                "run_window_end FROM poller_setting WHERE id=%s FOR UPDATE",
                (pid,),
            )
            setting = cur.fetchone()
            if not setting:
                conn.rollback()
                return 0

            if enforce_interval_due:
                if (
                    int(setting.get("enabled") or 0) != 1
                    or str(setting.get("task_type") or "inventory")
                    not in {"inventory", _INVENTORY_RECONCILE_TASK_TYPE}
                    or not self._inside_run_window(
                        setting.get("run_window_start"),
                        setting.get("run_window_end"),
                    )
                ):
                    conn.rollback()
                    return 0
                minutes = max(1, int(setting.get("interval_minutes") or 360))
                cur.execute(
                    "SELECT id FROM poller_setting WHERE id=%s "
                    "AND last_interval_enqueue_utc >= "
                    "(UTC_TIMESTAMP() - INTERVAL %s MINUTE) LIMIT 1",
                    (pid, minutes),
                )
                if cur.fetchone():
                    conn.rollback()
                    return 0

            cur.execute(
                "SELECT id FROM poller_job WHERE poller_id=%s "
                "AND status IN ('queued','running') "
                "ORDER BY id DESC LIMIT 1",
                (pid,),
            )
            active = cur.fetchone()
            if active:
                active_job_id = int(active.get("id") or 0)
                if explicit_request:
                    conn.rollback()
                    raise _PollerRunAlreadyActive(active_job_id)
                conn.commit()
                if enforce_interval_due or trigger == "scheduler":
                    return 0
                return active_job_id

            if (
                explicit_request
                and str(setting.get("task_type") or "inventory")
                not in {_CPE_TASK_TYPE, _INVENTORY_FULL_TASK_TYPE}
                and not self._inside_run_window(
                    setting.get("run_window_start"),
                    setting.get("run_window_end"),
                )
            ):
                detail = self._run_window_detail(
                    setting.get("run_window_start"),
                    setting.get("run_window_end"),
                )
                conn.rollback()
                raise _PollerOutsideRunWindow(detail)

            cur.execute(
                sql,
                (
                    pid,
                    trigger,
                    "queued",
                    source or "api",
                    payload,
                    scheduled_slot_utc,
                    now,
                ),
            )
            job_id = int(cur.lastrowid or 0)
            if job_id and str(setting.get("task_type") or "inventory") in {
                "inventory",
                _INVENTORY_RECONCILE_TASK_TYPE,
            }:
                cur.execute(
                    "UPDATE poller_setting SET "
                    "last_interval_enqueue_utc="
                    "GREATEST(COALESCE(last_interval_enqueue_utc, %s), %s), "
                    "updated_at=%s WHERE id=%s",
                    (now, now, now, pid),
                )
            if not job_id and scheduled_slot_utc:
                cur.execute(
                    "SELECT id FROM poller_job WHERE poller_id=%s "
                    "AND scheduled_slot_utc=%s LIMIT 1",
                    (pid, scheduled_slot_utc),
                )
                existing = cur.fetchone()
                job_id = int((existing or {}).get("id") or 0)
            conn.commit()
            return job_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_jobs(self, limit: int = 30) -> List[Dict[str, Any]]:
        lim = max(1, int(limit))
        ph = "%s"
        rows = self._query(
            f"SELECT j.id, j.poller_id, p.name AS poller_name, "
            f"p.task_type, j.trigger_type, j.status, j.rows_collected, "
            f"j.modems_attempted, j.modems_succeeded, j.modems_failed, "
            f"j.error_text, j.cmts_breakdown, j.scheduled_slot_utc, "
            f"j.started_at, j.finished_at, j.created_at, "
            f"TIMESTAMPDIFF(SECOND, j.started_at, "
            f"COALESCE(j.finished_at, UTC_TIMESTAMP())) AS duration_seconds "
            f"FROM poller_job j LEFT JOIN poller_setting p ON p.id=j.poller_id "
            f"ORDER BY j.id DESC LIMIT {ph}",
            (lim,),
        )
        return rows

    def clear_jobs(self) -> int:
        before = self._query("SELECT COUNT(*) AS c FROM poller_job WHERE status IN ('done','failed','cancelled','timed_out','completed')")
        count_before = int((before[0] or {}).get("c") or 0) if before else 0
        self._execute("DELETE FROM poller_job WHERE status IN ('done','failed','cancelled','timed_out','completed')")
        return count_before

    def clear_all_jobs(self) -> int:
        before = self._query("SELECT COUNT(*) AS c FROM poller_job WHERE status NOT IN ('running','queued')")
        count_before = int((before[0] or {}).get("c") or 0) if before else 0
        self._execute("DELETE FROM poller_job WHERE status NOT IN ('running','queued')")
        return count_before

    def kill_job(self, job_id: int) -> Dict[str, Any]:
        rows = self._query(
            "SELECT id, status, poller_id FROM poller_job WHERE id=%s",
            (int(job_id),),
        )
        if not rows:
            return {"killed": 0, "state": "not_found"}

        state = str((rows[0] or {}).get("status") or "").lower()
        if state in {"done", "failed", "cancelled", "timed_out", "completed"}:
            return {"killed": 0, "state": state}

        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, error_text=%s "
            "WHERE id=%s AND status IN ('queued','running')",
            ("cancelled", self._now(), "Killed by admin", int(job_id)),
        )
        self._execute(
            "UPDATE poller_setting SET last_target_offset=0, updated_at=%s "
            "WHERE id=%s",
            (self._now(), int(rows[0].get("poller_id") or 0)),
        )
        return {"killed": 1, "state": "cancelled"}

    def get_scheduler_status(self) -> Dict[str, Any]:
        out = dict(self._scheduler)
        out["decisions"] = self._get_scheduler_decisions(limit=100)
        return out

    def set_scheduler_enabled(self, enabled: bool) -> Dict[str, Any]:
        self._scheduler["enabled"] = bool(enabled)
        self._scheduler["last_tick"] = datetime.now(timezone.utc).isoformat()
        return dict(self._scheduler)

    def set_scheduler_poll(self, poll_sec: int) -> Dict[str, Any]:
        self._scheduler["poll_sec"] = max(5, int(poll_sec))
        self._scheduler["last_tick"] = datetime.now(timezone.utc).isoformat()
        return dict(self._scheduler)

    @staticmethod
    def _schedule_zone() -> ZoneInfo:
        return ZoneInfo("Europe/Amsterdam")

    @staticmethod
    def _coerce_schedule_time(value: object) -> datetime_time | None:
        if value is None:
            return None
        if isinstance(value, datetime_time):
            return value.replace(tzinfo=None)
        if isinstance(value, timedelta):
            total_seconds = int(value.total_seconds())
            if total_seconds < 0 or total_seconds >= 24 * 60 * 60:
                return None
            hours, remainder = divmod(total_seconds, 60 * 60)
            minutes, seconds = divmod(remainder, 60)
            return datetime_time(hour=hours, minute=minutes, second=seconds)

        text = str(value).strip()
        if not text:
            return None
        try:
            if text.startswith("PT"):
                duration = text[2:]
                hours = 0
                minutes = 0
                if "H" in duration:
                    hour_text, duration = duration.split("H", 1)
                    hours = int(hour_text or 0)
                if "M" in duration:
                    minute_text, _ = duration.split("M", 1)
                    minutes = int(minute_text or 0)
                return datetime_time(hour=hours, minute=minutes)
            parts = text.split(":")
            if len(parts) < 2:
                return None
            seconds = int(float(parts[2])) if len(parts) > 2 else 0
            return datetime_time(
                hour=int(parts[0]),
                minute=int(parts[1]),
                second=seconds,
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _inside_run_window(
        cls,
        run_window_start: object,
        run_window_end: object,
        now_utc: datetime | None = None,
    ) -> bool:
        if run_window_start is None and run_window_end is None:
            return True

        start = cls._coerce_schedule_time(run_window_start)
        end = cls._coerce_schedule_time(run_window_end)
        if (run_window_start is not None and start is None) or (
            run_window_end is not None and end is None
        ):
            return False

        current_utc = now_utc or datetime.now(timezone.utc)
        if current_utc.tzinfo is None:
            current_utc = current_utc.replace(tzinfo=timezone.utc)
        current = current_utc.astimezone(cls._schedule_zone()).time().replace(
            tzinfo=None
        )
        if start is None:
            return end is not None and current < end
        if end is None:
            return current >= start
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    @classmethod
    def _run_window_label(
        cls,
        run_window_start: object,
        run_window_end: object,
    ) -> str:
        start = cls._coerce_schedule_time(run_window_start)
        end = cls._coerce_schedule_time(run_window_end)
        start_text = start.strftime("%H:%M:%S") if start is not None else "any"
        end_text = end.strftime("%H:%M:%S") if end is not None else "any"
        return f"Europe/Amsterdam {start_text}-{end_text}"

    @classmethod
    def _run_window_detail(
        cls,
        run_window_start: object,
        run_window_end: object,
        now_utc: datetime | None = None,
    ) -> str:
        current_utc = now_utc or datetime.now(timezone.utc)
        if current_utc.tzinfo is None:
            current_utc = current_utc.replace(tzinfo=timezone.utc)
        local_now = current_utc.astimezone(cls._schedule_zone())
        window = cls._run_window_label(run_window_start, run_window_end)
        return f"{window}; local time {local_now.strftime('%H:%M:%S')}"

    def _latest_cpe_slot_utc(self, now_utc: datetime | None = None) -> str:
        current_utc = now_utc or datetime.now(timezone.utc)
        local_now = current_utc.astimezone(self._schedule_zone())
        slot = _CPE_TASK_SCHEDULE[1] if local_now.hour >= 12 else _CPE_TASK_SCHEDULE[0]
        local_slot = local_now.replace(
            hour=slot.hour,
            minute=slot.minute,
            second=0,
            microsecond=0,
        )
        return local_slot.astimezone(timezone.utc).replace(tzinfo=None).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def _latest_daily_slot_utc(
        self,
        slot: datetime_time,
        now_utc: datetime | None = None,
    ) -> str:
        current_utc = now_utc or datetime.now(timezone.utc)
        local_now = current_utc.astimezone(self._schedule_zone())
        local_slot = local_now.replace(
            hour=slot.hour,
            minute=slot.minute,
            second=slot.second,
            microsecond=0,
        )
        if local_now < local_slot:
            local_slot -= timedelta(days=1)
        return local_slot.astimezone(timezone.utc).replace(tzinfo=None).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def run_scheduler_once(self) -> int:
        scheduler_lock_conn = self._try_acquire_scheduler_lock()
        if scheduler_lock_conn is None:
            return 0
        if self._scheduler.get("running"):
            scheduler_lock_conn.close()
            return 0

        self._scheduler["running"] = True
        tick_iso = datetime.now(timezone.utc).isoformat()
        tick_sql = self._now()
        self._scheduler["last_tick"] = tick_iso
        queued = 0
        decisions = []
        try:
            try:
                max_global_active = max(
                    1,
                    int(os.environ.get("DATA_STORE_MAX_ACTIVE_JOBS", "10")),
                )
            except (TypeError, ValueError):
                max_global_active = 10
            active_job_rows = self._query(
                "SELECT j.status, p.id AS setting_id, p.enabled, p.task_type, "
                "p.run_window_start, p.run_window_end "
                "FROM poller_job j LEFT JOIN poller_setting p ON p.id=j.poller_id "
                "WHERE j.status IN ('queued','running')"
            )
            global_active = 0
            for active_job in active_job_rows:
                status = str(active_job.get("status") or "").lower()
                setting_missing = active_job.get("setting_id") is None
                disabled = int(active_job.get("enabled") or 0) != 1
                is_fixed_task = str(active_job.get("task_type") or "inventory") in {
                    _CPE_TASK_TYPE,
                    _INVENTORY_FULL_TASK_TYPE,
                }
                inside_window = self._inside_run_window(
                    active_job.get("run_window_start"),
                    active_job.get("run_window_end"),
                )
                if (
                    status == "running"
                    or setting_missing
                    or disabled
                    or is_fixed_task
                    or inside_window
                ):
                    global_active += 1

            pollers = self._query(
                "SELECT id, name, enabled, interval_minutes, task_type, "
                "run_window_start, run_window_end, "
                "last_scheduled_slot_utc, last_interval_enqueue_utc "
                "FROM poller_setting ORDER BY id ASC"
            )
            for p in pollers:
                pid = int(p.get("id") or 0)
                if pid <= 0:
                    continue
                pname = p.get("name") or f"poller-{pid}"

                if int(p.get("enabled") or 0) != 1:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "disabled"})
                    continue

                if global_active >= max_global_active:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "global_active_limit"})
                    continue

                active = self._query(
                    "SELECT id FROM poller_job WHERE poller_id=%s AND status IN ('queued','running') LIMIT 1",
                    (pid,),
                )
                if active:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "active_job_exists"})
                    continue

                task_type = str(p.get("task_type") or "inventory")
                if task_type in {_CPE_TASK_TYPE, _INVENTORY_FULL_TASK_TYPE}:
                    if task_type == _CPE_TASK_TYPE:
                        scheduled_slot = self._latest_cpe_slot_utc()
                        fixed_reason = "fixed_schedule_due"
                    else:
                        scheduled_slot = self._latest_daily_slot_utc(
                            _INVENTORY_FULL_SCHEDULE
                        )
                        fixed_reason = "daily_full_schedule_due"
                    recorded_slot = p.get("last_scheduled_slot_utc")
                    if isinstance(recorded_slot, datetime):
                        recorded_slot = recorded_slot.strftime("%Y-%m-%d %H:%M:%S")
                    elif recorded_slot is not None:
                        recorded_slot = str(recorded_slot)
                    if recorded_slot == scheduled_slot:
                        decisions.append({
                            "poller_id": pid,
                            "poller_name": pname,
                            "decision": "skip",
                            "reason": "scheduled_slot_already_recorded",
                        })
                        continue

                    existing_slot = self._query(
                        "SELECT id FROM poller_job WHERE poller_id=%s "
                        "AND scheduled_slot_utc=%s LIMIT 1",
                        (pid, scheduled_slot),
                    )
                    if existing_slot:
                        self._execute(
                            "UPDATE poller_setting SET last_scheduled_slot_utc=%s, "
                            "updated_at=%s WHERE id=%s",
                            (scheduled_slot, self._now(), pid),
                        )
                        decisions.append({
                            "poller_id": pid,
                            "poller_name": pname,
                            "decision": "skip",
                            "reason": "scheduled_slot_already_exists",
                        })
                        continue
                    new_id = self.enqueue_run(
                        pid,
                        source="scheduler",
                        scheduled_slot_utc=scheduled_slot,
                    )
                    if new_id:
                        self._execute(
                            "UPDATE poller_setting SET last_scheduled_slot_utc=%s, "
                            "updated_at=%s WHERE id=%s",
                            (scheduled_slot, self._now(), pid),
                        )
                        queued += 1
                        global_active += 1
                        decisions.append({
                            "poller_id": pid,
                            "poller_name": pname,
                            "decision": "queued",
                            "reason": fixed_reason,
                        })
                    else:
                        decisions.append({
                            "poller_id": pid,
                            "poller_name": pname,
                            "decision": "skip",
                            "reason": "enqueue_rejected",
                        })
                    continue

                if not self._inside_run_window(
                    p.get("run_window_start"),
                    p.get("run_window_end"),
                ):
                    decisions.append({
                        "poller_id": pid,
                        "poller_name": pname,
                        "decision": "skip",
                        "reason": "outside_run_window",
                        "detail": self._run_window_detail(
                            p.get("run_window_start"),
                            p.get("run_window_end"),
                        ),
                    })
                    continue

                minutes = max(1, int(p.get("interval_minutes") or 360))
                due = self._query(
                    """
                    SELECT id FROM poller_setting
                    WHERE id=%s
                      AND last_interval_enqueue_utc >=
                          (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
                    LIMIT 1
                    """,
                    (pid, minutes),
                )
                if due:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "interval_not_due"})
                    continue

                new_id = self.enqueue_run(
                    pid,
                    source="scheduler",
                    enforce_interval_due=True,
                )
                if new_id:
                    queued += 1
                    global_active += 1
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "queued", "reason": "ok"})
                else:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "enqueue_rejected"})
        finally:
            try:
                self._scheduler["decisions"] = decisions[:100]
                self._log_scheduler_decisions(tick_sql, decisions)
            finally:
                self._scheduler["running"] = False
                scheduler_lock_conn.close()
        return queued

    def snapshots_by_day(self, lookback_days: int = 14, limit: int = 300) -> List[Dict[str, Any]]:
        capped_days = max(1, int(lookback_days))
        capped_limit = max(1, int(limit))
        raw = self._query(
            """
            SELECT
                DATE(COALESCE(j.finished_at, j.started_at, j.created_at)) AS day,
                COALESCE(NULLIF(p.name, ''), CONCAT('poller-', j.poller_id)) AS poller_name,
                SUM(GREATEST(COALESCE(j.rows_collected, 0), 0)) AS snapshots
            FROM poller_job j
            LEFT JOIN poller_setting p ON p.id = j.poller_id
            WHERE COALESCE(j.finished_at, j.started_at, j.created_at) >= (UTC_TIMESTAMP() - INTERVAL %s DAY)
              AND j.status IN ('running', 'done', 'failed', 'timed_out', 'cancelled', 'completed')
            GROUP BY DATE(COALESCE(j.finished_at, j.started_at, j.created_at)), COALESCE(NULLIF(p.name, ''), CONCAT('poller-', j.poller_id))
            ORDER BY day DESC, snapshots DESC
            LIMIT %s
            """,
            (capped_days, capped_limit),
        )
        rows: List[Dict[str, Any]] = []
        for r in raw:
            rows.append(
                {
                    "day": str(r.get("day") or ""),
                    "poller_name": str(r.get("poller_name") or "unknown"),
                    "snapshots": int(r.get("snapshots") or 0),
                }
            )
        return rows

    def snapshots_analytics(self, lookback_days: int = 14) -> Dict[str, Any]:
        days = max(1, int(lookback_days))
        rows = self.snapshots_by_day(lookback_days=days, limit=5000)
        per_day: Dict[str, int] = {}
        for r in rows:
            day = str(r.get("day") or "")
            per_day[day] = per_day.get(day, 0) + int(r.get("snapshots") or 0)

        daily_series = [{"day": d, "total": t} for d, t in sorted(per_day.items(), reverse=True)]
        total = sum(int(x.get("total") or 0) for x in daily_series)
        half = max(1, len(daily_series) // 2)
        recent_sum = sum(int(x.get("total") or 0) for x in daily_series[:half])
        older_sum = sum(int(x.get("total") or 0) for x in daily_series[half:])
        growth_pct = 0.0 if older_sum <= 0 else round(((recent_sum - older_sum) / older_sum) * 100.0, 1)
        return {
            "lookback_days": days,
            "total_snapshots": total,
            "total_snapshots_window": total,
            "avg_per_day": round(total / days, 2),
            "growth_pct": growth_pct,
            "deleted_last_24h": 0,
            "daily_series": daily_series,
        }

    @staticmethod
    def normalize_cpe_search(value: str) -> Dict[str, Any]:
        query = str(value or '').strip()
        if not query:
            raise ValueError('CPE address is required')
        if ':' in query:
            try:
                address = ipaddress.ip_address(query)
            except ValueError as exc:
                raise ValueError('Enter a complete valid IPv6 address') from exc
            if address.version != 6:
                raise ValueError('Enter a complete valid IPv6 address')
            return {'family': 'ipv6', 'value': address.compressed, 'prefix': False}

        trailing_dot = query.endswith('.')
        parts = query[:-1].split('.') if trailing_dot else query.split('.')
        if not 1 <= len(parts) <= 4 or any(not part.isdigit() for part in parts):
            raise ValueError('Enter a valid dotted IPv4 address prefix')
        octets = [int(part) for part in parts]
        if any(not 0 <= octet <= 255 for octet in octets):
            raise ValueError('IPv4 prefix octets must be between 0 and 255')
        if len(octets) == 4 and not trailing_dot:
            return {
                'family': 'ipv4',
                'value': ipaddress.ip_address('.'.join(str(o) for o in octets)).compressed,
                'prefix': False,
            }
        if len(octets) == 4:
            raise ValueError('A complete IPv4 address cannot end with a dot')
        return {
            'family': 'ipv4',
            'value': '.'.join(str(o) for o in octets) + '.',
            'prefix': True,
        }

    @staticmethod
    def normalize_cpe_suggestion(value: str) -> Dict[str, Any]:
        """Normalize canonical CPE text prefixes for autocomplete only."""
        query = str(value or '').strip().lower()
        if ':' not in query:
            try:
                return PollerService.normalize_cpe_search(query)
            except ValueError:
                if 1 <= len(query) <= 4 and all(
                    character in '0123456789abcdef' for character in query
                ):
                    if len(query) > 1 and query.startswith('0'):
                        raise ValueError('Enter a canonical IPv6 address prefix')
                    return {'family': 'ipv6', 'value': query, 'prefix': True}
                raise

        try:
            address = ipaddress.ip_address(query)
        except ValueError:
            if any(character not in '0123456789abcdef:' for character in query):
                raise ValueError('Enter a valid IPv6 address prefix')
            if query.startswith(':') and not query.startswith('::'):
                raise ValueError('Enter a valid IPv6 address prefix')
            if ':::' in query or query.count('::') > 1:
                raise ValueError('Enter a valid IPv6 address prefix')
            groups = query.split(':')
            if any(len(group) > 4 for group in groups):
                raise ValueError('Enter a valid IPv6 address prefix')
            if any(len(group) > 1 and group.startswith('0') for group in groups):
                raise ValueError('Enter a canonical IPv6 address prefix')
            if '::' in query:
                left, right = query.split('::', 1)
                if (
                    left == '0'
                    or left.endswith(':0')
                    or right == '0'
                    or right.startswith('0:')
                ):
                    raise ValueError('Enter a canonical IPv6 address prefix')
            populated_groups = sum(bool(group) for group in groups)
            if ('::' in query and populated_groups > 7) or (
                '::' not in query and len(groups) > 8
            ):
                raise ValueError('Enter a valid IPv6 address prefix')
            return {'family': 'ipv6', 'value': query, 'prefix': True}

        if address.version != 6:
            raise ValueError('Enter a valid IPv6 address prefix')
        return {'family': 'ipv6', 'value': address.compressed, 'prefix': True}

    def list_inventory_modems_page(
        self,
        cmts: Optional[str] = None,
        search_type: Optional[str] = None,
        search_value: Optional[str] = None,
        interface_filter: Optional[str] = None,
        lifecycle_state: str = "active",
        area: Optional[str] = "all",
        offset: int = 0,
        limit: int | None = None,
    ) -> Dict[str, Any]:
        """Return one stable filtered page, with an exact total when inexpensive."""
        if limit is None:
            limit = self._cm_modem_limit_default()
        limit = max(1, min(int(limit or self._cm_modem_limit_default()), 50000))
        offset = max(0, int(offset or 0))
        state = str(lifecycle_state or "active").strip().lower()
        if state not in {"active", "suspect_missing", "retired", "all"}:
            raise ValueError(
                "lifecycle_state must be one of: active, suspect_missing, retired, all"
            )
        normalized_area = self._normalize_inventory_area(area)
        where: List[str] = []
        params: List[Any] = []
        resolved_search_type: Optional[str] = None
        total_exact = True
        index_hint_sql = ""
        order_sql_override: Optional[str] = None

        def literal_like_pattern(value: str, *, contains: bool = False) -> str:
            escaped = value.replace("=", "==").replace("%", "=%").replace("_", "=_")
            return f"%{escaped}%" if contains else escaped + "%"
        if state != "all":
            where.append("m.inventory_state=%s")
            params.append(state)

        if cmts:
            cmts_value = str(cmts).strip()
            try:
                ipaddress.ip_address(cmts_value)
                cmts_column = "m.cmts_ip"
            except ValueError:
                cmts_column = "m.cmts"
            # Both columns use a case-insensitive collation in production. Direct
            # equality keeps the predicate sargable so the existing indexes are used.
            where.append(f"{cmts_column}=%s")
            params.append(cmts_value)

        if normalized_area != "all":
            area_predicate, area_params = self._area_sql_predicate(
                "s.area", normalized_area
            )
            where.append(
                "EXISTS (SELECT 1 FROM inventory_summary_status s "
                f"WHERE s.cmts_ip=m.cmts_ip AND {area_predicate})"
            )
            params.extend(area_params)

        if search_value:
            search_text = str(search_value).strip()
            normalized_search_type = str(search_type or "auto").strip().lower()
            normalized_search_type = {
                "all": "identity",
                "firmware": "software",
            }.get(normalized_search_type, normalized_search_type)
            allowed_search_types = {
                "auto",
                "identity",
                "mac",
                "ip",
                "vendor",
                "model",
                "software",
                "docsis",
                "fiber_node",
                "name",
                "cpe_ip",
            }
            if normalized_search_type not in allowed_search_types:
                raise ValueError(
                    "search_type must be one of: auto, mac, ip, vendor, model, "
                    "software, docsis, fiber_node, identity, cpe_ip"
                )

            formatted_mac = self._normalize_mac(search_text)
            try:
                parsed_ip = ipaddress.ip_address(search_text)
            except ValueError:
                parsed_ip = None

            if normalized_search_type == "auto":
                if formatted_mac:
                    normalized_search_type = "mac"
                elif parsed_ip is not None:
                    normalized_search_type = "ip"
                elif cmts:
                    normalized_search_type = "identity"
                else:
                    raise ValueError(
                        "All-server text search requires a search field; select "
                        "MAC, IP, vendor, model, software, DOCSIS, or fiber node"
                    )
            resolved_search_type = normalized_search_type

            if normalized_search_type == "cpe_ip":
                cpe_query = self.normalize_cpe_search(search_text)
                comparator = "c.ip_address LIKE %s" if cpe_query["prefix"] else "c.ip_address=%s"
                where.append(
                    "EXISTS (SELECT 1 FROM modem_cpe_ip_current c "
                    "WHERE c.modem_mac=m.mac AND c.cmts_ip=m.cmts_ip "
                    f"AND c.address_family=%s AND {comparator})"
                )
                params.extend(
                    [
                        cpe_query["family"],
                        cpe_query["value"] + "%"
                        if cpe_query["prefix"]
                        else cpe_query["value"],
                    ]
                )
            elif normalized_search_type == "ip":
                if parsed_ip is None:
                    raise ValueError("IP search requires a complete valid IPv4 or IPv6 address")
                canonical_ip = parsed_ip.compressed
                where.append("(m.ip=%s OR m.cmts_ip=%s)")
                params.extend([canonical_ip, canonical_ip])
                if not cmts:
                    index_hint_sql = (
                        " USE INDEX (idx_inv_ip_state, idx_inv_cmts_state)"
                    )
                    order_sql_override = "m.mac ASC"
            elif normalized_search_type == "mac":
                mac_compact = (
                    search_text.lower()
                    .replace(":", "")
                    .replace("-", "")
                    .replace(".", "")
                    .replace(" ", "")
                )
                if not 2 <= len(mac_compact) <= 12 or any(
                    character not in "0123456789abcdef" for character in mac_compact
                ):
                    raise ValueError("MAC search requires 2 to 12 hexadecimal characters")
                if len(mac_compact) == 12:
                    dotted = ".".join(
                        mac_compact[index:index + 4] for index in range(0, 12, 4)
                    )
                    where.append("m.mac IN (%s,%s,%s)")
                    params.extend([formatted_mac, mac_compact, dotted])
                else:
                    mac_prefix = ":".join(
                        mac_compact[index:index + 2]
                        for index in range(0, len(mac_compact), 2)
                    )
                    where.append("m.mac LIKE %s")
                    params.append(mac_prefix + "%")
                    total_exact = False
                index_hint_sql = " FORCE INDEX (PRIMARY)"
                order_sql_override = "m.mac ASC"
            elif normalized_search_type in {
                "vendor",
                "model",
                "software",
                "docsis",
                "fiber_node",
            }:
                if len(search_text) < 2:
                    raise ValueError("Prefix search requires at least 2 characters")
                search_columns = {
                    "vendor": ("vendor", "idx_inv_vendor"),
                    "model": ("model", "idx_inv_model"),
                    "software": ("software_version", "idx_inv_software_version"),
                    "docsis": ("docsis_version", "idx_inv_docsis_version"),
                    "fiber_node": ("fiber_node", "idx_inv_fiber_node"),
                }
                column, index_name = search_columns[normalized_search_type]
                where.append(f"m.{column} LIKE %s ESCAPE '='")
                params.append(literal_like_pattern(search_text))
                total_exact = False
                if not cmts:
                    index_hint_sql = f" FORCE INDEX ({index_name})"
                    order_sql_override = f"m.{column} ASC, m.mac ASC"
            elif normalized_search_type == "name":
                if not cmts:
                    raise ValueError("All-server name search requires a selected CCAP")
                prefix_value = literal_like_pattern(search_text)
                where.append(
                    "(m.vendor LIKE %s ESCAPE '=' OR "
                    "m.model LIKE %s ESCAPE '=' OR "
                    "m.fiber_node LIKE %s ESCAPE '=')"
                )
                params.extend([prefix_value, prefix_value, prefix_value])
            else:
                if not cmts:
                    raise ValueError(
                        "All-server contains search requires a selected CCAP or "
                        "an explicit structured search field"
                    )
                sv = literal_like_pattern(search_text.lower(), contains=True)
                broad_columns = (
                    "m.mac",
                    "m.ip",
                    "m.cmts",
                    "m.cmts_ip",
                    "m.fiber_node",
                    "m.vendor",
                    "m.model",
                    "m.software_version",
                    "m.docsis_version",
                    "m.upstream_interface",
                    "m.cable_mac",
                )
                where.append(
                    "(" + " OR ".join(
                        f"LOWER(COALESCE({column},'')) LIKE %s ESCAPE '='"
                        for column in broad_columns
                    ) + ")"
                )
                params.extend([sv] * len(broad_columns))

        if interface_filter:
            if not cmts:
                raise ValueError("Interface filtering requires a selected CCAP")
            where.append(
                "(LOWER(COALESCE(m.upstream_interface,'')) LIKE %s ESCAPE '=' OR "
                "LOWER(COALESCE(m.cable_mac,'')) LIKE %s ESCAPE '=')"
            )
            interface_value = literal_like_pattern(
                str(interface_filter).lower(), contains=True
            )
            params.extend([interface_value, interface_value])

        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        from_sql = f"FROM modem_inventory_current m{index_hint_sql}"
        total: Optional[int] = None
        if total_exact:
            total_rows = self._query(
                f"SELECT COUNT(*) AS c {from_sql}{where_sql}",
                tuple(params),
            )
            total = int((total_rows[0] or {}).get("c") or 0) if total_rows else 0
        order_sql = order_sql_override or (
            "m.mac ASC"
            if cmts and cmts_column == "m.cmts_ip"
            else "m.cmts ASC, m.mac ASC"
        )
        query_limit = limit if total_exact else limit + 1
        rows = self._query(
            "SELECT m.mac, m.ip, m.cmts, m.cmts_ip, m.cmts_index, "
            "m.docsif3_index, m.fiber_node, m.cable_mac, m.mac_domain, m.status, "
            "m.docsis_version, m.vendor, m.model, m.upstream_interface, "
            "m.upstream_ifindex, m.ofdm_ifindex, m.ofdma_ifindex, "
            "m.ofdm_channel_count, m.ofdma_channel_count, m.ofdma_rf_port_ifindex, "
            "m.ofdm_enabled, m.ofdma_enabled, m.partial_service, "
            "m.partial_service_downstream, m.partial_service_upstream, "
            "m.partial_service_state, m.software_version, m.inventory_state, "
            "m.missing_since, m.consecutive_full_misses, m.retired_at, m.updated_at "
            f"{from_sql}{where_sql} "
            f"ORDER BY {order_sql} LIMIT %s OFFSET %s",
            tuple(params + [query_limit, offset]),
        )
        has_more_without_total = not total_exact and len(rows) > limit
        page_rows = rows[:limit]
        modems = [self._map_inventory_row(row) for row in page_rows]
        count = len(modems)
        has_more = (
            offset + count < int(total or 0)
            if total_exact
            else has_more_without_total
        )
        return {
            "modems": modems,
            "total": total,
            "total_exact": total_exact,
            "count": count,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": offset + count if has_more else None,
            "lifecycle_state": state,
            "area": normalized_area,
            "search_type": resolved_search_type,
        }

    def list_inventory_modems(
        self,
        cmts: Optional[str] = None,
        search_type: Optional[str] = None,
        search_value: Optional[str] = None,
        interface_filter: Optional[str] = None,
        lifecycle_state: str = "active",
        area: Optional[str] = "all",
        offset: int = 0,
        limit: int | None = None,
    ) -> List[Dict[str, Any]]:
        """Compatibility wrapper returning only the modem rows from one page."""
        return self.list_inventory_modems_page(
            cmts=cmts,
            search_type=search_type,
            search_value=search_value,
            interface_filter=interface_filter,
            lifecycle_state=lifecycle_state,
            area=area,
            offset=offset,
            limit=limit,
        )["modems"]

    def list_inventory_interface_choices(self, cmts: str) -> Dict[str, List[str]]:
        """Return active-only distinct interface labels for one CMTS."""
        cmts_value = str(cmts or "").strip()
        if not cmts_value:
            raise ValueError("cmts is required")
        try:
            ipaddress.ip_address(cmts_value)
            cmts_column = "cmts_ip"
        except ValueError:
            cmts_column = "cmts"
        rows = self._query(
            "SELECT choice_type, choice_value FROM ("
            "SELECT 'upstream_interface' AS choice_type, "
            "TRIM(upstream_interface) AS choice_value "
            "FROM modem_inventory_current WHERE inventory_state='active' "
            f"AND {cmts_column}=%s AND COALESCE(TRIM(upstream_interface),'')<>'' "
            "GROUP BY TRIM(upstream_interface) UNION ALL "
            "SELECT 'cable_mac' AS choice_type, TRIM(cable_mac) AS choice_value "
            "FROM modem_inventory_current WHERE inventory_state='active' "
            f"AND {cmts_column}=%s AND COALESCE(TRIM(cable_mac),'')<>'' "
            "GROUP BY TRIM(cable_mac)) choices "
            "ORDER BY choice_type, choice_value",
            (cmts_value, cmts_value),
        )
        upstream_interfaces = [
            str(row.get("choice_value"))
            for row in rows
            if row.get("choice_type") == "upstream_interface"
        ]
        cable_macs = [
            str(row.get("choice_value"))
            for row in rows
            if row.get("choice_type") == "cable_mac"
        ]
        return {
            "upstream_interfaces": upstream_interfaces,
            "cable_macs": cable_macs,
        }

    def get_inventory_modem_by_mac(self, mac_address: str) -> Optional[Dict[str, Any]]:
        marker = "%s"
        formatted = self._normalize_mac(mac_address)
        if len(formatted) != 17:
            return None
        compact = formatted.replace(":", "")
        dotted = ".".join(compact[i:i+4] for i in range(0, 12, 4))
        rows = self._query(
            "SELECT mac, ip, cmts, cmts_ip, cmts_index, docsif3_index, "
            "fiber_node, cable_mac, mac_domain, status, docsis_version, vendor, model, "
            "upstream_interface, upstream_ifindex, ofdm_ifindex, ofdma_ifindex, "
            "ofdm_channel_count, ofdma_channel_count, ofdma_rf_port_ifindex, "
            "ofdm_enabled, ofdma_enabled, partial_service, partial_service_downstream, "
            "partial_service_upstream, partial_service_state, software_version, "
            "inventory_state, missing_since, consecutive_full_misses, retired_at, updated_at "
            f"FROM modem_inventory_current WHERE inventory_state='active' "
            f"AND mac IN ({marker}, {marker}, {marker}) "
            f"ORDER BY FIELD(mac, {marker}, {marker}, {marker}) LIMIT 1",
            (formatted, compact, dotted, formatted, compact, dotted),
        )
        if not rows:
            return None
        modem = self._map_inventory_row(rows[0])
        cpe_rows = self._query(
            "SELECT address_family, ip_address, prefix_length "
            "FROM modem_cpe_ip_current WHERE modem_mac=%s AND cmts_ip=%s "
            "ORDER BY address_family, ip_address, prefix_length",
            (
                str(rows[0].get('mac') or '').lower(),
                str(rows[0].get('cmts_ip') or ''),
            ),
        )
        modem['cpe_ipv4'] = [
            {'address': row.get('ip_address'), 'prefix_length': row.get('prefix_length')}
            for row in cpe_rows if row.get('address_family') == 'ipv4'
        ]
        modem['cpe_ipv6'] = [
            {'address': row.get('ip_address'), 'prefix_length': row.get('prefix_length')}
            for row in cpe_rows if row.get('address_family') == 'ipv6'
        ]
        return modem

    def list_cpe_index(self, limit: int = 500000) -> Dict[str, Any]:
        capped = max(1, min(int(limit or 500000), 500000))
        rows = self._query(
            "SELECT c.ip_address, c.address_family, c.modem_mac "
            "FROM modem_cpe_ip_current c JOIN modem_inventory_current m "
            "ON m.mac=c.modem_mac AND m.cmts_ip=c.cmts_ip "
            "WHERE m.inventory_state='active' LIMIT %s",
            (capped + 1,),
        )
        return {
            'rows': rows[:capped],
            'row_count': len(rows[:capped]),
            'truncated': len(rows) > capped,
        }

    def suggest_cpe_addresses(self, query: str, limit: int = 10) -> List[str]:
        normalized = self.normalize_cpe_suggestion(query)
        capped = max(1, min(int(limit or 10), 50))
        comparator = 'LIKE %s' if normalized['prefix'] else '= %s'
        value = normalized['value'] + '%' if normalized['prefix'] else normalized['value']
        rows = self._query(
            "SELECT DISTINCT c.ip_address FROM modem_cpe_ip_current c "
            "JOIN modem_inventory_current m ON m.mac=c.modem_mac "
            "AND m.cmts_ip=c.cmts_ip "
            f"WHERE m.inventory_state='active' AND c.address_family=%s "
            f"AND c.ip_address {comparator} "
            "ORDER BY c.ip_address LIMIT %s",
            (normalized['family'], value, capped),
        )
        return [str(row.get('ip_address')) for row in rows if row.get('ip_address')]

    def get_inventory_modems_bulk(self, mac_addresses: list[str]) -> list[Dict[str, Any]]:
        """Look up multiple modems by MAC address using a single indexed query."""
        if not mac_addresses:
            return []
        # Normalize to colon-separated lowercase (matches PRIMARY KEY format)
        def _norm(mac: str) -> str:
            raw = (mac or "").strip().lower().replace("-", "").replace(".", "").replace(":", "")
            if len(raw) == 12:
                return ":".join(raw[i:i+2] for i in range(0, 12, 2))
            return raw
        normalized = [_norm(m) for m in mac_addresses if m]
        if not normalized:
            return []
        # Batch into chunks of 500 to avoid overly long IN clauses
        results: list[Dict[str, Any]] = []
        for i in range(0, len(normalized), 500):
            batch = normalized[i:i+500]
            placeholders = ",".join(["%s"] * len(batch))
            rows = self._query(
                "SELECT mac, ip, cmts, cmts_ip, cmts_index, docsif3_index, "
                "fiber_node, cable_mac, mac_domain, status, docsis_version, vendor, model, "
                "upstream_interface, upstream_ifindex, ofdm_ifindex, ofdma_ifindex, "
                "ofdm_channel_count, ofdma_channel_count, ofdma_rf_port_ifindex, "
                "ofdm_enabled, ofdma_enabled, partial_service, partial_service_downstream, "
                "partial_service_upstream, partial_service_state, software_version, "
            "inventory_state, missing_since, consecutive_full_misses, retired_at, updated_at "
                f"FROM modem_inventory_current WHERE inventory_state='active' "
                f"AND mac IN ({placeholders})",
                tuple(batch),
            )
            results.extend(self._map_inventory_row(r) for r in rows)
        return results

    def clear_inventory_modems(self, cmts: Optional[str] = None, cmts_ip: Optional[str] = None) -> int:
        """Delete inventory rows scoped to a CMTS hostname and/or IP."""
        cmts_name = str(cmts or "").strip()
        cmts_addr = str(cmts_ip or "").strip()
        if not cmts_name and not cmts_addr:
            return 0

        where_parts: list[str] = []
        params: list[Any] = []
        marker = "%s"
        if cmts_name:
            where_parts.append(f"LOWER(COALESCE(cmts,'')) = LOWER({marker})")
            params.append(cmts_name)
        if cmts_addr:
            where_parts.append(f"LOWER(COALESCE(cmts_ip,'')) = LOWER({marker})")
            params.append(cmts_addr)

        where_sql = " OR ".join(where_parts)
        before_rows = self._query(
            f"SELECT COUNT(*) AS c FROM modem_inventory_current WHERE {where_sql}",
            tuple(params),
        )
        before_count = int((before_rows[0] or {}).get("c") or 0) if before_rows else 0
        if before_count > 0:
            cpe_where: list[str] = []
            cpe_params: list[Any] = []
            if cmts_name:
                cpe_where.append(
                    "EXISTS (SELECT 1 FROM modem_inventory_current m "
                    "WHERE m.mac=modem_cpe_ip_current.modem_mac "
                    "AND LOWER(m.cmts)=LOWER(%s))"
                )
                cpe_params.append(cmts_name)
            if cmts_addr:
                cpe_where.append("cmts_ip=%s")
                cpe_params.append(cmts_addr)
            if cpe_where:
                self._execute(
                    f"DELETE FROM modem_cpe_ip_current WHERE {' OR '.join(cpe_where)}",
                    tuple(cpe_params),
                )
            self._execute(
                f"DELETE FROM modem_inventory_current WHERE {where_sql}",
                tuple(params),
            )
        summary_rows = self._query(
            f"SELECT cmts_ip FROM inventory_summary_status WHERE {where_sql}",
            tuple(params),
        )
        summary_cmts_ips = {
            str(row.get("cmts_ip") or "").strip()
            for row in summary_rows
            if str(row.get("cmts_ip") or "").strip()
        }
        if cmts_addr:
            summary_cmts_ips.add(cmts_addr)
        if summary_cmts_ips:
            placeholders = ",".join(["%s"] * len(summary_cmts_ips))
            self._execute(
                f"DELETE FROM inventory_summary_count "
                f"WHERE cmts_ip IN ({placeholders})",
                tuple(sorted(summary_cmts_ips)),
            )
        self._execute(
            f"DELETE FROM inventory_summary_status WHERE {where_sql}",
            tuple(params),
        )
        self._execute(
            f"DELETE FROM cmts_inventory_snapshot WHERE {where_sql}",
            tuple(params),
        )
        return before_count

    def _map_inventory_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        def _to_bool(value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off", ""}:
                return False
            return bool(value)

        return {
            "mac_address": row.get("mac"),
            "ip_address": row.get("ip"),
            "cmts": row.get("cmts"),
            "cmts_ip": row.get("cmts_ip"),
            "cmts_index": row.get("cmts_index"),
            "docsif3_index": row.get("docsif3_index"),
            "fiber_node": row.get("fiber_node"),
            "cable_mac": row.get("cable_mac"),
            "mac_domain": row.get("mac_domain"),
            "status": row.get("status"),
            "docsis_version": row.get("docsis_version"),
            "vendor": row.get("vendor"),
            "model": row.get("model"),
            "upstream_interface": row.get("upstream_interface"),
            "upstream_ifindex": row.get("upstream_ifindex"),
            "ofdm_ifindex": row.get("ofdm_ifindex"),
            "ofdma_ifindex": row.get("ofdma_ifindex"),
            "ofdm_channel_count": row.get("ofdm_channel_count"),
            "ofdma_channel_count": row.get("ofdma_channel_count"),
            "ofdma_rf_port_ifindex": row.get("ofdma_rf_port_ifindex"),
            "ofdm_enabled": _to_bool(row.get("ofdm_enabled")),
            "ofdma_enabled": _to_bool(row.get("ofdma_enabled")),
            "partial_service": _to_bool(row.get("partial_service")),
            "partial_service_downstream": _to_bool(row.get("partial_service_downstream")),
            "partial_service_upstream": _to_bool(row.get("partial_service_upstream")),
            "partial_service_state": row.get("partial_service_state"),
            "software_version": row.get("software_version"),
            "inventory_state": row.get("inventory_state") or "active",
            "missing_since": row.get("missing_since"),
            "consecutive_full_misses": int(row.get("consecutive_full_misses") or 0),
            "retired_at": row.get("retired_at"),
            "updated_at": row.get("updated_at"),
        }

    # ── Modem refresh (on-demand single-modem enrichment) ──────────

    def enqueue_modem_refresh(self, mac: str, cmts: str | None = None, requested_by: str | None = None) -> int:
        normalized_mac = self._normalize_mac(mac)
        if not normalized_mac:
            return 0
        # Dedupe: if there's already a queued/running refresh for this modem, reuse it.
        existing = self._query(
            "SELECT id FROM modem_refresh_request "
            "WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = LOWER(%s) "
            "AND status IN ('queued','running') ORDER BY id DESC LIMIT 1",
            (normalized_mac.replace(":", "").replace("-", ""),),
        )
        if existing:
            return int((existing[0] or {}).get("id") or 0)

        now = self._now()
        inserted = int(
            self._execute(
                "INSERT IGNORE INTO modem_refresh_request "
                "(mac, cmts, status, requested_by, created_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (normalized_mac, cmts, "queued", requested_by or "api", now),
            ) or 0
        )
        if inserted:
            return inserted
        existing = self._query(
            "SELECT id FROM modem_refresh_request WHERE active_key=%s LIMIT 1",
            (normalized_mac,),
        )
        return int((existing[0] or {}).get("id") or 0) if existing else 0

    def get_refresh_status(self, mac: str) -> dict | None:
        mac_norm = self._normalize_mac(mac).replace(":", "").replace("-", "")
        rows = self._query(
            "SELECT id, mac, cmts, status, error_text, attempt_count, "
            "next_attempt_at, last_attempt_at, created_at, started_at, finished_at, "
            "agent_task_id, agent_id, dispatched_at, dispatch_deadline_at, "
            "response_received_at "
            "FROM modem_refresh_request "
            "WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = LOWER(%s) "
            "ORDER BY id DESC LIMIT 1",
            (mac_norm,),
        )
        return rows[0] if rows else None

    def cancel_refresh_request(self, req_id: int) -> bool:
        now = self._now()
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                cur.execute(
                    "SELECT status, requested_by FROM modem_refresh_request "
                    "WHERE id=%s FOR UPDATE",
                    (int(req_id),),
                )
                request = cur.fetchone() or {}
                if str(request.get("status") or "").lower() not in {
                    "queued",
                    "running",
                }:
                    conn.rollback()
                    return False
                cur.execute(
                    "UPDATE modem_refresh_request SET status='cancelled', "
                    "finished_at=%s WHERE id=%s AND status IN ('queued','running')",
                    (now, int(req_id)),
                )
                if int(cur.rowcount or 0) != 1:
                    conn.rollback()
                    return False
                if request.get("requested_by") == _IDENTITY_REQUEST_SOURCE:
                    cur.execute(
                        "DELETE FROM modem_refresh_request WHERE id=%s "
                        "AND requested_by=%s AND status='cancelled'",
                        (int(req_id), _IDENTITY_REQUEST_SOURCE),
                    )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _resolve_modem_from_cmts(self, mac: str, cmts_name: str | None, base: str) -> Dict[str, Any] | None:
        """Fallback live lookup that never mutates authoritative inventory."""
        if not cmts_name:
            return None
        try:
            cmts_ip = str(ipaddress.ip_address(cmts_name))
        except ValueError:
            # Resolve a hostname or inventory identifier by either stored CMTS
            # name or address.
            rows = self._query(
                "SELECT cmts_ip FROM modem_inventory_current "
                "WHERE inventory_state='active' AND "
                "(LOWER(cmts)=LOWER(%s) OR LOWER(cmts_ip)=LOWER(%s)) "
                "AND cmts_ip IS NOT NULL LIMIT 1",
                (cmts_name, cmts_name),
            )
            cmts_ip = (rows[0] or {}).get("cmts_ip") if rows else None
        if not cmts_ip:
            return None
        query_payload = {
            "cmts_ip": cmts_ip,
            "refresh": True,
            "enrich": False,
            "agent_priority": "bulk",
            "limit": self._cm_modem_limit_default(),
        }
        try:
            r = requests.post(
                f"{base}/cmts/modems/query",
                json=query_payload,
                timeout=120,
                verify=False,
            )
            r.raise_for_status()
            payload = r.json() if r.content else {}
            if payload.get("success") is not True:
                raise RuntimeError(
                    payload.get("error") or f"CMTS refresh failed for {cmts_ip}"
                )
            modems = payload.get("modems") or []
            mac_norm = mac.lower().replace(":", "").replace("-", "")
            for m in modems:
                m_mac = str(m.get("mac_address") or "").lower().replace(":", "").replace("-", "")
                if m_mac == mac_norm:
                    out = dict(m)
                    out["cmts_ip"] = cmts_ip
                    out["cmts"] = cmts_name
                    return out
        except Exception as exc:
            logger.warning("Live CMTS walk fallback for %s failed: %s", mac, exc)
        return None

    def _resolve_modem_ip_from_cmts(self, mac: str, cmts_name: str | None, base: str) -> str | None:
        modem = self._resolve_modem_from_cmts(mac, cmts_name, base)
        return (modem or {}).get("ip_address")

    def _resolve_cmts_interface_from_cmts(
        self,
        modem: Dict[str, Any] | None,
        base: str,
    ) -> Dict[str, str | None]:
        """Resolve one modem's CMTS interface, Fiber Node, and DOCSIS version."""
        existing = {
            "cable_mac": (modem or {}).get("cable_mac"),
            "fiber_node": (modem or {}).get("fiber_node"),
            "docsis_version": (modem or {}).get("docsis_version"),
        }
        if not modem:
            return existing
        if (
            existing["cable_mac"]
            and existing["fiber_node"]
            and "4.0" in str(existing["docsis_version"] or "")
        ):
            return existing

        cmts_ip = str(modem.get("cmts_ip") or "").strip()
        docsif3_index = str(modem.get("docsif3_index") or "").strip()
        if not cmts_ip or not docsif3_index:
            return existing
        try:
            docsif3_index_value = int(docsif3_index)
        except (TypeError, ValueError):
            return existing
        if docsif3_index_value <= 0:
            return existing

        query_payload = {
            "cmts_ip": cmts_ip,
            "docsif3_index": docsif3_index_value,
        }
        response = requests.post(
            f"{base}/cmts/modem-interface/query",
            json=query_payload,
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        if payload.get("error"):
            logger.warning(
                "Targeted CMTS interface lookup for %s returned: %s",
                modem.get("mac_address") or modem.get("mac") or docsif3_index,
                payload.get("error"),
            )

        discovered_version = payload.get("docsis_version")
        docsis_version = self._stronger_docsis_version(
            existing["docsis_version"],
            discovered_version,
        )
        return {
            "cable_mac": payload.get("cable_mac") or existing["cable_mac"],
            "fiber_node": payload.get("fiber_node") or existing["fiber_node"],
            "docsis_version": docsis_version,
        }

    @staticmethod
    def _stronger_docsis_version(
        current: Any,
        discovered: Any,
    ) -> str | None:
        """Return the strongest normalized DOCSIS version without downgrading."""
        version_rank = {
            "DOCSIS 1.0": 10,
            "DOCSIS 1.1": 11,
            "DOCSIS 2.0": 20,
            "DOCSIS 3.0": 30,
            "DOCSIS 3.1": 31,
            "DOCSIS 4.0": 40,
        }
        current_value = str(current or "").strip() or None
        discovered_value = str(discovered or "").strip() or None
        if version_rank.get(discovered_value, 0) > version_rank.get(current_value, 0):
            return discovered_value
        return current_value

    @staticmethod
    def _parse_docsis_capability(value: Any) -> str | None:
        """Parse a ClabsDocsisVersion scalar returned by a modem SNMP agent."""
        text = str(value or "").strip()
        match = re.search(r"(?:^|\D)([0-6])\D*$", text)
        if not match:
            return None
        return {
            1: "DOCSIS 1.0",
            2: "DOCSIS 1.1",
            3: "DOCSIS 2.0",
            4: "DOCSIS 3.0",
            5: "DOCSIS 3.1",
            6: "DOCSIS 4.0",
        }.get(int(match.group(1)))

    @staticmethod
    def _clean_identity_value(value: Any) -> str | None:
        text = str(value or "").strip()
        text = re.sub(
            r"^(?:STRING|INTEGER|Gauge32|Counter32|Counter64|OID|Hex-STRING|IpAddress):\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip().strip('"').strip()
        lowered = text.lower()
        missing = {
            "",
            "unknown",
            "n/a",
            "(unknown)",
            "none",
            "null",
            "not available",
        }
        if (
            lowered in missing
            or re.fullmatch(r"0+(?:\.0+)*", lowered) is not None
            or any(marker in lowered for marker in ("no such", "timeout", "unknown object"))
        ):
            return None
        return text

    @staticmethod
    def _stored_identity_value(value: Any) -> str | None:
        text = str(value or "").strip()
        lowered = text.lower()
        if (
            lowered
            in {
                "",
                "unknown",
                "n/a",
                "(unknown)",
                "none",
                "null",
                "not available",
                "0",
            }
            or re.fullmatch(r"0+(?:\.0+)*", lowered) is not None
            or any(marker in lowered for marker in ("no such", "timeout", "unknown object"))
        ):
            return None
        return text

    @classmethod
    def _summary_identity_value(cls, value: Any) -> str:
        return cls._stored_identity_value(value) or "(unknown)"

    @classmethod
    def _extract_agent_oid_value(cls, oid_results: Dict[str, Any], oid: str) -> str | None:
        result = oid_results.get(oid) or oid_results.get(oid.lstrip("."))
        if not isinstance(result, dict) or result.get("success") is not True:
            return None
        value = result.get("value")
        if value is None and isinstance(result.get("results"), list) and result["results"]:
            value = result["results"][0].get("value")
        if value is None and result.get("output") is not None:
            output = str(result["output"])
            value = output.split(" = ", 1)[1] if " = " in output else output
        return cls._clean_identity_value(value)

    @classmethod
    def _parse_modem_identity(
        cls,
        sys_descr: str | None,
        firmware: str | None,
    ) -> Dict[str, str | None]:
        description = cls._clean_identity_value(sys_descr) or ""
        parsed: Dict[str, str | None] = {
            "vendor": None,
            "model": None,
            "software_version": cls._clean_identity_value(firmware),
        }
        structured = re.search(r"<<(.+?)>>", description)
        if structured:
            fields: Dict[str, str] = {}
            for pair in structured.group(1).split(";"):
                if ":" not in pair:
                    continue
                key, value = pair.split(":", 1)
                cleaned = cls._clean_identity_value(value)
                if cleaned:
                    fields[key.strip().upper()] = cleaned
            parsed["vendor"] = fields.get("VENDOR")
            parsed["model"] = fields.get("MODEL") or fields.get("HW_MODEL")
            parsed["software_version"] = (
                parsed["software_version"] or fields.get("SW_REV")
            )

        if not parsed["vendor"] and description:
            from pypnm.lib.vendor_capabilities import get_vendor_from_sysdescr

            parsed["vendor"] = cls._clean_identity_value(
                get_vendor_from_sysdescr(description)
            )
        if not parsed["model"] and description:
            model_match = re.search(
                r"(FAST\d+|F\d{4}[A-Z]*|TG\d+[A-Z0-9-]*|TC\d+|SBG?\d+|"
                r"DPC\d+|EPC\d+|CGM\d+|CH\d+[A-Z0-9-]*|UBC\d+[A-Z0-9-]*)",
                description,
                re.IGNORECASE,
            )
            if model_match:
                parsed["model"] = model_match.group(1).upper()
        if not parsed["software_version"] and description:
            version_match = re.search(
                r"\b\d+\.\d+(?:\.\d+)+(?:[-._][A-Za-z0-9.-]+)?\b",
                description,
            )
            if version_match:
                parsed["software_version"] = version_match.group(0)
        return parsed

    def query_modem_identity(self, mac: str) -> Dict[str, Any]:
        """Query identity only for a modem and target in active Inventory."""
        normalized_mac = self._normalize_mac(mac)
        if not normalized_mac:
            raise ValueError("A valid modem MAC address is required")
        modem = self.get_inventory_modem_by_mac(normalized_mac)
        if not modem:
            raise ValueError(f"Modem {normalized_mac} is not in active inventory")
        modem_ip = str(modem.get("ip_address") or modem.get("ip") or "").strip()
        try:
            normalized_ip = str(ipaddress.ip_address(modem_ip))
        except ValueError as exc:
            raise ValueError(
                f"Modem {normalized_mac} has no valid Inventory management IP"
            ) from exc

        from pypnm.api.agent.manager import get_agent_manager

        agent_manager = get_agent_manager()
        if not agent_manager:
            raise RuntimeError("Agent manager is unavailable")
        agent = None
        agent_token: tuple[str, int] | None = None
        with self._identity_agent_lock:
            capable_agent_ids = agent_manager.get_all_agent_ids_for_capability(
                "cm_reachable"
            )
            for _ in capable_agent_ids:
                agent_id = agent_manager.get_agent_id_for_capability("cm_reachable")
                if not agent_id:
                    break
                candidate = agent_manager.get_agent(agent_id)
                if not candidate:
                    continue
                token = (candidate.agent_id, id(candidate.websocket))
                self._identity_blocked_agents = {
                    blocked
                    for blocked in self._identity_blocked_agents
                    if blocked[0] != candidate.agent_id or blocked == token
                }
                if token not in self._identity_blocked_agents:
                    agent = candidate
                    agent_token = token
                    break
        if not agent or not agent_token:
            raise _IdentityDispatchBlocked(
                "Identity dispatch is paused until an available agent reconnects"
            )

        params = {
            "target_ip": normalized_ip,
            "oids": [
                _IDENTITY_SYSDESCR_OID,
                _IDENTITY_FIRMWARE_OID,
                _IDENTITY_DOCSIS_CAPABILITY_OID,
            ],
            "target_role": "cm",
            "timeout": 5,
            "retries": 1,
            "max_concurrent": 1,
        }
        result = agent_manager.send_task_and_wait(
            agent.agent_id,
            "snmp_bulk_get",
            params,
            timeout=70,
            priority="bulk",
        )
        if not result or result.get("type") != "response":
            error = str((result or {}).get("error") or "Agent identity task timed out")
            if "timeout" in error.lower():
                with self._identity_agent_lock:
                    self._identity_blocked_agents.add(agent_token)
            raise RuntimeError(error)
        response = result.get("result") or {}
        if response.get("success") is not True:
            raise RuntimeError(response.get("error") or "Agent identity task failed")
        oid_results = response.get("results") or {}
        sys_descr = self._extract_agent_oid_value(
            oid_results,
            _IDENTITY_SYSDESCR_OID,
        )
        firmware = self._extract_agent_oid_value(
            oid_results,
            _IDENTITY_FIRMWARE_OID,
        )
        docsis_capability = self._extract_agent_oid_value(
            oid_results,
            _IDENTITY_DOCSIS_CAPABILITY_OID,
        )
        identity = self._parse_modem_identity(sys_descr, firmware)
        docsis_version = self._parse_docsis_capability(docsis_capability)
        if not any(identity.values()) and not docsis_version:
            raise RuntimeError("Modem returned no usable identity or capability values")
        return {
            "success": True,
            "mac": normalized_mac,
            "modem_ip": normalized_ip,
            "cmts_ip": str(modem.get("cmts_ip") or "").strip(),
            "inventory_updated_at": modem.get("updated_at"),
            "sys_descr": sys_descr,
            "docsis_version": docsis_version,
            **identity,
        }

    def _identity_queue_depth(self) -> int:
        try:
            return max(
                128,
                min(
                    int(os.environ.get("DATA_STORE_IDENTITY_QUEUE_DEPTH", "1024")),
                    10000,
                ),
            )
        except (TypeError, ValueError):
            return 1024

    @staticmethod
    def _identity_max_in_flight() -> int:
        """Global bound for asynchronous modem identity tasks."""
        try:
            return max(
                16,
                min(
                    int(
                        os.environ.get(
                            "DATA_STORE_IDENTITY_MAX_IN_FLIGHT",
                            "96",
                        )
                    ),
                    512,
                ),
            )
        except (TypeError, ValueError):
            return 96

    @staticmethod
    def _identity_max_attempts() -> int:
        try:
            return max(
                1,
                min(int(os.environ.get("DATA_STORE_IDENTITY_MAX_ATTEMPTS", "4")), 10),
            )
        except (TypeError, ValueError):
            return 4

    @staticmethod
    def _identity_retry_delay(attempt_count: int) -> int:
        try:
            base = max(
                30,
                min(int(os.environ.get("DATA_STORE_IDENTITY_RETRY_BASE_SEC", "60")), 3600),
            )
        except (TypeError, ValueError):
            base = 60
        return min(base * (2 ** max(0, attempt_count - 1)), 21600)

    def _seed_identity_refresh_queue(self) -> int:
        """Keep a tiny durable queue fed by a persisted primary-key cursor."""
        enabled = os.environ.get(
            "DATA_STORE_IDENTITY_ENRICHMENT_ENABLED",
            "true",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return 0

        now = self._now()
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                stale_eligible = self._identity_eligible_sql("i")
                cur.execute(
                    "DELETE r FROM modem_refresh_request r "
                    "LEFT JOIN modem_inventory_current i ON i.mac=r.mac "
                    "WHERE r.status='queued' AND r.requested_by=%s "
                    f"AND (i.mac IS NULL OR NOT COALESCE(({stale_eligible}), FALSE))",
                    (_IDENTITY_REQUEST_SOURCE,),
                )
                cur.execute(
                    "SELECT COUNT(*) AS c FROM modem_refresh_request "
                    "WHERE status IN ('queued','running') AND requested_by=%s",
                    (_IDENTITY_REQUEST_SOURCE,),
                )
                active = int((cur.fetchone() or {}).get("c") or 0)
                available = self._identity_queue_depth() - active
                if available <= 0:
                    conn.commit()
                    return 0

                cur.execute(
                    "SELECT cursor_mac, next_scan_at FROM inventory_identity_cursor "
                    "WHERE id=1 FOR UPDATE"
                )
                state = cur.fetchone() or {}
                next_scan_at = state.get("next_scan_at")
                if next_scan_at and next_scan_at > datetime.now():
                    conn.commit()
                    return 0
                cursor_mac = str(state.get("cursor_mac") or "")
                eligible = self._identity_eligible_sql()
                enriched = self._inventory_enriched_sql()
                cur.execute(
                    "SELECT mac, cmts FROM modem_inventory_current "
                    f"WHERE mac>%s AND {eligible} AND NOT ({enriched}) "
                    "ORDER BY mac LIMIT %s",
                    (cursor_mac, available),
                )
                candidates = cur.fetchall()
                if not candidates:
                    try:
                        rescan_seconds = max(
                            300,
                            min(
                                int(
                                    os.environ.get(
                                        "DATA_STORE_IDENTITY_RESCAN_SEC",
                                        "86400",
                                    )
                                ),
                                604800,
                            ),
                        )
                    except (TypeError, ValueError):
                        rescan_seconds = 86400
                    next_scan = (
                        datetime.now() + timedelta(seconds=rescan_seconds)
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    cur.execute(
                        "UPDATE inventory_identity_cursor SET cursor_mac='', "
                        "cycle_started_at=%s, next_scan_at=%s, updated_at=%s "
                        "WHERE id=1",
                        (now, next_scan, now),
                    )
                    conn.commit()
                    return 0

                queued = 0
                owned_cursor = cursor_mac
                for row in candidates:
                    cur.execute(
                        "INSERT IGNORE INTO modem_refresh_request "
                        "(mac, cmts, status, requested_by, created_at) "
                        "VALUES (%s,%s,'queued',%s,%s)",
                        (row["mac"], row.get("cmts"), _IDENTITY_REQUEST_SOURCE, now),
                    )
                    if int(cur.rowcount or 0) == 1:
                        queued += 1
                        owned_cursor = row["mac"]
                        continue
                    cur.execute(
                        "SELECT id FROM modem_refresh_request WHERE active_key=%s "
                        "AND requested_by=%s AND status IN ('queued','running') "
                        "LIMIT 1 FOR UPDATE",
                        (row["mac"], _IDENTITY_REQUEST_SOURCE),
                    )
                    if cur.fetchone():
                        owned_cursor = row["mac"]
                        continue
                    break

                if owned_cursor != cursor_mac:
                    cur.execute(
                        "UPDATE inventory_identity_cursor SET cursor_mac=%s, "
                        "next_scan_at=NULL, queued_count=queued_count+%s, updated_at=%s "
                        "WHERE id=1",
                        (owned_cursor, queued, now),
                    )
                conn.commit()
                return queued
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _identity_event_callback(self, event: dict) -> None:
        """Keep agent-loop callbacks nonblocking; DB work stays on the worker."""
        self._identity_events.put_nowait(dict(event))

    def _claim_next_identity_request(self, agent_id: str) -> Dict[str, Any] | None:
        """Durably claim one identity row and snapshot its dispatch target."""
        now = self._now()
        deadline = (
            datetime.now(timezone.utc) + timedelta(seconds=60)
        ).strftime("%Y-%m-%d %H:%M:%S")
        claim_token = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        eligible = self._identity_eligible_sql("i")
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                cur.execute(
                    "SELECT r.id, r.mac, r.cmts, r.attempt_count, "
                    "i.ip AS target_ip, "
                    "i.cmts_ip AS target_cmts_ip, i.updated_at AS target_updated_at "
                    "FROM modem_refresh_request r "
                    "JOIN modem_inventory_current i ON i.mac=r.mac "
                    "WHERE r.status='queued' AND r.requested_by=%s "
                    "AND (r.next_attempt_at IS NULL "
                    "OR r.next_attempt_at<=UTC_TIMESTAMP()) "
                    f"AND {eligible} "
                    "ORDER BY COALESCE(r.next_attempt_at, r.created_at), r.id "
                    "LIMIT 1 FOR UPDATE",
                    (_IDENTITY_REQUEST_SOURCE,),
                )
                request = cur.fetchone()
                if not request:
                    conn.rollback()
                    return None
                cur.execute(
                    "UPDATE modem_refresh_request SET status='running', "
                    "started_at=%s, finished_at=NULL, next_attempt_at=NULL, "
                    "claim_token=%s, agent_task_id=%s, agent_id=%s, "
                    "dispatched_at=NULL, dispatch_deadline_at=%s, "
                    "response_received_at=NULL, target_ip=%s, target_cmts_ip=%s, "
                    "target_inventory_updated_at=%s, error_text=NULL "
                    "WHERE id=%s AND status='queued' AND requested_by=%s",
                    (
                        now,
                        claim_token,
                        task_id,
                        agent_id,
                        deadline,
                        request.get("target_ip"),
                        request.get("target_cmts_ip"),
                        request.get("target_updated_at"),
                        int(request["id"]),
                        _IDENTITY_REQUEST_SOURCE,
                    ),
                )
                if int(cur.rowcount or 0) != 1:
                    conn.rollback()
                    return None
                conn.commit()
                claimed = dict(request)
                claimed.update(
                    {
                        "claim_token": claim_token,
                        "agent_task_id": task_id,
                        "agent_id": agent_id,
                    }
                )
                return claimed
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _dispatch_identity_tasks(self) -> int:
        """Fill available agent slots without waiting for task responses."""
        from pypnm.api.agent.manager import get_agent_manager

        manager = get_agent_manager()
        if not manager:
            return 0
        rows = self._query(
            "SELECT COUNT(*) AS c FROM modem_refresh_request "
            "WHERE status='running' AND requested_by=%s",
            (_IDENTITY_REQUEST_SOURCE,),
        )
        running = int((rows[0] or {}).get("c") or 0) if rows else 0
        available = self._identity_max_in_flight() - running
        dispatched = 0
        for _ in range(max(0, available)):
            agent_id = manager.get_agent_id_for_capability(
                "cm_reachable",
                priority="identity",
            )
            if not agent_id:
                break
            request = self._claim_next_identity_request(agent_id)
            if not request:
                break
            task_id = str(request["agent_task_id"])
            params = {
                "target_ip": str(request.get("target_ip") or "").strip(),
                "oids": [
                    _IDENTITY_SYSDESCR_OID,
                    _IDENTITY_FIRMWARE_OID,
                    _IDENTITY_DOCSIS_CAPABILITY_OID,
                ],
                "target_role": "cm",
                "timeout": 2,
                "retries": 0,
                "max_concurrent": 3,
                "allow_public_fallback": False,
            }
            try:
                manager.send_task_fire_and_forget(
                    agent_id,
                    "snmp_bulk_get",
                    params,
                    task_id=task_id,
                    callback=self._identity_event_callback,
                    timeout=45,
                    priority="identity",
                )
            except Exception as exc:
                self._identity_event_callback(
                    {
                        "type": "error",
                        "request_id": task_id,
                        "error": str(exc),
                        "terminal_reason": "send_failed",
                    }
                )
            dispatched += 1
        return dispatched

    def _expire_identity_dispatches(self) -> None:
        rows = self._query(
            "SELECT agent_task_id FROM modem_refresh_request "
            "WHERE status='running' AND requested_by=%s "
            "AND dispatch_deadline_at<=UTC_TIMESTAMP() "
            "AND agent_task_id IS NOT NULL LIMIT 512",
            (_IDENTITY_REQUEST_SOURCE,),
        )
        for row in rows:
            self._identity_event_callback(
                {
                    "type": "error",
                    "request_id": row.get("agent_task_id"),
                    "error": "Identity dispatch deadline expired",
                    "terminal_reason": "dispatch_timeout",
                }
            )

    def _acknowledge_identity_dispatch_cursor(
        self,
        cur,
        *,
        request: Dict[str, Any],
        now: str,
    ) -> bool:
        """Durably consume one attempt after the WebSocket send succeeds."""
        if request.get("dispatched_at"):
            return False
        deadline = (
            datetime.now(timezone.utc) + timedelta(seconds=60)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "UPDATE modem_refresh_request SET attempt_count=attempt_count+1, "
            "last_attempt_at=%s, dispatched_at=%s, dispatch_deadline_at=%s "
            "WHERE id=%s AND status='running' AND agent_task_id=%s "
            "AND claim_token=%s AND agent_id=%s AND dispatched_at IS NULL",
            (
                now,
                now,
                deadline,
                int(request["id"]),
                str(request.get("agent_task_id") or ""),
                str(request.get("claim_token") or ""),
                str(request.get("agent_id") or ""),
            ),
        )
        if int(cur.rowcount or 0) != 1:
            raise RuntimeError(
                f"Identity task {request.get('agent_task_id')} send acknowledgement "
                "lost ownership"
            )
        request["attempt_count"] = int(request.get("attempt_count") or 0) + 1
        request["dispatched_at"] = now
        request["dispatch_deadline_at"] = deadline
        return True

    def _transition_identity_failure_cursor(
        self,
        cur,
        *,
        request: Dict[str, Any],
        error_text: str,
        now: str,
    ) -> None:
        request_id = int(request["id"])
        task_id = str(request.get("agent_task_id") or "")
        claim_token = str(request.get("claim_token") or "")
        attempt_count = int(request.get("attempt_count") or 0)
        if not request.get("dispatched_at"):
            next_attempt_at = (
                datetime.now(timezone.utc) + timedelta(seconds=2)
            ).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                "UPDATE modem_refresh_request SET status='queued', "
                "started_at=NULL, finished_at=NULL, next_attempt_at=%s, "
                "claim_token=NULL, agent_task_id=NULL, agent_id=NULL, "
                "dispatched_at=NULL, dispatch_deadline_at=NULL, "
                "response_received_at=%s, error_text=%s "
                "WHERE id=%s AND status='running' AND agent_task_id=%s "
                "AND claim_token=%s AND dispatched_at IS NULL",
                (
                    next_attempt_at,
                    now,
                    error_text[:500],
                    request_id,
                    task_id,
                    claim_token,
                ),
            )
            return
        if attempt_count < self._identity_max_attempts():
            delay = self._identity_retry_delay(attempt_count)
            next_attempt_at = (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                "UPDATE modem_refresh_request SET status='queued', "
                "started_at=NULL, finished_at=NULL, next_attempt_at=%s, "
                "claim_token=NULL, agent_task_id=NULL, agent_id=NULL, "
                "dispatched_at=NULL, dispatch_deadline_at=NULL, "
                "response_received_at=%s, error_text=%s "
                "WHERE id=%s AND status='running' AND agent_task_id=%s "
                "AND claim_token=%s",
                (
                    next_attempt_at,
                    now,
                    error_text[:500],
                    request_id,
                    task_id,
                    claim_token,
                ),
            )
        else:
            cur.execute(
                "UPDATE modem_refresh_request SET status='failed', "
                "finished_at=%s, next_attempt_at=NULL, claim_token=NULL, "
                "dispatch_deadline_at=NULL, response_received_at=%s, "
                "error_text=%s WHERE id=%s AND status='running' "
                "AND agent_task_id=%s AND claim_token=%s",
                (
                    now,
                    now,
                    error_text[:500],
                    request_id,
                    task_id,
                    claim_token,
                ),
            )
            if int(cur.rowcount or 0) == 1:
                cur.execute(
                    "UPDATE inventory_identity_cursor SET "
                    "failed_count=failed_count+1, last_error=%s, updated_at=%s "
                    "WHERE id=1",
                    (error_text[:500], now),
                )

    def _apply_identity_task_event(self, event: dict) -> None:
        """Persist one asynchronous identity response or terminal transport error."""
        task_id = str(event.get("request_id") or "")
        if not task_id:
            return
        now = self._now()
        response_event = event.get("type") == "response"
        target = None
        if response_event:
            rows = self._query(
                "SELECT target_cmts_ip, cmts FROM modem_refresh_request "
                "WHERE agent_task_id=%s AND status='running'",
                (task_id,),
            )
            target = rows[0] if rows else None
            if not target:
                return
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                if response_event:
                    target_cmts_ip = str(
                        (target or {}).get("target_cmts_ip") or ""
                    ).strip()
                    target_cmts = str(
                        (target or {}).get("cmts") or target_cmts_ip
                    ).strip()
                    self._lock_inventory_snapshot_cursor(
                        cur,
                        cmts_ip=target_cmts_ip,
                        cmts=target_cmts or target_cmts_ip,
                        locked_at=now,
                    )
                cur.execute(
                    "SELECT id, mac, cmts, status, attempt_count, claim_token, "
                    "agent_task_id, agent_id, dispatched_at, dispatch_deadline_at, "
                    "target_ip, target_cmts_ip, target_inventory_updated_at "
                    "FROM modem_refresh_request "
                    "WHERE agent_task_id=%s FOR UPDATE",
                    (task_id,),
                )
                request = cur.fetchone()
                if not request or str(request.get("status") or "") != "running":
                    conn.rollback()
                    return

                event_type = str(event.get("type") or "")
                if event_type == "sent":
                    event_agent_id = str(event.get("agent_id") or "")
                    if event_agent_id != str(request.get("agent_id") or ""):
                        conn.rollback()
                        return
                    self._acknowledge_identity_dispatch_cursor(
                        cur,
                        request=request,
                        now=now,
                    )
                    conn.commit()
                    return

                if event_type != "response":
                    # An agent-originated error also proves that send_text
                    # completed. Manager transport failures carry a terminal
                    # reason and intentionally remain unacknowledged.
                    if not event.get("terminal_reason"):
                        self._acknowledge_identity_dispatch_cursor(
                            cur,
                            request=request,
                            now=now,
                        )
                    self._transition_identity_failure_cursor(
                        cur,
                        request=request,
                        error_text=str(event.get("error") or "Identity task failed"),
                        now=now,
                    )
                    conn.commit()
                    return

                # A response proves the command crossed the send boundary. This
                # also handles a very fast response arriving before its sent event.
                self._acknowledge_identity_dispatch_cursor(
                    cur,
                    request=request,
                    now=now,
                )
                response = event.get("result") or {}
                if response.get("success") is not True:
                    self._transition_identity_failure_cursor(
                        cur,
                        request=request,
                        error_text=str(response.get("error") or "Identity task failed"),
                        now=now,
                    )
                    conn.commit()
                    return
                oid_results = response.get("results") or {}
                sys_descr = self._extract_agent_oid_value(
                    oid_results,
                    _IDENTITY_SYSDESCR_OID,
                )
                firmware = self._extract_agent_oid_value(
                    oid_results,
                    _IDENTITY_FIRMWARE_OID,
                )
                docsis_value = self._extract_agent_oid_value(
                    oid_results,
                    _IDENTITY_DOCSIS_CAPABILITY_OID,
                )
                identity = self._parse_modem_identity(sys_descr, firmware)
                docsis_version = self._parse_docsis_capability(docsis_value)
                if not any(identity.values()) and not docsis_version:
                    self._transition_identity_failure_cursor(
                        cur,
                        request=request,
                        error_text="Modem returned no usable identity values",
                        now=now,
                    )
                    conn.commit()
                    return

                cmts_ip = str(request.get("target_cmts_ip") or "").strip()
                cmts = str(request.get("cmts") or cmts_ip).strip()
                cur.execute(
                    "SELECT inventory_state, ip, cmts, cmts_ip, status, updated_at, "
                    "vendor, model, software_version, docsis_version "
                    "FROM modem_inventory_current WHERE mac=%s AND cmts_ip=%s "
                    "FOR UPDATE",
                    (request.get("mac"), cmts_ip),
                )
                inventory = cur.fetchone()
                valid_statuses = {
                    "operational",
                    "registrationcomplete",
                    "ipcomplete",
                    "online",
                }
                if (
                    not inventory
                    or str(inventory.get("inventory_state") or "") != "active"
                    or str(inventory.get("ip") or "").strip()
                    != str(request.get("target_ip") or "").strip()
                    or inventory.get("updated_at")
                    != request.get("target_inventory_updated_at")
                    or str(inventory.get("status") or "").strip().lower()
                    not in valid_statuses
                ):
                    self._transition_identity_failure_cursor(
                        cur,
                        request=request,
                        error_text="Inventory target changed during identity query",
                        now=now,
                    )
                    conn.commit()
                    return

                before = {
                    "vendor": inventory.get("vendor"),
                    "model": inventory.get("model"),
                    "software_version": inventory.get("software_version"),
                    "docsis_version": inventory.get("docsis_version"),
                }
                after = {
                    "vendor": self._clean_identity_value(identity.get("vendor"))
                    or before["vendor"],
                    "model": self._clean_identity_value(identity.get("model"))
                    or before["model"],
                    "software_version": self._clean_identity_value(
                        identity.get("software_version")
                    )
                    or before["software_version"],
                    "docsis_version": self._stronger_docsis_version(
                        before["docsis_version"],
                        docsis_version,
                    ),
                }
                cur.execute(
                    "UPDATE modem_inventory_current SET "
                    "vendor=COALESCE(NULLIF(%s,''), vendor), "
                    "model=COALESCE(NULLIF(%s,''), model), "
                    "software_version=COALESCE(NULLIF(%s,''), software_version), "
                    "docsis_version=COALESCE(NULLIF(%s,''), docsis_version), "
                    "updated_at=%s WHERE mac=%s AND cmts_ip=%s "
                    "AND inventory_state='active'",
                    (
                        after["vendor"],
                        after["model"],
                        after["software_version"],
                        after["docsis_version"],
                        now,
                        request.get("mac"),
                        cmts_ip,
                    ),
                )
                self._apply_refresh_summary_delta_cursor(
                    cur,
                    cmts_ip=cmts_ip,
                    cmts=cmts or cmts_ip,
                    before=before,
                    after=after,
                    refreshed_at=now,
                )
                cur.execute(
                    "UPDATE cmts_inventory_snapshot SET revision_at="
                    "GREATEST(UTC_TIMESTAMP(), DATE_ADD(COALESCE(revision_at, "
                    "collected_at, '1970-01-01 00:00:00'), INTERVAL 1 SECOND)) "
                    "WHERE cmts_ip=%s",
                    (cmts_ip,),
                )
                if not self._identity_row_is_enriched(after):
                    self._transition_identity_failure_cursor(
                        cur,
                        request=request,
                        error_text=(
                            "Identity response did not include both vendor and firmware"
                        ),
                        now=now,
                    )
                    conn.commit()
                    return

                cur.execute(
                    "UPDATE modem_refresh_request SET status='completed', "
                    "finished_at=%s, response_received_at=%s, claim_token=NULL, "
                    "dispatch_deadline_at=NULL WHERE id=%s AND status='running' "
                    "AND agent_task_id=%s AND claim_token=%s",
                    (
                        now,
                        now,
                        int(request["id"]),
                        task_id,
                        request.get("claim_token"),
                    ),
                )
                if int(cur.rowcount or 0) != 1:
                    raise RuntimeError(
                        f"Identity task {task_id} completion lost ownership"
                    )
                cur.execute(
                    "UPDATE inventory_identity_cursor SET "
                    "completed_count=completed_count+1, last_error=NULL, "
                    "updated_at=%s WHERE id=1",
                    (now,),
                )
                cur.execute(
                    "DELETE FROM modem_refresh_request WHERE id=%s "
                    "AND requested_by=%s AND status='completed'",
                    (int(request["id"]), _IDENTITY_REQUEST_SOURCE),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _fetch_modem_identity(self, *, mac: str) -> Dict[str, Any]:
        payload = self.query_modem_identity(mac)
        if payload.get("success") is not True:
            raise RuntimeError(payload.get("error") or "Identity query failed")
        return {
            "vendor": self._clean_identity_value(payload.get("vendor")),
            "model": self._clean_identity_value(payload.get("model")),
            "software_version": self._clean_identity_value(
                payload.get("software_version")
            ),
            "docsis_version": self._stronger_docsis_version(
                None,
                payload.get("docsis_version"),
            ),
            "queried_ip": str(payload.get("modem_ip") or "").strip(),
            "queried_cmts_ip": str(payload.get("cmts_ip") or "").strip(),
            "inventory_updated_at": payload.get("inventory_updated_at"),
        }

    @classmethod
    def _identity_row_is_enriched(cls, row: Dict[str, Any]) -> bool:
        vendor = cls._stored_identity_value(row.get("vendor"))
        software = cls._stored_identity_value(row.get("software_version"))
        return vendor is not None and software is not None

    def _apply_refresh_summary_delta_cursor(
        self,
        cur,
        *,
        cmts_ip: str,
        cmts: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        refreshed_at: str,
    ) -> None:
        cur.execute(
            "SELECT cmts_ip FROM inventory_summary_status "
            "WHERE cmts_ip=%s FOR UPDATE",
            (cmts_ip,),
        )
        if not cur.fetchone():
            # The inventory update is already visible in this transaction, so a
            # full rebuild is both the repair and the post-update summary state.
            self._refresh_summary_for_cmts_cursor(
                cur,
                cmts_ip=cmts_ip,
                cmts=cmts or cmts_ip,
                refreshed_at=refreshed_at,
            )
            return

        changes: list[tuple[str, str, str]] = []
        for dimension in ("vendor", "model", "software_version", "docsis_version"):
            if dimension in {"vendor", "model", "software_version"}:
                old_value = self._summary_identity_value(before.get(dimension))
                new_value = self._summary_identity_value(after.get(dimension))
            else:
                old_value = str(before.get(dimension) or "").strip() or "(unknown)"
                new_value = str(after.get(dimension) or "").strip() or "(unknown)"
            if old_value == new_value:
                continue
            cur.execute(
                "SELECT row_count FROM inventory_summary_count "
                "WHERE cmts_ip=%s AND dimension=%s AND value=%s FOR UPDATE",
                (cmts_ip, dimension, old_value),
            )
            old_bucket = cur.fetchone() or {}
            if int(old_bucket.get("row_count") or 0) <= 0:
                self._refresh_summary_for_cmts_cursor(
                    cur,
                    cmts_ip=cmts_ip,
                    cmts=cmts or cmts_ip,
                    refreshed_at=refreshed_at,
                )
                return
            changes.append((dimension, old_value, new_value))

        for dimension, old_value, new_value in changes:
            cur.execute(
                "UPDATE inventory_summary_count SET row_count=row_count-1 "
                "WHERE cmts_ip=%s AND dimension=%s AND value=%s AND row_count>0",
                (cmts_ip, dimension, old_value),
            )
            if int(cur.rowcount or 0) != 1:
                raise RuntimeError(
                    "Identity summary bucket update lost a race for "
                    f"{cmts_ip}/{dimension}/{old_value}"
                )
            cur.execute(
                "DELETE FROM inventory_summary_count WHERE cmts_ip=%s "
                "AND dimension=%s AND value=%s AND row_count=0",
                (cmts_ip, dimension, old_value),
            )
            cur.execute(
                "INSERT INTO inventory_summary_count "
                "(cmts_ip, dimension, value, row_count) VALUES (%s,%s,%s,1) "
                "ON DUPLICATE KEY UPDATE row_count=row_count+1",
                (cmts_ip, dimension, new_value),
            )

        enriched_delta = int(self._identity_row_is_enriched(after)) - int(
            self._identity_row_is_enriched(before)
        )
        cur.execute(
            "UPDATE inventory_summary_status SET "
            "enriched_count=GREATEST(enriched_count+%s,0), "
            "last_updated=%s, refreshed_at=%s WHERE cmts_ip=%s",
            (enriched_delta, refreshed_at, refreshed_at, cmts_ip),
        )

    def _claim_next_refresh_request(self) -> Optional[Dict[str, Any]]:
        """Atomically lock and claim one due request for a refresh worker."""
        claim_at = self._now()
        claim_token = str(uuid.uuid4())
        with self._db_lock:
            conn = self._connect()
            try:
                conn.begin()
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, mac, cmts, requested_by "
                    "FROM modem_refresh_request WHERE status='queued' "
                    "AND COALESCE(requested_by,'')<>%s "
                    "AND (next_attempt_at IS NULL "
                    "OR next_attempt_at<=UTC_TIMESTAMP()) "
                    "ORDER BY COALESCE(next_attempt_at, created_at), id ASC "
                    "LIMIT 1 FOR UPDATE",
                    (_IDENTITY_REQUEST_SOURCE,),
                )
                req = cur.fetchone()
                if not req:
                    conn.rollback()
                    return None
                cur.execute(
                    "UPDATE modem_refresh_request SET status='running', "
                    "started_at=%s, finished_at=NULL, next_attempt_at=NULL, "
                    "last_attempt_at=%s, attempt_count=attempt_count+1, "
                    "claim_token=%s, error_text=NULL WHERE id=%s "
                    "AND status='queued' "
                    "AND (next_attempt_at IS NULL "
                    "OR next_attempt_at<=UTC_TIMESTAMP())",
                    (claim_at, claim_at, claim_token, int(req["id"])),
                )
                if int(cur.rowcount or 0) != 1:
                    conn.rollback()
                    return None
                conn.commit()
                claimed = dict(req)
                claimed["claim_token"] = claim_token
                return claimed
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _process_refresh_queue(self) -> None:
        """Atomically claim and process one queued modem refresh request."""
        req = self._claim_next_refresh_request()
        if not req:
            return
        req_id = int(req["id"])
        claim_token = str(req["claim_token"])
        mac = req["mac"]
        cmts = req.get("cmts")
        requested_by = str(req.get("requested_by") or "api")
        identity_only = requested_by == _IDENTITY_REQUEST_SOURCE
        try:
            base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
            modem = self.get_inventory_modem_by_mac(mac)
            if not modem:
                raise ValueError(
                    f"Modem {mac} is not in active inventory; "
                    "targeted refresh cannot discover or reactivate inventory rows"
                )

            cable_source = dict(modem)
            modem_ip = str(
                cable_source.get("ip_address") or cable_source.get("ip") or ""
            ).strip()
            if not modem_ip:
                raise ValueError(f"Modem {mac} has no management IP in inventory")

            identity = self._fetch_modem_identity(mac=mac)
            discovered_vendor = self._clean_identity_value(identity.get("vendor"))
            discovered_model = self._clean_identity_value(identity.get("model"))
            discovered_software = self._clean_identity_value(
                identity.get("software_version")
            )
            discovered_docsis_version = self._stronger_docsis_version(
                cable_source.get("docsis_version"),
                identity.get("docsis_version"),
            )
            queried_ip = str(identity.get("queried_ip") or "").strip()
            queried_cmts_ip = str(identity.get("queried_cmts_ip") or "").strip()
            queried_updated_at = identity.get("inventory_updated_at")
            if identity_only:
                vendor = discovered_vendor
                model_name = discovered_model
                software_ver = discovered_software
                interface_values = {
                    "cable_mac": None,
                    "fiber_node": None,
                    "docsis_version": discovered_docsis_version,
                }
            else:
                vendor = discovered_vendor or cable_source.get("vendor")
                model_name = discovered_model or cable_source.get("model")
                software_ver = (
                    discovered_software
                    or cable_source.get("software_version")
                    or cable_source.get("firmware")
                )
                interface_values = {
                    "cable_mac": cable_source.get("cable_mac"),
                    "fiber_node": cable_source.get("fiber_node"),
                    "docsis_version": discovered_docsis_version,
                }
                try:
                    interface_values = self._resolve_cmts_interface_from_cmts(
                        cable_source,
                        base,
                    )
                    interface_values["docsis_version"] = self._stronger_docsis_version(
                        interface_values.get("docsis_version"),
                        discovered_docsis_version,
                    )
                except Exception as exc:
                    logger.warning(
                        "Targeted CMTS interface lookup for %s failed: %s",
                        mac,
                        exc,
                    )
            cable_mac = interface_values.get("cable_mac")
            fiber_node = interface_values.get("fiber_node")
            docsis_version = interface_values.get("docsis_version")

            cmts_address = str(cable_source.get("cmts_ip") or "").strip()
            if identity_only:
                cmts_label = str(cable_source.get("cmts") or cmts_address).strip()
            else:
                cmts_label = str(
                    cmts or cable_source.get("cmts") or cmts_address
                ).strip()
            inventory_mac = str(
                cable_source.get("mac_address") or cable_source.get("mac") or mac
            )
            if not cmts_address:
                raise ValueError(f"Modem {mac} has no CMTS address in inventory")

            now = self._now()
            with self._db_lock:
                conn = self._connect()
                try:
                    conn.begin()
                    cur = conn.cursor()
                    self._lock_inventory_snapshot_cursor(
                        cur,
                        cmts_ip=cmts_address,
                        cmts=cmts_label or cmts_address,
                        locked_at=now,
                    )
                    cur.execute(
                        "SELECT inventory_state, ip, cmts, cmts_ip, status, updated_at, "
                        "vendor, model, software_version, docsis_version "
                        "FROM modem_inventory_current "
                        "WHERE mac=%s AND cmts_ip=%s FOR UPDATE",
                        (inventory_mac, cmts_address),
                    )
                    inventory_row = cur.fetchone()
                    if not inventory_row or str(
                        inventory_row.get("inventory_state") or ""
                    ) != "active":
                        raise ValueError(
                            f"Modem {mac} is no longer active inventory"
                        )
                    if identity_only:
                        try:
                            locked_ip = str(
                                ipaddress.ip_address(
                                    str(inventory_row.get("ip") or "").strip()
                                )
                            )
                        except ValueError as exc:
                            raise RuntimeError(
                                f"Modem {mac} Inventory target became invalid"
                            ) from exc
                        locked_status = str(
                            inventory_row.get("status") or ""
                        ).strip().lower()
                        target_changed = (
                            locked_ip != queried_ip
                            or str(inventory_row.get("cmts_ip") or "").strip()
                            != queried_cmts_ip
                            or inventory_row.get("updated_at") != queried_updated_at
                            or locked_status
                            not in {
                                "operational",
                                "registrationcomplete",
                                "ipcomplete",
                                "online",
                            }
                        )
                        if target_changed:
                            raise RuntimeError(
                                f"Modem {mac} Inventory changed during identity query"
                            )
                    cur.execute(
                        "SELECT status, attempt_count, claim_token "
                        "FROM modem_refresh_request WHERE id=%s FOR UPDATE",
                        (req_id,),
                    )
                    request_row = cur.fetchone() or {}
                    if (
                        str(request_row.get("status") or "") != "running"
                        or str(request_row.get("claim_token") or "") != claim_token
                    ):
                        raise RuntimeError(
                            f"Refresh request {req_id} is no longer owned by this worker"
                        )

                    identity_before = {
                        "vendor": inventory_row.get("vendor"),
                        "model": inventory_row.get("model"),
                        "software_version": inventory_row.get("software_version"),
                        "docsis_version": inventory_row.get("docsis_version"),
                    }
                    identity_after = {
                        "vendor": vendor or identity_before["vendor"],
                        "model": model_name or identity_before["model"],
                        "software_version": (
                            software_ver or identity_before["software_version"]
                        ),
                        "docsis_version": (
                            docsis_version or identity_before["docsis_version"]
                        ),
                    }

                    if identity_only:
                        cur.execute(
                            "UPDATE modem_inventory_current SET "
                            "vendor=COALESCE(NULLIF(%s,''), vendor), "
                            "model=COALESCE(NULLIF(%s,''), model), "
                            "software_version=COALESCE(NULLIF(%s,''), software_version), "
                            "docsis_version=COALESCE(NULLIF(%s,''), docsis_version), "
                            "updated_at=%s WHERE mac=%s AND cmts_ip=%s "
                            "AND inventory_state='active'",
                            (
                                vendor,
                                model_name,
                                software_ver,
                                docsis_version,
                                now,
                                inventory_mac,
                                cmts_address,
                            ),
                        )
                    elif (
                        vendor
                        or model_name
                        or software_ver
                        or cable_mac
                        or fiber_node
                        or docsis_version
                    ):
                        cur.execute(
                            "UPDATE modem_inventory_current SET "
                            "vendor=COALESCE(NULLIF(%s,''), vendor), "
                            "model=COALESCE(NULLIF(%s,''), model), "
                            "software_version=COALESCE(NULLIF(%s,''), software_version), "
                            "cable_mac=COALESCE(NULLIF(%s,''), cable_mac), "
                            "fiber_node=COALESCE(NULLIF(%s,''), fiber_node), "
                            "docsis_version=COALESCE(NULLIF(%s,''), docsis_version), "
                            "updated_at=%s WHERE mac=%s AND cmts_ip=%s "
                            "AND inventory_state='active'",
                            (
                                vendor,
                                model_name,
                                software_ver,
                                cable_mac,
                                fiber_node,
                                docsis_version,
                                now,
                                inventory_mac,
                                cmts_address,
                            ),
                        )
                    self._apply_refresh_summary_delta_cursor(
                        cur,
                        cmts_ip=cmts_address,
                        cmts=cmts_label or cmts_address,
                        before=identity_before,
                        after=identity_after,
                        refreshed_at=now,
                    )
                    cur.execute(
                        "UPDATE cmts_inventory_snapshot SET revision_at="
                        "GREATEST(UTC_TIMESTAMP(), DATE_ADD(COALESCE(revision_at, "
                        "collected_at, '1970-01-01 00:00:00'), INTERVAL 1 SECOND)) "
                        "WHERE cmts_ip=%s",
                        (cmts_address,),
                    )
                    if identity_only and not self._identity_row_is_enriched(
                        identity_after
                    ):
                        incomplete_error = (
                            "Identity response did not include both vendor and firmware"
                        )
                        attempt_count = int(request_row.get("attempt_count") or 0)
                        if attempt_count < self._identity_max_attempts():
                            next_attempt_at = (
                                datetime.now(timezone.utc)
                                + timedelta(
                                    seconds=self._identity_retry_delay(attempt_count)
                                )
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            cur.execute(
                                "UPDATE modem_refresh_request SET status='queued', "
                                "started_at=NULL, finished_at=NULL, "
                                "next_attempt_at=%s, claim_token=NULL, error_text=%s "
                                "WHERE id=%s AND status='running' "
                                "AND claim_token=%s",
                                (
                                    next_attempt_at,
                                    incomplete_error,
                                    req_id,
                                    claim_token,
                                ),
                            )
                            transitioned = int(cur.rowcount or 0)
                        else:
                            cur.execute(
                                "UPDATE modem_refresh_request SET status='failed', "
                                "finished_at=%s, next_attempt_at=NULL, "
                                "claim_token=NULL, error_text=%s "
                                "WHERE id=%s AND status='running' "
                                "AND claim_token=%s",
                                (now, incomplete_error, req_id, claim_token),
                            )
                            transitioned = int(cur.rowcount or 0)
                            if transitioned == 1:
                                cur.execute(
                                    "UPDATE inventory_identity_cursor SET "
                                    "failed_count=failed_count+1, last_error=%s, "
                                    "updated_at=%s WHERE id=1",
                                    (incomplete_error, now),
                                )
                        if transitioned != 1:
                            raise RuntimeError(
                                f"Refresh request {req_id} incomplete transition "
                                "lost a race"
                            )
                        conn.commit()
                        return

                    cur.execute(
                        "UPDATE modem_refresh_request SET status=%s, "
                        "finished_at=%s, claim_token=NULL WHERE id=%s "
                        "AND status='running' AND claim_token=%s",
                        ("completed", now, req_id, claim_token),
                    )
                    if int(cur.rowcount or 0) != 1:
                        raise RuntimeError(
                            f"Refresh request {req_id} completion lost a race"
                        )
                    if identity_only:
                        cur.execute(
                            "UPDATE inventory_identity_cursor SET "
                            "completed_count=completed_count+1, last_error=NULL, "
                            "updated_at=%s WHERE id=1",
                            (now,),
                        )
                        cur.execute(
                            "DELETE FROM modem_refresh_request WHERE id=%s "
                            "AND requested_by=%s AND status='completed'",
                            (req_id, _IDENTITY_REQUEST_SOURCE),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        except Exception as exc:
            error_text = str(exc)[:500]
            failed_at = self._now()
            with self._db_lock:
                conn = self._connect()
                try:
                    conn.begin()
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT status, attempt_count, claim_token "
                        "FROM modem_refresh_request WHERE id=%s FOR UPDATE",
                        (req_id,),
                    )
                    request = cur.fetchone() or {}
                    if (
                        str(request.get("status") or "") != "running"
                        or str(request.get("claim_token") or "") != claim_token
                    ):
                        conn.rollback()
                        return
                    attempt_count = int(request.get("attempt_count") or 0)
                    if identity_only and isinstance(exc, _IdentityDispatchBlocked):
                        next_attempt_at = (
                            datetime.now(timezone.utc) + timedelta(seconds=60)
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute(
                            "UPDATE modem_refresh_request SET status='queued', "
                            "attempt_count=GREATEST(attempt_count-1,0), "
                            "started_at=NULL, finished_at=NULL, next_attempt_at=%s, "
                            "claim_token=NULL, error_text=%s WHERE id=%s "
                            "AND status='running' AND claim_token=%s",
                            (next_attempt_at, error_text, req_id, claim_token),
                        )
                    elif identity_only and attempt_count < self._identity_max_attempts():
                        delay = self._identity_retry_delay(attempt_count)
                        next_attempt_at = (
                            datetime.now(timezone.utc) + timedelta(seconds=delay)
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        cur.execute(
                            "UPDATE modem_refresh_request SET status='queued', "
                            "started_at=NULL, finished_at=NULL, next_attempt_at=%s, "
                            "claim_token=NULL, error_text=%s WHERE id=%s "
                            "AND status='running' AND claim_token=%s",
                            (next_attempt_at, error_text, req_id, claim_token),
                        )
                    else:
                        cur.execute(
                            "UPDATE modem_refresh_request SET status='failed', "
                            "finished_at=%s, next_attempt_at=NULL, claim_token=NULL, "
                            "error_text=%s WHERE id=%s AND status='running' "
                            "AND claim_token=%s",
                            (failed_at, error_text, req_id, claim_token),
                        )
                        if identity_only and int(cur.rowcount or 0) == 1:
                            cur.execute(
                                "UPDATE inventory_identity_cursor SET "
                                "failed_count=failed_count+1, last_error=%s, "
                                "updated_at=%s WHERE id=1",
                                (error_text, failed_at),
                            )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

    # ── Enrichment progress ──────────────────────────────────────

    def get_enrichment_progress(self, cmts: str | None = None) -> dict:
        scope_sql = ""
        scope_params: list = []
        if cmts:
            scope_sql = (
                " AND (LOWER(COALESCE(cmts,''))=LOWER(%s) "
                "OR LOWER(COALESCE(cmts_ip,''))=LOWER(%s))"
            )
            scope_params = [cmts, cmts]

        inventory_rows = self._query(
            "SELECT COUNT(*) AS c FROM modem_inventory_current "
            "WHERE inventory_state='active'" + scope_sql,
            tuple(scope_params),
        )
        inventory_total = (
            int((inventory_rows[0] or {}).get("c") or 0) if inventory_rows else 0
        )
        eligible = self._identity_eligible_sql()
        enriched_predicate = self._inventory_enriched_sql()
        total_rows = self._query(
            "SELECT COUNT(*) AS c FROM modem_inventory_current "
            f"WHERE {eligible}" + scope_sql,
            tuple(scope_params),
        )
        total = int((total_rows[0] or {}).get("c") or 0) if total_rows else 0
        enriched_rows = self._query(
            "SELECT COUNT(*) AS c FROM modem_inventory_current "
            f"WHERE {eligible} AND ({enriched_predicate})" + scope_sql,
            tuple(scope_params),
        )
        enriched = (
            int((enriched_rows[0] or {}).get("c") or 0) if enriched_rows else 0
        )

        if cmts:
            pending_rows = self._query(
                "SELECT COUNT(*) AS c FROM modem_refresh_request r "
                "JOIN modem_inventory_current i ON i.mac=r.mac "
                "WHERE r.status IN ('queued','running') AND r.requested_by=%s "
                "AND i.inventory_state='active' "
                "AND (LOWER(COALESCE(i.cmts,''))=LOWER(%s) "
                "OR LOWER(COALESCE(i.cmts_ip,''))=LOWER(%s))",
                (_IDENTITY_REQUEST_SOURCE, cmts, cmts),
            )
        else:
            pending_rows = self._query(
                "SELECT COUNT(*) AS c FROM modem_refresh_request r "
                "JOIN modem_inventory_current i ON i.mac=r.mac "
                "WHERE r.status IN ('queued','running') AND r.requested_by=%s "
                "AND i.inventory_state='active'",
                (_IDENTITY_REQUEST_SOURCE,),
            )
        pending = int((pending_rows[0] or {}).get("c") or 0) if pending_rows else 0

        return {
            "inventory_total": inventory_total,
            "total": total,
            "eligible_total": total,
            "enriched": enriched,
            "pending_refresh": pending,
            "pending_identity": pending,
            "enriching": pending > 0,
            "percentage": round(enriched / total * 100, 1) if total > 0 else 0.0,
        }

    # ── Inventory summary (admin dashboard) ──────────────────────

    def get_inventory_summary(
        self,
        cmts: Optional[str] = None,
        top_n: int = 25,
        area: Optional[str] = "all",
    ) -> dict:
        """Read normalized materialized inventory summaries only."""
        top = max(1, min(int(top_n), 100))
        normalized_area = self._normalize_inventory_area(area)
        cmts_value = str(cmts).strip() if cmts else None

        def _scope(alias: str) -> tuple[str, List[Any]]:
            predicates: List[str] = []
            params: List[Any] = []
            if cmts_value:
                predicates.append(f"({alias}.cmts=%s OR {alias}.cmts_ip=%s)")
                params.extend([cmts_value, cmts_value])
            area_predicate, area_params = self._area_sql_predicate(
                f"{alias}.area", normalized_area
            )
            if area_predicate:
                predicates.append(area_predicate)
                params.extend(area_params)
            return (
                (" WHERE " + " AND ".join(predicates)) if predicates else "",
                params,
            )

        status_where, status_params = _scope("s")
        status_rows = self._query(
            "SELECT COUNT(*) AS covered_cmts, "
            "COALESCE(SUM(s.active_total),0) AS total, "
            "COALESCE(SUM(s.enriched_count),0) AS enriched, "
            "MAX(s.last_updated) AS last_updated, "
            "MAX(s.refreshed_at) AS refreshed_at "
            f"FROM inventory_summary_status s{status_where}",
            tuple(status_params),
        )
        status = (status_rows[0] if status_rows else {}) or {}
        covered_cmts = int(status.get("covered_cmts") or 0)
        total = int(status.get("total") or 0)
        enriched = int(status.get("enriched") or 0)

        snapshot_where, snapshot_params = _scope("snap")
        snapshot_rows = self._query(
            "SELECT COUNT(*) AS c FROM cmts_inventory_snapshot snap"
            f"{snapshot_where}",
            tuple(snapshot_params),
        )
        snapshot_count = (
            int((snapshot_rows[0] or {}).get("c") or 0) if snapshot_rows else 0
        )

        count_where, count_params = _scope("s")
        results: Dict[str, List[Dict[str, Any]]] = {}
        for dimension in ("vendor", "model", "software_version", "docsis_version"):
            dimension_predicate = (
                f"{count_where} AND c.dimension=%s"
                if count_where
                else " WHERE c.dimension=%s"
            )
            rows = self._query(
                "SELECT c.value, SUM(c.row_count) AS count "
                "FROM inventory_summary_count c "
                "JOIN inventory_summary_status s ON s.cmts_ip=c.cmts_ip "
                f"{dimension_predicate} GROUP BY c.value "
                "ORDER BY count DESC, c.value ASC LIMIT %s",
                tuple(count_params + [dimension, top]),
            )
            results[dimension] = [
                {
                    "value": str(row.get("value") or ""),
                    "count": int(row.get("count") or 0),
                }
                for row in rows
            ]

        return {
            "total": total,
            "enriched": enriched,
            "enriched_pct": round(enriched / total * 100, 1) if total else 0.0,
            "last_updated": str(status.get("last_updated") or ""),
            "vendors": results.get("vendor", []),
            "models": results.get("model", []),
            "firmwares": results.get("software_version", []),
            "docsis_versions": results.get("docsis_version", []),
            "materialized": True,
            "area": normalized_area,
            "coverage": {
                "covered_cmts": covered_cmts,
                "snapshot_cmts": snapshot_count,
                "complete": covered_cmts == snapshot_count,
            },
            "refreshed_at": str(status.get("refreshed_at") or ""),
        }

    def get_inventory_history(
        self,
        *,
        dimension: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        cmts: Optional[str] = None,
        area: Optional[str] = "all",
        top_n: int = 10,
    ) -> Dict[str, Any]:
        """Read stable interval-wide Top N series from daily inventory history."""
        dimensions = {
            "model": "model",
            "vendor": "vendor",
            "firmware": "software_version",
            "docsis": "docsis_version",
        }
        normalized_dimension = str(dimension or "").strip().lower()
        if normalized_dimension not in dimensions:
            raise ValueError(
                "dimension must be one of: model, vendor, firmware, docsis"
            )
        storage_dimension = dimensions[normalized_dimension]
        normalized_area = self._normalize_inventory_area(area)
        try:
            requested_top_n = int(top_n)
        except (TypeError, ValueError) as exc:
            raise ValueError("top_n must be between 1 and 100") from exc
        if not 1 <= requested_top_n <= 100:
            raise ValueError("top_n must be between 1 and 100")

        today = datetime.now(timezone.utc).date()

        def _parse_date(value: Optional[str], default) -> Any:
            if value is None:
                return default
            text = str(value).strip()
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError(
                    "start and end must be ISO dates (YYYY-MM-DD)"
                ) from exc
            if len(text) != 10 or parsed.isoformat() != text:
                raise ValueError("start and end must be ISO dates (YYYY-MM-DD)")
            return parsed

        start_date = _parse_date(start, today - timedelta(days=29))
        end_date = _parse_date(end, today)
        if start_date > end_date:
            raise ValueError("start date must be on or before end date")

        predicates = [
            "d.dimension=%s",
            "d.snapshot_date BETWEEN %s AND %s",
        ]
        params: List[Any] = [storage_dimension, start_date, end_date]
        cmts_value = str(cmts).strip() if cmts else None
        if cmts_value:
            predicates.append("(d.cmts=%s OR d.cmts_ip=%s)")
            params.extend([cmts_value, cmts_value])
        area_predicate, area_params = self._area_sql_predicate(
            "d.area", normalized_area
        )
        if area_predicate:
            predicates.append(area_predicate)
            params.extend(area_params)
        where_sql = " WHERE " + " AND ".join(predicates)

        top_rows = self._query(
            "SELECT d.value, SUM(d.row_count) AS total "
            f"FROM inventory_summary_daily d{where_sql} "
            "GROUP BY d.value ORDER BY total DESC, d.value ASC LIMIT %s",
            tuple(params + [requested_top_n]),
        )
        selected = [str(row.get("value") or "") for row in top_rows]
        totals = {
            str(row.get("value") or ""): int(row.get("total") or 0)
            for row in top_rows
        }

        coverage_rows = self._query(
            "SELECT d.snapshot_date, COUNT(DISTINCT d.cmts_ip) AS cmts_count "
            f"FROM inventory_summary_daily d{where_sql} "
            "GROUP BY d.snapshot_date ORDER BY d.snapshot_date ASC",
            tuple(params),
        )
        labels = [str(row.get("snapshot_date")) for row in coverage_rows]
        coverage = [
            {
                "date": str(row.get("snapshot_date")),
                "cmts_count": int(row.get("cmts_count") or 0),
            }
            for row in coverage_rows
        ]

        point_rows = self._query(
            "SELECT d.snapshot_date, d.value, SUM(d.row_count) AS row_count "
            f"FROM inventory_summary_daily d{where_sql} "
            "GROUP BY d.snapshot_date, d.value "
            "ORDER BY d.snapshot_date ASC, d.value ASC",
            tuple(params),
        )
        selected_points: Dict[str, Dict[str, int]] = {
            value: {} for value in selected
        }
        other_points: Dict[str, int] = {label: 0 for label in labels}
        selected_set = set(selected)
        for row in point_rows:
            label = str(row.get("snapshot_date"))
            value = str(row.get("value") or "")
            count = int(row.get("row_count") or 0)
            if value in selected_set:
                selected_points[value][label] = count
            elif label in other_points:
                other_points[label] += count

        ordered_selected = sorted(selected, key=lambda value: (-totals[value], value))
        series = [
            {
                "value": value,
                "data": [selected_points[value].get(label, 0) for label in labels],
                "total": totals[value],
            }
            for value in ordered_selected
        ]
        other_total = sum(other_points.values())
        if other_total > 0:
            series.append(
                {
                    "value": "Other (remaining)",
                    "data": [other_points[label] for label in labels],
                    "total": other_total,
                    "is_other": True,
                }
            )

        return {
            "dimension": normalized_dimension,
            "storage_dimension": storage_dimension,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "area": normalized_area,
            "cmts": cmts_value,
            "top_n": requested_top_n,
            "labels": labels,
            "series": series,
            "coverage": coverage,
            "has_data": bool(point_rows),
        }

    def rebuild_inventory_summaries(self) -> Dict[str, Any]:
        """Recompute summaries in bounded, restart-safe per-CMTS transactions."""
        started = time.perf_counter()
        now = self._now()
        targets = self._query(
            "SELECT cmts_ip, MAX(cmts) AS cmts FROM ("
            "SELECT cmts_ip, cmts FROM cmts_inventory_snapshot "
            "WHERE COALESCE(cmts_ip,'')<>'' UNION ALL "
            "SELECT cmts_ip, cmts FROM inventory_summary_status "
            "WHERE COALESCE(cmts_ip,'')<>''"
            ") inventory_targets GROUP BY cmts_ip ORDER BY cmts_ip"
        )
        status_rows = 0
        conn = self._connect()
        try:
            for target in targets:
                cmts_ip = str(target.get("cmts_ip") or "").strip()
                if not cmts_ip:
                    continue
                cmts = str(target.get("cmts") or cmts_ip).strip() or cmts_ip
                with self._db_lock:
                    try:
                        conn.begin()
                        cur = conn.cursor()
                        area = self._refresh_summary_for_cmts_cursor(
                            cur,
                            cmts_ip=cmts_ip,
                            cmts=cmts,
                            refreshed_at=now,
                        )
                        cur.execute(
                            "UPDATE cmts_inventory_snapshot SET area=%s "
                            "WHERE cmts_ip=%s",
                            (area, cmts_ip),
                        )
                        conn.commit()
                        status_rows += 1
                    except Exception:
                        conn.rollback()
                        raise
        finally:
            conn.close()
        count_result = self._query(
            "SELECT COUNT(*) AS c FROM inventory_summary_count"
        )
        count_rows = (
            int((count_result[0] or {}).get("c") or 0)
            if count_result
            else 0
        )
        return {
            "status_rows": status_rows,
            "count_rows": count_rows,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "refreshed_at": now,
            "strategy": "per_cmts",
        }

    # ── Queue head (admin dashboard) ─────────────────────────────

    def get_queue_heads(self) -> dict:
        poller_head = self._query(
            "SELECT id, poller_id, status, created_at FROM poller_job WHERE status IN ('queued','running') ORDER BY id ASC LIMIT 5"
        )
        refresh_head = self._query(
            "SELECT id, mac, status, created_at FROM modem_refresh_request WHERE status IN ('queued','running') ORDER BY id ASC LIMIT 5"
        )
        return {"poller_jobs": poller_head, "refresh_requests": refresh_head}


poller_service = PollerService()
