# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from pypnm.api.routes.cm_snmp_query.service import cm_snmp_query_service

logger = logging.getLogger(__name__)


class CmSnmpQueryWorker:
    """Run one custom SNMP query job at a time."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_lock = asyncio.Lock()

    async def start(
        self,
        public_id: str,
        max_concurrency: int = 10,
        community: str | None = None,
    ) -> dict[str, Any]:
        concurrency = max(1, min(int(max_concurrency), 20))
        lease_owner = f"snmp-query-worker-{uuid.uuid4()}"

        async with self._task_lock:
            if public_id in self._tasks and not self._tasks[public_id].done():
                return cm_snmp_query_service.get_job(public_id)

            job = cm_snmp_query_service.get_job(public_id)
            if job["status"] != "planned":
                raise ValueError(f"Job is in state '{job['status']}', cannot start")

            task = asyncio.create_task(
                self._run_job(
                    public_id=public_id,
                    job_id=cm_snmp_query_service.get_job_id_by_public_id(public_id),
                    lease_owner=lease_owner,
                    max_concurrency=concurrency,
                    community=community,
                ),
                name=f"snmp-query-{public_id}",
            )
            self._tasks[public_id] = task
        return cm_snmp_query_service.get_job(public_id)

    async def cancel(self, public_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(cm_snmp_query_service.request_cancel, public_id)

    async def _run_job(
        self,
        *,
        public_id: str,
        job_id: int,
        lease_owner: str,
        max_concurrency: int,
        community: str | None,
    ) -> None:
        heartbeat: asyncio.Task | None = None
        try:
            await asyncio.to_thread(cm_snmp_query_service.activate_job, public_id, lease_owner)
            heartbeat = asyncio.create_task(
                self._heartbeat(job_id, lease_owner),
                name=f"snmp-query-heartbeat-{public_id}",
            )

            # Load OIDs for this job
            oids = await asyncio.to_thread(cm_snmp_query_service.get_job_oids, job_id)

            active_targets: set[asyncio.Task] = set()
            while True:
                if heartbeat.done():
                    heartbeat.result()

                cancelling = await asyncio.to_thread(
                    cm_snmp_query_service.job_cancel_requested, job_id
                )
                if cancelling:
                    break

                while not cancelling and len(active_targets) < max_concurrency:
                    targets = await asyncio.to_thread(
                        cm_snmp_query_service.claim_targets,
                        job_id,
                        max_concurrency - len(active_targets),
                    )
                    if not targets:
                        break
                    for target in targets:
                        active_targets.add(
                            asyncio.create_task(
                                self._query_target(target, oids, community),
                                name=f"snmp-query-target-{target['id']}",
                            )
                        )

                if not active_targets:
                    break

                done, active_targets = await asyncio.wait(
                    active_targets, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    if t.exception():
                        logger.warning(f"SNMP query target error: {t.exception()}")

            if active_targets:
                await asyncio.wait(active_targets, timeout=60)

        except Exception as exc:
            logger.error(f"SNMP query job {public_id} failed: {exc}", exc_info=True)
            await asyncio.to_thread(cm_snmp_query_service.finish_job, job_id, str(exc))
            return
        finally:
            if heartbeat and not heartbeat.done():
                heartbeat.cancel()

        await asyncio.to_thread(cm_snmp_query_service.finish_job, job_id, None)
        logger.info(f"SNMP query job {public_id} finished")

    async def _heartbeat(self, job_id: int, lease_owner: str) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(cm_snmp_query_service.extend_lease, job_id, lease_owner)
            except Exception as exc:
                logger.warning(f"SNMP query heartbeat failed: {exc}")
                return

    async def _query_target(
        self,
        target: dict[str, Any],
        oids: list[dict],
        community: str | None,
    ) -> None:
        """Query all requested OIDs for one modem in a single bulk task."""
        target_id = int(target["id"])
        modem_ip = target.get("modem_ip")

        if not modem_ip:
            await asyncio.to_thread(
                cm_snmp_query_service.mark_target_failed, target_id, "No modem IP"
            )
            return

        try:
            from pypnm.api.agent.manager import get_agent_manager
            from pypnm.api.routes.cm_snmp_query.oid_resolver import resolve_oid

            agent_manager = get_agent_manager()
            if not agent_manager:
                raise RuntimeError("Agent manager not available")

            agent = agent_manager.get_agent_for_capability("cm_reachable")
            if not agent:
                raise RuntimeError("No cm_reachable agent connected")

            resolved_entries = [
                (entry.get("label") or entry.get("oid", ""), resolve_oid(entry.get("oid", "")))
                for entry in oids
            ]
            results: dict[str, Any] = {label: None for label, _ in resolved_entries}
            params = {
                "target_ip": modem_ip,
                "oids": [numeric_oid for _, numeric_oid in resolved_entries],
                "target_role": "cm",
                "timeout": 5,
                "retries": 1,
                # Preserve the previous one-request-at-a-time modem load shape.
                "max_concurrent": 1,
            }
            if community:
                params["community"] = community

            task_id = await agent_manager.send_task(
                agent.agent_id,
                "snmp_bulk_get",
                params,
                timeout=30,
                priority="bulk",
            )
            result = await agent_manager.wait_for_task_async(task_id, timeout=30)
            if not result or result.get("type") != "response":
                raise RuntimeError("Agent bulk SNMP task timed out")
            response = result.get("result", {})
            if not response.get("success"):
                raise RuntimeError(response.get("error") or "Agent bulk SNMP task failed")
            oid_results = response.get("results", {})

            for label, numeric_oid in resolved_entries:
                oid_result = oid_results.get(numeric_oid) or oid_results.get(numeric_oid.lstrip("."))
                if not isinstance(oid_result, dict) or not oid_result.get("success"):
                    continue
                value = oid_result.get("value")
                if value is None and oid_result.get("results"):
                    value = oid_result["results"][0].get("value")
                if value is None and oid_result.get("output") is not None:
                    raw = str(oid_result["output"])
                    value = raw.split(" = ", 1)[1].strip() if " = " in raw else raw.strip()
                results[label] = value

            await asyncio.to_thread(
                cm_snmp_query_service.record_target_result, target_id, results
            )

        except Exception as exc:
            logger.warning(f"SNMP query failed for {target.get('mac')}: {exc}")
            await asyncio.to_thread(
                cm_snmp_query_service.mark_target_failed, target_id, str(exc)[:500]
            )


# Singleton
cm_snmp_query_worker = CmSnmpQueryWorker()
