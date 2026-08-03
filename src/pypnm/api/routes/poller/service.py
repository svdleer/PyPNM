# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import json
import ipaddress
import logging
import threading
import time
import uuid
from datetime import datetime, time as datetime_time, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import pymysql
import pymysql.cursors
import requests

logger = logging.getLogger(__name__)

_CPE_TASK_TYPE = "cpe_address_refresh"
_CPE_TASK_SYSTEM_KEY = "cpe-address-refresh"
_CPE_TASK_NAME = "CPE address refresh"
_CPE_TASK_SCHEDULE = (datetime_time(hour=0), datetime_time(hour=12))


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
            read_timeout=30,
            write_timeout=30,
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
        raw = (mac or "").strip().lower().replace("-", ":").replace(".", "")
        # If MAC has no separators and is 12 hex chars, format as aa:bb:cc:dd:ee:ff
        if ":" not in raw:
            compact = "".join(ch for ch in raw if ch in "0123456789abcdef")
            if len(compact) == 12:
                return ":".join(compact[i : i + 2] for i in range(0, 12, 2))
            return compact
        return raw

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
        if "last_scheduled_slot_utc" not in setting_columns:
            missing_setting_columns.append(
                "ADD COLUMN `last_scheduled_slot_utc` DATETIME NULL"
            )
        if missing_setting_columns:
            self._execute(
                "ALTER TABLE poller_setting " + ", ".join(missing_setting_columns)
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
                "max_runtime_sec=43200, updated_at=%s WHERE id=%s",
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
                        720,1,20,30,300,0,43200,0,%s,%s)
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
        t = threading.Thread(target=self._worker_loop, name="pypnm-poller-worker", daemon=True)
        t.start()
        self._worker_started = True

    def _try_acquire_worker_lock(self):
        """Return a dedicated connection holding the singleton worker lock."""
        conn = self._connect()
        lock_name = f"pypnm-poller-worker:{self._db_name()}"[:64]
        try:
            cur = conn.cursor()
            cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
            row = cur.fetchone() or {}
            cur.close()
            if int(row.get("acquired") or 0) == 1:
                logger.info("Acquired poller worker lock for database %s", self._db_name())
                return conn
        except Exception:
            conn.close()
            raise
        conn.close()
        return None

    def _recover_interrupted_work(self) -> None:
        """Requeue work orphaned when the previous lock owner stopped."""
        self._execute(
            """
            UPDATE poller_job
            SET status='queued', started_at=NULL, finished_at=NULL,
                error_text='Recovered after poller worker restart'
            WHERE status='running'
            """
        )
        self._execute(
            """
            UPDATE modem_refresh_request
            SET status='queued', started_at=NULL, finished_at=NULL,
                error_text='Recovered after poller worker restart'
            WHERE status='running'
            """
        )

    def _worker_loop(self) -> None:
        lock_conn = None
        while True:
            if lock_conn is None:
                try:
                    lock_conn = self._try_acquire_worker_lock()
                    if lock_conn is not None:
                        self._recover_interrupted_work()
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
                self._timeout_stale_refresh_requests()
            except Exception as exc:
                logger.warning("Refresh timeout sweep failed: %s", exc)

            try:
                self._process_one_job()
            except Exception as exc:
                logger.warning("Poller queue worker failed: %s", exc)

            try:
                self._process_refresh_queue()
            except Exception as exc:
                logger.warning("Refresh queue worker failed: %s", exc)

            try:
                if self._scheduler.get("enabled") and self._scheduler_due():
                    self.run_scheduler_once()
            except Exception as exc:
                logger.warning("Poller scheduler tick failed: %s", exc)

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
        if not decisions:
            return

        try:
            with self._db_lock:
                conn = self._connect()
                cur = conn.cursor()
                for d in decisions:
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
            "community": os.environ.get("CMTS_COMMUNITY") or os.environ.get("CMTS_SNMP_COMMUNITY") or "public",
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

    def _fetch_cmts_cpe(self, cmts_ip: str, timeout_sec: int = 300) -> Dict[str, Any]:
        """Fetch one fresh CPE-only generation from a CMTS."""
        base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        payload = {
            "cmts_ip": cmts_ip,
            "community": os.environ.get("CMTS_COMMUNITY") or os.environ.get("CMTS_SNMP_COMMUNITY") or "public",
        }
        request_timeout = max(330, int(timeout_sec or 300) + 30)
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
            mac = (r.get("mac_address") or r.get("mac") or "").lower().replace("-", ":")
            if not mac:
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

    def _persist_cpe_generation(
        self,
        rows: List[Dict[str, Any]],
        *,
        cmts_ip: str,
        snapshot_id: str,
        complete: bool,
        truncated: bool,
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
                revision_at=VALUES(revision_at)
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
        params: List[Any] = [self._now()]
        if cmts:
            where.append("LOWER(cmts)=LOWER(%s)")
            params.append(str(cmts))
        if cmts_ip:
            where.append("cmts_ip=%s")
            params.append(str(cmts_ip))
        if where:
            self._execute(
                f"UPDATE cmts_inventory_snapshot SET revision_at=%s WHERE {' OR '.join(where)}",
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
        breakdown: List[Dict[str, Any]] = []
        fatal_error = None
        incomplete_targets = 0
        poller_id = int(poller.get("id") or 0)
        start_offset = max(0, int(poller.get("last_target_offset") or 0))
        subtask_timeout_sec = max(
            30, int(os.environ.get("DATA_STORE_SUBTASK_TIMEOUT_SEC", "300"))
        )
        subtask_retries = max(
            0, int(os.environ.get("DATA_STORE_SUBTASK_RETRIES", "1"))
        )
        total_targets = len(targets)
        if total_targets == 0:
            fatal_error = "No CMTS targets resolved (check scope/appdb config)"

        for idx, target in enumerate(targets, start=1):
            if fatal_error or idx <= start_offset:
                continue
            status_rows = self._query(
                "SELECT status FROM poller_job WHERE id=%s", (job_id,)
            )
            current_status = (
                str((status_rows[0] or {}).get("status") or "").lower()
                if status_rows else ""
            )
            if current_status != "running":
                self._execute(
                    "UPDATE poller_setting SET last_target_offset=0, updated_at=%s "
                    "WHERE id=%s",
                    (self._now(), poller_id),
                )
                return

            cmts_ip = target.get("ip")
            cmts_name = target.get("name") or cmts_ip
            if not cmts_ip:
                continue
            self._update_running_job_progress(
                job_id,
                f"CPE {idx}/{total_targets}: walking {cmts_name}",
                rows_collected=rows_collected,
                modems_attempted=targets_attempted,
                modems_succeeded=targets_succeeded,
                modems_failed=targets_failed,
            )

            fetch_result = None
            last_target_error = None
            for attempt in range(subtask_retries + 1):
                try:
                    fetch_result = self._fetch_cmts_cpe(
                        cmts_ip, timeout_sec=subtask_timeout_sec
                    )
                    break
                except Exception as exc:
                    last_target_error = exc
                    self._update_running_job_progress(
                        job_id,
                        f"CPE {idx}/{total_targets}: {cmts_name} attempt "
                        f"{attempt + 1}/{subtask_retries + 1} failed ({exc})",
                        rows_collected=rows_collected,
                        modems_attempted=targets_attempted,
                        modems_succeeded=targets_succeeded,
                        modems_failed=targets_failed,
                    )
            if fetch_result is None:
                self._execute(
                    "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s "
                    "WHERE id=%s",
                    (idx - 1, self._now(), poller_id),
                )
                fatal_error = (
                    f"Subtask timeout/failure at CMTS {idx}/{total_targets} "
                    f"({cmts_name}): {last_target_error}"
                )
                targets_failed += 1
                break

            # Kill is cooperative. Never persist a generation returned after the
            # administrator cancelled the job while its SNMP request was in flight.
            status_rows = self._query(
                "SELECT status FROM poller_job WHERE id=%s", (job_id,)
            )
            if not status_rows or str(status_rows[0].get("status") or "") != "running":
                self._execute(
                    "UPDATE poller_setting SET last_target_offset=0, updated_at=%s "
                    "WHERE id=%s",
                    (self._now(), poller_id),
                )
                return

            targets_attempted += 1
            cpe_rows = fetch_result.get("cpe_addresses") or []
            complete = fetch_result.get("complete") is True
            truncated = fetch_result.get("truncated") is True
            validation_error = fetch_result.get("validation_error")
            written = 0
            if complete and not truncated:
                try:
                    written = self._persist_cpe_generation(
                        cpe_rows,
                        cmts_ip=cmts_ip,
                        snapshot_id=str(uuid.uuid4()),
                        complete=True,
                        truncated=False,
                    )
                    targets_succeeded += 1
                except Exception as exc:
                    complete = False
                    validation_error = str(exc)
            if not complete or truncated:
                targets_failed += 1
                incomplete_targets += 1

            breakdown.append({
                "cmts": cmts_name,
                "cmts_ip": cmts_ip,
                "row_count": written,
                "cpe_row_count": written,
                "skipped_cpe_rows": int(fetch_result.get("skipped_cpe_rows") or 0),
                "cpe_complete": complete,
                "cpe_truncated": truncated,
                "cpe_oid_errors": fetch_result.get("oid_errors") or {},
                "validation_error": validation_error,
                "requested_limit": fetch_result.get("requested_limit"),
                "collected_at": fetch_result.get("collected_at"),
                "raw_d3_mac_count": fetch_result.get("raw_d3_mac_count"),
                "raw_cpe_type_count": fetch_result.get("raw_cpe_type_count"),
                "raw_cpe_address_count": fetch_result.get("raw_cpe_address_count"),
                "raw_cpe_prefix_count": fetch_result.get("raw_cpe_prefix_count"),
            })
            self._execute(
                "UPDATE poller_job SET cmts_breakdown=%s WHERE id=%s",
                (json.dumps(breakdown), job_id),
            )
            rows_collected += written
            self._execute(
                "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s "
                "WHERE id=%s",
                (idx, self._now(), poller_id),
            )
            self._update_running_job_progress(
                job_id,
                f"CPE {idx}/{total_targets}: {cmts_name} done "
                f"({written} addresses, complete={complete})",
                rows_collected=rows_collected,
                modems_attempted=targets_attempted,
                modems_succeeded=targets_succeeded,
                modems_failed=targets_failed,
            )

        if not fatal_error:
            self._execute(
                "UPDATE poller_setting SET last_target_offset=0, updated_at=%s "
                "WHERE id=%s",
                (self._now(), poller_id),
            )
        result_error = fatal_error
        if not result_error and incomplete_targets:
            result_error = (
                f"CPE refresh completed with {incomplete_targets} incomplete "
                "CMTS generation(s); previous stored rows were preserved"
            )
        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, rows_collected=%s, "
            "modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, "
            "error_text=%s WHERE id=%s AND status='running'",
            (
                "done" if not result_error else "failed",
                self._now(),
                rows_collected,
                targets_attempted,
                targets_succeeded,
                targets_failed,
                result_error,
                job_id,
            ),
        )
        if fatal_error and "Subtask timeout/failure" in fatal_error:
            self.enqueue_run(poller_id, source="resume")

    def _process_one_job(self) -> None:
        queued = self._query("SELECT id, poller_id FROM poller_job WHERE status='queued' ORDER BY id ASC LIMIT 1")
        if not queued:
            return

        job = queued[0]
        job_id = int(job.get("id"))
        poller_id = int(job.get("poller_id") or 0)

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
        all_rows = []  # kept for potential future use; upserts are now per-CMTS
        cmts_breakdown: List[Dict[str, Any]] = []
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
                targets = self._cmts_targets_for_poller(poller)
                if str(poller.get("task_type") or "inventory") == _CPE_TASK_TYPE:
                    self._process_cpe_job(job_id, poller, targets)
                    return
                total_targets = len(targets)
                start_offset = max(0, int(poller.get("last_target_offset") or 0))
                subtask_timeout_sec = max(30, int(os.environ.get("DATA_STORE_SUBTASK_TIMEOUT_SEC", "300")))
                subtask_retries = max(0, int(os.environ.get("DATA_STORE_SUBTASK_RETRIES", "1")))
                self._update_running_job_progress(
                    job_id,
                    f"Resolved {total_targets} CMTS target(s) (resume offset={start_offset})",
                    rows_collected=0,
                    modems_attempted=0,
                    modems_succeeded=0,
                    modems_failed=0,
                )
                if total_targets == 0:
                    error_text = "No CMTS targets resolved (check scope/appdb config)"
                for idx, t in enumerate(targets, start=1):
                    if idx <= start_offset:
                        continue

                    status_rows = self._query(
                        "SELECT status FROM poller_job WHERE id=%s",
                        (job_id,),
                    )
                    current_status = (
                        str((status_rows[0] or {}).get("status") or "").lower()
                        if status_rows else ""
                    )
                    if current_status != "running":
                        self._execute(
                            "UPDATE poller_setting SET last_target_offset=0, "
                            "updated_at=%s WHERE id=%s",
                            (self._now(), poller_id),
                        )
                        return
                    cmts_ip = t.get("ip")
                    cmts_name = t.get("name") or cmts_ip
                    if not cmts_ip:
                        continue
                    self._update_running_job_progress(
                        job_id,
                        f"CMTS {idx}/{total_targets}: walking {cmts_name}",
                        rows_collected=rows_collected,
                        modems_attempted=modems_attempted,
                        modems_succeeded=modems_succeeded,
                        modems_failed=modems_failed,
                    )
                    fetch_result = None
                    last_target_error = None
                    for attempt in range(subtask_retries + 1):
                        try:
                            fetch_result = self._fetch_cmts_modems(cmts_ip, timeout_sec=subtask_timeout_sec)
                            break
                        except Exception as exc:
                            last_target_error = exc
                            self._update_running_job_progress(
                                job_id,
                                f"CMTS {idx}/{total_targets}: {cmts_name} attempt {attempt + 1}/{subtask_retries + 1} failed ({exc})",
                                rows_collected=rows_collected,
                                modems_attempted=modems_attempted,
                                modems_succeeded=modems_succeeded,
                                modems_failed=modems_failed,
                            )
                            status_rows = self._query(
                                "SELECT status FROM poller_job WHERE id=%s",
                                (job_id,),
                            )
                            if (
                                not status_rows
                                or str(status_rows[0].get("status") or "").lower()
                                != "running"
                            ):
                                self._execute(
                                    "UPDATE poller_setting SET last_target_offset=0, "
                                    "updated_at=%s WHERE id=%s",
                                    (self._now(), poller_id),
                                )
                                return

                    # Cancellation is cooperative: discard an in-flight result
                    # returned after the administrator stopped or cleared the job.
                    status_rows = self._query(
                        "SELECT status FROM poller_job WHERE id=%s",
                        (job_id,),
                    )
                    if (
                        not status_rows
                        or str(status_rows[0].get("status") or "").lower()
                        != "running"
                    ):
                        self._execute(
                            "UPDATE poller_setting SET last_target_offset=0, "
                            "updated_at=%s WHERE id=%s",
                            (self._now(), poller_id),
                        )
                        return

                    if fetch_result is None:
                        self._execute(
                            "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s WHERE id=%s",
                            (idx - 1, self._now(), poller_id),
                        )
                        error_text = f"Subtask timeout/failure at CMTS {idx}/{total_targets} ({cmts_name}): {last_target_error}"
                        modems_failed = max(modems_failed, 1)
                        break

                    modems = fetch_result.get("modems") or []
                    modems_attempted += len(modems)
                    for m in modems:
                        m["cmts"] = cmts_name
                        m["cmts_ip"] = cmts_ip

                    # Every collection receives an immutable generation ID. The
                    # snapshot row proves whether fewer rows than the safety cap
                    # represents a complete walk or a partial result.
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
                        "capability_enriched": fetch_result.get("capability_enriched") is True,
                        "requested_limit": fetch_result.get("requested_limit"),
                        "collected_at": fetch_result.get("collected_at"),
                        "critical_oid_errors": fetch_result.get("critical_oid_errors") or {},
                    }
                    cmts_breakdown.append(breakdown_entry)
                    self._execute(
                        "UPDATE poller_job SET cmts_breakdown=%s WHERE id=%s",
                        (json.dumps(cmts_breakdown), job_id),
                    )
                    rows_collected += written
                    modems_succeeded += len(modems)
                    all_rows.extend(modems)
                    self._execute(
                        "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s WHERE id=%s",
                        (idx, self._now(), poller_id),
                    )
                    self._update_running_job_progress(
                        job_id,
                        f"CMTS {idx}/{total_targets}: {cmts_name} done ({len(modems)} modems) [checkpoint={idx}]",
                        rows_collected=rows_collected,
                        modems_attempted=modems_attempted,
                        modems_succeeded=modems_succeeded,
                        modems_failed=modems_failed,
                    )

                try:
                    self._purge_stale_inventory(int(poller.get("retention_days") or 30))
                except Exception:
                    pass

                if not error_text:
                    self._execute(
                        "UPDATE poller_setting SET last_target_offset=%s, updated_at=%s WHERE id=%s",
                        (0, self._now(), poller_id),
                    )

        except Exception as exc:
            error_text = str(exc)
            modems_failed = max(modems_failed, 1)

        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, error_text=%s WHERE id=%s AND status='running'",
            ("done" if not error_text else "failed", self._now(), int(rows_collected), int(modems_attempted), int(modems_succeeded), int(modems_failed), error_text, job_id),
        )
        if error_text and 'Subtask timeout/failure' in str(error_text):
            self.enqueue_run(poller_id, source="resume")

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
            "SELECT id, enabled FROM poller_setting WHERE id=%s",
            (pid,),
        )
        if not pollers:
            return {"state": "not_found", "job_id": 0}
        if int(pollers[0].get("enabled") or 0) != 1:
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

        job_id = self.enqueue_run(pid, source=source)
        return {"state": "queued" if job_id else "rejected", "job_id": job_id}

    def enqueue_run(
        self,
        poller_id: int,
        source: Optional[str] = None,
        scheduled_slot_utc: Optional[str] = None,
    ) -> int:
        pid = int(poller_id)
        active = self._query(
            "SELECT id FROM poller_job WHERE poller_id=%s "
            "AND status IN ('queued','running') ORDER BY id DESC LIMIT 1",
            (pid,),
        )
        if active:
            return int((active[0] or {}).get("id") or 0)

        now = self._now()
        trigger = "scheduler" if (source or "api") == "scheduler" else "manual"
        payload = json.dumps({"source": source or "api"})
        sql = (
            "INSERT IGNORE INTO poller_job "
            "(poller_id, trigger_type, status, requested_by, request_payload, "
            "scheduled_slot_utc, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        )
        job_id = int(self._execute(
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
        ) or 0)
        if job_id or not scheduled_slot_utc:
            return job_id
        existing = self._query(
            "SELECT id FROM poller_job WHERE poller_id=%s "
            "AND scheduled_slot_utc=%s LIMIT 1",
            (pid, scheduled_slot_utc),
        )
        return int((existing[0] or {}).get("id") or 0) if existing else 0

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
        if self._scheduler.get("running"):
            return 0

        self._scheduler["running"] = True
        tick_iso = datetime.now(timezone.utc).isoformat()
        tick_sql = self._now()
        self._scheduler["last_tick"] = tick_iso
        queued = 0
        decisions = []
        try:
            max_global_active = max(1, int(os.environ.get("DATA_STORE_MAX_ACTIVE_JOBS", "10")))
            global_active_rows = self._query(
                "SELECT COUNT(*) AS c FROM poller_job WHERE status IN ('queued','running')"
            )
            global_active = int((global_active_rows[0] or {}).get("c") or 0) if global_active_rows else 0

            pollers = self._query(
                "SELECT id, name, enabled, interval_minutes, task_type, "
                "last_scheduled_slot_utc FROM poller_setting ORDER BY id ASC"
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

                minutes = max(1, int(p.get("interval_minutes") or 360))
                due = self._query(
                    """
                    SELECT id FROM poller_job
                    WHERE poller_id=%s
                      AND created_at >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
                    LIMIT 1
                    """,
                    (pid, minutes),
                )
                if due:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "interval_not_due"})
                    continue

                new_id = self.enqueue_run(pid, source="scheduler")
                if new_id:
                    queued += 1
                    global_active += 1
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "queued", "reason": "ok"})
                else:
                    decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "enqueue_rejected"})
        finally:
            self._scheduler["decisions"] = decisions[:100]
            self._log_scheduler_decisions(tick_sql, decisions)
            self._scheduler["running"] = False
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
                    # Full MAC — use exact match on the primary key column
                    # (stored as aa:bb:cc:dd:ee:ff) so the PK index is used.
                    formatted = ":".join(mac_norm[i:i+2] for i in range(0, 12, 2))
                    where.append(f"LOWER(mac) = {marker}")
                    params.append(formatted)
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
        mac_norm = (mac_address or "").lower().replace(":", "").replace("-", "")
        rows = self._query(
            "SELECT mac, ip, cmts, cmts_ip, cmts_index, docsif3_index, "
            "fiber_node, cable_mac, mac_domain, status, docsis_version, vendor, model, "
            "upstream_interface, upstream_ifindex, ofdm_ifindex, ofdma_ifindex, "
            "ofdm_channel_count, ofdma_channel_count, ofdma_rf_port_ifindex, "
            "ofdm_enabled, ofdma_enabled, partial_service, partial_service_downstream, "
            "partial_service_upstream, partial_service_state, software_version, updated_at "
            f"FROM modem_inventory_current WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = {marker} LIMIT 1",
            (mac_norm,),
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
        normalized = self.normalize_cpe_search(query)
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
                "partial_service_upstream, partial_service_state, software_version, updated_at "
                f"FROM modem_inventory_current WHERE mac IN ({placeholders})",
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
        cmts_community = os.environ.get("CMTS_COMMUNITY") or os.environ.get("CMTS_SNMP_COMMUNITY") or "public"
        try:
            r = requests.post(
                f"{base}/cmts/modems/query",
                json={
                    "cmts_ip": cmts_ip,
                    "community": cmts_community,
                    "enrich": False,
                    "limit": self._cm_modem_limit_default(),
                },
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
                                "firmware", "software_version", "vendor", "model",
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

    @staticmethod
    def _agent_snmp_get_value(base: str, target_ip: str, oid: str) -> str | None:
        """Run one read-only CMTS SNMP GET through the configured agent."""
        community = os.environ.get("CMTS_COMMUNITY") or os.environ.get("CMTS_SNMP_COMMUNITY") or "public"
        agent_id = os.environ.get("CMTS_AGENT_ID") or "cmts-agent"
        response = requests.post(
            f"{base}/api/agents/{agent_id}/task",
            params={"command": "snmp_get", "timeout": 30, "wait": "true"},
            json={
                "target_ip": target_ip,
                "oid": oid,
                "community": community,
                "timeout": 10,
            },
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        result = payload.get("result") or {}
        if result.get("type") == "response":
            result = result.get("result") or {}
        if result.get("success") is not True:
            return None
        output = str(result.get("output") or "").strip()
        value = output.split(" = ", 1)[1].strip() if " = " in output else output
        if not value or "No Such" in value:
            return None
        for prefix in ("STRING:", "INTEGER:", "Gauge32:"):
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
                break
        return value.strip('"') or None

    def _resolve_cable_mac_from_cmts(self, modem: Dict[str, Any] | None, base: str) -> str | None:
        """Resolve one modem's MAC-domain ifName using two scalar GETs."""
        if not modem or modem.get("cable_mac"):
            return (modem or {}).get("cable_mac")
        cmts_ip = str(modem.get("cmts_ip") or "").strip()
        docsif3_index = str(modem.get("docsif3_index") or "").strip()
        if not cmts_ip or not docsif3_index:
            return None

        md_if_value = self._agent_snmp_get_value(
            base,
            cmts_ip,
            f"1.3.6.1.4.1.4491.2.1.20.1.3.1.7.{docsif3_index}",
        )
        try:
            md_if_index = int(str(md_if_value).split()[-1])
        except (TypeError, ValueError):
            return None
        if md_if_index <= 0:
            return None

        return self._agent_snmp_get_value(
            base,
            cmts_ip,
            f"1.3.6.1.2.1.31.1.1.1.1.{md_if_index}",
        )

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

        # Claim only if still queued; if not, another worker/admin changed state.
        self._execute(
            "UPDATE modem_refresh_request SET status=%s, started_at=%s WHERE id=%s",
            ("running", self._now(), req_id),
        )
        claimed = self._query("SELECT status FROM modem_refresh_request WHERE id=%s", (req_id,))
        if not claimed or str((claimed[0] or {}).get("status") or "") != "running":
            return
        try:
            base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
            community = os.environ.get("MODEM_COMMUNITY") or os.environ.get("CM_SNMP_COMMUNITY") or "private"
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

            # Final fallback: values from CMTS walk row (often includes firmware)
            if (not vendor or not model_name or not software_ver) and cmts:
                if not cmts_fallback_modem:
                    cmts_fallback_modem = self._resolve_modem_from_cmts(mac, cmts, base)
                if isinstance(cmts_fallback_modem, dict):
                    if not vendor:
                        vendor = cmts_fallback_modem.get("vendor")
                    if not model_name:
                        model_name = cmts_fallback_modem.get("model")
                    if not software_ver:
                        software_ver = cmts_fallback_modem.get("software_version") or cmts_fallback_modem.get("firmware")

            cable_source = dict(modem or {})
            if isinstance(cmts_fallback_modem, dict):
                for key, value in cmts_fallback_modem.items():
                    if value is not None and not cable_source.get(key):
                        cable_source[key] = value
            cable_mac = None
            try:
                cable_mac = self._resolve_cable_mac_from_cmts(cable_source, base)
            except Exception as exc:
                logger.warning("Targeted cable-MAC lookup for %s failed: %s", mac, exc)

            if vendor or model_name or software_ver or cable_mac:
                self._execute(
                    "UPDATE modem_inventory_current SET "
                    "vendor=COALESCE(NULLIF(%s,''), vendor), "
                    "model=COALESCE(NULLIF(%s,''), model), "
                    "software_version=COALESCE(NULLIF(%s,''), software_version), "
                    "cable_mac=COALESCE(NULLIF(%s,''), cable_mac), "
                    "updated_at=%s WHERE mac=%s",
                    (vendor, model_name, software_ver, cable_mac, self._now(), mac),
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
