# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import pymysql
import pymysql.cursors

logger = logging.getLogger(__name__)

_EXECUTION_WINDOW_START_HOUR = 1   # 01:00 local
_EXECUTION_WINDOW_END_HOUR = 6     # 06:00 local
_MAX_CONCURRENCY = 10
_DEFAULT_CONCURRENCY = 5


class CmResetService:
    """Persistence and lifecycle management for CM bulk reset jobs."""

    def __init__(self) -> None:
        self._db_lock = threading.Lock()
        self._schema_ensured = False

    # ── DB helpers ────────────────────────────────────────────

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
            read_timeout=60,
            write_timeout=30,
        )

    def _execute(self, sql: str, params=None):
        with self._db_lock:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params or ())
                conn.commit()
            finally:
                conn.close()

    def _query(self, sql: str, params=None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return list(cur.fetchall())
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # ── Schema ────────────────────────────────────────────────

    def ensure_schema(self) -> None:
        if self._schema_ensured:
            return
        ddl_statements = [
            """
            CREATE TABLE IF NOT EXISTS cm_reset_job (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                public_id CHAR(36) NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'planned',
                scope_type VARCHAR(24) NOT NULL,
                scope_json JSON NOT NULL,
                scheduled_start DATETIME NULL,
                requested_by VARCHAR(64) NULL,
                idempotency_key VARCHAR(128) NULL,
                max_concurrency SMALLINT NOT NULL DEFAULT 5,
                targets_total INT NOT NULL DEFAULT 0,
                targets_succeeded INT NOT NULL DEFAULT 0,
                targets_failed INT NOT NULL DEFAULT 0,
                error_text TEXT NULL,
                cancel_requested_at DATETIME NULL,
                lease_owner VARCHAR(128) NULL,
                lease_until DATETIME NULL,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_cm_reset_job_public_id (public_id),
                INDEX idx_cm_reset_job_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS cm_reset_target (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                job_id BIGINT NOT NULL,
                mac VARCHAR(20) NOT NULL,
                modem_ip VARCHAR(45) NULL,
                cmts VARCHAR(128) NULL,
                cmts_ip VARCHAR(45) NULL,
                fiber_node VARCHAR(128) NULL,
                state VARCHAR(24) NOT NULL DEFAULT 'planned',
                error_text TEXT NULL,
                reset_at DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_cm_reset_target_job_state (job_id, state),
                CONSTRAINT fk_cm_reset_target_job FOREIGN KEY (job_id)
                    REFERENCES cm_reset_job(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for ddl in ddl_statements:
                    try:
                        cur.execute(ddl)
                    except pymysql.err.OperationalError:
                        pass
            conn.commit()
        finally:
            conn.close()
        self._schema_ensured = True

    # ── Execution window ──────────────────────────────────────

    @staticmethod
    def is_within_execution_window(dt: Optional[datetime] = None) -> bool:
        """Check if the given datetime (or now) is within 01:00-06:00 local."""
        if dt is None:
            dt = datetime.now()
        return _EXECUTION_WINDOW_START_HOUR <= dt.hour < _EXECUTION_WINDOW_END_HOUR

    @staticmethod
    def next_execution_window_start() -> datetime:
        """Return the next 01:00 local time."""
        now = datetime.now()
        candidate = now.replace(hour=_EXECUTION_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
        if now >= candidate:
            candidate += timedelta(days=1)
        return candidate

    # ── Planning ──────────────────────────────────────────────

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a reset job and populate targets from the scope."""
        self.ensure_schema()

        scope = dict(payload.get("scope") or {})
        scope_type = str(scope.get("type") or "").strip().lower()
        if scope_type not in {"single", "cmts", "fiber_node", "file"}:
            raise ValueError(f"Unsupported scope type: {scope_type}")

        requested_by = str(payload.get("requested_by") or "admin").strip()[:64]
        idempotency_key = payload.get("idempotency_key")
        scheduled_start = payload.get("scheduled_start")

        # Validate scheduled_start is within window
        scheduled_dt: Optional[datetime] = None
        if scheduled_start:
            scheduled_dt = datetime.fromisoformat(str(scheduled_start))
            if not self.is_within_execution_window(scheduled_dt):
                raise ValueError(
                    f"Scheduled start must be between "
                    f"{_EXECUTION_WINDOW_START_HOUR:02d}:00 and {_EXECUTION_WINDOW_END_HOUR:02d}:00. "
                    f"Got {scheduled_dt.strftime('%H:%M')}."
                )

        # Idempotency check
        if idempotency_key:
            existing = self._query(
                "SELECT public_id FROM cm_reset_job WHERE requested_by=%s "
                "AND idempotency_key=%s LIMIT 1",
                (requested_by, idempotency_key),
            )
            if existing:
                return self.get_job(existing[0]["public_id"])

        public_id = str(uuid.uuid4())
        scope_json = json.dumps(scope, separators=(",", ":"))
        now = self._now()

        conn = self._connect(autocommit=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cm_reset_job
                    (public_id, status, scope_type, scope_json, scheduled_start,
                     requested_by, idempotency_key, created_at, updated_at)
                    VALUES (%s, 'planned', %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        public_id, scope_type, scope_json,
                        scheduled_dt.strftime("%Y-%m-%d %H:%M:%S") if scheduled_dt else None,
                        requested_by, idempotency_key, now, now,
                    ),
                )
                job_id = cursor.lastrowid

                # Resolve targets based on scope
                targets = self._resolve_targets(cursor, scope_type, scope)
                if not targets:
                    raise ValueError("No targets resolved from scope (check CMTS/fiber-node names or MAC addresses)")

                # Batch insert targets
                insert_sql = """
                    INSERT INTO cm_reset_target
                    (job_id, mac, modem_ip, cmts, cmts_ip, fiber_node, state, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'planned', %s, %s)
                """
                batch = [
                    (job_id, t["mac"], t.get("ip"), t.get("cmts"), t.get("cmts_ip"),
                     t.get("fiber_node"), now, now)
                    for t in targets
                ]
                cursor.executemany(insert_sql, batch)

                # Update total count
                cursor.execute(
                    "UPDATE cm_reset_job SET targets_total=%s, updated_at=%s WHERE id=%s",
                    (len(targets), now, job_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return self.get_job(public_id)

    def _resolve_targets(self, cursor, scope_type: str, scope: dict) -> list[dict[str, Any]]:
        """Resolve MAC addresses from the given scope."""
        if scope_type == "single":
            mac = str(scope.get("mac") or "").strip()
            if not mac:
                raise ValueError("single scope requires 'mac'")
            # Look up in inventory for IP/CMTS info
            rows = self._query(
                "SELECT mac, ip, cmts, cmts_ip, fiber_node "
                "FROM modem_inventory_current WHERE mac=%s LIMIT 1",
                (mac,),
            )
            if rows:
                r = rows[0]
                return [{"mac": r["mac"], "ip": r.get("ip"), "cmts": r.get("cmts"),
                         "cmts_ip": r.get("cmts_ip"), "fiber_node": r.get("fiber_node")}]
            # Not in inventory — still allow reset with just the MAC
            return [{"mac": mac}]

        elif scope_type == "cmts":
            cmts_names = [str(c).strip() for c in (scope.get("cmts") or []) if str(c).strip()]
            if not cmts_names:
                raise ValueError("cmts scope requires at least one CMTS name")
            placeholders = ",".join(["%s"] * len(cmts_names))
            rows = self._query(
                f"SELECT mac, ip, cmts, cmts_ip, fiber_node "
                f"FROM modem_inventory_current WHERE cmts IN ({placeholders}) "
                f"AND status IN ('operational','registrationComplete','ipComplete','online')",
                cmts_names,
            )
            return [{"mac": r["mac"], "ip": r.get("ip"), "cmts": r.get("cmts"),
                     "cmts_ip": r.get("cmts_ip"), "fiber_node": r.get("fiber_node")}
                    for r in rows]

        elif scope_type == "fiber_node":
            cmts_name = str(scope.get("cmts") or "").strip()
            fiber_nodes = [str(fn).strip() for fn in (scope.get("fiber_nodes") or []) if str(fn).strip()]
            if not cmts_name:
                raise ValueError("fiber_node scope requires 'cmts'")
            if not fiber_nodes:
                raise ValueError("fiber_node scope requires at least one fiber node")
            fn_placeholders = ",".join(["%s"] * len(fiber_nodes))
            rows = self._query(
                f"""
                SELECT m.mac, m.ip, m.cmts, m.cmts_ip, t.fiber_node
                FROM modem_inventory_current m
                JOIN topology_fiber_node_map t
                  ON t.bare_mac = LOWER(REPLACE(REPLACE(REPLACE(m.mac, ':', ''), '-', ''), '.', ''))
                WHERE m.cmts = %s
                  AND t.fiber_node IN ({fn_placeholders})
                  AND t.snapshot_id = (SELECT MAX(id) FROM topology_snapshots)
                  AND m.status IN ('operational','registrationComplete','ipComplete','online')
                """,
                (cmts_name, *fiber_nodes),
            )
            return [{"mac": r["mac"], "ip": r.get("ip"), "cmts": r.get("cmts"),
                     "cmts_ip": r.get("cmts_ip"), "fiber_node": r.get("fiber_node")}
                    for r in rows]

        elif scope_type == "file":
            mac_list = [str(m).strip() for m in (scope.get("mac_list") or []) if str(m).strip()]
            if not mac_list:
                raise ValueError("file scope requires 'mac_list' with at least one MAC address")
            # Enrich from inventory where possible
            placeholders = ",".join(["%s"] * len(mac_list))
            rows = self._query(
                f"SELECT mac, ip, cmts, cmts_ip, fiber_node "
                f"FROM modem_inventory_current WHERE mac IN ({placeholders})",
                mac_list,
            )
            found = {r["mac"].lower(): r for r in rows}
            targets = []
            for mac in mac_list:
                r = found.get(mac.lower())
                if r:
                    targets.append({"mac": r["mac"], "ip": r.get("ip"), "cmts": r.get("cmts"),
                                    "cmts_ip": r.get("cmts_ip"), "fiber_node": r.get("fiber_node")})
                else:
                    targets.append({"mac": mac})
            return targets

        return []

    # ── Job lifecycle ─────────────────────────────────────────

    def get_job(self, public_id: str) -> dict[str, Any]:
        self.ensure_schema()
        rows = self._query("SELECT * FROM cm_reset_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not rows:
            raise KeyError(public_id)
        return self._format_job(rows[0])

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        self.ensure_schema()
        rows = self._query(
            "SELECT * FROM cm_reset_job ORDER BY id DESC LIMIT %s",
            (max(1, min(int(limit), 200)),),
        )
        return [self._format_job(r) for r in rows]

    def activate_job(self, public_id: str, lease_owner: str) -> None:
        """Move job to running state."""
        self.ensure_schema()
        now = self._now()
        lease_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        self._execute(
            "UPDATE cm_reset_job SET status='running', lease_owner=%s, lease_until=%s, "
            "started_at=%s, updated_at=%s WHERE public_id=%s AND status IN ('planned','queued')",
            (lease_owner, lease_until, now, now, public_id),
        )

    def extend_lease(self, job_id: int, lease_owner: str) -> None:
        lease_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        self._execute(
            "UPDATE cm_reset_job SET lease_until=%s, updated_at=%s "
            "WHERE id=%s AND lease_owner=%s",
            (lease_until, self._now(), job_id, lease_owner),
        )

    def claim_targets(self, job_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """Claim a batch of planned targets for processing."""
        self.ensure_schema()
        conn = self._connect(autocommit=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, mac, modem_ip, cmts, cmts_ip, fiber_node "
                    "FROM cm_reset_target WHERE job_id=%s AND state='planned' "
                    "ORDER BY id ASC LIMIT %s FOR UPDATE SKIP LOCKED",
                    (job_id, max(1, min(int(limit), _MAX_CONCURRENCY))),
                )
                targets = list(cursor.fetchall())
                if targets:
                    ids = [int(t["id"]) for t in targets]
                    placeholders = ",".join(["%s"] * len(ids))
                    cursor.execute(
                        f"UPDATE cm_reset_target SET state='running', updated_at=%s "
                        f"WHERE id IN ({placeholders})",
                        (self._now(), *ids),
                    )
            conn.commit()
            return targets
        except Exception:
            conn.rollback()
            return []
        finally:
            conn.close()

    def mark_target_done(self, target_id: int) -> None:
        """Mark a target as successfully reset (fire-and-forget)."""
        now = self._now()
        self._execute(
            "UPDATE cm_reset_target SET state='complete', reset_at=%s, updated_at=%s WHERE id=%s",
            (now, now, target_id),
        )

    def mark_target_failed(self, target_id: int, error: str) -> None:
        """Mark a target as failed."""
        now = self._now()
        self._execute(
            "UPDATE cm_reset_target SET state='failed', error_text=%s, updated_at=%s WHERE id=%s",
            (error[:500], now, target_id),
        )

    def finish_job(self, job_id: int, error_text: Optional[str] = None) -> None:
        """Finalize the job — compute final counts and set status."""
        self.ensure_schema()
        counts = self._query(
            "SELECT "
            "  SUM(state='complete') AS succeeded, "
            "  SUM(state='failed') AS failed "
            "FROM cm_reset_target WHERE job_id=%s",
            (job_id,),
        )
        succeeded = int(counts[0].get("succeeded") or 0) if counts else 0
        failed = int(counts[0].get("failed") or 0) if counts else 0
        status = "completed" if failed == 0 else "completed_with_errors"
        if error_text:
            status = "failed"
        now = self._now()
        self._execute(
            "UPDATE cm_reset_job SET status=%s, targets_succeeded=%s, targets_failed=%s, "
            "error_text=%s, finished_at=%s, updated_at=%s WHERE id=%s",
            (status, succeeded, failed, error_text, now, now, job_id),
        )

    def request_cancel(self, public_id: str) -> dict[str, Any]:
        self.ensure_schema()
        now = self._now()
        self._execute(
            "UPDATE cm_reset_job SET cancel_requested_at=%s, updated_at=%s "
            "WHERE public_id=%s AND status IN ('planned','queued','running')",
            (now, now, public_id),
        )
        return self.get_job(public_id)

    def job_cancel_requested(self, job_id: int) -> bool:
        rows = self._query(
            "SELECT cancel_requested_at FROM cm_reset_job WHERE id=%s LIMIT 1",
            (job_id,),
        )
        if not rows:
            return True
        return rows[0].get("cancel_requested_at") is not None

    def delete_job(self, public_id: str) -> dict[str, str]:
        self.ensure_schema()
        rows = self._query(
            "SELECT id, status FROM cm_reset_job WHERE public_id=%s LIMIT 1",
            (public_id,),
        )
        if not rows:
            raise KeyError(public_id)
        if rows[0]["status"] == "running":
            raise ValueError("Cannot delete a running job — cancel it first")
        job_id = int(rows[0]["id"])
        self._execute("DELETE FROM cm_reset_target WHERE job_id=%s", (job_id,))
        self._execute("DELETE FROM cm_reset_job WHERE id=%s", (job_id,))
        return {"status": "success", "deleted": public_id}

    def list_targets(
        self,
        public_id: str,
        *,
        cursor: int = 0,
        limit: int = 200,
        state: Optional[str] = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        jobs = self._query("SELECT id FROM cm_reset_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        safe_limit = max(1, min(int(limit), 1000))
        filters = ["job_id=%s", "id>%s"]
        params: list[Any] = [job_id, max(0, int(cursor))]
        if state:
            filters.append("state=%s")
            params.append(str(state).strip())
        where_sql = " AND ".join(filters)
        rows = self._query(
            f"SELECT id, mac, modem_ip, cmts, fiber_node, state, error_text, reset_at "
            f"FROM cm_reset_target WHERE {where_sql} ORDER BY id ASC LIMIT %s",
            (*params, safe_limit + 1),
        )
        has_more = len(rows) > safe_limit
        page = rows[:safe_limit]
        next_cursor = int(page[-1]["id"]) if has_more and page else None
        return {"targets": page, "next_cursor": next_cursor, "has_more": has_more}

    def get_job_id_by_public_id(self, public_id: str) -> int:
        rows = self._query("SELECT id FROM cm_reset_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not rows:
            raise KeyError(public_id)
        return int(rows[0]["id"])

    # ── Options (for UI selectors) ────────────────────────────

    def get_cmts_options(self) -> list[str]:
        """Return distinct CMTS names from inventory for the scope selector (CCAP only)."""
        rows = self._query(
            "SELECT DISTINCT cmts FROM modem_inventory_current "
            "WHERE cmts IS NOT NULL AND TRIM(cmts)<>'' "
            "AND LOWER(cmts) LIKE %s ORDER BY cmts",
            ("%ccap%",),
        )
        return [str(r["cmts"]) for r in rows]

    def get_fiber_node_options(self, cmts: str) -> list[str]:
        """Return distinct fiber nodes for a given CMTS (from topology mapping)."""
        rows = self._query(
            """
            SELECT DISTINCT t.fiber_node
            FROM topology_fiber_node_map t
            JOIN modem_inventory_current m
              ON t.bare_mac = LOWER(REPLACE(REPLACE(REPLACE(m.mac, ':', ''), '-', ''), '.', ''))
            WHERE m.cmts = %s
              AND t.snapshot_id = (SELECT MAX(id) FROM topology_snapshots)
              AND t.fiber_node IS NOT NULL AND TRIM(t.fiber_node) <> ''
            ORDER BY t.fiber_node
            """,
            (cmts,),
        )
        return [str(r["fiber_node"]) for r in rows]

    # ── Formatting ────────────────────────────────────────────

    @staticmethod
    def _format_job(row: dict[str, Any]) -> dict[str, Any]:
        def _dt(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v.replace(tzinfo=timezone.utc).isoformat()
            return str(v)

        total = int(row.get("targets_total") or 0)
        succeeded = int(row.get("targets_succeeded") or 0)
        failed = int(row.get("targets_failed") or 0)
        return {
            "public_id": row["public_id"],
            "status": row["status"],
            "scope_type": row.get("scope_type"),
            "targets_total": total,
            "targets_succeeded": succeeded,
            "targets_failed": failed,
            "targets_pending": max(0, total - succeeded - failed),
            "scheduled_start": _dt(row.get("scheduled_start")),
            "started_at": _dt(row.get("started_at")),
            "finished_at": _dt(row.get("finished_at")),
            "created_at": _dt(row.get("created_at")),
            "requested_by": row.get("requested_by"),
            "error_text": row.get("error_text"),
        }


# Singleton
cm_reset_service = CmResetService()
