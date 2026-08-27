# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from pypnm.api.routes.cm_reset.service import cm_reset_service

logger = logging.getLogger(__name__)

# OID for docsDevResetNow — SET to 1 (true) triggers modem reset
_DOCS_DEV_RESET_NOW_OID = "1.3.6.1.2.1.69.1.1.3.0"


def _configured_modem_community() -> str | None:
    """Resolve the optional modem write community from environment/config."""
    from pypnm.config.pnm_config_manager import PnmConfigManager
    community = (
        os.environ.get("MODEM_COMMUNITY")
        or os.environ.get("CM_SNMP_COMMUNITY")
        or PnmConfigManager.get_write_community()
    )
    return str(community) if community else None


class CmResetWorker:
    """Run one durable CM bulk reset job at a time."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_lock = asyncio.Lock()

    async def start(self, public_id: str, max_concurrency: int = 5, skip_window_check: bool = False) -> dict[str, Any]:
        """Start execution of a planned reset job."""
        concurrency = max(1, min(int(max_concurrency), 10))
        lease_owner = f"cm-reset-worker-{uuid.uuid4()}"

        async with self._task_lock:
            if public_id in self._tasks and not self._tasks[public_id].done():
                return cm_reset_service.get_job(public_id)

            job = cm_reset_service.get_job(public_id)
            if job["status"] not in ("planned", "queued"):
                raise ValueError(f"Job is in state '{job['status']}', cannot start")

            # Check execution window (unless godmode)
            if not skip_window_check and not cm_reset_service.is_within_execution_window():
                next_start = cm_reset_service.next_execution_window_start()
                raise ValueError(
                    f"Resets can only run between 01:00 and 06:00. "
                    f"Next window opens at {next_start.strftime('%Y-%m-%d %H:%M')}."
                )

            task = asyncio.create_task(
                self._run_job(
                    public_id=public_id,
                    job_id=cm_reset_service.get_job_id_by_public_id(public_id),
                    lease_owner=lease_owner,
                    max_concurrency=concurrency,
                ),
                name=f"cm-reset-{public_id}",
            )
            self._tasks[public_id] = task
        return cm_reset_service.get_job(public_id)

    async def cancel(self, public_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(cm_reset_service.request_cancel, public_id)

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
            await asyncio.to_thread(
                cm_reset_service.activate_job, public_id, lease_owner
            )
            heartbeat = asyncio.create_task(
                self._heartbeat(job_id, lease_owner),
                name=f"cm-reset-heartbeat-{public_id}",
            )

            active_targets: set[asyncio.Task] = set()
            while True:
                # Check execution window — pause if outside 01:00-06:00
                if not cm_reset_service.is_within_execution_window():
                    logger.info(
                        f"CM reset job {public_id}: outside execution window, "
                        "pausing until next 01:00"
                    )
                    # Wait until we're back in the window (check every 60s)
                    while not cm_reset_service.is_within_execution_window():
                        if await asyncio.to_thread(cm_reset_service.job_cancel_requested, job_id):
                            break
                        await asyncio.sleep(60)

                if heartbeat.done():
                    heartbeat.result()

                cancelling = await asyncio.to_thread(
                    cm_reset_service.job_cancel_requested, job_id
                )
                if cancelling:
                    break

                # Fill up to max_concurrency
                while not cancelling and len(active_targets) < max_concurrency:
                    targets = await asyncio.to_thread(
                        cm_reset_service.claim_targets,
                        job_id,
                        max_concurrency - len(active_targets),
                    )
                    if not targets:
                        break
                    for target in targets:
                        active_targets.add(
                            asyncio.create_task(
                                self._reset_target(target),
                                name=f"cm-reset-target-{target['id']}",
                            )
                        )

                if not active_targets:
                    # No more targets to process
                    break

                # Wait for at least one to finish
                done, active_targets = await asyncio.wait(
                    active_targets, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    if t.exception():
                        logger.warning(f"CM reset target task error: {t.exception()}")

            # Wait for remaining
            if active_targets:
                await asyncio.wait(active_targets, timeout=30)

        except Exception as exc:
            logger.error(f"CM reset job {public_id} failed: {exc}", exc_info=True)
            await asyncio.to_thread(
                cm_reset_service.finish_job, job_id, str(exc)
            )
            return
        finally:
            if heartbeat and not heartbeat.done():
                heartbeat.cancel()

        await asyncio.to_thread(cm_reset_service.finish_job, job_id, None)
        logger.info(f"CM reset job {public_id} finished")

    async def _heartbeat(self, job_id: int, lease_owner: str) -> None:
        """Extend the job lease every 30s to prevent stale-lock recovery."""
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(
                    cm_reset_service.extend_lease, job_id, lease_owner
                )
            except Exception as exc:
                logger.warning(f"CM reset heartbeat failed: {exc}")
                return

    async def _reset_target(self, target: dict[str, Any]) -> None:
        """Fire-and-forget: send docsDevResetNow SET to the modem via cm-agent."""
        target_id = int(target["id"])
        mac = target.get("mac", "unknown")
        modem_ip = target.get("modem_ip")

        if not modem_ip:
            await asyncio.to_thread(
                cm_reset_service.mark_target_failed,
                target_id,
                "No modem IP address available",
            )
            return

        try:
            from pypnm.api.agent.manager import get_agent_manager

            agent_manager = get_agent_manager()
            if not agent_manager:
                raise RuntimeError("Agent manager not available")

            # Get cm-agent (modem-reachable) without a generic SNMP fallback.
            agent = agent_manager.get_agent_for_capability("cm_reachable")
            if not agent:
                raise RuntimeError("No cm_reachable agent connected")

            community = _configured_modem_community()
            params = {
                "target_ip": modem_ip,
                "oid": _DOCS_DEV_RESET_NOW_OID,
                "value": 1,
                "type": "i",
                "target_role": "cm",
                "timeout": 3,
                "retries": 0,
            }
            if community:
                params["community"] = community

            # Fire-and-forget: send the SET but don't wait long for confirmation
            # (modem will reset and drop the connection anyway)
            task_id = await agent_manager.send_task(
                agent.agent_id,
                "snmp_set",
                params,
                timeout=10,
                priority="bulk",
            )

            # Brief wait — a timeout/disconnect can be consistent with the modem
            # rebooting, but an explicit agent rejection must fail the target.
            try:
                result = await agent_manager.wait_for_task_async(task_id, timeout=8)
            except Exception:
                result = None

            if result and result.get("type") == "error":
                raise RuntimeError(result.get("error") or "Agent rejected CM reset")
            if result and result.get("type") == "response":
                operation = result.get("result") or {}
                if not operation.get("success"):
                    raise RuntimeError(
                        operation.get("error") or "Agent CM reset SET failed"
                    )

            await asyncio.to_thread(cm_reset_service.mark_target_done, target_id)
            logger.debug(f"CM reset sent: {mac} ({modem_ip})")

        except Exception as exc:
            logger.warning(f"CM reset failed for {mac} ({modem_ip}): {exc}")
            await asyncio.to_thread(
                cm_reset_service.mark_target_failed, target_id, str(exc)[:500]
            )


# Singleton
cm_reset_worker = CmResetWorker()
