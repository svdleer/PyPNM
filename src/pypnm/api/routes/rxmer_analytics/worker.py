# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from pypnm.api.routes.rxmer_analytics.service import rxmer_analytics_service

logger = logging.getLogger(__name__)


class RxMerCollectionWorker:
    """Run one durable, non-overlapping network RxMER job at a time."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._task_lock = asyncio.Lock()

    async def start(self, public_id: str, max_concurrency: int = 2) -> dict[str, Any]:
        concurrency = max(1, min(int(max_concurrency), 2))
        lease_owner = f"rxmer-worker-{uuid.uuid4()}"
        async with self._task_lock:
            current = self._tasks.get(public_id)
            if current and not current.done():
                raise RuntimeError("RxMER job is already running in this process")
            job = await asyncio.to_thread(
                rxmer_analytics_service.prepare_job_start,
                public_id,
                lease_owner,
            )
            task = asyncio.create_task(
                self._run_job(
                    public_id=public_id,
                    job_id=int(job["id"]),
                    lease_owner=lease_owner,
                    max_concurrency=concurrency,
                ),
                name=f"rxmer-job-{public_id}",
            )
            self._tasks[public_id] = task
        return job

    async def cancel(self, public_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(rxmer_analytics_service.request_cancel, public_id)

    async def _run_job(
        self,
        *,
        public_id: str,
        job_id: int,
        lease_owner: str,
        max_concurrency: int,
    ) -> None:
        heartbeat: asyncio.Task[None] | None = None
        try:
            await asyncio.to_thread(
                rxmer_analytics_service.activate_job,
                public_id,
                lease_owner,
            )
            heartbeat = asyncio.create_task(
                self._heartbeat(job_id, lease_owner),
                name=f"rxmer-heartbeat-{public_id}",
            )
            while not await asyncio.to_thread(
                rxmer_analytics_service.job_cancel_requested,
                job_id,
            ):
                if heartbeat.done():
                    heartbeat.result()
                targets = await asyncio.to_thread(
                    rxmer_analytics_service.claim_targets,
                    job_id,
                    max_concurrency,
                )
                if not targets:
                    break
                await asyncio.to_thread(
                    rxmer_analytics_service.refresh_job_progress,
                    job_id,
                )
                await asyncio.gather(
                    *(self._process_target(job_id, target) for target in targets)
                )
                if heartbeat.done():
                    heartbeat.result()
                await asyncio.to_thread(
                    rxmer_analytics_service.refresh_job_progress,
                    job_id,
                )

            await asyncio.to_thread(
                rxmer_analytics_service.finish_job,
                job_id,
                lease_owner,
            )
        except Exception as exc:
            logger.exception("RxMER job %s interrupted: %s", public_id, exc)
            await asyncio.to_thread(
                rxmer_analytics_service.interrupt_job,
                job_id,
                lease_owner,
                str(exc),
            )
        finally:
            if heartbeat:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.warning("RxMER heartbeat stopped with error: %s", exc)
            async with self._task_lock:
                self._tasks.pop(public_id, None)

    async def _heartbeat(self, job_id: int, lease_owner: str) -> None:
        while True:
            await asyncio.sleep(30)
            await asyncio.to_thread(
                rxmer_analytics_service.heartbeat_job,
                job_id,
                lease_owner,
            )

    async def _process_target(self, job_id: int, target: dict[str, Any]) -> None:
        from pypnm.api.routes.common.extended.common_measure_schema import (
            DownstreamOfdmParameters,
        )
        from pypnm.api.routes.docs.pnm.ds.ofdm.rxmer.service import (
            CmDsOfdmRxMerService,
        )
        from pypnm.docsis.cable_modem import CableModem
        from pypnm.lib.inet import Inet
        from pypnm.lib.mac_address import MacAddress

        target_id = int(target["id"])
        last_error: str | None = None
        try:
            modem = CableModem(
                mac_address=MacAddress(str(target["mac"])),
                inet=Inet(str(target["modem_ip"])),
            )
            cm_agent_id = getattr(getattr(modem, "_snmp", None), "_agent_id", None)
            channels = await modem.getDocsIf31CmDsOfdmChannelIdIndexStack()
            if not channels:
                raise RuntimeError("modem reported no downstream OFDM channels")
            await asyncio.to_thread(
                rxmer_analytics_service.update_expected_channels,
                target_id,
                len(channels),
            )
            completed_ifindexes = await asyncio.to_thread(
                rxmer_analytics_service.successful_ifindexes,
                target_id,
            )

            for ifindex, channel_id in channels:
                if int(ifindex) in completed_ifindexes:
                    continue
                if await asyncio.to_thread(
                    rxmer_analytics_service.job_cancel_requested,
                    job_id,
                ):
                    last_error = "job cancellation requested"
                    break
                try:
                    response = await CmDsOfdmRxMerService(modem).set_and_go(
                        interface_parameters=DownstreamOfdmParameters(
                            channel_id=[channel_id]
                        )
                    )
                    transaction_id, filename = self._successful_transaction(response)
                    await self._persist_transaction(
                        target_id=target_id,
                        expected_channel_id=int(channel_id),
                        expected_ifindex=int(ifindex),
                        transaction_id=transaction_id,
                        filename=filename,
                        cm_agent_id=cm_agent_id,
                    )
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning(
                        "RxMER target=%s channel=%s failed: %s",
                        target_id,
                        channel_id,
                        exc,
                    )
                    await asyncio.to_thread(
                        rxmer_analytics_service.mark_channel_failure,
                        target_id,
                        int(ifindex),
                        int(channel_id),
                        last_error,
                    )
        except Exception as exc:
            last_error = str(exc)
            logger.warning("RxMER target=%s failed: %s", target_id, exc)
        finally:
            await asyncio.to_thread(
                rxmer_analytics_service.finish_target,
                target_id,
                last_error,
            )

    @staticmethod
    def _successful_transaction(response: Any) -> tuple[str, str]:
        from pypnm.api.routes.common.extended.common_messaging_service import (
            MessageResponse,
            MessageResponseType,
        )
        from pypnm.api.routes.common.service.status_codes import ServiceStatusCode

        if response.status != ServiceStatusCode.SUCCESS:
            raise RuntimeError(f"RxMER capture failed with status {response.status.name}")
        if not isinstance(response.payload, list):
            raise RuntimeError("RxMER capture returned an invalid payload")
        for entry in response.payload:
            status_name, message_type, body = MessageResponse.get_payload_msg(entry)
            if (
                status_name == ServiceStatusCode.SUCCESS.name
                and message_type == MessageResponseType.PNM_FILE_TRANSACTION.name
                and isinstance(body, dict)
            ):
                transaction_id = str(body.get("transaction_id") or "")
                filename = str(body.get("filename") or "")
                if transaction_id and filename:
                    return transaction_id, filename
        raise RuntimeError("RxMER capture returned no successful file transaction")

    @staticmethod
    async def _persist_transaction(
        *,
        target_id: int,
        expected_channel_id: int,
        expected_ifindex: int,
        transaction_id: str,
        filename: str,
        cm_agent_id: str | None,
    ) -> None:
        from pypnm.api.routes.docs.pnm.files.service import PnmFileService
        from pypnm.lib.file_processor import FileProcessor
        from pypnm.pnm.parser.CmDsOfdmRxMer import CmDsOfdmRxMer

        last_error: Exception | None = None
        parsed = None
        for attempt in range(3):
            try:
                path = await asyncio.to_thread(
                    PnmFileService().get_pnm_path_for_transaction,
                    transaction_id,
                )
                binary_data = await asyncio.to_thread(FileProcessor(path).read_file)
                parsed = CmDsOfdmRxMer(binary_data)
                break
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(attempt + 1)
        if parsed is None:
            raise RuntimeError(f"RxMER transaction could not be parsed: {last_error}")
        model = parsed.to_model()
        parsed_channel_id = int(model.channel_id)
        if parsed_channel_id != expected_channel_id:
            raise RuntimeError(
                f"RxMER channel mismatch: expected {expected_channel_id}, "
                f"received {parsed_channel_id}"
            )
        await asyncio.to_thread(
            rxmer_analytics_service.record_channel_result,
            target_id=target_id,
            channel_id=parsed_channel_id,
            ifindex=expected_ifindex,
            zero_frequency_hz=int(model.subcarrier_zero_frequency),
            first_active_index=int(model.first_active_subcarrier_index),
            spacing_hz=int(model.subcarrier_spacing),
            raw_vector=parsed.get_raw_rxmer_qdb(),
            filename=filename,
            cm_agent_id=cm_agent_id,
            file_agent_id=None,
        )


rxmer_collection_worker = RxMerCollectionWorker()
