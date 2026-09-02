# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ipaddress
import json
import logging
import os
import queue
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_for_futures
from datetime import datetime, timedelta, timezone
from datetime import time as datetime_time
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

        # CPE-triggered identity work is globally bounded per API process.
        # Queue items contain only authoritative parent modem MACs, never the
        # subscriber CPE addresses collected from DOCS-SUBMGT3.
        self._identity_worker_count = self._bounded_env_int(
            "CPE_IDENTITY_WORKERS", 1, minimum=1, maximum=4
        )
        identity_queue_size = self._bounded_env_int(
            "CPE_IDENTITY_QUEUE_SIZE", 16, minimum=1, maximum=512
        )
        self._identity_queue: queue.Queue[
            tuple[
                str,
                str,
                tuple[str, ...],
                int,
                float,
                threading.Event,
                Dict[str, Any],
            ]
        ] = queue.Queue(maxsize=identity_queue_size)
        self._identity_start_lock = threading.Lock()
        self._identity_workers_started = False

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
    def _bounded_env_int(
        name: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            return max(minimum, min(int(os.environ.get(name, str(default))), maximum))
        except (TypeError, ValueError):
            return default

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

    def _start_identity_workers(self) -> None:
        with self._identity_start_lock:
            if self._identity_workers_started:
                return
            workers = [
                threading.Thread(
                    target=self._identity_worker_loop,
                    name=f"pypnm-identity-worker-{index + 1}",
                    daemon=True,
                )
                for index in range(self._identity_worker_count)
            ]
            self._identity_workers_started = True
        for worker in workers:
            worker.start()
        logger.info(
            "Started %d bounded CPE identity worker(s); queue capacity=%d",
            self._identity_worker_count,
            self._identity_queue.maxsize,
        )

    def _enqueue_identity_enrichment(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts_ip: str,
        cmts_name: str,
        job_id: int,
        job_deadline: float,
        should_continue: Optional[Callable[[], bool]] = None,
    ) -> Optional[tuple[threading.Event, Dict[str, Any]]]:
        """Queue parent modem MACs with backpressure; never queue CPE IPs."""
        target_cmts_ip = str(cmts_ip or "").strip()
        if not target_cmts_ip:
            return None
        modem_macs = tuple(
            dict.fromkeys(
                normalized
                for row in rows or []
                if isinstance(row, dict)
                for normalized in [
                    self._normalize_mac(str(row.get("modem_mac") or ""))
                ]
                if normalized
            )
        )
        if not modem_macs:
            return None

        self._start_identity_workers()
        completed = threading.Event()
        outcome: Dict[str, Any] = {
            "cmts": str(cmts_name or target_cmts_ip),
            "cmts_ip": target_cmts_ip,
            "status": "queued",
            "updated": 0,
            "error": None,
        }
        item = (
            str(cmts_name or target_cmts_ip),
            target_cmts_ip,
            modem_macs,
            int(job_id),
            float(job_deadline),
            completed,
            outcome,
        )
        if self._identity_queue.full():
            logger.info(
                "Identity enrichment queue full; applying backpressure for %s",
                cmts_name,
            )
        while True:
            try:
                self._identity_queue.put(item, timeout=1.0)
                return completed, outcome
            except queue.Full:
                if should_continue is None:
                    continue
                try:
                    keep_waiting = should_continue()
                except Exception as exc:
                    logger.warning(
                        "Identity enrichment queue status check failed for %s: %s",
                        cmts_name,
                        exc,
                    )
                    return None
                if not keep_waiting:
                    logger.info(
                        "Identity enrichment queue cancelled for %s",
                        cmts_name,
                    )
                    return None

    def _identity_worker_loop(self) -> None:
        while True:
            (
                cmts_name,
                cmts_ip,
                modem_macs,
                job_id,
                job_deadline,
                completed,
                outcome,
            ) = self._identity_queue.get()
            try:
                status_rows = self._query(
                    "SELECT status FROM poller_job WHERE id=%s",
                    (job_id,),
                )
                if (
                    time.monotonic() >= job_deadline
                    or not status_rows
                    or str((status_rows[0] or {}).get("status") or "").lower()
                    != "running"
                ):
                    outcome["status"] = "skipped"
                    outcome["error"] = (
                        f"Poller job {job_id} is no longer running"
                    )
                    logger.info(
                        "Identity enrichment skipped for %s: poller job %d is no "
                        "longer running",
                        cmts_name,
                        job_id,
                    )
                    continue
                outcome["status"] = "running"
                outcome["updated"] = self._run_identity_enrichment(
                    modem_macs,
                    cmts_ip=cmts_ip,
                    cmts_name=cmts_name,
                    job_id=job_id,
                    job_deadline=job_deadline,
                )
                outcome["status"] = "done"
            except Exception as exc:
                outcome["status"] = "failed"
                outcome["error"] = str(exc)
                logger.warning(
                    "Identity enrichment failed for %s: %s",
                    cmts_name,
                    exc,
                )
            finally:
                completed.set()
                self._identity_queue.task_done()

    def _run_identity_enrichment(
        self,
        modem_macs: tuple[str, ...],
        *,
        cmts_ip: str,
        cmts_name: str,
        job_id: int,
        job_deadline: float,
    ) -> int:
        import asyncio

        from pypnm.api.routes.cmts.service import CMTSModemService

        inventory_modems = self.get_inventory_modems_bulk(
            list(modem_macs),
            cmts_ip=cmts_ip,
        )
        modem_dicts = [
            modem
            for modem in inventory_modems
            if str(modem.get("ip_address") or "").strip()
        ]
        skipped = len(modem_macs) - len(modem_dicts)
        if skipped:
            logger.info(
                "Identity enrichment: skipped %d/%d modems for %s without a "
                "matching authoritative inventory address",
                skipped,
                len(modem_macs),
                cmts_name,
            )
        if not modem_dicts:
            return 0

        identity_fields = (
            "vendor",
            "model",
            "software_version",
            "docsis_version",
        )
        before = {
            str(modem.get("mac_address") or ""): tuple(
                modem.get(field) for field in identity_fields
            )
            for modem in modem_dicts
        }
        logger.info(
            "Identity enrichment: starting for %s (%d modems from inventory)",
            cmts_name,
            len(modem_dicts),
        )
        service = CMTSModemService(agent_priority="bulk")
        asyncio.run(
            service._enrich_modem_identities(
                modem_dicts,
                cmts_ip=cmts_ip,
                # Poller enrichment must not share GUI cache progress or
                # cancellation state keyed by CMTS address.
                progress_cmts_ip=None,
            )
        )

        changed = []
        for modem in modem_dicts:
            mac = str(modem.get("mac_address") or "")
            original = before.get(mac)
            if original is None:
                continue
            delta: Dict[str, Any] = {"mac_address": mac}
            for index, field in enumerate(identity_fields):
                if modem.get(field) != original[index]:
                    delta[field] = modem.get(field)
            if len(delta) > 1:
                changed.append(delta)
        if time.monotonic() >= job_deadline:
            self._execute(
                "UPDATE poller_job SET status='timed_out', finished_at=%s, "
                "error_text=%s WHERE id=%s AND status='running'",
                (
                    self._now(),
                    "CPE identity result discarded after job deadline",
                    job_id,
                ),
            )
            return 0
        status_rows = self._query(
            "SELECT status FROM poller_job WHERE id=%s",
            (job_id,),
        )
        if not status_rows or str(
            (status_rows[0] or {}).get("status") or ""
        ).lower() != "running":
            logger.info(
                "Identity enrichment result discarded for %s: poller job %d "
                "is no longer running",
                cmts_name,
                job_id,
            )
            return 0
        updated = self._update_inventory_identity_rows(
            changed,
            cmts_ip=cmts_ip,
            job_id=job_id,
        )
        logger.info(
            "Identity enrichment: finished for %s (%d/%d modem identities updated)",
            cmts_name,
            updated,
            len(modem_dicts),
        )
        return updated

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
                PRIMARY KEY (mac)
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
                identity_rollout_version SMALLINT UNSIGNED NOT NULL DEFAULT 1,
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
                revision_at DATETIME NOT NULL,
                PRIMARY KEY (cmts_ip),
                INDEX idx_inventory_snapshot_cmts (cmts),
                INDEX idx_inventory_snapshot_collected (collected_at)
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
        if "identity_rollout_version" not in setting_columns:
            # Existing installations receive version 0 so the protected CPE
            # task is disabled exactly once during the safe rollout below.
            missing_setting_columns.append(
                "ADD COLUMN `identity_rollout_version` SMALLINT UNSIGNED "
                "NOT NULL DEFAULT 0"
            )
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
            "SELECT id, identity_rollout_version FROM poller_setting "
            "WHERE system_key=%s LIMIT 1",
            (_CPE_TASK_SYSTEM_KEY,),
        )
        cpe_by_name = self._query(
            "SELECT id, identity_rollout_version FROM poller_setting "
            "WHERE name=%s LIMIT 1",
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
                "scope_type='all_cmts', scope_json=NULL, "
                "collect_identity=CASE WHEN identity_rollout_version < 1 "
                "THEN FALSE ELSE collect_identity END, identity_rollout_version=1, "
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
                     collect_identity, identity_rollout_version,
                     collect_scqam, collect_rxmer,
                     interval_minutes, max_concurrency, max_agent_queue_depth,
                     retention_days, heavy_max_modems, heavy_delay_ms,
                     max_runtime_sec, last_target_offset, created_at, updated_at)
                VALUES (%s,%s,%s,TRUE,'all_cmts',NULL,FALSE,1,FALSE,FALSE,
                        720,10,20,30,300,0,43200,0,%s,%s)
                """,
                (_CPE_TASK_NAME, _CPE_TASK_TYPE, _CPE_TASK_SYSTEM_KEY, now, now),
            )

        snapshot_columns = {
            "revision_at": "DATETIME NULL",
            "capability_enriched": "BOOLEAN NOT NULL DEFAULT FALSE",
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

        # Indexes for listing/filtering (duplicate-index errors are harmless).
        for idx_ddl in [
            "CREATE INDEX idx_inv_cmts ON modem_inventory_current (cmts, mac)",
            "CREATE INDEX idx_inv_cmts_ip ON modem_inventory_current (cmts_ip)",
            "CREATE INDEX idx_inv_fiber_node ON modem_inventory_current (fiber_node)",
        ]:
            try:
                self._execute(idx_ddl)
            except Exception:
                pass

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
                INDEX idx_refresh_status (status, created_at),
                INDEX idx_refresh_mac (mac, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
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
        """Requeue refresh work orphaned when the refresh lock owner stopped."""
        self._execute(
            """
            UPDATE modem_refresh_request
            SET status='queued', started_at=NULL, finished_at=NULL,
                error_text='Recovered after refresh worker restart'
            WHERE status='running'
            """
        )

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
        """Process targeted modem enrichment independently of long poller jobs."""
        lock_conn = None
        while True:
            if lock_conn is None:
                try:
                    lock_conn = self._try_acquire_worker_lock("refresh")
                    if lock_conn is not None:
                        self._recover_interrupted_refresh_work()
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
                # Keep the advisory-lock connection distinct from thread-local
                # query connections, and never reconnect it implicitly.
                lock_conn.ping(reconnect=False)
            except Exception:
                try:
                    lock_conn.close()
                except Exception:
                    pass
                lock_conn = None
                continue

            try:
                self._timeout_stale_refresh_requests()
            except Exception as exc:
                logger.warning("Refresh timeout sweep failed: %s", exc)

            try:
                self._process_refresh_queue()
            except Exception as exc:
                logger.warning("Refresh queue worker failed: %s", exc)

            time.sleep(2)

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
        max_runtime = max(30, int(os.environ.get("DATA_STORE_REFRESH_MAX_RUNTIME_SEC", "300")))
        max_queue_age = max(30, int(os.environ.get("DATA_STORE_REFRESH_MAX_QUEUE_AGE_SEC", str(max_runtime))))
        self._execute(
            """
            UPDATE modem_refresh_request
            SET status=%s,
                finished_at=%s,
                error_text=CONCAT('Timed out after ', %s, 's')
            WHERE status='running' AND started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, started_at, UTC_TIMESTAMP()) > %s
            """,
            ("timed_out", self._now(), max_runtime, max_runtime),
        )
        self._execute(
            """
            UPDATE modem_refresh_request
            SET status=%s,
                finished_at=%s,
                error_text=CONCAT('Expired in queue after ', %s, 's')
            WHERE status='queued' AND created_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, created_at, UTC_TIMESTAMP()) > %s
            """,
            ("timed_out", self._now(), max_queue_age, max_queue_age),
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
                "WHERE COALESCE(cmts_ip, '') <> '' LIMIT 2000"
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

    def _fetch_cmts_modems(self, cmts_ip: str, timeout_sec: int = 300) -> Dict[str, Any]:
        """Fetch a fresh base CMTS inventory and its completeness metadata."""
        base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        requested_limit = self._cm_modem_limit_default()
        payload = {
            "cmts_ip": cmts_ip,
            "agent_priority": "bulk",
            "limit": requested_limit,
            "enrich": False,
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
        request_timeout_cap_sec: Optional[float] = None,
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
        if request_timeout_cap_sec is not None:
            request_timeout = min(
                request_timeout,
                max(1.0, float(request_timeout_cap_sec)),
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
                r.get("software_version") or None,
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
                 source_poller, snapshot_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                WHEN docsis_version LIKE '%4.0%' THEN docsis_version
                WHEN VALUES(docsis_version) LIKE '%4.0%' THEN VALUES(docsis_version)
                WHEN docsis_version LIKE '%3.1%' THEN docsis_version
                WHEN VALUES(docsis_version) LIKE '%3.1%' THEN VALUES(docsis_version)
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
              snapshot_id=COALESCE(VALUES(snapshot_id), snapshot_id)
        """

        batch_size = 500
        for i in range(0, len(all_values), batch_size):
            batch = all_values[i:i + batch_size]
            with self._db_lock:
                conn = self._connect()
                cur = conn.cursor()
                cur.executemany(sql, batch)
                conn.close()
            inserted += len(batch)

        return inserted

    def _update_inventory_identity_rows(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts_ip: str,
        job_id: int,
    ) -> int:
        """Update identity fields only while the owning poller job is running."""
        target_cmts_ip = str(cmts_ip or "").strip()
        if not rows or not target_cmts_ip:
            return 0

        def _meaningful(value: Any) -> Optional[str]:
            text = str(value or "").strip()
            if text.lower() in {"", "unknown", "n/a", "none"}:
                return None
            return text

        values = []
        for row in rows:
            mac = self._normalize_mac(
                str(row.get("mac_address") or row.get("mac") or "")
            )
            if not mac:
                continue
            identity = (
                _meaningful(row.get("vendor")),
                _meaningful(row.get("model")),
                _meaningful(row.get("software_version")),
                _meaningful(row.get("docsis_version")),
            )
            if not any(identity):
                continue
            values.append((*identity, mac, target_cmts_ip, int(job_id)))
        if not values:
            return 0

        sql = """
            UPDATE modem_inventory_current
            SET vendor=COALESCE(%s, vendor),
                model=COALESCE(%s, model),
                software_version=COALESCE(%s, software_version),
                docsis_version=COALESCE(%s, docsis_version)
            WHERE mac=%s AND cmts_ip=%s
              AND EXISTS (
                  SELECT 1 FROM poller_job
                  WHERE id=%s AND status='running'
              )
        """
        with self._db_lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.executemany(sql, values)
                return int(cur.rowcount or 0)
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

        snapshot_id = str(uuid.uuid4())
        stamped_rows: List[Dict[str, Any]] = []
        for source in rows or []:
            if not isinstance(source, dict):
                continue
            row = dict(source)
            row["cmts"] = cmts_name
            row["cmts_ip"] = cmts_address
            stamped_rows.append(row)

        written = self._upsert_inventory_rows(
            stamped_rows,
            source_poller=source_poller,
            snapshot_id=snapshot_id,
        )
        cpe_written = self._persist_cpe_generation(
            metadata.get('cpe_addresses') or [],
            cmts_ip=cmts_address,
            snapshot_id=snapshot_id,
            complete=metadata.get('cpe_complete') is True,
            truncated=metadata.get('cpe_truncated') is True,
        )
        self._record_inventory_snapshot(
            cmts=cmts_name,
            cmts_ip=cmts_address,
            snapshot_id=snapshot_id,
            metadata=metadata,
            row_count=written,
            source_poller=source_poller,
        )
        return {
            "snapshot_id": snapshot_id,
            "row_count": written,
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

        # A complete generation is authoritative. Prune stale rows before
        # publishing its metadata; readers do not filter by generation, so a
        # failed batch or metadata write cannot hide the previous inventory.
        if metadata.get("complete") is True and metadata.get("truncated") is not True:
            self._execute(
                "DELETE FROM modem_inventory_current "
                "WHERE cmts_ip=%s AND (snapshot_id IS NULL OR snapshot_id<>%s)",
                (cmts_ip, snapshot_id),
            )

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
            "SELECT cmts_ip, cmts, snapshot_id, complete, truncated, "
            "capability_enriched, requested_limit, row_count, collected_at, revision_at "
            "FROM cmts_inventory_snapshot"
        )
        snapshots: List[Dict[str, Any]] = []
        for source in rows:
            row = dict(source)
            row["complete"] = bool(row.get("complete"))
            row["truncated"] = bool(row.get("truncated"))
            row["capability_enriched"] = bool(row.get("capability_enriched"))
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

    def _purge_stale_inventory(self, retention_days: int) -> int:
        days = max(1, int(retention_days or 30))
        before = self._query("SELECT COUNT(*) AS c FROM modem_inventory_current")
        count_before = int((before[0] or {}).get("c") or 0) if before else 0

        self._execute(
            "DELETE FROM modem_inventory_current WHERE last_seen_at < (UTC_TIMESTAMP() - INTERVAL %s DAY)",
            (days,),
        )
        self._execute(
            "DELETE FROM modem_cpe_ip_current "
            "WHERE last_seen_at < (UTC_TIMESTAMP() - INTERVAL %s DAY) "
            "OR NOT EXISTS (SELECT 1 FROM modem_inventory_current m "
            "WHERE m.mac=modem_cpe_ip_current.modem_mac "
            "AND m.cmts_ip=modem_cpe_ip_current.cmts_ip)",
            (days,),
        )
        after = self._query("SELECT COUNT(*) AS c FROM modem_inventory_current")
        count_after = int((after[0] or {}).get("c") or 0) if after else 0
        return max(0, count_before - count_after)

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
        collect_identity = bool(int(poller.get("collect_identity") or 0))
        identity_tickets: List[
            tuple[threading.Event, Dict[str, Any]]
        ] = []
        identity_failures = 0
        try:
            max_runtime_sec = max(60, int(poller.get("max_runtime_sec") or 43200))
        except (TypeError, ValueError):
            max_runtime_sec = 43200
        job_deadline = time.monotonic() + max_runtime_sec
        deadline_expired = False
        # Identity queue state is in memory. If a process restarts while an
        # identity-enabled job is running, replay every CMTS so no accepted
        # enrichment item can be skipped by the CPE fetch checkpoint.
        start_offset = (
            0
            if collect_identity
            else max(0, int(poller.get("last_target_offset") or 0))
        )
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
            nonlocal deadline_expired
            if time.monotonic() >= job_deadline:
                deadline_expired = True
                self._execute(
                    "UPDATE poller_job SET status='timed_out', finished_at=%s, "
                    "error_text=%s WHERE id=%s AND status='running'",
                    (
                        self._now(),
                        f"CPE job exceeded max runtime of {max_runtime_sec}s",
                        job_id,
                    ),
                )
                return False
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
                remaining_job_sec = max(1.0, job_deadline - time.monotonic())
                bounded_overall_timeout = max(
                    1,
                    min(
                        int(envelope["overall_timeout_sec"]),
                        int(remaining_job_sec),
                    ),
                )
                bounded_agent_timeout = max(
                    1,
                    min(
                        int(envelope["agent_command_timeout_sec"]),
                        int(remaining_job_sec),
                    ),
                )
                bounded_tree_reserve = min(
                    float(envelope["min_remaining_tree_reserve_sec"]),
                    max(0.0, float(bounded_overall_timeout - 1)),
                )
                try:
                    return {
                        "cancelled": False,
                        "fetch_result": self._fetch_cmts_cpe(
                            cmts_ip,
                            overall_timeout_sec=bounded_overall_timeout,
                            agent_command_timeout_sec=bounded_agent_timeout,
                            min_remaining_tree_reserve_sec=bounded_tree_reserve,
                            http_timeout_sec=envelope["http_timeout_sec"],
                            request_timeout_cap_sec=remaining_job_sec,
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

                    # Queue only parent modem MACs. The bounded worker resolves
                    # authoritative management IPs from modem_inventory_current;
                    # DOCS-SUBMGT3 CPE addresses must never be SNMP targets.
                    if complete and collect_identity and cpe_rows:
                        ticket = self._enqueue_identity_enrichment(
                            cpe_rows,
                            cmts_ip=cmts_ip,
                            cmts_name=cmts_name,
                            job_id=job_id,
                            job_deadline=job_deadline,
                            should_continue=_job_is_running,
                        )
                        if ticket is not None:
                            identity_tickets.append(ticket)
                        elif _job_is_running():
                            logger.warning(
                                "Identity enrichment not queued for %s: no valid "
                                "parent modem MACs",
                                cmts_name,
                            )

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
                        executor.shutdown(
                            wait=not deadline_expired,
                            cancel_futures=True,
                        )
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

        if not cancelled and identity_tickets:
            total_identity_targets = len(identity_tickets)
            last_reported = -1
            while True:
                completed_identity_targets = sum(
                    completed.is_set() for completed, _ in identity_tickets
                )
                if completed_identity_targets >= total_identity_targets:
                    break
                if not _job_is_running():
                    cancelled = True
                    break
                if completed_identity_targets != last_reported:
                    self._update_running_job_progress(
                        job_id,
                        "CPE identity enrichment: "
                        f"{completed_identity_targets}/{total_identity_targets} "
                        "CMTS targets finished",
                        rows_collected=rows_collected,
                        modems_attempted=targets_attempted,
                        modems_succeeded=targets_succeeded,
                        modems_failed=targets_failed,
                    )
                    last_reported = completed_identity_targets
                time.sleep(1)
            identity_failures = sum(
                outcome.get("status") == "failed"
                for _, outcome in identity_tickets
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
        if identity_failures:
            identity_message = (
                f"identity enrichment failed for {identity_failures}/"
                f"{len(identity_tickets)} queued CMTS target(s)"
            )
            result_message = (
                f"{result_message}; {identity_message}"
                if result_message
                else identity_message
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
            is_cpe_task = (
                str(candidate.get("task_type") or "inventory") == _CPE_TASK_TYPE
            )
            inside_window = self._inside_run_window(
                candidate.get("run_window_start"),
                candidate.get("run_window_end"),
            )
            if setting_missing or disabled or is_cpe_task or inside_window:
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
                != _CPE_TASK_TYPE
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
                ) -> List[Dict[str, str]]:
                    if not isinstance(raw_targets, list):
                        raise RuntimeError("Inventory target manifest is not a list")
                    normalized_targets = []
                    seen_ips = set()
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
                                "name": str(
                                    target.get("name") or cmts_ip
                                ).strip(),
                                "ip": cmts_ip,
                            }
                        )
                    return normalized_targets

                if "inventory_targets" in request_payload:
                    if request_payload.get(
                        "inventory_target_manifest_version"
                    ) != 1:
                        raise RuntimeError(
                            "Unsupported inventory target manifest version"
                        )
                    targets = _normalize_inventory_targets(
                        request_payload.get("inventory_targets"),
                        reject_duplicates=True,
                    )
                else:
                    if start_offset:
                        raise RuntimeError(
                            "Cannot safely resume inventory without a target manifest"
                        )
                    targets = _normalize_inventory_targets(
                        self._cmts_targets_for_poller(poller),
                        reject_duplicates=False,
                    )
                    request_payload["inventory_targets"] = targets
                    request_payload["inventory_target_manifest_version"] = 1
                    self._execute(
                        "UPDATE poller_job SET request_payload=%s "
                        "WHERE id=%s AND status='running'",
                        (json.dumps(request_payload), job_id),
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
                        min(int(poller.get("max_concurrency") or 1), 4),
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

                        snapshot_id = str(uuid.uuid4())
                        written = self._upsert_inventory_rows(
                            modems,
                            source_poller=poller.get("name"),
                            snapshot_id=snapshot_id,
                        )
                        self._record_inventory_snapshot(
                            cmts=cmts_name,
                            cmts_ip=cmts_ip,
                            snapshot_id=snapshot_id,
                            metadata=fetch_result,
                            row_count=written,
                            source_poller=poller.get("name"),
                        )
                        breakdown_entry = {
                            "cmts": cmts_name,
                            "cmts_ip": cmts_ip,
                            "row_count": written,
                            "complete": fetch_result.get("complete") is True,
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
                        modems_succeeded += len(modems)
                        progress_message = (
                            f"CMTS {idx}/{total_targets}: {cmts_name} done "
                            f"({len(modems)} modems)"
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

                try:
                    self._purge_stale_inventory(
                        int(poller.get("retention_days") or 30)
                    )
                except Exception:
                    pass

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

        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, error_text=%s WHERE id=%s AND status='running'",
            ("done" if not error_text else "failed", self._now(), int(rows_collected), int(modems_attempted), int(modems_succeeded), int(modems_failed), error_text, job_id),
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
                allowed = {}
                if "enabled" in payload:
                    allowed["enabled"] = bool(payload.get("enabled"))
                if "collect_identity" in payload:
                    allowed["collect_identity"] = bool(payload.get("collect_identity"))
                if allowed:
                    set_clause = ", ".join(f"{k}=%s" for k in allowed)
                    self._execute(
                        f"UPDATE poller_setting SET {set_clause}, updated_at=%s WHERE id=%s",
                        (*allowed.values(), now, int(poller_id)),
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
            str(poller.get("task_type") or "inventory") != _CPE_TASK_TYPE
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
                    or str(setting.get("task_type") or "inventory") != "inventory"
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
                != _CPE_TASK_TYPE
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
            if job_id and str(setting.get("task_type") or "inventory") == "inventory":
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
            max_global_active = max(1, int(os.environ.get("DATA_STORE_MAX_ACTIVE_JOBS", "10")))
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
                is_cpe_task = (
                    str(active_job.get("task_type") or "inventory")
                    == _CPE_TASK_TYPE
                )
                inside_window = self._inside_run_window(
                    active_job.get("run_window_start"),
                    active_job.get("run_window_end"),
                )
                if (
                    status == "running"
                    or setting_missing
                    or disabled
                    or is_cpe_task
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

                if str(p.get("task_type") or "inventory") == _CPE_TASK_TYPE:
                    scheduled_slot = self._latest_cpe_slot_utc()
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
                            "reason": "fixed_schedule_due",
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

    def list_inventory_modems(
        self,
        cmts: Optional[str] = None,
        search_type: Optional[str] = None,
        search_value: Optional[str] = None,
        interface_filter: Optional[str] = None,
        limit: int | None = None,
    ) -> List[Dict[str, Any]]:
        if limit is None:
            limit = self._cm_modem_limit_default()
        limit = max(1, min(int(limit or self._cm_modem_limit_default()), 50000))
        where = []
        params: List[Any] = []

        if cmts:
            marker = "%s"
            cmts_value = str(cmts).strip()
            try:
                ipaddress.ip_address(cmts_value)
                cmts_column = "cmts_ip"
            except ValueError:
                cmts_column = "cmts"
            # Both columns use a case-insensitive collation in production. Direct
            # equality keeps the predicate sargable so the existing indexes are used.
            where.append(f"{cmts_column} = {marker}")
            params.append(cmts_value)

        if search_value:
            sv = f"%{str(search_value).lower()}%"
            marker = "%s"
            if search_type == "cpe_ip":
                cpe_query = self.normalize_cpe_search(str(search_value))
                comparator = (
                    f"c.ip_address LIKE {marker}"
                    if cpe_query['prefix'] else f"c.ip_address = {marker}"
                )
                where.append(
                    "EXISTS (SELECT 1 FROM modem_cpe_ip_current c "
                    f"WHERE c.modem_mac=modem_inventory_current.mac "
                    f"AND c.cmts_ip=modem_inventory_current.cmts_ip "
                    f"AND c.address_family={marker} AND {comparator})"
                )
                params.extend([
                    cpe_query['family'],
                    cpe_query['value'] + '%' if cpe_query['prefix'] else cpe_query['value'],
                ])
            elif search_type == "ip":
                where.append(f"LOWER(COALESCE(ip,'')) LIKE {marker}")
                params.append(sv)
            elif search_type == "mac":
                mac_norm = (
                    str(search_value)
                    .lower()
                    .replace(":", "")
                    .replace("-", "")
                    .replace(".", "")
                    .replace(" ", "")
                )
                marker = "%s"
                if len(mac_norm) == 12:
                    # Full MAC — use indexed primary-key candidates. Canonical
                    # rows are first; bare/dotted candidates preserve upgrade
                    # compatibility without applying functions to the column.
                    formatted = ":".join(mac_norm[i:i+2] for i in range(0, 12, 2))
                    dotted = ".".join(mac_norm[i:i+4] for i in range(0, 12, 4))
                    where.append(f"mac IN ({marker}, {marker}, {marker})")
                    params.extend([formatted, mac_norm, dotted])
                    limit = 1
                else:
                    # Partial MAC — fall back to normalised LIKE scan
                    expr = "LOWER(REPLACE(REPLACE(COALESCE(mac,''),':',''),'-',''))"
                    where.append(f"{expr} LIKE {marker}")
                    params.append(f"%{mac_norm}%")
            elif search_type == "name":
                where.append(
                    f"(LOWER(COALESCE(vendor,'')) LIKE {marker} OR LOWER(COALESCE(model,'')) LIKE {marker} OR LOWER(COALESCE(fiber_node,'')) LIKE {marker})"
                )
                params.extend([sv, sv, sv])
            elif search_type == "fiber_node":
                where.append(f"LOWER(COALESCE(fiber_node,'')) LIKE {marker}")
                params.append(sv)

        if interface_filter:
            marker = "%s"
            where.append(f"(LOWER(COALESCE(upstream_interface,'')) LIKE {marker} OR LOWER(COALESCE(cable_mac,'')) LIKE {marker})")
            params.append(f"%{str(interface_filter).lower()}%")

        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        marker = "%s"
        rows = self._query(
            "SELECT mac, ip, cmts, cmts_ip, cmts_index, docsif3_index, "
            "fiber_node, cable_mac, mac_domain, status, docsis_version, vendor, model, "
            "upstream_interface, upstream_ifindex, ofdm_ifindex, ofdma_ifindex, "
            "ofdm_channel_count, ofdma_channel_count, ofdma_rf_port_ifindex, "
            "ofdm_enabled, ofdma_enabled, partial_service, partial_service_downstream, "
            "partial_service_upstream, partial_service_state, software_version, updated_at "
            f"FROM modem_inventory_current{where_sql} ORDER BY cmts ASC, mac ASC LIMIT {marker}",
            tuple(params + [limit]),
        )
        return [self._map_inventory_row(row) for row in rows]

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
            "partial_service_upstream, partial_service_state, software_version, updated_at "
            f"FROM modem_inventory_current WHERE mac IN ({marker}, {marker}, {marker}) "
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
            "SELECT ip_address, address_family, modem_mac "
            "FROM modem_cpe_ip_current LIMIT %s",
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
            "SELECT DISTINCT ip_address FROM modem_cpe_ip_current "
            f"WHERE address_family=%s AND ip_address {comparator} "
            "ORDER BY ip_address LIMIT %s",
            (normalized['family'], value, capped),
        )
        return [str(row.get('ip_address')) for row in rows if row.get('ip_address')]

    def get_inventory_modems_bulk(
        self,
        mac_addresses: list[str],
        cmts_ip: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """Look up modems by primary-key MAC, optionally scoped to one CMTS."""
        normalized = list(
            dict.fromkeys(
                mac
                for value in mac_addresses or []
                for mac in [self._normalize_mac(str(value or ""))]
                if mac
            )
        )
        if not normalized:
            return []
        target_cmts_ip = str(cmts_ip or "").strip()

        results: list[Dict[str, Any]] = []
        for i in range(0, len(normalized), 500):
            batch = normalized[i:i + 500]
            placeholders = ",".join(["%s"] * len(batch))
            sql = (
                "SELECT mac, ip, cmts, cmts_ip, cmts_index, docsif3_index, "
                "fiber_node, cable_mac, mac_domain, status, docsis_version, vendor, model, "
                "upstream_interface, upstream_ifindex, ofdm_ifindex, ofdma_ifindex, "
                "ofdm_channel_count, ofdma_channel_count, ofdma_rf_port_ifindex, "
                "ofdm_enabled, ofdma_enabled, partial_service, partial_service_downstream, "
                "partial_service_upstream, partial_service_state, software_version, updated_at "
                f"FROM modem_inventory_current WHERE mac IN ({placeholders})"
            )
            params: list[Any] = list(batch)
            if target_cmts_ip:
                sql += " AND cmts_ip=%s"
                params.append(target_cmts_ip)
            rows = self._query(sql, tuple(params))
            results.extend(self._map_inventory_row(row) for row in rows)
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
            "updated_at": row.get("updated_at"),
        }

    # ── Modem refresh (on-demand single-modem enrichment) ──────────

    def enqueue_modem_refresh(self, mac: str, cmts: str | None = None, requested_by: str | None = None) -> int:
        normalized_mac = self._normalize_mac(mac)
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
        return int(
            self._execute(
                "INSERT INTO modem_refresh_request (mac, cmts, status, requested_by, created_at) VALUES (%s,%s,%s,%s,%s)",
                (normalized_mac, cmts, "queued", requested_by or "api", now),
            ) or 0
        )

    def get_refresh_status(self, mac: str) -> dict | None:
        mac_norm = self._normalize_mac(mac).replace(":", "").replace("-", "")
        rows = self._query(
            "SELECT id, mac, cmts, status, error_text, created_at, started_at, finished_at "
            "FROM modem_refresh_request "
            "WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = LOWER(%s) "
            "ORDER BY id DESC LIMIT 1",
            (mac_norm,),
        )
        return rows[0] if rows else None

    def cancel_refresh_request(self, req_id: int) -> bool:
        before = self._query(
            "SELECT status FROM modem_refresh_request WHERE id=%s LIMIT 1",
            (int(req_id),),
        )
        if not before:
            return False
        current_status = str((before[0] or {}).get("status") or "").lower()
        if current_status not in {"queued", "running"}:
            return False
        self._execute(
            "UPDATE modem_refresh_request SET status=%s, finished_at=%s WHERE id=%s AND status IN ('queued','running')",
            ("cancelled", self._now(), int(req_id)),
        )
        return True

    def _resolve_modem_from_cmts(self, mac: str, cmts_name: str | None, base: str) -> Dict[str, Any] | None:
        """Fallback: do a live CMTS walk to find modem row and upsert inventory."""
        if not cmts_name:
            return None
        # Resolve CMTS IP: look up any row for this CMTS name in inventory
        rows = self._query(
            "SELECT cmts_ip FROM modem_inventory_current WHERE LOWER(cmts)=LOWER(%s) AND cmts_ip IS NOT NULL LIMIT 1",
            (cmts_name,),
        )
        cmts_ip = (rows[0] or {}).get("cmts_ip") if rows else None
        if not cmts_ip:
            return None
        query_payload = {
            "cmts_ip": cmts_ip,
            "enrich": False,
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
            modems = payload.get("modems") or []
            mac_norm = mac.lower().replace(":", "").replace("-", "")
            for m in modems:
                m_mac = str(m.get("mac_address") or "").lower().replace(":", "").replace("-", "")
                if m_mac == mac_norm:
                    found_ip = m.get("ip_address")
                    if found_ip:
                        # Upsert into inventory so the UPDATE later succeeds
                        self._upsert_inventory_rows([{
                            "mac_address": mac,
                            "ip_address": found_ip,
                            "cmts": cmts_name,
                            "cmts_ip": cmts_ip,
                            **{k: m.get(k) for k in (
                                "cmts_index", "docsif3_index", "fiber_node",
                                "cable_mac", "mac_domain", "status",
                                "docsis_version", "upstream_interface", "upstream_ifindex",
                                "ofdm_ifindex", "ofdma_ifindex",
                                "ofdm_channel_count", "ofdma_channel_count",
                                "ofdma_rf_port_ifindex", "ofdm_enabled", "ofdma_enabled",
                                "partial_service", "partial_service_downstream",
                                "partial_service_upstream", "partial_service_state",
                                "software_version", "vendor", "model",
                            )},
                        }], source_poller="refresh-fallback")
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
            "modem_ip": modem.get("ip_address") or modem.get("ip"),
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

        version_rank = {
            "DOCSIS 1.0": 10,
            "DOCSIS 1.1": 11,
            "DOCSIS 2.0": 20,
            "DOCSIS 3.0": 30,
            "DOCSIS 3.1": 31,
            "DOCSIS 4.0": 40,
        }
        discovered_version = payload.get("docsis_version")
        docsis_version = (
            discovered_version
            if version_rank.get(discovered_version, 0)
            >= version_rank.get(existing["docsis_version"], 0)
            else existing["docsis_version"]
        )
        return {
            "cable_mac": payload.get("cable_mac") or existing["cable_mac"],
            "fiber_node": payload.get("fiber_node") or existing["fiber_node"],
            "docsis_version": docsis_version,
        }

    def _process_refresh_queue(self) -> None:
        """Process one queued modem refresh request."""
        rows = self._query(
            "SELECT id, mac, cmts FROM modem_refresh_request WHERE status='queued' ORDER BY id ASC LIMIT 1"
        )
        if not rows:
            return
        req = rows[0]
        req_id = int(req["id"])
        mac = req["mac"]
        cmts = req.get("cmts")

        # Claim only if still queued; never resurrect a request cancelled
        # between the SELECT and UPDATE.
        self._execute(
            "UPDATE modem_refresh_request SET status=%s, started_at=%s "
            "WHERE id=%s AND status='queued'",
            ("running", self._now(), req_id),
        )
        claimed = self._query(
            "SELECT status FROM modem_refresh_request WHERE id=%s", (req_id,)
        )
        if not claimed or str((claimed[0] or {}).get("status") or "") != "running":
            return
        try:
            base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
            community = (
                os.environ.get("MODEM_COMMUNITY")
                or os.environ.get("CM_SNMP_COMMUNITY")
            )
            # Look up modem IP from inventory; if missing, do a live CMTS walk fallback
            modem = self.get_inventory_modem_by_mac(mac)
            cmts_fallback_modem = None
            modem_ip = (modem or {}).get("ip_address")
            if not modem_ip:
                cmts_fallback_modem = self._resolve_modem_from_cmts(mac, cmts, base)
                modem_ip = (cmts_fallback_modem or {}).get("ip_address")
                if not modem_ip:
                    raise ValueError(f"Modem {mac} not in inventory and not found via live CMTS walk")
            # Call sysDescr endpoint
            r = requests.post(
                f"{base}/system/sysDescr",
                json={
                    "cable_modem": {
                        "mac_address": mac,
                        "ip_address": modem_ip,
                        "snmp": {
                            "snmp_v2c": {
                                "community": community,
                            }
                        },
                    }
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json() if r.content else {}

            # Extract sysDescr string and parse vendor/model/software
            raw_descr = ""
            results = data.get("results") or {}
            sys_descr_obj = results.get("sysDescr")
            if isinstance(sys_descr_obj, dict):
                raw_descr = sys_descr_obj.get("raw") or sys_descr_obj.get("description") or str(sys_descr_obj)
            elif isinstance(sys_descr_obj, str):
                raw_descr = sys_descr_obj

            vendor = None
            model_name = None
            software_ver = None

            if raw_descr:
                from pypnm.api.routes.cmts.service import CMTSModemService
                parsed = CMTSModemService._parse_sys_descr(None, raw_descr)
                vendor = parsed.get("vendor")
                model_name = parsed.get("model")
                software_ver = parsed.get("software")

            # Fallback: try flat fields from response
            if not vendor:
                vendor = data.get("vendor") or data.get("VENDOR")
            if not model_name:
                model_name = data.get("model") or data.get("MODEL") or data.get("hw_rev") or data.get("HW_REV")
            if not software_ver:
                software_ver = data.get("software_version") or data.get("SW_REV")

            # Fallback: nested sysDescr object fields from System API
            if isinstance(sys_descr_obj, dict):
                if not vendor:
                    vendor = sys_descr_obj.get("vendor") or sys_descr_obj.get("VENDOR")
                if not model_name:
                    model_name = sys_descr_obj.get("model") or sys_descr_obj.get("MODEL") or sys_descr_obj.get("hw_rev")
                if not software_ver:
                    software_ver = sys_descr_obj.get("sw_rev") or sys_descr_obj.get("SW_REV") or sys_descr_obj.get("software")

            # Final fallback: valid identity values from the live CMTS row.
            if (not vendor or not model_name or not software_ver) and cmts:
                if not cmts_fallback_modem:
                    cmts_fallback_modem = self._resolve_modem_from_cmts(mac, cmts, base)
                if isinstance(cmts_fallback_modem, dict):
                    if not vendor:
                        vendor = cmts_fallback_modem.get("vendor")
                    if not model_name:
                        model_name = cmts_fallback_modem.get("model")
                    if not software_ver:
                        software_ver = cmts_fallback_modem.get("software_version")

            cable_source = dict(modem or {})
            if isinstance(cmts_fallback_modem, dict):
                for key, value in cmts_fallback_modem.items():
                    if value is not None and not cable_source.get(key):
                        cable_source[key] = value
            interface_values = {
                "cable_mac": cable_source.get("cable_mac"),
                "fiber_node": cable_source.get("fiber_node"),
                "docsis_version": cable_source.get("docsis_version"),
            }
            try:
                interface_values = self._resolve_cmts_interface_from_cmts(cable_source, base)
            except Exception as exc:
                logger.warning("Targeted CMTS interface lookup for %s failed: %s", mac, exc)
            cable_mac = interface_values.get("cable_mac")
            fiber_node = interface_values.get("fiber_node")
            docsis_version = interface_values.get("docsis_version")

            if vendor or model_name or software_ver or cable_mac or fiber_node or docsis_version:
                self._execute(
                    "UPDATE modem_inventory_current SET "
                    "vendor=COALESCE(NULLIF(%s,''), vendor), "
                    "model=COALESCE(NULLIF(%s,''), model), "
                    "software_version=COALESCE(NULLIF(%s,''), software_version), "
                    "cable_mac=COALESCE(NULLIF(%s,''), cable_mac), "
                    "fiber_node=COALESCE(NULLIF(%s,''), fiber_node), "
                    "docsis_version=COALESCE(NULLIF(%s,''), docsis_version), "
                    "updated_at=%s WHERE mac=%s",
                    (
                        vendor,
                        model_name,
                        software_ver,
                        cable_mac,
                        fiber_node,
                        docsis_version,
                        self._now(),
                        mac,
                    ),
                )
            # A completed single-modem refresh changes data outside the full
            # snapshot generation. Advance its CMTS revision so every GUI
            # Redis entry derived from the prior revision is rejected.
            self._touch_inventory_revision(
                cmts or (modem or {}).get("cmts"),
                (modem or {}).get("cmts_ip"),
            )
            self._execute(
                "UPDATE modem_refresh_request SET status=%s, finished_at=%s WHERE id=%s",
                ("completed", self._now(), req_id),
            )
        except Exception as exc:
            self._execute(
                "UPDATE modem_refresh_request SET status=%s, finished_at=%s, error_text=%s WHERE id=%s",
                ("failed", self._now(), str(exc)[:500], req_id),
            )

    # ── Enrichment progress ──────────────────────────────────────

    def get_enrichment_progress(self, cmts: str | None = None) -> dict:
        where = ""
        params: list = []
        if cmts:
            where = " WHERE (LOWER(COALESCE(cmts,'')) = LOWER(%s) OR LOWER(COALESCE(cmts_ip,'')) = LOWER(%s))"
            params = [cmts, cmts]

        total_rows = self._query(f"SELECT COUNT(*) AS c FROM modem_inventory_current{where}", tuple(params))
        total = int((total_rows[0] or {}).get("c") or 0) if total_rows else 0

        enriched_rows = self._query(
            f"SELECT COUNT(*) AS c FROM modem_inventory_current{where}"
            + (" AND" if where else " WHERE")
            + " LOWER(TRIM(COALESCE(vendor,''))) NOT IN ('', 'unknown', 'n/a')"
            + " AND ("
            + " TRIM(COALESCE(software_version,'')) <> ''"
            + " OR LOWER(TRIM(COALESCE(model,''))) NOT IN ('', 'unknown', 'n/a')"
            + " )",
            tuple(params),
        )
        enriched = int((enriched_rows[0] or {}).get("c") or 0) if enriched_rows else 0

        # Check if any refresh requests are in progress (scoped to CMTS when provided)
        if cmts:
            pending_rows = self._query(
                "SELECT COUNT(*) AS c FROM modem_refresh_request "
                "WHERE status IN ('queued','running') AND LOWER(COALESCE(cmts,'')) = LOWER(%s)",
                (cmts,),
            )
        else:
            pending_rows = self._query(
                "SELECT COUNT(*) AS c FROM modem_refresh_request WHERE status IN ('queued','running')"
            )
        pending = int((pending_rows[0] or {}).get("c") or 0) if pending_rows else 0

        return {
            "total": total,
            "enriched": enriched,
            "pending_refresh": pending,
            "enriching": pending > 0,
            "percentage": round(enriched / total * 100, 1) if total > 0 else 0.0,
        }

    # ── Inventory summary (admin dashboard) ──────────────────────

    def get_inventory_summary(
        self,
        cmts: Optional[str] = None,
        top_n: int = 25,
        area: Optional[str] = None,
    ) -> dict:
        """Return inventory breakdowns with one grouped MySQL scan.

        fZiggo and fUPC filter on the modem management IPv4 address. VFZ is
        intentionally unfiltered by modem IP and represents the full inventory
        scope (subject only to an optional CMTS filter).
        """
        normalized_area = str(area or "").strip().lower()
        valid_areas = {"fziggo", "fupc", "vfz"}
        area_ranges = {
            "fziggo": [(2147483648, 2149580799)],  # 128.0.0.0/11
            "fupc": [
                (2684354560, 2686451711),  # 160.0.0.0/11
                (180355072, 182452223),    # 10.192.0.0/11
            ],
        }
        if normalized_area and normalized_area not in valid_areas:
            raise ValueError(f"Unsupported inventory area: {area}")

        where_parts: list[str] = []
        params: list[Any] = []
        cmts_value = str(cmts or "").strip()
        if cmts_value:
            try:
                ipaddress.ip_address(cmts_value)
                cmts_column = "cmts_ip"
            except ValueError:
                cmts_column = "cmts"
            where_parts.append(f"{cmts_column}=%s")
            params.append(cmts_value)

        if normalized_area in area_ranges:
            ip_number = "INET_ATON(NULLIF(TRIM(ip),''))"
            ranges = area_ranges[normalized_area]
            where_parts.append(
                "(" + " OR ".join(
                    f"{ip_number} BETWEEN %s AND %s" for _ in ranges
                ) + ")"
            )
            for lower, upper in ranges:
                params.extend([lower, upper])

        where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
        grouped_rows = self._query(
            f"""
            SELECT
                TRIM(COALESCE(vendor,'')) AS vendor,
                TRIM(COALESCE(model,'')) AS model,
                TRIM(COALESCE(software_version,'')) AS software_version,
                TRIM(COALESCE(docsis_version,'')) AS docsis_version,
                COUNT(*) AS row_count,
                MAX(updated_at) AS last_updated
            FROM modem_inventory_current{where_sql}
            GROUP BY 1, 2, 3, 4
            """,
            tuple(params),
        )

        placeholders = {"", "unknown", "n/a", "na", "none", "null", "-"}
        enriched_placeholders = {"", "unknown", "n/a"}

        def _meaningful(value: Any) -> str:
            text = str(value or "").strip()
            return "" if text.lower() in placeholders else text

        vendor_counts: Counter[str] = Counter()
        model_counts: Counter[str] = Counter()
        software_version_counts: Counter[str] = Counter()
        docsis_counts: Counter[str] = Counter()
        total = 0
        enriched = 0
        last_updated = ""

        for source in grouped_rows or []:
            count = int(source.get("row_count") or 0)
            total += count
            vendor_text = str(source.get("vendor") or "").strip()
            model_text = str(source.get("model") or "").strip()
            software_version_text = str(source.get("software_version") or "").strip()
            vendor = _meaningful(vendor_text)
            model = _meaningful(model_text)
            software_version = _meaningful(software_version_text)
            docsis = _meaningful(source.get("docsis_version"))
            if vendor:
                vendor_counts[vendor] += count
            if model:
                model_counts[model] += count
            if software_version:
                software_version_counts[software_version] += count
            if docsis:
                docsis_counts[docsis] += count
            if (
                vendor_text.lower() not in enriched_placeholders
                and (
                    bool(software_version_text)
                    or model_text.lower() not in enriched_placeholders
                )
            ):
                enriched += count
            updated = str(source.get("last_updated") or "")
            if updated > last_updated:
                last_updated = updated

        top = max(1, min(int(top_n), 100))

        def _top(counter: Counter[str]) -> list[dict[str, Any]]:
            return [
                {"value": value, "count": count}
                for value, count in counter.most_common(top)
            ]

        return {
            "total": total,
            "enriched": enriched,
            "enriched_pct": round(enriched / total * 100, 1) if total else 0.0,
            "last_updated": last_updated,
            "area": normalized_area or None,
            "vendors": _top(vendor_counts),
            "models": _top(model_counts),
            # Backward-compatible API key; internal storage/model uses software_version.
            "firmwares": _top(software_version_counts),
            "docsis_versions": _top(docsis_counts),
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
