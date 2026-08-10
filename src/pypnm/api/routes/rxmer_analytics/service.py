# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pymysql
import pymysql.cursors

SCHEMA_VERSION = 2
_SPECTRUM_GRID_HZ = 25_000
_SPECTRUM_MAX_GRID_POINTS = 100_000
_MAX_COLLECTION_CONCURRENCY = 20
_DEFAULT_COLLECTION_CONCURRENCY = 10
_ONLINE_STATUSES = ("operational", "registrationComplete", "ipComplete", "online")


class RxMerAnalyticsService:
    """Persistence boundary for durable RxMER plans and future collection jobs."""

    def __init__(self) -> None:
        self._schema_lock = threading.Lock()
        self._schema_initialized = False
        self._tls = threading.local()

    @staticmethod
    def _db_name() -> str:
        return os.environ.get("DATA_DB_NAME") or os.environ.get("AUTH_DB_NAME") or "pypnm_auth"

    def _connect(self, *, autocommit: bool = True):
        return pymysql.connect(
            host=os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DATA_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306")),
            user=os.environ.get("DATA_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm"),
            password=os.environ.get("DATA_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm"),
            database=self._db_name(),
            autocommit=autocommit,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )

    def _get_conn(self):
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
        self._tls.conn = self._connect()
        return self._tls.conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return int(cursor.lastrowid or 0)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            self._tls.conn = None
            raise

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            self._tls.conn = None
            raise

    def ensure_schema(self) -> None:
        if self._schema_initialized:
            return
        with self._schema_lock:
            if self._schema_initialized:
                return
            for statement in self._schema_statements():
                self._execute(statement)
            self._schema_initialized = True

    @staticmethod
    def _schema_statements() -> tuple[str, ...]:
        return (
            """
            CREATE TABLE IF NOT EXISTS rxmer_schedule (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(128) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                scope_json JSON NOT NULL,
                interval_minutes INT NOT NULL DEFAULT 360,
                next_slot_utc DATETIME NULL,
                raw_retention_days INT NOT NULL DEFAULT 7,
                aggregate_retention_days INT NOT NULL DEFAULT 90,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_rxmer_schedule_name (name),
                INDEX idx_rxmer_schedule_due (enabled, next_slot_utc)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_job (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                public_id CHAR(36) NOT NULL,
                schedule_id BIGINT NULL,
                parent_job_id BIGINT NULL,
                trigger_type VARCHAR(24) NOT NULL,
                status VARCHAR(24) NOT NULL,
                scope_hash CHAR(64) NOT NULL,
                scope_json JSON NOT NULL,
                inventory_revision VARCHAR(64) NULL,
                scheduled_slot_utc DATETIME NULL,
                idempotency_key VARCHAR(128) NULL,
                requested_by VARCHAR(64) NULL,
                aggregate_revision BIGINT NOT NULL DEFAULT 0,
                targets_total INT NOT NULL DEFAULT 0,
                targets_running INT NOT NULL DEFAULT 0,
                targets_succeeded INT NOT NULL DEFAULT 0,
                targets_partial INT NOT NULL DEFAULT 0,
                targets_failed INT NOT NULL DEFAULT 0,
                channels_succeeded INT NOT NULL DEFAULT 0,
                channels_failed INT NOT NULL DEFAULT 0,
                error_text TEXT NULL,
                raw_retention_days INT NOT NULL DEFAULT 7,
                aggregate_retention_days INT NOT NULL DEFAULT 90,
                cancel_requested_at DATETIME NULL,
                lease_owner VARCHAR(128) NULL,
                lease_until DATETIME NULL,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_rxmer_job_public_id (public_id),
                UNIQUE KEY uk_rxmer_job_request_key (requested_by, idempotency_key),
                UNIQUE KEY uk_rxmer_job_schedule_slot (schedule_id, scheduled_slot_utc),
                INDEX idx_rxmer_job_status_created (status, created_at),
                INDEX idx_rxmer_job_finished (finished_at),
                INDEX idx_rxmer_job_parent (parent_job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_scope_lease (
                scope_key VARCHAR(64) PRIMARY KEY,
                active_job_id BIGINT NULL,
                lease_owner VARCHAR(128) NULL,
                lease_until DATETIME NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_rxmer_scope_lease_until (lease_until)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_job_target (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                job_id BIGINT NOT NULL,
                ordinal INT NOT NULL DEFAULT 0,
                mac VARCHAR(17) NOT NULL,
                modem_ip VARCHAR(45) NOT NULL,
                cmts VARCHAR(128) NOT NULL,
                cmts_ip VARCHAR(45) NULL,
                fiber_node VARCHAR(128) NULL,
                inventory_snapshot_id CHAR(36) NULL,
                state VARCHAR(24) NOT NULL DEFAULT 'planned',
                expected_channels INT NOT NULL DEFAULT 0,
                completed_channels INT NOT NULL DEFAULT 0,
                failed_channels INT NOT NULL DEFAULT 0,
                attempt_count INT NOT NULL DEFAULT 0,
                next_attempt_at DATETIME NULL,
                last_cm_agent_id VARCHAR(128) NULL,
                error_class VARCHAR(64) NULL,
                error_text TEXT NULL,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_rxmer_target_job_mac (job_id, mac),
                INDEX idx_rxmer_target_claim (job_id, state, next_attempt_at, id),
                INDEX idx_rxmer_target_cmts (job_id, cmts, state),
                INDEX idx_rxmer_target_mac_job (mac, job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_target_channel (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                target_id BIGINT NOT NULL,
                ifindex BIGINT NOT NULL,
                channel_id SMALLINT UNSIGNED NOT NULL,
                state VARCHAR(24) NOT NULL DEFAULT 'planned',
                attempt_count INT NOT NULL DEFAULT 0,
                successful_attempt_id BIGINT NULL,
                error_class VARCHAR(64) NULL,
                error_text TEXT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_rxmer_channel_target_ifindex (target_id, ifindex),
                INDEX idx_rxmer_channel_claim (target_id, state),
                INDEX idx_rxmer_channel_id_state (channel_id, state)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_capture_attempt (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                channel_target_id BIGINT NOT NULL,
                attempt_no INT NOT NULL,
                capture_key CHAR(64) NOT NULL,
                cm_agent_id VARCHAR(128) NULL,
                file_agent_id VARCHAR(128) NULL,
                state VARCHAR(24) NOT NULL,
                filename VARCHAR(255) NULL,
                started_at DATETIME NULL,
                uploaded_at DATETIME NULL,
                retrieved_at DATETIME NULL,
                finished_at DATETIME NULL,
                error_class VARCHAR(64) NULL,
                error_text TEXT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_rxmer_attempt_number (channel_target_id, attempt_no),
                UNIQUE KEY uk_rxmer_attempt_capture_key (capture_key),
                INDEX idx_rxmer_attempt_state_started (state, started_at),
                INDEX idx_rxmer_attempt_filename (filename)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_channel_result (
                capture_attempt_id BIGINT PRIMARY KEY,
                job_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                channel_id SMALLINT UNSIGNED NOT NULL,
                ifindex BIGINT NOT NULL,
                zero_frequency_hz BIGINT NOT NULL,
                first_active_index INT NOT NULL,
                spacing_hz INT NOT NULL,
                sample_count INT NOT NULL,
                sum_qdb BIGINT NOT NULL,
                avg_db DECIMAL(7,3) NOT NULL,
                best_qdb TINYINT UNSIGNED NOT NULL,
                best_subcarrier_index INT NOT NULL,
                best_frequency_hz BIGINT NOT NULL,
                vector_sha256 BINARY(32) NOT NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_rxmer_result_job_avg (job_id, avg_db),
                INDEX idx_rxmer_result_job_best (job_id, best_qdb),
                INDEX idx_rxmer_result_job_channel (job_id, channel_id, avg_db)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_vector (
                capture_attempt_id BIGINT PRIMARY KEY,
                codec VARCHAR(32) NOT NULL,
                uncompressed_bytes INT NOT NULL,
                compressed_bytes INT NOT NULL,
                payload MEDIUMBLOB NOT NULL,
                created_at DATETIME NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_modem_aggregate (
                job_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                mac VARCHAR(17) NOT NULL,
                cmts VARCHAR(128) NOT NULL,
                fiber_node VARCHAR(128) NULL,
                completeness VARCHAR(16) NOT NULL,
                valid_channel_count INT NOT NULL,
                sample_count INT NOT NULL,
                sum_qdb BIGINT NOT NULL,
                avg_db DECIMAL(7,3) NOT NULL,
                best_qdb TINYINT UNSIGNED NOT NULL,
                best_channel_id SMALLINT UNSIGNED NOT NULL,
                best_subcarrier_index INT NOT NULL,
                best_frequency_hz BIGINT NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (job_id, target_id),
                INDEX idx_rxmer_aggregate_job_avg (job_id, avg_db),
                INDEX idx_rxmer_aggregate_job_best (job_id, best_qdb),
                INDEX idx_rxmer_aggregate_cmts_avg (job_id, cmts, avg_db),
                INDEX idx_rxmer_aggregate_fiber_avg (job_id, fiber_node, avg_db)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_spectrum_build (
                job_id BIGINT PRIMARY KEY,
                source_revision BIGINT NOT NULL,
                state VARCHAR(16) NOT NULL,
                lease_owner VARCHAR(128) NULL,
                lease_until DATETIME NULL,
                source_channels INT NOT NULL DEFAULT 0,
                source_modems INT NOT NULL DEFAULT 0,
                source_samples BIGINT NOT NULL DEFAULT 0,
                frequency_start_hz BIGINT NULL,
                frequency_end_hz BIGINT NULL,
                point_count INT NOT NULL DEFAULT 0,
                error_text TEXT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_rxmer_spectrum_build_state (state, lease_until)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_spectrum_bin (
                job_id BIGINT NOT NULL,
                source_revision BIGINT NOT NULL,
                frequency_hz BIGINT NOT NULL,
                sample_count BIGINT NOT NULL,
                sum_qdb BIGINT NOT NULL,
                worst_qdb TINYINT UNSIGNED NOT NULL,
                max_qdb TINYINT UNSIGNED NOT NULL,
                PRIMARY KEY (job_id, source_revision, frequency_hz),
                INDEX idx_rxmer_spectrum_frequency
                    (job_id, source_revision, frequency_hz)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "schema_initialized": self._schema_initialized,
            "planning_enabled": True,
            "dispatch_enabled": True,
            "scheduler_enabled": False,
            "max_concurrency": _MAX_COLLECTION_CONCURRENCY,
            "default_concurrency": _DEFAULT_COLLECTION_CONCURRENCY,
            "max_inventory_modems": 50000,
            "spectrum_enabled": True,
            "spectrum_max_points": 4000,
            "scope_types": ["all_network", "cmts"],
        }

    @staticmethod
    def _scope_hash(scope: dict[str, Any], online_only: bool) -> str:
        canonical = json.dumps(
            {"scope": scope, "online_only": bool(online_only)},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _decode_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                return decoded if isinstance(decoded, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _job_row(self, row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["scope"] = self._decode_json(result.pop("scope_json", None))
        return result

    def create_plan(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Persist a read-only inventory snapshot; never dispatch remote work."""
        self.ensure_schema()
        scope = dict(payload.get("scope") or {})
        scope_type = str(scope.get("type") or "all_network")
        cmts_names = sorted({str(value).strip() for value in scope.get("cmts") or [] if str(value).strip()})
        if scope_type not in {"all_network", "cmts"}:
            raise ValueError("unsupported RxMER scope type")
        if scope_type == "cmts" and not cmts_names:
            raise ValueError("cmts scope requires at least one CMTS")
        if scope_type == "all_network" and cmts_names:
            raise ValueError("all_network scope cannot include CMTS selections")

        online_only = bool(payload.get("online_only", True))
        requested_by = str(payload.get("requested_by") or "api").strip()[:64]
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key is not None:
            idempotency_key = str(idempotency_key).strip()[:128]
        scope_document = {
            "type": scope_type,
            "cmts": cmts_names,
            "online_only": online_only,
            "channel_mode": "all",
        }
        scope_json = json.dumps(scope_document, sort_keys=True, separators=(",", ":"))
        scope_hash = self._scope_hash(scope_document, online_only)
        public_id = str(uuid.uuid4())
        now = self._now()

        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                if idempotency_key:
                    cursor.execute(
                        "SELECT public_id FROM rxmer_job WHERE requested_by=%s "
                        "AND idempotency_key=%s LIMIT 1",
                        (requested_by, idempotency_key),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        connection.rollback()
                        job = self.get_job(str(existing["public_id"]))
                        if not job:
                            raise RuntimeError("idempotent RxMER plan disappeared")
                        return job, True

                where_parts = [
                    "ip IS NOT NULL",
                    "TRIM(ip) NOT IN ('', 'N/A', '0.0.0.0', '::')",
                    "(ofdm_enabled=TRUE OR COALESCE(ofdm_channel_count, 0)>0 "
                    "OR COALESCE(ofdm_ifindex, 0)>0)",
                ]
                where_params: list[Any] = []
                if online_only:
                    placeholders = ",".join(["%s"] * len(_ONLINE_STATUSES))
                    where_parts.append(f"status IN ({placeholders})")
                    where_params.extend(_ONLINE_STATUSES)
                if scope_type == "cmts":
                    placeholders = ",".join(["%s"] * len(cmts_names))
                    where_parts.append(f"cmts IN ({placeholders})")
                    where_params.extend(cmts_names)
                where_sql = " AND ".join(where_parts)

                cursor.execute(
                    f"SELECT DATE_FORMAT(MAX(updated_at), '%%Y-%%m-%%dT%%H:%%i:%%sZ') AS revision "
                    f"FROM modem_inventory_current WHERE {where_sql}",
                    tuple(where_params),
                )
                revision_row = cursor.fetchone() or {}
                inventory_revision = revision_row.get("revision")

                cursor.execute(
                    """
                    INSERT INTO rxmer_job
                    (public_id, trigger_type, status, scope_hash, scope_json,
                     inventory_revision, idempotency_key, requested_by,
                     raw_retention_days, aggregate_retention_days, created_at, updated_at)
                    VALUES (%s, 'plan', 'planned', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        public_id,
                        scope_hash,
                        scope_json,
                        inventory_revision,
                        idempotency_key,
                        requested_by,
                        int(payload.get("raw_retention_days") or 7),
                        int(payload.get("aggregate_retention_days") or 90),
                        now,
                        now,
                    ),
                )
                job_id = int(cursor.lastrowid)

                cursor.execute(
                    f"""
                    INSERT INTO rxmer_job_target
                    (job_id, mac, modem_ip, cmts, cmts_ip, fiber_node,
                     inventory_snapshot_id, state, expected_channels,
                     created_at, updated_at)
                    SELECT %s, mac, ip, cmts, cmts_ip, fiber_node,
                           snapshot_id, 'planned', COALESCE(ofdm_channel_count, 0),
                           %s, %s
                    FROM modem_inventory_current
                    WHERE {where_sql}
                    ORDER BY cmts, mac
                    LIMIT 50000
                    """,
                    (job_id, now, now, *where_params),
                )
                target_count = int(cursor.rowcount or 0)
                if target_count <= 0:
                    raise ValueError("no eligible operational OFDM modems found in the selected inventory scope")
                cursor.execute(
                    "UPDATE rxmer_job SET targets_total=%s, updated_at=%s WHERE id=%s",
                    (target_count, now, job_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        job = self.get_job(public_id)
        if not job:
            raise RuntimeError("created RxMER plan could not be loaded")
        return job, False

    def get_job(self, public_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        rows = self._query(
            """
            SELECT id, public_id, trigger_type, status, scope_hash, scope_json,
                   inventory_revision, targets_total, targets_running,
                   targets_succeeded, targets_partial, targets_failed,
                   channels_succeeded, channels_failed, requested_by, error_text,
                   raw_retention_days, aggregate_retention_days,
                   started_at, finished_at, created_at, updated_at
            FROM rxmer_job WHERE public_id=%s LIMIT 1
            """,
            (public_id,),
        )
        return self._job_row(rows[0]) if rows else None

    def list_jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        self.ensure_schema()
        safe_limit = max(1, min(int(limit), 500))
        rows = self._query(
            """
            SELECT id, public_id, trigger_type, status, scope_hash, scope_json,
                   inventory_revision, targets_total, targets_running,
                   targets_succeeded, targets_partial, targets_failed,
                   channels_succeeded, channels_failed, requested_by, error_text,
                   raw_retention_days, aggregate_retention_days,
                   started_at, finished_at, created_at, updated_at
            FROM rxmer_job ORDER BY id DESC LIMIT %s
            """,
            (safe_limit,),
        )
        return [self._job_row(row) for row in rows]

    def list_targets(self, public_id: str, *, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        self.ensure_schema()
        job_rows = self._query("SELECT id FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not job_rows:
            raise KeyError(public_id)
        job_id = int(job_rows[0]["id"])
        safe_limit = max(1, min(int(limit), 1000))
        rows = self._query(
            """
            SELECT t.id, t.mac, t.modem_ip, t.cmts, t.cmts_ip, t.fiber_node,
                   t.inventory_snapshot_id, t.state, t.expected_channels,
                   t.completed_channels, t.failed_channels, t.attempt_count,
                   t.error_class, t.error_text, t.created_at, t.updated_at,
                   a.completeness, a.valid_channel_count, a.sample_count,
                   a.avg_db, (a.best_qdb / 4.0) AS best_db,
                   a.best_channel_id, a.best_subcarrier_index,
                   a.best_frequency_hz
            FROM rxmer_job_target t
            LEFT JOIN rxmer_modem_aggregate a
              ON a.job_id=t.job_id AND a.target_id=t.id
            WHERE t.job_id=%s AND t.id>%s ORDER BY t.id ASC LIMIT %s
            """,
            (job_id, max(0, int(cursor)), safe_limit + 1),
        )
        has_more = len(rows) > safe_limit
        page = rows[:safe_limit]
        next_cursor = int(page[-1]["id"]) if has_more and page else None
        return {"targets": page, "next_cursor": next_cursor, "has_more": has_more}

    def record_channel_result(
        self,
        *,
        target_id: int,
        channel_id: int,
        ifindex: int,
        zero_frequency_hz: int,
        first_active_index: int,
        spacing_hz: int,
        raw_vector: bytes,
        filename: str | None = None,
        cm_agent_id: str | None = None,
        file_agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist one decoded channel and refresh its modem aggregate."""
        from pypnm.api.routes.rxmer_analytics.analytics import CODEC, analyze_channel

        self.ensure_schema()
        metrics = analyze_channel(
            raw_vector,
            channel_id=channel_id,
            ifindex=ifindex,
            zero_frequency_hz=zero_frequency_hz,
            first_active_index=first_active_index,
            spacing_hz=spacing_hz,
        )
        now = self._now()
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT job_id, mac, cmts, fiber_node, expected_channels "
                    "FROM rxmer_job_target WHERE id=%s FOR UPDATE",
                    (int(target_id),),
                )
                target = cursor.fetchone()
                if not target:
                    raise KeyError(target_id)
                job_id = int(target["job_id"])

                cursor.execute(
                    """
                    INSERT INTO rxmer_target_channel
                    (target_id, ifindex, channel_id, state, created_at, updated_at)
                    VALUES (%s, %s, %s, 'running', %s, %s)
                    ON DUPLICATE KEY UPDATE channel_id=VALUES(channel_id),
                        state='running', updated_at=VALUES(updated_at)
                    """,
                    (target_id, ifindex, channel_id, now, now),
                )
                cursor.execute(
                    "SELECT id FROM rxmer_target_channel "
                    "WHERE target_id=%s AND ifindex=%s LIMIT 1",
                    (target_id, ifindex),
                )
                channel_target = cursor.fetchone()
                if not channel_target:
                    raise RuntimeError("RxMER channel target could not be loaded")
                channel_target_id = int(channel_target["id"])

                cursor.execute(
                    "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS attempt_no "
                    "FROM rxmer_capture_attempt WHERE channel_target_id=%s",
                    (channel_target_id,),
                )
                attempt_no = int((cursor.fetchone() or {}).get("attempt_no") or 1)
                capture_key = hashlib.sha256(
                    f"{target_id}:{ifindex}:{attempt_no}:{filename or ''}:{now}".encode("utf-8")
                ).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO rxmer_capture_attempt
                    (channel_target_id, attempt_no, capture_key, cm_agent_id,
                     file_agent_id, state, filename, started_at, retrieved_at,
                     finished_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'succeeded', %s,
                            %s, %s, %s, %s, %s)
                    """,
                    (
                        channel_target_id,
                        attempt_no,
                        capture_key,
                        cm_agent_id,
                        file_agent_id,
                        filename,
                        now,
                        now,
                        now,
                        now,
                        now,
                    ),
                )
                attempt_id = int(cursor.lastrowid)
                cursor.execute(
                    """
                    INSERT INTO rxmer_channel_result
                    (capture_attempt_id, job_id, target_id, channel_id, ifindex,
                     zero_frequency_hz, first_active_index, spacing_hz,
                     sample_count, sum_qdb, avg_db, best_qdb,
                     best_subcarrier_index, best_frequency_hz,
                     vector_sha256, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        attempt_id,
                        job_id,
                        target_id,
                        metrics.channel_id,
                        metrics.ifindex,
                        metrics.zero_frequency_hz,
                        metrics.first_active_index,
                        metrics.spacing_hz,
                        metrics.sample_count,
                        metrics.sum_qdb,
                        metrics.avg_db,
                        metrics.best_qdb,
                        metrics.best_subcarrier_index,
                        metrics.best_frequency_hz,
                        metrics.vector_sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO rxmer_vector
                    (capture_attempt_id, codec, uncompressed_bytes,
                     compressed_bytes, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        attempt_id,
                        CODEC,
                        len(metrics.normalized_vector),
                        len(metrics.compressed_vector),
                        metrics.compressed_vector,
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE rxmer_target_channel SET state='succeeded', "
                    "successful_attempt_id=%s, updated_at=%s WHERE id=%s",
                    (attempt_id, now, channel_target_id),
                )

                cursor.execute(
                    """
                    SELECT COUNT(*) AS valid_channel_count,
                           COALESCE(SUM(r.sample_count), 0) AS sample_count,
                           COALESCE(SUM(r.sum_qdb), 0) AS sum_qdb
                    FROM rxmer_target_channel c
                    JOIN rxmer_channel_result r
                      ON r.capture_attempt_id=c.successful_attempt_id
                    WHERE c.target_id=%s
                    """,
                    (target_id,),
                )
                totals = cursor.fetchone() or {}
                valid_channels = int(totals.get("valid_channel_count") or 0)
                sample_count = int(totals.get("sample_count") or 0)
                sum_qdb = int(totals.get("sum_qdb") or 0)
                cursor.execute(
                    """
                    SELECT r.best_qdb, r.channel_id, r.best_subcarrier_index,
                           r.best_frequency_hz
                    FROM rxmer_target_channel c
                    JOIN rxmer_channel_result r
                      ON r.capture_attempt_id=c.successful_attempt_id
                    WHERE c.target_id=%s
                    ORDER BY r.best_qdb DESC, r.best_frequency_hz ASC,
                             r.channel_id ASC LIMIT 1
                    """,
                    (target_id,),
                )
                best = cursor.fetchone() or {}
                expected_channels = int(target.get("expected_channels") or 0)
                completeness = (
                    "complete"
                    if expected_channels > 0 and valid_channels >= expected_channels
                    else "partial"
                )
                avg_db = sum_qdb / (4.0 * sample_count)
                cursor.execute(
                    """
                    INSERT INTO rxmer_modem_aggregate
                    (job_id, target_id, mac, cmts, fiber_node, completeness,
                     valid_channel_count, sample_count, sum_qdb, avg_db,
                     best_qdb, best_channel_id, best_subcarrier_index,
                     best_frequency_hz, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE completeness=VALUES(completeness),
                        valid_channel_count=VALUES(valid_channel_count),
                        sample_count=VALUES(sample_count), sum_qdb=VALUES(sum_qdb),
                        avg_db=VALUES(avg_db), best_qdb=VALUES(best_qdb),
                        best_channel_id=VALUES(best_channel_id),
                        best_subcarrier_index=VALUES(best_subcarrier_index),
                        best_frequency_hz=VALUES(best_frequency_hz),
                        updated_at=VALUES(updated_at)
                    """,
                    (
                        job_id,
                        target_id,
                        target["mac"],
                        target["cmts"],
                        target.get("fiber_node"),
                        completeness,
                        valid_channels,
                        sample_count,
                        sum_qdb,
                        avg_db,
                        int(best["best_qdb"]),
                        int(best["channel_id"]),
                        int(best["best_subcarrier_index"]),
                        int(best["best_frequency_hz"]),
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE rxmer_job_target SET state=%s, completed_channels=%s, "
                    "updated_at=%s WHERE id=%s",
                    (completeness, valid_channels, now, target_id),
                )
                cursor.execute(
                    "UPDATE rxmer_job SET aggregate_revision=aggregate_revision+1, "
                    "updated_at=%s WHERE id=%s",
                    (now, job_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "target_id": target_id,
            "channel_id": channel_id,
            "ifindex": ifindex,
            "avg_db": metrics.avg_db,
            "best_db": metrics.best_qdb / 4.0,
            "best_frequency_hz": metrics.best_frequency_hz,
            "sample_count": metrics.sample_count,
        }

    def aggregate_histograms(
        self,
        public_id: str,
        *,
        bucket_db: float = 0.5,
        cmts: str | None = None,
        fiber_node: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        bucket = float(bucket_db)
        if bucket < 0.25 or bucket > 5.0:
            raise ValueError("bucket_db must be between 0.25 and 5.0")
        jobs = self._query("SELECT id FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        filters = ["job_id=%s"]
        params: list[Any] = [job_id]
        if cmts:
            filters.append("cmts=%s")
            params.append(cmts)
        if fiber_node:
            filters.append("fiber_node=%s")
            params.append(fiber_node)
        where_sql = " AND ".join(filters)

        completeness_rows = self._query(
            f"SELECT completeness, COUNT(*) AS modem_count "
            f"FROM rxmer_modem_aggregate WHERE {where_sql} GROUP BY completeness",
            tuple(params),
        )
        average_rows = self._query(
            f"SELECT ROUND(FLOOR(avg_db / %s) * %s, 3) AS rxmer_db, "
            f"COUNT(*) AS modem_count FROM rxmer_modem_aggregate "
            f"WHERE {where_sql} GROUP BY rxmer_db ORDER BY rxmer_db",
            (bucket, bucket, *params),
        )
        best_rows = self._query(
            f"SELECT ROUND(FLOOR((best_qdb / 4.0) / %s) * %s, 3) AS rxmer_db, "
            f"COUNT(*) AS modem_count FROM rxmer_modem_aggregate "
            f"WHERE {where_sql} GROUP BY rxmer_db ORDER BY rxmer_db",
            (bucket, bucket, *params),
        )
        completeness = {
            str(row["completeness"]): int(row["modem_count"])
            for row in completeness_rows
        }
        return {
            "job_public_id": public_id,
            "total_modems": sum(completeness.values()),
            "completeness": completeness,
            "average_rxmer": [
                {"rxmer_db": float(row["rxmer_db"]), "modem_count": int(row["modem_count"])}
                for row in average_rows
            ],
            "best_subcarrier_rxmer": [
                {"rxmer_db": float(row["rxmer_db"]), "modem_count": int(row["modem_count"])}
                for row in best_rows
            ],
            "bucket_db": bucket,
        }
    def prepare_job_start(self, public_id: str, lease_owner: str) -> dict[str, Any]:
        """Atomically acquire the network lease and queue a planned/resumable job."""
        self.ensure_schema()
        now = self._now()
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE rxmer_job
                    SET status='interrupted', error_text='Recovered after expired worker lease',
                        updated_at=%s
                    WHERE public_id=%s
                      AND status IN ('queued','running','cancelling')
                      AND (lease_until IS NULL OR lease_until <= UTC_TIMESTAMP())
                    """,
                    (now, public_id),
                )
                cursor.execute(
                    "SELECT id, status FROM rxmer_job WHERE public_id=%s FOR UPDATE",
                    (public_id,),
                )
                job = cursor.fetchone()
                if not job:
                    raise KeyError(public_id)
                if str(job["status"]) not in {
                    "planned", "interrupted", "failed", "completed_with_errors"
                }:
                    raise RuntimeError(f"job cannot start from state {job['status']}")
                job_id = int(job["id"])
                cursor.execute(
                    """
                    INSERT INTO rxmer_scope_lease
                    (scope_key, active_job_id, lease_owner, lease_until, updated_at)
                    VALUES ('network-downstream-rxmer', NULL, NULL, NULL, %s)
                    ON DUPLICATE KEY UPDATE updated_at=updated_at
                    """,
                    (now,),
                )
                cursor.execute(
                    "SELECT active_job_id, lease_owner, "
                    "(lease_until > UTC_TIMESTAMP()) AS lease_active "
                    "FROM rxmer_scope_lease WHERE scope_key='network-downstream-rxmer' "
                    "FOR UPDATE"
                )
                lease = cursor.fetchone() or {}
                active_job_id = lease.get("active_job_id")
                if int(lease.get("lease_active") or 0) == 1 and active_job_id not in {None, job_id}:
                    raise RuntimeError(f"another RxMER job is active ({active_job_id})")

                cursor.execute(
                    "UPDATE rxmer_job_target SET state='planned', error_class=NULL, "
                    "error_text=NULL, updated_at=%s WHERE job_id=%s "
                    "AND state IN ('running','failed','partial')",
                    (now, job_id),
                )
                cursor.execute(
                    """
                    UPDATE rxmer_job
                    SET status='queued', error_text=NULL, cancel_requested_at=NULL,
                        lease_owner=%s,
                        lease_until=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE),
                        started_at=NULL, finished_at=NULL, updated_at=%s
                    WHERE id=%s
                    """,
                    (lease_owner, now, job_id),
                )
                cursor.execute(
                    """
                    UPDATE rxmer_scope_lease
                    SET active_job_id=%s, lease_owner=%s,
                        lease_until=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE),
                        updated_at=%s
                    WHERE scope_key='network-downstream-rxmer'
                    """,
                    (job_id, lease_owner, now),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        result = self.get_job(public_id)
        if not result:
            raise RuntimeError("queued RxMER job disappeared")
        return result

    def activate_job(self, public_id: str, lease_owner: str) -> int:
        self.ensure_schema()
        updated = self._execute(
            "UPDATE rxmer_job SET status='running', started_at=COALESCE(started_at,%s), "
            "updated_at=%s WHERE public_id=%s AND status='queued' AND lease_owner=%s",
            (self._now(), self._now(), public_id, lease_owner),
        )
        rows = self._query(
            "SELECT id FROM rxmer_job WHERE public_id=%s AND status='running' "
            "AND lease_owner=%s LIMIT 1",
            (public_id, lease_owner),
        )
        if not rows:
            raise RuntimeError("RxMER job lease was lost before activation")
        return int(rows[0]["id"])

    def heartbeat_job(self, job_id: int, lease_owner: str) -> None:
        now = self._now()
        self._execute(
            "UPDATE rxmer_job SET lease_until=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE), "
            "updated_at=%s WHERE id=%s AND lease_owner=%s AND status IN ('queued','running','cancelling')",
            (now, job_id, lease_owner),
        )
        self._execute(
            "UPDATE rxmer_scope_lease SET lease_until=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 MINUTE), "
            "updated_at=%s WHERE scope_key='network-downstream-rxmer' "
            "AND active_job_id=%s AND lease_owner=%s",
            (now, job_id, lease_owner),
        )

    def claim_targets(self, job_id: int, limit: int) -> list[dict[str, Any]]:
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, mac, modem_ip, cmts, cmts_ip, fiber_node, expected_channels "
                    "FROM rxmer_job_target WHERE job_id=%s AND state='planned' "
                    "ORDER BY id ASC LIMIT %s FOR UPDATE SKIP LOCKED",
                    (job_id, max(1, min(int(limit), _MAX_COLLECTION_CONCURRENCY))),
                )
                targets = list(cursor.fetchall())
                if targets:
                    ids = [int(row["id"]) for row in targets]
                    placeholders = ",".join(["%s"] * len(ids))
                    cursor.execute(
                        f"UPDATE rxmer_job_target SET state='running', "
                        f"attempt_count=attempt_count+1, started_at=COALESCE(started_at,%s), "
                        f"updated_at=%s WHERE id IN ({placeholders}) AND state='planned'",
                        (self._now(), self._now(), *ids),
                    )
            connection.commit()
            return targets
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def job_cancel_requested(self, job_id: int) -> bool:
        rows = self._query(
            "SELECT status, cancel_requested_at FROM rxmer_job WHERE id=%s LIMIT 1",
            (job_id,),
        )
        return bool(
            rows
            and (
                str(rows[0].get("status") or "") == "cancelling"
                or rows[0].get("cancel_requested_at") is not None
            )
        )

    def request_cancel(self, public_id: str) -> dict[str, Any]:
        self.ensure_schema()
        rows = self._query("SELECT id, status FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not rows:
            raise KeyError(public_id)
        current = str(rows[0].get("status") or "")
        if current in {"queued", "running", "cancelling"}:
            self._execute(
                "UPDATE rxmer_job SET status='cancelling', cancel_requested_at=%s, "
                "updated_at=%s WHERE id=%s",
                (self._now(), self._now(), int(rows[0]["id"])),
            )
        result = self.get_job(public_id)
        if not result:
            raise KeyError(public_id)
        return result

    def successful_ifindexes(self, target_id: int) -> set[int]:
        rows = self._query(
            "SELECT ifindex FROM rxmer_target_channel "
            "WHERE target_id=%s AND state='succeeded' AND successful_attempt_id IS NOT NULL",
            (target_id,),
        )
        return {int(row["ifindex"]) for row in rows}

    def update_expected_channels(self, target_id: int, count: int) -> None:
        self._execute(
            "UPDATE rxmer_job_target SET expected_channels=%s, updated_at=%s WHERE id=%s",
            (max(0, int(count)), self._now(), target_id),
        )

    def mark_channel_failure(
        self, target_id: int, ifindex: int, channel_id: int, error_text: str
    ) -> None:
        now = self._now()
        self._execute(
            """
            INSERT INTO rxmer_target_channel
            (target_id, ifindex, channel_id, state, attempt_count,
             error_class, error_text, created_at, updated_at)
            VALUES (%s, %s, %s, 'failed', 1, 'capture_error', %s, %s, %s)
            ON DUPLICATE KEY UPDATE state='failed',
                attempt_count=attempt_count+1, error_class='capture_error',
                error_text=VALUES(error_text), updated_at=VALUES(updated_at)
            """,
            (target_id, ifindex, channel_id, error_text[:2000], now, now),
        )

    def finish_target(self, target_id: int, error_text: str | None = None) -> None:
        rows = self._query(
            """
            SELECT t.expected_channels,
                   SUM(CASE WHEN c.state='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                   SUM(CASE WHEN c.state='failed' THEN 1 ELSE 0 END) AS failed
            FROM rxmer_job_target t
            LEFT JOIN rxmer_target_channel c ON c.target_id=t.id
            WHERE t.id=%s GROUP BY t.id, t.expected_channels
            """,
            (target_id,),
        )
        if not rows:
            raise KeyError(target_id)
        row = rows[0]
        expected = int(row.get("expected_channels") or 0)
        succeeded = int(row.get("succeeded") or 0)
        failed = int(row.get("failed") or 0)
        if expected > 0 and succeeded >= expected and failed == 0:
            state = "complete"
        elif succeeded > 0:
            state = "partial"
        else:
            state = "failed"
        self._execute(
            "UPDATE rxmer_job_target SET state=%s, completed_channels=%s, "
            "failed_channels=%s, error_class=%s, error_text=%s, finished_at=%s, "
            "updated_at=%s WHERE id=%s",
            (
                state,
                succeeded,
                failed,
                "capture_error" if state != "complete" else None,
                error_text[:2000] if error_text else None,
                self._now(),
                self._now(),
                target_id,
            ),
        )

    def refresh_job_progress(self, job_id: int) -> None:
        counts = self._query(
            """
            SELECT SUM(CASE WHEN state='running' THEN 1 ELSE 0 END) AS running,
                   SUM(CASE WHEN state='complete' THEN 1 ELSE 0 END) AS succeeded,
                   SUM(CASE WHEN state='partial' THEN 1 ELSE 0 END) AS partial,
                   SUM(CASE WHEN state='failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(completed_channels) AS channels_succeeded,
                   SUM(failed_channels) AS channels_failed
            FROM rxmer_job_target WHERE job_id=%s
            """,
            (job_id,),
        )[0]
        self._execute(
            """
            UPDATE rxmer_job SET targets_running=%s, targets_succeeded=%s,
                targets_partial=%s, targets_failed=%s,
                channels_succeeded=%s, channels_failed=%s, updated_at=%s
            WHERE id=%s AND status IN ('queued','running','cancelling')
            """,
            (
                int(counts.get("running") or 0),
                int(counts.get("succeeded") or 0),
                int(counts.get("partial") or 0),
                int(counts.get("failed") or 0),
                int(counts.get("channels_succeeded") or 0),
                int(counts.get("channels_failed") or 0),
                self._now(),
                job_id,
            ),
        )

    def finish_job(self, job_id: int, lease_owner: str, error_text: str | None = None) -> str:
        rows = self._query(
            "SELECT status, cancel_requested_at FROM rxmer_job WHERE id=%s LIMIT 1",
            (job_id,),
        )
        cancelling = bool(
            rows
            and (
                str(rows[0].get("status") or "") == "cancelling"
                or rows[0].get("cancel_requested_at") is not None
            )
        )
        counts = self._query(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN state='complete' THEN 1 ELSE 0 END) AS succeeded,
                   SUM(CASE WHEN state='partial' THEN 1 ELSE 0 END) AS partial,
                   SUM(CASE WHEN state='failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(completed_channels) AS channels_succeeded,
                   SUM(failed_channels) AS channels_failed
            FROM rxmer_job_target WHERE job_id=%s
            """,
            (job_id,),
        )[0]
        succeeded = int(counts.get("succeeded") or 0)
        partial = int(counts.get("partial") or 0)
        failed = int(counts.get("failed") or 0)
        if cancelling:
            status = "cancelled"
        elif succeeded == 0 and partial == 0:
            status = "failed"
        elif partial or failed:
            status = "completed_with_errors"
        else:
            status = "completed"
        self._execute(
            """
            UPDATE rxmer_job SET status=%s, targets_running=0,
                targets_succeeded=%s, targets_partial=%s, targets_failed=%s,
                channels_succeeded=%s, channels_failed=%s, error_text=%s,
                finished_at=%s, lease_until=NULL, updated_at=%s
            WHERE id=%s AND lease_owner=%s
            """,
            (
                status,
                succeeded,
                partial,
                failed,
                int(counts.get("channels_succeeded") or 0),
                int(counts.get("channels_failed") or 0),
                error_text[:2000] if error_text else None,
                self._now(),
                self._now(),
                job_id,
                lease_owner,
            ),
        )
        self._execute(
            "UPDATE rxmer_scope_lease SET active_job_id=NULL, lease_owner=NULL, "
            "lease_until=NULL, updated_at=%s WHERE scope_key='network-downstream-rxmer' "
            "AND active_job_id=%s AND lease_owner=%s",
            (self._now(), job_id, lease_owner),
        )
        return status

    def interrupt_job(self, job_id: int, lease_owner: str, error_text: str) -> None:
        self._execute(
            "UPDATE rxmer_job_target SET state='planned', updated_at=%s "
            "WHERE job_id=%s AND state='running'",
            (self._now(), job_id),
        )
        self._execute(
            "UPDATE rxmer_job SET status='interrupted', error_text=%s, "
            "lease_until=NULL, updated_at=%s WHERE id=%s AND lease_owner=%s",
            (error_text[:2000], self._now(), job_id, lease_owner),
        )
        self._execute(
            "UPDATE rxmer_scope_lease SET active_job_id=NULL, lease_owner=NULL, "
            "lease_until=NULL, updated_at=%s WHERE scope_key='network-downstream-rxmer' "
            "AND active_job_id=%s AND lease_owner=%s",
            (self._now(), job_id, lease_owner),
        )

    def _lock_job_for_cleanup(self, cursor, public_id: str) -> dict[str, Any]:
        cursor.execute(
            "SELECT id, status, lease_owner, "
            "(lease_until > UTC_TIMESTAMP()) AS lease_active "
            "FROM rxmer_job WHERE public_id=%s FOR UPDATE",
            (public_id,),
        )
        job = cursor.fetchone()
        if not job:
            raise KeyError(public_id)
        job_id = int(job["id"])
        if str(job.get("status") or "") in {"queued", "running", "cancelling"}:
            raise RuntimeError("active RxMER jobs must be cancelled before deletion")
        if bool(job.get("lease_active")):
            raise RuntimeError("RxMER job still has an active worker lease")

        cursor.execute(
            "SELECT active_job_id, lease_owner, "
            "(lease_until > UTC_TIMESTAMP()) AS lease_active "
            "FROM rxmer_scope_lease WHERE scope_key='network-downstream-rxmer' "
            "FOR UPDATE"
        )
        scope_lease = cursor.fetchone() or {}
        if (
            scope_lease.get("active_job_id") is not None
            and int(scope_lease["active_job_id"]) == job_id
            and bool(scope_lease.get("lease_active"))
        ):
            raise RuntimeError("RxMER job still owns the active network lease")

        cursor.execute(
            "SELECT state, (lease_until > UTC_TIMESTAMP()) AS lease_active "
            "FROM rxmer_spectrum_build WHERE job_id=%s FOR UPDATE",
            (job_id,),
        )
        spectrum_build = cursor.fetchone() or {}
        if (
            str(spectrum_build.get("state") or "") == "building"
            and bool(spectrum_build.get("lease_active"))
        ):
            raise RuntimeError("spectrum materialization is still active")
        return job

    @staticmethod
    def _delete_result_rows(cursor, job_id: int) -> None:
        cursor.execute("DELETE FROM rxmer_spectrum_bin WHERE job_id=%s", (job_id,))
        cursor.execute("DELETE FROM rxmer_spectrum_build WHERE job_id=%s", (job_id,))
        cursor.execute("DELETE FROM rxmer_modem_aggregate WHERE job_id=%s", (job_id,))
        cursor.execute(
            """
            UPDATE rxmer_target_channel c
            JOIN rxmer_job_target t ON t.id=c.target_id
            SET c.successful_attempt_id=NULL
            WHERE t.job_id=%s
            """,
            (job_id,),
        )
        cursor.execute(
            """
            DELETE v FROM rxmer_vector v
            JOIN rxmer_capture_attempt a ON a.id=v.capture_attempt_id
            JOIN rxmer_target_channel c ON c.id=a.channel_target_id
            JOIN rxmer_job_target t ON t.id=c.target_id
            WHERE t.job_id=%s
            """,
            (job_id,),
        )
        cursor.execute("DELETE FROM rxmer_channel_result WHERE job_id=%s", (job_id,))
        cursor.execute(
            """
            DELETE a FROM rxmer_capture_attempt a
            JOIN rxmer_target_channel c ON c.id=a.channel_target_id
            JOIN rxmer_job_target t ON t.id=c.target_id
            WHERE t.job_id=%s
            """,
            (job_id,),
        )
        cursor.execute(
            """
            DELETE c FROM rxmer_target_channel c
            JOIN rxmer_job_target t ON t.id=c.target_id
            WHERE t.job_id=%s
            """,
            (job_id,),
        )

    def clear_job_results(self, public_id: str) -> dict[str, Any]:
        """Delete collected data while retaining and resetting the inventory plan."""
        self.ensure_schema()
        now = self._now()
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                job = self._lock_job_for_cleanup(cursor, public_id)
                job_id = int(job["id"])
                self._delete_result_rows(cursor, job_id)
                cursor.execute(
                    """
                    UPDATE rxmer_job_target
                    SET state='planned', completed_channels=0, failed_channels=0,
                        attempt_count=0, next_attempt_at=NULL,
                        last_cm_agent_id=NULL, error_class=NULL, error_text=NULL,
                        started_at=NULL, finished_at=NULL, updated_at=%s
                    WHERE job_id=%s
                    """,
                    (now, job_id),
                )
                cursor.execute(
                    """
                    UPDATE rxmer_job
                    SET status='planned', aggregate_revision=aggregate_revision+1,
                        targets_running=0, targets_succeeded=0, targets_partial=0,
                        targets_failed=0, channels_succeeded=0, channels_failed=0,
                        error_text=NULL, cancel_requested_at=NULL,
                        lease_owner=NULL, lease_until=NULL,
                        started_at=NULL, finished_at=NULL, updated_at=%s
                    WHERE id=%s
                    """,
                    (now, job_id),
                )
                cursor.execute(
                    """
                    UPDATE rxmer_scope_lease
                    SET active_job_id=NULL, lease_owner=NULL, lease_until=NULL,
                        updated_at=%s
                    WHERE scope_key='network-downstream-rxmer'
                      AND active_job_id=%s
                    """,
                    (now, job_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        job = self.get_job(public_id)
        if not job:
            raise RuntimeError("reset RxMER job disappeared")
        return job

    def delete_job(self, public_id: str) -> None:
        """Delete an inactive RxMER job and all analytics-owned rows."""
        self.ensure_schema()
        now = self._now()
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                job = self._lock_job_for_cleanup(cursor, public_id)
                job_id = int(job["id"])
                cursor.execute(
                    "SELECT COUNT(*) AS child_count FROM rxmer_job "
                    "WHERE parent_job_id=%s",
                    (job_id,),
                )
                child_count = int((cursor.fetchone() or {}).get("child_count") or 0)
                if child_count:
                    raise RuntimeError("RxMER job has child jobs and cannot be deleted")
                self._delete_result_rows(cursor, job_id)
                cursor.execute("DELETE FROM rxmer_job_target WHERE job_id=%s", (job_id,))
                cursor.execute(
                    """
                    UPDATE rxmer_scope_lease
                    SET active_job_id=NULL, lease_owner=NULL, lease_until=NULL,
                        updated_at=%s
                    WHERE scope_key='network-downstream-rxmer'
                      AND active_job_id=%s
                    """,
                    (now, job_id),
                )
                cursor.execute("DELETE FROM rxmer_job WHERE id=%s", (job_id,))
                if cursor.rowcount != 1:
                    raise RuntimeError("RxMER job could not be deleted")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def request_spectrum_build(self, public_id: str) -> dict[str, Any]:
        """Acquire a DB lease for post-processing persisted RxMER vectors."""
        self.ensure_schema()
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, status, aggregate_revision FROM rxmer_job "
                    "WHERE public_id=%s FOR UPDATE",
                    (public_id,),
                )
                job = cursor.fetchone()
                if not job:
                    raise KeyError(public_id)
                job_status = str(job.get("status") or "")
                if job_status in {"planned", "queued", "running", "cancelling"}:
                    raise ValueError("spectrum materialization is available after collection stops")
                job_id = int(job["id"])
                revision = int(job.get("aggregate_revision") or 0)
                cursor.execute(
                    "SELECT source_revision, state, "
                    "(lease_until > UTC_TIMESTAMP()) AS lease_active "
                    "FROM rxmer_spectrum_build WHERE job_id=%s FOR UPDATE",
                    (job_id,),
                )
                existing = cursor.fetchone() or {}
                current_revision = int(existing.get("source_revision") or -1)
                existing_state = str(existing.get("state") or "")
                if current_revision == revision and existing_state == "ready":
                    connection.commit()
                    return {
                        "job_public_id": public_id,
                        "state": "ready",
                        "queued": False,
                        "message": "Spectrum profile is already current",
                    }
                if (
                    current_revision == revision
                    and existing_state == "building"
                    and bool(existing.get("lease_active"))
                ):
                    connection.commit()
                    return {
                        "job_public_id": public_id,
                        "state": "building",
                        "queued": False,
                        "message": "Spectrum profile is already building",
                    }

                owner = f"rxmer-spectrum-{uuid.uuid4()}"
                now = self._now()
                cursor.execute(
                    """
                    INSERT INTO rxmer_spectrum_build
                    (job_id, source_revision, state, lease_owner, lease_until,
                     source_channels, source_modems, source_samples,
                     frequency_start_hz, frequency_end_hz, point_count,
                     error_text, created_at, updated_at)
                    VALUES (%s, %s, 'building', %s,
                            DATE_ADD(UTC_TIMESTAMP(), INTERVAL 10 MINUTE),
                            0, 0, 0, NULL, NULL, 0, NULL, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        source_revision=VALUES(source_revision), state='building',
                        lease_owner=VALUES(lease_owner), lease_until=VALUES(lease_until),
                        source_channels=0, source_modems=0, source_samples=0,
                        frequency_start_hz=NULL, frequency_end_hz=NULL,
                        point_count=0, error_text=NULL, updated_at=VALUES(updated_at)
                    """,
                    (job_id, revision, owner, now, now),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "job_public_id": public_id,
            "state": "building",
            "queued": True,
            "message": "Spectrum post-processing queued",
            "_job_id": job_id,
            "_source_revision": revision,
            "_lease_owner": owner,
        }

    def materialize_spectrum(self, job_id: int, source_revision: int, lease_owner: str) -> None:
        """Build an exact 25 kHz rollup from stored vectors; never contacts modems."""
        from pypnm.api.routes.rxmer_analytics.analytics import CODEC, decode_vector

        connection = self._connect(autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS source_channels,
                           COUNT(DISTINCT r.target_id) AS source_modems,
                           COALESCE(SUM(r.sample_count), 0) AS source_samples,
                           MIN(r.zero_frequency_hz +
                               r.first_active_index * r.spacing_hz) AS start_hz,
                           MAX(r.zero_frequency_hz +
                               (r.first_active_index + r.sample_count - 1) *
                               r.spacing_hz) AS end_hz
                    FROM rxmer_channel_result r
                    JOIN rxmer_target_channel c
                      ON c.successful_attempt_id=r.capture_attempt_id
                    WHERE r.job_id=%s
                    """,
                    (job_id,),
                )
                stats = cursor.fetchone() or {}
            source_channels = int(stats.get("source_channels") or 0)
            source_modems = int(stats.get("source_modems") or 0)
            source_samples = int(stats.get("source_samples") or 0)
            start_hz = int(stats.get("start_hz") or 0)
            end_hz = int(stats.get("end_hz") or 0)

            if source_channels == 0:
                self._finish_empty_spectrum_build(
                    job_id, source_revision, lease_owner,
                )
                return

            grid_start_hz = (start_hz // _SPECTRUM_GRID_HZ) * _SPECTRUM_GRID_HZ
            grid_end_hz = (
                math.ceil(end_hz / _SPECTRUM_GRID_HZ) * _SPECTRUM_GRID_HZ
            )
            grid_points = ((grid_end_hz - grid_start_hz) // _SPECTRUM_GRID_HZ) + 1
            if grid_points <= 0 or grid_points > _SPECTRUM_MAX_GRID_POINTS:
                raise ValueError("RxMER spectrum frequency range exceeds the supported grid")

            counts = np.zeros(grid_points, dtype=np.uint64)
            sums = np.zeros(grid_points, dtype=np.uint64)
            worst = np.full(grid_points, 255, dtype=np.uint16)
            maximum = np.zeros(grid_points, dtype=np.uint8)
            last_attempt_id = 0
            processed_channels = 0
            while True:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT r.capture_attempt_id, r.zero_frequency_hz,
                               r.first_active_index, r.spacing_hz, r.sample_count,
                               r.vector_sha256, v.codec, v.uncompressed_bytes,
                               v.payload
                        FROM rxmer_channel_result r
                        JOIN rxmer_target_channel c
                          ON c.successful_attempt_id=r.capture_attempt_id
                        JOIN rxmer_vector v
                          ON v.capture_attempt_id=r.capture_attempt_id
                        WHERE r.job_id=%s AND r.capture_attempt_id>%s
                        ORDER BY r.capture_attempt_id ASC LIMIT 250
                        """,
                        (job_id, last_attempt_id),
                    )
                    rows = list(cursor.fetchall())
                if not rows:
                    break
                for row in rows:
                    if str(row.get("codec") or "") != CODEC:
                        raise ValueError("unsupported persisted RxMER vector codec")
                    sample_count = int(row["sample_count"])
                    vector = decode_vector(
                        bytes(row["payload"]),
                        expected_sha256=bytes(row["vector_sha256"]),
                        expected_size=sample_count,
                    )
                    spacing_hz = int(row["spacing_hz"])
                    first_frequency_hz = int(row["zero_frequency_hz"]) + (
                        int(row["first_active_index"]) * spacing_hz
                    )
                    if (
                        spacing_hz <= 0
                        or spacing_hz % _SPECTRUM_GRID_HZ != 0
                        or (first_frequency_hz - grid_start_hz) % _SPECTRUM_GRID_HZ != 0
                    ):
                        raise ValueError("RxMER vector is not aligned to the 25 kHz spectrum grid")
                    start_index = (first_frequency_hz - grid_start_hz) // _SPECTRUM_GRID_HZ
                    stride = spacing_hz // _SPECTRUM_GRID_HZ
                    stop_index = start_index + stride * sample_count
                    if start_index < 0 or stop_index > grid_points + stride - 1:
                        raise ValueError("RxMER vector exceeds the calculated spectrum grid")
                    positions = slice(start_index, stop_index, stride)
                    values = np.frombuffer(vector, dtype=np.uint8)
                    count_view = counts[positions]
                    sum_view = sums[positions]
                    worst_view = worst[positions]
                    maximum_view = maximum[positions]
                    count_view += 1
                    sum_view += values.astype(np.uint64)
                    np.minimum(worst_view, values, out=worst_view)
                    np.maximum(maximum_view, values, out=maximum_view)
                    last_attempt_id = int(row["capture_attempt_id"])
                    processed_channels += 1
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE rxmer_spectrum_build SET lease_until="
                        "DATE_ADD(UTC_TIMESTAMP(), INTERVAL 10 MINUTE), updated_at=%s "
                        "WHERE job_id=%s AND source_revision=%s AND lease_owner=%s",
                        (self._now(), job_id, source_revision, lease_owner),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("RxMER spectrum build lease was lost")

            if processed_channels != source_channels:
                raise ValueError("one or more successful RxMER vectors are missing")
            occupied = np.flatnonzero(counts)
            rows_to_insert = [
                (
                    job_id,
                    source_revision,
                    grid_start_hz + int(index) * _SPECTRUM_GRID_HZ,
                    int(counts[index]),
                    int(sums[index]),
                    int(worst[index]),
                    int(maximum[index]),
                )
                for index in occupied
            ]
            write_connection = self._connect(autocommit=False)
            try:
                with write_connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM rxmer_spectrum_bin WHERE job_id=%s "
                        "AND source_revision=%s",
                        (job_id, source_revision),
                    )
                    insert_sql = (
                        "INSERT INTO rxmer_spectrum_bin "
                        "(job_id, source_revision, frequency_hz, sample_count, "
                        "sum_qdb, worst_qdb, max_qdb) VALUES "
                        "(%s, %s, %s, %s, %s, %s, %s)"
                    )
                    for offset in range(0, len(rows_to_insert), 1000):
                        cursor.executemany(insert_sql, rows_to_insert[offset:offset + 1000])
                    cursor.execute(
                        """
                        UPDATE rxmer_spectrum_build
                        SET state='ready', lease_owner=NULL, lease_until=NULL,
                            source_channels=%s, source_modems=%s, source_samples=%s,
                            frequency_start_hz=%s, frequency_end_hz=%s,
                            point_count=%s, error_text=NULL, updated_at=%s
                        WHERE job_id=%s AND source_revision=%s AND lease_owner=%s
                        """,
                        (
                            source_channels,
                            source_modems,
                            source_samples,
                            start_hz,
                            end_hz,
                            len(rows_to_insert),
                            self._now(),
                            job_id,
                            source_revision,
                            lease_owner,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("RxMER spectrum build lease was lost")
                    cursor.execute(
                        "DELETE FROM rxmer_spectrum_bin WHERE job_id=%s "
                        "AND source_revision<>%s",
                        (job_id, source_revision),
                    )
                write_connection.commit()
            except Exception:
                write_connection.rollback()
                raise
            finally:
                write_connection.close()
        except Exception as exc:
            self._execute(
                "UPDATE rxmer_spectrum_build SET state='failed', lease_owner=NULL, "
                "lease_until=NULL, error_text=%s, updated_at=%s "
                "WHERE job_id=%s AND source_revision=%s AND lease_owner=%s",
                (str(exc)[:2000], self._now(), job_id, source_revision, lease_owner),
            )
        finally:
            connection.close()

    def _finish_empty_spectrum_build(
        self, job_id: int, source_revision: int, lease_owner: str,
    ) -> None:
        connection = self._connect(autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM rxmer_spectrum_bin WHERE job_id=%s",
                    (job_id,),
                )
                cursor.execute(
                    """
                    UPDATE rxmer_spectrum_build
                    SET state='ready', lease_owner=NULL, lease_until=NULL,
                        source_channels=0, source_modems=0, source_samples=0,
                        frequency_start_hz=NULL, frequency_end_hz=NULL,
                        point_count=0, error_text=NULL, updated_at=%s
                    WHERE job_id=%s AND source_revision=%s AND lease_owner=%s
                    """,
                    (self._now(), job_id, source_revision, lease_owner),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("RxMER spectrum build lease was lost")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_spectrum(self, public_id: str, *, max_points: int = 1600) -> dict[str, Any]:
        """Return a bounded spectrum profile from a previously materialized rollup."""
        self.ensure_schema()
        jobs = self._query(
            "SELECT id, aggregate_revision FROM rxmer_job WHERE public_id=%s LIMIT 1",
            (public_id,),
        )
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        source_revision = int(jobs[0].get("aggregate_revision") or 0)
        builds = self._query(
            "SELECT * FROM rxmer_spectrum_build WHERE job_id=%s LIMIT 1",
            (job_id,),
        )
        base: dict[str, Any] = {
            "job_public_id": public_id,
            "state": "missing",
            "source_revision": source_revision,
            "source_channels": 0,
            "source_modems": 0,
            "source_samples": 0,
            "frequency_start_hz": None,
            "frequency_end_hz": None,
            "bin_width_hz": None,
            "points": [],
            "channel_spans": [],
            "span_groups_omitted": 0,
        }
        if not builds:
            base["message"] = "Spectrum profile has not been materialized"
            return base
        build = builds[0]
        build_revision = int(build.get("source_revision") or 0)
        if build_revision != source_revision:
            base["state"] = "stale"
            base["message"] = "New channel results require spectrum rebuilding"
            return base
        state = str(build.get("state") or "missing")
        base.update(
            {
                "state": state,
                "source_channels": int(build.get("source_channels") or 0),
                "source_modems": int(build.get("source_modems") or 0),
                "source_samples": int(build.get("source_samples") or 0),
                "frequency_start_hz": (
                    int(build["frequency_start_hz"])
                    if build.get("frequency_start_hz") is not None else None
                ),
                "frequency_end_hz": (
                    int(build["frequency_end_hz"])
                    if build.get("frequency_end_hz") is not None else None
                ),
            }
        )
        if state == "failed":
            base["message"] = str(build.get("error_text") or "Spectrum build failed")
            return base
        if state != "ready":
            base["message"] = "Spectrum profile is building"
            return base
        if int(build.get("point_count") or 0) == 0:
            base["message"] = "No successful channel vectors are available"
            return base

        safe_max_points = max(200, min(int(max_points), 4000))
        start_hz = int(build["frequency_start_hz"])
        end_hz = int(build["frequency_end_hz"])
        raw_width = max(1, math.ceil((end_hz - start_hz) / max(safe_max_points - 1, 1)))
        bin_width_hz = max(
            _SPECTRUM_GRID_HZ,
            math.ceil(raw_width / _SPECTRUM_GRID_HZ) * _SPECTRUM_GRID_HZ,
        )
        grouped_rows = self._query(
            """
            SELECT (%s + FLOOR((frequency_hz - %s) / %s) * %s)
                       AS bucket_frequency_hz,
                   SUM(sample_count) AS sample_count,
                   SUM(sum_qdb) AS sum_qdb,
                   MIN(worst_qdb) AS worst_qdb,
                   MAX(max_qdb) AS max_qdb
            FROM rxmer_spectrum_bin
            WHERE job_id=%s AND source_revision=%s
            GROUP BY bucket_frequency_hz ORDER BY bucket_frequency_hz
            """,
            (start_hz, start_hz, bin_width_hz, bin_width_hz, job_id, source_revision),
        )
        grouped = {int(row["bucket_frequency_hz"]): row for row in grouped_rows}
        lattice_end_hz = start_hz + ((end_hz - start_hz) // bin_width_hz) * bin_width_hz
        points: list[dict[str, Any]] = []
        for frequency_hz in range(start_hz, lattice_end_hz + 1, bin_width_hz):
            row = grouped.get(frequency_hz)
            if not row:
                points.append(
                    {
                        "frequency_hz": frequency_hz,
                        "average_db": None,
                        "max_db": None,
                        "worst_db": None,
                        "sample_count": 0,
                    }
                )
                continue
            sample_count = int(row["sample_count"])
            points.append(
                {
                    "frequency_hz": frequency_hz,
                    "average_db": round(int(row["sum_qdb"]) / (4.0 * sample_count), 3),
                    "max_db": round(int(row["max_qdb"]) / 4.0, 3),
                    "worst_db": round(int(row["worst_qdb"]) / 4.0, 3),
                    "sample_count": sample_count,
                }
            )

        span_count_rows = self._query(
            """
            SELECT COUNT(*) AS span_count FROM (
                SELECT r.channel_id,
                       (r.zero_frequency_hz + r.first_active_index * r.spacing_hz),
                       (r.zero_frequency_hz +
                        (r.first_active_index + r.sample_count - 1) * r.spacing_hz),
                       r.spacing_hz
                FROM rxmer_channel_result r
                JOIN rxmer_target_channel c
                  ON c.successful_attempt_id=r.capture_attempt_id
                WHERE r.job_id=%s
                GROUP BY r.channel_id,
                         (r.zero_frequency_hz + r.first_active_index * r.spacing_hz),
                         (r.zero_frequency_hz +
                          (r.first_active_index + r.sample_count - 1) * r.spacing_hz),
                         r.spacing_hz
            ) grouped_spans
            """,
            (job_id,),
        )
        total_span_groups = int(span_count_rows[0].get("span_count") or 0)
        span_rows = self._query(
            """
            SELECT r.channel_id,
                   (r.zero_frequency_hz + r.first_active_index * r.spacing_hz)
                       AS start_frequency_hz,
                   (r.zero_frequency_hz +
                    (r.first_active_index + r.sample_count - 1) * r.spacing_hz)
                       AS end_frequency_hz,
                   r.spacing_hz, COUNT(DISTINCT r.target_id) AS modem_count
            FROM rxmer_channel_result r
            JOIN rxmer_target_channel c
              ON c.successful_attempt_id=r.capture_attempt_id
            WHERE r.job_id=%s
            GROUP BY r.channel_id, start_frequency_hz, end_frequency_hz, r.spacing_hz
            ORDER BY modem_count DESC, start_frequency_hz, r.channel_id
            LIMIT 64
            """,
            (job_id,),
        )
        base.update(
            {
                "bin_width_hz": bin_width_hz,
                "points": points,
                "channel_spans": [
                    {
                        "channel_id": int(row["channel_id"]),
                        "start_frequency_hz": int(row["start_frequency_hz"]),
                        "end_frequency_hz": int(row["end_frequency_hz"]),
                        "spacing_hz": int(row["spacing_hz"]),
                        "modem_count": int(row["modem_count"]),
                    }
                    for row in span_rows
                ],
                "span_groups_omitted": max(0, total_span_groups - len(span_rows)),
                "message": "Spectrum profile ready",
            }
        )
        return base


rxmer_analytics_service = RxMerAnalyticsService()
