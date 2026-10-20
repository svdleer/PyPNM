from __future__ import annotations

import os
from typing import Any

import pymysql
import pymysql.cursors


class CmSingleResetService:
    """Resolve one modem for the independent single-reset operation."""

    @staticmethod
    def _db_name() -> str:
        return os.environ.get("DATA_DB_NAME") or os.environ.get("AUTH_DB_NAME") or "pypnm_auth"

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

    def resolve_modem(self, mac: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT mac, ip
                    FROM modem_inventory_current
                    WHERE inventory_state <> 'retired'
                      AND LOWER(mac) = LOWER(%s)
                    LIMIT 1
                    """,
                    (mac.strip(),),
                )
                return cursor.fetchone()
        finally:
            conn.close()


cm_single_reset_service = CmSingleResetService()
