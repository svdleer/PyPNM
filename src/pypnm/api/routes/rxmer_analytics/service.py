# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator

import numpy as np
import pymysql
import pymysql.cursors

SCHEMA_VERSION = 3
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

    @staticmethod
    def _db_timeout_seconds(name: str, fallback_name: str, default: int) -> int:
        raw = os.environ.get(name) or os.environ.get(fallback_name) or str(default)
        try:
            return max(30, min(int(raw), 3600))
        except (TypeError, ValueError):
            return default

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
            read_timeout=self._db_timeout_seconds(
                "RXMER_DB_READ_TIMEOUT_SEC", "DATA_DB_READ_TIMEOUT_SEC", 600
            ),
            write_timeout=self._db_timeout_seconds(
                "RXMER_DB_WRITE_TIMEOUT_SEC", "DATA_DB_WRITE_TIMEOUT_SEC", 120
            ),
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
            CREATE TABLE IF NOT EXISTS rxmer_job_topology_snapshot (
                job_id BIGINT PRIMARY KEY,
                snapshot_date CHAR(8) NOT NULL,
                created_at DATETIME NOT NULL
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
            CREATE TABLE IF NOT EXISTS rxmer_channel_extreme (
                capture_attempt_id BIGINT PRIMARY KEY,
                job_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                worst_qdb TINYINT UNSIGNED NOT NULL,
                worst_subcarrier_index INT NOT NULL,
                worst_frequency_hz BIGINT NOT NULL,
                created_at DATETIME NOT NULL,
                INDEX idx_rxmer_channel_extreme_job (job_id, worst_qdb),
                INDEX idx_rxmer_channel_extreme_target (target_id, worst_qdb)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS rxmer_modem_extreme (
                job_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                worst_qdb TINYINT UNSIGNED NOT NULL,
                worst_channel_id SMALLINT UNSIGNED NOT NULL,
                worst_subcarrier_index INT NOT NULL,
                worst_frequency_hz BIGINT NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (job_id, target_id),
                INDEX idx_rxmer_modem_extreme_job (job_id, worst_qdb)
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
            "max_inventory_modems": None,
            "planning_source": "persisted_inventory",
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
            "topology_source": "latest_topology_with_inventory_fallback",
        }
        scope_json = json.dumps(scope_document, sort_keys=True, separators=(",", ":"))
        scope_hash = self._scope_hash(scope_document, online_only)
        public_id = str(uuid.uuid4())
        now = self._now()

        if idempotency_key:
            existing_rows = self._query(
                "SELECT public_id FROM rxmer_job WHERE requested_by=%s "
                "AND idempotency_key=%s LIMIT 1",
                (requested_by, idempotency_key),
            )
            if existing_rows:
                job = self.get_job(str(existing_rows[0]["public_id"]))
                if not job:
                    raise RuntimeError("idempotent RxMER plan disappeared")
                return job, True

        from pypnm.api.routes.topology.service import normalize_bare_mac, topology_service

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
                    "i.ip IS NOT NULL",
                    "TRIM(i.ip) NOT IN ('', 'N/A', '0.0.0.0', '::')",
                    "(i.ofdm_enabled=TRUE OR COALESCE(i.ofdm_channel_count, 0)>0 "
                    "OR COALESCE(i.ofdm_ifindex, 0)>0)",
                ]
                where_params: list[Any] = []
                if online_only:
                    placeholders = ",".join(["%s"] * len(_ONLINE_STATUSES))
                    where_parts.append(f"i.status IN ({placeholders})")
                    where_params.extend(_ONLINE_STATUSES)
                if scope_type == "cmts":
                    placeholders = ",".join(["%s"] * len(cmts_names))
                    where_parts.append(f"i.cmts IN ({placeholders})")
                    where_params.extend(cmts_names)
                where_sql = " AND ".join(where_parts)
                candidate_where_parts = list(where_parts)
                candidate_where_params = list(where_params)
                if scope_type == "cmts":
                    candidate_where_parts = candidate_where_parts[:-1]
                    candidate_where_params = candidate_where_params[:-len(cmts_names)]
                candidate_where_sql = " AND ".join(candidate_where_parts)

                # Reserve the idempotency key before the potentially long
                # snapshot preparation so duplicate requests cannot repeat it.
                cursor.execute(
                    """
                    INSERT INTO rxmer_job
                    (public_id, trigger_type, status, scope_hash, scope_json,
                     inventory_revision, idempotency_key, requested_by,
                     raw_retention_days, aggregate_retention_days, created_at, updated_at)
                    VALUES (%s, 'plan', 'planned', %s, %s, NULL, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        public_id,
                        scope_hash,
                        scope_json,
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
                    """
                    CREATE TEMPORARY TABLE rxmer_plan_topology (
                        bare_mac CHAR(12) CHARACTER SET ascii COLLATE ascii_bin
                            NOT NULL PRIMARY KEY,
                        fiber_node VARCHAR(128) NOT NULL
                    ) ENGINE=InnoDB
                    """
                )

                # Prefer indexed point lookups against a completed normalized
                # topology map. This keeps CMTS-scoped plans proportional to
                # their eligible inventory instead of every topology modem.
                inventory_revision: str | None = None
                topology_snapshot_date: str | None = None
                indexed_topology = False
                with topology_service.storage.latest_fiber_node_map_lookup() as (
                    map_snapshot_date,
                    topology_lookup,
                ):
                    topology_snapshot_date = map_snapshot_date
                    indexed_topology = topology_lookup is not None
                    if topology_lookup is not None:
                        try:
                            lookup_batch_size = max(
                                100,
                                min(
                                    int(os.environ.get("RXMER_PLAN_LOOKUP_BATCH_SIZE", "2000")),
                                    5000,
                                ),
                            )
                        except (TypeError, ValueError):
                            lookup_batch_size = 2000
                        latest_updated_at: datetime | None = None
                        candidate_scopes: list[str | None] = (
                            list(cmts_names) if scope_type == "cmts" else [None]
                        )
                        for candidate_cmts in candidate_scopes:
                            last_mac = ""
                            while True:
                                scoped_where_sql = candidate_where_sql
                                scoped_params: list[Any] = list(candidate_where_params)
                                if candidate_cmts is not None:
                                    scoped_where_sql += " AND i.cmts=%s"
                                    scoped_params.append(candidate_cmts)
                                cursor.execute(
                                    f"""
                                    SELECT i.mac, i.updated_at
                                    FROM modem_inventory_current AS i
                                    WHERE {scoped_where_sql} AND i.mac>%s
                                    ORDER BY i.mac ASC LIMIT %s
                                    """,
                                    (*scoped_params, last_mac, lookup_batch_size),
                                )
                                candidate_rows = list(cursor.fetchall())
                                if not candidate_rows:
                                    break
                                last_mac = str(candidate_rows[-1]["mac"])
                                bare_macs: list[str] = []
                                for candidate in candidate_rows:
                                    bare_mac = normalize_bare_mac(candidate.get("mac"))
                                    if bare_mac:
                                        bare_macs.append(bare_mac)
                                    updated_at = candidate.get("updated_at")
                                    if isinstance(updated_at, datetime) and (
                                        latest_updated_at is None
                                        or updated_at > latest_updated_at
                                    ):
                                        latest_updated_at = updated_at
                                topology_rows = topology_lookup(bare_macs)
                                if topology_rows:
                                    cursor.executemany(
                                        """
                                        INSERT INTO rxmer_plan_topology
                                            (bare_mac, fiber_node)
                                        VALUES (%s, %s)
                                        ON DUPLICATE KEY UPDATE
                                            fiber_node=LEAST(
                                                fiber_node, VALUES(fiber_node)
                                            )
                                        """,
                                        topology_rows,
                                    )
                        if latest_updated_at is not None:
                            inventory_revision = latest_updated_at.strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )

                if not indexed_topology:
                    # Compatibility path until the explicit existing-data map
                    # backfill has completed. It preserves topology precedence
                    # without making deployment run a blocking large migration.
                    cursor.execute(
                        f"SELECT DATE_FORMAT(MAX(i.updated_at), "
                        f"'%%Y-%%m-%%dT%%H:%%i:%%sZ') AS revision "
                        f"FROM modem_inventory_current AS i WHERE {where_sql}",
                        tuple(where_params),
                    )
                    revision_row = cursor.fetchone() or {}
                    inventory_revision = revision_row.get("revision")
                    with topology_service.storage.stream_latest_fiber_nodes() as (
                        fallback_snapshot_date,
                        topology_batches,
                    ):
                        topology_snapshot_date = fallback_snapshot_date
                        for topology_batch in topology_batches:
                            cursor.executemany(
                                """
                                INSERT INTO rxmer_plan_topology
                                    (bare_mac, fiber_node)
                                VALUES (%s, %s)
                                ON DUPLICATE KEY UPDATE
                                    fiber_node=LEAST(
                                        fiber_node, VALUES(fiber_node)
                                    )
                                """,
                                topology_batch,
                            )

                # Materialize the immutable target set inside MySQL. Latest
                # topology takes precedence; persisted inventory remains the
                # fallback for MACs absent from that topology snapshot.
                cursor.execute(
                    f"""
                    INSERT INTO rxmer_job_target
                    (job_id, mac, modem_ip, cmts, cmts_ip, fiber_node,
                     inventory_snapshot_id, state, expected_channels,
                     created_at, updated_at)
                    SELECT %s, i.mac, i.ip, i.cmts, i.cmts_ip,
                           COALESCE(
                               t.fiber_node,
                               NULLIF(LEFT(TRIM(COALESCE(i.fiber_node, '')), 128), '')
                           ),
                           i.snapshot_id, 'planned',
                           COALESCE(i.ofdm_channel_count, 0), %s, %s
                    FROM modem_inventory_current AS i
                    LEFT JOIN rxmer_plan_topology AS t
                      ON t.bare_mac=(
                          CONVERT(
                              LOWER(REPLACE(REPLACE(REPLACE(
                                  i.mac, ':', ''), '-', ''), '.', ''))
                              USING ascii
                          ) COLLATE ascii_bin
                      )
                    WHERE {where_sql}
                    """,
                    (job_id, now, now, *where_params),
                )
                target_count = max(0, int(cursor.rowcount or 0))
                if target_count <= 0:
                    raise ValueError("no eligible operational OFDM modems found in the selected inventory scope")
                if topology_snapshot_date:
                    cursor.execute(
                        "INSERT INTO rxmer_job_topology_snapshot "
                        "(job_id, snapshot_date, created_at) VALUES (%s, %s, %s)",
                        (job_id, topology_snapshot_date, now),
                    )
                cursor.execute(
                    "UPDATE rxmer_job SET targets_total=%s, inventory_revision=%s, "
                    "updated_at=%s WHERE id=%s",
                    (target_count, inventory_revision, now, job_id),
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

    def list_cmts_options(self, *, query: str | None = None, limit: int = 500) -> list[str]:
        """Return persisted CCAP hostnames; never performs discovery."""
        self.ensure_schema()
        safe_limit = max(1, min(int(limit), 5000))
        query_value = str(query or "").strip()
        params: list[Any] = ["%ccap%"]
        where = "TRIM(cmts)<>'' AND LOWER(TRIM(cmts)) LIKE %s"
        if query_value:
            where += " AND cmts LIKE %s"
            params.append(f"%{query_value}%")
        rows = self._query(
            f"SELECT DISTINCT cmts FROM modem_inventory_current WHERE {where} "
            "ORDER BY cmts LIMIT %s",
            (*params, safe_limit),
        )
        return [str(row["cmts"]) for row in rows]

    def get_job_filter_options(self, public_id: str) -> dict[str, Any]:
        self.ensure_schema()
        jobs = self._query("SELECT id FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        cmts_rows = self._query(
            "SELECT DISTINCT cmts FROM rxmer_job_target WHERE job_id=%s "
            "AND TRIM(cmts)<>'' AND LOWER(TRIM(cmts)) LIKE %s ORDER BY cmts",
            (job_id, "%ccap%"),
        )
        fiber_rows = self._query(
            "SELECT DISTINCT fiber_node FROM rxmer_job_target WHERE job_id=%s "
            "AND fiber_node IS NOT NULL AND TRIM(fiber_node)<>'' ORDER BY fiber_node",
            (job_id,),
        )
        return {
            "job_public_id": public_id,
            "cmts": [str(row["cmts"]) for row in cmts_rows],
            "fiber_nodes": [str(row["fiber_node"]) for row in fiber_rows],
        }

    def list_targets(
        self,
        public_id: str,
        *,
        cursor: int = 0,
        limit: int = 200,
        cmts: str | None = None,
        fiber_node: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        job_rows = self._query("SELECT id FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not job_rows:
            raise KeyError(public_id)
        job_id = int(job_rows[0]["id"])
        safe_limit = max(1, min(int(limit), 1000))
        filters = ["t.job_id=%s", "t.id>%s"]
        params: list[Any] = [job_id, max(0, int(cursor))]
        if cmts:
            filters.append("t.cmts=%s")
            params.append(str(cmts).strip())
        if fiber_node:
            filters.append("t.fiber_node=%s")
            params.append(str(fiber_node).strip())
        where_sql = " AND ".join(filters)
        rows = self._query(
            f"""
            SELECT t.id, t.mac, t.modem_ip, t.cmts, t.cmts_ip, t.fiber_node,
                   t.inventory_snapshot_id, t.state, t.expected_channels,
                   t.completed_channels, t.failed_channels, t.attempt_count,
                   t.error_class, t.error_text, t.created_at, t.updated_at,
                   a.completeness, a.valid_channel_count, a.sample_count,
                   a.avg_db, (a.best_qdb / 4.0) AS best_db,
                   a.best_channel_id, a.best_subcarrier_index,
                   a.best_frequency_hz, (e.worst_qdb / 4.0) AS worst_db,
                   e.worst_channel_id, e.worst_subcarrier_index,
                   e.worst_frequency_hz
            FROM rxmer_job_target t
            LEFT JOIN rxmer_modem_aggregate a
              ON a.job_id=t.job_id AND a.target_id=t.id
            LEFT JOIN rxmer_modem_extreme e
              ON e.job_id=t.job_id AND e.target_id=t.id
            WHERE {where_sql} ORDER BY t.id ASC LIMIT %s
            """,
            (*params, safe_limit + 1),
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
                    """
                    INSERT INTO rxmer_channel_extreme
                    (capture_attempt_id, job_id, target_id, worst_qdb,
                     worst_subcarrier_index, worst_frequency_hz, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        attempt_id,
                        job_id,
                        target_id,
                        metrics.worst_qdb,
                        metrics.worst_subcarrier_index,
                        metrics.worst_frequency_hz,
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
                cursor.execute(
                    """
                    SELECT e.worst_qdb, r.channel_id,
                           e.worst_subcarrier_index, e.worst_frequency_hz
                    FROM rxmer_target_channel c
                    JOIN rxmer_channel_result r
                      ON r.capture_attempt_id=c.successful_attempt_id
                    JOIN rxmer_channel_extreme e
                      ON e.capture_attempt_id=r.capture_attempt_id
                    WHERE c.target_id=%s
                    ORDER BY e.worst_qdb ASC, e.worst_frequency_hz ASC,
                             r.channel_id ASC LIMIT 1
                    """,
                    (target_id,),
                )
                worst = cursor.fetchone() or {}
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
                    """
                    INSERT INTO rxmer_modem_extreme
                    (job_id, target_id, worst_qdb, worst_channel_id,
                     worst_subcarrier_index, worst_frequency_hz, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE worst_qdb=VALUES(worst_qdb),
                        worst_channel_id=VALUES(worst_channel_id),
                        worst_subcarrier_index=VALUES(worst_subcarrier_index),
                        worst_frequency_hz=VALUES(worst_frequency_hz),
                        updated_at=VALUES(updated_at)
                    """,
                    (
                        job_id,
                        target_id,
                        int(worst["worst_qdb"]),
                        int(worst["channel_id"]),
                        int(worst["worst_subcarrier_index"]),
                        int(worst["worst_frequency_hz"]),
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
            "worst_db": metrics.worst_qdb / 4.0,
            "worst_frequency_hz": metrics.worst_frequency_hz,
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
        cursor.execute("DELETE FROM rxmer_modem_extreme WHERE job_id=%s", (job_id,))
        cursor.execute("DELETE FROM rxmer_modem_aggregate WHERE job_id=%s", (job_id,))
        cursor.execute("DELETE FROM rxmer_channel_extreme WHERE job_id=%s", (job_id,))
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
                cursor.execute("DELETE FROM rxmer_job_topology_snapshot WHERE job_id=%s", (job_id,))
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

    def stream_report(
        self,
        public_id: str,
        *,
        report_format: str,
        cmts: str | None = None,
        fiber_node: str | None = None,
    ) -> Iterator[str]:
        """Stream a bounded-memory report over frozen targets and persisted results."""
        self.ensure_schema()
        jobs = self._query("SELECT id FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        normalized_format = str(report_format or "").lower()
        if normalized_format not in {"json", "csv"}:
            raise ValueError("report format must be json or csv")

        filters = ["t.job_id=%s"]
        params: list[Any] = [job_id]
        clean_cmts = str(cmts or "").strip() or None
        clean_fiber_node = str(fiber_node or "").strip() or None
        if clean_cmts:
            filters.append("t.cmts=%s")
            params.append(clean_cmts)
        if clean_fiber_node:
            filters.append("t.fiber_node=%s")
            params.append(clean_fiber_node)
        where_sql = " AND ".join(filters)
        sql = f"""
            SELECT t.id AS target_id, t.mac, t.modem_ip, t.cmts, t.cmts_ip,
                   t.fiber_node, p.snapshot_date AS topology_snapshot_date,
                   t.state, t.expected_channels,
                   t.completed_channels, t.failed_channels, t.attempt_count,
                   t.error_class, t.error_text, t.created_at, t.updated_at,
                   a.completeness, a.valid_channel_count, a.sample_count,
                   a.avg_db, (a.best_qdb / 4.0) AS best_db,
                   a.best_channel_id, a.best_subcarrier_index,
                   a.best_frequency_hz, (e.worst_qdb / 4.0) AS worst_db,
                   e.worst_channel_id, e.worst_subcarrier_index,
                   e.worst_frequency_hz
            FROM rxmer_job_target t
            LEFT JOIN rxmer_job_topology_snapshot p
              ON p.job_id=t.job_id
            LEFT JOIN rxmer_modem_aggregate a
              ON a.job_id=t.job_id AND a.target_id=t.id
            LEFT JOIN rxmer_modem_extreme e
              ON e.job_id=t.job_id AND e.target_id=t.id
            WHERE {where_sql}
            ORDER BY t.id ASC
        """
        field_names = [
            "target_id", "mac", "modem_ip", "cmts", "cmts_ip", "fiber_node",
            "topology_snapshot_date", "state", "expected_channels", "completed_channels", "failed_channels",
            "attempt_count", "error_class", "error_text", "created_at", "updated_at",
            "completeness", "valid_channel_count", "sample_count", "avg_db", "best_db",
            "best_channel_id", "best_subcarrier_index", "best_frequency_hz", "worst_db",
            "worst_channel_id", "worst_subcarrier_index", "worst_frequency_hz",
        ]

        def serialize_row(source: dict[str, Any]) -> dict[str, Any]:
            row: dict[str, Any] = {}
            for field in field_names:
                value = source.get(field)
                if isinstance(value, datetime):
                    value = value.replace(tzinfo=timezone.utc).isoformat()
                elif hasattr(value, "as_integer_ratio") and not isinstance(value, (int, float)):
                    value = float(value)
                row[field] = value
            return row

        def generate() -> Iterator[str]:
            connection = self._connect(autocommit=True)
            try:
                with connection.cursor(pymysql.cursors.SSDictCursor) as cursor:
                    cursor.execute(sql, tuple(params))
                    if normalized_format == "json":
                        yield json.dumps(
                            {
                                "job_public_id": public_id,
                                "filters": {
                                    "cmts": clean_cmts,
                                    "fiber_node": clean_fiber_node,
                                },
                            },
                            separators=(",", ":"),
                        )[:-1] + ',"results":['
                        first = True
                        for source in cursor:
                            if not first:
                                yield ","
                            first = False
                            yield json.dumps(
                                serialize_row(dict(source)),
                                ensure_ascii=True,
                                separators=(",", ":"),
                            )
                        yield "]}"
                    else:
                        buffer = io.StringIO()
                        writer = csv.DictWriter(buffer, fieldnames=field_names)
                        writer.writeheader()
                        yield buffer.getvalue()
                        buffer.seek(0)
                        buffer.truncate(0)
                        for source in cursor:
                            writer.writerow(serialize_row(dict(source)))
                            yield buffer.getvalue()
                            buffer.seek(0)
                            buffer.truncate(0)
            finally:
                connection.close()

        return generate()

    @staticmethod
    def _subcarrier_statistic(value: str | None) -> str:
        statistic = str(value or "average").strip().lower()
        if statistic not in {"average", "best", "worst"}:
            raise ValueError("subcarrier statistic must be average, best, or worst")
        return statistic

    @staticmethod
    def _filtered_spectrum_max_samples() -> int:
        raw = os.environ.get("RXMER_FILTERED_SPECTRUM_MAX_SAMPLES", "500000000")
        try:
            return max(1_000_000, min(int(raw), 5_000_000_000))
        except (TypeError, ValueError):
            return 500_000_000

    def _filtered_spectrum_rollup(
        self,
        job_id: int,
        *,
        cmts: str | None,
        fiber_node: str | None,
    ) -> dict[str, Any]:
        """Build a bounded in-memory rollup from matching stored vectors only."""
        from pypnm.api.routes.rxmer_analytics.analytics import CODEC, decode_vector

        filters = ["r.job_id=%s"]
        filter_params: list[Any] = [job_id]
        if cmts:
            filters.append("t.cmts=%s")
            filter_params.append(cmts)
        if fiber_node:
            filters.append("t.fiber_node=%s")
            filter_params.append(fiber_node)
        where_sql = " AND ".join(filters)
        connection = self._connect(autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS source_channels,
                           COUNT(v.capture_attempt_id) AS available_channels,
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
                    JOIN rxmer_job_target t
                      ON t.id=r.target_id AND t.job_id=r.job_id
                    LEFT JOIN rxmer_vector v
                      ON v.capture_attempt_id=r.capture_attempt_id
                    WHERE {where_sql}
                    """,
                    tuple(filter_params),
                )
                stats = cursor.fetchone() or {}

            source_channels = int(stats.get("source_channels") or 0)
            available_channels = int(stats.get("available_channels") or 0)
            source_modems = int(stats.get("source_modems") or 0)
            source_samples = int(stats.get("source_samples") or 0)
            if available_channels != source_channels:
                raise FileNotFoundError(
                    "One or more matching raw RxMER vectors are unavailable or expired"
                )
            sample_limit = self._filtered_spectrum_max_samples()
            if source_samples > sample_limit:
                raise OverflowError(
                    f"Filtered spectrum contains {source_samples:,} samples; "
                    f"narrow the CMTS/fiber-node filters below the {sample_limit:,}-sample limit"
                )
            if source_channels == 0:
                return {
                    "source_channels": 0,
                    "source_modems": 0,
                    "source_samples": 0,
                    "frequency_start_hz": None,
                    "frequency_end_hz": None,
                    "bins": [],
                }

            start_hz = int(stats["start_hz"])
            end_hz = int(stats["end_hz"])
            grid_start_hz = (start_hz // _SPECTRUM_GRID_HZ) * _SPECTRUM_GRID_HZ
            grid_end_hz = math.ceil(end_hz / _SPECTRUM_GRID_HZ) * _SPECTRUM_GRID_HZ
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
                page_filters = ["r.job_id=%s", "r.capture_attempt_id>%s"]
                page_params: list[Any] = [job_id, last_attempt_id]
                if cmts:
                    page_filters.append("t.cmts=%s")
                    page_params.append(cmts)
                if fiber_node:
                    page_filters.append("t.fiber_node=%s")
                    page_params.append(fiber_node)
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT r.capture_attempt_id, r.zero_frequency_hz,
                               r.first_active_index, r.spacing_hz, r.sample_count,
                               r.vector_sha256, v.codec, v.payload
                        FROM rxmer_channel_result r
                        JOIN rxmer_target_channel c
                          ON c.successful_attempt_id=r.capture_attempt_id
                        JOIN rxmer_job_target t
                          ON t.id=r.target_id AND t.job_id=r.job_id
                        JOIN rxmer_vector v
                          ON v.capture_attempt_id=r.capture_attempt_id
                        WHERE {' AND '.join(page_filters)}
                        ORDER BY r.capture_attempt_id ASC LIMIT 250
                        """,
                        tuple(page_params),
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
                    counts[positions] += 1
                    sums[positions] += values.astype(np.uint64)
                    np.minimum(worst[positions], values, out=worst[positions])
                    np.maximum(maximum[positions], values, out=maximum[positions])
                    last_attempt_id = int(row["capture_attempt_id"])
                    processed_channels += 1
            if processed_channels != source_channels:
                raise FileNotFoundError(
                    "One or more matching raw RxMER vectors are unavailable or expired"
                )
            occupied = np.flatnonzero(counts)
            bins = [
                {
                    "frequency_hz": grid_start_hz + int(index) * _SPECTRUM_GRID_HZ,
                    "sample_count": int(counts[index]),
                    "sum_qdb": int(sums[index]),
                    "worst_qdb": int(worst[index]),
                    "max_qdb": int(maximum[index]),
                }
                for index in occupied
            ]
            return {
                "source_channels": source_channels,
                "source_modems": source_modems,
                "source_samples": source_samples,
                "frequency_start_hz": start_hz,
                "frequency_end_hz": end_hz,
                "bins": bins,
            }
        finally:
            connection.close()

    @staticmethod
    def _subcarrier_row(row: dict[str, Any], statistic: str) -> dict[str, Any]:
        sample_count = int(row["sample_count"])
        if statistic == "best":
            value = int(row["max_qdb"]) / 4.0
        elif statistic == "worst":
            value = int(row["worst_qdb"]) / 4.0
        else:
            value = int(row["sum_qdb"]) / (4.0 * sample_count)
        return {
            "frequency_hz": int(row["frequency_hz"]),
            "rxmer_db": round(value, 3),
            "sample_count": sample_count,
        }

    def _format_filtered_spectrum(
        self,
        public_id: str,
        rollup: dict[str, Any],
        *,
        max_points: int,
        statistic: str,
        cmts: str | None,
        fiber_node: str | None,
    ) -> dict[str, Any]:
        bins = list(rollup["bins"])
        base: dict[str, Any] = {
            "job_public_id": public_id,
            "state": "ready",
            "message": "Filtered spectrum ready" if bins else "No successful channel vectors match the filters",
            "source_revision": 0,
            "source_channels": int(rollup["source_channels"]),
            "source_modems": int(rollup["source_modems"]),
            "source_samples": int(rollup["source_samples"]),
            "frequency_start_hz": rollup["frequency_start_hz"],
            "frequency_end_hz": rollup["frequency_end_hz"],
            "bin_width_hz": None,
            "points": [],
            "best_subcarriers": [],
            "worst_subcarriers": [],
            "channel_spans": [],
            "span_groups_omitted": 0,
            "filters": {"cmts": cmts, "fiber_node": fiber_node},
            "statistic": statistic,
        }
        if not bins:
            return base

        def score(row: dict[str, Any]) -> float:
            return self._subcarrier_row(row, statistic)["rxmer_db"]

        ordered = sorted(bins, key=lambda row: (score(row), -int(row["frequency_hz"])))
        def ranking_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    "frequency_hz": int(row["frequency_hz"]),
                    "average_db": round(
                        int(row["sum_qdb"]) / (4.0 * int(row["sample_count"])), 3
                    ),
                    "max_db": round(int(row["max_qdb"]) / 4.0, 3),
                    "worst_db": round(int(row["worst_qdb"]) / 4.0, 3),
                    "sample_count": int(row["sample_count"]),
                }
                for row in rows
            ]

        base["best_subcarriers"] = ranking_rows(list(reversed(ordered[-10:])))
        base["worst_subcarriers"] = ranking_rows(ordered[:10])

        safe_max_points = max(200, min(int(max_points), 4000))
        start_hz = int(rollup["frequency_start_hz"])
        end_hz = int(rollup["frequency_end_hz"])
        raw_width = max(1, math.ceil((end_hz - start_hz) / max(safe_max_points - 1, 1)))
        bin_width_hz = max(
            _SPECTRUM_GRID_HZ,
            math.ceil(raw_width / _SPECTRUM_GRID_HZ) * _SPECTRUM_GRID_HZ,
        )
        grouped: dict[int, dict[str, int]] = {}
        for row in bins:
            bucket = start_hz + (
                (int(row["frequency_hz"]) - start_hz) // bin_width_hz
            ) * bin_width_hz
            target = grouped.setdefault(
                bucket,
                {"sample_count": 0, "sum_qdb": 0, "worst_qdb": 255, "max_qdb": 0},
            )
            target["sample_count"] += int(row["sample_count"])
            target["sum_qdb"] += int(row["sum_qdb"])
            target["worst_qdb"] = min(target["worst_qdb"], int(row["worst_qdb"]))
            target["max_qdb"] = max(target["max_qdb"], int(row["max_qdb"]))
        lattice_end_hz = start_hz + ((end_hz - start_hz) // bin_width_hz) * bin_width_hz
        points: list[dict[str, Any]] = []
        for frequency_hz in range(start_hz, lattice_end_hz + 1, bin_width_hz):
            row = grouped.get(frequency_hz)
            if not row:
                points.append(
                    {"frequency_hz": frequency_hz, "average_db": None,
                     "max_db": None, "worst_db": None, "sample_count": 0}
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
        base["bin_width_hz"] = bin_width_hz
        base["points"] = points
        return base

    def get_filtered_spectrum(
        self,
        public_id: str,
        *,
        max_points: int = 1600,
        cmts: str | None = None,
        fiber_node: str | None = None,
        statistic: str = "average",
    ) -> dict[str, Any]:
        """Return display-only spectrum output for the selected persisted-result filters."""
        clean_cmts = str(cmts or "").strip() or None
        clean_fiber_node = str(fiber_node or "").strip() or None
        clean_statistic = self._subcarrier_statistic(statistic)
        if clean_cmts or clean_fiber_node:
            self.ensure_schema()
            jobs = self._query(
                "SELECT id FROM rxmer_job WHERE public_id=%s LIMIT 1", (public_id,)
            )
            if not jobs:
                raise KeyError(public_id)
            rollup = self._filtered_spectrum_rollup(
                int(jobs[0]["id"]), cmts=clean_cmts, fiber_node=clean_fiber_node
            )
            return self._format_filtered_spectrum(
                public_id,
                rollup,
                max_points=max_points,
                statistic=clean_statistic,
                cmts=clean_cmts,
                fiber_node=clean_fiber_node,
            )

        payload = self.get_spectrum(public_id, max_points=max_points)
        payload["filters"] = {"cmts": None, "fiber_node": None}
        payload["statistic"] = clean_statistic
        if payload.get("state") != "ready" or not payload.get("points"):
            return payload
        jobs = self._query(
            "SELECT id, aggregate_revision FROM rxmer_job WHERE public_id=%s LIMIT 1",
            (public_id,),
        )
        expression = {
            "average": "(sum_qdb / sample_count)",
            "best": "max_qdb",
            "worst": "worst_qdb",
        }[clean_statistic]
        ranking_sql = f"""
            SELECT frequency_hz, sample_count, sum_qdb, worst_qdb, max_qdb
            FROM rxmer_spectrum_bin
            WHERE job_id=%s AND source_revision=%s
            ORDER BY {expression} {{direction}}, frequency_hz ASC LIMIT 10
        """
        job_id = int(jobs[0]["id"])
        revision = int(jobs[0].get("aggregate_revision") or 0)
        best = self._query(ranking_sql.format(direction="DESC"), (job_id, revision))
        worst = self._query(ranking_sql.format(direction="ASC"), (job_id, revision))
        def ranking_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    "frequency_hz": int(row["frequency_hz"]),
                    "average_db": round(int(row["sum_qdb"]) / (4.0 * int(row["sample_count"])), 3),
                    "max_db": round(int(row["max_qdb"]) / 4.0, 3),
                    "worst_db": round(int(row["worst_qdb"]) / 4.0, 3),
                    "sample_count": int(row["sample_count"]),
                }
                for row in rows
            ]
        payload["best_subcarriers"] = ranking_rows(best)
        payload["worst_subcarriers"] = ranking_rows(worst)
        return payload

    def stream_subcarrier_report(
        self,
        public_id: str,
        *,
        report_format: str,
        cmts: str | None = None,
        fiber_node: str | None = None,
        statistic: str = "average",
    ) -> Iterator[str]:
        """Stream one selected RxMER statistic per subcarrier frequency."""
        self.ensure_schema()
        jobs = self._query(
            "SELECT id, aggregate_revision FROM rxmer_job WHERE public_id=%s LIMIT 1",
            (public_id,),
        )
        if not jobs:
            raise KeyError(public_id)
        normalized_format = str(report_format or "").lower()
        if normalized_format not in {"json", "csv"}:
            raise ValueError("report format must be json or csv")
        clean_statistic = self._subcarrier_statistic(statistic)
        clean_cmts = str(cmts or "").strip() or None
        clean_fiber_node = str(fiber_node or "").strip() or None
        job_id = int(jobs[0]["id"])
        revision = int(jobs[0].get("aggregate_revision") or 0)
        filtered_bins: list[dict[str, Any]] | None = None
        if clean_cmts or clean_fiber_node:
            filtered_bins = self._filtered_spectrum_rollup(
                job_id, cmts=clean_cmts, fiber_node=clean_fiber_node
            )["bins"]
        else:
            builds = self._query(
                "SELECT state, source_revision FROM rxmer_spectrum_build WHERE job_id=%s LIMIT 1",
                (job_id,),
            )
            if (
                not builds
                or str(builds[0].get("state") or "") != "ready"
                or int(builds[0].get("source_revision") or -1) != revision
            ):
                raise FileNotFoundError(
                    "The job-wide subcarrier spectrum must be built before it can be exported"
                )

        metadata = {
            "job_public_id": public_id,
            "filters": {"cmts": clean_cmts, "fiber_node": clean_fiber_node},
            "statistic": clean_statistic,
            "units": {"frequency": "Hz", "rxmer": "dB"},
        }
        field_names = [
            "job_public_id", "cmts_filter", "fiber_node_filter", "statistic",
            "frequency_hz", "rxmer_db", "sample_count",
        ]

        def source_rows() -> Iterator[dict[str, Any]]:
            if filtered_bins is not None:
                yield from filtered_bins
                return
            connection = self._connect(autocommit=True)
            try:
                with connection.cursor(pymysql.cursors.SSDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT frequency_hz, sample_count, sum_qdb, worst_qdb, max_qdb
                        FROM rxmer_spectrum_bin
                        WHERE job_id=%s AND source_revision=%s
                        ORDER BY frequency_hz ASC
                        """,
                        (job_id, revision),
                    )
                    for row in cursor:
                        yield dict(row)
            finally:
                connection.close()

        def generate() -> Iterator[str]:
            if normalized_format == "json":
                yield json.dumps(metadata, separators=(",", ":"))[:-1] + ',"results":['
                first = True
                for source in source_rows():
                    if not first:
                        yield ","
                    first = False
                    yield json.dumps(
                        self._subcarrier_row(source, clean_statistic),
                        separators=(",", ":"),
                    )
                yield "]}"
                return
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=field_names)
            writer.writeheader()
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            for source in source_rows():
                value = self._subcarrier_row(source, clean_statistic)
                writer.writerow(
                    {
                        "job_public_id": public_id,
                        "cmts_filter": clean_cmts,
                        "fiber_node_filter": clean_fiber_node,
                        "statistic": clean_statistic,
                        **value,
                    }
                )
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

        return generate()

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
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS missing_extremes
                        FROM rxmer_channel_result r
                        JOIN rxmer_target_channel c
                          ON c.successful_attempt_id=r.capture_attempt_id
                        LEFT JOIN rxmer_channel_extreme e
                          ON e.capture_attempt_id=r.capture_attempt_id
                        WHERE r.job_id=%s AND e.capture_attempt_id IS NULL
                        """,
                        (job_id,),
                    )
                    missing_extremes = int(
                        (cursor.fetchone() or {}).get("missing_extremes") or 0
                    )
                    if missing_extremes == 0:
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
                        SELECT r.capture_attempt_id, r.target_id, r.channel_id,
                               r.zero_frequency_hz, r.first_active_index,
                               r.spacing_hz, r.sample_count,
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
                extreme_rows: list[tuple[Any, ...]] = []
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
                    worst_qdb = min(vector)
                    worst_offset = vector.index(worst_qdb)
                    worst_subcarrier_index = int(row["first_active_index"]) + worst_offset
                    extreme_rows.append(
                        (
                            int(row["capture_attempt_id"]),
                            job_id,
                            int(row["target_id"]),
                            worst_qdb,
                            worst_subcarrier_index,
                            int(row["zero_frequency_hz"])
                            + worst_subcarrier_index * spacing_hz,
                            self._now(),
                        )
                    )
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
                    cursor.executemany(
                        """
                        INSERT INTO rxmer_channel_extreme
                        (capture_attempt_id, job_id, target_id, worst_qdb,
                         worst_subcarrier_index, worst_frequency_hz, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE worst_qdb=VALUES(worst_qdb),
                            worst_subcarrier_index=VALUES(worst_subcarrier_index),
                            worst_frequency_hz=VALUES(worst_frequency_hz)
                        """,
                        extreme_rows,
                    )
                    cursor.execute(
                        "UPDATE rxmer_spectrum_build SET lease_until="
                        "DATE_ADD(UTC_TIMESTAMP(), INTERVAL 10 MINUTE), updated_at=%s "
                        "WHERE job_id=%s AND source_revision=%s AND lease_owner=%s "
                        "AND state='building'",
                        (self._now(), job_id, source_revision, lease_owner),
                    )
                    if cursor.rowcount == 0:
                        cursor.execute(
                            "SELECT 1 FROM rxmer_spectrum_build WHERE job_id=%s "
                            "AND source_revision=%s AND lease_owner=%s "
                            "AND state='building' LIMIT 1",
                            (job_id, source_revision, lease_owner),
                        )
                        if not cursor.fetchone():
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
                        INSERT INTO rxmer_modem_extreme
                        (job_id, target_id, worst_qdb, worst_channel_id,
                         worst_subcarrier_index, worst_frequency_hz, updated_at)
                        SELECT job_id, target_id, worst_qdb, channel_id,
                               worst_subcarrier_index, worst_frequency_hz, %s
                        FROM (
                            SELECT e.job_id, e.target_id, e.worst_qdb,
                                   r.channel_id, e.worst_subcarrier_index,
                                   e.worst_frequency_hz,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY e.target_id
                                       ORDER BY e.worst_qdb ASC,
                                                e.worst_frequency_hz ASC,
                                                r.channel_id ASC
                                   ) AS extreme_rank
                            FROM rxmer_channel_extreme e
                            JOIN rxmer_channel_result r
                              ON r.capture_attempt_id=e.capture_attempt_id
                            JOIN rxmer_target_channel c
                              ON c.successful_attempt_id=e.capture_attempt_id
                            WHERE e.job_id=%s
                        ) ranked
                        WHERE extreme_rank=1
                        ON DUPLICATE KEY UPDATE worst_qdb=VALUES(worst_qdb),
                            worst_channel_id=VALUES(worst_channel_id),
                            worst_subcarrier_index=VALUES(worst_subcarrier_index),
                            worst_frequency_hz=VALUES(worst_frequency_hz),
                            updated_at=VALUES(updated_at)
                        """,
                        (self._now(), job_id),
                    )
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
            "best_subcarriers": [],
            "worst_subcarriers": [],
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

        ranking_select = """
            SELECT frequency_hz, sample_count, sum_qdb, worst_qdb, max_qdb
            FROM rxmer_spectrum_bin
            WHERE job_id=%s AND source_revision=%s
            ORDER BY (sum_qdb / sample_count) {direction}, frequency_hz ASC
            LIMIT 10
        """
        best_rows = self._query(
            ranking_select.format(direction="DESC"),
            (job_id, source_revision),
        )
        worst_rows = self._query(
            ranking_select.format(direction="ASC"),
            (job_id, source_revision),
        )

        def ranking_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    "frequency_hz": int(row["frequency_hz"]),
                    "average_db": round(
                        int(row["sum_qdb"]) / (4.0 * int(row["sample_count"])), 3
                    ),
                    "max_db": round(int(row["max_qdb"]) / 4.0, 3),
                    "worst_db": round(int(row["worst_qdb"]) / 4.0, 3),
                    "sample_count": int(row["sample_count"]),
                }
                for row in rows
            ]

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
                "best_subcarriers": ranking_rows(best_rows),
                "worst_subcarriers": ranking_rows(worst_rows),
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
