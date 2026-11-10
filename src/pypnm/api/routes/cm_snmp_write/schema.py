from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


SUPPORTED_WRITE_TYPES = ("i", "s", "x", "u", "c", "g", "t", "a")


class CmWriteOperation(BaseModel):
    oid: str = Field(min_length=1, max_length=256)
    value: Any
    type: str = Field(default="i", min_length=1, max_length=2)
    delay: float = Field(default=0, ge=0, le=300)


class CmWritePlanRequest(BaseModel):
    scope: dict[str, Any]
    operations: list[CmWriteOperation] = Field(min_length=1, max_length=32)
    requested_by: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)
    delay_seconds: int = Field(default=0, ge=0, le=86400)
    confirmation_password: str = Field(min_length=1, max_length=256)


class CmWriteStartRequest(BaseModel):
    confirmation_password: str = Field(min_length=1, max_length=256)
    max_concurrency: int = Field(default=5, ge=1, le=10)


class CmWriteJob(BaseModel):
    public_id: str
    status: str
    scope_type: str | None = None
    targets_total: int = 0
    operations_total: int = 0
    operations_succeeded: int = 0
    operations_failed: int = 0
    operations_pending: int = 0
    scheduled_start: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    requested_by: str | None = None
    error_text: str | None = None


class CmWriteJobResponse(BaseModel):
    status: str = "success"
    job: CmWriteJob


class CmWriteJobListResponse(BaseModel):
    status: str = "success"
    jobs: list[CmWriteJob] = Field(default_factory=list)


class CmWriteResult(BaseModel):
    id: int
    mac: str
    modem_ip: str | None = None
    cmts: str | None = None
    operation_index: int
    oid: str
    type: str
    value: Any = None
    state: str = "planned"
    error_text: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None


class CmWriteResultListResponse(BaseModel):
    status: str = "success"
    results: list[CmWriteResult] = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False
