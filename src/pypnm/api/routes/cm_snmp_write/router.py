from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from .schema import (
    CmWriteJob,
    CmWriteJobListResponse,
    CmWriteJobResponse,
    CmWritePlanRequest,
    CmWriteResultListResponse,
    CmWriteStartRequest,
)
from .service import cm_write_service
from .worker import cm_write_worker

logger=logging.getLogger(__name__)
router=APIRouter(prefix='/api/admin/cm-snmp-write',tags=['CM bulk SNMP write'])

@router.on_event('startup')
async def start_worker(): await cm_write_worker.start_scheduler()

@router.get('/options/cmts')
def options_cmts(limit:int=Query(5000,ge=1,le=10000)): return {'status':'success','cmts':cm_write_service.options_cmts()[:limit]}

@router.get('/options/fiber-nodes')
def options_fiber_nodes(cmts:str=Query(...,max_length=128),limit:int=Query(5000,ge=1,le=10000)): return {'status':'success','fiber_nodes':cm_write_service.options_fiber_nodes(cmts)[:limit]}

@router.get('/jobs',response_model=CmWriteJobListResponse)
def jobs(limit:int=Query(50,ge=1,le=200)): return CmWriteJobListResponse(jobs=[CmWriteJob(**j) for j in cm_write_service.list_jobs(limit)])

@router.post('/jobs/plan',response_model=CmWriteJobResponse)
def plan(payload:CmWritePlanRequest):
    if not cm_write_service.password_valid(payload.confirmation_password): raise HTTPException(403,'Incorrect confirmation password')
    try: job=cm_write_service.create_plan({**payload.model_dump(exclude={'confirmation_password'}),'operations':[x.model_dump() for x in payload.operations]})
    except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc)) from exc
    except Exception as exc: logger.exception('CM write plan failed'); raise HTTPException(503,'Plan creation failed') from exc
    return CmWriteJobResponse(job=CmWriteJob(**job))

@router.get('/jobs/{public_id}',response_model=CmWriteJobResponse)
def job(public_id:str):
    try: return CmWriteJobResponse(job=CmWriteJob(**cm_write_service.get_job(public_id)))
    except KeyError as exc: raise HTTPException(404,'Job not found') from exc

@router.post('/jobs/{public_id}/start',response_model=CmWriteJobResponse)
async def start(public_id:str,payload:CmWriteStartRequest):
    if not cm_write_service.password_valid(payload.confirmation_password): raise HTTPException(403,'Incorrect confirmation password')
    try: return CmWriteJobResponse(job=CmWriteJob(**(await cm_write_worker.start(public_id,payload.max_concurrency))))
    except KeyError as exc: raise HTTPException(404,'Job not found') from exc
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc

@router.post('/jobs/{public_id}/cancel',response_model=CmWriteJobResponse)
async def cancel(public_id:str):
    try: return CmWriteJobResponse(job=CmWriteJob(**(await asyncio.to_thread(cm_write_service.cancel,public_id))))
    except KeyError as exc: raise HTTPException(404,'Job not found') from exc

@router.delete('/jobs/{public_id}')
def delete(public_id:str):
    try: return cm_write_service.delete(public_id)
    except KeyError as exc: raise HTTPException(404,'Job not found') from exc
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc

@router.get('/jobs/{public_id}/results',response_model=CmWriteResultListResponse)
def results(public_id:str,cursor:int=Query(0,ge=0),limit:int=Query(200,ge=1,le=1000)):
    try: return CmWriteResultListResponse(**cm_write_service.list_results(public_id,cursor,limit))
    except KeyError as exc: raise HTTPException(404,'Job not found') from exc
