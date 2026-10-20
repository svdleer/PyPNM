from __future__ import annotations

from pydantic import BaseModel, Field


class CmSingleResetRequest(BaseModel):
    mac: str = Field(min_length=1, max_length=32)
    confirmation_clicks: list[str] = Field(min_length=3, max_length=3)
    requested_by: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=128)


class CmSingleResetResponse(BaseModel):
    status: str = "success"
    mac: str
    target_ip: str
    reset_sent: bool = True
    message: str
