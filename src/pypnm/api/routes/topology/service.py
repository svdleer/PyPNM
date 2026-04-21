from __future__ import annotations

import csv
import gzip
import json
import os
import re
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pypnm.lib.mac_address import MacAddress, MacAddressFormat


# ---------------------------------------------------------------------------
# Background import job state
# ---------------------------------------------------------------------------

class _ImportJob:
    """Tracks progress of a single in-flight or completed import."""

    def __init__(self, snapshot_date: str) -> None:
        self.snapshot_date = snapshot_date
        self.state: str = "queued"          # queued | running | done | error
        self.stage: str = ""                # human-readable current step
        self.pct: int = 0                   # 0-100
        self.stats: dict[str, Any] = {}
        self.error: str | None = None
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.finished_at: str | None = None

    def update(self, stage: str, pct: int) -> None:
        self.stage = stage
        self.pct = min(100, max(0, pct))

    def finish(self, stats: dict[str, Any]) -> None:
        self.state = "done"
        self.stage = "complete"
        self.pct = 100
        self.stats = stats
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def fail(self, error: str) -> None:
        self.state = "error"
        self.stage = "failed"
        self.error = error
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_date": self.snapshot_date,
            "state": self.state,
            "stage": self.stage,
            "pct": self.pct,
            "stats": self.stats,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# One active job per date; replaced when a new import starts for the same date.
_import_jobs: dict[str, _ImportJob] = {}
_import_jobs_lock = threading.Lock()


@dataclass
class DatasetFiles:
    file_date: str
    topology_file: Path | None
    modemlocation_file: Path | None

    @property
    def complete(self) -> bool:
        return self.topology_file is not None and self.modemlocation_file is not None


class TopologyStorage:
    def __init__(self) -> None:
        self._db_lock = threading.Lock()

    def _connect(self):
        try:
            import pymysql
        except Exception as exc:  # pragma: no cover - dependency/runtime issue
            raise RuntimeError("PyMySQL is required for topology MySQL backend") from exc

        host = os.environ.get("TOPOLOGY_DB_HOST") or os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1")
        port = int(os.environ.get("TOPOLOGY_DB_PORT") or os.environ.get("DATA_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306"))
        user = os.environ.get("TOPOLOGY_DB_USER") or os.environ.get("DATA_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm")
        password = os.environ.get("TOPOLOGY_DB_PASSWORD") or os.environ.get("DATA_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm")
        database = os.environ.get("TOPOLOGY_DB_NAME") or os.environ.get("DATA_DB_NAME") or os.environ.get("AUTH_DB_NAME", "pypnm_auth")

        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def init_db(self) -> None:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topology_snapshots (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    snapshot_date CHAR(8) NOT NULL UNIQUE,
                    topology_file VARCHAR(255) NULL,
                    modemlocation_file VARCHAR(255) NULL,
                    topology_signature VARCHAR(64) NULL,
                    modemlocation_signature VARCHAR(64) NULL,
                    imported_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    INDEX idx_topology_snapshot_updated (updated_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topology_nodes (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    snapshot_id BIGINT NOT NULL,
                    node_id VARCHAR(255) NOT NULL,
                    parent_id VARCHAR(255) NULL,
                    fnid VARCHAR(255) NULL,
                    node_type VARCHAR(64) NULL,
                    link_id VARCHAR(64) NULL,
                    lat DOUBLE NULL,
                    lon DOUBLE NULL,
                    description TEXT NULL,
                    metadata_json JSON NULL,
                    UNIQUE KEY uq_nodes_snapshot_node (snapshot_id, node_id),
                    KEY idx_nodes_snapshot_parent (snapshot_id, parent_id),
                    KEY idx_nodes_snapshot_fnid (snapshot_id, fnid),
                    KEY idx_nodes_snapshot_type (snapshot_id, node_type),
                    KEY idx_nodes_snapshot_link (snapshot_id, link_id),
                    CONSTRAINT fk_topology_nodes_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topology_edges (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    snapshot_id BIGINT NOT NULL,
                    from_node_id VARCHAR(255) NOT NULL,
                    to_node_id VARCHAR(255) NOT NULL,
                    KEY idx_edges_snapshot_from (snapshot_id, from_node_id),
                    KEY idx_edges_snapshot_to (snapshot_id, to_node_id),
                    CONSTRAINT fk_topology_edges_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topology_modems (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    snapshot_id BIGINT NOT NULL,
                    mac VARCHAR(32) NULL,
                    fibernode VARCHAR(255) NULL,
                    topology_link_id VARCHAR(64) NULL,
                    lat DOUBLE NULL,
                    lon DOUBLE NULL,
                    address TEXT NULL,
                    address1 VARCHAR(255) NULL,
                    address2 VARCHAR(255) NULL,
                    locality VARCHAR(255) NULL,
                    postalcode VARCHAR(32) NULL,
                    house_number VARCHAR(32) NULL,
                    house_number_extension VARCHAR(64) NULL,
                    customer_id VARCHAR(128) NULL,
                    linked_node_id VARCHAR(255) NULL,
                    linked_node_type VARCHAR(64) NULL,
                    link_match TINYINT(1) NOT NULL DEFAULT 0,
                    KEY idx_modems_snapshot_mac (snapshot_id, mac),
                    KEY idx_modems_snapshot_fn (snapshot_id, fibernode),
                    KEY idx_modems_snapshot_link (snapshot_id, topology_link_id),
                    KEY idx_modems_snapshot_customer (snapshot_id, customer_id),
                    KEY idx_modems_snapshot_postal_house (snapshot_id, postalcode, house_number),
                    KEY idx_modems_snapshot_match (snapshot_id, link_match),
                    CONSTRAINT fk_topology_modems_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS topology_hierarchy (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    snapshot_id BIGINT NOT NULL,
                    path VARCHAR(1024) NULL,
                    hub VARCHAR(255) NULL,
                    cmts VARCHAR(255) NULL,
                    serving_group VARCHAR(255) NULL,
                    segment VARCHAR(255) NULL,
                    direction VARCHAR(10) NULL,
                    node_id VARCHAR(255) NULL,
                    KEY idx_hierarchy_snapshot_node (snapshot_id, node_id),
                    KEY idx_hierarchy_snapshot_cmts (snapshot_id, cmts),
                    KEY idx_hierarchy_snapshot_direction (snapshot_id, direction),
                    CONSTRAINT fk_topology_hierarchy_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            # Idempotently add any missing indexes on existing tables
            _ensure_indexes = [
                ("topology_nodes",     "idx_nodes_snapshot_link",      "snapshot_id, link_id"),
                ("topology_nodes",     "idx_nodes_snapshot_fnid",      "snapshot_id, fnid"),
                ("topology_nodes",     "idx_nodes_snapshot_type",      "snapshot_id, node_type"),
                ("topology_modems",    "idx_modems_snapshot_mac",      "snapshot_id, mac"),
                ("topology_modems",    "idx_modems_snapshot_fn",       "snapshot_id, fibernode"),
                ("topology_modems",    "idx_modems_snapshot_link",     "snapshot_id, topology_link_id"),
                ("topology_modems",    "idx_modems_snapshot_customer", "snapshot_id, customer_id"),
                ("topology_modems",    "idx_modems_snapshot_postal_house", "snapshot_id, postalcode, house_number"),
                ("topology_modems",    "idx_modems_snapshot_match",    "snapshot_id, link_match"),
                ("topology_hierarchy", "idx_hierarchy_snapshot_node",  "snapshot_id, node_id"),
                ("topology_hierarchy", "idx_hierarchy_snapshot_cmts",  "snapshot_id, cmts"),
                ("topology_hierarchy", "idx_hierarchy_snapshot_hub",   "snapshot_id, hub"),
                ("topology_hierarchy", "idx_hierarchy_snapshot_dir",   "snapshot_id, direction"),
            ]
            cur.execute("SELECT TABLE_NAME, INDEX_NAME FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'topology_%'")
            existing_indexes: set[tuple[str, str]] = {
                (row["TABLE_NAME"], row["INDEX_NAME"]) for row in (cur.fetchall() or [])
            }
            for tbl, idx, cols in _ensure_indexes:
                if (tbl, idx) not in existing_indexes:
                    cur.execute(f"ALTER TABLE `{tbl}` ADD INDEX `{idx}` ({cols})")

            # Idempotently add any missing columns on topology_modems (older installs)
            cur.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='topology_modems'"
            )
            modem_cols = {str(row["COLUMN_NAME"]) for row in (cur.fetchall() or []) if row.get("COLUMN_NAME")}
            _ensure_modem_cols = {
                "address1": "VARCHAR(255) NULL",
                "address2": "VARCHAR(255) NULL",
                "locality": "VARCHAR(255) NULL",
                "postalcode": "VARCHAR(32) NULL",
                "house_number": "VARCHAR(32) NULL",
                "house_number_extension": "VARCHAR(64) NULL",
            }
            for col, ddl in _ensure_modem_cols.items():
                if col not in modem_cols:
                    cur.execute(f"ALTER TABLE `topology_modems` ADD COLUMN `{col}` {ddl}")

            # ── CMTS fiber-node / OFDMA-channel cache ───────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cmts_fiber_node_cache (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    cmts_ip VARCHAR(64) NOT NULL,
                    fn_name VARCHAR(128) NOT NULL,
                    mac_domain VARCHAR(128) NULL,
                    ifindex BIGINT NOT NULL,
                    description VARCHAR(512) NULL,
                    modem_count INT NOT NULL DEFAULT 0,
                    channel_modem_count INT NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL,
                    KEY idx_fn_cache_cmts (cmts_ip),
                    KEY idx_fn_cache_cmts_fn (cmts_ip, fn_name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            conn.close()

    # ── CMTS fiber-node cache CRUD ──────────────────────────────────

    def get_cached_fiber_nodes(self, cmts_ip: str, max_age_s: int = 259200) -> dict | None:
        """Return cached channel/list response for a CMTS, or None if stale/missing."""
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT fn_name, mac_domain, ifindex, description, modem_count, "
                "channel_modem_count, updated_at FROM cmts_fiber_node_cache "
                "WHERE cmts_ip=%s ORDER BY fn_name, ifindex",
                (cmts_ip,),
            )
            rows = cur.fetchall() or []
            conn.close()

        if not rows:
            return None

        updated_at = rows[0].get("updated_at")
        if updated_at:
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc)).total_seconds()
            if age > max_age_s:
                return None

        # Reconstruct the channel/list response format
        channels: list[dict] = []
        fn_map: dict[str, dict] = {}
        for r in rows:
            ch = {
                "ifindex": r["ifindex"],
                "description": r["description"] or "",
                "mac_domain": r["fn_name"],
                "suggested_fn": r["fn_name"],
                "modem_count": r["channel_modem_count"],
            }
            channels.append(ch)
            if r["fn_name"] not in fn_map:
                fn_map[r["fn_name"]] = {
                    "name": r["fn_name"],
                    "mac_domain": r["mac_domain"] or r["fn_name"],
                    "channels": [],
                    "modem_count": r["modem_count"],
                }
            fn_map[r["fn_name"]]["channels"].append({
                "ifindex": r["ifindex"],
                "description": r["description"] or "",
                "modem_count": r["channel_modem_count"],
            })

        # Exclude fallback mac-domain entries — only return real FN names
        _fallback_prefixes = ('cable-mac', 'OFDMA-', 'RPD-', 'FN-cable-mac', 'FN-OFDMA-', 'FN-RPD-', 'Cable')
        filtered_fns = [
            f for f in fn_map.values()
            if not f.get('mac_domain', '').startswith(_fallback_prefixes)
            and not f.get('name', '').startswith(_fallback_prefixes)
        ]

        return {
            "success": True,
            "channels": channels,
            "fiber_nodes": sorted(filtered_fns, key=lambda f: f.get("mac_domain", "")),
            "_cached": True,
            "_cache_age_s": round(age) if updated_at else 0,
        }

    def store_fiber_node_cache(self, cmts_ip: str, channels: list[dict], fiber_nodes: list[dict]) -> None:
        """Store channel/list SNMP walk results in MySQL for fast retrieval."""
        # Build a lookup: fn_name -> modem_count (unique modems across all channels)
        fn_modem_count: dict[str, int] = {}
        for fn in fiber_nodes:
            fn_modem_count[fn.get("name", "")] = fn.get("modem_count", 0)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("DELETE FROM cmts_fiber_node_cache WHERE cmts_ip=%s", (cmts_ip,))
            for ch in channels:
                fn_name = ch.get("mac_domain") or ch.get("suggested_fn") or ""
                cur.execute(
                    "INSERT INTO cmts_fiber_node_cache "
                    "(cmts_ip, fn_name, mac_domain, ifindex, description, "
                    "modem_count, channel_modem_count, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        cmts_ip,
                        fn_name,
                        ch.get("mac_domain", ""),
                        ch.get("ifindex", 0),
                        ch.get("description", ""),
                        fn_modem_count.get(fn_name, 0),
                        ch.get("modem_count", 0),
                        now,
                    ),
                )
            conn.close()

    def get_snapshot_meta(self, snapshot_date: str) -> dict[str, Any] | None:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, topology_signature, modemlocation_signature FROM topology_snapshots WHERE snapshot_date=%s",
                (snapshot_date,),
            )
            row = cur.fetchone()
            conn.close()
            return row

    def get_latest_snapshot_date(self) -> str | None:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if not row:
                return None
            return str(row.get("snapshot_date") or "") or None

    def search_modems(
        self,
        snapshot_date: str | None,
        search_type: str,
        value: str,
        house_number: str | None = None,
        limit: int = 200,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            resolved_date = snapshot_date
            if not resolved_date:
                cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
                latest = cur.fetchone() or {}
                resolved_date = str(latest.get("snapshot_date") or "") or None
            if not resolved_date:
                conn.close()
                return None, []

            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (resolved_date,))
            row = cur.fetchone() or {}
            snapshot_id = int(row.get("id") or 0)
            if snapshot_id <= 0:
                conn.close()
                return resolved_date, []

            base_sql = (
                "SELECT m.mac, m.fibernode, m.customer_id, m.topology_link_id, m.address, m.address1, m.address2, m.locality, "
                "m.postalcode, m.house_number, m.house_number_extension, m.linked_node_id, m.linked_node_type, m.link_match, "
                "h.path AS hierarchy_path, h.cmts AS cmts "
                "FROM topology_modems m "
                "LEFT JOIN ("
                "  SELECT snapshot_id, node_id, MIN(path) AS path, MIN(cmts) AS cmts "
                "  FROM topology_hierarchy "
                "  GROUP BY snapshot_id, node_id"
                ") h ON h.snapshot_id=m.snapshot_id AND h.node_id=m.fibernode "
                "WHERE m.snapshot_id=%s "
            )

            st = (search_type or "").strip().lower()
            vv = (value or "").strip()
            hn = (house_number or "").strip()

            if st == "fibernode":
                cur.execute(
                    base_sql + "AND m.fibernode LIKE %s ORDER BY m.mac ASC LIMIT %s",
                    (snapshot_id, f"%{vv}%", int(limit)),
                )
            elif st == "customer_id":
                cur.execute(
                    base_sql + "AND m.customer_id LIKE %s ORDER BY m.mac ASC LIMIT %s",
                    (snapshot_id, f"%{vv}%", int(limit)),
                )
            elif st == "postal_house":
                if not vv or not hn:
                    conn.close()
                    return resolved_date, []
                cur.execute(
                    base_sql + "AND m.postalcode=%s AND m.house_number=%s ORDER BY m.mac ASC LIMIT %s",
                    (snapshot_id, vv, hn, int(limit)),
                )
            else:
                conn.close()
                return resolved_date, []

            rows = cur.fetchall() or []
            conn.close()
            return resolved_date, [dict(r) for r in rows]

    def get_modem_by_mac(
        self,
        snapshot_date: str | None,
        mac_address: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            resolved_date = snapshot_date
            if not resolved_date:
                cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
                latest = cur.fetchone() or {}
                resolved_date = str(latest.get("snapshot_date") or "") or None
            if not resolved_date:
                conn.close()
                return None, None

            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (resolved_date,))
            row = cur.fetchone() or {}
            snapshot_id = int(row.get("id") or 0)
            if snapshot_id <= 0:
                conn.close()
                return resolved_date, None

            mac = (mac_address or "").strip().lower()
            mac_bare = re.sub(r"[^0-9a-f]", "", mac)
            if len(mac_bare) != 12:
                conn.close()
                return resolved_date, None

            sql = (
                "SELECT m.mac, m.fibernode, m.customer_id, m.topology_link_id, m.address, m.address1, m.address2, m.locality, "
                "m.postalcode, m.house_number, m.house_number_extension, m.linked_node_id, m.linked_node_type, m.link_match, "
                "h.path AS hierarchy_path, h.cmts AS cmts "
                "FROM topology_modems m "
                "LEFT JOIN ("
                "  SELECT snapshot_id, node_id, MIN(path) AS path, MIN(cmts) AS cmts "
                "  FROM topology_hierarchy "
                "  GROUP BY snapshot_id, node_id"
                ") h ON h.snapshot_id=m.snapshot_id AND h.node_id=m.fibernode "
                "WHERE m.snapshot_id=%s "
                "AND LOWER(REPLACE(REPLACE(REPLACE(m.mac, ':', ''), '-', ''), '.', ''))=%s "
                "LIMIT 1"
            )
            cur.execute(sql, (snapshot_id, mac_bare))
            modem = cur.fetchone()
            conn.close()
            return resolved_date, (dict(modem) if modem else None)

    def suggest_values(
        self,
        snapshot_date: str | None,
        search_type: str,
        query: str,
        limit: int = 10,
    ) -> tuple[str | None, list[str]]:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            resolved_date = snapshot_date
            if not resolved_date:
                cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
                latest = cur.fetchone() or {}
                resolved_date = str(latest.get("snapshot_date") or "") or None
            if not resolved_date:
                conn.close()
                return None, []

            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (resolved_date,))
            row = cur.fetchone() or {}
            snapshot_id = int(row.get("id") or 0)
            if snapshot_id <= 0:
                conn.close()
                return resolved_date, []

            st = (search_type or "").strip().lower()
            q = (query or "").strip()

            if st == "fibernode":
                cur.execute(
                    "SELECT DISTINCT fibernode FROM topology_modems WHERE snapshot_id=%s AND fibernode LIKE %s ORDER BY fibernode ASC LIMIT %s",
                    (snapshot_id, f"%{q}%", int(limit)),
                )
                values = [str(r.get("fibernode") or "") for r in (cur.fetchall() or []) if r.get("fibernode")]
            elif st == "customer_id":
                cur.execute(
                    "SELECT DISTINCT customer_id FROM topology_modems WHERE snapshot_id=%s AND customer_id LIKE %s ORDER BY customer_id ASC LIMIT %s",
                    (snapshot_id, f"%{q}%", int(limit)),
                )
                values = [str(r.get("customer_id") or "") for r in (cur.fetchall() or []) if r.get("customer_id")]
            elif st == "postal_house":
                cur.execute(
                    "SELECT DISTINCT postalcode, house_number FROM topology_modems "
                    "WHERE snapshot_id=%s AND CONCAT(postalcode, ' ', house_number) LIKE %s "
                    "ORDER BY postalcode ASC, house_number ASC LIMIT %s",
                    (snapshot_id, f"%{q}%", int(limit)),
                )
                values = [
                    f"{str(r.get('postalcode') or '').strip()} {str(r.get('house_number') or '').strip()}".strip()
                    for r in (cur.fetchall() or [])
                    if r.get("postalcode") and r.get("house_number")
                ]
            else:
                values = []

            conn.close()
            # Preserve order while dropping empties/duplicates
            out: list[str] = []
            seen: set[str] = set()
            for v in values:
                if not v or v in seen:
                    continue
                seen.add(v)
                out.append(v)
            return resolved_date, out

    def get_path_by_node(self, snapshot_date: str | None, node_id: str) -> tuple[str | None, str | None]:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            resolved_date = snapshot_date
            if not resolved_date:
                cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
                latest = cur.fetchone() or {}
                resolved_date = str(latest.get("snapshot_date") or "") or None
            if not resolved_date:
                conn.close()
                return None, None

            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (resolved_date,))
            row = cur.fetchone() or {}
            snapshot_id = int(row.get("id") or 0)
            if snapshot_id <= 0:
                conn.close()
                return resolved_date, None

            cur.execute(
                "SELECT MIN(path) AS path FROM topology_hierarchy WHERE snapshot_id=%s AND node_id=%s",
                (snapshot_id, (node_id or "").strip()),
            )
            r = cur.fetchone() or {}
            conn.close()
            return resolved_date, (str(r.get("path") or "") or None)

    def get_node_metadata(
        self,
        snapshot_date: str | None,
        node_ids: list[str],
        direction: str | None = None,
    ) -> tuple[str | None, dict[str, dict[str, Any]]]:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            resolved_date = snapshot_date
            if not resolved_date:
                cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
                latest = cur.fetchone() or {}
                resolved_date = str(latest.get("snapshot_date") or "") or None
            if not resolved_date:
                conn.close()
                return None, {}

            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (resolved_date,))
            row = cur.fetchone() or {}
            snapshot_id = int(row.get("id") or 0)
            if snapshot_id <= 0:
                conn.close()
                return resolved_date, {}

            clean_ids = [str(n or "").strip() for n in node_ids if str(n or "").strip()]
            if not clean_ids:
                conn.close()
                return resolved_date, {}

            placeholders = ",".join(["%s"] * len(clean_ids))
            params: list[Any] = [snapshot_id, *clean_ids]
            sql = (
                "SELECT node_id, MIN(path) AS path, MIN(hub) AS hub, MIN(cmts) AS cmts, "
                "MIN(serving_group) AS serving_group, MIN(segment) AS segment, MIN(direction) AS direction "
                "FROM topology_hierarchy WHERE snapshot_id=%s AND node_id IN (" + placeholders + ")"
            )
            if direction:
                sql += " AND direction=%s"
                params.append(str(direction).strip())
            sql += " GROUP BY node_id"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            conn.close()

            out: dict[str, dict[str, Any]] = {}
            for r in rows:
                node_id = str(r.get("node_id") or "").strip()
                if not node_id:
                    continue
                out[node_id] = {
                    "path": str(r.get("path") or "").strip() or None,
                    "hub": str(r.get("hub") or "").strip() or None,
                    "cmts": str(r.get("cmts") or "").strip() or None,
                    "serving_group": str(r.get("serving_group") or "").strip() or None,
                    "segment": str(r.get("segment") or "").strip() or None,
                    "direction": str(r.get("direction") or "").strip() or None,
                }
            return resolved_date, out

    def get_serving_group_metadata(
        self,
        snapshot_date: str | None,
        serving_groups: list[str],
        direction: str | None = None,
    ) -> tuple[str | None, dict[str, dict[str, Any]]]:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            resolved_date = snapshot_date
            if not resolved_date:
                cur.execute("SELECT snapshot_date FROM topology_snapshots ORDER BY snapshot_date DESC LIMIT 1")
                latest = cur.fetchone() or {}
                resolved_date = str(latest.get("snapshot_date") or "") or None
            if not resolved_date:
                conn.close()
                return None, {}

            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (resolved_date,))
            row = cur.fetchone() or {}
            snapshot_id = int(row.get("id") or 0)
            if snapshot_id <= 0:
                conn.close()
                return resolved_date, {}

            groups = [str(g or "").strip() for g in serving_groups if str(g or "").strip()]
            if not groups:
                conn.close()
                return resolved_date, {}

            placeholders = ",".join(["%s"] * len(groups))
            params: list[Any] = [snapshot_id, *groups]
            sql = (
                "SELECT serving_group, MIN(cmts) AS cmts, MIN(segment) AS segment, MIN(node_id) AS node_id "
                "FROM topology_hierarchy WHERE snapshot_id=%s AND serving_group IN (" + placeholders + ")"
            )
            if direction:
                sql += " AND direction=%s"
                params.append(str(direction).strip())
            sql += " GROUP BY serving_group"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
            conn.close()

            out: dict[str, dict[str, Any]] = {}
            for r in rows:
                sg = str(r.get("serving_group") or "").strip()
                if not sg:
                    continue
                out[sg] = {
                    "cmts": str(r.get("cmts") or "") or None,
                    "segment": str(r.get("segment") or "") or None,
                    "node_id": str(r.get("node_id") or "") or None,
                }
            return resolved_date, out

    def upsert_snapshot_payload(
        self,
        snapshot_date: str,
        topology_file: str | None,
        modemlocation_file: str | None,
        topology_signature: str | None,
        modemlocation_signature: str | None,
        payload: dict[str, Any],
        job: "_ImportJob | None" = None,
    ) -> int:
        def _upd(stage: str, pct: int) -> None:
            if job:
                job.update(stage, pct)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db_lock:
            _upd("connecting to database", 2)
            conn = self._connect()
            cur = conn.cursor()

            _upd("upserting snapshot record", 4)
            cur.execute(
                """
                INSERT INTO topology_snapshots (
                    snapshot_date,
                    topology_file,
                    modemlocation_file,
                    topology_signature,
                    modemlocation_signature,
                    imported_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    topology_file=VALUES(topology_file),
                    modemlocation_file=VALUES(modemlocation_file),
                    topology_signature=VALUES(topology_signature),
                    modemlocation_signature=VALUES(modemlocation_signature),
                    updated_at=VALUES(updated_at)
                """,
                (
                    snapshot_date,
                    topology_file,
                    modemlocation_file,
                    topology_signature,
                    modemlocation_signature,
                    now,
                    now,
                ),
            )
            cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (snapshot_date,))
            snap_row = cur.fetchone() or {}
            snapshot_id_raw = snap_row.get("id")
            if snapshot_id_raw is None:
                conn.close()
                raise RuntimeError(f"Failed to resolve snapshot id for date {snapshot_date}")
            snapshot_id = int(snapshot_id_raw)

            _upd("clearing old data", 6)
            cur.execute("DELETE FROM topology_hierarchy WHERE snapshot_id=%s", (snapshot_id,))
            cur.execute("DELETE FROM topology_edges WHERE snapshot_id=%s", (snapshot_id,))
            cur.execute("DELETE FROM topology_modems WHERE snapshot_id=%s", (snapshot_id,))
            cur.execute("DELETE FROM topology_nodes WHERE snapshot_id=%s", (snapshot_id,))

            # --- nodes (batch 500, sleep between batches) ---
            nodes = payload.get("topology_nodes") or []
            node_sql = (
                "INSERT INTO topology_nodes "
                "(snapshot_id, node_id, parent_id, fnid, node_type, link_id, lat, lon, description, metadata_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            )
            node_rows = [
                (
                    snapshot_id,
                    n.get("id"),
                    n.get("parent_id"),
                    n.get("fnid"),
                    n.get("node_type"),
                    n.get("link_id"),
                    n.get("lat"),
                    n.get("lon"),
                    n.get("description"),
                    json.dumps(n.get("metadata") or {}, ensure_ascii=True),
                )
                for n in nodes
            ]
            _batch = 500
            total_nodes = len(node_rows)
            for i in range(0, total_nodes, _batch):
                cur.executemany(node_sql, node_rows[i : i + _batch])
                pct = 8 + int((i + _batch) / max(total_nodes, 1) * 35)
                _upd(f"inserting nodes ({min(i + _batch, total_nodes)}/{total_nodes})", pct)
                time.sleep(0.02)

            # --- edges (batch 1000) ---
            edges = payload.get("topology_edges") or []
            edge_sql = "INSERT INTO topology_edges (snapshot_id, from_node_id, to_node_id) VALUES (%s, %s, %s)"
            edge_rows = [(snapshot_id, e.get("from"), e.get("to")) for e in edges]
            total_edges = len(edge_rows)
            _batch = 1000
            for i in range(0, total_edges, _batch):
                cur.executemany(edge_sql, edge_rows[i : i + _batch])
                pct = 43 + int((i + _batch) / max(total_edges, 1) * 20)
                _upd(f"inserting edges ({min(i + _batch, total_edges)}/{total_edges})", pct)
                time.sleep(0.02)

            # --- modems (batch 1000) ---
            modems = payload.get("modems") or []
            modem_sql = (
                "INSERT INTO topology_modems "
                "(snapshot_id, mac, fibernode, topology_link_id, lat, lon, address, customer_id, linked_node_id, linked_node_type, link_match) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            )
            modem_rows = [
                (
                    snapshot_id,
                    m.get("mac"),
                    m.get("fibernode"),
                    m.get("topology_link_id"),
                    m.get("lat"),
                    m.get("lon"),
                    m.get("address"),
                    m.get("customer_id"),
                    m.get("linked_node_id"),
                    m.get("linked_node_type"),
                    1 if m.get("link_match") else 0,
                )
                for m in modems
            ]
            total_modems = len(modem_rows)
            _batch = 1000
            for i in range(0, total_modems, _batch):
                cur.executemany(modem_sql, modem_rows[i : i + _batch])
                pct = 63 + int((i + _batch) / max(total_modems, 1) * 20)
                _upd(f"inserting modems ({min(i + _batch, total_modems)}/{total_modems})", pct)
                time.sleep(0.02)

            # --- hierarchy (batch 2000) ---
            hierarchy = payload.get("hierarchy_records") or []
            hierarchy_sql = (
                "INSERT INTO topology_hierarchy "
                "(snapshot_id, path, hub, cmts, serving_group, segment, direction, node_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            )
            hierarchy_rows = [
                (
                    snapshot_id,
                    h.get("PATH", ""),
                    h.get("HUB", ""),
                    h.get("CMTS", ""),
                    h.get("SERVINGGROUP", ""),
                    h.get("SEGMENT", ""),
                    h.get("DIRECTION", ""),
                    h.get("NODE", ""),
                )
                for h in hierarchy
            ]
            total_hier = len(hierarchy_rows)
            _batch = 2000
            for i in range(0, total_hier, _batch):
                cur.executemany(hierarchy_sql, hierarchy_rows[i : i + _batch])
                pct = 83 + int((i + _batch) / max(total_hier, 1) * 12)
                _upd(f"inserting hierarchy ({min(i + _batch, total_hier)}/{total_hier})", pct)
                time.sleep(0.02)

            _upd("finalising", 97)
            conn.close()
            return snapshot_id

    def load_summary_payload(self, snapshot_date: str, sample_limit: int = 200) -> dict[str, Any] | None:
        with self._db_lock:
            conn = self._connect()
            cur = conn.cursor()

            cur.execute(
                "SELECT id, topology_file, modemlocation_file FROM topology_snapshots WHERE snapshot_date=%s",
                (snapshot_date,),
            )
            snap = cur.fetchone()
            if not snap:
                conn.close()
                return None
            snapshot_id_raw = snap.get("id")
            if snapshot_id_raw is None:
                conn.close()
                return None
            snapshot_id = int(snapshot_id_raw)

            # Single-pass counts for nodes using one query instead of 4 separate ones
            cur.execute(
                """
                SELECT
                    COUNT(*)                                       AS nodes_count,
                    COUNT(DISTINCT fnid)                          AS fiber_nodes_count
                FROM topology_nodes WHERE snapshot_id=%s
                """,
                (snapshot_id,),
            )
            _nd = cur.fetchone() or {}
            nodes_count = int(_nd.get("nodes_count") or 0)
            fiber_nodes_count = int(_nd.get("fiber_nodes_count") or 0)

            # Single-pass counts for modems using one query instead of 3 separate ones
            cur.execute(
                """
                SELECT
                    COUNT(*)                                       AS modems_count,
                    SUM(CASE WHEN link_match=1 THEN 1 ELSE 0 END) AS matched_count,
                    SUM(CASE WHEN link_match=0 THEN 1 ELSE 0 END) AS unmatched_count
                FROM topology_modems WHERE snapshot_id=%s
                """,
                (snapshot_id,),
            )
            _md = cur.fetchone() or {}
            modems_count   = int(_md.get("modems_count")   or 0)
            matched_count  = int(_md.get("matched_count")  or 0)
            unmatched_count= int(_md.get("unmatched_count") or 0)

            cur.execute("SELECT COUNT(*) AS c FROM topology_edges WHERE snapshot_id=%s", (snapshot_id,))
            edges_count = int((cur.fetchone() or {}).get("c", 0))

            cur.execute(
                "SELECT node_type, COUNT(*) AS c FROM topology_nodes WHERE snapshot_id=%s GROUP BY node_type ORDER BY node_type ASC",
                (snapshot_id,),
            )
            node_type_counts = {str(r.get("node_type") or "Unknown"): int(r.get("c") or 0) for r in cur.fetchall() or []}
            amp_nodes = sum(v for k, v in node_type_counts.items() if str(k).strip().lower() == "amp")
            tap_nodes = sum(v for k, v in node_type_counts.items() if str(k).strip().lower() == "tap")
            avg_amp_per_node = (amp_nodes / fiber_nodes_count) if fiber_nodes_count else 0.0
            avg_tap_per_node = (tap_nodes / fiber_nodes_count) if fiber_nodes_count else 0.0

            cur.execute(
                "SELECT node_id AS id, parent_id, fnid, node_type, link_id, lat, lon, description, metadata_json "
                "FROM topology_nodes WHERE snapshot_id=%s LIMIT %s",
                (snapshot_id, int(sample_limit)),
            )
            sample_nodes: list[dict[str, Any]] = []
            for row in cur.fetchall() or []:
                md_raw = row.get("metadata_json")
                metadata: dict[str, Any]
                if isinstance(md_raw, str):
                    try:
                        metadata = json.loads(md_raw) if md_raw else {}
                    except Exception:
                        metadata = {}
                else:
                    metadata = md_raw or {}
                sample_nodes.append(
                    {
                        "id": row.get("id") or "",
                        "parent_id": row.get("parent_id") or "",
                        "fnid": row.get("fnid") or "",
                        "node_type": row.get("node_type") or "Unknown",
                        "link_id": row.get("link_id") or "",
                        "lat": row.get("lat"),
                        "lon": row.get("lon"),
                        "description": row.get("description") or "",
                        "metadata": metadata,
                    }
                )

            cur.execute(
                "SELECT mac, fibernode, topology_link_id, lat, lon, address, address1, address2, locality, postalcode, "
                "house_number, house_number_extension, customer_id, linked_node_id, linked_node_type, link_match "
                "FROM topology_modems WHERE snapshot_id=%s "
                "AND link_match=1 "
                "ORDER BY RAND() LIMIT %s",
                (snapshot_id, int(sample_limit)),
            )
            sample_modems = [
                {
                    "mac": TopologyService._normalize_mac_static(str(row.get("mac") or "")),
                    "fibernode": row.get("fibernode") or "",
                    "topology_link_id": row.get("topology_link_id") or "",
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                    "address": row.get("address") or "",
                    "address1": row.get("address1") or "",
                    "address2": row.get("address2") or "",
                    "locality": row.get("locality") or "",
                    "postalcode": row.get("postalcode") or "",
                    "house_number": row.get("house_number") or "",
                    "house_number_extension": row.get("house_number_extension") or "",
                    "customer_id": row.get("customer_id") or "",
                    "linked_node_id": row.get("linked_node_id"),
                    "linked_node_type": row.get("linked_node_type"),
                    "link_match": bool(row.get("link_match")),
                }
                for row in (cur.fetchall() or [])
            ]

            cur.execute("SELECT COUNT(*) AS c FROM topology_hierarchy WHERE snapshot_id=%s", (snapshot_id,))
            hierarchy_count = int((cur.fetchone() or {}).get("c", 0))

            conn.close()

            return {
                "files": {
                    "pair_date": snapshot_date,
                    "topology_file": snap.get("topology_file"),
                    "modemlocation_file": snap.get("modemlocation_file"),
                },
                "topology_nodes": sample_nodes,
                "topology_edges": [],
                "modems": sample_modems,
                "stats": {
                    "topology_nodes": nodes_count,
                    "topology_edges": edges_count,
                    "modems": modems_count,
                    "fiber_nodes": fiber_nodes_count,
                    "amp_nodes": amp_nodes,
                    "tap_nodes": tap_nodes,
                    "avg_amp_per_node": avg_amp_per_node,
                    "avg_tap_per_node": avg_tap_per_node,
                    "matched_by_linkid": matched_count,
                    "potential_fibernode_match": 0,
                    "unmatched_modems": unmatched_count,
                    "hierarchy_records": hierarchy_count,
                    "node_type_counts": node_type_counts,
                },
            }


class TopologyService:
    DATE_PATTERN = re.compile(r"_(\d{8})(?:\D.*)?$")

    def __init__(self) -> None:
        self.storage = TopologyStorage()

    def _volume_dir(self) -> Path:
        return Path(os.environ.get("TOPOLOGY_VOLUME_DIR", "/app/data/topology")).resolve()

    def _extract_date(self, path: Path) -> str | None:
        match = self.DATE_PATTERN.search(path.stem)
        return match.group(1) if match else None

    def _file_signature(self, path: Path | None) -> str | None:
        if path is None or (not path.exists()):
            return None
        st = path.stat()
        return f"{st.st_size}:{int(st.st_mtime)}"

    def _open_csv_text(self, path: Path):
        if path.suffix.lower() == ".gz":
            return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
        return path.open("r", encoding="utf-8", errors="replace", newline="")

    @staticmethod
    def _clean_csv_cell(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    def _clean_csv_row(self, row: dict[object, object]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, value in row.items():
            key_text = self._clean_csv_cell(key)
            if not key_text:
                continue
            cleaned[key_text] = self._clean_csv_cell(value)
        return cleaned

    def _to_float(self, value: str | None) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _normalize_mac(self, mac: str) -> str:
        """
        Normalize MAC address to xx:xx:xx:xx:xx:xx format.
        
        Returns empty string if invalid.
        """
        if not mac:
            return ""
        try:
            return MacAddress(mac).to_mac_format(MacAddressFormat.COLON)
        except Exception:
            # Return original if invalid, don't fail the entire import
            return mac

    @staticmethod
    def _normalize_mac_static(mac: str) -> str:
        if not mac:
            return ""
        try:
            return MacAddress(mac).to_mac_format(MacAddressFormat.COLON)
        except Exception:
            return mac

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        with self._open_csv_text(path) as fh:
            while True:
                pos = fh.tell()
                line = fh.readline()
                if not line:
                    return rows
                if not line.startswith("%%"):
                    fh.seek(pos)
                    break

            reader = csv.DictReader(fh)
            for row in reader:
                if not row:
                    continue
                rows.append(self._clean_csv_row(row))
        return rows

    def _iter_csv_rows(self, path: Path) -> Iterator[dict[str, str]]:
        """Stream CSV rows while skipping optional vendor preamble lines (%%...)."""
        with self._open_csv_text(path) as fh:
            while True:
                pos = fh.tell()
                line = fh.readline()
                if not line:
                    return
                if not line.startswith("%%"):
                    fh.seek(pos)
                    break

            reader = csv.DictReader(fh)
            for row in reader:
                if not row:
                    continue
                yield self._clean_csv_row(row)

    def _parse_modem_address(self, address1_raw: str, address2_raw: str, locality_raw: str = "") -> tuple[str, str, str]:
        """Parse modemlocation ADDRESS1 variants into (street, house_number, house_number_extension)."""
        street = (address1_raw or "").strip()
        house_number = ""
        house_ext = ""

        parts = [p.strip() for p in street.strip(" -").split("-") if p.strip()]
        if len(parts) >= 2:
            street = parts[0]
            house_number = parts[1]
            if len(parts) >= 3:
                house_ext = parts[2]

        if not house_ext:
            alt = (address2_raw or "").strip()
            locality = (locality_raw or "").strip().lower()
            alt_l = alt.lower()
            compact = "".join(ch for ch in alt if ch.isalnum())
            looks_like_ext = (
                # Typical short extension tokens: A, B, bis, 1, 2A, hs
                (len(compact) <= 4 and any(ch.isdigit() for ch in compact))
                or (len(compact) <= 3 and compact.isalpha())
            )
            if house_number and alt and alt_l != locality and looks_like_ext:
                house_ext = alt

        return street, house_number, house_ext

    def _stream_import_payload_to_db(
        self,
        snapshot_date: str,
        topology_file: Path,
        modemlocation_file: Path,
        hierarchy_file: Path | None,
        topology_signature: str | None,
        modemlocation_signature: str | None,
        job: _ImportJob,
    ) -> dict[str, Any]:
        """Import very large topology datasets using streaming batches to stay memory-safe."""
        # Lower process priority in the container to reduce impact on other requests.
        try:
            os.nice(10)
        except Exception:
            pass

        batch_nodes = 300
        batch_edges = 600
        batch_modems = 600
        batch_hier = 1000

        def _upd(stage: str, pct: int) -> None:
            job.update(stage, pct)

        _upd("connecting database", 4)
        conn = self.storage._connect()
        cur = conn.cursor()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            INSERT INTO topology_snapshots (
                snapshot_date, topology_file, modemlocation_file,
                topology_signature, modemlocation_signature,
                imported_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                topology_file=VALUES(topology_file),
                modemlocation_file=VALUES(modemlocation_file),
                topology_signature=VALUES(topology_signature),
                modemlocation_signature=VALUES(modemlocation_signature),
                updated_at=VALUES(updated_at)
            """,
            (
                snapshot_date,
                topology_file.name,
                modemlocation_file.name,
                topology_signature,
                modemlocation_signature,
                now,
                now,
            ),
        )
        cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (snapshot_date,))
        row = cur.fetchone() or {}
        snapshot_id = int(row.get("id") or 0)
        if snapshot_id <= 0:
            conn.close()
            raise RuntimeError(f"Failed to resolve snapshot id for date {snapshot_date}")

        _upd("clearing existing snapshot rows", 7)
        cur.execute("DELETE FROM topology_hierarchy WHERE snapshot_id=%s", (snapshot_id,))
        cur.execute("DELETE FROM topology_edges WHERE snapshot_id=%s", (snapshot_id,))
        cur.execute("DELETE FROM topology_modems WHERE snapshot_id=%s", (snapshot_id,))
        cur.execute("DELETE FROM topology_nodes WHERE snapshot_id=%s", (snapshot_id,))

        node_sql = (
            "INSERT IGNORE INTO topology_nodes "
            "(snapshot_id, node_id, parent_id, fnid, node_type, link_id, lat, lon, description, metadata_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        edge_sql = "INSERT INTO topology_edges (snapshot_id, from_node_id, to_node_id) VALUES (%s, %s, %s)"

        nodes_buf: list[tuple[Any, ...]] = []
        edges_buf: list[tuple[Any, ...]] = []
        node_rows = 0

        _upd("streaming topology rows", 10)
        for r in self._iter_csv_rows(topology_file):
            node_id = r.get("ID", "")
            parent_id = r.get("PARENTID", "")
            fnid = r.get("FNID", "")
            node_type = r.get("NODETYPE", "Unknown") or "Unknown"
            link_id = r.get("LINKID", "")
            desc = r.get("DESCRIPTION", "")

            nodes_buf.append(
                (
                    snapshot_id,
                    node_id,
                    parent_id,
                    fnid,
                    node_type,
                    link_id,
                    self._to_float(r.get("LAT")),
                    self._to_float(r.get("LON")),
                    desc,
                    json.dumps(self._desc_to_map(desc), ensure_ascii=True),
                )
            )
            if parent_id:
                edges_buf.append((snapshot_id, parent_id, node_id))
            node_rows += 1

            if len(nodes_buf) >= batch_nodes:
                cur.executemany(node_sql, nodes_buf)
                nodes_buf.clear()
                if edges_buf:
                    cur.executemany(edge_sql, edges_buf)
                    edges_buf.clear()
                if node_rows % 3000 == 0:
                    _upd(f"streaming topology rows ({node_rows})", min(55, 10 + node_rows // 200000))
                time.sleep(0.01)

        if nodes_buf:
            cur.executemany(node_sql, nodes_buf)
        if edges_buf:
            cur.executemany(edge_sql, edges_buf)

        # Modems: insert raw first; link matching is done in SQL for memory safety.
        modem_sql = (
            "INSERT INTO topology_modems "
            "(snapshot_id, mac, fibernode, topology_link_id, lat, lon, address, address1, address2, locality, postalcode, "
            "house_number, house_number_extension, customer_id, linked_node_id, linked_node_type, link_match) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, 0)"
        )
        modems_buf: list[tuple[Any, ...]] = []
        modem_rows = 0
        _upd("streaming modem rows", 58)
        for r in self._iter_csv_rows(modemlocation_file):
            address1_raw = r.get("ADDRESS1", "")
            address2_raw = r.get("ADDRESS2", "")
            locality = r.get("LOCALITY", "")
            postalcode = r.get("POSTALCODE", "")
            address1, house_number, house_ext = self._parse_modem_address(address1_raw, address2_raw, locality)
            address = " ".join(
                p for p in [address1_raw, address2_raw, postalcode, locality] if p
            ).strip()
            modems_buf.append(
                (
                    snapshot_id,
                    self._normalize_mac(r.get("MACADDRESS", "")),
                    r.get("FIBERNODE", ""),
                    r.get("TOPOLOGYLINKID", ""),
                    self._to_float(r.get("LAT")),
                    self._to_float(r.get("LON")),
                    address,
                    address1,
                    address2_raw,
                    locality,
                    postalcode,
                    house_number,
                    house_ext,
                    r.get("CUSTOMERID", ""),
                )
            )
            modem_rows += 1
            if len(modems_buf) >= batch_modems:
                cur.executemany(modem_sql, modems_buf)
                modems_buf.clear()
                if modem_rows % 3000 == 0:
                    _upd(f"streaming modem rows ({modem_rows})", min(80, 58 + modem_rows // 200000))
                time.sleep(0.01)
        if modems_buf:
            cur.executemany(modem_sql, modems_buf)

        # Hierarchy (optional)
        hier_rows = 0
        if hierarchy_file and hierarchy_file.exists():
            hierarchy_sql = (
                "INSERT INTO topology_hierarchy "
                "(snapshot_id, path, hub, cmts, serving_group, segment, direction, node_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            )
            hier_buf: list[tuple[Any, ...]] = []
            _upd("streaming hierarchy rows", 82)
            for r in self._iter_csv_rows(hierarchy_file):
                hier_buf.append(
                    (
                        snapshot_id,
                        r.get("PATH", ""),
                        r.get("HUB", ""),
                        r.get("CMTS", ""),
                        r.get("SERVINGGROUP", ""),
                        r.get("SEGMENT", ""),
                        r.get("DIRECTION", ""),
                        r.get("NODE", ""),
                    )
                )
                hier_rows += 1
                if len(hier_buf) >= batch_hier:
                    cur.executemany(hierarchy_sql, hier_buf)
                    hier_buf.clear()
                    if hier_rows % 5000 == 0:
                        _upd(f"streaming hierarchy rows ({hier_rows})", min(90, 82 + hier_rows // 10000))
                    time.sleep(0.01)
            if hier_buf:
                cur.executemany(hierarchy_sql, hier_buf)

        # DB-side link matching avoids massive in-memory maps.
        _upd("matching modem links in database", 92)
        cur.execute(
            """
            UPDATE topology_modems m
            JOIN topology_nodes n
              ON n.snapshot_id = m.snapshot_id
             AND n.link_id = m.topology_link_id
            SET m.linked_node_id = n.node_id,
                m.linked_node_type = n.node_type,
                m.link_match = 1
            WHERE m.snapshot_id = %s
              AND COALESCE(m.topology_link_id, '') <> ''
            """,
            (snapshot_id,),
        )

        _upd("finalising", 97)
        conn.close()

        stats_payload = self.storage.load_summary_payload(snapshot_date=snapshot_date, sample_limit=1) or {}
        stats = stats_payload.get("stats") or {}
        if hier_rows and not stats.get("hierarchy_records"):
            stats["hierarchy_records"] = hier_rows
        return stats

    def _desc_to_map(self, desc: str) -> dict[str, str]:
        out: dict[str, str] = {}
        if not desc:
            return out
        for part in desc.split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            out[key.strip()] = value.strip()
        return out

    def _parse_hierarchy(self, hierarchy_file: Path) -> list[dict[str, str]]:
        """Parse NL_hierarchy_YYYYMMDD CSV and return list of hierarchy records."""
        rows: list[dict[str, str]] = []
        if not hierarchy_file.exists():
            return rows
        
        with self._open_csv_text(hierarchy_file) as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if not row:
                    continue
                rows.append(self._clean_csv_row(row))
        return rows

    def _parse_payload(self, topology_file: Path, modemlocation_file: Path, hierarchy_file: Path | None = None) -> dict[str, Any]:
        topo_rows = self._read_csv(topology_file)
        modem_rows = self._read_csv(modemlocation_file)

        node_type_counts: dict[str, int] = {}
        by_linkid: dict[str, dict[str, Any]] = {}
        fnid_set: set[str] = set()

        edges: list[dict[str, str]] = []
        topo_nodes: list[dict[str, Any]] = []
        for row in topo_rows:
            node_id = row.get("ID", "")
            parent_id = row.get("PARENTID", "")
            fnid = row.get("FNID", "")
            node_type = row.get("NODETYPE", "Unknown") or "Unknown"
            link_id = row.get("LINKID", "")

            node = {
                "id": node_id,
                "parent_id": parent_id,
                "fnid": fnid,
                "node_type": node_type,
                "link_id": link_id,
                "lat": self._to_float(row.get("LAT")),
                "lon": self._to_float(row.get("LON")),
                "description": row.get("DESCRIPTION", ""),
                "metadata": self._desc_to_map(row.get("DESCRIPTION", "")),
            }
            topo_nodes.append(node)
            if link_id:
                by_linkid[link_id] = node
            if fnid:
                fnid_set.add(fnid)
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1
            if parent_id:
                edges.append({"from": parent_id, "to": node_id})

        modems: list[dict[str, Any]] = []
        matched_by_linkid = 0
        potential_fibernode_match = 0
        for row in modem_rows:
            link_id = row.get("TOPOLOGYLINKID", "")
            fibernode = row.get("FIBERNODE", "")
            linked_node = by_linkid.get(link_id)
            if linked_node:
                matched_by_linkid += 1
            elif fibernode and fibernode in fnid_set:
                potential_fibernode_match += 1

            address1_raw = row.get("ADDRESS1", "")
            address2_raw = row.get("ADDRESS2", "")
            locality = row.get("LOCALITY", "")
            postalcode = row.get("POSTALCODE", "")
            address1, house_number, house_ext = self._parse_modem_address(address1_raw, address2_raw, locality)

            modems.append(
                {
                    "mac": self._normalize_mac(row.get("MACADDRESS", "")),
                    "fibernode": fibernode,
                    "topology_link_id": link_id,
                    "lat": self._to_float(row.get("LAT")),
                    "lon": self._to_float(row.get("LON")),
                    "address": " ".join(
                        p
                        for p in [
                            address1_raw,
                            address2_raw,
                            postalcode,
                            locality,
                        ]
                        if p
                    ).strip(),
                    "address1": address1,
                    "address2": address2_raw,
                    "locality": locality,
                    "postalcode": postalcode,
                    "house_number": house_number,
                    "house_number_extension": house_ext,
                    "customer_id": row.get("CUSTOMERID", ""),
                    "linked_node_id": linked_node.get("id") if linked_node else None,
                    "linked_node_type": linked_node.get("node_type") if linked_node else None,
                    "link_match": bool(linked_node),
                }
            )

        hierarchy_records: list[dict[str, str]] = []
        if hierarchy_file:
            hierarchy_records = self._parse_hierarchy(hierarchy_file)

        return {
            "topology_nodes": topo_nodes,
            "topology_edges": edges,
            "modems": modems,
            "hierarchy_records": hierarchy_records,
            "stats": {
                "topology_nodes": len(topo_nodes),
                "topology_edges": len(edges),
                "modems": len(modems),
                "fiber_nodes": len(fnid_set),
                "matched_by_linkid": matched_by_linkid,
                "potential_fibernode_match": potential_fibernode_match,
                "unmatched_modems": max(0, len(modems) - matched_by_linkid),
                "node_type_counts": dict(sorted(node_type_counts.items(), key=lambda kv: kv[0].lower())),
                "hierarchy_records": len(hierarchy_records),
            },
        }

    def scan_inventory(self) -> dict[str, Any]:
        volume_dir = self._volume_dir()
        if not volume_dir.exists() or not volume_dir.is_dir():
            return {
                "volume_dir": str(volume_dir),
                "datasets": [],
                "available_pair_dates": [],
                "warnings": ["topology volume directory not found"],
                "image_files": [],
            }

        topo_by_date: dict[str, Path] = {}
        modem_by_date: dict[str, Path] = {}
        hierarchy_by_date: dict[str, Path] = {}
        image_files: list[str] = []

        for path in sorted(volume_dir.iterdir()):
            if not path.is_file():
                continue
            name = path.name
            lname = name.lower()
            if lname.endswith((".png", ".jpg", ".jpeg", ".webp")):
                image_files.append(name)
            if name.startswith("NL_topology_"):
                file_date = self._extract_date(path)
                if file_date:
                    topo_by_date[file_date] = path
            elif name.startswith("NL_modemlocation_"):
                file_date = self._extract_date(path)
                if file_date:
                    modem_by_date[file_date] = path
            elif name.startswith("NL_hierarchy_"):
                file_date = self._extract_date(path)
                if file_date:
                    hierarchy_by_date[file_date] = path

        all_dates = sorted(set(topo_by_date.keys()) | set(modem_by_date.keys()))
        datasets: list[dict[str, Any]] = []
        warnings: list[str] = []
        for file_date in all_dates:
            topo = topo_by_date.get(file_date)
            modem = modem_by_date.get(file_date)
            hierarchy = hierarchy_by_date.get(file_date)
            if topo and not modem:
                warnings.append(f"unpaired topology file date: {file_date}")
            if modem and not topo:
                warnings.append(f"unpaired modemlocation file date: {file_date}")
            datasets.append(
                {
                    "file_date": file_date,
                    "complete": bool(topo and modem),
                    "topology_file": topo.name if topo else None,
                    "modemlocation_file": modem.name if modem else None,
                    "hierarchy_file": hierarchy.name if hierarchy else None,
                    "topology_mtime": topo.stat().st_mtime if topo else None,
                    "modemlocation_mtime": modem.stat().st_mtime if modem else None,
                    "hierarchy_mtime": hierarchy.stat().st_mtime if hierarchy else None,
                }
            )

        datasets.sort(key=lambda item: str(item.get("file_date") or ""), reverse=True)
        available_pair_dates = sorted(
            [str(item["file_date"]) for item in datasets if item.get("complete")],
            reverse=False,
        )

        return {
            "volume_dir": str(volume_dir),
            "datasets": datasets,
            "available_pair_dates": available_pair_dates,
            "warnings": warnings,
            "image_files": sorted(image_files),
            "topo_by_date": topo_by_date,
            "modem_by_date": modem_by_date,
            "hierarchy_by_date": hierarchy_by_date,
        }

    def import_dataset(self, selected_date: str | None = None, force: bool = False) -> dict[str, Any]:
        inventory = self.scan_inventory()
        topo_by_date: dict[str, Path] = inventory.get("topo_by_date") or {}
        modem_by_date: dict[str, Path] = inventory.get("modem_by_date") or {}
        hierarchy_by_date: dict[str, Path] = inventory.get("hierarchy_by_date") or {}

        pair_dates = sorted(set(topo_by_date.keys()) & set(modem_by_date.keys()))
        if not pair_dates:
            raise RuntimeError("No complete topology dataset found in volume")

        snapshot_date = selected_date or pair_dates[-1]
        if snapshot_date not in pair_dates:
            raise RuntimeError(f"Selected date {snapshot_date} is not a complete dataset")

        topology_file = topo_by_date[snapshot_date]
        modemlocation_file = modem_by_date[snapshot_date]
        hierarchy_file = hierarchy_by_date.get(snapshot_date)
        topo_sig = self._file_signature(topology_file)
        modem_sig = self._file_signature(modemlocation_file)

        self.storage.init_db()
        existing = self.storage.get_snapshot_meta(snapshot_date=snapshot_date)
        if (
            existing
            and not force
            and str(existing.get("topology_signature") or "") == str(topo_sig or "")
            and str(existing.get("modemlocation_signature") or "") == str(modem_sig or "")
        ):
            payload = self.storage.load_summary_payload(snapshot_date=snapshot_date, sample_limit=200) or {}
            return {
                "snapshot_date": snapshot_date,
                "imported": False,
                "reason": "unchanged",
                "stats": payload.get("stats") or {},
            }

        parsed_payload = self._parse_payload(topology_file=topology_file, modemlocation_file=modemlocation_file, hierarchy_file=hierarchy_file)
        self.storage.upsert_snapshot_payload(
            snapshot_date=snapshot_date,
            topology_file=topology_file.name,
            modemlocation_file=modemlocation_file.name,
            topology_signature=topo_sig,
            modemlocation_signature=modem_sig,
            payload=parsed_payload,
        )
        return {
            "snapshot_date": snapshot_date,
            "imported": True,
            "reason": "imported",
            "stats": parsed_payload.get("stats") or {},
        }

    def start_import_background(self, selected_date: str | None = None, force: bool = False) -> _ImportJob:
        """Kick off a background import and return an _ImportJob for status tracking."""
        inventory = self.scan_inventory()
        topo_by_date: dict[str, Path] = inventory.get("topo_by_date") or {}
        modem_by_date: dict[str, Path] = inventory.get("modem_by_date") or {}
        hierarchy_by_date: dict[str, Path] = inventory.get("hierarchy_by_date") or {}

        pair_dates = sorted(set(topo_by_date.keys()) & set(modem_by_date.keys()))
        if not pair_dates:
            raise RuntimeError("No complete topology dataset found in volume")

        snapshot_date = selected_date or pair_dates[-1]
        if snapshot_date not in pair_dates:
            raise RuntimeError(f"Selected date {snapshot_date} is not a complete dataset")

        # Check for already-running job
        with _import_jobs_lock:
            existing_job = _import_jobs.get(snapshot_date)
            if existing_job and existing_job.state in ("queued", "running") and not force:
                return existing_job
            job = _ImportJob(snapshot_date)
            _import_jobs[snapshot_date] = job

        topology_file = topo_by_date[snapshot_date]
        modemlocation_file = modem_by_date[snapshot_date]
        hierarchy_file = hierarchy_by_date.get(snapshot_date)
        topo_sig = self._file_signature(topology_file)
        modem_sig = self._file_signature(modemlocation_file)

        def _worker() -> None:
            try:
                job.state = "running"
                job.update("initialising database", 1)
                self.storage.init_db()

                existing = self.storage.get_snapshot_meta(snapshot_date=snapshot_date)
                if (
                    existing
                    and not force
                    and str(existing.get("topology_signature") or "") == str(topo_sig or "")
                    and str(existing.get("modemlocation_signature") or "") == str(modem_sig or "")
                ):
                    payload = self.storage.load_summary_payload(snapshot_date=snapshot_date, sample_limit=0) or {}
                    job.finish(payload.get("stats") or {})
                    return

                stats = self._stream_import_payload_to_db(
                    snapshot_date=snapshot_date,
                    topology_file=topology_file,
                    modemlocation_file=modemlocation_file,
                    hierarchy_file=hierarchy_file,
                    topology_signature=topo_sig,
                    modemlocation_signature=modem_sig,
                    job=job,
                )
                job.finish(stats)
            except Exception as exc:
                job.fail(str(exc))

        t = threading.Thread(target=_worker, daemon=True, name=f"topo-import-{snapshot_date}")
        t.start()
        return job

    @staticmethod
    def get_import_job(snapshot_date: str) -> "_ImportJob | None":
        with _import_jobs_lock:
            return _import_jobs.get(snapshot_date)

    def search_modems(
        self,
        selected_date: str | None,
        search_type: str,
        value: str,
        house_number: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.storage.init_db()
        snapshot_date, rows = self.storage.search_modems(
            snapshot_date=selected_date,
            search_type=search_type,
            value=value,
            house_number=house_number,
            limit=limit,
        )
        for row in rows:
            if isinstance(row, dict) and "mac" in row:
                row["mac"] = self._normalize_mac(row.get("mac") or "")
        return {
            "snapshot_date": snapshot_date,
            "search_type": search_type,
            "count": len(rows),
            "modems": rows,
        }

    def suggest_values(
        self,
        selected_date: str | None,
        search_type: str,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        self.storage.init_db()
        snapshot_date, suggestions = self.storage.suggest_values(
            snapshot_date=selected_date,
            search_type=search_type,
            query=query,
            limit=limit,
        )
        return {
            "snapshot_date": snapshot_date,
            "search_type": search_type,
            "suggestions": suggestions,
        }

    def get_path_by_node(self, selected_date: str | None, node_id: str) -> dict[str, Any]:
        self.storage.init_db()
        snapshot_date, path = self.storage.get_path_by_node(snapshot_date=selected_date, node_id=node_id)
        return {
            "snapshot_date": snapshot_date,
            "node_id": node_id,
            "path": path,
        }

    def get_modem_by_mac(self, selected_date: str | None, mac_address: str) -> dict[str, Any]:
        self.storage.init_db()
        snapshot_date, modem = self.storage.get_modem_by_mac(
            snapshot_date=selected_date,
            mac_address=mac_address,
        )
        if modem and isinstance(modem, dict) and "mac" in modem:
            modem["mac"] = self._normalize_mac(modem.get("mac") or "")
        return {
            "snapshot_date": snapshot_date,
            "mac_address": mac_address,
            "modem": modem,
        }

    def get_node_metadata(
        self,
        selected_date: str | None,
        node_ids: list[str],
        direction: str | None = None,
    ) -> dict[str, Any]:
        self.storage.init_db()
        snapshot_date, node_meta = self.storage.get_node_metadata(
            snapshot_date=selected_date,
            node_ids=node_ids,
            direction=direction,
        )
        return {
            "snapshot_date": snapshot_date,
            "count": len(node_meta),
            "node_meta": node_meta,
        }

    def get_serving_group_metadata(
        self,
        selected_date: str | None,
        serving_groups: list[str],
        direction: str | None = None,
    ) -> dict[str, Any]:
        self.storage.init_db()
        snapshot_date, sg_meta = self.storage.get_serving_group_metadata(
            snapshot_date=selected_date,
            serving_groups=serving_groups,
            direction=direction,
        )
        return {
            "snapshot_date": snapshot_date,
            "count": len(sg_meta),
            "serving_group_meta": sg_meta,
        }

    def get_summary(
        self,
        selected_date: str | None = None,
        sample_limit: int = 200,
        auto_import: bool = False,
    ) -> dict[str, Any]:
        inventory = self.scan_inventory()
        warnings = list(inventory.get("warnings") or [])

        self.storage.init_db()

        if auto_import:
            try:
                self.import_dataset(selected_date=selected_date, force=False)
            except Exception as exc:
                warnings.append(f"topology import skipped: {exc}")

        snapshot_date = selected_date or self.storage.get_latest_snapshot_date()
        if not snapshot_date:
            return {
                "files": {
                    "pair_date": None,
                    "topology_file": None,
                    "modemlocation_file": None,
                    "hierarchy_file": None,
                    "available_pair_dates": inventory.get("available_pair_dates") or [],
                    "warnings": warnings,
                    "image_files": inventory.get("image_files") or [],
                    "volume_dir": inventory.get("volume_dir"),
                    "storage_backend": "mysql",
                },
                "topology_nodes": [],
                "topology_edges": [],
                "modems": [],
                "stats": {
                    "topology_nodes": 0,
                    "topology_edges": 0,
                    "modems": 0,
                    "fiber_nodes": 0,
                    "matched_by_linkid": 0,
                    "potential_fibernode_match": 0,
                    "unmatched_modems": 0,
                    "node_type_counts": {},
                },
            }

        payload = self.storage.load_summary_payload(snapshot_date=snapshot_date, sample_limit=sample_limit)
        if payload is None:
            return {
                "files": {
                    "pair_date": snapshot_date,
                    "topology_file": None,
                    "modemlocation_file": None,
                    "hierarchy_file": None,
                    "available_pair_dates": inventory.get("available_pair_dates") or [],
                    "warnings": warnings + ["snapshot not found in mysql"],
                    "image_files": inventory.get("image_files") or [],
                    "volume_dir": inventory.get("volume_dir"),
                    "storage_backend": "mysql",
                },
                "topology_nodes": [],
                "topology_edges": [],
                "modems": [],
                "stats": {
                    "topology_nodes": 0,
                    "topology_edges": 0,
                    "modems": 0,
                    "fiber_nodes": 0,
                    "matched_by_linkid": 0,
                    "potential_fibernode_match": 0,
                    "unmatched_modems": 0,
                    "node_type_counts": {},
                },
            }

        files = payload.get("files") or {}
        files["pair_date"] = snapshot_date
        hierarchy_by_date: dict[str, Path] = inventory.get("hierarchy_by_date") or {}
        hierarchy_path = hierarchy_by_date.get(snapshot_date)
        files["hierarchy_file"] = hierarchy_path.name if hierarchy_path else None
        files["available_pair_dates"] = inventory.get("available_pair_dates") or []
        files["warnings"] = warnings
        files["image_files"] = inventory.get("image_files") or []
        files["volume_dir"] = inventory.get("volume_dir")
        files["storage_backend"] = "mysql"

        payload["files"] = files
        return payload

    def resolve_asset_path(self, filename: str) -> Path:
        safe_name = os.path.basename(filename)
        if not safe_name:
            raise RuntimeError("Invalid filename")
        full_path = self._volume_dir() / safe_name
        if not full_path.exists() or (not full_path.is_file()):
            raise RuntimeError("Asset not found")
        return full_path


topology_service = TopologyService()
