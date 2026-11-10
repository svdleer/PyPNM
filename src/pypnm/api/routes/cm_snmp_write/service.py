from __future__ import annotations

import json
import os
import threading
import uuid
import hmac
import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Any

import pymysql
import pymysql.cursors

from pypnm.api.routes.cm_reset.service import cm_reset_service

_PASSWORD = "kensentme"
_MAX_CONCURRENCY = 10


class CmWriteService:
    def __init__(self) -> None:
        self._db_lock = threading.Lock()
        self._schema_ensured = False

    @staticmethod
    def _db_name() -> str:
        return os.environ.get("DATA_DB_NAME") or os.environ.get("AUTH_DB_NAME") or "pypnm_auth"

    def _connect(self, autocommit: bool = True):
        return pymysql.connect(
            host=os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DATA_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306")),
            user=os.environ.get("DATA_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm"),
            password=os.environ.get("DATA_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm"),
            database=self._db_name(), autocommit=autocommit,
            cursorclass=pymysql.cursors.DictCursor, connect_timeout=10,
            read_timeout=60, write_timeout=30,
        )

    def _query(self, sql: str, params=()):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def password_valid(value: str) -> bool:
        return isinstance(value, str) and hmac.compare_digest(value.strip().lower(), _PASSWORD)

    def ensure_schema(self) -> None:
        if self._schema_ensured:
            return
        ddls = [
            """CREATE TABLE IF NOT EXISTS cm_snmp_write_job (
                id BIGINT PRIMARY KEY AUTO_INCREMENT, public_id CHAR(36) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'planned', scope_type VARCHAR(24) NOT NULL,
                scope_json JSON NOT NULL, operations_json JSON NOT NULL,
                scheduled_start DATETIME NULL, requested_by VARCHAR(64) NULL,
                idempotency_key VARCHAR(128) NULL, targets_total INT NOT NULL DEFAULT 0,
                operations_total INT NOT NULL DEFAULT 0, operations_succeeded INT NOT NULL DEFAULT 0,
                operations_failed INT NOT NULL DEFAULT 0, error_text TEXT NULL,
                cancel_requested_at DATETIME NULL, started_at DATETIME NULL, finished_at DATETIME NULL,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                UNIQUE KEY uk_cm_write_public_id(public_id),
                INDEX idx_cm_write_status_due(status, scheduled_start)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS cm_snmp_write_target (
                id BIGINT PRIMARY KEY AUTO_INCREMENT, job_id BIGINT NOT NULL, mac VARCHAR(20) NOT NULL,
                modem_ip VARCHAR(45) NULL, cmts VARCHAR(128) NULL, fiber_node VARCHAR(128) NULL,
                created_at DATETIME NOT NULL, CONSTRAINT fk_cm_write_target_job FOREIGN KEY(job_id)
                REFERENCES cm_snmp_write_job(id) ON DELETE CASCADE, INDEX idx_cm_write_target_job(job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS cm_snmp_write_result (
                id BIGINT PRIMARY KEY AUTO_INCREMENT, job_id BIGINT NOT NULL, target_id BIGINT NOT NULL,
                operation_index INT NOT NULL, oid VARCHAR(256) NOT NULL, value_type VARCHAR(2) NOT NULL,
                value_json JSON NULL, delay_seconds DECIMAL(8,3) NOT NULL DEFAULT 0,
                state VARCHAR(24) NOT NULL DEFAULT 'planned', error_text TEXT NULL,
                started_at DATETIME NULL, finished_at DATETIME NULL, duration_ms INT NULL,
                agent_id VARCHAR(128) NULL, task_id VARCHAR(64) NULL,
                CONSTRAINT fk_cm_write_result_job FOREIGN KEY(job_id) REFERENCES cm_snmp_write_job(id) ON DELETE CASCADE,
                CONSTRAINT fk_cm_write_result_target FOREIGN KEY(target_id) REFERENCES cm_snmp_write_target(id) ON DELETE CASCADE,
                UNIQUE KEY uk_cm_write_result(target_id, operation_index), INDEX idx_cm_write_result_job_state(job_id,state)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        ]
        conn = self._connect(False)
        try:
            with conn.cursor() as cur:
                for ddl in ddls:
                    cur.execute(ddl)
            conn.commit()
        finally:
            conn.close()
        self._schema_ensured = True

    def options_cmts(self):
        cm_reset_service.ensure_schema()
        return cm_reset_service.get_cmts_options()

    def options_fiber_nodes(self, cmts: str):
        cm_reset_service.ensure_schema()
        return cm_reset_service.get_fiber_node_options(cmts)

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        scope = dict(payload.get("scope") or {})
        scope_type = str(scope.get("type") or "").strip().lower()
        if scope_type not in {"single", "cmts", "fiber_node", "file"}:
            raise ValueError("Unsupported scope type")
        operations = payload.get("operations") or []
        if not operations or len(operations) > 32:
            raise ValueError("One to 32 write operations are required")
        normalized = []
        for index, item in enumerate(operations):
            oid = str(item.get("oid") or "").strip()
            value_type = str(item.get("type") or "i").strip()
            if not oid or value_type not in {"i", "s", "x", "u", "c", "g", "t", "a"}:
                raise ValueError(f"Invalid operation {index + 1}")
            try:
                delay = max(0.0, min(float(item.get("delay") or 0), 300.0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid delay for operation {index + 1}") from exc
            value = item.get("value")
            if value is None:
                raise ValueError(f"Value is required for operation {index + 1}")
            if value_type in {"i", "u", "c", "g", "t"}:
                try:
                    value = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Integer value is invalid for operation {index + 1}") from exc
                if value_type == "i" and not -2147483648 <= value <= 2147483647:
                    raise ValueError(f"Integer32 value is out of range for operation {index + 1}")
                if value_type != "i" and value < 0:
                    raise ValueError(f"Unsigned value is invalid for operation {index + 1}")
                if value_type in {"u", "c", "g"} and value > 4294967295:
                    raise ValueError(f"32-bit value is out of range for operation {index + 1}")
            elif value_type == "a":
                try:
                    value = str(ipaddress.ip_address(str(value).strip()))
                except ValueError as exc:
                    raise ValueError(f"IP address is invalid for operation {index + 1}") from exc
            elif value_type == "s":
                value = str(value)
            if value_type == "x":
                text = str(value).strip().removeprefix("0x")
                if len(text) % 2 or any(c not in "0123456789abcdefABCDEF" for c in text):
                    raise ValueError(f"Hex value is invalid for operation {index + 1}")
                value = text
            normalized.append({"index": index, "oid": oid, "value": value, "type": value_type, "delay": delay})
        targets = cm_reset_service._resolve_targets(None, scope_type, scope)
        targets = [t for t in targets if t.get("ip")]
        if not targets:
            raise ValueError("No targets with a modem IP resolved from scope")
        delay_seconds = max(0, min(int(payload.get("delay_seconds") or 0), 86400))
        scheduled = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds) if delay_seconds else None
        requested_by = str(payload.get("requested_by") or "user")[:64]
        idem = payload.get("idempotency_key")
        if idem:
            existing = self._query("SELECT public_id FROM cm_snmp_write_job WHERE requested_by=%s AND idempotency_key=%s LIMIT 1", (requested_by, idem))
            if existing:
                return self.get_job(existing[0]["public_id"])
        public_id = str(uuid.uuid4()); now = self._now(); status = "scheduled" if scheduled else "planned"
        conn = self._connect(False)
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO cm_snmp_write_job (public_id,status,scope_type,scope_json,operations_json,scheduled_start,requested_by,idempotency_key,targets_total,operations_total,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (public_id,status,scope_type,json.dumps(scope),json.dumps(normalized),scheduled.strftime("%Y-%m-%d %H:%M:%S") if scheduled else None,requested_by,idem,len(targets),len(targets)*len(normalized),now,now))
                job_id = cur.lastrowid
                cur.executemany("INSERT INTO cm_snmp_write_target (job_id,mac,modem_ip,cmts,fiber_node,created_at) VALUES (%s,%s,%s,%s,%s,%s)", [(job_id,t.get("mac"),t.get("ip"),t.get("cmts"),t.get("fiber_node"),now) for t in targets])
                cur.execute("SELECT id FROM cm_snmp_write_target WHERE job_id=%s ORDER BY id", (job_id,))
                target_ids = [r["id"] for r in cur.fetchall()]
                result_rows = [(job_id, tid, op["index"], op["oid"], op["type"], json.dumps(op["value"]), op["delay"]) for tid in target_ids for op in normalized]
                cur.executemany("INSERT INTO cm_snmp_write_result (job_id,target_id,operation_index,oid,value_type,value_json,delay_seconds) VALUES (%s,%s,%s,%s,%s,%s,%s)", result_rows)
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()
        return self.get_job(public_id)

    def get_job_id(self, public_id):
        rows = self._query("SELECT id FROM cm_snmp_write_job WHERE public_id=%s", (public_id,))
        if not rows: raise KeyError(public_id)
        return int(rows[0]["id"])

    @staticmethod
    def _dt(value):
        return value.replace(tzinfo=timezone.utc).isoformat() if isinstance(value, datetime) else (str(value) if value else None)

    def _format_job(self, row):
        return {"public_id": row["public_id"], "status": row["status"], "scope_type": row.get("scope_type"), "targets_total": int(row.get("targets_total") or 0), "operations_total": int(row.get("operations_total") or 0), "operations_succeeded": int(row.get("operations_succeeded") or 0), "operations_failed": int(row.get("operations_failed") or 0), "operations_pending": max(0, int(row.get("operations_total") or 0)-int(row.get("operations_succeeded") or 0)-int(row.get("operations_failed") or 0)), "scheduled_start": self._dt(row.get("scheduled_start")), "started_at": self._dt(row.get("started_at")), "finished_at": self._dt(row.get("finished_at")), "created_at": self._dt(row.get("created_at")), "requested_by": row.get("requested_by"), "error_text": row.get("error_text")}

    def get_job(self, public_id):
        self.ensure_schema(); rows = self._query("SELECT * FROM cm_snmp_write_job WHERE public_id=%s", (public_id,))
        if not rows: raise KeyError(public_id)
        return self._format_job(rows[0])

    def list_jobs(self, limit=50):
        self.ensure_schema(); return [self._format_job(r) for r in self._query("SELECT * FROM cm_snmp_write_job ORDER BY id DESC LIMIT %s", (max(1,min(int(limit),200)),))]

    def set_status(self, public_id, status):
        now=self._now(); self._execute("UPDATE cm_snmp_write_job SET status=%s, started_at=CASE WHEN %s='running' THEN COALESCE(started_at,%s) ELSE started_at END, updated_at=%s WHERE public_id=%s AND status IN ('planned','scheduled','queued')",(status,status,now,now,public_id))

    def due_jobs(self):
        return self._query("SELECT public_id FROM cm_snmp_write_job WHERE status='scheduled' AND scheduled_start<=UTC_TIMESTAMP() ORDER BY id LIMIT 20")

    def claim_results(self, job_id, limit):
        return self._query("SELECT r.id,t.mac,t.modem_ip,t.cmts,r.operation_index,r.oid,r.value_type,r.value_json,r.delay_seconds,r.state,r.error_text,r.started_at,r.finished_at,r.duration_ms FROM cm_snmp_write_result r JOIN cm_snmp_write_target t ON t.id=r.target_id WHERE r.job_id=%s AND r.state='planned' ORDER BY t.id,r.operation_index LIMIT %s",(job_id,max(1,min(int(limit),100000))))

    def mark_result(self, result_id, state, error=None, agent_id=None, task_id=None, started_at=None, duration_ms=None):
        now=self._now(); self._execute("UPDATE cm_snmp_write_result SET state=%s,error_text=%s,started_at=COALESCE(started_at,%s),finished_at=%s,duration_ms=%s,agent_id=%s,task_id=%s WHERE id=%s",(state,error,started_at or now,now,duration_ms,agent_id,task_id,result_id))

    def finish_job(self, job_id, error=None):
        cancelled = bool(self._query("SELECT cancel_requested_at FROM cm_snmp_write_job WHERE id=%s AND cancel_requested_at IS NOT NULL", (job_id,)))
        if cancelled:
            self._execute("UPDATE cm_snmp_write_result SET state='cancelled', finished_at=%s WHERE job_id=%s AND state='planned'", (self._now(), job_id))
        counts=self._query("SELECT SUM(state='complete') ok,SUM(state='failed') bad,COUNT(*) total FROM cm_snmp_write_result WHERE job_id=%s",(job_id,))[0]
        ok=int(counts.get('ok') or 0); bad=int(counts.get('bad') or 0)
        status='cancelled' if cancelled else ('failed' if error else ('completed_with_errors' if bad else 'completed'))
        self._execute("UPDATE cm_snmp_write_job SET status=%s,operations_succeeded=%s,operations_failed=%s,error_text=%s,finished_at=%s,updated_at=%s WHERE id=%s",(status,ok,bad,error,self._now(),self._now(),job_id))

    def cancel(self, public_id):
        self._execute("UPDATE cm_snmp_write_job SET cancel_requested_at=%s,status=CASE WHEN status IN ('planned','scheduled') THEN 'cancelled' ELSE status END,updated_at=%s WHERE public_id=%s AND status IN ('planned','scheduled','queued','running')",(self._now(),self._now(),public_id)); return self.get_job(public_id)

    def cancelled(self, job_id):
        return bool(self._query("SELECT cancel_requested_at FROM cm_snmp_write_job WHERE id=%s AND cancel_requested_at IS NOT NULL",(job_id,)))

    def delete(self, public_id):
        job_id=self.get_job_id(public_id); row=self._query("SELECT status FROM cm_snmp_write_job WHERE id=%s",(job_id,))[0]
        if row['status']=='running': raise ValueError('Cannot delete a running job')
        self._execute("DELETE FROM cm_snmp_write_job WHERE id=%s",(job_id,)); return {'status':'success','deleted':public_id}

    def list_results(self, public_id, cursor=0, limit=200):
        job_id=self.get_job_id(public_id); safe=max(1,min(int(limit),1000)); rows=self._query("SELECT r.id,t.mac,t.modem_ip,t.cmts,r.operation_index,r.oid,r.value_type,r.value_json,r.state,r.error_text,r.started_at,r.finished_at,r.duration_ms FROM cm_snmp_write_result r JOIN cm_snmp_write_target t ON t.id=r.target_id WHERE r.job_id=%s AND r.id>%s ORDER BY r.id LIMIT %s",(job_id,max(0,int(cursor)),safe+1)); more=len(rows)>safe; page=rows[:safe]
        out=[]
        for r in page:
            out.append({'id':r['id'],'mac':r['mac'],'modem_ip':r.get('modem_ip'),'cmts':r.get('cmts'),'operation_index':r['operation_index'],'oid':r['oid'],'type':r['value_type'],'value':None,'state':r['state'],'error_text':r.get('error_text'),'started_at':self._dt(r.get('started_at')),'finished_at':self._dt(r.get('finished_at')),'duration_ms':r.get('duration_ms')})
        return {'results':out,'next_cursor':page[-1]['id'] if more and page else None,'has_more':more}

    def _execute(self, sql, params=()):
        with self._db_lock:
            conn=self._connect()
            try:
                with conn.cursor() as cur: cur.execute(sql,params)
                conn.commit()
            finally: conn.close()


cm_write_service = CmWriteService()
