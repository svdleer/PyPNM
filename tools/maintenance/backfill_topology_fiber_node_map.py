#!/usr/bin/env python3
"""Explicitly build indexed topology MAC-to-fiber-node maps for existing snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pymysql

from pypnm.api.routes.topology.service import normalize_bare_mac, topology_service


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument(
        "--all-snapshots",
        action="store_true",
        help="Backfill every snapshot instead of only the latest snapshot",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild maps already marked complete",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_size = max(100, min(int(args.batch_size), 20000))
    storage = topology_service.storage
    storage.init_db()
    read_connection = storage._connect()
    write_connection = storage._connect()
    lock_acquired = False
    try:
        with write_connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK('pypnm_topology_fiber_map_backfill', 0) AS acquired")
            lock_acquired = int((cursor.fetchone() or {}).get("acquired") or 0) == 1
        if not lock_acquired:
            raise RuntimeError("another topology fiber-node map backfill is running")

        with write_connection.cursor() as cursor:
            limit_sql = "" if args.all_snapshots else " LIMIT 1"
            cursor.execute(
                "SELECT id, snapshot_date FROM topology_snapshots "
                "ORDER BY snapshot_date DESC" + limit_sql
            )
            snapshots = list(cursor.fetchall() or [])

        for snapshot in snapshots:
            snapshot_id = int(snapshot["id"])
            snapshot_date = str(snapshot.get("snapshot_date") or snapshot_id)
            with write_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT state FROM topology_fiber_node_map_state "
                    "WHERE snapshot_id=%s LIMIT 1",
                    (snapshot_id,),
                )
                state = cursor.fetchone() or {}
                if str(state.get("state") or "") == "complete" and not args.force:
                    print(f"{snapshot_date}: map already complete; skipped")
                    continue
                storage.begin_fiber_node_map(cursor, snapshot_id, now())

            processed = 0
            mapped = 0
            source_cursor = read_connection.cursor(pymysql.cursors.SSDictCursor)
            try:
                source_cursor.execute(
                    "SELECT mac, fibernode FROM topology_modems "
                    "FORCE INDEX (idx_modems_snapshot_mac) "
                    "WHERE snapshot_id=%s ORDER BY mac",
                    (snapshot_id,),
                )
                while True:
                    rows = source_cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    map_rows: list[tuple[int, str, str]] = []
                    for row in rows:
                        bare_mac = normalize_bare_mac(row.get("mac"))
                        fiber_node = str(row.get("fibernode") or "").strip()[:128]
                        if bare_mac and fiber_node:
                            map_rows.append((snapshot_id, bare_mac, fiber_node))
                    with write_connection.cursor() as cursor:
                        storage.insert_fiber_node_map_rows(cursor, map_rows)
                    processed += len(rows)
                    mapped += len(map_rows)
                    if processed % (batch_size * 20) == 0:
                        print(f"{snapshot_date}: processed {processed:,} topology rows")
            finally:
                source_cursor.close()

            with write_connection.cursor() as cursor:
                storage.publish_fiber_node_map(cursor, snapshot_id, now())
            print(
                f"{snapshot_date}: complete; processed {processed:,}, "
                f"accepted {mapped:,} mappings"
            )
        return 0
    finally:
        if lock_acquired:
            try:
                with write_connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK('pypnm_topology_fiber_map_backfill')")
            except Exception:
                pass
        read_connection.close()
        write_connection.close()


if __name__ == "__main__":
    raise SystemExit(main())