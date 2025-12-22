## Agent Review Bundle Summary
- Goal: Update commit message tracking rules and include recent bulk-walk troubleshooting changes.
- Changes: Clarify commit message tracking/formatting rules; retain bulk-walk handling updates and tests already in scope.
- Files: AGENTS.md, CODING_AGENTS.md, src/pypnm/docsis/cm_snmp_operation.py, src/pypnm/snmp/snmp_v2c.py, src/pypnm/snmp/snmp_v3.py, tests/test_snmp_v2c_bulk_walk.py, tools/release/release.py
- Tests: Not run (no new test execution in this step).
- Notes: Review bundle excludes its own contents.

# FILE: AGENTS.md
# AGENTS.md

This file provides guidance for coding agents working in this repository.
Keep it short, accurate, and updated when workflows change.

## Agent Permissions

<environment_context>
    <sandbox_mode>danger-full-access</sandbox_mode>
    <network_access>enabled</network_access>
    <!-- Access is governed by this file and explicit user approval -->
</environment_context>

## Project Basics

- Language: Python (3.10+)
- This repo is NOT greenfield; extend existing code and patterns.
- Build/test entry points are defined in `pyproject.toml`, `Makefile`, or `scripts/`.
- Read `README.md` first for setup and usage.
- Type checking is strict; avoid `Any` and generic container types.
- Ruff compliance is required (do not auto-format unless explicitly requested).

## Agent Constraints

- General workflow:
  - Make minimal diffs; avoid formatting churn.
  - Preserve whitespace/alignment in existing files (no auto-reflow).
  - Do not add broad refactors unless explicitly requested.
  - Provide an end-of-run Agent Review Bundle summary: goal, changes, files, tests, notes.
- Typing and API style:
  - Strict typing everywhere; avoid `Dict`/`List`/`Tuple`/`Union` and avoid `Any`.
  - Prefer built-in generics (`dict[str, int]`, `list[str]`) and `A | B` rather than `Union`.
  - Prefer Pydantic `BaseModel` over dict returns for public interfaces.
  - `BaseModel` fields must be one-line `Field(...)` declarations with descriptions.
  - Prefer `match/case` over long if/else chains.
  - No one-line if statements (E701 compliance).
  - Avoid 3+ nested loops; 2 nested loops discouraged unless necessary.
- Code structure and documentation:
  - Prefer classes/static methods; minimize standalone global functions.
  - Public methods must have detailed docstrings; private methods minimal.
  - Keep code self-documented; avoid method-level debug logging.
  - Logger pattern in classes: `self.logger = logging.getLogger(f"{self.__class__.__name__}")`.
- Release hygiene / headers:
  - Any touched code files must have SPDX copyright year updated per Repo Hygiene rules (single year or range).
  - Do not add SPDX headers to Markdown files.
  - Remove SPDX lines embedded inside Markdown code blocks if encountered (especially SQL appendices).
- Docs / Markdown rules (MkDocs + GitHub compatible):
  - No emojis in docs.
  - No horizontal rules (`---`) in Markdown.
  - Keep tables ~132 characters wide when possible.
  - Use placeholders consistently in examples:
    - MAC: `aa:bb:cc:dd:ee:ff`
    - IP: `192.168.0.100`
    - system_description JSON: `{"HW_REV":"1.0","VENDOR":"LANCity","BOOTR":"NONE","SW_REV":"1.0.0","MODEL":"LCPET-3"}`
  - For code file links in docs: use HTTP GitHub links; relative links only for other Markdown files.
  - Always include a downloadable link at the end of any Markdown you generate (when generating Markdown as an artifact in chat; for repo docs, follow repo conventions).
- Shell scripts:
  - Proper indentation.
  - Emojis allowed only in `install.sh` and `pypnm-cmts` CLI output; do not use emojis elsewhere.
- Testing expectations:
  - Run at least: `python3 -m compileall src`, `ruff check src`, `ruff format --check .`, `pytest -q`.
  - If an integration test is optional/gated (for example Postgres DSN), note skips explicitly in the summary.

## External Consumers (Compatibility Contract)

- PyPNM is the authoritative engine and is consumed by downstream repos (example: PyPNM-CMTS).
- Preserve public API stability unless the user explicitly approves breaking changes.
- Do not embed downstream app concerns into PyPNM (keep PyPNM reusable and transport-agnostic).
- If a change affects downstream repos, call it out explicitly before making it.

## Repo Conventions (PyPNM)

- Persistence is filesystem-based artifacts plus metadata persistence per the DB backend design:
  - Binaries and derived artifacts remain on disk under `.data/` roots.
  - Transaction/group/operation metadata is DB-backed (SQLite or Postgres) per `docs/design/db/`.
- DB backend selection is owned by PyPNM at install time (no runtime “auto switching”).
- SQLite is intended for single-writer deployments (standalone/lab/demo).
- Postgres is recommended for multi-worker / multi-process deployments.

## Documentation

- Docs must follow the existing repo docs layout and conventions.
- Update docs alongside code changes (choose the correct location by inspecting the existing docs tree; do not invent parallel structures).
- Do not modify `mkdocs.yml` or navigation unless explicitly required by the task.
- Markdown must render correctly in both MkDocs and GitHub.
- No emojis in documentation.
- Use generic placeholders:
  - MAC: `aa:bb:cc:dd:ee:ff`
  - IP: `192.168.0.100`
- Emojis are allowed only in `install.sh`; they are prohibited everywhere else.
- When adding new terms or acronyms, update `docs/definition/index.md` and keep entries in alphabetical order.
- After completing a task, create a single “agent review” file that concatenates the full contents of all files changed in that task (path and naming should follow existing repo practice).
- Always regenerate the agent review bundle after any subsequent edits so it reflects every changed file.
- When an error is fixed, add or update a FAQ entry with the error and resolution, and add a TODO entry noting the FAQ update requirement.

### Reuse Index

- Agents MUST consult the existing reuse / symbol index under `tools/agent-review/` (if present) before introducing new:
  - types, validators, ID formats, storage conventions, persistence adapters, or config namespaces
- Any deviation requires an explicit gap justification and user approval.

## DB Backend Migration (Locked Decisions)

Agents working on the DB backend refactor MUST follow the locked decisions recorded in the design docs (see `docs/design/db/`):

- PyPNM owns persistence, schema initialization, and DB APIs.
- Install-time backend selection via `install.sh` flags + interactive default to SQLite.
- Postgres secrets via env var overrides (no plaintext requirement in tracked JSON).
- Idempotent schema apply using shipped DDL assets + seeding `UNKNOWN` sysDescr + default artifact store(s).
- SQLite for single-writer; Postgres recommended for multi-worker / multi-process (especially downstream orchestration use).
- Paths stored in DB are portable (app-root relative), resolved at runtime.
- CI validates SQLite (required) and Postgres (service container, recommended as required).
- JSON ledger persistence is deprecated and removed from runtime paths (optional offline migrator only).

## Configuration

- `system.json` is the single source of truth.
- New configuration namespaces must be implemented as Pydantic BaseModels.
- BaseModels must use one-line `Field(..., description="...")`.
- Avoid generic `str` for semantic identifiers or paths in public models and APIs; use an existing semantic type or add a new alias in `src/pypnm/lib/types.py`.
- When working with MAC or inet strings, validate using `MacAddress()` or `Inet()` instead of assuming `str(...)` formatting is valid.
- Request override defaults: missing or null means use `system.json` defaults; blank strings are invalid.

## Timestamp Conventions

- All stored timestamps are epoch seconds.
- Convert to ISO-8601 only at display or external response boundaries.

## Coding Guidelines (Strict)

- No generic container imports (`Dict`, `List`, `Tuple`, `Union`).
  Use built-in types and `|`.
- Avoid `Any` unless unavoidable; isolate and justify its usage.
- Every function argument must be annotated.
- Avoid `None` returns; prefer empty values unless `None` is semantically required.
- Avoid magic numbers; use named constants.
- Prefer `BaseModel` over raw dicts for public/stateful structures (state, configuration, persistence records).
- dicts are allowed only for short-lived internal glue logic.
- Prefer classes with static methods over standalone functions.
- Public methods MUST have detailed docstrings.
- Private methods may have minimal docstrings.
- Avoid method-level debug logs.
- Do not add Ruff ignores (`# noqa`, `# ruff: noqa`). If an ignore is needed, ask for permission first.
- Logging pattern in classes:

  ```python
  self.logger = logging.getLogger(f"{self.__class__.__name__}")
  ```

- Prefer `match/case` over long if/else chains.
- No code should contain 3+ nested loops. 2 nested loops are discouraged unless necessary.
- No one-line if statements (E701).
- If `STATUS` is used as a return type, return `STATUS_OK` or `STATUS_NOK` for readability.
- Preserve all existing whitespace and alignment.
- Never auto-format or re-align code.
- Do not enforce snake_case; keep existing naming conventions as-is.

## FastAPI Guidelines (PyPNM)

- Router files must be lean:
  - `router.py` contains routing glue only (APIRouter configuration, endpoint registration, HTTP status translation).
  - No business logic in `router.py`. Business logic must live in `service.py` for that route group (same folder) or a shared service module if reused.
- All request/response bodies must be Pydantic BaseModels.
- Prefer POST for payload submission and endpoint contracts (PyPNM default).
  - Allow GET only where already present or clearly appropriate (health, readiness, version, status).
- Reuse shared models under the existing `src/pypnm/api/common/` structure (inspect current tree before adding anything new).
- Do not block request paths with `time.sleep()`.

## Tests (Mandatory)

- Every phase deliverable MUST include pytest coverage for new or changed behavior.
- Do not claim a phase item is complete unless pytest has been added and executed (or a concrete blocker is documented).
- Tests must remain hermetic: no live CMTS/cable modem dependencies.

## Burndown Governance

- Agents MUST consult the current burndown and DB design docs before implementing work.
- Agents MUST NOT update burndown checkmarks unless explicitly instructed by the user.
- Code written does not imply progress accepted.

## Workflow Rules

- When the user says “train”, read code silently until told otherwise.
- Do not assume missing context; ask.
- Keep changes minimal and scoped.
- Do not refactor unrelated code.
- Avoid destructive commands unless explicitly requested.
- Do not print file contents into chat unless the user explicitly requests it.
- Keep a brief summary of user prompts after any request for a commit message and track changes since the most recent commit message request.
- When asked for a commit message, respond with the specified format, keep it succinct, and include all changes since the last commit message request.
- Default response content should be a summary, changed file list, commands run, and the review bundle path.
- Always end tasks with an agent review bundle containing the full contents of all files touched in the task.
- Agent review bundles must start with the standard summary template block below (before any `# FILE:` sections).
- If a review bundle exceeds 3000 lines, split it into multiple bundles without splitting files. Use a part naming convention like `name.part-1.review.md`, `name.part-2.review.md`, and repeat the summary block at the top of each part.
- When the user says `CAT_FILES`, create a single bundle file containing the full contents of every file touched in the task, each preceded by `# FILE: <path>`, and provide the `cat` command for the bundle.

### Commit Message Format

- One line summary (max 50 characters)
- Detailed description lines (max 72 characters per line); every line after the first must start with `-`

### Agent Review Bundle Summary Template (Standard)

Use this block at the very top of every `*.review.md` bundle (before any `# FILE:` sections).

## Agent Review Bundle Summary
- Goal:
- Changes:
- Files:
- Tests:
- Notes:

## Repo Hygiene

- License is Apache-2.0; keep SPDX headers and `NOTICE`.
- For any modified or newly created file, update the SPDX header year to 2026.
- If a file already has a SPDX year and the year has changed, update it as a range (example: 2025 -> 2025-2026).
- Keep `tools/` organized by category.
- Do not add files directly under `tools/` root.

## Agent Self-Checks

Before responding:

- Re-read this file and `README.md`.
- Confirm pytest coverage exists or is explicitly blocked.
- Confirm pytest and ruff output have no deprecation warnings (treat as failures).
- Confirm changes align to the current phase and do not leak scope.
- Confirm formatting and alignment are preserved.

## Training

When the user requests "train", read the following sources:

- `AGENTS.md`
- `docs/design/db/` (all files)
- `src/pypnm/lib/` (DB/persistence + config helpers)
- `src/pypnm/api/` (routing/service patterns, where applicable)
- `tools/agent-review/` (all files, if present)

# FILE: CODING_AGENTS.md
# General-Purpose AI Coding Guide

This document provides a generic coding guide for AI contributors. It focuses on code style,
reuse, and maintainability.

## Core Principles

- Reuse before adding: prefer existing types, helpers, models, and utilities.
- Keep diffs minimal and focused; avoid formatting churn.
- Preserve existing naming, alignment, and whitespace patterns.
- Favor clarity and explicit typing over clever shortcuts.
- Review this document before making any changes.
  This is a generic guide and does not replace `AGENTS.md`.

## Reuse-First Checklist

Before introducing new types, validators, formats, or storage conventions:

- Search for similar helpers in `src/pypnm/lib/` and `src/pypnm/api/`.
- Check `tools/agent-review/` for any reuse or symbol index guidance.
- Prefer existing semantic aliases over raw `str` identifiers.
- Prefer existing constants over inline values.
- Prefer existing Pydantic models for public data structures.
- Refer to shared utilities and helpers before creating new classes.

## Common Locations To Consult

- Types and semantic aliases: `src/pypnm/lib/types.py`
- Constants: `src/pypnm/lib/constants.py`
- Validators and parsing helpers: `src/pypnm/lib/`
- Config models and defaults: `src/pypnm/config/`
- Shared API models and schemas: `src/pypnm/api/` (including `src/pypnm/api/common/`)

## Coding Style (General)

- Use built-in generics (`list[str]`, `dict[str, int]`) and `A | B` unions.
- Avoid `Any` unless unavoidable; isolate and justify its usage.
- Annotate all function arguments and return types.
- Prefer classes or static methods over standalone functions.
- Use Pydantic `BaseModel` for public interfaces instead of raw dicts.
- Keep public method docstrings detailed; private method docstrings minimal.

## Workflow Guidance

- Validate changes with repository test entry points.
- When adding new behavior, include tests covering the change.
- New classes must have pytest coverage at a minimum for IPC and system calls.
- Avoid broad refactors unless explicitly requested.
- Keep a brief summary of user prompts after any request for a commit message and track changes since the most recent commit message request.
- When asked for a commit message, respond with the specified format, keep it succinct, and include all changes since the last commit message request.

### Commit Message Format

- One line summary (max 50 characters)
- Detailed description lines (max 72 characters per line); every line after the first must start with `-`

## Agent Constraints

- General workflow:
  - Make minimal diffs; avoid formatting churn.
  - Preserve whitespace/alignment in existing files (no auto-reflow).
  - Do not add broad refactors unless explicitly requested.
  - Provide an end-of-run Agent Review Bundle summary: goal, changes, files, tests, notes.
- Typing and API style:
  - Strict typing everywhere; avoid `Dict`/`List`/`Tuple`/`Union` and avoid `Any`.
  - Prefer built-in generics (`dict[str, int]`, `list[str]`) and `A | B` rather than `Union`.
  - Prefer Pydantic `BaseModel` over dict returns for public interfaces.
  - `BaseModel` fields must be one-line `Field(...)` declarations with descriptions.
  - Avoid generic returns; every method must have an explicit return type annotation.
  - Every method argument must have an explicit type annotation.
  - Public/shared method types must be defined in `src/pypnm/lib/types.py`.
  - Only define local types in a module when the type is strictly private and not reused.
  - Common folder methods must use types defined in `src/pypnm/lib/types.py`.
- Prefer `match/case` over long if/else chains.
- No one-line if statements (E701 compliance).
- Avoid 3+ nested loops; 2 nested loops discouraged unless necessary.
- If `STATUS` is used as a return type, return `STATUS_OK` or `STATUS_NOK` for readability.
- Code structure and documentation:
  - Prefer classes/static methods; minimize standalone global functions.
  - Public methods must have detailed docstrings; private methods minimal.
  - Keep code self-documented; avoid method-level debug logging.
  - Logger pattern in classes: `self.logger = logging.getLogger(f"{self.__class__.__name__}")`.
- Release hygiene / headers:
  - Code files must include `SPDX-License-Identifier: Apache-2.0`.
  - Copyright lines must include only the year or year range (no author names).
  - Any touched code files must have SPDX copyright year updated per Repo Hygiene rules (single year or range).
  - Do not add SPDX headers to Markdown files.
  - Remove SPDX lines embedded inside Markdown code blocks if encountered (especially SQL appendices).
- Docs / Markdown rules (MkDocs + GitHub compatible):
  - No emojis in docs.
  - No horizontal rules (`---`) in Markdown.
  - Keep tables ~132 characters wide when possible.
  - Use placeholders consistently in examples:
    - MAC: `aa:bb:cc:dd:ee:ff`
    - IP: `192.168.0.100`
    - system_description JSON: `{"HW_REV":"1.0","VENDOR":"LANCity","BOOTR":"NONE","SW_REV":"1.0.0","MODEL":"LCPET-3"}`
  - For code file links in docs: use HTTP GitHub links; relative links only for other Markdown files.
  - Always include a downloadable link at the end of any Markdown you generate (when generating Markdown as an artifact in chat; for repo docs, follow repo conventions).
- Shell scripts:
  - Proper indentation.
  - Emojis allowed only in `install.sh` and `pypnm-cmts` CLI output; do not use emojis elsewhere.
- Testing expectations:
  - Run at least: `python3 -m compileall src`, `ruff check src`, `ruff format --check .`, `pytest -q`.
  - If an integration test is optional/gated (for example Postgres DSN), note skips explicitly in the summary.

## Pytest Guidance (PyPNM Pattern)

- Place new tests under `tests/` with `test_*.py` naming.
- Prefer small, focused unit tests that mirror the existing test style.
- Use fixtures for shared data (see current `tests/` patterns).
- Prefer module-level test functions over new class wrappers unless an existing test uses classes.
- Reuse `tests/files/` for binary fixtures and sample data.
- Favor hermetic tests: no live devices, no external services.
- When testing IPC or system calls, isolate behavior with fakes/mocks and assert edge cases.
- Keep tests aligned with existing patterns in similar modules before introducing new structures.
  Start by locating a similar test file and mirror its structure.

## Notes

- This document is intentionally generic. Use `AGENTS.md` for this repository’s
  authoritative rules and workflow constraints.

# FILE: src/pypnm/docsis/cm_snmp_operation.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, IntEnum
from typing import Any, cast

from pysnmp.proto.rfc1902 import Gauge32, Integer32, OctetString

from pypnm.config.pnm_config_manager import SystemConfigSettings
from pypnm.docsis.data_type.ClabsDocsisVersion import ClabsDocsisVersion
from pypnm.docsis.data_type.DocsDevEventEntry import DocsDevEventEntry
from pypnm.docsis.data_type.DocsFddCmFddCapabilities import (
    DocsFddCmFddBandEdgeCapabilities,
)
from pypnm.docsis.data_type.DocsFddCmFddSystemCfgState import DocsFddCmFddSystemCfgState
from pypnm.docsis.data_type.DocsIf31CmDsOfdmChanEntry import (
    DocsIf31CmDsOfdmChanChannelEntry,
    DocsIf31CmDsOfdmChanEntry,
)
from pypnm.docsis.data_type.DocsIf31CmDsOfdmProfileStatsEntry import (
    DocsIf31CmDsOfdmProfileStatsEntry,
)
from pypnm.docsis.data_type.DocsIf31CmSystemCfgState import (
    DocsIf31CmSystemCfgDiplexState,
)
from pypnm.docsis.data_type.DocsIf31CmUsOfdmaChanEntry import DocsIf31CmUsOfdmaChanEntry
from pypnm.docsis.data_type.DocsIfDownstreamChannel import DocsIfDownstreamChannelEntry
from pypnm.docsis.data_type.DocsIfDownstreamChannelCwErrorRate import (
    DocsIfDownstreamChannelCwErrorRate,
    DocsIfDownstreamCwErrorRateEntry,
)
from pypnm.docsis.data_type.DocsIfSignalQualityEntry import DocsIfSignalQuality
from pypnm.docsis.data_type.DocsIfUpstreamChannelEntry import DocsIfUpstreamChannelEntry
from pypnm.docsis.data_type.DsCmConstDisplay import CmDsConstellationDisplayConst
from pypnm.docsis.data_type.enums import MeasStatusType
from pypnm.docsis.data_type.InterfaceStats import InterfaceStats
from pypnm.docsis.data_type.OfdmProfiles import OfdmProfiles
from pypnm.docsis.data_type.pnm.DocsIf3CmSpectrumAnalysisEntry import (
    DocsIf3CmSpectrumAnalysisEntry,
)
from pypnm.docsis.data_type.pnm.DocsPnmCmDsConstDispMeasEntry import (
    DocsPnmCmDsConstDispMeasEntry,
)
from pypnm.docsis.data_type.pnm.DocsPnmCmDsHistEntry import DocsPnmCmDsHistEntry
from pypnm.docsis.data_type.pnm.DocsPnmCmDsOfdmFecEntry import DocsPnmCmDsOfdmFecEntry
from pypnm.docsis.data_type.pnm.DocsPnmCmDsOfdmMerMarEntry import (
    DocsPnmCmDsOfdmMerMarEntry,
)
from pypnm.docsis.data_type.pnm.DocsPnmCmDsOfdmModProfEntry import (
    DocsPnmCmDsOfdmModProfEntry,
)
from pypnm.docsis.data_type.pnm.DocsPnmCmDsOfdmRxMerEntry import (
    DocsPnmCmDsOfdmRxMerEntry,
)
from pypnm.docsis.data_type.pnm.DocsPnmCmOfdmChanEstCoefEntry import (
    DocsPnmCmOfdmChanEstCoefEntry,
)
from pypnm.docsis.data_type.pnm.DocsPnmCmUsPreEqEntry import DocsPnmCmUsPreEqEntry
from pypnm.docsis.data_type.sysDescr import SystemDescriptor
from pypnm.docsis.lib.pnm_bulk_data import DocsPnmBulkDataGroup
from pypnm.lib.constants import DEFAULT_SPECTRUM_ANALYZER_INDICES
from pypnm.lib.format_string import Format
from pypnm.lib.inet import Inet
from pypnm.lib.inet_utils import InetGenerate
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import ChannelId, EntryIndex, FrequencyHz, InterfaceIndex
from pypnm.lib.utils import Generate
from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import (
    DocsIf3CmSpectrumAnalysisCtrlCmd,
    SpectrumRetrievalType,
)
from pypnm.pnm.data_type.pnm_test_types import DocsPnmCmCtlTest
from pypnm.snmp.compiled_oids import COMPILED_OIDS
from pypnm.snmp.modules import DocsisIfType, DocsPnmBulkUploadControl
from pypnm.snmp.snmp_v2c import Snmp_v2c
from pypnm.snmp.snmp_v3 import Snmp_v3


class DocsPnmBulkFileUploadStatus(Enum):
    """Represents the upload status of a DOCSIS PNM bulk data file."""
    OTHER                   = 1
    AVAILABLE_FOR_UPLOAD    = 2
    UPLOAD_IN_PROGRESS      = 3
    UPLOAD_COMPLETED        = 4
    UPLOAD_PENDING          = 5
    UPLOAD_CANCELLED        = 6
    ERROR                   = 7

    def describe(self) -> str:
        """Returns a human-readable description of the enum value."""
        return {
            self.OTHER: "Other: unspecified condition",
            self.AVAILABLE_FOR_UPLOAD: "Available: ready for upload",
            self.UPLOAD_IN_PROGRESS: "In progress: upload ongoing",
            self.UPLOAD_COMPLETED: "Completed: upload successful",
            self.UPLOAD_PENDING: "Pending: blocked until conditions clear",
            self.UPLOAD_CANCELLED: "Cancelled: upload was stopped",
            self.ERROR: "Error: upload failed",
        }.get(self, "Unknown status")

    def to_dict(self) -> dict:
        """Serializes the status for API or JSON usage."""
        return {"name": self.name, "value": self.value, "description": self.describe()}

    def __str__(self) -> str:
        return super().__str__()

class DocsPnmCmCtlStatus(Enum):
    """
    Enum representing the overall status of the PNM test platform.

    Based on the SNMP object `docsPnmCmCtlStatus`, this enum is used to manage
    test initiation constraints on the Cable Modem (CM).
    """

    OTHER               = 1
    READY               = 2
    TEST_IN_PROGRESS    = 3
    TEMP_REJECT         = 4
    SNMP_ERROR          = 255

    def __str__(self) -> str:
        return self.name.lower()

class FecSummaryType(Enum):
    """
    Enum for FEC Summary Type used in DOCSIS PNM SNMP operations.
    """
    TEN_MIN             = 2
    TWENTY_FOUR_HOUR    = 3

    @classmethod
    def choices(cls) -> dict[str, int]:
        ''' Returns a dictionary [key,value] of enum names and their corresponding values. '''
        return {e.name: e.value for e in cls}

    @classmethod
    def from_value(cls, value: int) -> FecSummaryType:
        try:
            return cls(value)
        except ValueError as err:
            raise ValueError(f"Invalid FEC Summary Type value: {value}") from err

class CmSnmpOperation:
    """
    Cable Modem SNMP Operation Handler.

    This class provides methods to perform SNMP operations
    (GET, WALK, etc.) specifically for Cable Modems.

    Attributes:
        _inet (str): IP address of the Cable Modem.
        _community (str): SNMP community string used for authentication.
        _port (int): SNMP port (default: 161).
        _snmp (Snmp_v2c): SNMP client instance for communication.
        logger (logging.Logger): Logger instance for this class.
    """

    class SnmpVersion(IntEnum):
        _SNMPv2C = 0
        _SNMPv3  = 1

    def __init__(self, inet: Inet, write_community: str, port: int = Snmp_v2c.SNMP_PORT) -> None:
        """
        Initialize a CmSnmpOperation instance.

        Args:
            inet (str): IP address of the Cable Modem.
            write_community (str): SNMP community string (usually 'private' for read/write access).
            port (int, optional): SNMP port number. Defaults to standard SNMP port 161.

        """
        self.logger = logging.getLogger(self.__class__.__name__)

        if not isinstance(inet, Inet):
            self.logger.error(f'CmSnmpOperation() inet is of an Invalid Type: {type(inet)} , expecting Inet')
            exit(1)

        self._inet:Inet = inet
        self._community = write_community
        self._port = port
        self._snmp = self.__load_snmp_version()

    def __load_snmp_version(self) -> Snmp_v2c | Snmp_v3:
        """
        Select and instantiate the appropriate SNMP client.

        Precedence:
        1) If SNMPv3 is explicitly enabled and parameters are valid -> return Snmp_v3
        2) Else if SNMPv2c is enabled -> return Snmp_v2c
        3) Else -> error
        """

        if SystemConfigSettings.snmp_v3_enable():
            '''
            self.logger.debug("SNMPv3 enabled in configuration; validating parameters...")
            try:
                p = PnmConfigManager.get_snmp_v3_params()
            except Exception as e:
                self.logger.error(f"Failed to load SNMPv3 parameters: {e}. Falling back to SNMPv2c.")
                p = None

            # Minimal required fields for a usable v3 session
            required = ("user", "auth_key", "priv_key", "auth_protocol", "priv_protocol")
            if p and all(p.get(k) for k in required):
                self.logger.debug("Using SNMPv3")
                return Snmp_v3(
                    host=self._inet,
                    user=p["user"],
                    auth_key=p["auth_key"],
                    priv_key=p["priv_key"],
                    auth_protocol=p["auth_protocol"],
                    priv_protocol=p["priv_protocol"],
                    port=self._port,
                )
            else:
                self.logger.warning(
                    "SNMPv3 is enabled but parameters are incomplete or invalid; "
                    "falling back to SNMPv2c."
                )
            '''
            # Keep the implementation stubbed for now.
            # Force an explicit failure instead of silently falling back.
            raise NotImplementedError(
                "SNMPv3 is enabled in configuration, but the SNMPv3 client is not implemented yet. "
                "Disable SNMPv3 to use SNMPv2c.")

        if SystemConfigSettings.snmp_enable():
            self.logger.debug("Using SNMPv2c")
            return Snmp_v2c(host=self._inet, community=self._community, port=self._port)

        # Neither protocol is usable
        msg = "No SNMP protocol enabled or properly configured (v3 disabled/invalid and v2c disabled)."
        self.logger.error(msg)
        raise ValueError(msg)

    async def _get_value(self, oid_suffix: str, value_type: type | str = str) -> str | bytes | int | None:
        """
        Retrieves a value from SNMP for the given OID suffix, processes the value based on the expected type,
        and handles any error cases that may arise during the process.

        Parameters:
        - oid_suffix (str): The suffix of the OID to query.
        - value_type (type or str): The type to which the value should be converted. Defaults to `str`.

        Returns:
        - Optional[Union[str, bytes, int]]: The value retrieved from SNMP, converted to the specified type,
          or `None` if there was an error or no value could be obtained.
        """
        result = await self._snmp.get(f"{oid_suffix}.0")

        if result is None:
            logging.warning(f"Failed to get value for {oid_suffix}")
            return None

        val = Snmp_v2c.snmp_get_result_value(result)[0]
        logging.debug(f"get_value() -> Val:{val}")

        # Check if the result is an error message, and return None if it is
        if isinstance(val, str) and "No Such Instance currently exists at this OID" in val:
            logging.warning(f"SNMP error for {oid_suffix}: {val}")
            return None

        # Handle string and bytes conversions explicitly
        if value_type is str:
            if isinstance(val, bytes):  # if val is bytes, decode it
                return val.decode('utf-8', errors='ignore')  # or replace with appropriate encoding
            return str(val)

        if value_type is bytes:
            if isinstance(val, str):  # if val is a string, convert to bytes
                # Remove any '0x' prefix or spaces before converting
                val = val.strip().lower()
                if val.startswith('0x'):
                    val = val[2:]  # Remove '0x' prefix

                # Ensure the string is a valid hex format
                try:
                    return bytes.fromhex(val)  # convert the cleaned hex string to bytes
                except ValueError as e:
                    logging.error(f"Invalid hex string: {val}. Error: {e}")
                    return None
            return val  # assuming it's already in bytes

        # Default case (int conversion)
        try:
            return value_type(val)
        except ValueError as e:
            logging.error(f"Failed to convert value for {oid_suffix}: {val}. Error: {e}")
            return None

    ######################
    # SNMP Get Operation #
    ######################

    def getWriteCommunity(self) -> str:
        return self._community

    async def getIfTypeIndex(self, doc_if_type: DocsisIfType) -> list[InterfaceIndex]:
        """
        Retrieve interface indexes that match the specified DOCSIS IANA ifType.

        Args:
            doc_if_type (DocsisIfType): The DOCSIS interface type to filter by.

        Returns:
            List[int]: A list of interface indexes matching the given ifType.
        """
        self.logger.debug(f"Starting getIfTypeIndex for ifType: {doc_if_type}")

        indexes: list[int] = []

        # Perform SNMP walk
        results = await self._snmp.walk("ifType")

        if not results:
            self.logger.warning("No results found during SNMP walk for ifType.")
            return indexes

        # Iterate through results and filter by the specified DOCSIS interface type
        ifType_name = doc_if_type.name
        ifType_value = doc_if_type.value

        try:
            for result in results:
                # Compare ifType value with the result value
                if ifType_value == int(result[1]):
                    self.logger.debug(f"ifType-Name: ({ifType_name}) -> ifType-Value: ({ifType_value}) -> Found: {result}")

                    # Extract index using a helper method (ensure it returns a valid index)
                    index = Snmp_v2c.get_oid_index(str(result[0]))
                    if index is not None:
                        indexes.append(index)
                    else:
                        self.logger.warning(f"Invalid OID index for result: {result}")
        except Exception as e:
            self.logger.error(f"Error processing results: {e}")

        # Return the list of found indexes
        return indexes

    async def getSysDescr(self, timeout: int | None = None, retries: int | None = None) -> SystemDescriptor:
        """
        Retrieves and parses the sysDescr SNMP value into a SysDescr dataclass.

        Returns:
            SysDescr if successful, otherwise empty SysDescr.empty().
        """
        timeout = timeout if timeout is not None else self._snmp._timeout
        retries = retries if retries is not None else self._snmp._retries

        self.logger.debug(f"Retrieving sysDescr for {self._inet}, timeout: {timeout}, retries: {retries}")

        try:
            result = await self._snmp.get(f'{"sysDescr"}.0', timeout=timeout, retries=retries)
        except Exception as e:
            self.logger.error(f"Error occurred while retrieving sysDescr: {e}")
            return SystemDescriptor.empty()

        if not result:
            self.logger.warning("SNMP get failed or returned empty for sysDescr.")
            return SystemDescriptor.empty()

        self.logger.debug(f"SysDescr Results: {result} before get_result_value")
        values = Snmp_v2c.get_result_value(result)

        if not values:
            self.logger.warning("No sysDescr value parsed.")
            return SystemDescriptor.empty()

        if not result:
            self.logger.warning("SNMP get failed or returned empty for sysDescr.")
            return SystemDescriptor.empty()

        values = Snmp_v2c.get_result_value(result)

        if not values:
            self.logger.warning("No sysDescr value parsed.")
            return SystemDescriptor.empty()

        self.logger.debug(f"SysDescr: {values}")

        try:
            parsed = SystemDescriptor.parse(values)
            self.logger.debug(f"Successfully parsed sysDescr: {parsed}")
            return parsed

        except ValueError as e:
            self.logger.error(f"Failed to parse sysDescr: {values}. Error: {e}")
            return SystemDescriptor.empty()

    async def getDocsPnmBulkDataGroup(self) -> DocsPnmBulkDataGroup:
        """
        Retrieves the current DocsPnmBulkDataGroup SNMP configuration from the device.

        Returns:
            DocsPnmBulkDataGroup: A dataclass populated with SNMP values.
        """

        return DocsPnmBulkDataGroup(
            docsPnmBulkDestIpAddrType   =   await self._get_value("docsPnmBulkDestIpAddrType", int),
            docsPnmBulkDestIpAddr       =   InetGenerate.binary_to_inet(await self._get_value("docsPnmBulkDestIpAddr", bytes)),
            docsPnmBulkDestPath         =   await self._get_value("docsPnmBulkDestPath", str),
            docsPnmBulkUploadControl    =   await self._get_value("docsPnmBulkUploadControl", int)
        )

    async def getDocsPnmCmCtlStatus(self, max_retry:int=1) -> DocsPnmCmCtlStatus:
        """
        Fetches the current Docs PNM CmCtlStatus.

        This method retrieves the Docs PNM CmCtlStatus and retries up to a specified number of times
        if the response is not valid. The possible statuses are:
        - 1: other
        - 2: ready
        - 3: testInProgress
        - 4: tempReject

        Parameters:
        - max_retry (int, optional): The maximum number of retries to obtain the status (default is 1).

        Returns:
        - DocsPnmCmCtlStatus: The Docs PNM CmCtlStatus as an enum value. Possible values:
        - DocsPnmCmCtlStatus.OTHER
        - DocsPnmCmCtlStatus.READY
        - DocsPnmCmCtlStatus.TEST_IN_PROGRESS
        - DocsPnmCmCtlStatus.TEMP_REJECT

        If the status cannot be retrieved after the specified retries, the method will return `DocsPnmCmCtlStatus.TEMP_REJECT`.
        """
        count = 1
        while True:

            result = await self._snmp.get(f'{"docsPnmCmCtlStatus"}.0')

            if result is None:
                time.sleep(2)
                self.logger.warning(f"Not getting a proper docsPnmCmCtlStatus response, retrying: ({count} of {max_retry})")

                if count >= max_retry:
                    self.logger.error(f"Reached max retries: ({max_retry})")
                    return DocsPnmCmCtlStatus.TEMP_REJECT

                count += 1
                continue
            else:
                break

        if not result:
            self.logger.error(f'No results found for docsPnmCmCtlStatus: {DocsPnmCmCtlStatus.SNMP_ERROR}')
            return DocsPnmCmCtlStatus.SNMP_ERROR

        status_value = int(Snmp_v2c.snmp_get_result_value(result)[0])

        return DocsPnmCmCtlStatus(status_value)

    async def getIfPhysAddress(self, if_type: DocsisIfType = DocsisIfType.docsCableMaclayer) -> MacAddress:
        """
        Retrieve the physical (MAC) address of the specified interface type.
        Args:
            if_type (DocsisIfType): The DOCSIS interface type to query. Defaults to docsCableMaclayer.
        Returns:
            MacAddress: The MAC address of the interface.
        Raises:
            RuntimeError: If no interfaces are found or SNMP get fails.
            ValueError: If the retrieved MAC address is invalid.
        """
        self.logger.debug(f"Getting ifPhysAddress for ifType: {if_type.name}")

        if_indexes = await self.getIfTypeIndex(if_type)
        self.logger.debug(f"{if_type.name} -> {if_indexes}")
        if not if_indexes:
            raise RuntimeError(f"No interfaces found for {if_type.name}")

        idx = if_indexes[0]
        resp = await self._snmp.get(f"ifPhysAddress.{idx}")
        self.logger.debug(f"getIfPhysAddress() -> {resp}")
        if not resp:
            raise RuntimeError(f"SNMP get failed for ifPhysAddress.{idx}")

        # Prefer grabbing raw bytes directly from the varbind
        try:
            varbind = resp[0]
            value = varbind[1]  # should be OctetString
            if isinstance(value, (OctetString, bytes, bytearray)):
                mac_bytes = bytes(value)
            else:
                # Fallback: use helper and try to coerce
                raw = Snmp_v2c.snmp_get_result_value(resp)[0]
                if isinstance(raw, (bytes, bytearray)):
                    mac_bytes = bytes(raw)
                elif isinstance(raw, str):
                    s = raw.strip().lower()
                    if s.startswith("0x"):
                        s = s[2:]
                    s = s.replace(":", "").replace("-", "").replace(" ", "")
                    mac_bytes = bytes.fromhex(s)
                else:
                    raise ValueError(f"Unsupported ifPhysAddress type: {type(raw)}")
        except Exception as e:
            # Log and rethrow with context
            self.logger.error(f"Failed to parse ifPhysAddress.{idx}: {e}")
            raise

        if len(mac_bytes) != 6:
            raise ValueError(f"Invalid MAC length {len(mac_bytes)} from ifPhysAddress.{idx}")

        mac_hex = mac_bytes.hex()
        return MacAddress(mac_hex)

    async def getDocsIfCmDsScQamChanChannelIdIndex(self) -> list[InterfaceIndex]:
        """
        Retrieve the list of DOCSIS 3.0 downstream SC-QAM channel indices.

        Returns:
            List[int]: A list of SC-QAM channel indices present on the device.
        """
        try:
            return await self.getIfTypeIndex(DocsisIfType.docsCableDownstream)

        except Exception as e:
            self.logger.error(f"Failed to retrieve SC-QAM Indexes: {e}")
            return []

    async def getDocsIf31CmDsOfdmChannelIdIndex(self) -> list[InterfaceIndex]:
        """
        Retrieve the list of Docsis 3.1 downstream OFDM channel indices.

        Returns:
            List[int]: A list of channel indices present on the device.
        """
        return await self.getIfTypeIndex(DocsisIfType.docsOfdmDownstream)

    async def getDocsIf31CmDsOfdmChanPlcFreq(self) -> list[tuple[InterfaceIndex, FrequencyHz]]:
        """
        Retrieve the PLC frequencies of DOCSIS 3.1 downstream OFDM channels.

        Returns:
            List[Tuple[int, int]]: A list of tuples where each tuple contains:
                - the index (int) of the OFDM channel
                - the PLC frequency (int, in Hz)
        """
        oid = "docsIf31CmDsOfdmChanPlcFreq"
        self.logger.debug(f"Walking OID for PLC frequencies: {oid}")

        try:
            results = await self._snmp.walk(oid)
            idx_plc_freqs = cast(list[tuple[InterfaceIndex, FrequencyHz]], Snmp_v2c.snmp_get_result_last_idx_value(results))

            self.logger.debug(f"Retrieved PLC Frequencies: {idx_plc_freqs}")
            return idx_plc_freqs

        except Exception as e:
            self.logger.error(f"Failed to retrieve PLC frequencies from OID {oid}: {e}")
            return []

    async def getDocsPnmCmOfdmChEstCoefMeasStatus(self, ofdm_idx: InterfaceIndex) -> int:
        '''
        Retrieves the measurement status of OFDM channel estimation coefficients.

        Parameters:
        - ofdm_idx (int): The OFDM index.

        Returns:
        int: The measurement status.
        '''
        result = await self._snmp.get(f'{"docsPnmCmOfdmChEstCoefMeasStatus"}.{ofdm_idx}')
        return int(Snmp_v2c.snmp_get_result_value(result)[0])

    async def getCmDsOfdmProfileStatsConfigChangeCt(self, ofdm_idx: InterfaceIndex) -> dict[int,dict[int,int]]:
        """
        Retrieve the count of configuration change events for a specific OFDM profile.

        Parameters:
        - ofdm_idx (int): The index of the OFDM profile.

        Returns:
            dict[ofdm_idx, dict[profile_id, count_change]]

        TODO: Need to get back, not really working

        """
        result = self._snmp.walk(f'{"docsIf31CmDsOfdmProfileStatsConfigChangeCt"}.{ofdm_idx}')
        profile_change_count = Snmp_v2c.snmp_get_result_value(result)[0]
        return profile_change_count

    async def _getDocsIf31CmDsOfdmChanEntry(self) -> list[DocsIf31CmDsOfdmChanEntry]:
        """
        Asynchronously retrieve all DOCSIS 3.1 downstream OFDM channel entries.

        This method queries SNMP for each available OFDM channel index
        and populates a DocsIf31CmDsOfdmChanEntry object with its SNMP attributes.

        NOTE:
            This is an async method. You must use 'await' when calling it.

        Returns:
            List[DocsIf31CmDsOfdmChanEntry]:
                A list of populated DocsIf31CmDsOfdmChanEntry objects,
                each representing one OFDM downstream channel.

        Raises:
            Exception: If SNMP queries fail or unexpected errors occur.
        """
        entries: list[DocsIf31CmDsOfdmChanEntry] = []

        # Get all OFDM Channel Indexes
        channel_indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

        for idx in channel_indices:
            self.logger.debug(f"Processing OFDM Channel Index: {idx}")
            oce = DocsIf31CmDsOfdmChanEntry(ofdm_idx=idx)

            # Iterate over all member attributes
            for member_name in oce.get_member_list():
                oid_base = COMPILED_OIDS.get(member_name)

                if not oid_base:
                    self.logger.warning(f"OID base not found for {member_name}")
                    continue

                oid = f"{oid_base}.{idx}"
                result = await self._snmp.get(oid)

                if result is not None:
                    self.logger.debug(f"Retrieved SNMP value for Member: {member_name} -> OID: {oid}")
                    try:
                        value = Snmp_v2c.snmp_get_result_value(result)
                        setattr(oce, member_name, value)
                    except (ValueError, TypeError) as e:
                        self.logger.error(f"Failed to set '{member_name}' with value '{result}': {e}")
                else:
                    self.logger.warning(f"No SNMP response received for OID: {oid}")

            entries.append(oce)

        return entries

    async def getDocsIfSignalQuality(self) -> list[DocsIfSignalQuality]:
        """
        Retrieves signal quality metrics for all downstream QAM channels.

        This method queries the SNMP agent for the list of downstream QAM channel indexes,
        and for each index, creates a `DocsIfSignalQuality` instance, populates it with SNMP data,
        and collects it into a list.

        Returns:
            List[DocsIfSignalQuality]: A list of signal quality objects, one per downstream channel.
        """
        sig_qual_list: list[DocsIfSignalQuality] = []

        indices = await self.getDocsIfCmDsScQamChanChannelIdIndex()
        if not indices:
            self.logger.warning("No downstream channel indices found.")
            return sig_qual_list

        for idx in indices:
            obj = DocsIfSignalQuality(index=idx, snmp=self._snmp)
            await obj.start()
            sig_qual_list.append(obj)

        return sig_qual_list

    async def getDocsIfDownstreamChannel(self) -> list[DocsIfDownstreamChannelEntry]:
        """
        Retrieves signal quality metrics for all downstream SC-QAM channels.

        This method queries the SNMP agent for the list of downstream SC-QAM channel indexes,
        and for each index, fetches and builds a DocsIfDownstreamChannelEntry.

        Returns:
            List[DocsIfDownstreamChannelEntry]: A list of populated downstream channel entries.
        """
        try:
            indices = await self.getDocsIfCmDsScQamChanChannelIdIndex()

            if not indices:
                self.logger.warning("No downstream SC-QAM channel indices found.")
                return []

            entries = await DocsIfDownstreamChannelEntry.get(snmp=self._snmp, indices=indices)

            return entries

        except Exception as e:
            self.logger.exception("Failed to retrieve downstream SC-QAM channel entries, error: %s", e)
            return []

    async def getDocsIfDownstreamChannelCwErrorRate(self, sample_time_elapsed: float = 5.0) -> \
        list[DocsIfDownstreamCwErrorRateEntry] | dict[str, Any]:
        """
        Retrieves codeword error rate for all downstream SC-QAM channels.

        1. Fetch initial SNMP snapshot for all channels.
        2. Wait asynchronously for `sample_time_elapsed` seconds.
        3. Fetch second SNMP snapshot.
        4. Compute per-channel & aggregate CW error metrics.
        """
        try:
            # 1) Discover all downstream SC-QAM (index, channel_id) indices
            idx_chanid_indices:list[tuple[int, int]] = await self.getDocsIfDownstreamChannelIdIndexStack()

            if not idx_chanid_indices:
                self.logger.warning("No downstream SC-QAM channel indices found.")
                return {"entries": [], "aggregate_error_rate": 0.0}

            self.logger.debug(f"Found {len(idx_chanid_indices)} downstream SC-QAM channel indices: {idx_chanid_indices}")
            # Extract only the first element of each tuple
            idx_indices:list[int] = [index[0] for index in idx_chanid_indices]

            # 2) First snapshot
            initial_entry = await DocsIfDownstreamChannelEntry.get(snmp=self._snmp, indices=idx_indices)
            self.logger.debug(f"Initial snapshot: {len(initial_entry)} channels")

            # 3) Wait the sample interval
            await asyncio.sleep(sample_time_elapsed)

            # 4) Second snapshot
            later_entry = await DocsIfDownstreamChannelEntry.get(snmp=self._snmp, indices=idx_indices)
            self.logger.debug(f"Second snapshot after {sample_time_elapsed}s: {len(later_entry)} channels")

            # 5) Calculate error rates
            calculator = DocsIfDownstreamChannelCwErrorRate(
                            entries_1=initial_entry,
                            entries_2=later_entry,
                            channel_id_index_stack=idx_chanid_indices,
                            time_elapsed=sample_time_elapsed)
            return calculator.get()

        except Exception:
            self.logger.exception("Failed to retrieve downstream SC-QAM codeword error rates")
            return {"entries": [], "aggregate_error_rate": 0.0}

    async def getEventEntryIndex(self) -> list[EntryIndex]:
        """
        Retrieves the list of index values for the docsDevEventEntry table.

        Returns:
            List[int]: A list of SNMP index integers.
        """
        oid = "docsDevEvId"

        results = await self._snmp.walk(oid)

        if not results:
            self.logger.warning(f"No results found for OID {oid}")
            return []

        return cast(list[EntryIndex], Snmp_v2c.extract_last_oid_index(results))

    async def getDocsDevEventEntry(self, to_dict: bool = False) -> list[DocsDevEventEntry] | list[dict]:
        """
        Retrieves all DocsDevEventEntry SNMP table entries.

        Args:
            to_dict (bool): If True, returns a list of dictionaries instead of DocsDevEventEntry instances.

        Returns:
            Union[List[DocsDevEventEntry], List[dict]]: A list of event log entries.
        """
        event_entries = []

        try:
            indices = await self.getEventEntryIndex()

            if not indices:
                self.logger.warning("No DocsDevEventEntry indices found.")
                return event_entries

            for idx in indices:
                entry = DocsDevEventEntry(index=idx, snmp=self._snmp)
                await entry.start()
                event_entries.append(entry.to_dict() if to_dict else entry)

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsDevEventEntry entries, error: %s", e)

        return event_entries

    async def getDocsIf31CmDsOfdmChanEntry(self) -> list[DocsIf31CmDsOfdmChanChannelEntry]:
        """
        Asynchronously retrieves and populates a list of `DocsIf31CmDsOfdmChanEntry` entries.

        This method fetches the indices of the DOCSIS 3.1 CM DS OFDM channels, creates
        `DocsIf31CmDsOfdmChanEntry` objects for each index, and populates their attributes
        by making SNMP queries. The entries are returned as a list.

        Returns:
            List[DocsIf31CmDsOfdmChanEntry]: A list of `DocsIf31CmDsOfdmChanEntry` objects.

        Raises:
            Exception: If any unexpected error occurs during the process of fetching or processing.
        """

        ofdm_chan_entry: list[DocsIf31CmDsOfdmChanChannelEntry] = []

        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelId indices found.")
                return ofdm_chan_entry

            ofdm_chan_entry.extend(await DocsIf31CmDsOfdmChanChannelEntry.get(self._snmp, indices))

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsIf31CmDsOfdmChanEntry entries, error: %s", e)

        return ofdm_chan_entry

    async def getDocsIf31CmSystemCfgDiplexState(self) -> DocsIf31CmSystemCfgDiplexState:
        """
        Asynchronously retrieves the DOCS-IF31-MIB system configuration state and populates the `DocsIf31CmSystemCfgState` object.

        This method will fetch the necessary MIB data, populate the attributes of the
        `DocsIf31CmSystemCfgState` object, and return the object.

        Returns:
            DocsIf31CmSystemCfgState: An instance of the `DocsIf31CmSystemCfgState` class with populated data.
        """
        obj = DocsIf31CmSystemCfgDiplexState(self._snmp)
        await obj.start()

        return obj

    async def getDocsIf31CmDsOfdmProfileStatsEntry(self) -> list[DocsIf31CmDsOfdmProfileStatsEntry]:
        """
        Asynchronously retrieves the DOCS-IF31-MIB system configuration state and populates the `DocsIf31CmSystemCfgState` object.

        This method will fetch the necessary MIB data, populate the attributes of the
        `DocsIf31CmSystemCfgState` object, and return the object.

        Returns:
            DocsIf31CmSystemCfgState: An instance of the `DocsIf31CmSystemCfgState` class with populated data.
        """

        ofdm_profile_entry: list[DocsIf31CmDsOfdmProfileStatsEntry] = []

        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return ofdm_profile_entry

            for idx in indices:
                entry = DocsIf31CmDsOfdmProfileStatsEntry(index=idx, snmp=self._snmp)
                await entry.start()
                ofdm_profile_entry.append(entry)

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsIf31CmDsOfdmProfileStatsEntry entries, error: %s", e)

        return ofdm_profile_entry

    async def getPnmMeasurementStatus(self, test_type: DocsPnmCmCtlTest, ofdm_ifindex: int = 0) -> MeasStatusType:
        """
        Retrieve the measurement status for a given PNM test type.

        Depending on the test type, the appropriate SNMP OID is selected,
        and the required interface index is either used directly or derived
        based on DOCSIS interface type conventions.

        Args:
            test_type (DocsPnmCmCtlTest): Enum specifying the PNM test type.
            ofdm_ifindex (int): Interface index for OFDM-based tests. This may be
                                ignored or overridden for specific test types.

        Returns:
            MeasStatusType: Parsed status value from SNMP response.

        Notes:
            - `DS_SPECTRUM_ANALYZER` uses a fixed ifIndex of 0.
            - `LATENCY_REPORT` dynamically resolves the ifIndex of the DOCSIS MAC layer.
            - If the test type is unsupported or SNMP fails, `MeasStatusType.OTHER | ERROR` is returned.
        """

        oid_key_map = {
            DocsPnmCmCtlTest.SPECTRUM_ANALYZER: "docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus",
            DocsPnmCmCtlTest.DS_OFDM_SYMBOL_CAPTURE: "docsPnmCmDsOfdmSymMeasStatus",
            DocsPnmCmCtlTest.DS_OFDM_CHAN_EST_COEF: "docsPnmCmOfdmChEstCoefMeasStatus",
            DocsPnmCmCtlTest.DS_CONSTELLATION_DISP: "docsPnmCmDsConstDispMeasStatus",
            DocsPnmCmCtlTest.DS_OFDM_RXMER_PER_SUBCAR: "docsPnmCmDsOfdmRxMerMeasStatus",
            DocsPnmCmCtlTest.DS_OFDM_CODEWORD_ERROR_RATE: "docsPnmCmDsOfdmFecMeasStatus",
            DocsPnmCmCtlTest.DS_HISTOGRAM: "docsPnmCmDsHistMeasStatus",
            DocsPnmCmCtlTest.US_PRE_EQUALIZER_COEF: "docsPnmCmUsPreEqMeasStatus",
            DocsPnmCmCtlTest.DS_OFDM_MODULATION_PROFILE: "docsPnmCmDsOfdmModProfMeasStatus",
            DocsPnmCmCtlTest.LATENCY_REPORT: "docsCmLatencyRptCfgMeasStatus",
        }

        if test_type == DocsPnmCmCtlTest.SPECTRUM_ANALYZER:
            ofdm_ifindex = 0
        elif test_type == DocsPnmCmCtlTest.LATENCY_REPORT:
            ofdm_ifindex = await self.getIfTypeIndex(DocsisIfType.docsCableMaclayer)[0]

        oid = oid_key_map.get(test_type)
        if not oid:
            self.logger.warning(f"Unsupported test type provided: {test_type}")
            return MeasStatusType.OTHER

        oid = f"{oid}.{ofdm_ifindex}"

        try:
            result = await self._snmp.get(oid)
            status_value = int(Snmp_v2c.snmp_get_result_value(result)[0])
            return MeasStatusType(status_value)

        except Exception as e:
            self.logger.error(f"[{test_type.name}] SNMP fetch failed on OID {oid}: {e}")
            self.logger.error(f'[{test_type.name}] {result}')
            return MeasStatusType.ERROR

    async def getDocsIfDownstreamChannelIdIndexStack(self) -> list[tuple[InterfaceIndex, ChannelId]]:
        """
        Retrieve SC-QAM channel index ↔ channelId tuples for DOCSIS 3.0 downstream channels,
        ensuring we only return true SC-QAM channels ( skips OFDM / zero entries ).

        Returns:
            List[Tuple[int, int]]: (entryIndex, channelId) pairs, or [] if none found.
        """
        # 1) fetch indices of all SC-QAM interfaces
        try:
            scqam_if_indices = await self.getIfTypeIndex(DocsisIfType.docsCableDownstream)
        except Exception:
            self.logger.error("Failed to retrieve SC-QAM interface indices", exc_info=True)
            return []
        if not scqam_if_indices:
            self.logger.debug("No SC-QAM interface indices found")
            return []

        # 2) do a single walk of the SC-QAM ChannelId table
        try:
            responses = await self._snmp.walk("docsIfDownChannelId")
        except Exception:
            self.logger.error("SNMP walk failed for docsIfDownChannelId", exc_info=True)
            return []
        if not responses:
            self.logger.debug("No entries returned from docsIfDownChannelId walk")
            return []

        # 3) parse into (idx, chanId), forcing chanId → int
        try:
            raw_pairs: list[tuple[int, int]] = Snmp_v2c.snmp_get_result_last_idx_force_value_type(responses,
                                                                                                  value_type=int)

        except Exception:
            self.logger.error("Failed to parse index/channel-ID pairs", exc_info=True)
            return []

        # 4) filter out non-SC-QAM and zero entries (likely OFDM)
        scqam_set = set(scqam_if_indices)
        filtered: list[tuple[InterfaceIndex, ChannelId]] = []

        for idx, chan_id in raw_pairs:
            if idx not in scqam_set:
                self.logger.debug("Skipping idx %s not in SC-QAM interface list", idx)
                continue
            if chan_id == 0:
                self.logger.debug("Skipping idx %s with channel_id=0 (likely OFDM)", idx)
                continue
            filtered.append((InterfaceIndex(idx), ChannelId(chan_id)))

        return filtered

    async def getDocsIf31CmDsOfdmChannelIdIndexStack(self) -> list[tuple[InterfaceIndex, ChannelId]]:
        """
        Retrieve a list of tuples representing OFDM channel index and their associated channel IDs
        for DOCSIS 3.1 downstream OFDM channels.

        Returns:
            List[Tuple[int, int]]: Each tuple contains (index, channelId). Returns an empty list if no data is found.
        """
        result = await self._snmp.walk(f'{"docsIf31CmDsOfdmChanChannelId"}')

        if not result:
            return []

        raw_pairs: list[tuple[int, int]] = Snmp_v2c.snmp_get_result_last_idx_force_value_type(
            result,
            value_type=int,
        )
        idx_channel_id: list[tuple[InterfaceIndex, ChannelId]] = [
            (InterfaceIndex(idx), ChannelId(chan_id)) for idx, chan_id in raw_pairs
        ]

        return idx_channel_id or []

    async def getSysUpTime(self) -> str | None:
        """
        Retrieves the system uptime of the SNMP target device.

        This method performs an SNMP GET operation on the `sysUpTime` OID (1.3.6.1.2.1.1.3.0),
        which returns the time (in hundredths of a second) since the network management portion
        of the system was last re-initialized.

        Returns:
            Optional[int]: The system uptime in hundredths of a second if successful,
            otherwise `None` if the SNMP request fails or the result cannot be parsed.

        Logs:
            - A warning if the SNMP GET fails or returns no result.
            - An error if the value cannot be converted to an integer.
        """
        result = await self._snmp.get(f'{"sysUpTime"}.0')

        if not result:
            self.logger.warning("SNMP get failed or returned empty for sysUpTime.")
            return None

        try:
            value = Snmp_v2c.get_result_value(result)
            return Snmp_v2c.ticks_to_duration(int(value))

        except (ValueError, TypeError) as e:
            self.logger.error(f"Failed to parse sysUpTime value: {value} - {e}")
            return None

    async def isAmplitudeDataPresent(self) -> bool:
        """
        Check if DOCSIS spectrum amplitude data is available via SNMP.

        Returns:
            bool: True if amplitude data exists; False otherwise.
        """
        oid = COMPILED_OIDS.get("docsIf3CmSpectrumAnalysisMeasAmplitudeData")
        if not oid:
            return False

        try:

            # TODO: Uncomment when ready to use
            #results = await self._snmp.walk(oid)

            results = await self._snmp.bulk_walk(oid, max_repetitions=1)

        except Exception as e:
            self.logger.warning(f"Amplitude data bulk walk failed for {oid}: {e}")
            return False

        return bool(results)

    async def getSpectrumAmplitudeData(self) -> bytes:
        """
        Retrieve and return the raw spectrum analyzer amplitude data from the cable modem via SNMP.

        This method queries the 'docsIf3CmSpectrumAnalysisMeasAmplitudeData' table, collects all
        returned byte-chunks, and concatenates them into a single byte stream. It logs a warning
        if no data is found, and logs the first 128 bytes of the raw result (in hex) for inspection.

        Returns:
            A bytes object containing the full amplitude data stream. If no data is returned, an
            empty bytes object is returned.

        Raises:
            RuntimeError: If SNMP walk returns an unexpected data type or if any underlying SNMP
                          operation fails.
        """
        # OID for the amplitude data (should be a ByteString/Textual convention)
        oid = COMPILED_OIDS.get("docsIf3CmSpectrumAnalysisMeasAmplitudeData")
        if oid is None:
            msg = "OID 'docsIf3CmSpectrumAnalysisMeasAmplitudeData' is not defined in COMPILED_OIDS."
            self.logger.error(msg)
            raise RuntimeError(msg)

        # Perform SNMP WALK asynchronously
        try:
            results = await self._snmp.walk(oid)
        except Exception as e:
            self.logger.error(f"SNMP walk for OID {oid} failed: {e}")
            raise RuntimeError(f"SNMP walk failed: {e}") from e

        # If the SNMP WALK returned no varbinds, warn and return empty bytes
        if not results:
            self.logger.warning(f"No results found for OID {oid}")
            return b""

        # Extract raw byte-chunks from the SNMP results
        raw_chunks = []
        for idx, chunk in enumerate(Snmp_v2c.snmp_get_result_bytes(results)):
            # Ensure we got a bytes-like object
            if not isinstance(chunk, (bytes, bytearray)):
                self.logger.error(
                    f"Unexpected data type for chunk #{idx}: {type(chunk).__name__}. "
                    "Expected bytes or bytearray."
                )
                raise RuntimeError(f"Invalid SNMP result type: {type(chunk)}")

            # Log the first 128 bytes of each chunk (hex) for debugging
            preview = chunk[:128].hex()
            self.logger.debug(f"Raw SNMP chunk #{idx} (first 128 bytes): {preview}")

            raw_chunks.append(bytes(chunk))  # ensure immutability

        # Concatenate all chunks into a single bytes object
        varbind_bytes = b"".join(raw_chunks)

        # Log total length for reference
        total_length = len(varbind_bytes)
        if total_length == 0:
            self.logger.warning(f"OID {oid} returned an empty byte stream after concatenation.")
        else:
            self.logger.debug(f"Retrieved {total_length} bytes of amplitude data for OID {oid}.")

        return varbind_bytes

    async def getBulkFileUploadStatus(self, filename: str) -> DocsPnmBulkFileUploadStatus:
        """
        Retrieve the upload‐status enum of a bulk data file by its filename.

        Args:
            filename: The exact file name to search for in the BulkDataFile table.

        Returns:
            DocsPnmBulkFileUploadStatus:
            - The actual upload status if found
            - DocsPnmBulkFileUploadStatus.ERROR if the filename is not present or any SNMP error occurs
        """
        self.logger.debug(f"Starting getBulkFileUploadStatus for filename: {filename}")

        name_oid = "docsPnmBulkFileName"
        status_oid = "docsPnmBulkFileUploadStatus"

        # 1) Walk file‐name column
        try:
            name_rows = await self._snmp.walk(name_oid)
        except Exception as e:
            self.logger.error(f"SNMP walk failed for BulkFileName: {e}")
            return DocsPnmBulkFileUploadStatus.ERROR

        if not name_rows:
            self.logger.warning("BulkFileName table is empty.")
            return None

        # 2) Loop through (index, name) pairs
        for idx, current_name in Snmp_v2c.snmp_get_result_last_idx_value(name_rows):
            if current_name != filename:
                continue

            # 3) Fetch the status OID for this index
            full_oid = f"{status_oid}.{idx}"
            try:
                resp = await self._snmp.get(full_oid)
            except Exception as e:
                self.logger.error(f"SNMP get failed for {full_oid}: {e}")
                return DocsPnmBulkFileUploadStatus.ERROR

            if not resp:
                self.logger.warning(f"No response for status OID {full_oid}")
                return DocsPnmBulkFileUploadStatus.ERROR

            # 4) Parse and convert to enum
            try:
                _, val = resp[0]
                status_int = int(val)
                status_enum = DocsPnmBulkFileUploadStatus(status_int)
            except ValueError as ve:
                self.logger.error(f"Invalid status value {val}: {ve}")
                return DocsPnmBulkFileUploadStatus.ERROR
            except Exception as e:
                self.logger.error(f"Unexpected error parsing status: {e}")
                return DocsPnmBulkFileUploadStatus.ERROR

            self.logger.debug(f"Bulk file '{filename}' upload status: {status_enum.name}")
            return status_enum

        # not found
        self.logger.warning(f"Filename '{filename}' not found in BulkDataFile table.")
        return DocsPnmBulkFileUploadStatus.ERROR

    async def getDocsisBaseCapability(self) -> ClabsDocsisVersion:
        """
        Retrieve the DOCSIS version capability reported by the device.

        This method queries the SNMP OID `docsIf31CmDocsisBaseCapability`, which reflects
        the supported DOCSIS Radio Frequency specification version.

        Returns:
            ClabsDocsisVersion: Enum indicating the DOCSIS version supported by the device, or None if unavailable.

        SNMP MIB Reference:
            - OID: docsIf31DocsisBaseCapability
            - SYNTAX: ClabsDocsisVersion (INTEGER enum from 0 to 6)
            - Affected Devices:
                - CMTS: reports highest supported DOCSIS version.
                - CM: reports supported DOCSIS version.

            This attribute replaces `docsIfDocsisBaseCapability` from RFC 4546.
        """
        self.logger.debug("Fetching docsIf31DocsisBaseCapability")

        try:
            rsp = await self._snmp.get('docsIf31DocsisBaseCapability.0')
            docsis_version_raw = Snmp_v2c.get_result_value(rsp)

            if docsis_version_raw is None:
                self.logger.error("Failed to retrieve DOCSIS version: SNMP result is None")
                return None

            try:
                docsis_version = int(docsis_version_raw)
            except (ValueError, TypeError):
                self.logger.error(f"Failed to cast DOCSIS version to int: {docsis_version_raw}")
                return None

            cdv = ClabsDocsisVersion.from_value(docsis_version)

            if cdv == ClabsDocsisVersion.OTHER:
                self.logger.warning(f"Unknown DOCSIS version: {docsis_version} -> Enum: {cdv.name}")
            else:
                self.logger.debug(f"DOCSIS version: {cdv.name}")

            return cdv

        except Exception as e:
            self.logger.exception(f"Exception during DOCSIS version retrieval: {e}")
            return None

    async def getInterfaceStatistics(self, interface_types: type[Enum] = DocsisIfType) -> dict[str, list[dict]]:
        """
        Retrieves interface statistics grouped by provided Enum of interface types.

        Args:
            interface_types (Type[Enum]): Enum class representing interface types.

        Returns:
            Dict[str, List[Dict]]: Mapping of interface type name to list of interface stats.
        """
        stats: dict[str, list[dict]] = {}

        for if_type in interface_types:
            interfaces = await InterfaceStats.from_snmp(self._snmp, if_type)
            if interfaces:
                stats[if_type.name] = [iface.model_dump() for iface in interfaces]

        return stats

    async def getDocsIf31CmUsOfdmaChanChannelIdIndex(self) -> list[InterfaceIndex]:
        """
        Get the Docsis 3.1 upstream OFDMA channels.

        Returns:
            List[int]: A list of OFDMA channel indices present on the device.
        """
        return await self.getIfTypeIndex(DocsisIfType.docsOfdmaUpstream)

    async def getDocsIf31CmUsOfdmaChanEntry(self) -> list[DocsIf31CmUsOfdmaChanEntry]:
        """
        Retrieves and initializes all OFDMA channel entries from Snmp_v2c.

        Returns:
            List[DocsIf31CmUsOfdmaChanEntry]: List of populated OFDMA channel objects.
        """
        results: list[DocsIf31CmUsOfdmaChanEntry] = []

        indices = await self.getDocsIf31CmUsOfdmaChanChannelIdIndex()
        if not indices:
            self.logger.warning("No upstream OFDMA indices found.")
            return results

        return await DocsIf31CmUsOfdmaChanEntry.get(snmp=self._snmp, indices=indices)

    async def getDocsIfUpstreamChannelEntry(self) -> list[DocsIfUpstreamChannelEntry]:
        """
        Retrieves and initializes all ATDMA US channel entries from Snmp_v2c.

        Returns:
            List[DocsIfUpstreamChannelEntry]: List of populated ATDMA channel objects.
        """
        try:
            indices = await self.getDocsIfCmUsTdmaChanChannelIdIndex()

            if not indices:
                self.logger.warning("No upstream ATDMA indices found.")
                return []

            entries = await DocsIfUpstreamChannelEntry.get(
                snmp=self._snmp,
                indices=indices
            )

            return entries

        except Exception as e:
            self.logger.exception("Failed to retrieve ATDMA upstream channel entries, error: %s", e)
            return []

    async def getDocsIf31CmUsOfdmaChannelIdIndexStack(self) -> list[tuple[InterfaceIndex, ChannelId]]:
        """
        Retrieve a list of tuples representing OFDMA channel index and their associated channel IDs
        for DOCSIS 3.1 upstream OFDMA channels.

        Returns:
            List[Tuple[InterfaceIndex, ChannelId]]: Each tuple contains (index, channelId). Returns an empty list if no data is found.
        """
        result = await self._snmp.walk(f'{"docsIf31CmUsOfdmaChanChannelId"}')

        if not result:
            return []

        raw_pairs: list[tuple[int, int]] = Snmp_v2c.snmp_get_result_last_idx_force_value_type(
            result,
            value_type=int,
        )
        idx_channel_id_list: list[tuple[InterfaceIndex, ChannelId]] = [
            (InterfaceIndex(idx), ChannelId(chan_id)) for idx, chan_id in raw_pairs
        ]

        return idx_channel_id_list or []

    async def getDocsIfCmUsTdmaChanChannelIdIndex(self) -> list[InterfaceIndex]:
        """
        Retrieve the list of DOCSIS 3.0 upstream TDMA/ATDMA channel indices (i.e., TDMA or ATDMA).

        Returns:
            List[int]: A list of TDMA/ATDMA channel indices present on the device.
        """
        idx_list: list[int] = []
        oid_channel_id = "docsIfUpChannelId"

        try:
            results = await self._snmp.walk(oid_channel_id)
            if not results:
                self.logger.warning(f"No results found for OID {oid_channel_id}")
                return []

            index_list = Snmp_v2c.extract_last_oid_index(results)

            oid_modulation = "docsIfUpChannelType"

            for idx in index_list:

                result = await self._snmp.get(f'{oid_modulation}.{idx}')

                if not result:
                    self.logger.warning(f"SNMP get failed or returned empty docsIfUpChannelType for index {idx}.")
                    continue

                val = Snmp_v2c.snmp_get_result_value(result)[0]

                try:
                    channel_type = int(val)

                except ValueError:
                    self.logger.warning(f"Failed to convert channel-type value '{val}' to int for index {idx}. Skipping.")
                    continue

                '''
                    DocsisUpstreamType ::= TEXTUAL-CONVENTION
                    STATUS          current
                    DESCRIPTION
                            "Indicates the DOCSIS Upstream Channel Type.
                            'unknown' means information not available.
                            'tdma' is related to TDMA, Time Division
                            Multiple Access; 'atdma' is related to A-TDMA,
                            Advanced Time Division Multiple Access,
                            'scdma' is related to S-CDMA, Synchronous
                            Code Division Multiple Access.
                            'tdmaAndAtdma is related to simultaneous support of
                            TDMA and A-TDMA modes."
                    SYNTAX INTEGER {
                        unknown(0),
                        tdma(1),
                        atdma(2),
                        scdma(3),
                        tdmaAndAtdma(4)
                    }

                '''

                if channel_type != 0: # 0 means OFDMA in this case
                    idx_list.append(idx)

            return idx_list

        except Exception as e:
            self.logger.error(f"Failed to retrieve SC-QAM channel indices from {oid_channel_id}: {e}")
            return []


    """
    Measurement Entries
    """

    async def getDocsPnmCmDsOfdmRxMerEntry(self) -> list[DocsPnmCmDsOfdmRxMerEntry]:
        """
        Retrieve RxMER (per-subcarrier) entries for all downstream OFDM channels.

        Returns
        -------
        List[DocsPnmCmDsOfdmRxMerEntry]
            A list of Pydantic models with values already coerced to floats
            where appropriate (e.g., dB fields scaled by 1/100).
        """
        self.logger.debug('Entering into -> getDocsPnmCmDsOfdmRxMerEntry()')
        entries: list[DocsPnmCmDsOfdmRxMerEntry] = []
        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            # De-dupe and sort for predictable iteration (optional but nice for logs)
            unique_indices = sorted(set(int(i) for i in indices))
            self.logger.debug(f"RxMER fetch: indices={unique_indices}")

            entries = await DocsPnmCmDsOfdmRxMerEntry.get(snmp=self._snmp, indices=unique_indices)

            # Helpful summary log—count only; detailed per-field logs happen in the entry fetcher
            self.logger.debug("RxMER fetch complete: %d entries", len(entries))
            return entries

        except Exception as e:
            # Keep the exception in logs for debugging (stacktrace included)
            self.logger.exception("Failed to retrieve DocsPnmCmDsOfdmRxMerEntry entries: %s", e)
            return entries

    async def getDocsPnmCmOfdmChanEstCoefEntry(self) -> list[DocsPnmCmOfdmChanEstCoefEntry]:
        """
        Retrieves downstream OFDM Channel Estimation Coefficient entries from the cable modem via SNMP.

        This method:
        - Queries for all available downstream OFDM channel indices using `getDocsIf31CmDsOfdmChannelIdIndex()`.
        - For each index, requests a structured set of coefficient data points including amplitude ripple,
          group delay characteristics, mean values, and measurement status.
        - Constructs a list of `DocsPnmCmOfdmChanEstCoefEntry` objects, each encapsulating the raw
          coefficients for one OFDM channel.

        Returns:
            List[DocsPnmCmOfdmChanEstCoefEntry]: A list of populated OFDM channel estimation entries. Each entry
            includes both metadata and coefficient fields defined in `DocsPnmCmOfdmChanEstCoefFields`.
        """
        entries: list[DocsPnmCmOfdmChanEstCoefEntry] = []

        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            entries = await DocsPnmCmOfdmChanEstCoefEntry.get(snmp=self._snmp, indices=indices)

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsPnmCmOfdmChanEstCoefEntry entries, error: %s", e)

        return entries

    async def getDocsPnmCmDsConstDispMeasEntry(self) -> list[DocsPnmCmDsConstDispMeasEntry]:
        """
        Retrieves Constellation Display measurement entries for all downstream OFDM channels.

        This method:
        - Discovers available downstream OFDM channel indices using SNMP via `getDocsIf31CmDsOfdmChannelIdIndex()`
        - For each channel index, fetches constellation capture configuration, modulation info,
          measurement status, and associated binary filename
        - Returns the results as a structured list of `DocsPnmCmDsConstDispMeasEntry` models

        Returns:
            List[DocsPnmCmDsConstDispMeasEntry]: A list of Constellation Display SNMP measurement entries.
        """
        entries: list[DocsPnmCmDsConstDispMeasEntry] = []

        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            entries = await DocsPnmCmDsConstDispMeasEntry.get(snmp=self._snmp, indices=indices)

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsPnmCmDsConstDispMeasEntry entries, error: %s", e)

        return entries

    async def getDocsPnmCmUsPreEqEntry(self) -> list[DocsPnmCmUsPreEqEntry]:
        """
        Retrieves upstream OFDMA Pre-Equalization measurement entries for all upstream OFDMA channels.

        This method performs:
        - SNMP index discovery via `getDocsIf31CmDsOfdmChannelIdIndex()` (may need to be updated to upstream index discovery)
        - Per-index SNMP fetch of pre-equalization configuration and measurement metadata
        - Returns structured list of `DocsPnmCmUsPreEqEntry` models
        """
        entries: list[DocsPnmCmUsPreEqEntry] = []

        try:
            indices = await self.getDocsIf31CmUsOfdmaChanChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmUsOfdmaChannelIdIndex indices found.")
                return entries

            entries = await DocsPnmCmUsPreEqEntry.get(snmp=self._snmp, indices=indices)

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsPnmCmUsPreEqEntry entries, error: %s", e)

        return entries

    async def getDocsPnmCmDsOfdmMerMarEntry(self) -> list[DocsPnmCmDsOfdmMerMarEntry]:
        """
        Retrieves DOCSIS 3.1 Downstream OFDM MER Margin entries.

        This method queries the SNMP agent to collect MER Margin data for each downstream OFDM channel
        using the ifIndex values retrieved from the modem. Each returned entry corresponds to a channel's
        MER margin metrics, including required MER, measured MER, threshold offsets, and measurement status.

        Returns:
            List[DocsPnmCmDsOfdmMerMarEntry]: A list of populated MER margin entries for each OFDM channel.
        """
        entries: list[DocsPnmCmDsOfdmMerMarEntry] = []

        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            entries = await DocsPnmCmDsOfdmMerMarEntry.get(snmp=self._snmp, indices=indices)
            self.logger.debug(f'Number of DocsPnmCmDsOfdmMerMarEntry Found: {len(entries)}')

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsPnmCmDsOfdmMerMarEntry entries, error: %s", e)

        return entries

    async def getDocsPnmCmDsHistEntry(self) -> list[DocsPnmCmDsHistEntry]:
        """
        Retrieves DOCSIS 3.1 Downstream Histogram entries.

        This method queries the SNMP agent to collect histogram data for each downstream OFDM channel
        using the ifIndex values retrieved from the modem. Each returned entry corresponds to a channel's
        histogram configuration and status.

        """
        entries: list[DocsPnmCmDsHistEntry] = []

        try:
            indices = await self.getIfTypeIndex(DocsisIfType.docsCableMaclayer)

            if not indices:
                self.logger.error("No docsCableMaclayer indices found.")
                return entries

            self.logger.debug(f'Found docsCableDownstream Indices: {indices}')

            entries = await DocsPnmCmDsHistEntry.get(snmp=self._snmp, indices=indices)
            self.logger.debug(f'Number of DocsPnmCmDsHistEntry Found: {len(entries)}')

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsPnmCmDsHistEntry entries, error: %s", e)

        return entries

    async def getDocsPnmCmDsOfdmFecEntry(self) -> list[DocsPnmCmDsOfdmFecEntry]:
        """
        Retrieve FEC Summary entries for all downstream OFDM channels.

        Returns
        -------
        List[DocsPnmCmDsOfdmFecEntry].
        """
        self.logger.debug('Entering into -> getDocsPnmCmDsOfdmFecEntry()')
        entries: list[DocsPnmCmDsOfdmFecEntry] = []
        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            unique_indices = sorted(set(int(i) for i in indices))
            self.logger.debug(f"`FEC Summary fetch: indices={unique_indices}")

            entries = await DocsPnmCmDsOfdmFecEntry.get(snmp=self._snmp, indices=unique_indices)

            self.logger.debug("FEC Summary fetch complete: %d entries", len(entries))
            return entries

        except Exception as e:
            self.logger.exception("Failed to retrieve DocsPnmCmDsOfdmFecEntry entries: %s", e)
            return entries

    async def getDocsPnmCmDsOfdmModProfEntry(self) -> list[DocsPnmCmDsOfdmModProfEntry]:
        """
        Retrieve Modulation Profile entries for all downstream OFDM channels.

        Returns
        -------
        List[DocsPnmCmDsOfdmModProfEntry].
        """
        self.logger.debug('Entering into -> getDocsPnmCmDsOfdmModProfEntry()')
        entries: list[DocsPnmCmDsOfdmModProfEntry] = []
        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            # De-dupe and sort for predictable iteration (optional but nice for logs)
            unique_indices = sorted(set(int(i) for i in indices))
            self.logger.debug(f"ModProf fetch: indices={unique_indices}")

            entries = await DocsPnmCmDsOfdmModProfEntry.get(snmp=self._snmp, indices=unique_indices)

            # Helpful summary log—count only; detailed per-field logs happen in the entry fetcher
            self.logger.debug("ModProf fetch complete: %d entries", len(entries))
            return entries

        except Exception as e:
            # Keep the exception in logs for debugging (stacktrace included)
            self.logger.exception("Failed to retrieve DocsPnmCmDsOfdmModProfEntry entries: %s", e)
            return entries

    async def getDocsIf3CmSpectrumAnalysisEntry(self, indices: list[int] = DEFAULT_SPECTRUM_ANALYZER_INDICES) -> list[DocsIf3CmSpectrumAnalysisEntry]:
        """
        Retrieves DOCSIS 3.0 Spectrum Analysis entries
        Args:
            indices: List[int] = DEFAULT_SPECTRUM_ANALYZER_INDICES
                This method queries the SNMP agent to collect spectrum analysis data for each specified index.
                Each returned entry corresponds to a spectrum analyzer's configuration and status.
                Current DOCSIS 3.0 MIB only defines index 0 for downstream spectrum analysis.
                Leaving for possible future expansion.

        """
        entries: list[DocsIf3CmSpectrumAnalysisEntry] = []

        try:
            if not indices:
                self.logger.error("No docsCableMaclayer indices found.")
                return entries

            self.logger.debug(f'Found docsCableDownstream Indices: {indices}')

            entries = await DocsIf3CmSpectrumAnalysisEntry.get(snmp=self._snmp, indices=indices)
            self.logger.debug(f'Number of DocsIf3CmSpectrumAnalysisEntry Found: {len(entries)}')

        except Exception as e:
            self.logger.exception(f"Failed to retrieve DocsIf3CmSpectrumAnalysisEntry entries: {e}")

        return entries

    async def getOfdmProfiles(self) -> list[tuple[int, OfdmProfiles]]:
        """
        Retrieve provisioned OFDM profile bits for each downstream OFDM channel.

        Returns:
            List[Tuple[int, OfdmProfiles]]: A list of tuples where each tuple contains:
                - SNMP index (int)
                - Corresponding OfdmProfiles bitmask (OfdmProfiles enum)
        """
        BITS_16:int = 16

        entries: list[tuple[int, OfdmProfiles]] = []

        try:
            indices = await self.getDocsIf31CmDsOfdmChannelIdIndex()

            if not indices:
                self.logger.warning("No DocsIf31CmDsOfdmChanChannelIdIndex indices found.")
                return entries

            for index in indices:
                results = await self._snmp.get(f'docsIf31RxChStatusOfdmProfiles.{index}')
                raw = Snmp_v2c.get_result_value(results)

                if isinstance(raw, bytes):
                    value = int.from_bytes(raw, byteorder='little')
                else:
                    value = int(raw, BITS_16)

                profiles = OfdmProfiles(value)
                entries.append((index, profiles))

        except Exception as e:
            self.logger.exception("Failed to retrieve OFDM profiles, error: %s", e)

        return entries

    ####################
    # DOCSIS 4.0 - FDD #
    ####################

    async def getDocsFddCmFddSystemCfgState(self, index: int = 0) -> DocsFddCmFddSystemCfgState | None | None:
        """
        Retrieves the FDD band edge configuration state for a specific cable modem index.

        This queries the DOCSIS 4.0 MIB values for:
        - Downstream Lower Band Edge
        - Downstream Upper Band Edge
        - Upstream Upper Band Edge

        Args:
            index (int): SNMP index of the CM to query (default: 0).

        Returns:
            DocsFddCmFddSystemCfgState | None: Populated object if successful, or None on failure.
        """
        results = await self._snmp.walk('docsFddCmFddSystemCfgState')
        if not results:
            self.logger.warning(f"No results found during SNMP walk for OID {'docsFddCmFddSystemCfgState'}")
            return None

        obj = DocsFddCmFddSystemCfgState(index, self._snmp)
        success = await obj.start()

        if not success:
            self.logger.warning(f"SNMP population failed for DocsFddCmFddSystemCfgState (index={index})")
            return None

        return obj

    async def getDocsFddCmFddBandEdgeCapabilities(self, create_and_start: bool = True) -> list[DocsFddCmFddBandEdgeCapabilities] | None:
        """
        Retrieve a list of FDD band edge capability entries for a DOCSIS 4.0 modem.

        Walks the SNMP table to discover indices, and returns capability objects
        optionally populated with SNMP data.

        Args:
            create_and_start (bool): Whether to call `.start()` on each entry.

        Returns:
            A list of DocsFddCmFddBandEdgeCapabilities objects, or None if none found.
        """
        results = await self._snmp.walk('docsFddDiplexerUsUpperBandEdgeCapability')
        if not results:
            self.logger.warning("No results found during SNMP walk for OID 'docsFddDiplexerUsUpperBandEdgeCapability'")
            return None

        entries = []
        for idx in Snmp_v2c.extract_last_oid_index(results):
            obj = DocsFddCmFddBandEdgeCapabilities(idx, self._snmp)

            if create_and_start and not await obj.start():
                self.logger.warning(f"SNMP population failed for DocsFddCmFddBandEdgeCapabilities (index={idx})")
                continue

            entries.append(obj)

        return entries or None

    ######################
    # SNMP Set Operation #
    ######################

    async def setDocsDevResetNow(self) -> bool:
        """
        Triggers an immediate device reset using the SNMP `docsDevResetNow` object.

        Returns:
        - bool: True if the SNMP set operation is successful, False otherwise.
        """
        try:
            oid = f'{"docsDevResetNow"}.0'
            self.logger.debug(f'Sending device reset via SNMP SET: {oid} = 1')

            response = await self._snmp.set(oid, Snmp_v2c.TRUE, Integer32)

            if response is None:
                self.logger.error('Device reset command returned None')
                return False

            result = Snmp_v2c.snmp_set_result_value(response)

            self.logger.debug(f'Device reset command issued. SNMP response: {result}')
            return True

        except Exception as e:
            self.logger.exception(f'Failed to send device reset command: {e}')
            return False

    async def setDocsPnmBulk(self, tftp_server: str, tftp_path: str = "") -> bool:
        """
        Set Docs PNM Bulk SNMP parameters.

        Args:
            tftp_server (str): TFTP server IP address.
            tftp_path (str, optional): TFTP server path. Defaults to empty string.

        Returns:
            bool: True if all SNMP set operations succeed, False if any fail.
        """
        try:
            ip_type = Snmp_v2c.get_inet_address_type(tftp_server).value
            set_response = await self._snmp.set(f'{"docsPnmBulkDestIpAddrType"}.0', ip_type, Integer32)
            self.logger.debug(f'docsPnmBulkDestIpAddrType set: {set_response}')

            set_response = await self._snmp.set(f'{"docsPnmBulkUploadControl"}.0',
                                          DocsPnmBulkUploadControl.AUTO_UPLOAD.value, Integer32)
            self.logger.debug(f'docsPnmBulkUploadControl set: {set_response}')

            ip_binary = InetGenerate.inet_to_binary(tftp_server)
            if ip_binary is None:
                self.logger.error(f"Failed to convert IP address to binary: {tftp_server}")
                return False
            set_response = await self._snmp.set('docsPnmBulkDestIpAddr.0', ip_binary, OctetString)
            self.logger.debug(f'docsPnmBulkDestIpAddr set: {set_response}')

            tftp_path = tftp_path or ""
            set_response = await self._snmp.set(f'{"docsPnmBulkDestPath"}.0', tftp_path, OctetString)
            self.logger.debug(f'docsPnmBulkDestPath set: {set_response}')

            return True

        except Exception as e:
            self.logger.error(f"Failed to set DocsPnmBulk parameters: {e}")
            return False

    async def setDocsIf3CmSpectrumAnalysisCtrlCmd(self,
                        spec_ana_cmd: DocsIf3CmSpectrumAnalysisCtrlCmd,
                        spectrum_retrieval_type: SpectrumRetrievalType = SpectrumRetrievalType.FILE,
                        set_and_go: bool = True) -> bool:
        """
        Sets all DocsIf3CmSpectrumAnalysisCtrlCmd parameters via SNMP using index 0.

        Parameters:
        - spec_ana_cmd (DocsIf3CmSpectrumAnalysisCtrlCmd): The control command object to apply.
        - spectrum_retrieval_type (SpectrumRetrieval): Determines the method of spectrum retrieval.
            - SpectrumRetrieval.FILE: File-based retrieval, in which case `docsIf3CmSpectrumAnalysisCtrlCmdFileEnable` is set to ENABLE.
            - SpectrumRetrieval.SNMP: SNMP-based retrieval, in which case `docsIf3CmSpectrumAnalysisCtrlCmdEnable` is set to ENABLE.
        - set_and_go (bool): Whether to include the 'Enable' field in the set request.
            - If `data_retrival_opt = SpectrumRetrieval.FILE`, then `docsIf3CmSpectrumAnalysisCtrlCmdFileEnable` is set to ENABLE and `docsIf3CmSpectrumAnalysisCtrlCmdEnable` is skipped.
            - If `data_retrival_opt = SpectrumRetrieval.SNMP`, then `docsIf3CmSpectrumAnalysisCtrlCmdEnable` is set to ENABLE.

        Returns:
        - bool: True if all parameters were set successfully and confirmed, False otherwise.

        Raises:
        - Exception: If any error occurs during the SNMP set operations.
        """

        self.logger.debug(f'SpectrumAnalyzerPara: {spec_ana_cmd.to_dict()}')

        if spec_ana_cmd.precheck_spectrum_analyzer_settings():
            self.logger.debug(f'SpectrumAnalyzerPara-PreCheck-Changed: {spec_ana_cmd.to_dict()}')

        '''
            Custom SNMP SET for Spectrum Analyzer
        '''
        async def __snmp_set(field_name:str, obj_value:str | int, snmp_type:type) -> bool:
            """ Helper function to perform SNMP set and verify the result."""
            base_oid = COMPILED_OIDS.get(field_name)
            if not base_oid:
                self.logger.warning(f'OID not found for field "{field_name}", skipping.')
                return False

            oid = f"{base_oid}.0"
            logging.debug(f'Field-OID: {field_name} -> OID: {oid} -> {obj_value} -> Type: {snmp_type}')

            set_response = await self._snmp.set(oid, obj_value, snmp_type)
            logging.debug(f'Set {field_name} [{oid}] = {obj_value}: {set_response}')

            if not set_response:
                logging.error(f'Failed to set {field_name} to ({obj_value})')
                return False

            result = Snmp_v2c.snmp_set_result_value(set_response)[0]

            if not result:
                logging.error(f'Failed to set {field_name} to ({obj_value})')
                return False

            logging.debug(f"Result({result}): {type(result)} -> Value({obj_value}): {type(obj_value)}")

            if str(result) != str(obj_value):
                logging.error(f'Failed to set {field_name}. Expected ({obj_value}), got ({result})')
                return False
            return True

        # Need to get Diplex Setting to make sure that the Spec Analyzer setting are within the band
        cscs:DocsIf31CmSystemCfgDiplexState = await self.getDocsIf31CmSystemCfgDiplexState()
        cscs.to_dict()[0]

        """ TODO: Will need to validate the Spec Analyzer Settings against the Diplex Settings
        lower_edge = int(diplex_dict["docsIf31CmSystemCfgStateDiplexerCfgDsLowerBandEdge"]) * 1_000_000
        upper_edge = diplex_dict["docsIf31CmSystemCfgStateDiplexerCfgDsUpperBandEdge"] * 1_000_000
        """
        try:
            field_type_map = {
                "docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout": Integer32,
                "docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency": Gauge32,
                "docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency": Gauge32,
                "docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan": Gauge32,
                "docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment": Gauge32,
                "docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth": Gauge32,
                "docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction": Integer32,
                "docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages": Gauge32,
                "docsIf3CmSpectrumAnalysisCtrlCmdEnable": Integer32,
                "docsIf3CmSpectrumAnalysisCtrlCmdFileName": OctetString,
                "docsIf3CmSpectrumAnalysisCtrlCmdFileEnable": Integer32,
            }

            '''
                Note: MUST BE THE LAST 2 AND IN THIS ORDER:
                    docsIf3CmSpectrumAnalysisCtrlCmdEnable      <- Triggers SNMP AMPLITUDE DATA RETURN
                    docsIf3CmSpectrumAnalysisCtrlCmdFileEnable  <- Trigger PNM FILE RETURN, OVERRIDES SNMP AMPLITUDE DATA RETURN
            '''

            # Iterating through the fields and setting their values via SNMP
            for field_name, snmp_type in field_type_map.items():
                obj_value = getattr(spec_ana_cmd, field_name)

                self.logger.debug(f'Field-Name: {field_name} -> SNMP-Type: {snmp_type}')

                ##############################################################
                # OVERRIDE SECTION TO MAKE SURE WE FOLLOW THE SPEC-ANA RULES #
                ##############################################################

                if field_name == "docsIf3CmSpectrumAnalysisCtrlCmdFileName":
                    file_name = getattr(spec_ana_cmd, field_name)

                    if not file_name:
                        setattr(spec_ana_cmd, field_name,f'snmp-amplitude-get-flag-{Generate.time_stamp()}')

                    await __snmp_set(field_name, getattr(spec_ana_cmd, field_name) , snmp_type)

                    continue

                #######################################################################################
                #                                                                                     #
                #                   START SPECTRUM ANALYZER MEASURING PROCESS                         #
                #                                                                                     #
                # This OID Triggers the start of the Spectrum Analysis for SNMP-AMPLITUDE-DATA RETURN #
                #######################################################################################
                elif field_name == "docsIf3CmSpectrumAnalysisCtrlCmdEnable":

                    obj_value = Snmp_v2c.TRUE
                    self.logger.debug(f'Field-Name: {field_name} -> SNMP-Type: {snmp_type}')

                    # Need to toggle ? -> FALSE -> TRUE
                    if not await __snmp_set(field_name, Snmp_v2c.FALSE, snmp_type):
                        self.logger.error(f'Fail to set {field_name} to {Snmp_v2c.FALSE}')
                        return False

                    time.sleep(1)

                    if not await __snmp_set(field_name, Snmp_v2c.TRUE, snmp_type):
                        self.logger.error(f'Fail to set {field_name} to {Snmp_v2c.TRUE}')
                        return False

                    continue

                ######################################################################################
                #
                #                   CHECK SPECTRUM ANALYZER MEASURING PROCESS
                #                           FOR PNM FILE RETRIVAL
                #
                # This OID Triggers the start of the Spectrum Analysis for PNM-FILE RETURN
                # Override SNMP-AMPLITUDE-DATA RETURN
                ######################################################################################
                elif field_name == "docsIf3CmSpectrumAnalysisCtrlCmdFileEnable":
                    obj_value = Snmp_v2c.TRUE if spectrum_retrieval_type == SpectrumRetrievalType.FILE else Snmp_v2c.FALSE
                    self.logger.debug(f'Setting File Retrival, Set-And-Go({set_and_go}) -> Value: {obj_value}')

                ###############################################
                # Set Field setting not change by above rules #
                ###############################################
                if isinstance(obj_value, Enum):
                    obj_value = str(obj_value.value)
                    self.logger.debug(f'ENUM Found: Set Value Type: {obj_value} -> {type(obj_value)}')
                else:
                    obj_value = str(obj_value)

                self.logger.debug(f'{field_name} -> Set Value Type: {obj_value} -> {type(obj_value)}')

                if not await __snmp_set(field_name, obj_value, snmp_type):
                    self.logger.error(f'Fail to set {field_name} to {obj_value}')
                    return False

            return True

        except Exception:
            logging.exception("Exception while setting DocsIf3CmSpectrumAnalysisCtrlCmd")
            return False

    async def setDocsPnmCmUsPreEq(self, ofdma_idx: int, filename:str, last_pre_eq_filename:str, set_and_go:bool=True) -> bool:
        """
        Set the upstream Pre-EQ file name and enable Pre-EQ capture for a specified OFDMA channel index.

        Args:
            ofdma_idx (int): Index in the DocsPnmCmUsPreEq SNMP table.
            file_name (str): Desired file name to use for Pre-EQ capture.

        Returns:
            bool: True if both SNMP set operations succeed and verify expected values; False otherwise.
        """
        try:
            oid = f'{"docsPnmCmUsPreEqFileName"}.{ofdma_idx}'
            self.logger.debug(f'Setting Pre-EQ filename: [{oid}] = "{filename}"')
            response = await self._snmp.set(oid, filename, OctetString)
            result = Snmp_v2c.snmp_set_result_value(response)

            if not result or str(result[0]) != filename:
                self.logger.error(f'Filename mismatch. Expected "{filename}", got "{result[0] if result else "None"}"')
                return False

            oid = f'{"docsPnmCmUsPreEqLastUpdateFileName"}.{ofdma_idx}'
            self.logger.debug(f'Setting Last-Pre-EQ filename: [{oid}] = "{last_pre_eq_filename}"')
            response = await self._snmp.set(oid, last_pre_eq_filename, OctetString)
            result = Snmp_v2c.snmp_set_result_value(response)

            if not result or str(result[0]) != last_pre_eq_filename:
                self.logger.error(f'Filename mismatch. Expected "{last_pre_eq_filename}", got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                time.sleep(1)
                enable_oid = f'{"docsPnmCmUsPreEqFileEnable"}.{ofdma_idx}'
                self.logger.debug(f'Enabling Pre-EQ capture [{enable_oid}] = {Snmp_v2c.TRUE}')
                response = await self._snmp.set(enable_oid, Snmp_v2c.TRUE, Integer32)
                result = Snmp_v2c.snmp_set_result_value(response)

                if not result or int(result[0]) != Snmp_v2c.TRUE:
                    self.logger.error(f'Failed to enable Pre-EQ capture. Expected 1, got "{result[0] if result else "None"}"')
                    return False

            return True

        except Exception as e:
            self.logger.exception(f'Exception during setDocsPnmCmUsPreEq for index {ofdma_idx}: {e}')
            return False

    async def setDocsPnmCmDsOfdmModProf(self, ofdm_idx: int, mod_prof_file_name: str, set_and_go:bool=True) -> bool:
        """
        Set the DocsPnmCmDsOfdmModProf parameters for a given OFDM index.

        Parameters:
        - ofdm_idx (int): The index of the OFDM channel.
        - mod_prof_file_name (str): The filename to set for the modulation profile.

        Returns:
        - bool: True if both SNMP sets were successful, False otherwise.
        """
        try:
            file_oid = f'{"docsPnmCmDsOfdmModProfFileName"}.{ofdm_idx}'
            enable_oid = f'{"docsPnmCmDsOfdmModProfFileEnable"}.{ofdm_idx}'

            file_response = await self._snmp.set(file_oid, mod_prof_file_name, OctetString)
            self.logger.debug(f'Set {file_oid} to {mod_prof_file_name}: {file_response}')

            if set_and_go:
                enable_response = await self._snmp.set(enable_oid, Snmp_v2c.TRUE, Integer32)
                self.logger.debug(f'Set {enable_oid} to 1 (enable): {enable_response}')

            return True

        except Exception as e:
            self.logger.error(f"Failed to set DocsPnmCmDsOfdmModProf for index {ofdm_idx}: {e}")
            return False

    async def setDocsPnmCmDsOfdmRxMer(self, ofdm_idx: int, rxmer_file_name: str, set_and_go:bool=True) -> bool:
        """
        Sets the RxMER file name and enables file capture for a specified OFDM channel index.

        Parameters:
        - ofdm_idx (str): The index in the DocsPnmCmDsOfdmRxMer SNMP table.
        - rxmer_file_name (str): Desired file name to assign for RxMER capture.

        Returns:
        - bool: True if both SNMP set operations succeed and return expected values, False otherwise.
        """
        try:
            oid_file_name = f'{"docsPnmCmDsOfdmRxMerFileName"}.{ofdm_idx}'
            set_response = await self._snmp.set(oid_file_name, rxmer_file_name, OctetString)
            self.logger.debug(f'Setting RxMER file name [{oid_file_name}] = "{rxmer_file_name}"')

            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or str(result[0]) != rxmer_file_name:
                self.logger.error(f'File name mismatch. Expected "{rxmer_file_name}", got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                oid_file_enable = f'{"docsPnmCmDsOfdmRxMerFileEnable"}.{ofdm_idx}'
                set_response = await self._snmp.set(oid_file_enable, 1, Integer32)
                self.logger.debug(f'Enabling RxMER capture [{oid_file_enable}] = 1')

                result = Snmp_v2c.snmp_set_result_value(set_response)
                if not result or int(result[0]) != 1:
                    self.logger.error(f'Failed to enable RxMER capture. Expected 1, got "{result[0] if result else "None"}"')
                    return False

            return True

        except Exception as e:
            self.logger.exception(f'Exception during setDocsPnmCmDsOfdmRxMer for index {ofdm_idx}: {e}')
            return False

    async def setDocsPnmCmDsOfdmFecSum(self, ofdm_idx: int,
                                       fec_sum_file_name: str,
                                       fec_sum_type: FecSummaryType = FecSummaryType.TEN_MIN,
                                       set_and_go:bool=True) -> bool:
        """
        Sets SNMP parameters for FEC summary of an OFDM channel.

        Parameters:
        - ofdm_idx (str): The OFDM index.
        - fec_sum_file_name (str): The file name associated with FEC sum.
        - fec_sum_type (FecSummaryType): The type of FEC summary (default is 10 minutes).

        Returns:
        - bool: True if successful, False if any error occurs during SNMP operations.
        """
        try:
            oid_file_name = f'{"docsPnmCmDsOfdmFecFileName"}.{ofdm_idx}'
            self.logger.debug(f'Setting FEC file name [{oid_file_name}] = "{fec_sum_file_name}"')
            set_response = await self._snmp.set(oid_file_name, fec_sum_file_name, OctetString)
            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or str(result[0]) != fec_sum_file_name:
                self.logger.error(f'File name mismatch. Expected "{fec_sum_file_name}", got "{result[0] if result else "None"}"')
                return False

            oid_sum_type = f'{"docsPnmCmDsOfdmFecSumType"}.{ofdm_idx}'
            self.logger.debug(f'Setting FEC sum type [{oid_sum_type}] = {fec_sum_type.name} -> {type(fec_sum_type.value)}')
            set_response = await self._snmp.set(oid_sum_type, fec_sum_type.value, Integer32)
            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or int(result[0]) != fec_sum_type.value:
                self.logger.error(f'FEC sum type mismatch. Expected {fec_sum_type.value}, got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                oid_file_enable = f'{"docsPnmCmDsOfdmFecFileEnable"}.{ofdm_idx}'
                self.logger.debug(f'Enabling FEC file capture [{oid_file_enable}] = 1')
                set_response = await self._snmp.set(oid_file_enable, 1, Integer32)
                result = Snmp_v2c.snmp_set_result_value(set_response)
                if not result or int(result[0]) != 1:
                    self.logger.error(f'Failed to enable FEC capture. Expected 1, got "{result[0] if result else "None"}"')
                    return False

            self.logger.debug(f'Successfully configured FEC summary capture for OFDM index {ofdm_idx}')
            return True

        except Exception as e:
            self.logger.exception(f'Exception during setDocsPnmCmDsOfdmFecSum for index {ofdm_idx}: {e}')
            return False

    async def setDocsPnmCmOfdmChEstCoef(self, ofdm_idx: int, chan_est_file_name: str, set_and_go:bool=True) -> bool:
        """
        Sets SNMP parameters for OFDM channel estimation coefficients.

        Parameters:
        - ofdm_idx (str): The OFDM index.
        - chan_est_file_name (str): The file name associated with the OFDM Channel Estimation.

        Returns:
        - bool: True if the SNMP set operations were successful, False otherwise.
        """
        try:
            oid_file_name = f'{"docsPnmCmOfdmChEstCoefFileName"}.{ofdm_idx}'
            self.logger.debug(f'Setting OFDM Channel Estimation File Name [{oid_file_name}] = "{chan_est_file_name}"')
            set_response = await self._snmp.set(oid_file_name, chan_est_file_name, OctetString)

            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or str(result[0]) != chan_est_file_name:
                self.logger.error(f'Failed to set channel estimation file name. Expected "{chan_est_file_name}", got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                oid_trigger_enable = f'{"docsPnmCmOfdmChEstCoefTrigEnable"}.{ofdm_idx}'
                self.logger.debug(f'Setting Channel Estimation Trigger Enable [{oid_trigger_enable}] = 1')
                set_response = await self._snmp.set(oid_trigger_enable, Snmp_v2c.TRUE, Integer32)

                result = Snmp_v2c.snmp_set_result_value(set_response)
                if not result or int(result[0]) != 1:
                    self.logger.error(f'Failed to enable channel estimation trigger. Expected 1, got "{result[0] if result else "None"}"')
                    return False

            self.logger.debug(f'Successfully configured OFDM channel estimation for index {ofdm_idx} with file name "{chan_est_file_name}"')

        except Exception as e:
            self.logger.exception(f'Exception occurred while setting OFDM Channel Estimation coefficients for index {ofdm_idx}: {e}')
            return False

        return True

    async def setDocsPnmCmDsConstDisp(
        self,
        ofdm_idx: int,
        const_disp_name: str,
        modulation_order_offset: int = CmDsConstellationDisplayConst.MODULATION_OFFSET.value,
        number_sample_symbol: int = CmDsConstellationDisplayConst.NUM_SAMPLE_SYMBOL.value,
        set_and_go: bool = True ) -> bool:
        """
        Configures SNMP parameters for the OFDM Downstream Constellation Display.

        Args:
            ofdm_idx (int): Index of the downstream OFDM channel.
            const_disp_name (str): Desired filename to store the constellation display data.
            modulation_offset (int, optional): Modulation order offset. Defaults to standard constant value.
            num_sample_symb (int, optional): Number of sample symbols. Defaults to standard constant value.
            set_and_go (bool, optional): If True, triggers immediate measurement start. Defaults to True.

        Returns:
            bool: True if all SNMP SET operations succeed; False otherwise.
        """
        try:
            # Set file name
            oid = f'{"docsPnmCmDsConstDispFileName"}.{ofdm_idx}'
            self.logger.debug(f'Setting FileName [{oid}] = "{const_disp_name}"')
            set_response = await self._snmp.set(oid, const_disp_name, OctetString)
            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or str(result[0]) != const_disp_name:
                self.logger.error(f'Failed to set FileName. Expected "{const_disp_name}", got "{result[0] if result else "None"}"')
                return False

            # Set modulation order offset
            oid = f'{"docsPnmCmDsConstDispModOrderOffset"}.{ofdm_idx}'
            self.logger.debug(f'Setting ModOrderOffset [{oid}] = {modulation_order_offset}')
            set_response = await self._snmp.set(oid, modulation_order_offset, Gauge32)
            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or int(result[0]) != modulation_order_offset:
                self.logger.error(f'Failed to set ModOrderOffset. Expected {modulation_order_offset}, got "{result[0] if result else "None"}"')
                return False

            # Set number of sample symbols
            oid = f'{"docsPnmCmDsConstDispNumSampleSymb"}.{ofdm_idx}'
            self.logger.debug(f'Setting NumSampleSymb [{oid}] = {number_sample_symbol}')
            set_response = await self._snmp.set(oid, number_sample_symbol, Gauge32)
            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or int(result[0]) != number_sample_symbol:
                self.logger.error(f'Failed to set NumSampleSymb. Expected {number_sample_symbol}, got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                # Trigger measurement
                oid = f'{"docsPnmCmDsConstDispTrigEnable"}.{ofdm_idx}'
                self.logger.debug(f'Setting TrigEnable [{oid}] = 1')
                set_response = await self._snmp.set(oid, Snmp_v2c.TRUE, Integer32)
                result = Snmp_v2c.snmp_set_result_value(set_response)
                if not result or int(result[0]) != 1:
                    self.logger.error(f'Failed to trigger measurement. Expected 1, got "{result[0] if result else "None"}"')
                    return False

            self.logger.debug(
                f'Successfully configured Constellation Display for OFDM index {ofdm_idx} with file name "{const_disp_name}"'
            )
            return True

        except Exception as e:
            self.logger.exception(
                f'Exception occurred while setting Constellation Display for OFDM index {ofdm_idx}: {e}'
            )
            return False

    async def setDocsCmLatencyRptCfg(self, latency_rpt_file_name: str, num_of_reports: int = 1, set_and_go:bool=True) -> bool:
        """
        Configures the CM upstream latency reporting feature. This enables
        the creation of latency report files containing per-Service Flow
        latency measurements over a defined period of time.

        Parameters:
        - latency_rpt_file_name (str): The filename to store the latency report.
        - num_of_reports (int): Number of report files to generate.

        Returns:
        - bool: True if configuration is successful, False otherwise.
        """

        mac_idx = self.getIfTypeIndex(DocsisIfType.docsCableMaclayer)[0]

        try:
            oid_file_name = f'{"docsCmLatencyRptCfgFileName"}.{mac_idx}'
            self.logger.debug(f'Setting US Latency Report file name [{oid_file_name}] = "{latency_rpt_file_name}"')
            set_response = await self._snmp.set(oid_file_name, latency_rpt_file_name, OctetString)
            result = Snmp_v2c.snmp_set_result_value(set_response)

            if not result or str(result[0]) != latency_rpt_file_name:
                self.logger.error(f'File name mismatch. Expected "{latency_rpt_file_name}", got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                oid_num_reports = f'{"docsCmLatencyRptCfgNumFiles"}.{mac_idx}'
                self.logger.debug(f'Setting number of latency reports [{oid_num_reports}] = {num_of_reports}')
                set_response = await self._snmp.set(oid_num_reports, num_of_reports, Gauge32)
                result = Snmp_v2c.snmp_set_result_value(set_response)

                if not result or int(result[0]) != num_of_reports:
                    self.logger.error(f'Failed to enable latency report capture. Expected {num_of_reports}, got "{result[0] if result else "None"}"')
                    return False

            return True

        except Exception as e:
            self.logger.exception(f'Exception during setDocsCmLatencyRptCfg: {e}')
            return False

    async def setDocsPnmCmDsHist(self, ds_histogram_file_name: str, set_and_go:bool=True, timeout:int=10) -> bool:
        """
        Configure and enable downstream histogram capture for the CM MAC layer interface.

        This method performs the following steps:
        1. Retrieves the index for the `docsCableMaclayer` interface.
        2. Sets the histogram file name via Snmp_v2c.
        3. Enables histogram data capture via Snmp_v2c.

        Args:
            ds_histogram_file_name (str): The name of the file where the downstream histogram will be saved.

        Returns:
            bool: True if the file name was set and capture was successfully enabled, False otherwise.

        Logs:
            - debug: Index being used.
            - Debug: SNMP set operations for file name and capture enable.
            - Error: Mismatched response or SNMP failure.
            - Exception: Any exception that occurs during the SNMP operations.
        """
        idx_list = await self.getIfTypeIndex(DocsisIfType.docsCableMaclayer)

        if not idx_list:
            self.logger.error("No index found for docsCableMaclayer interface type.")
            return False

        if len(idx_list) > 1:
            self.logger.error(f"Expected a single index for docsCableMaclayer, but found multiple: {idx_list}")
            return False

        idx = idx_list[0]

        self.logger.debug(f'setDocsPnmCmDsHist -> idx: {idx}')

        try:
            # TODO: Need to make this dynamic
            set_response = await self._snmp.set(f'{"docsPnmCmDsHistTimeOut"}.{idx}', timeout, Gauge32)
            self.logger.debug(f'Setting Histogram Timeout: {timeout}')

            oid_file_name = f'{"docsPnmCmDsHistFileName"}.{idx}'
            set_response = await self._snmp.set( oid_file_name, ds_histogram_file_name, OctetString)
            self.logger.debug(f'Setting Histogram file name [{oid_file_name}] = "{ds_histogram_file_name}"')

            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or str(result[0]) != ds_histogram_file_name:
                self.logger.error(f'File name mismatch. Expected "{ds_histogram_file_name}", got "{result[0] if result else "None"}"')
                return False

            if set_and_go:
                oid_file_enable = f'{"docsPnmCmDsHistEnable"}.{idx}'
                set_response = await self._snmp.set(oid_file_enable, Snmp_v2c.TRUE, Integer32)
                self.logger.debug(f'Enabling Histogram capture [{oid_file_enable}] = 1')

                result = Snmp_v2c.snmp_set_result_value(set_response)
                if not result or int(result[0]) != 1:
                    self.logger.error(f'Failed to enable Histogram capture. Expected 1, got "{result[0] if result else "None"}"')
                    return False

        except Exception as e:
            self.logger.exception(f'Exception during setDocsPnmCmDsHist for index {idx}: {e}')
            return False

        return True

    async def setDocsPnmCmDsOfdmSymTrig(self, ofdm_idx: int, symbol_trig_file_name: str) -> bool:
        """
        Sets SNMP parameters for OFDM Downstream Symbol Capture.

        Parameters:
        - ofdm_idx (str): The OFDM index.
        - symbol_trig_file_name (str): The file name associated with the OFDM Downstream Symbol Capture

        Returns:
        - bool: True if the SNMP set operations were successful, False otherwise.
        TODO: NOT ABLE TO TEST DUE TO CMTS DOES NOT SUPPORT
        """
        try:
            oid_file_name = f'{"docsPnmCmDsOfdmSymCaptFileName"}.{ofdm_idx}'
            self.logger.debug(f'Setting OFDM Downstream Symbol Capture File Name [{oid_file_name}] = "{symbol_trig_file_name}"')
            set_response = await self._snmp.set(oid_file_name, symbol_trig_file_name, OctetString)

            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or str(result[0]) != symbol_trig_file_name:
                self.logger.error(f'Failed to set Downstream Symbol Capture file name. Expected "{symbol_trig_file_name}", got "{result[0] if result else "None"}"')
                return False

            oid_trigger_enable = f'{"docsPnmCmDsConstDispTrigEnable"}.{ofdm_idx}'
            self.logger.debug(f'Setting OFDM Downstream Symbol Capture Trigger Enable [{oid_trigger_enable}] = 1')
            set_response = await self._snmp.set(oid_trigger_enable, 1, Integer32)

            result = Snmp_v2c.snmp_set_result_value(set_response)
            if not result or int(result[0]) != 1:
                self.logger.error(f'Failed to enable OFDM Downstream Symbol Capture trigger. Expected 1, got "{result[0] if result else "None"}"')
                return False

            self.logger.debug(f'Successfully configured OFDM Downstream Symbol Capturey for index {ofdm_idx} with file name "{symbol_trig_file_name}"')
            return True

        except Exception as e:
            self.logger.exception(f'Exception occurred while setting OFDM Downstream Symbol Capture for index {ofdm_idx}: {e}')
            return False

    async def getDocsIf3CmStatusUsEqData(self) -> DocsEqualizerData:
        """
        Retrieve and parse DOCSIS 3.0/3.1 upstream equalizer data via Snmp_v2c.

        This method performs an SNMP walk on the OID corresponding to
        `docsIf3CmStatusUsEqData`, which contains the pre-equalization
        coefficient data for upstream channels.

        It parses the SNMP response into a structured `DocsEqualizerData` object.

        Returns:
            DocsEqualizerData: Parsed equalizer data including real/imaginary tap coefficients
            for each upstream channel index.
            Returns None if SNMP walk fails, no data is returned, or parsing fails.
        """
        oid = 'docsIf3CmStatusUsEqData'
        try:
            result = await self._snmp.walk(oid)

        except Exception as e:
            self.logger.error(f"SNMP walk failed for {oid}: {e}")
            return DocsEqualizerData()

        if not result:
            self.logger.warning(f"No data returned from SNMP walk for {oid}.")
            return DocsEqualizerData()

        ded = DocsEqualizerData()

        try:
            for varbind in result:
                us_idx = Snmp_v2c.extract_last_oid_index([varbind])[0]
                eq_data = Snmp_v2c.snmp_get_result_value([varbind])[0]
                eq_data = Format.non_ascii_to_hex(eq_data)
                self.logger.debug(f'idx: {us_idx} -> eq-data: ({eq_data})')
                ded.add(us_idx, eq_data)

        except ValueError as e:
            self.logger.error(f"Failed to parse equalizer data. Error: {e}")
            return None

        if not ded.coefficients_found():
            self.logger.warning(
                "No upstream pre-equalization coefficients found. "
                "Ensure Pre-Equalization is enabled on the upstream interface(s).")

        return ded

# FILE: src/pypnm/snmp/snmp_v2c.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    bulk_cmd,
    get_cmd,
    set_cmd,
    walk_cmd,
)
from pysnmp.proto.rfc1902 import Integer32, OctetString

from pypnm.config.pnm_config_manager import SystemConfigSettings
from pypnm.lib.constants import T
from pypnm.lib.inet import Inet
from pypnm.lib.inet_utils import InetGenerate
from pypnm.lib.types import (
    InetAddressStr,
    InterfaceIndex,
    SnmpIndex,
    SnmpReadCommunity,
    SnmpWriteCommunity,
)
from pypnm.snmp.compiled_oids import COMPILED_OIDS
from pypnm.snmp.modules import InetAddressType


class Snmp_v2c:
    """
    SNMPv2c Client for asynchronous GET, SET, and WALK operations.

    Attributes:
        host (str): Hostname or IP address of the SNMP agent.
        port (int): Port number used for SNMP (default is 161).
        read_community (str): Community string for SNMP GET/WALK (default from config).
        write_community (str): Community string for SNMP SET (default from config).
        _snmp_engine (SnmpEngine): Instance of pysnmp SnmpEngine.

    Class Attributes:
        COMPILE_MIBS (bool): Whether to compile MIBs for OID resolution.
        SNMP_PORT (int): Default SNMP port.

    Example:
        >>> snmp = Snmp_v2c(Inet('192.168.1.1'), community='public')
        >>> await snmp.get('1.3.6.1.2.1.1.1.0')
        >>> await snmp.walk('1.3.6.1.2.1.2')
        >>> await snmp.set('1.3.6.1.2.1.1.5.0', 'NewHostName')
        >>> snmp.close()
    """

    DISABLE = 1
    ENABLE = 2

    TRUE = 1
    FALSE = 2

    SNMP_PORT = 161

    def __init__(
        self,
        host: Inet,
        community: str | None = None,
        read_community: SnmpReadCommunity | None = None,
        write_community: SnmpWriteCommunity | None = None,
        port: int = SNMP_PORT,
        timeout: int = SystemConfigSettings.snmp_timeout(),
        retries: int = SystemConfigSettings.snmp_retries(),
    ) -> None:
        """
        Initializes the SNMPv2c client.

        Args:
            host (Inet): Host address of the SNMP device.
            community (str | None): Legacy community string for SNMP access.
            read_community (SnmpReadCommunity | None): Read community string override.
            write_community (SnmpWriteCommunity | None): Write community string override.
            port (int): SNMP port (default 161).
        """
        self.logger     = logging.getLogger(self.__class__.__name__)
        self._host      = host.inet
        self._port      = port
        if read_community is not None:
            self._read_community = str(read_community)
        elif community is not None:
            self._read_community = str(community)
        else:
            self._read_community = str(SystemConfigSettings.snmp_read_community())

        if write_community is not None:
            self._write_community = str(write_community)
        elif community is not None:
            self._write_community = str(community)
        else:
            self._write_community = str(SystemConfigSettings.snmp_write_community())

        if self._write_community == "":
            self._write_community = self._read_community
        self._timeout   = timeout
        self._retries   = retries
        self._snmp_engine = SnmpEngine()

    async def get(
        self,
        oid: str | tuple[str, str, int],
        timeout: float | None = None,
        retries: int | None = None,
    ) -> list[ObjectType] | None:
        """
        Perform an SNMP GET operation.

        Notes
        -----
        `timeout` for UdpTransportTarget.create(...) is in **seconds**, not milliseconds.

        Args:
            oid: OID to fetch, either as a numeric string, symbolic name, or tuple.
            timeout: Request timeout in **seconds**. If None, uses self._timeout.
            retries: Number of retries. If None, uses self._retries.

        Returns:
            Optional[List[ObjectType]]: List of SNMP variable bindings or None if no result.

        Raises:
            RuntimeError: On SNMP errors (transport/protocol).
        """
        self.logger.debug(f"Input OID: {oid}, timeout: {timeout}, retries: {retries}")

        resolved_oid = Snmp_v2c.resolve_oid(oid)
        obj = ObjectType(self._to_object_identity(resolved_oid))

        timeout_s = float(timeout if timeout is not None else self._timeout)
        retries_n = int(retries if retries is not None else self._retries)

        errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
            self._snmp_engine,
            CommunityData(self._read_community, mpModel=1),
            await UdpTransportTarget.create((self._host, self._port),
                                            timeout=timeout_s,     # seconds
                                            retries=retries_n,     # count
                                            ),
            ContextData(),
            obj,
        )

        try:
            self._raise_on_snmp_error(errorIndication, errorStatus, errorIndex)
        except Exception as e:
            self.logger.error(f"Failed GET for OID {resolved_oid}: {e}")

        return varBinds

    async def walk(self, oid: str | tuple[str, str, int]) -> list[ObjectType] | None:
        """
        Perform an SNMP WALK operation.

        Args:
            oid (str | Tuple[str, str, int]): The starting OID for the walk.

        Returns:
            Optional[List[ObjectType]]: List of walked SNMP ObjectTypes, or None if no results.
        """
        self.logger.debug(f"Starting SNMP WALK with OID: {oid}")
        oid = Snmp_v2c.resolve_oid(oid)
        self.logger.debug(f"Converted: {oid}")

        identity = self._to_object_identity(oid)
        obj = ObjectType(identity)
        results: list[ObjectType] = []

        transport = await UdpTransportTarget.create((self._host, self._port),
                                                    timeout=self._timeout,
                                                    retries=self._retries)

        objects = walk_cmd(
            self._snmp_engine,
            CommunityData(self._read_community, mpModel=1),
            transport,
            ContextData(),
            obj
        )

        async for item in objects:

            errorIndication, errorStatus, errorIndex, varBinds = item

            try:
                self._raise_on_snmp_error(errorIndication, errorStatus, errorIndex)

            except Exception as e:
                self.logger.error(f"Failed walk : {e}")
                continue

            if not varBinds:
                continue

            for varBind in varBinds:
                oid_str = str(varBind[0])

                if not self._is_oid_in_subtree(oid_str, str(identity)):
                    self.logger.debug(f"End of OID subtree reached at {oid_str} -> {varBind} - List size {len(results)}")
                    return results if results else None

                results.append(varBind)

        self.logger.debug(f'List size {len(results)}')

        return results if results else None

    async def bulk_walk(
        self,
        oid: str | tuple[str, str, int],
        non_repeaters: int = 0,
        max_repetitions: int = 25,
        suppress_no_such_name: bool = True,
    ) -> list[ObjectType] | None:
        """
        Perform an SNMP GETBULK operation (faster alternative to WALK).

        GETBULK is an SNMPv2c/v3 operation that retrieves multiple variables
        in a single request, making it significantly faster than traditional
        WALK operations for large tables.

        Args:
            oid (str | Tuple[str, str, int]): The starting OID for the bulk walk.
            non_repeaters (int): Number of OIDs from the start that should not be repeated.
                                 Default is 0 (repeat all).
            max_repetitions (int): Maximum number of repetitions for repeating variables.
                                   Default is 25. Higher values = fewer requests but
                                   larger packets. Typical range: 10-50.

        Returns:
            Optional[List[ObjectType]]: List of SNMP ObjectTypes retrieved, or None if no results.

        Notes:
            - GETBULK is more efficient than WALK for large MIB tables
            - Not supported by SNMPv1 agents (will fall back to WALK)
            - max_repetitions should be tuned based on network conditions:
              * Small networks: 25-50
              * Large/slow networks: 10-25
              * Very fast networks: 50-100
        """
        oid = Snmp_v2c.resolve_oid(oid)

        identity = self._to_object_identity(oid)
        attempt_values: list[int] = []
        for value in [max_repetitions, 10, 5, 1]:
            if value > 0 and value not in attempt_values:
                attempt_values.append(value)

        last_error: str | None = None

        for attempt in attempt_values:
            self.logger.debug(
                f"Starting SNMP BULK WALK with OID: {oid}, non_repeaters={non_repeaters}, max_repetitions={attempt}"
            )
            obj = ObjectType(identity)
            results: list[ObjectType] = []
            retry = False
            hard_error = False

            transport = await UdpTransportTarget.create(
                (self._host, self._port),
                timeout=self._timeout,
                retries=self._retries
            )

            objects = await bulk_cmd(
                self._snmp_engine,
                CommunityData(self._read_community, mpModel=1),
                transport,
                ContextData(),
                non_repeaters,
                attempt,
                obj
            )

            def _process_item(
                item: tuple[object, object, object, list[ObjectType]],
                attempt_value: int,
                identity_value: object,
                results_list: list[ObjectType],
            ) -> tuple[bool, bool, bool, str | None]:
                errorIndication, errorStatus, errorIndex, varBinds = item

                if errorIndication or errorStatus:
                    status_text = ""
                    if errorStatus:
                        pretty = getattr(errorStatus, "prettyPrint", None)
                        status_text = pretty() if callable(pretty) else str(errorStatus)
                    error_message = status_text or str(errorIndication)

                    if status_text == "tooBig":
                        self.logger.warning(
                            f"Bulk walk tooBig with max_repetitions={attempt_value}; retrying with smaller value."
                        )
                        return True, True, False, error_message

                    if status_text == "noSuchName" and suppress_no_such_name:
                        self.logger.debug(f"Failed bulk walk: {error_message}")
                    else:
                        self.logger.error(f"Failed bulk walk: {error_message}")
                    return True, False, True, error_message

                if not varBinds:
                    return False, False, False, None

                for varBind in varBinds:
                    oid_str = str(varBind[0])

                    if not self._is_oid_in_subtree(oid_str, str(identity_value)):
                        self.logger.debug   (
                            f"End of OID subtree reached at {oid_str} -> {varBind} - List size {len(results_list)}"
                        )
                        return True, False, False, None

                    results_list.append(varBind)

                return False, False, False, None

            if isinstance(objects, tuple) and len(objects) == 4:
                done, retry, hard_error, error_message = _process_item(
                    objects,
                    attempt,
                    identity,
                    results,
                )
                if error_message:
                    last_error = error_message
                if done and results:
                    return results
            elif isinstance(objects, AsyncIterable):
                async for item in objects:
                    done, retry, hard_error, error_message = _process_item(
                        item,
                        attempt,
                        identity,
                        results,
                    )
                    if error_message:
                        last_error = error_message
                    if done:
                        if results:
                            return results
                        break
            else:
                last_error = f"unexpected bulk_cmd result type: {type(objects).__name__}"
                self.logger.error(f"Failed bulk walk: {last_error}")
                hard_error = True

            if hard_error:
                break
            if results:
                self.logger.debug(f'Bulk walk completed - List size {len(results)}')
                return results
            if retry:
                continue

            self.logger.debug(f"Bulk walk returned no data with max_repetitions={attempt}.")

        if last_error:
            if last_error == "noSuchName" and suppress_no_such_name:
                self.logger.debug(f"Bulk walk failed or empty ({last_error}); falling back to walk.")
            else:
                self.logger.warning(f"Bulk walk failed or empty ({last_error}); falling back to walk.")
        else:
            self.logger.warning("Bulk walk returned no data; falling back to walk.")

        return await self.walk(oid)

    async def set(self, oid: str, value: str | int, value_type: type)-> list[ObjectType] | None:
        """
        Perform an SNMP SET operation with explicit value type.

        Args:
            oid (str): The OID to set.
            value (Union[str, int]): The value to set.
            value_type (Type): pysnmp value type class (no default).

                Examples:
                    OctetString, Integer, Integer32, Counter32, Counter64, Gauge32, IpAddress.

        Returns:
            Dict[str, str]: Mapping of OID to the set value.

        Raises:
            ValueError: If value type instantiation fails.
            RuntimeError: On SNMP errors.
        """
        if value_type is None:
            raise ValueError("value_type must be explicitly specified")

        self.logger.debug(f'SNMP-SET-OID: {oid} -> {value_type} -> {value}')

        oid = Snmp_v2c.resolve_oid(oid)

        transport = await UdpTransportTarget.create((self._host, self._port),
                                                    timeout=self._timeout, retries=self._retries)

        try:
            snmp_value = value_type(value)
        except Exception as e:
            raise ValueError(f"Failed to create SNMP value of type {value_type}: {e}") from e

        errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(
            self._snmp_engine,
            CommunityData(self._write_community, mpModel=1),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(oid), snmp_value),
        )
        try:
            self._raise_on_snmp_error(errorIndication, errorStatus, errorIndex)

        except Exception as e:
            self.logger.error(f"Error extracting SNMP value: {e}")
            return None

        return varBinds # type: ignore

    def close(self) -> None:
        """
        Close the SNMP engine dispatcher and release resources.
        """
        self._snmp_engine.close_dispatcher()

    @staticmethod
    def resolve_oid(oid: str | tuple[str, str, int]) -> str:
        """
        Resolves symbolic OIDs with optional numeric suffixes.

        Examples:
            'ifDescr'             → '1.3.6.1.2.1.2.2.1.2'
            'ifDescr.2'           → '1.3.6.1.2.1.2.2.1.2.2'
            '1.3.6.1.2.1.2.2.1.2' → '1.3.6.1.2.1.2.2.1.2' (unchanged)

        Returns:
            str: Fully resolved numeric OID string.
        """
        if isinstance(oid, tuple):
            # Optional support for Tuple format: (base, suffix1, suffix2)
            oid = '.'.join(map(str, oid))

        if Snmp_v2c.is_numeric_oid(oid):
            return oid

        # Split symbolic base from numeric suffix
        match = re.match(r"^([a-zA-Z0-9_:]+)(\..+)?$", oid)
        if not match:
            return oid  # fallback: invalid pattern

        base_sym, suffix = match.groups()
        base_num = COMPILED_OIDS.get(base_sym, base_sym)
        return f"{base_num}{suffix or ''}"

    @staticmethod
    def is_numeric_oid(oid: str) -> bool:
        """
        Returns True if the OID string is numeric.

        Accepted formats:
            - '1.3.6.1.2.1.2.2.1.2'
            - '.1.3.6.1.2.1.2.2.1.2'  (leading dot is allowed)

        Returns:
            bool: True if the OID is numeric, False otherwise.
        """
        return bool(re.fullmatch(r"\.?(\d+\.)+\d+", oid))

    @staticmethod
    def get_result_value(pysnmp_get_result: ObjectType | tuple[ObjectType, ...] | None) -> str | None:
        """
        Extract the value from a pysnmp GET result.

        Args:
            pysnmp_get_result: SNMP response from get().

        Returns:
            Optional[str]: The extracted value as string, or None if not found.
        """
        try:
            if isinstance(pysnmp_get_result, tuple):
                pysnmp_get_result = pysnmp_get_result[0]

            if isinstance(pysnmp_get_result, ObjectType):
                value = pysnmp_get_result[1]
                if isinstance(value, OctetString):
                    return value.prettyPrint()
                return str(value)

            return None

        except Exception as e:
            logging.debug(f"Error extracting SNMP value: {e}")
            return None

    @staticmethod
    def extract_last_oid_index(snmp_responses: list[ObjectType]) -> list[int]:
        """
        Extract the last index from a list of SNMP responses.

        Parameters:
        - snmp_responses: List of SNMP responses.

        Returns:
        - List of extracted indices.
        """
        last_oid_indexes = []
        for response in snmp_responses:
            oid = response[0]
            index = Snmp_v2c.get_oid_index(oid)
            logging.debug(f'extract_last_oid_index-IN-LOOP -> {response} -> {oid} -> {index}')
            last_oid_indexes.append(index)
        return last_oid_indexes

    @staticmethod
    def extract_oid_indices(snmp_responses: list[ObjectType],num_indices: int = 1) -> list[list[SnmpIndex]]:
        """
        Extract the last `num_indices` components from the OID index of each SNMP response.

        Parameters:
        - snmp_responses: List of SNMP responses.
        - num_indices: Number of trailing OID index components to extract.

        Returns:
        - List of lists, each containing the extracted index components.
        """
        extracted_indices:list[list[SnmpIndex]] = []

        for response in snmp_responses:
            oid = response[0]
            full_index = Snmp_v2c.get_oid_index(oid)

            if isinstance(full_index, int):
                indices = [full_index]
            elif isinstance(full_index, (list, tuple)):
                indices = list(full_index)
            else:
                logging.warning(f"Unexpected OID index format: {full_index}")
                continue

            selected = indices[-num_indices:] if len(indices) >= num_indices else indices
            logging.debug(f"extract_oid_indices -> {response} -> {oid} -> {selected}")
            extracted_indices.append(selected)

        return extracted_indices

    @staticmethod
    def snmp_get_result_value(snmp_responses: list[ObjectType]) -> list[str]:
        """
        Extract the result value from a list of SNMP responses.

        Args:
            snmp_responses (List[ObjectType]): List of SNMP ObjectType responses.

        Returns:
            List[str]: List of extracted result values as strings.
        """
        return [str(value[1]) for value in snmp_responses]

    @staticmethod
    def snmp_get_result_bytes(snmp_responses: list[ObjectType]) -> list[bytes]:
        """
        Extract raw byte values from a list of SNMP ObjectType responses.

        Args:
            snmp_responses (List[ObjectType]): List of SNMP ObjectType responses.

        Returns:
            List[bytes]: List of extracted result values as bytes.
        """
        result = []
        for varbind in snmp_responses:
            value = varbind[1]
            # Attempt to get raw bytes directly if available
            if hasattr(value, 'asOctets'):
                result.append(value.asOctets())
            elif isinstance(value, bytes):
                result.append(value)
            else:
                # Fallback: try encoding string representation
                result.append(str(value).encode())
        return result

    @staticmethod
    def snmp_get_result_last_idx_value(snmp_responses: list[ObjectType]) -> list[tuple[InterfaceIndex, str]]:
        """
        Extract the last index and value from each SNMP response.

        Args:
            snmp_responses (List[ObjectType]): List of SNMP ObjectType responses.

        Returns:
            List[Tuple[InterfaceIndex, str]]: List of (last InterfaceIndex, value) pairs.
        """
        result = []
        for obj in snmp_responses:
            oid = obj[0]
            last_idx = InterfaceIndex(int(str(oid).split('.')[-1]))
            value = str(obj[1])
            result.append((last_idx, value))
        return result

    T = TypeVar("T", int, str)
    @staticmethod
    def snmp_get_result_last_idx_force_value_type(snmp_responses: list[ObjectType],
                                                  value_type: type[T] = str) -> list[tuple[int, T]]:
        """
        Extract the last index and value from each SNMP response,
        casting the value to the requested type (int or str).

        Args:
            snmp_responses: List of SNMP ObjectType responses.
            value_type: Type to cast the SNMP value to (int or str). Defaults to str.

        Returns:
            List of (last index, value) pairs, where `value` is of type `value_type`.
        """
        logger = logging.getLogger(__name__)
        result: list[tuple[int, T]] = []

        for obj in snmp_responses:
            # 1) extract index
            try:
                oid_str = str(obj[0])
                last_idx = int(oid_str.rsplit(".", 1)[-1])
            except Exception as e:
                logger.warning(f"Could not parse index from OID {obj[0]!r}: {e}")
                continue

            # 2) cast value
            raw_val = obj[1]
            try:
                if value_type is int:
                    cast_val: int | str = int(raw_val)
                else:
                    cast_val = str(raw_val)
            except Exception as e:
                logger.warning(f"Failed to cast SNMP value {raw_val!r} to {value_type}: {e}")
                # fallback: leave it in its raw form
                cast_val = raw_val  # type: ignore

            result.append((last_idx, cast_val))  # type: ignore

        return result

    @staticmethod
    def snmp_set_result_value(snmp_set_response: str) -> list[str]:
        """
        Extracts value(s) from an SNMP SET response string.

        This method parses the raw SNMP SET response string and extracts the
        returned value(s), if any, from the output. Useful for validating
        SNMP set operations.

        Parameters:
        - snmp_set_response (str): The raw SNMP SET response string, typically
        returned by an SNMP set operation.

        Returns:
        - List[str]: A list containing the parsed value(s) from the response.
                    If no value is found, returns an empty list.
        """
        if not snmp_set_response:
            return []

        logging.debug(f'snmp_set_result_value -> {snmp_set_response}')

        return  [str(value[1]) for value in snmp_set_response]

    @staticmethod
    def get_oid_index(oid: str) -> SnmpIndex | None:
        """
        Extract the index (last sub-identifier) from an OID string.

        Args:
            oid (str): The OID in dot-separated format (e.g., '1.3.6.1.2.1.2.2.1.3.2').

        Returns:
            Optional[int]: The last part of the OID interpreted as an integer, or None if extraction fails.
        """
        if not isinstance(oid, str):
            oid = str(oid)

        try:
            parts = oid.strip().split('.')
            index = SnmpIndex(int(parts[-1]))
            logging.debug(f"Extracted OID index: OID='{oid}', Parts={parts}, Index={index}")
            return index
        except (ValueError, IndexError) as e:
            logging.error(f"Failed to extract index from OID '{oid}': {e}")
            return None

    @staticmethod
    def get_inet_address_type(inet_address: InetAddressStr) -> InetAddressType:
        """
        Determine the InetAddressType of an IP address (IPv4 or IPv6).

        Args:
            inet_address (str): The IP address to check.

        Returns:
            InetAddressType: IPV4 (1) for IPv4 addresses, or IPV6 (2) for IPv6 addresses.

        Raises:
            ValueError: If the IP address is invalid.
        """
        binary = InetGenerate.inet_to_binary(inet_address)

        if not binary:
            raise ValueError(f"Invalid IP address: {inet_address}")

        return InetAddressType.IPV6 if len(binary) > 4 else InetAddressType.IPV4

    @staticmethod
    def parse_snmp_datetime(data: bytes) -> str:
        """
        Parses SNMP DateAndTime byte array and returns an ISO 8601 datetime string.

        Args:
            data (bytes): SNMP DateAndTime value as a byte array.

        Returns:
            str: ISO 8601 formatted datetime string (e.g., "2025-05-02T13:15:00").
        """
        if len(data) < 8:
            raise ValueError("Invalid SNMP DateAndTime data (too short)")

        # Convert the raw bytes into integer values
        year = data[0] << 8 | data[1]
        month = data[2]
        day = data[3]
        hour = data[4]
        minute = data[5]
        second = data[6]

        # Default: naive datetime (no timezone info)
        dt = datetime(year, month, day, hour, minute, second)

        if len(data) >= 11:
            # Timezone info exists
            direction = chr(data[8])
            tz_hours = data[9]
            tz_minutes = data[10]
            offset_minutes = tz_hours * 60 + tz_minutes
            if direction == '-':
                offset_minutes = -offset_minutes
            tz = timezone(timedelta(minutes=offset_minutes))
            dt = dt.replace(tzinfo=tz)

        return dt.isoformat()

    @staticmethod
    def truth_value(snmp_value: int | str) -> bool:
        """
        Converts SNMP TruthValue integer to a boolean.

        TruthValue ::= INTEGER { true(1), false(2) }

        Args:
            snmp_value (int or str): The raw SNMP integer value or string representation.

        Returns:
            bool: True if value is 1 (true), False if 2 (false).

        Raises:
            ValueError: If the value is not 1 or 2.
        """
        # Attempt to convert the snmp_value to an integer
        try:
            snmp_value = int(snmp_value)
        except ValueError:
            raise ValueError(f"Invalid input for TruthValue: {snmp_value}") from None

        if snmp_value == 1:
            return True
        elif snmp_value == 2:
            return False
        else:
            raise ValueError(f"Invalid TruthValue: {snmp_value}")

    @staticmethod
    def ticks_to_duration(ticks: int) -> str:
        """
        Converts SNMP sysUpTime ticks to a human-readable duration string.

        SNMP uptime ticks are measured in hundredths of a second.

        Args:
            ticks (int): The sysUpTime value in hundredths of a second.

        Returns:
            str: A formatted duration string like '3 days, 4:05:06.78'
        """
        if ticks < 0:
            raise ValueError("Ticks must be a non-negative integer")

        # Convert hundredths of a second to total seconds and microseconds
        total_seconds = ticks // 100
        remainder_hundredths = ticks % 100
        duration = timedelta(seconds=total_seconds, milliseconds=remainder_hundredths * 10)

        return str(duration)


    ###################
    # Private Methods #
    ###################

    def _to_object_identity(self, oid: str | tuple[str, str, int]) -> ObjectIdentity:
        """
        Internal helper to resolve an OID.

        Args:
            oid (Union[str, Tuple[str, str, int]]): OID to resolve.

        Returns:
            ObjectIdentity: pysnmp ObjectIdentity.
        """
        if isinstance(oid, tuple):
            self.logger.debug(f"Resolving OID tuple: {oid}")
            return ObjectIdentity(*oid)
        else:
            self.logger.debug(f"Resolving OID string: {oid}")
            return ObjectIdentity(oid)

    def _raise_on_snmp_error(self, errorIndication: Exception | str | None, errorStatus: object | None, errorIndex: Integer32 | int | None) -> None:
        """
        Raises RuntimeError if any SNMP error is detected.

        Args:
            errorIndication: General SNMP engine-level error (e.g., timeout, transport failure).
                            Typically an Exception instance or an error string, or None.
            errorStatus: SNMP protocol-level error (e.g., noSuchName, tooBig) or None.
            errorIndex: Index of the variable that caused the error (if applicable).

        Raises:
            RuntimeError: If an SNMP error or indication is present.
        """
        if errorIndication:
            raise RuntimeError(f"SNMP operation failed: {errorIndication}")
        if errorStatus:
            # errorStatus objects from pysnmp typically expose prettyPrint()
            pretty = getattr(errorStatus, "prettyPrint", None)
            status_text = pretty() if callable(pretty) else str(errorStatus)
            raise RuntimeError(
                f"SNMP error {status_text} at index {errorIndex}"
            )

    def _is_oid_in_subtree(self, oid_str: str, obj_str: str) -> bool:
        """
        Check if an OID is part of the requested subtree.

        Args:
            oid_str (str): The current OID string (e.g., '1.3.6.1.2.1.2.2.1.2.5').
            obj_str (str): The requested root OID string (e.g., '1.3.6.1.2.1.2.2.1.2').

        Returns:
            bool: True if oid_str is within the subtree of obj_str.
        """
        oid_parts = oid_str.strip('.').split('.')
        obj_parts = obj_str.strip('.').split('.')
        return oid_parts[:len(obj_parts)] == obj_parts

# FILE: src/pypnm/snmp/snmp_v3.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import NoReturn

from pysnmp.hlapi.v3arch.asyncio import ObjectType

from pypnm.lib.inet import Inet


class SecurityLevel(str, Enum):
    """SNMPv3 security level."""
    NO_AUTH_NO_PRIV = "noAuthNoPriv"
    AUTH_NO_PRIV    = "authNoPriv"
    AUTH_PRIV       = "authPriv"


class AuthProtocol(str, Enum):
    """Auth protocol names; map to pysnmp later."""
    NONE = "NONE"
    MD5  = "MD5"
    SHA  = "SHA"
    SHA224 = "SHA224"
    SHA256 = "SHA256"
    SHA384 = "SHA384"
    SHA512 = "SHA512"


class PrivProtocol(str, Enum):
    """Privacy (encryption) protocol names; map to pysnmp later."""
    NONE = "NONE"
    DES  = "DES"
    AES  = "AES"
    AES128 = "AES128"
    AES192 = "AES192"
    AES256 = "AES256"


class Snmp_v3:
    """
    SNMPv3 Client (stub).

    Provides the same public method signatures as Snmp_v2c, but all network
    operations raise NotImplementedError until the implementation is completed.

    Intended usage in config-driven code paths:
        if cfg.SNMP.version["3"]["enable"]:
            snmp = Snmp_v3(
                host=Inet(ip),
                username=...,
                security_level=SecurityLevel.AUTH_PRIV,
                auth_protocol=AuthProtocol.SHA,
                auth_password="...",
                priv_protocol=PrivProtocol.AES,
                priv_password="...",
                timeout=cfg.SNMP["timeout"],
                retries=cfg.SNMP["version"]["3"]["retries"],
                port=161,
            )
    """

    SNMP_PORT: int = 161

    def __init__(
        self,
        host: Inet,
        *,
        username: str = "",
        security_level: SecurityLevel = SecurityLevel.NO_AUTH_NO_PRIV,
        auth_protocol: AuthProtocol = AuthProtocol.NONE,
        auth_password: str = "",
        priv_protocol: PrivProtocol = PrivProtocol.NONE,
        priv_password: str = "",
        port: int = SNMP_PORT,
        timeout: int = 5,
        retries: int = 3,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self._host = host.inet
        self._port = port
        self._timeout = timeout
        self._retries = retries

        # v3 security params
        self._username = username
        self._sec_level = security_level
        self._auth_proto = auth_protocol
        self._auth_pass = auth_password
        self._priv_proto = priv_protocol
        self._priv_pass = priv_password

        # Placeholder for pysnmp engine/session later
        self._snmp_engine = None

        self._validate_params()

    def _validate_params(self) -> None:
        """
        Basic parameter checks so misconfigurations fail fast even in stub mode.
        """
        if (self._sec_level in (SecurityLevel.AUTH_NO_PRIV, SecurityLevel.AUTH_PRIV)
                and (self._auth_proto == AuthProtocol.NONE or not self._auth_pass)):
            raise ValueError("SNMPv3 auth* requires auth_protocol and auth_password.")

        if self._sec_level is SecurityLevel.AUTH_PRIV and (self._priv_proto == PrivProtocol.NONE or not self._priv_pass):
            raise ValueError("SNMPv3 authPriv requires priv_protocol and priv_password.")

        if not isinstance(self._host, str) or not self._host:
            raise ValueError("Invalid host provided to Snmp_v3.")

    # ─────────────────────────────────────────────────────────────────────
    # Public API (signatures align with Snmp_v2c; behavior is stubbed)
    # ─────────────────────────────────────────────────────────────────────

    async def get(self, oid: str | tuple[str, str, int],
                  timeout: int | None = None,
                  retries: int | None = None) -> NoReturn:
        """
        Stub for SNMP GET (v3).
        """
        self.logger.debug("Snmp_v3.get(%r) called (stub).", oid)
        raise NotImplementedError("Snmp_v3.get is not implemented yet.")

    async def walk(self, oid: str | tuple[str, str, int]) -> NoReturn:
        """
        Stub for SNMP WALK (v3).
        """
        self.logger.debug("Snmp_v3.walk(%r) called (stub).", oid)
        raise NotImplementedError("Snmp_v3.walk is not implemented yet.")

    async def bulk_walk(
        self,
        oid: str | tuple[str, str, int],
        non_repeaters: int = 0,
        max_repetitions: int = 25
    ) -> list[ObjectType] | None:
        """
        Stub for SNMP BULK WALK (v3).
        """
        self.logger.debug(
            "Snmp_v3.bulk_walk(%r, %r, %r) called (stub).",
            oid, non_repeaters, max_repetitions
        )
        raise NotImplementedError("Snmp_v3.bulk_walk is not implemented yet.")

    async def set(self, oid: str, value: str | int | float | bytes | bool, value_type: str) -> NoReturn:
        """
        Stub for SNMP SET (v3).
        """
        self.logger.debug("Snmp_v3.set(%r, %r, %r) called (stub).", oid, value, value_type)
        raise NotImplementedError("Snmp_v3.set is not implemented yet.")

    def close(self) -> None:
        """
        Close any underlying engine/transport (no-op in stub).
        """
        self.logger.debug("Snmp_v3.close() called (stub).")
        return

    # ─────────────────────────────────────────────────────────────────────
    # Helpers (copy/keep parity with v2c where convenient)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def resolve_oid(oid: str | tuple[str, str, int]) -> str:
        """
        Placeholder resolver. When you wire v3, either import COMPILED_OIDS
        or reuse shared resolver utilities.
        """
        if isinstance(oid, tuple):
            return ".".join(map(str, oid))

        if Snmp_v3.is_numeric_oid(oid):
            return oid

        # symbolic base + optional suffix, same pattern used elsewhere
        m = re.match(r"^([a-zA-Z0-9_:]+)(\..+)?$", oid)
        if not m:
            return oid
        base_sym, suffix = m.groups()
        # TODO: map base_sym using COMPILED_OIDS once imported.
        return f"{base_sym}{suffix or ''}"

    @staticmethod
    def is_numeric_oid(oid: str) -> bool:
        return bool(re.fullmatch(r"\.?(\d+\.)+\d+", oid))

# FILE: tests/test_snmp_v2c_bulk_walk.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

import pytest

import pypnm.snmp.snmp_v2c as snmp_v2c_module
from pypnm.lib.inet import Inet
from pypnm.snmp.snmp_v2c import Snmp_v2c


@pytest.mark.asyncio
async def test_bulk_walk_returns_results_until_subtree_exit(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    snmp = Snmp_v2c(Inet("192.168.0.100"), community="public")
    oid = "1.3.6.1.2.1"

    in_subtree = ("1.3.6.1.2.1.1.0", "value-1")
    out_of_subtree = ("1.3.6.1.3.1.0", "value-2")

    class FakeIdentity:
        def __init__(self, oid_value: str) -> None:
            self._oid_value = oid_value

        def __str__(self) -> str:
            return self._oid_value

    def fake_object_type(identity: object) -> tuple[str, object]:
        return ("object", identity)

    async def fake_create(*_args: object, **_kwargs: object) -> object:
        return object()

    async def fake_bulk_cmd(*_args: object, **_kwargs: object):
        async def generator():
            yield (None, None, 0, [in_subtree])
            yield (None, None, 0, [out_of_subtree])

        return generator()

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)

    results = await snmp.bulk_walk(oid)

    assert results is not None
    assert results == [in_subtree]


@pytest.mark.asyncio
async def test_bulk_walk_falls_back_to_walk_on_empty_payload(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    snmp = Snmp_v2c(Inet("192.168.0.100"), community="public")

    class FakeIdentity:
        def __init__(self, oid_value: str) -> None:
            self._oid_value = oid_value

        def __str__(self) -> str:
            return self._oid_value

    def fake_object_type(identity: object) -> tuple[str, object]:
        return ("object", identity)

    async def fake_create(*_args: object, **_kwargs: object) -> object:
        return object()

    async def fake_bulk_cmd(*_args: object, **_kwargs: object):
        return (None, None, 0, [])

    async def fake_walk(_oid: str | tuple[str, str, int]) -> list[str]:
        return ["walked"]

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)
    monkeypatch.setattr(snmp, "walk", fake_walk)

    results = await snmp.bulk_walk("1.3.6.1.2.1")

    assert results == ["walked"]


@pytest.mark.asyncio
async def test_bulk_walk_retries_on_too_big(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    snmp = Snmp_v2c(Inet("192.168.0.100"), community="public")

    in_subtree = ("1.3.6.1.2.1.1.0", "value-1")

    class FakeIdentity:
        def __init__(self, oid_value: str) -> None:
            self._oid_value = oid_value

        def __str__(self) -> str:
            return self._oid_value

    class FakeStatus:
        def prettyPrint(self) -> str:
            return "tooBig"

    def fake_object_type(identity: object) -> tuple[str, object]:
        return ("object", identity)

    async def fake_create(*_args: object, **_kwargs: object) -> object:
        return object()

    attempts: list[int] = []

    async def fake_bulk_cmd(*_args: object, **_kwargs: object):
        max_repetitions = int(_args[5])
        attempts.append(max_repetitions)

        async def generator():
            if max_repetitions > 1:
                yield (None, FakeStatus(), 0, [])
                return
            yield (None, None, 0, [in_subtree])

        return generator()

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)

    results = await snmp.bulk_walk("1.3.6.1.2.1")

    assert results == [in_subtree]
    assert attempts[-1] == 1

# FILE: tools/release/release.py
#!/usr/bin/env python3
from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

import argparse
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Final


VERSION_FILE_PATH: Final[Path]           = Path("src/pypnm/version.py")
BUMP_SCRIPT_PATH: Final[Path]            = Path("tools/support") / "bump_version.py"
PYPROJECT_FILE_PATH: Final[Path]         = Path("pyproject.toml")
README_FILE_PATH: Final[Path]            = Path("README.md")
DOCS_ROOT: Final[Path]                   = Path("docs")
README_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r'TAG="v\d+\.\d+\.\d+\.\d+(?:-rc\d+)?"')
WORKFLOWS_DIR: Final[Path]               = Path(".github") / "workflows"

VERSION_PART_SEPARATOR: Final[str]       = "."
EXPECTED_VERSION_PARTS: Final[int]       = 4

MAJOR_INDEX: Final[int]                  = 0
MINOR_INDEX: Final[int]                  = 1
MAINTENANCE_INDEX: Final[int]            = 2
BUILD_INDEX: Final[int]                  = 3
RC_SUFFIX_PREFIX: Final[str]             = "-rc"
RC_DEFAULT_NUMBER: Final[int]            = 1

REPORT_DIR_NAME: Final[str]              = "release-reports"
REPORT_FILE_PREFIX: Final[str]           = "release-report"
REPORT_SECTIONS: Final[list[str]]        = [
    "Docs",
    "Docker",
    "K8s",
    "FastAPI",
    "REST",
    "DOCSIS",
    "PNM",
    "PNM-Python",
    "Tools",
    "Install",
]
REPORT_HEADERS: Final[list[str]]         = ["Section", "Files Changed"]
INSTALL_PREFIXES: Final[list[str]]       = ["install.sh", "scripts/install", "deploy/"]
DOCKER_PREFIXES: Final[list[str]]        = ["docker/", "docker-compose", "docs/docker/"]
K8S_PREFIX: Final[str]                   = "docs/kubernetes/"


SUMMARY: dict[str, str] = {}
RELEASE_LOG_DIR: Path | None = None


def _parse_version_parts(version: str) -> list[int]:
    _validate_version_string(version)
    return [int(part) for part in version.split(VERSION_PART_SEPARATOR)]


def _determine_bump_kind(current_version: str, new_version: str) -> str:
    current_parts = _parse_version_parts(current_version)
    new_parts = _parse_version_parts(new_version)
    if new_parts[MAJOR_INDEX] != current_parts[MAJOR_INDEX]:
        return "major"
    if new_parts[MINOR_INDEX] != current_parts[MINOR_INDEX]:
        return "minor"
    if new_parts[MAINTENANCE_INDEX] != current_parts[MAINTENANCE_INDEX]:
        return "maintenance"
    if new_parts[BUILD_INDEX] != current_parts[BUILD_INDEX]:
        return "build"
    return "none"


def _prompt_release_candidate(bump_kind: str) -> str:
    prompt = f"Is this a GA release for the {bump_kind} bump? [y/N]: "
    answer = input(prompt).strip().lower()
    if answer in ("y", "yes"):
        return ""

    rc_input = input(f"RC number (default {RC_DEFAULT_NUMBER}): ").strip()
    if not rc_input:
        rc_number = RC_DEFAULT_NUMBER
    elif rc_input.isdigit():
        rc_number = int(rc_input)
    else:
        print("ERROR: RC number must be a positive integer.", file=sys.stderr)
        sys.exit(1)

    if rc_number < RC_DEFAULT_NUMBER:
        print("ERROR: RC number must be at least 1.", file=sys.stderr)
        sys.exit(1)

    return f"{RC_SUFFIX_PREFIX}{rc_number}"


def _print_banner() -> None:
    banner_path = Path(__file__).resolve().parent.parent / "banner.txt"
    if banner_path.is_file():
        print(banner_path.read_text(encoding="utf-8"))
        print()


def _init_release_logging() -> None:
    """Create a temporary directory for failed-command logs and announce it."""
    global RELEASE_LOG_DIR
    if RELEASE_LOG_DIR is None:
        logs_dir = Path(REPORT_DIR_NAME) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        RELEASE_LOG_DIR = Path(tempfile.mkdtemp(prefix="pypnm-release-logs-", dir=str(logs_dir)))
        print(f"[release] Command failures will be logged under: {RELEASE_LOG_DIR}")


def _sanitize_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label.strip().lower())
    return safe or "cmd"


def _default_label(cmd: list[str]) -> str:
    return Path(cmd[0]).name


def _log_command_failure(label: str, result: subprocess.CompletedProcess[str]) -> None:
    if RELEASE_LOG_DIR is None:
        return
    safe_label = _sanitize_label(label)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = RELEASE_LOG_DIR / f"{safe_label}-{timestamp}.log"
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    log_path.write_text(
        f"$ {' '.join(result.args if isinstance(result.args, (list, tuple)) else [str(result.args)])}\n\n"
        f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n",
        encoding="utf-8",
    )
    print(f"[release] {label} failed; see {log_path}")


def _run(
    cmd: list[str],
    check: bool = True,
    *,
    label: str | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command, capturing output for logging on failure."""
    if capture_output:
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    else:
        proc = subprocess.run(cmd, text=True, check=False)

    if proc.returncode != 0:
        if capture_output:
            _log_command_failure(label or _default_label(cmd), proc)
        if check:
            raise subprocess.CalledProcessError(
                proc.returncode,
                cmd,
                output=proc.stdout,
                stderr=proc.stderr,
            )
    return proc


# Simple status printer with color for TTY output
def _colorize(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    codes = {
        "green": "\033[32m",
        "red": "\033[31m",
        "yellow": "\033[33m",
        "reset": "\033[0m",
    }
    return f"{codes.get(color, '')}{text}{codes['reset']}"


def _format_state(state: str) -> str:
    match state.lower():
        case "pass":
            return _colorize("PASS", "green")
        case "fail":
            return _colorize("FAIL", "red")
        case "skip":
            return _colorize("SKIP", "yellow")
        case _:
            return state.upper()


def _print_status(label: str, state: str) -> None:
    SUMMARY[label] = state
    print(f"{_format_state(state)} {label}")


def _print_release_summary() -> None:
    if not SUMMARY:
        return
    print("\nRelease step summary:")
    for label, state in SUMMARY.items():
        print(f" {_format_state(state)} {label}")
    if RELEASE_LOG_DIR:
        print(f"Failure logs (if any) stored in: {RELEASE_LOG_DIR}")


atexit.register(_print_release_summary)


def _ensure_clean_worktree() -> None:
    """Ensure the git working tree has no uncommitted changes."""
    result = _run(["git", "status", "--porcelain"], check=False, label="git-status")
    output = (result.stdout or "").strip()
    if output:
        print("ERROR: Working tree is not clean. Commit or stash changes first.", file=sys.stderr)
        sys.exit(1)


def _get_head_commit() -> str:
    result = _run(["git", "rev-parse", "HEAD"], label="git-rev-parse")
    return result.stdout.strip()


def _get_previous_commit() -> str | None:
    result = _run(["git", "rev-parse", "HEAD~1"], check=False, label="git-rev-parse-prev")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _get_current_branch() -> str:
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], label="git-branch")
    return result.stdout.strip()


def _get_upstream_ref() -> str | None:
    result = _run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        check=False,
        label="git-upstream",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _list_pending_commits(upstream: str) -> list[str]:
    result = _run(["git", "rev-list", "--reverse", f"{upstream}..HEAD"], label="git-rev-list")
    commits = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return commits


def _collect_commit_files(commit: str) -> list[str]:
    result = _run(["git", "show", "--pretty=format:", "--name-only", commit], label="git-show")
    paths = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return paths


def _collect_range_files(range_spec: str) -> list[str]:
    result = _run(["git", "log", "--pretty=format:", "--name-only", range_spec], label="git-log-range")
    seen: set[str] = set()
    paths: list[str] = []
    for line in (result.stdout or "").splitlines():
        path = line.strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _classify_path(path: str) -> str:
    normalized = path.replace("\\", "/").lower()
    if normalized.startswith(K8S_PREFIX):
        return "K8s"
    if any(normalized.startswith(prefix) for prefix in DOCKER_PREFIXES):
        return "Docker"
    if normalized.startswith("docs/") or normalized == "readme.md":
        return "Docs"
    if "fastapi" in normalized:
        return "FastAPI"
    if normalized.startswith("src/pypnm/api/routes/"):
        return "REST"
    if "/rest" in normalized or "rest_" in normalized or "rest-" in normalized:
        return "REST"
    if normalized.startswith("src/pypnm/") or normalized == "pyproject.toml":
        if normalized.startswith("src/pypnm/docsis/"):
            return "DOCSIS"
        if normalized.startswith("src/pypnm/pnm/"):
            return "PNM"
        return "PNM-Python"
    if normalized.startswith("tools/"):
        return "Tools"
    if any(normalized.startswith(prefix) for prefix in INSTALL_PREFIXES):
        return "Install"
    return "Other"


def _summarize_sections(paths: list[str]) -> dict[str, int]:
    counts = {section: 0 for section in REPORT_SECTIONS}
    counts["Other"] = 0
    for path in paths:
        section = _classify_path(path)
        if section in counts:
            counts[section] += 1
        else:
            counts["Other"] += 1
    return counts


def _render_table(counts: dict[str, int]) -> str:
    rows = [(section, str(counts.get(section, 0))) for section in REPORT_SECTIONS]
    if counts.get("Other", 0) > 0:
        rows.append(("Other", str(counts["Other"])))

    header_section, header_count = REPORT_HEADERS
    section_width = max(len(header_section), max(len(row[0]) for row in rows))
    count_width = max(len(header_count), max(len(row[1]) for row in rows))

    def line() -> str:
        return f"+{'-' * (section_width + 2)}+{'-' * (count_width + 2)}+"

    lines = [
        line(),
        f"| {header_section.ljust(section_width)} | {header_count.ljust(count_width)} |",
        line(),
    ]
    for section, count in rows:
        lines.append(f"| {section.ljust(section_width)} | {count.ljust(count_width)} |")
    lines.append(line())
    return "\n".join(lines)


def _render_markdown_table(counts: dict[str, int]) -> str:
    rows = [(section, str(counts.get(section, 0))) for section in REPORT_SECTIONS]
    if counts.get("Other", 0) > 0:
        rows.append(("Other", str(counts["Other"])))

    lines = [
        f"| {REPORT_HEADERS[0]} | {REPORT_HEADERS[1]} |",
        "| --- | --- |",
    ]
    for section, count in rows:
        lines.append(f"| {section} | {count} |")
    return "\n".join(lines)


def _read_workflow_name(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return path.name

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", 1)[1].strip() or path.name

    return path.name


def _collect_workflows() -> list[tuple[str, str]]:
    if not WORKFLOWS_DIR.exists():
        return []

    workflows: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        workflows.append((_read_workflow_name(path), os.path.relpath(path, Path.cwd())))
    for path in sorted(WORKFLOWS_DIR.glob("*.yaml")):
        workflows.append((_read_workflow_name(path), os.path.relpath(path, Path.cwd())))
    return workflows


def _write_release_report(
    commit: str,
    version: str,
    tag_name: str,
    branch: str,
    report_mode: str,
    extra_sections: list[str] | None = None,
) -> Path:
    report_dir = Path(REPORT_DIR_NAME)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"{REPORT_FILE_PREFIX}-{version}-{timestamp}.md"
    files = _collect_commit_files(commit)
    sorted_files = sorted(files)
    counts = _summarize_sections(files)
    workflows = _collect_workflows()
    mode = report_mode

    lines = [
        f"# PyPNM {mode} report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Branch: {branch}",
        f"- Source commit: `{commit}`",
        f"- Release version: `{version}`",
        f"- Release tag: `{tag_name}`",
        "",
        "## Workflows",
        "",
    ]
    if workflows:
        lines.extend(f"- `{name}` (`{path}`)" for name, path in workflows)
    else:
        lines.append("_No workflows found._")
    lines.extend(
        [
            "",
            "## Change summary (commit)",
        "",
        _render_markdown_table(counts),
        "",
        "## Files (commit)",
        "",
        ]
    )
    if sorted_files:
        lines.extend(f"- `{path}`" for path in sorted_files)
    else:
        lines.append("_No files detected._")
    lines.append("")
    if SUMMARY:
        lines.extend(
            [
                "## Release step summary",
                "",
            ]
        )
        for label, state in SUMMARY.items():
            lines.append(f"- {state.upper()} {label}")
        lines.append("")

    if RELEASE_LOG_DIR:
        log_files = sorted(RELEASE_LOG_DIR.glob("*.log"))
        log_dir_display = os.path.relpath(RELEASE_LOG_DIR, Path.cwd())
        lines.extend(
            [
                "## Failure logs",
                "",
                f"- [Release Log]({log_dir_display})",
            ]
        )
        if log_files:
            lines.extend(
                f"- [`{os.path.relpath(log_file, Path.cwd())}`]({os.path.relpath(log_file, Path.cwd())})"
                for log_file in log_files
            )
        else:
            lines.append("- _No failure logs generated._")
        lines.append("")
    if extra_sections:
        lines.extend(extra_sections)
        if lines[-1] != "":
            lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _ensure_virtualenv() -> None:
    """Ensure release is running inside a virtual environment."""
    if os.environ.get("VIRTUAL_ENV"):
        return
    if getattr(sys, "base_prefix", sys.prefix) != sys.prefix:
        return
    setup_cmd = (
        f"{sys.executable} -m venv .venv && "
        ". .venv/bin/activate && "
        "pip install -e '.[dev]'"
    )
    print(
        "ERROR: Release must run inside a Python virtual environment. "
        "Activate the venv (or create one) before running tools/release/release.py.",
        file=sys.stderr,
    )
    print("Suggested setup (copy/paste):", file=sys.stderr)
    print(f"  {setup_cmd}", file=sys.stderr)
    sys.exit(1)


def _ensure_pytest_available() -> None:
    """Ensure pytest is importable in the current environment."""
    try:
        import pytest  # noqa: F401
    except ModuleNotFoundError:
        print(
            "ERROR: pytest is not installed in the active Python environment. "
            "Install dev dependencies in the venv before running the release.",
            file=sys.stderr,
        )
        sys.exit(1)


def _checkout_and_pull(branch: str) -> None:
    """Checkout the target branch and fast-forward pull from origin."""
    _run(["git", "checkout", branch], label="git-checkout")
    _run(["git", "pull", "--ff-only"], label="git-pull")


def _read_current_version() -> str:
    """Read the current __version__ value from the version file."""
    if not VERSION_FILE_PATH.exists():
        print(f"ERROR: Version file not found: {VERSION_FILE_PATH}", file=sys.stderr)
        sys.exit(1)

    text = VERSION_FILE_PATH.read_text(encoding="utf-8")
    prefix = '__version__: str = "'
    start_index = text.find(prefix)
    if start_index < 0:
        print(
            f"ERROR: Could not find __version__ assignment in {VERSION_FILE_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)

    start_index = start_index + len(prefix)
    end_index = text.find('"', start_index)
    if end_index < 0:
        print(
            f"ERROR: Unterminated __version__ string in {VERSION_FILE_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)

    return text[start_index:end_index]


def _read_pyproject_version() -> str:
    """Read the [project].version value from pyproject.toml."""
    if not PYPROJECT_FILE_PATH.exists():
        print(f"ERROR: pyproject.toml not found: {PYPROJECT_FILE_PATH}", file=sys.stderr)
        sys.exit(1)

    text = PYPROJECT_FILE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_project_section = False

    for line in lines:
        stripped = line.strip()
        if stripped == "[project]":
            in_project_section = True
            continue

        if in_project_section and stripped.startswith("[") and stripped.endswith("]"):
            break

        if in_project_section and stripped.startswith("version") and "=" in stripped and '"' in stripped:
            first_quote = line.find('"')
            second_quote = line.find('"', first_quote + 1)
            if first_quote == -1 or second_quote == -1:
                print(
                    f"ERROR: Malformed [project].version line in {PYPROJECT_FILE_PATH}: {line!r}",
                    file=sys.stderr,
                )
                sys.exit(1)
            return line[first_quote + 1 : second_quote]

    print(
        f"ERROR: Could not find [project].version in {PYPROJECT_FILE_PATH}.",
        file=sys.stderr,
    )
    sys.exit(1)


def _validate_version_string(version: str) -> None:
    """Validate that the version string matches MAJOR.MINOR.MAINTENANCE.BUILD."""
    parts = version.split(VERSION_PART_SEPARATOR)
    if len(parts) != EXPECTED_VERSION_PARTS:
        print(
            f"ERROR: Version '{version}' has {len(parts)} parts, expected {EXPECTED_VERSION_PARTS}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not all(part.isdigit() for part in parts):
        print(
            f"ERROR: Invalid version '{version}'. Expected numeric MAJOR.MINOR.MAINTENANCE.BUILD.",
            file=sys.stderr,
        )
        sys.exit(1)


def _compute_next_version(current_version: str, mode: str) -> str:
    """Compute the next version string by incrementing the requested component."""
    _validate_version_string(current_version)
    parts_str = current_version.split(VERSION_PART_SEPARATOR)
    parts_int = [int(part) for part in parts_str]

    match mode:
        case "major":
            parts_int[MAJOR_INDEX]       = parts_int[MAJOR_INDEX] + 1
            parts_int[MINOR_INDEX]       = 0
            parts_int[MAINTENANCE_INDEX] = 0
            parts_int[BUILD_INDEX]       = 0
        case "minor":
            parts_int[MINOR_INDEX]       = parts_int[MINOR_INDEX] + 1
            parts_int[MAINTENANCE_INDEX] = 0
            parts_int[BUILD_INDEX]       = 0
        case "maintenance":
            parts_int[MAINTENANCE_INDEX] = parts_int[MAINTENANCE_INDEX] + 1
            parts_int[BUILD_INDEX]       = 0
        case "build":
            parts_int[BUILD_INDEX]       = parts_int[BUILD_INDEX] + 1
        case _:
            print(f"ERROR: Unsupported next mode '{mode}'.", file=sys.stderr)
            sys.exit(1)

    return VERSION_PART_SEPARATOR.join(str(part) for part in parts_int)


def _bump_version(new_version: str) -> None:
    """Invoke tools/bump_version.py to update the version string."""
    if not BUMP_SCRIPT_PATH.exists():
        print(f"ERROR: Version bump script not found: {BUMP_SCRIPT_PATH}", file=sys.stderr)
        sys.exit(1)

    _run([sys.executable, str(BUMP_SCRIPT_PATH), new_version], label="bump-version")


def _restore_previous_version(previous_version: str, tag_prefix: str) -> None:
    """Restore version files back to the previous version after a test release."""
    print(f"Restoring version files to {previous_version}...")
    _bump_version(previous_version)
    _update_readme_tag(f"{tag_prefix}{previous_version}")


def _update_readme_tag(new_tag: str) -> None:
    """Rewrite TAG placeholders to the new release tag in README and docs."""
    paths = [README_FILE_PATH]
    if DOCS_ROOT.exists():
        paths.extend([p for p in DOCS_ROOT.rglob("*.md") if p.is_file()])

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue

        updated_text, count = README_TAG_PATTERN.subn(f'TAG="{new_tag}"', text)
        if count == 0:
            continue

        path.write_text(updated_text, encoding="utf-8")
        print(f"Updated TAG placeholders in {path} to {new_tag}")


def _run_tests() -> None:
    """Run the test suite before finalizing the release."""
    _ensure_pytest_available()
    print("Running tests (pytest)...")
    result = _run([sys.executable, "-m", "pytest"], check=False, label="pytest")
    if result.returncode != 0:
        print("ERROR: pytest failed. Aborting release.", file=sys.stderr)
        _print_status("Tests", "fail")
        sys.exit(result.returncode)
    _print_status("Tests", "pass")


def _run_repo_hygiene_checks() -> None:
    """Run pre-release hygiene checks (secrets, MAC address scans, etc.)."""
    checks: list[tuple[str, list[str]]] = [
        ("Secret scan", ["./tools/security/scan-secrets.sh"]),
        ("Encrypted secret scan", [sys.executable, "./tools/security/scan-enc-secrets.py"]),
        ("MAC scan", ["./tools/security/scan-mac-addresses.py", "--fail-on-found"]),
    ]
    print("Running repository hygiene checks...")
    for label, cmd in checks:
        script_path = Path(cmd[0])
        if script_path.suffix in {".sh", ".py"} and not script_path.exists():
            print(f"{label}: {script_path} not found, skipping.")
            _print_status(label, "skip")
            continue
        result = _run(cmd, check=False, label=label)
        if result.returncode != 0:
            print(f"ERROR: {label} failed. Aborting release.", file=sys.stderr)
            _print_status(label, "fail")
            sys.exit(result.returncode)
        _print_status(label, "pass")


def _prime_sudo_session() -> None:
    """Run sudo -v once so later sudo invocations do not re-prompt."""
    if shutil.which("sudo") is None:
        return
    print("Priming sudo credentials (sudo -v)...")
    result = _run(["sudo", "-v"], check=False, label="sudo-validate", capture_output=False)
    if result.returncode != 0:
        print("ERROR: Unable to validate sudo credentials. Aborting release.", file=sys.stderr)
        _print_status("sudo-validate", "fail")
        sys.exit(result.returncode)
    _print_status("sudo-validate", "pass")


def _run_mkdocs_strict() -> None:
    """Build mkdocs site in strict mode to catch broken links before release."""
    if not Path("mkdocs.yml").exists():
        print("mkdocs.yml not found; skipping mkdocs strict build.")
        _print_status("MkDocs", "skip")
        return

    print("Building docs with mkdocs --strict ...")
    result = _run(["mkdocs", "build", "--strict"], check=False, label="mkdocs")
    if result.returncode != 0:
        print("ERROR: mkdocs build failed. Aborting release.", file=sys.stderr)
        _print_status("MkDocs", "fail")
        sys.exit(result.returncode)
    _print_status("MkDocs", "pass")


def _commit_version_bump(new_version: str) -> None:
    """Commit the version bump change (includes README/docs tag updates)."""
    add_paths = [
        str(VERSION_FILE_PATH),
        str(PYPROJECT_FILE_PATH),
        str(README_FILE_PATH),
    ]

    # Add docs in case TAG placeholders were updated there
    if DOCS_ROOT.exists():
        add_paths.append(str(DOCS_ROOT))

    _run(["git", "add", *add_paths], label="git-add")
    _run(["git", "commit", "-m", f"Release {new_version}"], label="git-commit")


def _create_tag(new_version: str, tag_prefix: str, tag_suffix: str = "") -> str:
    """Create an annotated git tag for the release."""
    tag_name = f"{tag_prefix}{new_version}{tag_suffix}"
    _run(["git", "tag", "-a", tag_name, "-m", f"Release {new_version}"], label="git-tag")
    return tag_name


def _push_branch_and_tag(branch: str, tag_name: str) -> None:
    """Push the branch and tag to the origin remote."""
    _run(["git", "push", "origin", branch], label="git-push-branch")
    _run(["git", "push", "origin", tag_name], label="git-push-tag")


def main() -> None:
    """Automate a release: bump version, run tests, commit, tag, and push.

    Typical flows
    -------------
    1) Let the script compute the next maintenance version:
       tools/release/release.py

    2) Let the script compute the next version by mode:
       tools/release/release.py --next minor
       tools/release/release.py --next major
       tools/release/release.py --next maintenance
       tools/release/release.py --next build

    3) Release an explicit version:
       tools/release/release.py --version 0.2.1.0

    4) Show what would happen without changing anything:
       tools/release/release.py --next maintenance --dry-run
       tools/release/release.py --dry-run
    """
    _print_banner()
    parser = argparse.ArgumentParser(
        description=(
            "Automate a PyPNM release: compute or apply a version using tools/bump_version.py, "
            "run tests, commit, tag, and push."
        )
    )
    parser.add_argument(
        "--version",
        help="Explicit release version in MAJOR.MINOR.MAINTENANCE.BUILD format (e.g. 0.1.0.0).",
    )
    parser.add_argument(
        "--next",
        choices=["major", "minor", "maintenance", "build"],
        help="Compute the next version from the current one (default: maintenance if omitted).",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Branch to release from (default: main). Use 'stable' when ready.",
    )
    parser.add_argument(
        "--tag-prefix",
        default="v",
        help="Prefix for git tag names (default: 'v', e.g. v0.1.0.0).",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running pytest before committing and tagging.",
    )
    parser.add_argument(
        "--skip-docker-test",
        action="store_true",
        help="Skip local docker build/smoke preflight (tools/local/local_container_build.sh).",
    )
    parser.add_argument(
        "--skip-k8s-test",
        action="store_true",
        help="Skip local Kubernetes smoke test (tools/local/local_kubernetes_smoke.sh).",
    )
    parser.add_argument(
        "--test-release",
        action="store_true",
        help="Run locally without commit/tag/push, then restore the prior version.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without modifying anything.",
    )
    parser.add_argument(
        "--last-commit-report",
        action="store_true",
        help="Generate a report for the previous commit only (no release actions).",
    )
    parser.add_argument(
        "--latest-commit-report",
        action="store_true",
        help="Generate a report for the current commit only (no release actions).",
    )

    args = parser.parse_args()
    explicit_version: str | None = args.version
    next_mode: str | None        = args.next
    branch: str                  = args.branch
    tag_prefix: str              = args.tag_prefix
    skip_tests: bool             = args.skip_tests
    skip_docker: bool            = args.skip_docker_test
    skip_k8s: bool               = args.skip_k8s_test
    dry_run: bool                = args.dry_run
    test_release: bool           = args.test_release
    last_commit_report: bool     = args.last_commit_report
    latest_commit_report: bool   = args.latest_commit_report

    if last_commit_report and latest_commit_report:
        print("ERROR: --last-commit-report and --latest-commit-report cannot be used together.", file=sys.stderr)
        sys.exit(1)

    if last_commit_report or latest_commit_report:
        if explicit_version or next_mode or skip_tests or skip_docker or skip_k8s or dry_run or test_release:
            print("ERROR: Commit report modes cannot be combined with release options.", file=sys.stderr)
            sys.exit(1)

        current_branch = _get_current_branch()
        if branch != current_branch:
            print(
                f"ERROR: Commit report runs on the current branch ({current_branch}). "
                f"Checkout '{branch}' first or omit --branch.",
                file=sys.stderr,
            )
            sys.exit(1)

        target_commit = _get_previous_commit() if last_commit_report else _get_head_commit()
        if not target_commit:
            print("ERROR: Unable to resolve the requested commit for reporting.", file=sys.stderr)
            sys.exit(1)

        report_version = _read_current_version()
        report_mode = "last-commit" if last_commit_report else "latest-commit"
        report_tag = "n/a"

        pending_counts = None
        pending_count = 0
        pending_upstream = _get_upstream_ref()
        if pending_upstream:
            pending_commits = _list_pending_commits(pending_upstream)
            pending_count = len(pending_commits)
            if pending_count > 1:
                pending_files = _collect_range_files(f"{pending_upstream}..HEAD")
                pending_counts = _summarize_sections(pending_files)

        extra_sections: list[str] = []
        if pending_counts:
            extra_sections.extend(
                [
                    "## Change summary (pending commits ahead of upstream)",
                    "",
                    _render_markdown_table(pending_counts),
                    "",
                    f"- Pending commits: {pending_count}",
                    f"- Upstream: `{pending_upstream}`",
                    "",
                ]
            )

        report_path = _write_release_report(
            target_commit,
            report_version,
            report_tag,
            current_branch,
            report_mode,
            extra_sections=extra_sections or None,
        )

        counts = _summarize_sections(_collect_commit_files(target_commit))
        print("\nCommit change summary:")
        print(_render_table(counts))
        if pending_counts:
            print("\nPending commits summary (ahead of upstream):")
            print(_render_table(pending_counts))
            print(f"Pending commits: {pending_count}")
            print(f"Upstream: {pending_upstream}")
        print(f"Commit report saved to {report_path}")
        return

    current_branch = _get_current_branch()
    if current_branch not in ("main", "hot-fix"):
        print("ERROR: release can only be done in main or hot-fix branch.", file=sys.stderr)
        sys.exit(1)

    current_version   = _read_current_version()
    pyproject_version = _read_pyproject_version()

    if current_version != pyproject_version:
        print(
            "ERROR: Version mismatch between src/pypnm/version.py "
            f"({current_version}) and pyproject.toml [project].version "
            f"({pyproject_version}). Run tools/bump_version.py or fix manually.",
            file=sys.stderr,
        )
        sys.exit(1)

    if explicit_version is not None and next_mode is not None:
        print("ERROR: --version and --next cannot be used together.", file=sys.stderr)
        sys.exit(1)

    if explicit_version is not None:
        new_version = explicit_version
        _validate_version_string(new_version)
    else:
        mode       = next_mode or "maintenance"
        new_version = _compute_next_version(current_version, mode)

    if new_version == current_version:
        print(f"No change: version is already {current_version}.")
        sys.exit(0)

    bump_kind = _determine_bump_kind(current_version, new_version)
    rc_suffix = ""
    release_tag = f"{tag_prefix}{new_version}"

    if dry_run:
        print("Dry run: the following actions would be performed:")
        print("  1) Ensure git working tree is clean")
        print(f"  2) Checkout branch '{branch}' and pull with --ff-only")
        print(f"  3) Update version {current_version} -> {new_version} via tools/bump_version.py")
        print(f"  4) Update README/docs TAG placeholders to {release_tag}")
        print("  5) Run repository hygiene checks (secrets/macs)")
        if not skip_tests:
            print("  6) Run pytest")
        if not skip_docker:
            print("  7) Run local docker preflight (tools/local/local_container_build.sh --smoke)")
        if not skip_k8s:
            print("  8) Run local Kubernetes smoke test (tools/local/local_kubernetes_smoke.sh)")
        print(f"  9) Build docs with mkdocs --strict")
        if test_release:
            print(" 10) Skip commit/tag/push (test-only)")
            print(f" 11) Restore version files back to {current_version}")
        else:
            print(f" 10) Commit version bump: 'Release {new_version}'")
            print(f" 11) Create annotated tag '{release_tag}'")
            print(f" 12) Push branch '{branch}' and tag to origin")
        if bump_kind in ("major", "minor", "maintenance"):
            print("Note: you will be prompted to confirm GA; otherwise an -rcX suffix is used.")
        sys.exit(0)

    _ensure_virtualenv()

    if explicit_version is None:
        print(f"Current version: {current_version}")
        print(f"Planned version bump: {current_version} -> {new_version}")
        answer = input("Proceed with release? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted: release was not confirmed.")
            sys.exit(1)

    if bump_kind in ("major", "minor", "maintenance"):
        rc_suffix = _prompt_release_candidate(bump_kind)
        release_tag = f"{tag_prefix}{new_version}{rc_suffix}"

    _init_release_logging()
    if not skip_docker or not skip_k8s:
        _prime_sudo_session()

    _ensure_clean_worktree()
    if not test_release:
        _checkout_and_pull(branch)

    report_commit = _get_head_commit()

    print(f"Bumping version: {current_version} -> {new_version}")
    _bump_version(new_version)
    _update_readme_tag(release_tag)

    _run_repo_hygiene_checks()

    if not skip_tests:
        _run_tests()
    else:
        _print_status("Tests", "skip")

    if not skip_docker:
        print("Running local docker preflight (tools/local/local_container_build.sh --smoke)...")
        cmd = ["./tools/local/local_container_build.sh", "--smoke"]
        result = _run(cmd, check=False, label="docker-smoke")
        if result.returncode != 0:
            # Attempt sudo fallback if permission denied is suspected
            err_text = (result.stderr or "") + "\n" + (result.stdout or "")
            if "permission denied" in err_text.lower():
                print("Docker preflight failed; retrying with sudo...")
                result = _run(["sudo"] + cmd, check=False, label="docker-smoke-sudo")
        if result.returncode != 0:
            print("ERROR: local docker preflight failed. Aborting release.", file=sys.stderr)
            print("If this is a Docker permission issue, add your user to the docker group and re-login:")
            print("  sudo usermod -aG docker $USER")
            _print_status("Docker preflight", "fail")
            sys.exit(result.returncode)
        _print_status("Docker preflight", "pass")
    else:
        _print_status("Docker preflight", "skip")

    if not skip_k8s:
        print("Running local Kubernetes smoke test (tools/local/local_kubernetes_smoke.sh)...")
        cmd = ["./tools/local/local_kubernetes_smoke.sh"]
        result = _run(cmd, check=False, label="k8s-smoke")
        if result.returncode != 0:
            err_text = (result.stderr or "") + "\n" + (result.stdout or "")
            if "permission denied" in err_text.lower():
                print("Kubernetes smoke test failed; retrying with sudo...")
                result = _run(["sudo"] + cmd, check=False, label="k8s-smoke-sudo")
        if result.returncode != 0:
            print("ERROR: local Kubernetes smoke test failed. Aborting release.", file=sys.stderr)
            err_text = (result.stderr or "") + "\n" + (result.stdout or "")
            if "missing required command: kind" in err_text.lower() or "missing required command: kubectl" in err_text.lower():
                print("Hint: install kind + kubectl with:")
                print("  ./tools/k8s/pypnm_kind_vm_bootstrap.sh")
                print("Also ensure Docker is running: sudo systemctl start docker")
            _print_status("Kubernetes smoke", "fail")
            sys.exit(result.returncode)
        _print_status("Kubernetes smoke", "pass")
    else:
        _print_status("Kubernetes smoke", "skip")

    _run_mkdocs_strict()

    if test_release:
        print("Skipping commit/tag/push (--test-release set).")
        _restore_previous_version(current_version, tag_prefix)
        _print_status("Commit", "skip")
        _print_status("Tag", "skip")
        _print_status("Push", "skip")
        return

    _commit_version_bump(new_version)
    tag_name = _create_tag(new_version, tag_prefix, rc_suffix)
    _push_branch_and_tag(branch, tag_name)

    _print_status("Release report", "pass")
    report_mode = "test-release" if test_release else "release"
    report_path = _write_release_report(report_commit, new_version, tag_name, branch, report_mode)
    counts = _summarize_sections(_collect_commit_files(report_commit))
    print("\nRelease change summary (last commit):")
    print(_render_table(counts))
    print(f"Release report saved to {report_path}")

    print(f"Release {new_version} completed on branch '{branch}' with tag '{tag_name}'.")


if __name__ == "__main__":
    main()
