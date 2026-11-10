from __future__ import annotations

import asyncio, json, logging, time
from datetime import datetime, timezone
from typing import Any

from pypnm.api.agent.manager import get_agent_manager
from .service import cm_write_service

logger=logging.getLogger(__name__)

class CmWriteWorker:
    def __init__(self):
        self._tasks={}
        self._scheduler=None

    async def start_scheduler(self):
        if self._scheduler is None or self._scheduler.done():
            self._scheduler=asyncio.create_task(self._schedule_loop(), name='cm-write-scheduler')

    async def _schedule_loop(self):
        while True:
            try:
                for row in await asyncio.to_thread(cm_write_service.due_jobs):
                    public_id=row['public_id']
                    if public_id not in self._tasks or self._tasks[public_id].done():
                        await asyncio.to_thread(cm_write_service.set_status, public_id, 'queued')
                        self._tasks[public_id]=asyncio.create_task(self._run(public_id), name=f'cm-write-{public_id}')
            except Exception: logger.exception('CM write scheduler failed')
            await asyncio.sleep(2)

    async def start(self, public_id, max_concurrency=5):
        await self.start_scheduler()
        job=cm_write_service.get_job(public_id)
        if job['status'] not in ('planned','queued'):
            raise ValueError(f"Job is in state '{job['status']}', cannot start")
        if public_id not in self._tasks or self._tasks[public_id].done():
            await asyncio.to_thread(cm_write_service.set_status, public_id, 'queued')
            self._tasks[public_id]=asyncio.create_task(self._run(public_id,max_concurrency),name=f'cm-write-{public_id}')
        return cm_write_service.get_job(public_id)

    async def _run(self, public_id, max_concurrency=5):
        job_id=cm_write_service.get_job_id(public_id); cm_write_service.set_status(public_id,'running')
        try:
            results=await asyncio.to_thread(cm_write_service.claim_results,job_id,100000)
            # Results are ordered by target then operation. Each target sequence is
            # sequential, while different targets are bounded concurrently.
            by_target={}
            for r in results: by_target.setdefault((r['mac'],r['modem_ip']),[]).append(r)
            semaphore=asyncio.Semaphore(max(1,min(int(max_concurrency),10)))
            async def run_target(items):
                async with semaphore:
                    for result in items:
                        if await asyncio.to_thread(cm_write_service.cancelled,job_id): return
                        await self._run_result(result)
            await asyncio.gather(*(run_target(items) for items in by_target.values()))
            await asyncio.to_thread(cm_write_service.finish_job,job_id)
        except Exception as exc:
            logger.exception('CM write job %s failed',public_id)
            await asyncio.to_thread(cm_write_service.finish_job,job_id,str(exc)[:500])

    async def _run_result(self, result):
        started=time.monotonic(); started_at=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        manager=get_agent_manager()
        if not result.get('modem_ip'):
            await asyncio.to_thread(cm_write_service.mark_result,result['id'],'failed','No modem IP address available',started_at=started_at,duration_ms=0); return
        if not manager: await asyncio.to_thread(cm_write_service.mark_result,result['id'],'failed','Agent manager unavailable',started_at=started_at,duration_ms=0); return
        agent=manager.get_agent_for_capability('cm_reachable')
        if not agent: await asyncio.to_thread(cm_write_service.mark_result,result['id'],'failed','No cm_reachable agent connected',started_at=started_at,duration_ms=0); return
        try:
            value=result.get('value_json'); value=json.loads(value) if isinstance(value,str) else value
            params={'target_ip':result['modem_ip'],'oid':result['oid'],'value':value,'type':result['value_type'],'target_role':'cm','timeout':5,'retries':0}
            task_id=await manager.send_task(agent.agent_id,'snmp_set',params,timeout=15,priority='bulk')
            response=await manager.wait_for_task_async(task_id,timeout=15)
            operation=(response or {}).get('result') or {}
            if (response or {}).get('type')=='error' or not operation.get('success'):
                raise RuntimeError((response or {}).get('error') or operation.get('error') or 'SNMP SET failed')
            await asyncio.to_thread(cm_write_service.mark_result,result['id'],'complete',None,agent.agent_id,task_id,started_at,int((time.monotonic()-started)*1000))
        except Exception as exc:
            await asyncio.to_thread(cm_write_service.mark_result,result['id'],'failed',str(exc)[:500],agent.agent_id if agent else None,locals().get('task_id'),started_at,int((time.monotonic()-started)*1000))
        delay=float(result.get('delay_seconds') or 0)
        if delay: await asyncio.sleep(min(delay,300))

cm_write_worker=CmWriteWorker()
