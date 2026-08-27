# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from pypnm.api.routes.cm_snmp_query.service import cm_snmp_query_service

logger = logging.getLogger(__name__)


def _configured_modem_community() -> str:
    from pypnm.config.pnm_config_manager import PnmConfigManager
    community = (
        os.environ.get("MODEM_COMMUNITY")
        or os.environ.get("CM_SNMP_COMMUNITY")
        or PnmConfigManager.get_write_community()
    )
    if not community:
        raise RuntimeError("Cable-modem SNMP community is not configured")
    return str(community)


class CmSnmpQueryWorker:
    """Run one custom SNMP query job at a time."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_lock = asyncio.Lock()

    async def start(self, public_id: str, max_concurrency: int = 10) -> dict[str, Any]:
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
                                self._query_target(target, oids),
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

    async def _query_target(self, target: dict[str, Any], oids: list[dict]) -> None:
        """SNMP GET each OID for this modem via cm-agent."""
        target_id = int(target["id"])
        modem_ip = target.get("modem_ip")

        if not modem_ip:
            await asyncio.to_thread(
                cm_snmp_query_service.mark_target_failed, target_id, "No modem IP"
            )
            return

        try:
            from pypnm.api.agent.manager import get_agent_manager

            agent_manager = get_agent_manager()
            if not agent_manager:
                raise RuntimeError("Agent manager not available")

            agent = (
                agent_manager.get_agent_for_capability("cm_reachable")
                or agent_manager.get_agent_for_capability("snmp_get")
            )
            if not agent:
                raise RuntimeError("No cm-agent connected")

            community = _configured_modem_community()
            results: dict[str, Any] = {}

            for entry in oids:
                oid = entry.get("oid", "")
                label = entry.get("label") or oid

                # Resolve MIB name to numeric OID server-side
                from pypnm.api.routes.cm_snmp_query.oid_resolver import resolve_oid
                numeric_oid = resolve_oid(oid)

                try:
                    task_id = await agent_manager.send_task(
                        agent.agent_id,
                        "snmp_get",
                        {
                            "target_ip": modem_ip,
                            "oid": numeric_oid,
                            "community": community,
                            "timeout": 5,
                            "retries": 1,
                        },
                        timeout=15,
                        priority="bulk",
                    )
                    result = await agent_manager.wait_for_task_async(task_id, timeout=15)

                    if result and result.get("type") == "response":
                        res_data = result.get("result", {})
                        if res_data.get("success"):
                            # Agent returns 'results' list (parallel_walk style)
                            # or 'output' string (get style: "OID = value")
                            if res_data.get("results"):
                                value = res_data["results"][0].get("value")
                            elif res_data.get("output"):
                                # Parse "OID = value" format
                                raw = str(res_data["output"])
                                if " = " in raw:
                                    value = raw.split(" = ", 1)[1].strip()
                                else:
                                    value = raw.strip()
                            else:
                                value = None
                            results[label] = value
                        else:
                            results[label] = None
                    else:
                        results[label] = None
                except Exception:
                    results[label] = None

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
