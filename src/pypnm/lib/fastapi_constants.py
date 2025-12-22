# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

from typing import Any, cast

from pypnm.lib.types import HttpRtnCode

FAST_API_RESPONSE: dict[int | str, dict[str, Any]] = {
    cast(HttpRtnCode, 200): {
        "description": "JSON payload, downloadable archive, or raw binary content, depending on endpoint and request.output.type",
        "content": {
            "application/json": {},
            "application/zip": {},
            "application/octet-stream": {},
        },
    },
    cast(HttpRtnCode, 201): {
        "description": "Resource successfully created (for example, an uploaded or registered file)",
    },
    cast(HttpRtnCode, 400): {
        "description": "Bad request (invalid parameters or unsupported operation)",
    },
    cast(HttpRtnCode, 404): {
        "description": "Resource not found (for example, missing transaction or file reference)",
    },
    cast(HttpRtnCode, 413): {
        "description": "Payload too large (uploaded file exceeds configured size limits)",
    },
    cast(HttpRtnCode, 415): {
        "description": "Unsupported media type (content-type not accepted for this endpoint)",
    },
    cast(HttpRtnCode, 422): {
        "description": "Request body validation error (Pydantic/FastAPI validation failure)",
    },
    cast(HttpRtnCode, 500): {
        "description": "Server error",
    },
}
