# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

from pydantic import BaseModel, Field

from pypnm.api.routes.common.classes.common_endpoint_classes.common_req_resp import (
    CommonResponse,
)


class EventLogEntry(BaseModel):
    """
    Represents a single DOCSIS docsDevEventEntry row from the event log.

    This corresponds to `DocsDevEventEntry` in the DOCS-IF-MIB and captures
    the first/last occurrence timestamps, duplicate count, severity level,
    event identifier, and human-readable description.
    """

    docsDevEvFirstTime: str = Field(
        description=(
            "Value of docsDevDateTime when this log entry was first created. "
            "Represents the timestamp of the first occurrence of this event."
        )
    )
    docsDevEvLastTime: str = Field(
        description=(
            "Value of docsDevDateTime when the most recent instance of this event "
            "was recorded. If only one instance occurred, this matches docsDevEvFirstTime."
        )
    )
    docsDevEvCounts: int = Field(
        description=(
            "Number of consecutive identical event instances represented by this entry. "
            "Starts at 1 when the row is created and increments for each subsequent duplicate event."
        )
    )
    docsDevEvLevel: int = Field(
        description=(
            "Event priority level as defined by the vendor. Ordered from most to least serious: "
            "1=emergency, 2=alert, 3=critical, 4=error, 5=warning, 6=notice, 7=information, 8=debug. "
            "During normal operation, no event more critical than notice(6) should be generated."
        )
    )
    docsDevEvId: int = Field(
        description=(
            "Unsigned event identifier that uniquely identifies the type of event for this product. "
            "Implementations are strongly encouraged to follow the CableLabs DOCSIS OSSI enumerations."
        )
    )
    docsDevEvText: str = Field(
        description=(
            "Human-readable description of the event, including all relevant context "
            "(e.g., interface identifiers, parameters, and additional diagnostic details)."
        )
    )


class EventLogResponse(CommonResponse):
    """
    Response model for returning the results of a DOCSIS docsDevEventTable query.

    Attributes:
        status (str): High-level request status (inherited from CommonResponse).
        logs (List[EventLogEntry]): Parsed docsDevEventEntry rows representing
            network and device events useful for fault isolation and troubleshooting.
    """

    logs: list[EventLogEntry]
