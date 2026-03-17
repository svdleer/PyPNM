# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


class PollerService:
    def __init__(self) -> None:
        self._db_lock = threading.Lock()
        self.backend = self._detect_backend()
        self.sqlite_path = os.environ.get("DATA_SQLITE_PATH", "/tmp/pypnm_poller.db")
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

    def _detect_backend(self) -> str:
        explicit = (os.environ.get("DATA_DB_BACKEND") or "").lower()
        if explicit in {"mysql", "sqlite"}:
            return explicit
        if os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST"):
            return "mysql"
        return "sqlite"

    def _db_name(self) -> str:
        return os.environ.get("DATA_DB_NAME") or os.environ.get("AUTH_DB_NAME") or "pypnm_auth"

    def _connect(self):
        if self.backend == "mysql":
            try:
                import pymysql
            except Exception as exc:
                raise RuntimeError("MySQL backend requested but pymysql is unavailable") from exc

            return pymysql.connect(
                host=os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1"),
                port=int(os.environ.get("DATA_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306")),
                user=os.environ.get("DATA_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm"),
                password=os.environ.get("DATA_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm"),
                database=self._db_name(),
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )

        os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _rows(self, cur):
        rows = cur.fetchall()
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append(r)
            else:
                out.append(dict(r))
        return out

    def _execute(self, sql: str, params=None):
        params = params or ()
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(sql, params)
            if self.backend == "sqlite":
                conn.commit()
            try:
                last_id = cur.lastrowid
            except Exception:
                last_id = None
            conn.close()
            return last_id

    def _query(self, sql: str, params=None):
        params = params or ()
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = self._rows(cur)
            conn.close()
            return rows

    def _init_db(self) -> None:
        if self.backend == "mysql":
            self._execute(
                """
                CREATE TABLE IF NOT EXISTS modem_inventory_current (
                    mac VARCHAR(17) NOT NULL,
                    ip VARCHAR(45) NULL,
                    cmts VARCHAR(128) NOT NULL,
                    cmts_ip VARCHAR(45) NULL,
                    fiber_node VARCHAR(128) NULL,
                    cable_mac VARCHAR(128) NULL,
                    status VARCHAR(64) NULL,
                    docsis_version VARCHAR(32) NULL,
                    vendor VARCHAR(64) NULL,
                    model VARCHAR(128) NULL,
                    upstream_interface VARCHAR(128) NULL,
                    ofdm_enabled BOOLEAN NULL,
                    ofdma_enabled BOOLEAN NULL,
                    partial_service BOOLEAN NULL,
                    first_seen_at DATETIME NOT NULL,
                    last_seen_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    source_poller VARCHAR(64) NULL,
                    PRIMARY KEY (mac)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            self._execute(
                """
                CREATE TABLE IF NOT EXISTS poller_setting (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(64) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    scope_type VARCHAR(16) NOT NULL DEFAULT 'all_cmts',
                    scope_json JSON NULL,
                    collect_identity BOOLEAN NOT NULL DEFAULT TRUE,
                    collect_scqam BOOLEAN NOT NULL DEFAULT FALSE,
                    collect_rxmer BOOLEAN NOT NULL DEFAULT FALSE,
                    interval_minutes INT NOT NULL DEFAULT 1440,
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
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    UNIQUE KEY uk_poller_setting_name (name)
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
                    created_at DATETIME NOT NULL,
                    INDEX idx_job_status_created (status, created_at)
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
            # Backward-compatible upgrades for already-existing tables.
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
            return

        self._execute(
            """
            CREATE TABLE IF NOT EXISTS modem_inventory_current (
                mac TEXT PRIMARY KEY,
                ip TEXT,
                cmts TEXT NOT NULL,
                cmts_ip TEXT,
                fiber_node TEXT,
                cable_mac TEXT,
                status TEXT,
                docsis_version TEXT,
                vendor TEXT,
                model TEXT,
                upstream_interface TEXT,
                ofdm_enabled INTEGER,
                ofdma_enabled INTEGER,
                partial_service INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_poller TEXT
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS poller_setting (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                scope_type TEXT NOT NULL DEFAULT 'all_cmts',
                scope_json TEXT,
                collect_identity INTEGER NOT NULL DEFAULT 1,
                collect_scqam INTEGER NOT NULL DEFAULT 0,
                collect_rxmer INTEGER NOT NULL DEFAULT 0,
                interval_minutes INTEGER NOT NULL DEFAULT 1440,
                run_window_start TEXT,
                run_window_end TEXT,
                max_concurrency INTEGER NOT NULL DEFAULT 1,
                max_agent_queue_depth INTEGER NOT NULL DEFAULT 20,
                retention_days INTEGER NOT NULL DEFAULT 30,
                heavy_window_start TEXT,
                heavy_window_end TEXT,
                heavy_max_modems INTEGER NOT NULL DEFAULT 300,
                heavy_delay_ms INTEGER NOT NULL DEFAULT 0,
                max_runtime_sec INTEGER NOT NULL DEFAULT 3600,
                last_target_offset INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS poller_job (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poller_id INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                rows_collected INTEGER NOT NULL DEFAULT 0,
                modems_attempted INTEGER NOT NULL DEFAULT 0,
                modems_succeeded INTEGER NOT NULL DEFAULT 0,
                modems_failed INTEGER NOT NULL DEFAULT 0,
                requested_by TEXT,
                request_payload TEXT,
                started_at TEXT,
                finished_at TEXT,
                error_text TEXT,
                cmts_breakdown TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_decision_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tick_at TEXT NOT NULL,
                poller_id INTEGER,
                poller_name TEXT,
                decision TEXT NOT NULL,
                reason TEXT,
                effective_load INTEGER,
                threshold INTEGER,
                detail TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._execute("CREATE INDEX IF NOT EXISTS idx_scheduler_decision_tick ON scheduler_decision_log(tick_at)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_poller_job_status_created ON poller_job(status, created_at)")
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS modem_rf_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac TEXT NOT NULL,
                cmts TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                scqam_json TEXT,
                rxmer_json TEXT,
                poller_name TEXT NOT NULL
            )
            """
        )
        self._execute("CREATE INDEX IF NOT EXISTS idx_modem_rf_snapshot_collected ON modem_rf_snapshot(collected_at)")

    def _start_worker(self) -> None:
        if self._worker_started:
            return
        t = threading.Thread(target=self._worker_loop, name="pypnm-poller-worker", daemon=True)
        t.start()
        self._worker_started = True

    def _worker_loop(self) -> None:
        while True:
            try:
                self._timeout_stale_jobs()
                self._process_one_job()
                if self._scheduler.get("enabled") and self._scheduler_due():
                    self.run_scheduler_once()
            except Exception:
                pass
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
        if self.backend == "mysql":
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
        else:
            self._execute(
                """
                UPDATE poller_job
                SET status=?, finished_at=?, error_text=?
                WHERE status='running' AND started_at IS NOT NULL
                  AND ((julianday('now') - julianday(started_at)) * 86400.0) >
                      COALESCE(NULLIF((SELECT max_runtime_sec FROM poller_setting p WHERE p.id = poller_job.poller_id), 0), ?)
                """,
                ("timed_out", self._now(), f"Timed out after {max_runtime}s", max_runtime),
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
                    if self.backend == "mysql":
                        cur.execute(
                            """
                            INSERT INTO scheduler_decision_log
                            (tick_at, poller_id, poller_name, decision, reason, effective_load, threshold, detail, created_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            vals,
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO scheduler_decision_log
                            (tick_at, poller_id, poller_name, decision, reason, effective_load, threshold, detail, created_at)
                            VALUES (?,?,?,?,?,?,?,?,?)
                            """,
                            vals,
                        )
                if self.backend == "sqlite":
                    conn.commit()
                conn.close()
        except Exception:
            # Keep scheduler operational even if decision logging has schema drift.
            return

    def _get_scheduler_decisions(self, limit: int = 100) -> List[Dict[str, Any]]:
        lim = max(1, int(limit))
        ph = "%s" if self.backend == "mysql" else "?"
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
            data = payload.get("data") if isinstance(payload, dict) else []
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _cmts_targets_for_poller(self, poller: Dict[str, Any]) -> List[Dict[str, str]]:
        scope_type = str(poller.get("scope_type") or "all_cmts").lower()
        if scope_type == "all_cmts":
            out = []
            for c in self._fetch_appdb_cmts():
                ip = c.get("IPAddress") or c.get("ip") or c.get("ip_address")
                if not ip:
                    continue
                out.append({
                    "name": c.get("HostName") or c.get("hostname") or ip,
                    "ip": ip,
                })
            return out

        raw_scope = poller.get("scope_json")
        if not raw_scope:
            return []
        try:
            scope = json.loads(raw_scope) if isinstance(raw_scope, str) else raw_scope
        except Exception:
            return []

        out = []
        if isinstance(scope, list):
            for item in scope:
                if isinstance(item, str):
                    out.append({"name": item, "ip": item})
                elif isinstance(item, dict):
                    ip = item.get("ip") or item.get("cmts_ip") or item.get("IPAddress")
                    if ip:
                        out.append({"name": item.get("name") or item.get("HostName") or ip, "ip": ip})
        return out

    def _fetch_cmts_modems(self, cmts_ip: str) -> List[Dict[str, Any]]:
        base = (os.environ.get("PYPNM_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        params = {
            "cmts_ip": cmts_ip,
            "community": os.environ.get("CMTS_COMMUNITY") or os.environ.get("CMTS_SNMP_COMMUNITY") or "public",
            "limit": 10000,
            "enrich": "true",
            "modem_community": os.environ.get("MODEM_COMMUNITY") or os.environ.get("CM_SNMP_COMMUNITY") or "private",
        }
        try:
            r = requests.get(f"{base}/cmts/modems", params=params, timeout=120, verify=False)
            r.raise_for_status()
            payload = r.json() if r.content else {}
            if isinstance(payload, dict) and payload.get("success"):
                modems = payload.get("modems") or []
                return modems if isinstance(modems, list) else []
            return []
        except Exception:
            return []

    def _upsert_inventory_rows(self, rows: List[Dict[str, Any]], source_poller: Optional[str]) -> int:
        if not rows:
            return 0
        now = self._now()
        inserted = 0
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            for r in rows:
                mac = (r.get("mac_address") or r.get("mac") or "").lower().replace("-", ":")
                if not mac:
                    continue
                values = (
                    mac,
                    r.get("ip_address") or r.get("ip"),
                    r.get("cmts") or "unknown",
                    r.get("cmts_ip"),
                    r.get("fiber_node"),
                    r.get("cable_mac"),
                    r.get("status"),
                    r.get("docsis_version"),
                    r.get("vendor"),
                    r.get("model"),
                    r.get("upstream_interface"),
                    1 if r.get("ofdm_enabled") else 0,
                    1 if r.get("ofdma_enabled") else 0,
                    1 if r.get("partial_service") else 0,
                    now,
                    now,
                    now,
                    source_poller,
                )

                if self.backend == "mysql":
                    cur.execute(
                        """
                        INSERT INTO modem_inventory_current
                        (mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version, vendor, model,
                         upstream_interface, ofdm_enabled, ofdma_enabled, partial_service,
                         first_seen_at, last_seen_at, updated_at, source_poller)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE
                          ip=VALUES(ip), cmts=VALUES(cmts), cmts_ip=VALUES(cmts_ip), fiber_node=VALUES(fiber_node),
                          cable_mac=VALUES(cable_mac), status=VALUES(status), docsis_version=VALUES(docsis_version),
                          vendor=VALUES(vendor), model=VALUES(model), upstream_interface=VALUES(upstream_interface),
                          ofdm_enabled=VALUES(ofdm_enabled), ofdma_enabled=VALUES(ofdma_enabled),
                          partial_service=VALUES(partial_service), last_seen_at=VALUES(last_seen_at),
                          updated_at=VALUES(updated_at), source_poller=VALUES(source_poller)
                        """,
                        values,
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO modem_inventory_current
                        (mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version, vendor, model,
                         upstream_interface, ofdm_enabled, ofdma_enabled, partial_service,
                         first_seen_at, last_seen_at, updated_at, source_poller)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(mac) DO UPDATE SET
                          ip=excluded.ip, cmts=excluded.cmts, cmts_ip=excluded.cmts_ip, fiber_node=excluded.fiber_node,
                          cable_mac=excluded.cable_mac, status=excluded.status, docsis_version=excluded.docsis_version,
                          vendor=excluded.vendor, model=excluded.model, upstream_interface=excluded.upstream_interface,
                          ofdm_enabled=excluded.ofdm_enabled, ofdma_enabled=excluded.ofdma_enabled,
                          partial_service=excluded.partial_service, last_seen_at=excluded.last_seen_at,
                          updated_at=excluded.updated_at, source_poller=excluded.source_poller
                        """,
                        values,
                    )
                inserted += 1

            if self.backend == "sqlite":
                conn.commit()
            conn.close()
        return inserted

    def _process_one_job(self) -> None:
        queued = self._query("SELECT id, poller_id FROM poller_job WHERE status='queued' ORDER BY id ASC LIMIT 1")
        if not queued:
            return

        job = queued[0]
        job_id = int(job.get("id"))
        poller_id = int(job.get("poller_id") or 0)

        self._execute(
            "UPDATE poller_job SET status=%s, started_at=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE poller_job SET status=?, started_at=? WHERE id=?",
            ("running", self._now(), job_id),
        )

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
                "SELECT * FROM poller_setting WHERE id=%s" if self.backend == "mysql" else "SELECT * FROM poller_setting WHERE id=?",
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
                all_rows = []
                total_targets = len(targets)
                self._update_running_job_progress(
                    job_id,
                    f"Resolved {total_targets} CMTS target(s)",
                    rows_collected=0,
                    modems_attempted=0,
                    modems_succeeded=0,
                    modems_failed=0,
                )
                if total_targets == 0:
                    error_text = "No CMTS targets resolved (check scope/appdb config)"
                for idx, t in enumerate(targets, start=1):
                    status_rows = self._query(
                        "SELECT status FROM poller_job WHERE id=%s" if self.backend == "mysql" else "SELECT status FROM poller_job WHERE id=?",
                        (job_id,),
                    )
                    current_status = str((status_rows[0] or {}).get("status") or "").lower() if status_rows else ""
                    if current_status and current_status != "running":
                        if current_status == "cancelled":
                            error_text = "Killed by admin"
                        else:
                            error_text = f"Stopped (status={current_status})"
                        break
                    cmts_ip = t.get("ip")
                    cmts_name = t.get("name") or cmts_ip
                    if not cmts_ip:
                        continue
                    self._update_running_job_progress(
                        job_id,
                        f"CMTS {idx}/{total_targets}: walking {cmts_name}",
                        rows_collected=len(all_rows),
                        modems_attempted=modems_attempted,
                        modems_succeeded=modems_succeeded,
                        modems_failed=modems_failed,
                    )
                    modems = self._fetch_cmts_modems(cmts_ip)
                    modems_attempted += len(modems)
                    modems_succeeded += len(modems)
                    for m in modems:
                        m["cmts"] = cmts_name
                        m["cmts_ip"] = cmts_ip
                    all_rows.extend(modems)
                    self._update_running_job_progress(
                        job_id,
                        f"CMTS {idx}/{total_targets}: {cmts_name} done ({len(modems)} modems)",
                        rows_collected=len(all_rows),
                        modems_attempted=modems_attempted,
                        modems_succeeded=modems_succeeded,
                        modems_failed=modems_failed,
                    )

                rows_collected = self._upsert_inventory_rows(all_rows, source_poller=poller.get("name"))

        except Exception as exc:
            error_text = str(exc)
            modems_failed = max(modems_failed, 1)

        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, error_text=%s WHERE id=%s AND status='running'"
            if self.backend == "mysql"
            else "UPDATE poller_job SET status=?, finished_at=?, rows_collected=?, modems_attempted=?, modems_succeeded=?, modems_failed=?, error_text=? WHERE id=? AND status='running'",
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
            "UPDATE poller_job SET rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, error_text=%s WHERE id=%s AND status='running'"
            if self.backend == "mysql"
            else "UPDATE poller_job SET rows_collected=?, modems_attempted=?, modems_succeeded=?, modems_failed=?, error_text=? WHERE id=? AND status='running'",
            (int(rows_collected), int(modems_attempted), int(modems_succeeded), int(modems_failed), str(message), int(job_id)),
        )

    def list_pollers(self) -> List[Dict[str, Any]]:
        return self._query("SELECT * FROM poller_setting ORDER BY id ASC")

    def upsert_poller(self, payload: Dict[str, Any]) -> int:
        now = self._now()
        poller_id = payload.get("id")

        if poller_id is None:
            cols = [k for k in payload.keys() if k != "id"]
            vals = [payload[k] for k in cols]
            cols += ["created_at", "updated_at"]
            vals += [now, now]

            ph = ", ".join(["%s" if self.backend == "mysql" else "?"] * len(cols))
            sql = f"INSERT INTO poller_setting ({', '.join(cols)}) VALUES ({ph})"
            return int(self._execute(sql, tuple(vals)) or 0)

        poller_id = int(poller_id)
        set_cols = [k for k in payload.keys() if k != "id"]
        assignments = ", ".join([f"{k}={'%s' if self.backend == 'mysql' else '?'}" for k in set_cols] + ["updated_at=%s" if self.backend == "mysql" else "updated_at=?"])
        params = [payload[k] for k in set_cols] + [now, poller_id]
        sql = (
            f"UPDATE poller_setting SET {assignments} WHERE id={'%s' if self.backend == 'mysql' else '?'}"
        )
        self._execute(sql, tuple(params))
        return poller_id

    def enqueue_run(self, poller_id: int, source: Optional[str] = None) -> int:
        now = self._now()
        sql = (
            "INSERT INTO poller_job (poller_id, trigger_type, status, requested_by, request_payload, created_at) VALUES (%s,%s,%s,%s,%s,%s)"
            if self.backend == "mysql"
            else "INSERT INTO poller_job (poller_id, trigger_type, status, requested_by, request_payload, created_at) VALUES (?,?,?,?,?,?)"
        )
        payload = '{"source":"' + (source or "api") + '"}'
        return int(self._execute(sql, (int(poller_id), "manual", "queued", source or "api", payload, now)) or 0)

    def list_jobs(self, limit: int = 30) -> List[Dict[str, Any]]:
        lim = max(1, int(limit))
        ph = "%s" if self.backend == "mysql" else "?"
        rows = self._query(
            f"SELECT id, poller_id, status, rows_collected, modems_attempted, modems_succeeded, modems_failed, error_text, started_at, finished_at, created_at FROM poller_job ORDER BY id DESC LIMIT {ph}",
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
            "SELECT id, status FROM poller_job WHERE id=%s" if self.backend == "mysql" else "SELECT id, status FROM poller_job WHERE id=?",
            (int(job_id),),
        )
        if not rows:
            return {"killed": 0, "state": "not_found"}

        state = str((rows[0] or {}).get("status") or "").lower()
        if state in {"done", "failed", "cancelled", "timed_out", "completed"}:
            return {"killed": 0, "state": state}

        self._execute(
            "UPDATE poller_job SET status=%s, finished_at=%s, error_text=%s WHERE id=%s AND status IN ('queued','running')"
            if self.backend == "mysql"
            else "UPDATE poller_job SET status=?, finished_at=?, error_text=? WHERE id=? AND status IN ('queued','running')",
            ("cancelled", self._now(), "Killed by admin", int(job_id)),
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

    def run_scheduler_once(self) -> int:
        self._scheduler["running"] = True
        tick_iso = datetime.now(timezone.utc).isoformat()
        tick_sql = self._now()
        self._scheduler["last_tick"] = tick_iso
        queued = 0
        decisions = []
        pollers = self._query("SELECT id, name, enabled, interval_minutes FROM poller_setting ORDER BY id ASC")
        for p in pollers:
            pid = int(p.get("id") or 0)
            if pid <= 0:
                continue
            pname = p.get("name") or f"poller-{pid}"

            if int(p.get("enabled") or 0) != 1:
                decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "disabled"})
                continue

            active = self._query(
                "SELECT id FROM poller_job WHERE poller_id=%s AND status IN ('queued','running') LIMIT 1"
                if self.backend == "mysql"
                else "SELECT id FROM poller_job WHERE poller_id=? AND status IN ('queued','running') LIMIT 1",
                (pid,),
            )
            if active:
                decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "active_job_exists"})
                continue

            minutes = max(1, int(p.get("interval_minutes") or 1440))
            if self.backend == "mysql":
                due = self._query(
                    """
                    SELECT id FROM poller_job
                    WHERE poller_id=%s
                      AND created_at >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
                    LIMIT 1
                    """,
                    (pid, minutes),
                )
            else:
                due = self._query(
                    """
                    SELECT id FROM poller_job
                    WHERE poller_id=?
                      AND created_at >= datetime('now', ?)
                    LIMIT 1
                    """,
                    (pid, f"-{minutes} minute"),
                )
            if due:
                decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "interval_not_due"})
                continue

            self.enqueue_run(pid, source="scheduler")
            queued += 1
            decisions.append({"poller_id": pid, "poller_name": pname, "decision": "queued", "reason": "ok"})

        self._scheduler["decisions"] = decisions[:100]
        self._log_scheduler_decisions(tick_sql, decisions)
        self._scheduler["running"] = False
        return queued

    def snapshots_by_day(self, lookback_days: int = 14, limit: int = 300) -> List[Dict[str, Any]]:
        capped_days = max(1, int(lookback_days))
        capped_limit = max(1, int(limit))
        max_rows = min(capped_days, capped_limit)
        rows = []

        if self.backend == "mysql":
            raw = self._query(
                """
                SELECT DATE(collected_at) AS d, COUNT(*) AS snapshot_count
                FROM modem_rf_snapshot
                WHERE collected_at >= (UTC_TIMESTAMP() - INTERVAL %s DAY)
                GROUP BY DATE(collected_at)
                ORDER BY d DESC
                LIMIT %s
                """,
                (capped_days, max_rows),
            )
            for idx, r in enumerate(raw):
                rows.append({"day_offset": idx, "snapshot_count": int(r.get("snapshot_count") or 0)})
            return rows

        raw = self._query(
            """
            SELECT DATE(collected_at) AS d, COUNT(*) AS snapshot_count
            FROM modem_rf_snapshot
            WHERE collected_at >= datetime('now', ?)
            GROUP BY DATE(collected_at)
            ORDER BY d DESC
            LIMIT ?
            """,
            (f"-{capped_days} day", max_rows),
        )
        for idx, r in enumerate(raw):
            rows.append({"day_offset": idx, "snapshot_count": int(r.get("snapshot_count") or 0)})
        return rows

    def snapshots_analytics(self, lookback_days: int = 14) -> Dict[str, Any]:
        days = max(1, int(lookback_days))
        if self.backend == "mysql":
            raw = self._query(
                "SELECT COUNT(*) AS c FROM modem_rf_snapshot WHERE collected_at >= (UTC_TIMESTAMP() - INTERVAL %s DAY)",
                (days,),
            )
        else:
            raw = self._query(
                "SELECT COUNT(*) AS c FROM modem_rf_snapshot WHERE collected_at >= datetime('now', ?)",
                (f"-{days} day",),
            )

        total = int((raw[0] or {}).get("c") or 0) if raw else 0
        return {
            "lookback_days": days,
            "total_snapshots": total,
            "avg_per_day": round(total / days, 2),
        }

    def list_inventory_modems(
        self,
        cmts: Optional[str] = None,
        search_type: Optional[str] = None,
        search_value: Optional[str] = None,
        interface_filter: Optional[str] = None,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 10000), 50000))
        where = []
        params: List[Any] = []

        if cmts:
            where.append(f"cmts={'%s' if self.backend == 'mysql' else '?'}")
            params.append(cmts)

        if search_value:
            sv = f"%{str(search_value).lower()}%"
            marker = "%s" if self.backend == "mysql" else "?"
            if search_type == "ip":
                where.append(f"LOWER(COALESCE(ip,'')) LIKE {marker}")
                params.append(sv)
            elif search_type == "mac":
                expr = "LOWER(REPLACE(REPLACE(COALESCE(mac,''),':',''),'-',''))"
                where.append(f"{expr} LIKE {marker}")
                params.append(str(search_value).lower().replace(":", "").replace("-", ""))
            elif search_type == "name":
                where.append(
                    f"(LOWER(COALESCE(vendor,'')) LIKE {marker} OR LOWER(COALESCE(model,'')) LIKE {marker} OR LOWER(COALESCE(fiber_node,'')) LIKE {marker})"
                )
                params.extend([sv, sv, sv])

        if interface_filter:
            marker = "%s" if self.backend == "mysql" else "?"
            where.append(f"(LOWER(COALESCE(upstream_interface,'')) LIKE {marker} OR LOWER(COALESCE(cable_mac,'')) LIKE {marker})")
            params.append(f"%{str(interface_filter).lower()}%")

        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        marker = "%s" if self.backend == "mysql" else "?"
        rows = self._query(
            "SELECT mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version, vendor, model, "
            "upstream_interface, ofdm_enabled, ofdma_enabled, partial_service, updated_at "
            f"FROM modem_inventory_current{where_sql} ORDER BY cmts ASC, mac ASC LIMIT {marker}",
            tuple(params + [limit]),
        )
        return [self._map_inventory_row(row) for row in rows]

    def get_inventory_modem_by_mac(self, mac_address: str) -> Optional[Dict[str, Any]]:
        marker = "%s" if self.backend == "mysql" else "?"
        mac_norm = (mac_address or "").lower().replace(":", "").replace("-", "")
        rows = self._query(
            "SELECT mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version, vendor, model, "
            "upstream_interface, ofdm_enabled, ofdma_enabled, partial_service, updated_at "
            f"FROM modem_inventory_current WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = {marker} LIMIT 1",
            (mac_norm,),
        )
        return self._map_inventory_row(rows[0]) if rows else None

    def _map_inventory_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "mac_address": row.get("mac"),
            "ip_address": row.get("ip"),
            "cmts": row.get("cmts"),
            "cmts_ip": row.get("cmts_ip"),
            "fiber_node": row.get("fiber_node"),
            "cable_mac": row.get("cable_mac"),
            "status": row.get("status"),
            "docsis_version": row.get("docsis_version"),
            "vendor": row.get("vendor"),
            "model": row.get("model"),
            "upstream_interface": row.get("upstream_interface"),
            "ofdm_enabled": row.get("ofdm_enabled"),
            "ofdma_enabled": row.get("ofdma_enabled"),
            "partial_service": row.get("partial_service"),
            "updated_at": row.get("updated_at"),
        }


poller_service = PollerService()
