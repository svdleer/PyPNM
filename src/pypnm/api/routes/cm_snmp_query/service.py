# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator, Optional

import pymysql
import pymysql.cursors
import requests

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 20
_DEFAULT_CONCURRENCY = 10
_DIRECTORY_CACHE_TTL_SECONDS = 60
_DIRECTORY_CACHE_MAX_STALE_SECONDS = 300


class CmtsDirectoryUnavailableError(RuntimeError):
    """The authoritative CMTS directory cannot be used safely."""


class CmSnmpQueryService:
    """Persistence and lifecycle for custom SNMP query jobs + templates."""

    def __init__(self) -> None:
        self._db_lock = threading.Lock()
        self._schema_ensured = False
        self._directory_cache_lock = threading.Lock()
        self._directory_cache: tuple[float, list[dict[str, str]]] | None = None

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
            CREATE TABLE IF NOT EXISTS snmp_query_template (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(128) NOT NULL,
                description VARCHAR(512) NULL,
                oids_json JSON NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_snmp_template_name (name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS snmp_query_oid_verification (
                receipt_id CHAR(36) NOT NULL,
                numeric_oid VARCHAR(256) NOT NULL,
                target_mode VARCHAR(8) NOT NULL,
                affiliate VARCHAR(16) NOT NULL,
                cmts VARCHAR(128) NULL,
                modem_vendor VARCHAR(64) NULL,
                modem_type VARCHAR(128) NULL,
                verified_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                used_at DATETIME NULL,
                used_job_id BIGINT NULL,
                PRIMARY KEY (receipt_id),
                INDEX idx_snmp_query_oid_verification_expiry (expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS snmp_query_job (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                public_id CHAR(36) NOT NULL,
                status VARCHAR(24) NOT NULL DEFAULT 'planned',
                scope_type VARCHAR(24) NOT NULL,
                scope_json JSON NOT NULL,
                oids_json JSON NOT NULL,
                requested_by VARCHAR(64) NULL,
                max_concurrency SMALLINT NOT NULL DEFAULT 10,
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
                UNIQUE KEY uk_snmp_query_job_public_id (public_id),
                INDEX idx_snmp_query_job_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS snmp_query_target (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                job_id BIGINT NOT NULL,
                mac VARCHAR(20) NOT NULL,
                modem_ip VARCHAR(45) NULL,
                cmts VARCHAR(128) NULL,
                cmts_ip VARCHAR(45) NULL,
                fiber_node VARCHAR(128) NULL,
                state VARCHAR(24) NOT NULL DEFAULT 'planned',
                results_json JSON NULL,
                error_text TEXT NULL,
                completed_at DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                INDEX idx_snmp_query_target_job_state (job_id, state),
                CONSTRAINT fk_snmp_query_target_job FOREIGN KEY (job_id)
                    REFERENCES snmp_query_job(id) ON DELETE CASCADE
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

    # ── Templates ─────────────────────────────────────────────

    def create_template(self, name: str, description: str | None, oids: list[dict]) -> dict[str, Any]:
        self.ensure_schema()
        now = self._now()
        oids_json = json.dumps(oids, separators=(",", ":"))
        conn = self._connect(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO snmp_query_template (name, description, oids_json, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE description=%s, oids_json=%s, updated_at=%s",
                    (name, description, oids_json, now, now, description, oids_json, now),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_template_by_name(name)

    def list_templates(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        rows = self._query("SELECT * FROM snmp_query_template ORDER BY name ASC")
        return [self._format_template(r) for r in rows]

    def get_template(self, template_id: int) -> dict[str, Any]:
        self.ensure_schema()
        rows = self._query("SELECT * FROM snmp_query_template WHERE id=%s LIMIT 1", (template_id,))
        if not rows:
            raise KeyError(template_id)
        return self._format_template(rows[0])

    def get_template_by_name(self, name: str) -> dict[str, Any]:
        rows = self._query("SELECT * FROM snmp_query_template WHERE name=%s LIMIT 1", (name,))
        if not rows:
            raise KeyError(name)
        return self._format_template(rows[0])

    def delete_template(self, template_id: int) -> None:
        self.ensure_schema()
        self._execute("DELETE FROM snmp_query_template WHERE id=%s", (template_id,))

    @staticmethod
    def _format_template(row: dict[str, Any]) -> dict[str, Any]:
        oids_raw = row.get("oids_json")
        if isinstance(oids_raw, str):
            oids = json.loads(oids_raw)
        elif isinstance(oids_raw, list):
            oids = oids_raw
        else:
            oids = []
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "description": row.get("description"),
            "oids": oids,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }

    # ── Job planning ──────────────────────────────────────────

    def issue_verification_receipt(
        self,
        *,
        numeric_oid: str,
        target_mode: str,
        affiliate: str,
        cmts: str | None,
        modem_vendor: str | None,
        modem_type: str | None,
    ) -> dict[str, str]:
        """Persist a short-lived proof from a successful OID verification."""
        self.ensure_schema()
        receipt_id = str(uuid.uuid4())
        normalized_affiliate = self._normalize_affiliate(affiliate)
        normalized_cmts = str(cmts or "").strip().casefold() or None
        vendor = str(modem_vendor or "").strip() or None
        model = str(modem_type or "").strip() or None
        verified_at = datetime.now(timezone.utc)
        expires_at = verified_at + timedelta(minutes=15)
        self._execute(
            """
            INSERT INTO snmp_query_oid_verification
            (receipt_id, numeric_oid, target_mode, affiliate, cmts, modem_vendor,
             modem_type, verified_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                receipt_id,
                numeric_oid,
                target_mode,
                normalized_affiliate,
                normalized_cmts,
                vendor,
                model,
                verified_at.strftime("%Y-%m-%d %H:%M:%S"),
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        return {
            "receipt_id": receipt_id,
            "expires_at": expires_at.isoformat(),
            "target_mode": target_mode,
        }

    def _plan_verification_context(self, scope_type: str, scope: dict) -> dict[str, str | None]:
        """Return the modem-query scope a verification receipt must match."""
        affiliate = self._normalize_affiliate(scope.get("affiliate"))
        vendor = self._scope_facet(scope, "modem_vendor", 64)
        model = self._scope_facet(scope, "modem_type", 128)
        if scope_type == "cmts":
            cmts_values = self._scope_strings(scope.get("cmts"), "cmts", 128)
            if len(cmts_values) != 1:
                raise ValueError("Verified modem OIDs require exactly one CMTS per task")
            cmts = cmts_values[0].casefold()
        elif scope_type == "fiber_node":
            cmts = self._scope_facet(scope, "cmts", 128)
            cmts = cmts.casefold() if cmts else None
        else:
            cmts = None
        return {
            "affiliate": affiliate,
            "cmts": cmts,
            "modem_vendor": vendor,
            "modem_type": model,
        }

    def _consume_verification_receipts(
        self,
        cursor,
        *,
        oids: list[dict],
        receipt_ids: object,
        scope_type: str,
        scope: dict,
        job_id: int,
        now: str,
    ) -> None:
        """Atomically validate and consume modem OID verification receipts."""
        if not isinstance(receipt_ids, list) or not receipt_ids:
            raise ValueError("Verify every OID on a cable modem before creating a task")
        normalized_receipt_ids = [str(value).strip() for value in receipt_ids]
        if any(not value for value in normalized_receipt_ids):
            raise ValueError("Invalid OID verification receipt")
        if len(set(normalized_receipt_ids)) != len(normalized_receipt_ids):
            raise ValueError("Each OID requires a distinct verification receipt")

        from pypnm.api.routes.cm_snmp_query.oid_resolver import resolve_oid

        numeric_oids = [resolve_oid(str(entry.get("oid") or "").strip()) for entry in oids]
        if len(set(numeric_oids)) != len(numeric_oids):
            raise ValueError("Duplicate OIDs require a single labeled entry")
        if len(normalized_receipt_ids) != len(numeric_oids):
            raise ValueError("Every OID requires one verification receipt")

        placeholders = ",".join(["%s"] * len(normalized_receipt_ids))
        cursor.execute(
            f"SELECT * FROM snmp_query_oid_verification WHERE receipt_id IN ({placeholders}) FOR UPDATE",
            tuple(normalized_receipt_ids),
        )
        receipts = {str(row["receipt_id"]): row for row in cursor.fetchall()}
        if len(receipts) != len(normalized_receipt_ids):
            raise ValueError("OID verification receipt is missing or invalid")

        context = self._plan_verification_context(scope_type, scope)
        expected_by_oid = {row["numeric_oid"]: row for row in receipts.values()}
        if set(expected_by_oid) != set(numeric_oids):
            raise ValueError("OID verification receipts do not match the planned OIDs")
        current_time = datetime.now(timezone.utc).replace(tzinfo=None)
        for numeric_oid in numeric_oids:
            receipt = expected_by_oid[numeric_oid]
            if receipt.get("used_at") is not None:
                raise ValueError("OID verification receipt has already been used")
            expires_at = receipt.get("expires_at")
            if not expires_at or expires_at <= current_time:
                raise ValueError("OID verification receipt has expired; verify the OID again")
            if receipt.get("target_mode") != "modem":
                raise ValueError("Modem query tasks require cable-modem OID verification")
            for field, expected in context.items():
                actual = receipt.get(field)
                if actual != expected:
                    raise ValueError(
                        "OID verification does not match the selected modem query scope"
                    )

        cursor.execute(
            f"UPDATE snmp_query_oid_verification SET used_at=%s, used_job_id=%s "
            f"WHERE receipt_id IN ({placeholders})",
            (now, job_id, *normalized_receipt_ids),
        )

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        scope = dict(payload.get("scope") or {})
        scope_type = str(scope.get("type") or "all_network").strip().lower()
        if scope_type not in {"all_network", "cmts", "fiber_node"}:
            raise ValueError(f"Unsupported scope type: {scope_type}")

        # Resolve OIDs from template or inline
        template_id = payload.get("template_id")
        if template_id:
            tmpl = self.get_template(int(template_id))
            oids = tmpl["oids"]
        else:
            oids = payload.get("oids") or []
        if not oids or not isinstance(oids, list):
            raise ValueError("At least one OID is required")
        if len(oids) > 50:
            raise ValueError("Maximum 50 OIDs per job")

        max_modems = payload.get("max_modems")
        requested_by = str(payload.get("requested_by") or "admin").strip()[:64]
        verification_receipts = payload.get("verification_receipts")
        targets = self._resolve_targets(scope_type, scope, max_modems)
        if not targets:
            raise ValueError("No targets resolved from scope")

        public_id = str(uuid.uuid4())
        scope_json = json.dumps(scope, separators=(",", ":"))
        oids_json = json.dumps(oids, separators=(",", ":"))
        now = self._now()

        conn = self._connect(autocommit=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO snmp_query_job
                    (public_id, status, scope_type, scope_json, oids_json,
                     requested_by, created_at, updated_at)
                    VALUES (%s, 'planned', %s, %s, %s, %s, %s, %s)
                    """,
                    (public_id, scope_type, scope_json, oids_json, requested_by, now, now),
                )
                job_id = cursor.lastrowid
                self._consume_verification_receipts(
                    cursor,
                    oids=oids,
                    receipt_ids=verification_receipts,
                    scope_type=scope_type,
                    scope=scope,
                    job_id=job_id,
                    now=now,
                )

                insert_sql = """
                    INSERT INTO snmp_query_target
                    (job_id, mac, modem_ip, cmts, cmts_ip, fiber_node, state, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'planned', %s, %s)
                """
                batch = [
                    (job_id, t["mac"], t.get("ip"), t.get("cmts"), t.get("cmts_ip"),
                     t.get("fiber_node"), now, now)
                    for t in targets
                ]
                cursor.executemany(insert_sql, batch)
                cursor.execute(
                    "UPDATE snmp_query_job SET targets_total=%s, updated_at=%s WHERE id=%s",
                    (len(targets), now, job_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return self.get_job(public_id)

    @staticmethod
    def _normalize_affiliate(value: object) -> str:
        affiliate = "all" if value is None else str(value).strip().lower()
        if affiliate not in {"all", "vfz", "fziggo", "fupc"}:
            raise ValueError("affiliate must be one of: all, vfz, fziggo, fupc")
        return affiliate

    @staticmethod
    def _online_inventory_filter() -> str:
        return "AND m.status IN ('operational','registrationComplete','ipComplete','online')"

    @staticmethod
    def _directory_cache_seconds(name: str, default: int) -> int:
        try:
            return max(0, int(os.environ.get(name, default)))
        except (TypeError, ValueError):
            return default

    def _get_cmts_directory(self) -> list[dict[str, str]]:
        """Return normalized, non-VCAS Device API rows from a successful response."""
        now = time.monotonic()
        ttl = self._directory_cache_seconds(
            "CM_SNMP_DIRECTORY_CACHE_TTL_SECONDS", _DIRECTORY_CACHE_TTL_SECONDS
        )
        max_stale = max(
            ttl,
            self._directory_cache_seconds(
                "CM_SNMP_DIRECTORY_CACHE_MAX_STALE_SECONDS",
                _DIRECTORY_CACHE_MAX_STALE_SECONDS,
            ),
        )
        with self._directory_cache_lock:
            if self._directory_cache and now - self._directory_cache[0] <= ttl:
                return [dict(row) for row in self._directory_cache[1]]
            try:
                api_url = os.environ.get(
                    "APPDB_API_URL", "https://appdb.oss.local/isw/api"
                ).rstrip("/")
                api_user = os.environ.get("APPDB_API_USER", "")
                api_pass = os.environ.get("APPDB_API_PASS", "")
                response = requests.get(
                    f"{api_url}/search",
                    params={"type": "hostname", "q": "*"},
                    auth=(api_user, api_pass) if api_user else None,
                    verify=False,
                    timeout=20,
                )
                response.raise_for_status()
                payload = response.json() if response.content else []
                if isinstance(payload, list):
                    raw_rows = payload
                elif isinstance(payload, dict):
                    raw_rows = next(
                        (
                            payload[key]
                            for key in ("data", "results", "items")
                            if isinstance(payload.get(key), list)
                        ),
                        None,
                    )
                    if raw_rows is None:
                        raise ValueError("Device API response has no record list")
                else:
                    raise ValueError("Device API response is not a record list")

                records: list[dict[str, str]] = []
                for row in raw_rows:
                    if not isinstance(row, dict):
                        continue
                    hostname = str(
                        row.get("HostName") or row.get("hostname") or row.get("name") or ""
                    ).strip()
                    if "-vcas" in hostname.casefold():
                        continue
                    ip_address = str(
                        row.get("IPAddress") or row.get("ip") or row.get("ip_address") or ""
                    ).strip()
                    if not hostname and not ip_address:
                        continue
                    alias = str(row.get("Alias") or row.get("alias") or "").strip()
                    records.append(
                        {
                            "hostname": hostname.casefold(),
                            "ip_address": ip_address.casefold(),
                            "affiliate": "fupc" if alias else "fziggo",
                        }
                    )
                self._directory_cache = (now, records)
                return [dict(row) for row in records]
            except Exception as exc:
                if self._directory_cache and now - self._directory_cache[0] <= max_stale:
                    logger.warning("Using bounded-stale CMTS directory cache: %s", exc)
                    return [dict(row) for row in self._directory_cache[1]]
                raise CmtsDirectoryUnavailableError(
                    "Authoritative CMTS directory is unavailable"
                ) from exc

    def _affiliate_inventory_predicate(self, affiliate: str) -> tuple[str, list[str]]:
        """Constrain inventory to Device API members classified by Alias."""
        if affiliate == "all":
            return "", []
        directory = self._get_cmts_directory()
        allowed = {"fupc", "fziggo"} if affiliate == "vfz" else {affiliate}
        hostnames = sorted(
            {row["hostname"] for row in directory if row["affiliate"] in allowed and row["hostname"]}
        )
        ip_addresses = sorted(
            {row["ip_address"] for row in directory if row["affiliate"] in allowed and row["ip_address"]}
        )
        if not hostnames and not ip_addresses:
            return "AND 1=0", []
        clauses: list[str] = []
        params: list[str] = []
        if hostnames:
            clauses.append(
                "LOWER(TRIM(COALESCE(m.cmts,''))) IN (" + ",".join(["%s"] * len(hostnames)) + ")"
            )
            params.extend(hostnames)
        if ip_addresses:
            clauses.append(
                "LOWER(TRIM(COALESCE(m.cmts_ip,''))) IN ("
                + ",".join(["%s"] * len(ip_addresses))
                + ")"
            )
            params.extend(ip_addresses)
        return "AND (" + " OR ".join(clauses) + ")", params

    @staticmethod
    def _scope_facet(scope: dict, key: str, max_length: int) -> str | None:
        value = scope.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{key} must not be blank")
        if len(normalized) > max_length:
            raise ValueError(f"{key} must be at most {max_length} characters")
        return normalized

    def _inventory_scope_predicates(self, scope: dict) -> tuple[str, list[str]]:
        vendor = self._scope_facet(scope, "modem_vendor", 64)
        modem_type = self._scope_facet(scope, "modem_type", 128)
        clauses: list[str] = []
        params: list[str] = []
        if vendor is not None:
            clauses.append("AND TRIM(COALESCE(m.vendor,''))=%s")
            params.append(vendor)
        if modem_type is not None:
            clauses.append("AND TRIM(COALESCE(m.model,''))=%s")
            params.append(modem_type)
        return " ".join(clauses), params

    @staticmethod
    def _scope_strings(value: object, name: str, max_length: int) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        values = [str(item).strip() for item in value if str(item).strip()]
        if not values:
            raise ValueError(f"{name} requires at least one value")
        if any(len(item) > max_length for item in values):
            raise ValueError(f"{name} values must be at most {max_length} characters")
        return values

    def _resolve_targets(self, scope_type: str, scope: dict, max_modems: int | None) -> list[dict]:
        if max_modems is not None and not 1 <= int(max_modems) <= 100000:
            raise ValueError("max_modems must be between 1 and 100000")
        limit_clause = f"LIMIT {int(max_modems)}" if max_modems else ""
        affiliate = self._normalize_affiliate(scope.get("affiliate"))
        affiliate_filter, affiliate_params = self._affiliate_inventory_predicate(affiliate)
        facet_filter, facet_params = self._inventory_scope_predicates(scope)
        online_filter = self._online_inventory_filter()
        table_rows = self._query(
            "SELECT COUNT(*) AS table_count FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN "
            "('topology_snapshots', 'topology_fiber_node_map', "
            "'topology_fiber_node_map_state')"
        )
        topology_tables_ready = int(
            (table_rows[0] if table_rows else {}).get("table_count") or 0
        ) == 3

        if topology_tables_ready:
            topology_join = """
                LEFT JOIN topology_fiber_node_map t
                  ON t.bare_mac = CONVERT(
                      LOWER(REPLACE(REPLACE(REPLACE(m.mac, ':', ''), '-', ''), '.', ''))
                      USING ascii
                  ) COLLATE ascii_bin
                  AND t.snapshot_id = (
                      SELECT s.id FROM topology_snapshots s
                      JOIN topology_fiber_node_map_state ms
                        ON ms.snapshot_id = s.id AND ms.state = 'complete'
                      ORDER BY s.snapshot_date DESC, s.id DESC LIMIT 1
                  )
            """
            fiber_node_col = "COALESCE(t.fiber_node, m.fiber_node) AS fiber_node"
        else:
            topology_join = ""
            fiber_node_col = "m.fiber_node AS fiber_node"

        if scope_type == "all_network":
            rows = self._query(
                f"SELECT m.mac, m.ip, m.cmts, m.cmts_ip, {fiber_node_col} "
                f"FROM modem_inventory_current m {topology_join} "
                f"WHERE m.inventory_state<>'retired' {online_filter} {affiliate_filter} {facet_filter} "
                f"ORDER BY RAND() {limit_clause}",
                (*affiliate_params, *facet_params),
            )
        elif scope_type == "cmts":
            cmts_names = self._scope_strings(scope.get("cmts"), "cmts", 128)
            normalized_cmts = [name.casefold() for name in cmts_names]
            placeholders = ",".join(["%s"] * len(normalized_cmts))
            rows = self._query(
                f"SELECT m.mac, m.ip, m.cmts, m.cmts_ip, {fiber_node_col} "
                f"FROM modem_inventory_current m {topology_join} "
                f"WHERE m.inventory_state<>'retired' "
                f"AND LOWER(TRIM(COALESCE(m.cmts,''))) IN ({placeholders}) "
                f"{online_filter} {affiliate_filter} {facet_filter} "
                f"ORDER BY RAND() {limit_clause}",
                (*normalized_cmts, *affiliate_params, *facet_params),
            )
        elif scope_type == "fiber_node":
            cmts_name = self._scope_facet(scope, "cmts", 128)
            fiber_nodes = self._scope_strings(scope.get("fiber_nodes"), "fiber_nodes", 128)
            if not topology_tables_ready:
                raise ValueError("Fiber-node topology data is unavailable")
            fn_placeholders = ",".join(["%s"] * len(fiber_nodes))
            rows = self._query(
                f"""
                SELECT m.mac, m.ip, m.cmts, m.cmts_ip, t.fiber_node
                FROM modem_inventory_current m
                JOIN topology_fiber_node_map t
                  ON t.bare_mac = CONVERT(
                      LOWER(REPLACE(REPLACE(REPLACE(m.mac, ':', ''), '-', ''), '.', ''))
                      USING ascii
                  ) COLLATE ascii_bin
                WHERE m.inventory_state<>'retired'
                  AND LOWER(TRIM(COALESCE(m.cmts,''))) = %s
                  AND TRIM(t.fiber_node) IN ({fn_placeholders})
                  AND t.snapshot_id = (
                      SELECT s.id FROM topology_snapshots s
                      JOIN topology_fiber_node_map_state ms
                        ON ms.snapshot_id = s.id AND ms.state = 'complete'
                      ORDER BY s.snapshot_date DESC, s.id DESC LIMIT 1
                  )
                  {online_filter}
                  {affiliate_filter}
                  {facet_filter}
                ORDER BY RAND() {limit_clause}
                """,
                (cmts_name.casefold(), *fiber_nodes, *affiliate_params, *facet_params),
            )
        else:
            rows = []

        return [{"mac": r["mac"], "ip": r.get("ip"), "cmts": r.get("cmts"),
                 "cmts_ip": r.get("cmts_ip"), "fiber_node": r.get("fiber_node")}
                for r in rows]

    # ── Job lifecycle ─────────────────────────────────────────

    def get_job(self, public_id: str) -> dict[str, Any]:
        self.ensure_schema()
        rows = self._query("SELECT * FROM snmp_query_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not rows:
            raise KeyError(public_id)
        return self._format_job(rows[0])

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        self.ensure_schema()
        rows = self._query(
            "SELECT * FROM snmp_query_job ORDER BY id DESC LIMIT %s",
            (max(1, min(int(limit), 200)),),
        )
        return [self._format_job(r) for r in rows]

    def activate_job(self, public_id: str, lease_owner: str) -> None:
        self.ensure_schema()
        now = self._now()
        lease_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        self._execute(
            "UPDATE snmp_query_job SET status='running', lease_owner=%s, lease_until=%s, "
            "started_at=%s, updated_at=%s WHERE public_id=%s AND status='planned'",
            (lease_owner, lease_until, now, now, public_id),
        )

    def extend_lease(self, job_id: int, lease_owner: str) -> None:
        lease_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        self._execute(
            "UPDATE snmp_query_job SET lease_until=%s, updated_at=%s WHERE id=%s AND lease_owner=%s",
            (lease_until, self._now(), job_id, lease_owner),
        )

    def claim_targets(self, job_id: int, limit: int = 10) -> list[dict[str, Any]]:
        self.ensure_schema()
        conn = self._connect(autocommit=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, mac, modem_ip, cmts, cmts_ip, fiber_node "
                    "FROM snmp_query_target WHERE job_id=%s AND state='planned' "
                    "ORDER BY id ASC LIMIT %s FOR UPDATE SKIP LOCKED",
                    (job_id, max(1, min(int(limit), _MAX_CONCURRENCY))),
                )
                targets = list(cursor.fetchall())
                if targets:
                    ids = [int(t["id"]) for t in targets]
                    placeholders = ",".join(["%s"] * len(ids))
                    cursor.execute(
                        f"UPDATE snmp_query_target SET state='running', updated_at=%s "
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

    def record_target_result(self, target_id: int, results: dict[str, Any]) -> None:
        now = self._now()
        self._execute(
            "UPDATE snmp_query_target SET state='complete', results_json=%s, "
            "completed_at=%s, updated_at=%s WHERE id=%s",
            (json.dumps(results, separators=(",", ":")), now, now, target_id),
        )
        # Update live counter on the job
        self._execute(
            "UPDATE snmp_query_job SET targets_succeeded = ("
            "  SELECT COUNT(*) FROM snmp_query_target WHERE job_id = ("
            "    SELECT job_id FROM snmp_query_target WHERE id=%s"
            "  ) AND state='complete'"
            "), updated_at=%s WHERE id = ("
            "  SELECT job_id FROM snmp_query_target WHERE id=%s"
            ")",
            (target_id, now, target_id),
        )

    def mark_target_failed(self, target_id: int, error: str) -> None:
        now = self._now()
        self._execute(
            "UPDATE snmp_query_target SET state='failed', error_text=%s, updated_at=%s WHERE id=%s",
            (error[:500], now, target_id),
        )
        # Update live counter on the job
        self._execute(
            "UPDATE snmp_query_job SET targets_failed = ("
            "  SELECT COUNT(*) FROM snmp_query_target WHERE job_id = ("
            "    SELECT job_id FROM snmp_query_target WHERE id=%s"
            "  ) AND state='failed'"
            "), updated_at=%s WHERE id = ("
            "  SELECT job_id FROM snmp_query_target WHERE id=%s"
            ")",
            (target_id, now, target_id),
        )

    def finish_job(self, job_id: int, error_text: Optional[str] = None) -> None:
        self.ensure_schema()
        counts = self._query(
            "SELECT SUM(state='complete') AS succeeded, SUM(state='failed') AS failed "
            "FROM snmp_query_target WHERE job_id=%s",
            (job_id,),
        )
        succeeded = int(counts[0].get("succeeded") or 0) if counts else 0
        failed = int(counts[0].get("failed") or 0) if counts else 0
        status = "completed" if failed == 0 else "completed_with_errors"
        if error_text:
            status = "failed"
        now = self._now()
        self._execute(
            "UPDATE snmp_query_job SET status=%s, targets_succeeded=%s, targets_failed=%s, "
            "error_text=%s, finished_at=%s, updated_at=%s WHERE id=%s",
            (status, succeeded, failed, error_text, now, now, job_id),
        )

    def request_cancel(self, public_id: str) -> dict[str, Any]:
        self.ensure_schema()
        now = self._now()
        self._execute(
            "UPDATE snmp_query_job SET cancel_requested_at=%s, updated_at=%s "
            "WHERE public_id=%s AND status IN ('planned','running')",
            (now, now, public_id),
        )
        return self.get_job(public_id)

    def job_cancel_requested(self, job_id: int) -> bool:
        rows = self._query(
            "SELECT cancel_requested_at FROM snmp_query_job WHERE id=%s LIMIT 1", (job_id,)
        )
        if not rows:
            return True
        return rows[0].get("cancel_requested_at") is not None

    def delete_job(self, public_id: str) -> None:
        self.ensure_schema()
        rows = self._query("SELECT id, status FROM snmp_query_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not rows:
            raise KeyError(public_id)
        if rows[0]["status"] == "running":
            raise ValueError("Cannot delete a running job")
        job_id = int(rows[0]["id"])
        self._execute("DELETE FROM snmp_query_target WHERE job_id=%s", (job_id,))
        self._execute("DELETE FROM snmp_query_job WHERE id=%s", (job_id,))

    def get_job_id_by_public_id(self, public_id: str) -> int:
        rows = self._query("SELECT id FROM snmp_query_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not rows:
            raise KeyError(public_id)
        return int(rows[0]["id"])

    def get_job_oids(self, job_id: int) -> list[dict[str, Any]]:
        rows = self._query("SELECT oids_json FROM snmp_query_job WHERE id=%s LIMIT 1", (job_id,))
        if not rows:
            return []
        raw = rows[0].get("oids_json")
        if isinstance(raw, str):
            return json.loads(raw)
        return raw if isinstance(raw, list) else []

    # ── Targets / results ─────────────────────────────────────

    def list_targets(self, public_id: str, *, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        self.ensure_schema()
        jobs = self._query("SELECT id FROM snmp_query_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        safe_limit = max(1, min(int(limit), 1000))
        rows = self._query(
            "SELECT id, mac, modem_ip, cmts, fiber_node, state, results_json, error_text "
            "FROM snmp_query_target WHERE job_id=%s AND id>%s ORDER BY id ASC LIMIT %s",
            (job_id, max(0, int(cursor)), safe_limit + 1),
        )
        has_more = len(rows) > safe_limit
        page = rows[:safe_limit]
        for r in page:
            raw = r.pop("results_json", None)
            if isinstance(raw, str):
                r["results"] = json.loads(raw)
            elif isinstance(raw, dict):
                r["results"] = raw
            else:
                r["results"] = None
        next_cursor = int(page[-1]["id"]) if has_more and page else None
        return {"targets": page, "next_cursor": next_cursor, "has_more": has_more}

    # ── Export ────────────────────────────────────────────────

    def stream_report(self, public_id: str, *, report_format: str) -> Iterator[str]:
        """Stream CSV or JSON report with per-modem SNMP results."""
        self.ensure_schema()
        jobs = self._query("SELECT id, oids_json FROM snmp_query_job WHERE public_id=%s LIMIT 1", (public_id,))
        if not jobs:
            raise KeyError(public_id)
        job_id = int(jobs[0]["id"])
        oids_raw = jobs[0].get("oids_json")
        if isinstance(oids_raw, str):
            oids = json.loads(oids_raw)
        elif isinstance(oids_raw, list):
            oids = oids_raw
        else:
            oids = []

        # Build column names from OID labels
        oid_columns = []
        for entry in oids:
            label = entry.get("label") or entry.get("oid", "unknown")
            oid_columns.append(label)

        normalized_format = str(report_format or "csv").lower()
        base_fields = ["mac", "modem_ip", "cmts", "fiber_node", "state"]
        field_names = base_fields + oid_columns

        def generate() -> Iterator[str]:
            connection = self._connect(autocommit=True)
            try:
                with connection.cursor(pymysql.cursors.SSDictCursor) as cur:
                    cur.execute(
                        "SELECT mac, modem_ip, cmts, fiber_node, state, results_json "
                        "FROM snmp_query_target WHERE job_id=%s ORDER BY id ASC",
                        (job_id,),
                    )
                    if normalized_format == "json":
                        yield '{"results":['
                        first = True
                        for row in cur:
                            if not first:
                                yield ","
                            first = False
                            results = row.pop("results_json", None)
                            if isinstance(results, str):
                                results = json.loads(results)
                            entry = dict(row)
                            if isinstance(results, dict):
                                entry.update(results)
                            yield json.dumps(entry, separators=(",", ":"), default=str)
                        yield "]}"
                    else:
                        buffer = io.StringIO()
                        writer = csv.DictWriter(buffer, fieldnames=field_names, extrasaction='ignore')
                        writer.writeheader()
                        yield buffer.getvalue()
                        buffer.seek(0)
                        buffer.truncate(0)
                        for row in cur:
                            results = row.pop("results_json", None)
                            if isinstance(results, str):
                                results = json.loads(results)
                            entry = {
                                "mac": row.get("mac"),
                                "modem_ip": row.get("modem_ip"),
                                "cmts": row.get("cmts"),
                                "fiber_node": row.get("fiber_node"),
                                "state": row.get("state"),
                            }
                            if isinstance(results, dict):
                                entry.update(results)
                            writer.writerow(entry)
                            yield buffer.getvalue()
                            buffer.seek(0)
                            buffer.truncate(0)
            finally:
                connection.close()

        return generate()

    # ── Options ───────────────────────────────────────────────

    def get_cmts_options(self, affiliate: str = "all") -> list[str]:
        """Return CMTS names from the cached authoritative ISW directory.

        Modem inventory is intentionally not read while the user is selecting a
        CMTS.  The final target plan remains responsible for enforcing the
        authoritative directory membership against live inventory.
        """
        normalized_affiliate = self._normalize_affiliate(affiliate)
        allowed_affiliates = (
            {"fupc", "fziggo"}
            if normalized_affiliate in {"all", "vfz"}
            else {normalized_affiliate}
        )
        return sorted(
            {
                row["hostname"]
                for row in self._get_cmts_directory()
                if row["affiliate"] in allowed_affiliates
                and row["hostname"]
                and "ccap" in row["hostname"]
            }
        )

    def get_verify_cmts_candidates(
        self, *, affiliate: str = "all", cmts: str | None = None, limit: int = 3
    ) -> list[dict[str, str]]:
        """Return bounded randomized CMTS verification candidates from ISW cache."""
        normalized_affiliate = self._normalize_affiliate(affiliate)
        normalized_cmts = str(cmts or "").strip().casefold()
        if len(normalized_cmts) > 128:
            raise ValueError("cmts must be at most 128 characters")
        allowed_affiliates = (
            {"fupc", "fziggo"}
            if normalized_affiliate in {"all", "vfz"}
            else {normalized_affiliate}
        )
        candidates = [
            dict(row)
            for row in self._get_cmts_directory()
            if row["affiliate"] in allowed_affiliates
            and row["hostname"]
            and row["ip_address"]
            and "ccap" in row["hostname"]
            and (not normalized_cmts or row["hostname"] == normalized_cmts)
        ]
        if normalized_cmts and not candidates:
            raise ValueError("Selected CMTS is not available in the authoritative directory")
        unique_candidates = {
            (row["hostname"], row["ip_address"]): row for row in candidates
        }
        ordered = sorted(unique_candidates.values(), key=lambda _: uuid.uuid4().hex)
        return ordered[: max(1, min(int(limit), 3))]

    def get_verify_modem_candidates(
        self,
        *,
        cmts: str,
        modem_vendor: str | None = None,
        modem_type: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, str]]:
        """Return a bounded randomized modem sample without ORDER BY RAND()."""
        normalized_cmts = self._scope_facet({"cmts": cmts}, "cmts", 128)
        vendor = self._scope_facet(
            {"modem_vendor": modem_vendor}, "modem_vendor", 64
        ) if modem_vendor else None
        model = self._scope_facet(
            {"modem_type": modem_type}, "modem_type", 128
        ) if modem_type else None
        requested_limit = max(1, min(int(limit), 3))
        window = max(6, requested_limit * 3)
        token = uuid.uuid4().int & ((1 << 48) - 1)
        compact_mac = f"{token:012x}"
        start_mac = ":".join(compact_mac[index:index + 2] for index in range(0, 12, 2))
        filters = [
            "m.inventory_state<>'retired'",
            "LOWER(TRIM(COALESCE(m.cmts,'')))=%s",
            "m.ip IS NOT NULL",
            "TRIM(m.ip)<>''",
            "m.status IN ('operational','registrationComplete','ipComplete','online')",
        ]
        filter_params: list[str] = [normalized_cmts]
        if vendor:
            filters.append("TRIM(COALESCE(m.vendor,''))=%s")
            filter_params.append(vendor)
        if model:
            filters.append("TRIM(COALESCE(m.model,''))=%s")
            filter_params.append(model)

        def _sample(comparison: str, count: int) -> list[dict[str, Any]]:
            rows = self._query(
                "SELECT m.mac, m.ip, m.cmts, m.cmts_ip FROM modem_inventory_current m "
                "WHERE " + " AND ".join(filters) + f" AND m.mac {comparison} %s "
                "ORDER BY m.mac LIMIT %s",
                tuple(filter_params + [start_mac, count]),
            )
            return rows

        rows = _sample(">=", window)
        if len(rows) < window:
            rows.extend(_sample("<", window - len(rows)))
        unique_rows = {
            str(row.get("ip") or ""): row for row in rows if str(row.get("ip") or "")
        }
        selected = sorted(unique_rows.values(), key=lambda _: uuid.uuid4().hex)
        return [
            {
                "mac": str(row.get("mac") or ""),
                "ip": str(row.get("ip") or ""),
                "cmts": str(row.get("cmts") or normalized_cmts),
                "cmts_ip": str(row.get("cmts_ip") or ""),
            }
            for row in selected[:requested_limit]
        ]

    def get_fiber_node_options(self, cmts: str, affiliate: str = "all") -> list[str]:
        normalized_cmts = self._scope_facet({"cmts": cmts}, "cmts", 128)
        normalized_affiliate = self._normalize_affiliate(affiliate)
        affiliate_filter, affiliate_params = self._affiliate_inventory_predicate(normalized_affiliate)
        online_filter = self._online_inventory_filter()
        rows = self._query(
            f"""
            SELECT DISTINCT TRIM(t.fiber_node) AS fiber_node
            FROM topology_fiber_node_map t
            WHERE t.snapshot_id = (
                SELECT s.id FROM topology_snapshots s
                JOIN topology_fiber_node_map_state ms
                  ON ms.snapshot_id = s.id AND ms.state = 'complete'
                ORDER BY s.snapshot_date DESC, s.id DESC LIMIT 1
            )
            AND t.bare_mac IN (
                SELECT CONVERT(
                    LOWER(REPLACE(REPLACE(REPLACE(m.mac, ':', ''), '-', ''), '.', ''))
                    USING ascii
                ) COLLATE ascii_bin
                FROM modem_inventory_current m
                WHERE m.inventory_state<>'retired'
                  AND LOWER(TRIM(COALESCE(m.cmts,''))) = %s
                {online_filter}
                {affiliate_filter}
            )
            AND t.fiber_node IS NOT NULL AND TRIM(t.fiber_node) <> ''
            ORDER BY TRIM(t.fiber_node)
            """,
            (normalized_cmts.casefold(), *affiliate_params),
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

        oids_raw = row.get("oids_json")
        if isinstance(oids_raw, str):
            oids = json.loads(oids_raw)
        elif isinstance(oids_raw, list):
            oids = oids_raw
        else:
            oids = []

        total = int(row.get("targets_total") or 0)
        succeeded = int(row.get("targets_succeeded") or 0)
        failed = int(row.get("targets_failed") or 0)
        return {
            "public_id": row["public_id"],
            "status": row["status"],
            "scope_type": row.get("scope_type"),
            "oids": oids,
            "targets_total": total,
            "targets_succeeded": succeeded,
            "targets_failed": failed,
            "targets_pending": max(0, total - succeeded - failed),
            "started_at": _dt(row.get("started_at")),
            "finished_at": _dt(row.get("finished_at")),
            "created_at": _dt(row.get("created_at")),
            "requested_by": row.get("requested_by"),
            "error_text": row.get("error_text"),
        }


# Singleton
cm_snmp_query_service = CmSnmpQueryService()
