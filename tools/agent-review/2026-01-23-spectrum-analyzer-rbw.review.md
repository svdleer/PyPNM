## Agent Review Bundle Summary
- Goal: Add pytest coverage for the new SNMP bulk_walk method and keep prior doc/link updates tracked.
- Changes: Added bulk_walk tests with mocked SNMP machinery, kept single-capture doc moves/links, and fixed mkdocs anchor warnings earlier in task.
- Files: AGENTS.md, CODING_AGENTS.md, README.md, docs/api/fast-api/file-manager/file-manager-api.md, docs/api/fast-api/index.md, docs/api/fast-api/single/general/diplexer-configuration.md, docs/api/fast-api/single/general/docsis-base-configuration.md, docs/api/fast-api/single/general/event-log.md, docs/api/fast-api/single/general/reset-cm.md, docs/api/fast-api/single/general/system-description.md, docs/api/fast-api/single/general/up-time.md, docs/api/fast-api/single/index.md, docs/api/fast-api/single/spectrum-analyzer.md, docs/api/fast-api/single/spectrum-analyzer/spectrum-analyzer.md, docs/docker/install.md, docs/gallery/index.md, docs/system/system-config.md, mkdocs.yml, src/pypnm/lib/constants.py, src/pypnm/lib/types.py, src/pypnm/pnm/data_type/DocsIf3CmSpectrumAnalysisCtrlCmd.py, tests/test_spectrum_analysis_ctrl_cmd_rbw.py, tests/test_snmp_v2c_bulk_walk.py.
- Tests: `python3 -m compileall src`, `ruff check src`, `ruff format --check .` (fails: formatting drift), `pytest -q`.
- Notes: Ruff format check reports pre-existing formatting drift across the repo.

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
- Keep a brief summary of user prompts after any request for a commit message so it can be referenced if asked again.
- When asked for a commit message, respond with the specified format and keep it succinct.
- Default response content should be a summary, changed file list, commands run, and the review bundle path.
- Always end tasks with an agent review bundle containing the full contents of all files touched in the task.
- Agent review bundles must start with the standard summary template block below (before any `# FILE:` sections).
- If a review bundle exceeds 3000 lines, split it into multiple bundles without splitting files. Use a part naming convention like `name.part-1.review.md`, `name.part-2.review.md`, and repeat the summary block at the top of each part.
- When the user says `CAT_FILES`, create a single bundle file containing the full contents of every file touched in the task, each preceded by `# FILE: <path>`, and provide the `cat` command for the bundle.

### Commit Message Format

- One line summary (max 50 characters)
- Detailed description (max 72 characters per line)

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
- Keep a brief summary of user prompts after any request for a commit message so it can be referenced if asked again.
- When asked for a commit message, respond with the specified format and keep it succinct.

### Commit Message Format

- One line summary (max 50 characters)
- Detailed description (max 72 characters per line) preface with a `-`

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

# FILE: README.md
<p align="center">
  <a href="docs/index.md">
    <picture>
      <source srcset="docs/images/logo/pypnm-dark-mode-hp.png"
              media="(prefers-color-scheme: dark)" />
      <img src="docs/images/logo/pypnm-light-mode-hp.png"
           alt="PyPNM Logo"
           width="200"
           style="border-radius: 24px;" />
    </picture>
  </a>
</p>

# PyPNM - Proactive Network Maintenance Toolkit

[![PyPNM Version](https://img.shields.io/github/v/tag/PyPNMApps/PyPNM?label=PyPNM&sort=semver)](https://github.com/PyPNMApps/PyPNM/tags)
[![PyPI - Version](https://img.shields.io/pypi/v/pypnm-docsis.svg)](https://pypi.org/project/pypnm-docsis/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pypnm-docsis.svg)](https://pypi.org/project/pypnm-docsis/)
[![Daily Build](https://github.com/PyPNMApps/PyPNM/actions/workflows/daily-build.yml/badge.svg?branch=main)](https://github.com/PyPNMApps/PyPNM/actions/workflows/daily-build.yml)
![CodeQL](https://github.com/PyPNMApps/PyPNM/actions/workflows/codeql.yml/badge.svg)
[![PyPI Install Check](https://github.com/PyPNMApps/PyPNM/actions/workflows/pypi-install-check.yml/badge.svg?branch=main)](https://github.com/PyPNMApps/PyPNM/actions/workflows/pypi-install-check.yml)
[![Kubernetes (kind)](https://github.com/PyPNMApps/PyPNM/actions/workflows/kubernetes-kind.yml/badge.svg?branch=main)](https://github.com/PyPNMApps/PyPNM/actions/workflows/kubernetes-kind.yml)
[![GHCR Publish](https://github.com/PyPNMApps/PyPNM/actions/workflows/publish-ghcr.yml/badge.svg)](https://github.com/PyPNMApps/PyPNM/actions/workflows/publish-ghcr.yml)
[![Dockerized](https://img.shields.io/badge/GHCR-latest-2496ED?logo=docker&logoColor=white&label=Docker)](https://github.com/PyPNMApps/PyPNM/pkgs/container/pypnm)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%20%7C%2024.04%20LTS-E95420?logo=ubuntu&logoColor=white)](https://github.com/PyPNMApps/PyPNM)

PyPNM is a DOCSIS 3.x/4.0 Proactive Network Maintenance toolkit for engineers who want repeatable, scriptable visibility into modem health. It can run purely as a Python library or as a FastAPI web service for real-time dashboards and offline analysis workflows.

## Table of contents

- [Choose your path](#choose-your-path)
- [Kubernetes | Docker](#kubernetes--docker)
  - [Docker](#docker-deploy)
  - [Kubernetes (kind)](#k8s-deploy)
- [Key Features](#key-features)
- [Prerequisites](#prerequisites)
  - [Operating Systems](#operating-systems)
  - [Shell Dependencies](#shell-dependencies)
- [Getting Started](#getting-started)
  - [Install From PyPI (Library Only)](#install-from-pypi-library-only)
  - [1) Clone](#1-clone)
  - [2) Install](#2-install)
  - [3) Activate The Virtual Environment](#3-activate-the-virtual-environment)
  - [4) Configure System Settings](#4-configure-system-settings)
  - [5) Run The FastAPI Service Launcher](#5-run-the-fastapi-service-launcher)
  - [6) (Optional) Serve The Documentation](#6-optional-serve-the-documentation)
  - [7) Explore The API](#7-explore-the-api)
- [Documentation](#documentation)
- [Gallery](docs/gallery/index.md)
- [SNMP Notes](#snmp-notes)
- [CableLabs Specifications & MIBs](#cablelabs-specifications--mibs)
- [PNM Architecture & Guidance](#pnm-architecture--guidance)
- [License](#license)
- [Maintainer](#maintainer)

## Choose your path

| Path | Description |
| --- | --- |
| [Kubernetes deploy (kind)](#k8s-deploy) | Run PyPNM in a local kind cluster (GHCR image). |
| [Docker deploy](#docker-deploy) | Install and run the containerized PyPNM service. |
| [Use PyPNM as a library](#install-from-pypi-library-only) | Install `pypnm-docsis` into an existing Python environment. |
| [Run the full platform](#1-clone) | Clone the repo and use the full FastAPI + tooling stack. |

## Kubernetes | Docker

<a id="docker-deploy"></a>
### Docker (Recommended) - [Install Docker](docs/docker/install-docker.md) | [Install PyPNM Container](docs/docker/install.md) | [Commands](docs/docker/commands.md)

Fast install (helper script; latest release auto-detected):

```bash
TAG="v1.0.36.0"
PORT=8080

curl -fsSLo install-pypnm-docker-container.sh \
  https://raw.githubusercontent.com/PyPNMApps/PyPNM/main/scripts/install-pypnm-docker-container.sh

chmod +x install-pypnm-docker-container.sh

sudo ./install-pypnm-docker-container.sh --tag ${TAG} --port ${PORT}
```

If Docker isn’t on your host yet, follow the [Install Docker prerequisites](docs/docker/install-docker.md) guide first.

More Docker options and compose workflows: [PyPNM Docker Installation](docs/docker/install.md) and [Developer Workflow](docs/docker/commands.md#developer-workflow).

<a id="k8s-deploy"></a>
### Kubernetes (kind) dev clusters

Kubernetes quick links:
- [Install kind](docs/kubernetes/kind-install.md)
- [Deploy PyPNM](docs/kubernetes/pypnm-deploy.md)
- [kind + FreeLens (VM)](docs/kubernetes/kind-freelens.md)

We continuously test the manifests with a kind-based CI smoke test (`Kubernetes (kind)` badge above). Follow the [kind quickstart](docs/kubernetes/quickstart.md) or the [detailed deployment guide](docs/kubernetes/pypnm-deploy.md) to run PyPNM inside a local single-node cluster; multi-node scenarios are not covered yet (see [pros/cons](docs/kubernetes/pros-cons.md)).

Script-only deployment (no repo clone) is documented in [PyPNM deploy](docs/kubernetes/pypnm-deploy.md#script-only-deploy-no-repo-clone).

## Prerequisites

### Operating systems

Linux, validated on:

- Ubuntu 22.04 LTS
- Ubuntu 24.04 LTS

Other modern Linux distributions may work but are not yet part of the test matrix.

### Shell dependencies

From a fresh system, install Git:

```bash
sudo apt update
sudo apt install -y git
```

Python and remaining dependencies are handled by the installer.

## Getting started

### Install from PyPI (library only)

If you only need the library, install from PyPI:

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install pypnm-docsis
  ```

Uninstall and cleanup:

  ```bash
  pip uninstall pypnm-docsis
  rm -f ~/.ssh/pypnm_secrets.key
  ```

## FastAPI Service and Development

### 1) Clone

  ```bash
  git clone https://github.com/PyPNMApps/PyPNM.git
  cd PyPNM
```

### 2) Install

Run the installer:

  ```bash
  ./install.sh
  ```

Common flags (use as needed):

| Flag | Purpose |
|------|---------|
| `--development` | Installs Docker Engine + kind/kubectl. See [Development Install](docs/install/development.md). |
| `--clean`       | Removes prior install artifacts (venv/build/dist/cache) before installing. Preserves data and system configuration. |
| `--purge-cache` | Clears pip cache after activating the venv (use with `--clean` when troubleshooting stale installs). |
| `--pnm-file-retrieval-setup` | Launches `tools/pnm/pnm_file_retrieval_setup.py` after install. See the [PNM File Retrieval Overview](docs/topology/index.md). |
| `--demo-mode`   | Seeds demo data/paths for offline exploration. See the [demo mode guide](./demo/README.md). |
| `--production`  | Reverts demo-mode changes and restores your previous `system.json` backup. |

Installer extras: adds shell aliases when available; source your rc file once to pick them up.

### 3) Activate the virtual environment

If you used the installer defaults, activate the `.env` environment:

  ```bash
  source .env/bin/activate
  ```

### 4) Configure system settings

System configuration lives in [deploy/docker/config/system.json](https://github.com/PyPNMApps/PyPNM/blob/main/deploy/docker/config/system.json).

- [Config menu](docs/system/menu.md): `source ~/.bashrc && config-menu`
- [System Configuration Reference](docs/system/system-config.md): field-by-field descriptions and defaults
If you installed with `--pnm-file-retrieval-setup`, it runs automatically and backs up `system.json` first.

### 5) [Run the FastAPI service launcher](docs/system/pypnm-cli.md)

HTTP (default: `http://127.0.0.1:8000`):

  ```bash
  pypnm
  ```

Development hot-reload:

  ```bash
  pypnm --reload
  ```

### 6) (Optional) Serve the documentation

HTTP (default: `http://127.0.0.1:8001`):

  ```bash
  mkdocs serve
  ```

### 7) Explore the API

Installed services and docs are available at the following URLs:

| Git Clone | Docker |
|-----------|--------|
| [FastAPI Swagger UI](http://localhost:8000/docs)  | [FastAPI Swagger UI](http://localhost:8080/docs)  |
| [FastAPI ReDoc](http://localhost:8000/redoc)      | [FastAPI ReDoc](http://localhost:8080/redoc)      |
| [MkDocs docs](http://localhost:8001)              | [MkDocs docs](http://localhost:8081)              |

## Recommendations

Postman is a great tool for testing the FastAPI endpoints:
- [Download Postman](https://www.postman.com/downloads/)

## Documentation

- [Docs hub](./docs/index.md) - task-based entry point (install, configure, operate, contribute).
- [FastAPI reference](./docs/api/fast-api/index.md) - Endpoint details and request/response schemas.
- [Python API reference](./docs/api/python/index.md) - Importable helpers and data models.

## SNMP notes

- SNMPv2c is supported  
- SNMPv3 is currently stubbed and not yet supported

## CableLabs specifications & MIBs

- [CM-SP-MULPIv3.1](https://www.cablelabs.com/specifications/CM-SP-MULPIv3.1)  
- [CM-SP-CM-OSSIv3.1](https://www.cablelabs.com/specifications/CM-SP-CM-OSSIv3.1)  
- [CM-SP-MULPIv4.0](https://www.cablelabs.com/specifications/CM-SP-MULPIv4.0)  
- [CM-SP-CM-OSSIv4.0](https://www.cablelabs.com/specifications/CM-SP-CM-OSSIv4.0)  
- [DOCSIS MIBs](https://mibs.cablelabs.com/MIBs/DOCSIS/)

## PNM architecture & guidance

- [CM-TR-PMA](https://www.cablelabs.com/specifications/CM-TR-PMA)  
- [CM-GL-PNM-HFC](https://www.cablelabs.com/specifications/CM-GL-PNM-HFC)  
- [CM-GL-PNM-3.1](https://www.cablelabs.com/specifications/CM-GL-PNM-3.1)

## License

[`Apache License 2.0`](./LICENSE) and [`NOTICE`](./NOTICE)

## Next steps

- Review [PNM topology options](docs/topology/index.md) to decide how captures will move through your network.
- Follow the [System Configuration guide](docs/system/system-config.md) to tailor `system.json` for your lab.
- Explore [system tools](docs/system/menu.md) and [operational scripts](docs/tools/index.md) for day-to-day automation.

## Maintainer

Maurice Garcia

- [Email](mailto:mgarcia01752@outlook.com)  
- [LinkedIn](https://www.linkedin.com/in/mauricemgarcia/)

# FILE: docs/api/fast-api/file-manager/file-manager-api.md
# PNM file manager API

REST API for searching, downloading, uploading, and analyzing PNM capture files stored in PyPNM.

> **When to use**
> - You need to grab captures produced by the single- or multi-capture workflows.
> - You want to upload an external capture into the PyPNM ledger so downstream tools can analyze it.
> - You need raw access (download or hexdump) to troubleshoot a specific transaction.

> **Prerequisites**
> - Captures already exist in the transaction database (produced via the capture workflows or uploaded).
> - The FastAPI service is running with access to the `.data/` directories configured in `system.json`.
> - You understand the [standard response schema](../common/response.md) for success/error envelopes.

Endpoints live under the FastAPI router `/docs/pnm/files`.

Typical flow:

1. Capture or upload files so they appear in the transaction database.
2. Search or list files by MAC address or operation.
3. Download single files or grouped ZIPs.
4. Optionally trigger analysis or hexdump inspection on specific transactions.
5. Use results downstream (for example, with the [multi-capture analysis modules](../multi/index.md#advanced-analysis-modules)).

## Endpoints

### 1) Search files by MAC address

**Endpoint**

```text
GET /docs/pnm/files/searchFiles/{mac_address}
```

**Description**

Return a mapping of MAC address to a list of file entries associated with that modem. Each file entry carries the transaction identifier, filename, PNM test type, timestamp, and optional system description metadata.

**Path Parameter**

| Name        | Type   | Description                                                               |
| ----------- | ------ | ------------------------------------------------------------------------- |
| mac_address | string | MAC address of the cable modem. Example: `aa:bb:cc:dd:ee:ff`             |

**Successful Response (200)**

- Content type: `application/json`
- Body schema: `FileQueryResponse`

```json
{
  "files": {
    "aa:bb:cc:dd:ee:ff": [
      {
        "transaction_id": "f67dd3ffb40420d6",
        "filename": "ds_ofdm_rxmer_per_subcar_aa_bb_cc_dd_ee_ff.bin",
        "pnm_test_type": "DS_OFDM_RXMER_PER_SUBCAR",
        "timestamp": 1763736292,
        "system_description": {
          "HW_REV": "1.0",
          "VENDOR": "LANCity",
          "BOOTR": "NONE",
          "SW_REV": "1.0.0",
          "MODEL": "LCPET-3"
        }
      }
    ]
  }
}
```

### 2) Download file by transaction ID

**Endpoint**

```text
GET /docs/pnm/files/download/transactionID/{transaction_id}
```

**Description**

Download a single PNM capture file associated with a given transaction identifier.

**Path Parameter**

| Name           | Type   | Description                                          |
| -------------- | ------ | ---------------------------------------------------- |
| transaction_id | string | Unique transaction identifier for the PNM file.     |

**Successful Response (200)**

- Content type: `application/octet-stream`
- Body: Raw PNM binary file.

If the transaction ID is not found:

```json
{
  "detail": "Transaction ID not found."
}
```

with HTTP 404 status.

### 3) Download files by MAC address (ZIP archive)

**Endpoint**

```text
GET /docs/pnm/files/download/macAddress/{mac_address}
```

**Description**

Resolve all transactions for the given MAC address, collect their on-disk PNM files, and return a ZIP archive containing all existing files.

**Path Parameter**

| Name        | Type   | Description                                                               |
| ----------- | ------ | ------------------------------------------------------------------------- |
| mac_address | string | MAC address of the cable modem. Example: `aa:bb:cc:dd:ee:ff`             |

**Successful Response (200)**

- Content type: `application/zip`
- Body: ZIP archive of PNM capture files.

Errors can include:

```json
{
  "detail": "No transactions found for MAC address."
}
```

or

```json
{
  "detail": "No files on disk for MAC address."
}
```

both with HTTP 404 status.

### 4) Download files by operation ID (ZIP archive)

**Endpoint**

```text
GET /docs/pnm/files/download/operationID/{operation_id}
```

**Description**

Resolve the capture group associated with a given operation ID, collect all transactions in that group, and return a ZIP archive containing all corresponding PNM files that exist on disk.

**Path Parameter**

| Name         | Type   | Description                                   |
| ------------ | ------ | --------------------------------------------- |
| operation_id | string | Operation identifier from the capture service.|

**Successful Response (200)**

- Content type: `application/zip`
- Body: ZIP archive of all PNM files associated with the operation.

Example error:

```json
{
  "detail": "No transactions found for Operation ID."
}
```

or

```json
{
  "detail": "No files on disk for Operation ID."
}
```

with HTTP 404 status.

### 5) Upload PNM file

**Endpoint**

```text
POST /docs/pnm/files/upload
```

**Description**

Upload a PNM capture file (for example, RxMER, constellation, histogram, spectrum) via multipart/form-data. The server persists the file, identifies the PNM file type from its header, maps it to a DOCSIS test, and registers a transaction using a placeholder null MAC address (to be backfilled later).

**Request**

- Content type: `multipart/form-data`
- Fields:

| Name | Type        | Description                                                                     |
| ---- | ----------- | ------------------------------------------------------------------------------- |
| file | binary file | Raw PNM capture file payload.                                                   |

**Successful Response (200)**

- Content type: `application/json`
- Body schema: `UploadFileResponse`

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "filename": "ds_ofdm_rxmer_per_subcar_example.bin",
  "transaction_id": "ea18519a572e2487"
}
```

If the file type is unrecognized:

```json
{
  "detail": "Unsupported or unrecognized PNM file type."
}
```

with HTTP 400 status.

### 6) Analyze PNM file

**Endpoint**

```text
POST /docs/pnm/files/getAnalysis
```

**Description**

Trigger an analysis run for a specific PNM file identified by transaction ID. The backend resolves the transaction, locates the PNM file, inspects its header, and routes it to the appropriate analysis pipeline.

The exact request/response schema is defined by `FileAnalysisRequest` and `AnalysisJsonResponse` in the FastAPI OpenAPI documentation. At a high level, the request specifies the transaction ID, analysis type, and output format (JSON or archive).

**Request**

- Content type: `application/json`
- Body schema: `FileAnalysisRequest`

Example (JSON output):

```json
{
  "search": {
    "transaction_id": "ea18519a572e2487"
  },
  "analysis": {
    "type": "BASIC",
    "output": {
      "type": "JSON"
    }
  }
}
```

**Successful Response (200)**

- Content type: `application/json`
- Body schema: `AnalysisJsonResponse`

Example (truncated):

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "pnm_file_type": "RECEIVE_MODULATION_ERROR_RATIO",
  "status": "success",
  "analysis": {
    "device_details": {
      "HW_REV": "1.0",
      "VENDOR": "LANCity",
      "BOOTR": "NONE",
      "SW_REV": "1.0.0",
      "MODEL": "LCPET-3"
    },
    "pnm_header": {
      "file_type": "PNN5",
      "file_type_version": 5,
      "major_version": 1,
      "minor_version": 0,
      "capture_time": 1495481
    },
    "...": "analysis fields omitted for brevity"
  }
}
```

If the transaction is not found:

```json
{
  "detail": "Transaction ID not found for analysis."
}
```

with HTTP 404 status.

### 7) Hexdump of a PNM file via transaction ID

**Endpoint**

```text
GET /docs/pnm/files/getHexdump/transactionID/{transaction_id}
```

**Description**

Generate a textual hexdump view of the raw PNM file associated with a given transaction ID. This is useful for low-level inspection, debugging binary parsing issues, or forensic analysis of the PNM header and payload.

The hexdump is returned as JSON: each line includes a byte offset, hex-encoded bytes, and an ASCII representation.

**Path Parameter**

| Name           | Type   | Description                                              |
| -------------- | ------ | -------------------------------------------------------- |
| transaction_id | string | Unique transaction identifier for the PNM file to dump. |

**Query Parameter**

| Name           | Type | Description                                                                                  |
| -------------- | ---- | -------------------------------------------------------------------------------------------- |
| bytes_per_line | int  | Optional bytes-per-line for each hexdump row. If omitted or non-positive, a default is used.|

**Successful Response (200)**

- Content type: `application/json`
- Body schema: `HexDumpResponse`

Example:

```json
{
  "transaction_id": "8f17fcdd4c0138ef",
  "bytes_per_line": 16,
  "lines": [
    "00000000  50 4e 4d 00 05 01 00 00  00 00 00 00 00 00 00 00  |PNM.............|",
    "00000010  01 23 45 67 89 ab cd ef  00 11 22 33 44 55 66 77  |.#Eg......\"3DUfw|"
  ]
}
```

If the transaction ID or file cannot be resolved, typical errors include:

```json
{
  "detail": "Transaction ID not found."
}
```

or

```json
{
  "detail": "PNM file not found on disk."
}
```

with HTTP 404 status, or:

```json
{
  "detail": "Failed to generate hexdump for PNM file."
}
```

with HTTP 500 status.

## Request and response examples

This section summarizes the core JSON shapes used by the PNM File Manager endpoints. All types are shown as they appear on the wire (FastAPI OpenAPI / SwaggerUI and tools such as Postman or curl).

### FileQueryResponse (search files)

```json
{
  "files": {
    "aa:bb:cc:dd:ee:ff": [
      {
        "transaction_id": "f67dd3ffb40420d6",
        "filename": "ds_ofdm_rxmer_per_subcar_aa_bb_cc_dd_ee_ff.bin",
        "pnm_test_type": "DS_OFDM_RXMER_PER_SUBCAR",
        "timestamp": 1763736292,
        "system_description": {
          "HW_REV": "1.0",
          "VENDOR": "LANCity",
          "BOOTR": "NONE",
          "SW_REV": "1.0.0",
          "MODEL": "LCPET-3"
        }
      }
    ]
  }
}
```

### UploadFileResponse (upload PNM file)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "filename": "ds_ofdm_rxmer_per_subcar_example.bin",
  "transaction_id": "ea18519a572e2487"
}
```

### AnalysisJsonResponse (analyze PNM file)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "pnm_file_type": "RECEIVE_MODULATION_ERROR_RATIO",
  "status": "success",
  "analysis": {
    "device_details": {
      "HW_REV": "1.0",
      "VENDOR": "LANCity",
      "BOOTR": "NONE",
      "SW_REV": "1.0.0",
      "MODEL": "LCPET-3"
    },
    "pnm_header": {
      "file_type": "PNN5",
      "file_type_version": 5,
      "major_version": 1,
      "minor_version": 0,
      "capture_time": 1495481
    },
    "...": "analysis fields omitted for brevity"
  }
}
```

## Next steps

- Need to generate new captures? Start with the [single capture](../single/index.md) or [multi capture](../multi/index.md) workflows.
- Looking for where files live on disk? Review the [system configuration reference](../../../system/system-config.md#pnmfileretrieval) for storage paths.

# FILE: docs/api/fast-api/index.md
# FastAPI overview

PyPNM exposes a FastAPI service that you can run locally ([localhost API](http://127.0.0.1:8000) by default) or deploy to your own infrastructure. Use this section whenever you call the service over HTTP.

> **Before you start**
>
> - Default base URL: [FastAPI host](http://<host>:8000) unless overridden via CLI flags (see [pypnm CLI](../../system/pypnm-cli.md)).
> - Authentication: none by default; secure deployments should front the API with network ACLs or a proxy.
> - Response envelope: every endpoint returns the standard [response schema](common/response.md). Familiarize yourself with it before consuming the API.
> - Errors and retries: see [FastAPI status codes](status/fast-api-status-codes.md) for retry guidance and validation failures.

## Pick a guide

| Section | When to use it | Common actions |
|---------|----------------|----------------|
| [PyPNM](pypnm/index.md) | Service/system endpoints (health, status, operations). | Check health; list operations; fetch service status. |
| [Single capture](single/index.md) | One-shot capture/queries (downstream, upstream, system). | Pull RxMER/FEC once; read event log; spectrum/histogram. |
| [Multi capture](multi/index.md) | Scheduled or multi-snapshot workflows and analysis. | Start capture; poll status; download ZIP; stop early. |
| [File management](file-manager/file-manager-api.md) | Upload/download files to/from the system. | Upload config; download logs; list stored files. |
| [Common schemas](common/index.md) | Request/response conventions and shared schemas. | Review request schema; response wrapper; error model. |
| [Status codes](status/fast-api-status-codes.md) | API status and error codes. | Map errors to fixes; see retry/validation guidance. |

# FILE: docs/api/fast-api/single/general/diplexer-configuration.md
# DOCSIS 3.1 System Diplexer

Provides Insight Into The Diplexer Configuration Of A DOCSIS 3.1 Cable Modem (Upstream/Downstream Band Splits, Capabilities, And Configured Band Edges). Use This To Audit Band Plans And Validate Mid-Split/High-Split Compatibility.

## Endpoint

**POST** `/docs/if31/system/diplexer`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `data`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "diplexer": {
      "diplexer_capability": 28,
      "cfg_band_edge": 204000000,
      "ds_lower_capability": 3,
      "cfg_ds_lower_band_edge": 258000000,
      "ds_upper_capability": 2,
      "cfg_ds_upper_band_edge": 1794000000
    }
  }
}
```

## Diplexer Fields

| Field                    | Type | Units | Description                                   |
| ------------------------ | ---- | ----- | --------------------------------------------- |
| `diplexer_capability`    | int  | —     | Upstream/Downstream diplexer capability code. |
| `cfg_band_edge`          | int  | Hz    | Configured **upstream** band edge frequency.  |
| `ds_lower_capability`    | int  | —     | Downstream lower frequency capability code.   |
| `cfg_ds_lower_band_edge` | int  | Hz    | Configured **downstream** lower band edge.    |
| `ds_upper_capability`    | int  | —     | Downstream upper frequency capability code.   |
| `cfg_ds_upper_band_edge` | int  | Hz    | Configured **downstream** upper band edge.    |

## Notes

* Values are reported in Hertz (Hz).
* Capability codes are device/implementation specific (per CableLabs/vendor definitions).
* Compare configured edges with plant split (e.g., 85 MHz mid-split, 204 MHz high-split) to verify alignment.

# FILE: docs/api/fast-api/single/general/docsis-base-configuration.md
# DOCSIS Base Capability

Provides Insight Into The DOCSIS Radio Frequency (RF) Specification Version Supported By A Cable Modem (CM) Or Cable Modem Termination System (CMTS). Based On `docsIf31DocsisBaseCapability` (DOCSIS-IF3-MIB).

## Endpoint

**POST** `/docs/if31/docsis/baseCapability`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `data`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": "DOCSIS Base Capability Retrieved Successfully.",
  "data": {
    "docsis_version": "DOCSIS_40",
    "clabs_docsis_version": 6
  }
}
```

## Field Definitions

| Field                       | Type   | Description                                                                  |
| --------------------------- | ------ | ---------------------------------------------------------------------------- |
| `mac_address`               | string | Target CM MAC Address Returned In The Common Envelope.                       |
| `status`                    | int    | Status Code (`0` = Success).                                                 |
| `message`                   | string | Human-Readable Result Message.                                               |
| `data.docsis_version`       | string | DOCSIS Version As Enum String (e.g., `DOCSIS_10`, `DOCSIS_31`, `DOCSIS_40`). |
| `data.clabs_docsis_version` | int    | Integer Value From `ClabsDocsisVersion` (`0`=other, `1`=1.0, …, `6`=4.0).    |

### Reference: `ClabsDocsisVersion`

```json
ClabsDocsisVersion ::= TEXTUAL-CONVENTION
    SYNTAX INTEGER {
        other (0),
        docsis10 (1),
        docsis11 (2),
        docsis20 (3),
        docsis30 (4),
        docsis31 (5),
        docsis40 (6)
    }
```

## Notes

* This Object Supersedes `docsIfDocsisBaseCapability` From RFC-4546 And Reflects The Highest RF Version Supported.
* Values Are Sourced From DOCSIS-IF3-MIB (`docsIf31MibObjects`).

# FILE: docs/api/fast-api/single/general/event-log.md
# DOCSIS Device Event Log

Provides Access To A Cable Modem’s Device Event Log For Operational And Troubleshooting Insight (Ranging, T3/T4, Profile Changes, CM-Status).

## Endpoint

**POST** `/docs/dev/eventLog`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data.logs` is an array of log entries reported by the device.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "logs": [
      {
        "docsDevEvFirstTime": "2025-10-19T18:39:24",
        "docsDevEvLastTime": "2025-10-19T18:39:24",
        "docsDevEvCounts": 1,
        "docsDevEvLevel": 6,
        "docsDevEvId": 67061601,
        "docsDevEvText": "US profile assignment change.  US Chan ID: 42; Previous Profile: 12; New Profile: 11.;CM-MAC=aa:bb:cc:dd:ee:ff;CMTS-MAC=aa:bb:cc:dd:ee:ff;CM-QOS=1.1;CM-VER=4.0;"
      },
      {
        "docsDevEvFirstTime": "2025-10-19T18:40:09",
        "docsDevEvLastTime": "2025-10-19T18:40:09",
        "docsDevEvCounts": 3,
        "docsDevEvLevel": 6,
        "docsDevEvId": 74010100,
        "docsDevEvText": "CM-STATUS message sent.  Event Type Code: 5; Chan ID: 13; DSID: N/A; MAC Addr: N/A; OFDM/OFDMA Profile ID: N/A.;CM-MAC=aa:bb:cc:dd:ee:ff;CMTS-MAC=aa:bb:cc:dd:ee:ff;CM-QOS=1.1;CM-VER=4.0;"
      },
      {
        "docsDevEvFirstTime": "2025-10-19T18:41:24",
        "docsDevEvLastTime": "2025-10-19T18:49:14",
        "docsDevEvCounts": 35,
        "docsDevEvLevel": 6,
        "docsDevEvId": 74010100,
        "docsDevEvText": "CM-STATUS message sent.  Event Type Code: 5; Chan ID: 13; DSID: N/A; MAC Addr: N/A; OFDM/OFDMA Profile ID: N/A.;CM-MAC=aa:bb:cc:dd:ee:ff;CMTS-MAC=aa:bb:cc:dd:ee:ff;CM-QOS=1.1;CM-VER=4.0;"
      },
      { "...": "additional log entries elided" }
    ]
  }
}
```

## Response Field Details

| Field                | Type   | Description                                                                            |
| -------------------- | ------ | -------------------------------------------------------------------------------------- |
| `mac_address`        | string | MAC address of the cable modem returned in the common envelope.                        |
| `status`             | int    | Operation status (`0` = success; non-zero indicates failure).                          |
| `message`            | string | Human-readable status or error message (nullable).                                     |
| `data.logs`          | array  | Array of device log entry objects.                                                     |
| `docsDevEvFirstTime` | string | First occurrence of the event (ISO-8601 timestamp).                                    |
| `docsDevEvLastTime`  | string | Most recent occurrence of the event (ISO-8601 timestamp).                              |
| `docsDevEvCounts`    | int    | Number of times the event has occurred.                                                |
| `docsDevEvLevel`     | int    | Syslog-style severity (`0`=Emergency, `1`=Alert, …, `7`=Debug; lower = more critical). |
| `docsDevEvId`        | int    | Numeric event identifier.                                                              |
| `docsDevEvText`      | string | Human-readable message; often includes CM/CMTS MACs, profiles, versions.               |

## Common Event Codes

| Event ID | Description                             |
| -------- | --------------------------------------- |
| 67061601 | US profile assignment change.           |
| 74010100 | CM-STATUS message sent.                 |
| 74010200 | Ranging request sent.                   |
| 74010300 | Ranging response received.              |
| 74020100 | T3 timeout occurred.                    |
| 74020200 | T4 timeout occurred.                    |
| 74030100 | Upstream channel change completed.      |
| 74030200 | Downstream channel change completed.    |
| 74040100 | Ranging success.                        |
| 74040200 | Ranging failure.                        |
| 74040300 | Ranging aborted.                        |
| 74050100 | Power adjustment performed.             |
| 74060100 | Cable modem reset (power cycle).        |
| 74060200 | Firmware download initiated.            |
| 74060300 | Firmware download completed.            |

## CM STATUS

| Event Type Code | Description                                                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| 0               | Reserved (no use)                                                                                        |
| 1               | Secondary Channel MDD Timeout (the MDD timer on a secondary channel expired)                             |
| 2               | QAM / FEC Lock Failure (loss of QAM or Forward Error Correction lock on downstream)                      |
| 3               | Sequence Out-of-Range (a packet sequence number was out of the expected range)                           |
| 4               | Secondary Channel MDD Recovery (receipt of MDD on a secondary channel)                                   |
| 5               | QAM / FEC Lock Recovery (channel regained lock)                                                          |
| 6               | T4 Timeout (station maintenance / broadcast failure)                                                     |
| 7               | T3 Retries Exceeded (ranging retries maximum exceeded)                                                   |
| 8               | Successful Ranging After T3 Retries Exceeded (ranging recovery)                                          |
| 9               | CM Operating on Battery Backup (loss of A/C power for > 5 seconds)                                       |
| 10              | CM Returned to A/C Power (came back from battery to A/C)                                                 |
| 11              | MAC Removal Event (one or more MAC addresses removed, e.g., in port transition)                          |
| 12-15           | Reserved for future use                                                                                  |
| 16              | DS OFDM Profile Failure (FEC errors exceeded limit on a downstream OFDM profile)                         |
| 17              | Primary Downstream Change (lost primary downstream, switched to backup)                                  |
| 18              | DPD Mismatch (Some mismatch in DPD change count vs NCP odd/even bit)                                     |
| 20              | NCP Profile Failure (FEC errors exceeded limit on NCP profile)                                           |
| 21              | PLC Failure (FEC errors exceeded on PLC)                                                                 |
| 22              | NCP Profile Recovery (FEC recovered on NCP)                                                              |
| 23              | PLC Recovery (FEC recovery on PLC channel)                                                               |
| 24              | OFDM Profile Recovery (FEC recovery on OFDM profile)                                                     |
| 25              | OFDMA Profile Failure (modem unable to support a received profile)                                       |
| 26              | MAP Storage Overflow (maps in CM overflow buffer)                                                        |
| 27              | MAP Storage Almost Full                                                                                  |
| 28-255          | Reserved / for vendor extensions                                                                         |

## Notes

* Event levels follow syslog conventions: **0 (Emergency)** … **7 (Debug)**.
* Entries are semi-structured; downstream analytics may parse `docsDevEvText` for fields like channel IDs, profiles, and MACs.
* Devices may cap or rotate stored logs; poll and archive if long-term history is required.

# FILE: docs/api/fast-api/single/general/reset-cm.md
# DOCSIS Device Reset

Initiates A Remote Reset (Reboot) Of A DOCSIS Cable Modem Via SNMP.

## Endpoint

**POST** `/docs/dev/reset`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `data`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": "Reset command sent to cable modem at 192.168.0.100 successfully.",
  "data": null
}
```

## Response Field Details

| Field         | Type   | Description                                        |
| ------------- | ------ | -------------------------------------------------- |
| `mac_address` | string | MAC address of the targeted cable modem.           |
| `status`      | int    | Operation status (`0` = success; non-zero = fail). |
| `message`     | string | Success or error message with IP/MAC detail.       |
| `data`        | null   | Reserved for future use or extended diagnostics.   |

## Notes

* Ensure SNMP credentials are valid and the modem is reachable.
* This operation reboots the modem and will briefly disrupt service.
* Useful for remote troubleshooting, recovery, or provisioning workflows.

# FILE: docs/api/fast-api/single/general/system-description.md
# DOCSIS System Description

Retrieves Basic System Identity And Firmware Metadata From A DOCSIS Cable Modem Using SNMP.

## Endpoint

**POST** `/system/sysDescr`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `results`).
`results.sys_descr` contains parsed fields from the device’s `sysDescr`.

### Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "results": {
    "sys_descr": {
      "HW_REV": "1.0",
      "VENDOR": "LANCity",
      "BOOTR": "NONE",
      "SW_REV": "1.0.0",
      "MODEL": "LCPET-3"
    }
  }
}
```

## Response Field Details

| Field                      | Type    | Description                                           |
| -------------------------- | ------- | ----------------------------------------------------- |
| `mac_address`              | string  | MAC address of the queried device.                    |
| `status`                   | int     | Operation status (`0` = success; non-zero = failure). |
| `message`                  | string  | Optional result message.                              |
| `results`                  | object  | Envelope payload.                                     |
| `results.sys_descr`        | object  | Parsed key/value fields from SNMP `sysDescr`.         |
| `results.sys_descr.HW_REV` | string  | Hardware revision reported by the device.             |
| `results.sys_descr.VENDOR` | string  | Manufacturer name parsed from `sysDescr`.             |
| `results.sys_descr.BOOTR`  | string  | Bootloader version string.                            |
| `results.sys_descr.SW_REV` | string  | Software (firmware) version string.                   |
| `results.sys_descr.MODEL`  | string  | Model identifier reported by the device.              |
| `results.is_empty`         | boolean | `true` if parsing failed or response was empty.       |

## Notes

* Data is derived from the SNMP `sysDescr` OID (`1.3.6.1.2.1.1.1.0`) and parsed using known vendor patterns.
* Useful for populating device metadata dashboards or validation checks.
* `is_empty = true` typically means the response could not be parsed into structured fields.

> Noted: Using `aa:bb:cc:dd:ee:ff` as the MAC address in examples moving forward.

# FILE: docs/api/fast-api/single/general/up-time.md
# DOCSIS System Uptime

Retrieves The Current System Uptime Of A DOCSIS Cable Modem Using SNMP.

## Endpoint

**POST** `/system/upTime`

## Request

Use the SNMP-only format: [Common → Request](../../common/request.md)
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../common/response.md) (`mac_address`, `status`, `message`, `results`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "results": {
    "uptime": "0:13:11.180000"
  }
}
```

## Response Field Details

| Field            | Type   | Description                                           |
| ---------------- | ------ | ----------------------------------------------------- |
| `mac_address`    | string | MAC address of the queried device.                    |
| `status`         | int    | Operation status (`0` = success; non-zero = failure). |
| `results`        | object | Envelope payload.                                     |
| `results.uptime` | string | Formatted uptime (`HH:MM:SS.microseconds`).           |

## Notes

* SNMP OID used: `1.3.6.1.2.1.1.3.0` (system uptime in hundredths of a second).
* The service converts the raw counter into a human-readable duration.
* Use uptime trends to detect unexpected reboots or instability.

# FILE: docs/api/fast-api/single/index.md
# Single capture operations

Endpoints that perform one-shot capture or query against a single device. All routes live under the FastAPI service (default [localhost API](http://127.0.0.1:8000)). Use the [request](../common/request.md) and [response](../common/response.md) conventions when constructing payloads.

## Choose a telemetry path

### Downstream SNMP telemetry

Poll DOCSIS 3.0/3.1 downstream metrics directly from the cable modem via SNMP-backed endpoints.

| Reference | Purpose |
|-----------|---------|
| [OFDM channel statistics](ds/ofdm/channel-stats.md) | Snapshot OFDM physical channel KPIs. |
| [OFDM profile statistics](ds/ofdm/profile-stats.md) | Codeword stats per OFDM profile. |
| [SC-QAM channel statistics](ds/scqam/channel-stats.md) | SC-QAM downstream power/SNR stats. |
| [SC-QAM CW error rate](ds/scqam/cw-error-rate.md) | Codeword error counters. |

### Upstream SNMP telemetry

| Reference | Purpose |
|-----------|---------|
| [OFDMA channel statistics](us/ofdma/stats.md) | OFDMA upstream channel KPIs. |
| [ATDMA pre-equalization](us/atdma/chan/pre-equalization.md) | Tap coefficients and equalizer status. |
| [ATDMA channel statistics](us/atdma/chan/stats.md) | ATDMA upstream power/SNR stats. |

### FDD / FDX diplexer info

| Reference | Purpose |
|-----------|---------|
| [Diplexer band-edge capability](fdd/fdd-diplexer-band-edge-cap.md) | Supported diplexer range. |
| [Diplexer configuration (system)](fdd/fdd-system-diplexer-configuration.md) | System-level diplexer settings. |

### Cable modem utilities

| Reference | Purpose |
|-----------|---------|
| [Diplexer configuration](general/diplexer-configuration.md) | Device-level diplexer settings. |
| [DOCSIS base configuration](general/docsis-base-configuration.md) | Full DOCSIS configuration snapshot. |
| [Event log](general/event-log.md) | Retrieve the CM event log. |
| [Reset cable modem](general/reset-cm.md) | Invoke a remote reset. |
| [System description](general/system-description.md) | SNMP `sysDescr`. |
| [System uptime](general/up-time.md) | SNMP `sysUpTime`. |
| [Interface statistics](pnm/interface/stats.md) | Interface-level counters. |

## Proactive network maintenance (PNM)

### Downstream captures

| Reference | Purpose |
|-----------|---------|
| [OFDM RxMER](ds/ofdm/rxmer.md) | Raw RxMER, summaries, plots. |
| [OFDM MER margin](ds/ofdm/mer-margin.md) | MER margin helpers. |
| [OFDM channel estimation](ds/ofdm/channel-estimation.md) | Echo/distortion analysis. |
| [OFDM constellation display](ds/ofdm/constellation-display.md) | Symbol visualization. |
| [OFDM FEC summary](ds/ofdm/fec-summary.md) | Forward error correction stats. |
| [OFDM modulation profile](ds/ofdm/modulation-profile.md) | Bit loading and usage. |
| [Histogram](ds/histogram.md) | Power-level histogram. |

### Upstream captures

| Reference | Purpose |
|-----------|---------|
| [OFDMA pre-equalization](us/ofdma/pre-equalization.md) | Upstream tap coefficients. |

## Spectrum analysis

| Reference | Purpose |
|-----------|---------|
| [Spectrum analyzer endpoints](spectrum-analyzer/spectrum-analyzer.md) | Capture downstream spectrum snapshots (SC-QAM and OFDM options within). |
| [Spectrum analyzer RBW permutations](spectrum-analyzer.md) | Reference RBW auto-scale outcomes for common and edge-case spans. |

# FILE: docs/api/fast-api/single/spectrum-analyzer.md
# Spectrum Analyzer RBW Permutations

This document enumerates 50 scenarios generated by running `autoScaleSpectrumAnalyzerRbw` with wide and edge-case frequency spans, including full-bandwidth sweeps, SC-QAM-like 6 MHz channels, 192 MHz blocks, and DOCSIS 3.1 UHD-style ranges.

For endpoint details, see [Spectrum analyzer endpoints](spectrum-analyzer/spectrum-analyzer.md).

Legend:

- Adjust Segment Span: 1=true, 0=false
- Status: STATUS_OK means the RBW configuration is achievable; STATUS_NOK means it is not
- Changed: 1=parameter changes applied, 0=no change

| Scenario ID | Adjust Segment Span | First Center (Hz) | Last Center (Hz) | Total Span (Hz) | Bins per Segment | Target RBW (Hz) | Status | Changed | Segment Span (Hz) | New First Center (Hz) | New Last Center (Hz) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 54000000 | 1218000000 | 1164000000 | 8 | 25000 | STATUS_NOK | 0 | 1000000 | 54000000 | 1218000000 |
| 2 | 0 | 54000000 | 1218000000 | 1164000000 | 8 | 25000 | STATUS_NOK | 0 | 1000000 | 54000000 | 1218000000 |
| 3 | 1 | 108000000 | 1218000000 | 1110000000 | 12 | 300000 | STATUS_OK | 1 | 3600000 | 108600000 | 1217400000 |
| 4 | 0 | 108000000 | 1218000000 | 1110000000 | 12 | 300000 | STATUS_OK | 1 | 3700000 | 108000000 | 1218000000 |
| 5 | 1 | 5000000 | 1002000000 | 997000000 | 20 | 50000 | STATUS_OK | 0 | 1000000 | 5000000 | 1002000000 |
| 6 | 0 | 5000000 | 1002000000 | 997000000 | 20 | 50000 | STATUS_OK | 0 | 1000000 | 5000000 | 1002000000 |
| 7 | 1 | 300000000 | 1296000000 | 996000000 | 64 | 100000 | STATUS_OK | 1 | 6400000 | 302000000 | 1294000000 |
| 8 | 0 | 300000000 | 1296000000 | 996000000 | 64 | 100000 | STATUS_OK | 1 | 6225000 | 300000000 | 1296000000 |
| 9 | 1 | 200000000 | 1396000000 | 1196000000 | 8 | 300000 | STATUS_OK | 1 | 2400000 | 200400000 | 1395600000 |
| 10 | 0 | 200000000 | 1396000000 | 1196000000 | 8 | 300000 | STATUS_OK | 1 | 2392000 | 200000000 | 1396000000 |
| 11 | 1 | 450000000 | 1350000000 | 900000000 | 12 | 200000 | STATUS_OK | 1 | 2400000 | 450000000 | 1350000000 |
| 12 | 0 | 450000000 | 1350000000 | 900000000 | 12 | 200000 | STATUS_OK | 1 | 2400000 | 450000000 | 1350000000 |
| 13 | 1 | 258000000 | 1002000000 | 744000000 | 20 | 500000 | STATUS_OK | 1 | 10000000 | 260000000 | 1000000000 |
| 14 | 0 | 258000000 | 1002000000 | 744000000 | 20 | 500000 | STATUS_OK | 1 | 9920000 | 258000000 | 1002000000 |
| 15 | 1 | 108000000 | 1002000000 | 894000000 | 64 | 1000000 | STATUS_OK | 1 | 64000000 | 139000000 | 971000000 |
| 16 | 0 | 108000000 | 1002000000 | 894000000 | 64 | 1000000 | STATUS_NOK | 0 | 1000000 | 108000000 | 1002000000 |
| 17 | 1 | 500000000 | 692000000 | 192000000 | 8 | 300000 | STATUS_OK | 1 | 2400000 | 500000000 | 692000000 |
| 18 | 0 | 500000000 | 692000000 | 192000000 | 8 | 300000 | STATUS_OK | 1 | 2400000 | 500000000 | 692000000 |
| 19 | 1 | 510000000 | 516000000 | 6000000 | 12 | 2000000 | STATUS_NOK | 0 | 1000000 | 510000000 | 516000000 |
| 20 | 0 | 510000000 | 516000000 | 6000000 | 12 | 2000000 | STATUS_NOK | 0 | 1000000 | 510000000 | 516000000 |
| 21 | 1 | 600000000 | 606000000 | 6000000 | 20 | 300000 | STATUS_OK | 1 | 6000000 | 600000000 | 606000000 |
| 22 | 0 | 600000000 | 606000000 | 6000000 | 20 | 300000 | STATUS_OK | 1 | 6000000 | 600000000 | 606000000 |
| 23 | 1 | 750000000 | 756000000 | 6000000 | 64 | 25000 | STATUS_OK | 1 | 1600000 | 750600000 | 755400000 |
| 24 | 0 | 750000000 | 756000000 | 6000000 | 64 | 25000 | STATUS_NOK | 0 | 1000000 | 750000000 | 756000000 |
| 25 | 1 | 300000000 | 492000000 | 192000000 | 8 | 300000 | STATUS_OK | 1 | 2400000 | 300000000 | 492000000 |
| 26 | 0 | 300000000 | 492000000 | 192000000 | 8 | 300000 | STATUS_OK | 1 | 2400000 | 300000000 | 492000000 |
| 27 | 1 | 402000000 | 594000000 | 192000000 | 12 | 50000 | STATUS_NOK | 0 | 1000000 | 402000000 | 594000000 |
| 28 | 0 | 402000000 | 594000000 | 192000000 | 12 | 50000 | STATUS_NOK | 0 | 1000000 | 402000000 | 594000000 |
| 29 | 1 | 606000000 | 798000000 | 192000000 | 20 | 100000 | STATUS_OK | 1 | 2000000 | 606000000 | 798000000 |
| 30 | 0 | 606000000 | 798000000 | 192000000 | 20 | 100000 | STATUS_OK | 1 | 2000000 | 606000000 | 798000000 |
| 31 | 1 | 100000000 | 292000000 | 192000000 | 64 | 300000 | STATUS_OK | 1 | 19200000 | 100000000 | 292000000 |
| 32 | 0 | 100000000 | 292000000 | 192000000 | 64 | 300000 | STATUS_OK | 1 | 19200000 | 100000000 | 292000000 |
| 33 | 1 | 108000000 | 300000000 | 192000000 | 8 | 200000 | STATUS_OK | 1 | 1600000 | 108000000 | 300000000 |
| 34 | 0 | 108000000 | 300000000 | 192000000 | 8 | 200000 | STATUS_OK | 1 | 1600000 | 108000000 | 300000000 |
| 35 | 1 | 250000000 | 442000000 | 192000000 | 12 | 500000 | STATUS_OK | 1 | 6000000 | 250000000 | 442000000 |
| 36 | 0 | 250000000 | 442000000 | 192000000 | 12 | 500000 | STATUS_OK | 1 | 6000000 | 250000000 | 442000000 |
| 37 | 1 | 360000000 | 552000000 | 192000000 | 20 | 1000000 | STATUS_OK | 1 | 20000000 | 366000000 | 546000000 |
| 38 | 0 | 360000000 | 552000000 | 192000000 | 20 | 1000000 | STATUS_OK | 1 | 19200000 | 360000000 | 552000000 |
| 39 | 1 | 420000000 | 612000000 | 192000000 | 64 | 300000 | STATUS_OK | 1 | 19200000 | 420000000 | 612000000 |
| 40 | 0 | 420000000 | 612000000 | 192000000 | 64 | 300000 | STATUS_OK | 1 | 19200000 | 420000000 | 612000000 |
| 41 | 1 | 500000000 | 692000000 | 192000000 | 8 | 2000000 | STATUS_OK | 1 | 16000000 | 500000000 | 692000000 |
| 42 | 0 | 500000000 | 692000000 | 192000000 | 8 | 2000000 | STATUS_OK | 1 | 16000000 | 500000000 | 692000000 |
| 43 | 1 | 600000000 | 792000000 | 192000000 | 12 | 300000 | STATUS_OK | 1 | 3600000 | 600600000 | 791400000 |
| 44 | 0 | 600000000 | 792000000 | 192000000 | 12 | 300000 | STATUS_NOK | 0 | 1000000 | 600000000 | 792000000 |
| 45 | 1 | 700000000 | 892000000 | 192000000 | 20 | 25000 | STATUS_NOK | 0 | 1000000 | 700000000 | 892000000 |
| 46 | 0 | 700000000 | 892000000 | 192000000 | 20 | 25000 | STATUS_NOK | 0 | 1000000 | 700000000 | 892000000 |
| 47 | 1 | 150000000 | 342000000 | 192000000 | 64 | 300000 | STATUS_OK | 1 | 19200000 | 150000000 | 342000000 |
| 48 | 0 | 150000000 | 342000000 | 192000000 | 64 | 300000 | STATUS_OK | 1 | 19200000 | 150000000 | 342000000 |
| 49 | 1 | 210000000 | 402000000 | 192000000 | 8 | 50000 | STATUS_NOK | 0 | 1000000 | 210000000 | 402000000 |
| 50 | 0 | 210000000 | 402000000 | 192000000 | 8 | 50000 | STATUS_NOK | 0 | 1000000 | 210000000 | 402000000 |

# FILE: docs/api/fast-api/single/spectrum-analyzer/spectrum-analyzer.md
# PNM Operations - Spectrum Analyzer

Downstream Spectrum Capture And Per-Channel Analysis For DOCSIS 3.x/4.0 Cable Modems.

## Overview

[`SpectrumAnalyzerRouter`](http://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/api/routes/docs/pnm/spectrumAnalyzer/router.py)
exposes three related endpoints that drive downstream spectrum capture and analysis:

* A single spectrum capture endpoint (`/getCapture`) for free-form frequency sweeps.
* An OFDM-focused endpoint (`/getCapture/ofdm`) that walks all downstream OFDM channels.
* An SC-QAM-focused endpoint (`/getCapture/scqam`) that walks all downstream SC-QAM channels.

Each capture is processed through the common analysis pipeline and can return either a JSON
analysis payload or an archive (ZIP) with Matplotlib plots and CSV exports.

For RBW auto-scale outcomes, see the [Spectrum analyzer RBW permutations](../spectrum-analyzer.md) reference.

> The cable modem must be PNM-ready and the requested frequency range must fall within the
> configured diplexer band. Use the diplexer configuration API to verify allowed frequency
> boundaries.

### Diplexer Configuration Endpoint

| DOCSIS | Endpoint | Description |
|-------|----------|-------------|
| [DOCSIS 3.1](../general/diplexer-configuration.md)                | `POST /docs/if31/system/diplexer`              | Retrieve the diplexer for spectrum capture. |
| [DOCSIS 4.0](../fdd/fdd-system-diplexer-configuration.md) | `POST /docs/fdd/system/diplexer/configuration` | Retrieve the diplexer for spectrum capture. |

## Endpoints

All endpoints share the same base prefix: `/docs/pnm/ds`.

| Purpose                        | Method | Path                                             |
| ------------------------------ | ------ | ------------------------------------------------ |
| Single spectrum capture        | POST   | `/docs/pnm/ds/spectrumAnalyzer/getCapture`       |
| All OFDM downstream channels   | POST   | `/docs/pnm/ds/spectrumAnalyzer/getCapture/ofdm`  |
| All SC-QAM downstream channels | POST   | `/docs/pnm/ds/spectrumAnalyzer/getCapture/scqam` |

Each endpoint accepts a common cable modem block and analysis controls. Capture-specific
settings are provided under `capture_parameters`.

> Note: A modem can only run either downstream or upstream spectrum at a time. The router
> documented here is downstream (`/ds`) only.

## Common Request Shape

Refer to [Common → Request](../../common/request.md).  
These endpoints add optional `analysis` controls and a `capture_parameters` section.

### Analysis Delta Table

| JSON path                | Type   | Allowed values / format | Default | Description                                                                                               |
| ------------------------ | ------ | ----------------------- | ------- | --------------------------------------------------------------------------------------------------------- |
| `analysis.type`          | string | "basic"                 | "basic" | Selects the analysis mode used during processing.                                                         |
| `analysis.output.type`   | string | "json", "archive"       | "json"  | Output format. **`json`** returns inline `data`; **`archive`** returns a ZIP (CSV exports and PNG plots). |
| `analysis.plot.ui.theme` | string | "light", "dark"         | "dark"  | Theme hint for Matplotlib plots (colors, grid, ticks). Does not affect raw metrics/CSV.                   |
| `analysis.spectrum_analysis.moving_average.points` | int | >= 1 | 10 | Window size for the moving average applied to spectrum magnitudes. |

When `analysis.output.type = "archive"`, the HTTP response body is the file (no `data` JSON payload).

## Single Capture - `/spectrumAnalyzer/getCapture`

Single downstream spectrum capture using the modem's generic spectrum engine. This is the
most flexible entry point and allows arbitrary sweep settings (within diplexer limits).

### Single Capture Example Request

```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.10",
        "ipv6": "2001:db8::10"
      }
    },
    "snmp": {
      "snmpV2C": {
        "community": "private"
      }
    }
  },
  "analysis": {
    "type": "basic",
    "output": { "type": "json" },
    "plot": { "ui": { "theme": "dark" } },
    "spectrum_analysis": {
      "moving_average": { "points": 10 }
    }
  },
  "capture_parameters": {
    "inactivity_timeout": 60,
    "first_segment_center_freq": 300000000,
    "last_segment_center_freq": 900000000,
    "segment_freq_span": 1000000,
    "num_bins_per_segment": 256,
    "noise_bw": 150,
    "window_function": 1,
    "num_averages": 1,
    "spectrum_retrieval_type": 1
  }
}
```

### Capture Parameters

| JSON path                                      | Type | Description                                                                  |
| ---------------------------------------------- | ---- | ---------------------------------------------------------------------------- |
| `capture_parameters.inactivity_timeout`        | int  | Timeout (seconds) before aborting idle spectrum acquisition.                 |
| `capture_parameters.first_segment_center_freq` | int  | Center frequency (Hz) of the first sweep segment.                            |
| `capture_parameters.last_segment_center_freq`  | int  | Center frequency (Hz) of the last sweep segment.                             |
| `capture_parameters.segment_freq_span`         | int  | Frequency span (Hz) covered by each sweep segment.                           |
| `capture_parameters.num_bins_per_segment`      | int  | Number of FFT bins per segment.                                              |
| `capture_parameters.noise_bw`                  | int  | Equivalent noise bandwidth in kHz.                                            |
| `capture_parameters.window_function`           | int  | Window function enum value.                                                    |
| `capture_parameters.num_averages`              | int  | Number of averages per segment for noise reduction.                           |
| `capture_parameters.spectrum_retrieval_type`   | int  | Retrieval mode enum value (FILE = 1, SNMP = 2).                                 |

#### Window Function Values

| Value | Enum name |
| ----- | --------- |
| 0     | OTHER |
| 1     | HANN |
| 2     | BLACKMAN_HARRIS |
| 3     | RECTANGULAR |
| 4     | HAMMING |
| 5     | FLAT_TOP |
| 6     | GAUSSIAN |
| 7     | CHEBYSHEV |

#### Note

> `spectrum_retrieval_type` Use 1 (PNM_FILE) is preferred for most use cases. Use `2` (SNMP) when PNM file transfer is not available.

### Abbreviated JSON Response (Output Type `"json"`)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "analysis": [
      {
        "device_details": {
          "system_description": {
            "HW_REV": "1.0",
            "VENDOR": "LANCity",
            "BOOTR": "NONE",
            "SW_REV": "1.0.0",
            "MODEL": "LCPET-3"
          }
        },
        "capture_parameters": {
          "inactivity_timeout": 60,
          "first_segment_center_freq": 300000000,
          "last_segment_center_freq": 900000000,
          "segment_freq_span": 1000000,
          "num_bins_per_segment": 100,
          "noise_bw": 0,
          "window_function": 1,
          "num_averages": 1,
          "spectrum_retrieval_type": 1
        },
        "signal_analysis": {
          "bin_bandwidth": 10000,
          "segment_length": 100,
          "frequencies": [],
          "magnitudes": [],
          "window_average": {
            "points": 20,
            "magnitudes": []
          }
        }
      }
    ],
    "primative": [
      {
        "status": "SUCCESS",
        "pnm_header": {
          "file_type": "PNN",
          "file_type_version": 9,
          "major_version": 1,
          "minor_version": 0,
          "capture_time": 1762839675
        },
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "first_segment_center_frequency": 300000000,
        "last_segment_center_frequency": 900000000,
        "segment_frequency_span": 1000000,
        "num_bins_per_segment": 100,
        "equivalent_noise_bandwidth": 110.0,
        "window_function": 1,
        "bin_frequency_spacing": 10000,
        "spectrum_analysis_data_length": 120200,
        "spectrum_analysis_data": "e570e3...40e340"
      }
    ],
    "measurement_stats": [
      {
        "index": 0,
        "entry": {
          "docsIf3CmSpectrumAnalysisCtrlCmdEnable": true,
          "docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout": 60,
          "docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency": 300000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency": 900000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan": 1000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment": 100,
          "docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth": 110,
          "docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction": 1,
          "docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages": 1,
          "docsIf3CmSpectrumAnalysisCtrlCmdFileEnable": true,
          "docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus": "sample_ready",
          "docsIf3CmSpectrumAnalysisCtrlCmdFileName": "spectrum_analyzer_aabbccddeeff_0_1762839621.bin"
        }
      }
    ]
  }
}
```

### Single-Capture Return Structure

Top-level envelope:

| Field         | Type          | Description                                                               |
| ------------- | ------------- | ------------------------------------------------------------------------- |
| `mac_address` | string        | Request echo of the modem MAC.                                            |
| `status`      | int           | 0 on success, non-zero on error.                                          |
| `message`     | string\|null  | Optional message describing status.                                       |
| `data`        | object        | Container for results (`analysis`, `primative`, `measurement_stats`).     |

**Payload: `data.analysis[]`**

| Field                            | Type   | Description                                                           |
| -------------------------------- | ------ | --------------------------------------------------------------------- |
| device_details.*                 | object | System descriptor captured at analysis time.                          |
| capture_parameters.*             | object | Echo of the capture parameters effective for this run.               |
| signal_analysis.bin_bandwidth    | int    | Effective bin bandwidth (Hz) derived from bin spacing/windowing.     |
| signal_analysis.segment_length   | int    | Number of FFT bins per segment used in analysis.                     |
| signal_analysis.frequencies      | array  | Frequency axis for the analyzed spectrum (per-bin center frequency). |
| signal_analysis.magnitudes       | array  | Amplitude values aligned with `frequencies`.                         |
| signal_analysis.window_average.* | object | Optional moving-average smoothing applied to `magnitudes`.           |

**Payload: `data.primative[]`**

| Field                          | Type       | Description                                               |
| ------------------------------ | ---------- | --------------------------------------------------------- |
| status                         | string     | Result for this capture (e.g., `"SUCCESS"`).              |
| pnm_header.*                   | object     | PNM file header (type, version, capture time).            |
| mac_address                    | string     | MAC address.                                              |
| first_segment_center_frequency | int (Hz)   | Center frequency of the first sweep segment.              |
| last_segment_center_frequency  | int (Hz)   | Center frequency of the last sweep segment.               |
| segment_frequency_span         | int (Hz)   | Frequency span covered by each segment.                   |
| num_bins_per_segment           | int        | Number of FFT bins per segment.                           |
| equivalent_noise_bandwidth     | float (Hz) | Equivalent noise bandwidth used for amplitude scaling.    |
| window_function                | int        | Window function index.                                    |
| bin_frequency_spacing          | float (Hz) | Frequency spacing between adjacent bins.                  |
| spectrum_analysis_data_length  | int        | Byte length of `spectrum_analysis_data`.                  |
| spectrum_analysis_data         | string     | Raw spectrum data encoded as hexadecimal text.            |

**Payload: `data.measurement_stats[]`**

| Field                                                     | Type    | Description                                              |
| --------------------------------------------------------- | ------- | -------------------------------------------------------- |
| index                                                               | int     | SNMP table row index.                                    |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdEnable                        | boolean | Whether capture was enabled for this measurement.        |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout             | int     | Inactivity timeout (seconds) used for the capture.       |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency   | int (Hz) | First segment center frequency at capture time.  |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency    | int (Hz) | Last segment center frequency at capture time.   |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan          | int (Hz) | Segment frequency span in Hz.                   |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment             | int     | Number of bins per segment.                      |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth      | int     | Equivalent noise bandwidth in Hz.                |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction                | int     | Window function index.                           |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages              | int     | Number of averages used for this capture.        |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdFileEnable                    | boolean | Whether capture-to-file was enabled.             |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus                    | string  | Measurement status (e.g., `"sample_ready"`).     |
| entry.docsIf3CmSpectrumAnalysisCtrlCmdFileName                      | string  | Device-side filename of the captured spectrum.   |

## OFDM Downstream Capture - `/spectrumAnalyzer/getCapture/ofdm`

This endpoint iterates across all downstream OFDM channels on the modem, performing a
spectrum capture per channel and aggregating the results into a multi-analysis structure.

Each per-channel capture is processed like the single capture. Results are returned as:

* `data.analyses[]` - list of per-channel analysis views (one entry per capture).
* `data.primative` - dictionary of raw capture payloads indexed by channel position.
* `data.measurement_stats[]` - flattened SNMP spectrum-analysis entries.

DOCSIS constraints:

* DOCSIS 3.1: up to **2** downstream OFDM channels.  
* DOCSIS 4.0 FDD/FDX: up to **5** downstream OFDM channels.

### OFDM Capture Example Request

```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.10",
        "ipv6": "2001:db8::10"
      }
    },
    "snmp": {
      "snmpV2C": {
        "community": "private"
      }
    }
  },
  "analysis": {
    "type": "basic",
    "output": { "type": "json" },
    "plot": { "ui": { "theme": "dark" } },
    "spectrum_analysis": {
      "moving_average": { "points": 10 }
    }
  },
  "capture_parameters": {
    "number_of_averages": 10
  }
}
```

### Abbreviated JSON Response (OFDM View)

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "analyses": [
      {
        "device_details": {
          "system_description": {
            "HW_REV": "1.0",
            "VENDOR": "LANCity",
            "BOOTR": "NONE",
            "SW_REV": "1.0.0",
            "MODEL": "LCPET-3"
          }
        },
        "capture_parameters": {
          "inactivity_timeout": 60,
          "first_segment_center_freq": 739000000,
          "last_segment_center_freq": 833000000,
          "segment_freq_span": 1000000,
          "num_bins_per_segment": 100,
          "noise_bw": 0,
          "window_function": 1,
          "num_averages": 1,
          "spectrum_retrieval_type": 1
        },
        "signal_analysis": {
          "bin_bandwidth": 10000,
          "segment_length": 100,
          "frequencies": [],
          "magnitudes": [],
          "window_average": {
            "points": 10,
            "magnitudes": []
          }
        }
      }
    ],
    "primative": {
      "0": [
        {
          "status": "SUCCESS",
          "pnm_header": {
            "file_type": "PNN",
            "file_type_version": 9,
            "major_version": 1,
            "minor_version": 0,
            "capture_time": 1762840213
          },
          "channel_id": 0,
          "mac_address": "aa:bb:cc:dd:ee:ff",
          "first_segment_center_frequency": 739000000,
          "last_segment_center_frequency": 833000000,
          "segment_frequency_span": 1000000,
          "num_bins_per_segment": 100,
          "equivalent_noise_bandwidth": 110.0,
          "window_function": 1,
          "bin_frequency_spacing": 10000,
          "spectrum_analysis_data_length": 19000,
          "spectrum_analysis_data": "",
          "amplitude_bin_segments_float": []
        }
      ],
      "1": []
    },
    "measurement_stats": [
      {
        "index": 0,
        "entry": {
          "docsIf3CmSpectrumAnalysisCtrlCmdEnable": true,
          "docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout": 30,
          "docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency": 739000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency": 833000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan": 1000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment": 100,
          "docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth": 110,
          "docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction": 1,
          "docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages": 2,
          "docsIf3CmSpectrumAnalysisCtrlCmdFileEnable": true,
          "docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus": "sample_ready",
          "docsIf3CmSpectrumAnalysisCtrlCmdFileName": "spectrum_analyzer_aabbccddeeff_0_1762840189.bin"
        }
      },
      {
        "index": 0,
        "entry": {
          "docsIf3CmSpectrumAnalysisCtrlCmdEnable": true,
          "docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout": 30,
          "docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency": 619000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency": 737000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan": 1000000,
          "docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment": 100,
          "docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth": 110,
          "docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction": 1,
          "docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages": 2,
          "docsIf3CmSpectrumAnalysisCtrlCmdFileEnable": true,
          "docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus": "sample_ready",
          "docsIf3CmSpectrumAnalysisCtrlCmdFileName": "spectrum_analyzer_aabbccddeeff_0_1762840227.bin"
        }
      }
    ]
  }
}
```

### OFDM Multi-Channel Return Structure

**Payload: `data.analyses[]` (OFDM)**

| Field                          | Type   | Description                                                          |
| ------------------------------ | ------ | -------------------------------------------------------------------- |
| `[index]`.device_details.*     | object | System descriptor captured at analysis time for that channel.        |
| `[index]`.capture_parameters.* | object | Effective capture parameters for that OFDM channel.                  |
| `[index]`.signal_analysis.*    | object | Per-channel spectrum analysis (frequencies, magnitudes, smoothing).  |

**Payload: `data.primative` (OFDM)**

| Field           | Type  | Description                                                             |
| --------------- | ----- | ----------------------------------------------------------------------- |
| `"0"`, `"1"`, … | array | Raw per-channel capture payloads for each OFDM channel position.       |

**Payload: `data.measurement_stats[]` (OFDM)**

Reuses the single-capture `measurement_stats` field definitions, repeated per OFDM channel.

## SC-QAM Downstream Capture - `/spectrumAnalyzer/getCapture/scqam`

This endpoint iterates across all downstream SC-QAM channels, performing spectrum captures
per channel and aggregating the results into a multi-analysis view similar to the OFDM
endpoint.

DOCSIS constraints:

* DOCSIS 3.1 and DOCSIS 4.0 support up to **32** downstream SC-QAM channels (implementation-dependent).

The response shape for SC-QAM captures mirrors the OFDM multi-channel layout:

* `data.analyses[]` - list of per-channel analysis views.
* `data.primative` - dictionary of raw capture payloads indexed by channel position.
* `data.measurement_stats[]` - flattened SNMP statistics per captured channel.

### Example Request

```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.0.100",
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.0.10",
        "ipv6": "2001:db8::10"
      }
    },
    "snmp": {
      "snmpV2C": {
        "community": "private"
      }
    }
  },
  "analysis": {
    "type": "basic",
    "output": { "type": "json" },
    "plot": { "ui": { "theme": "dark" } },
    "spectrum_analysis": {
      "moving_average": { "points": 10 }
    }
  },
  "capture_parameters": {
    "number_of_averages": 10
  }
}
```

### SC-QAM Multi-Channel Return Structure

**Payload: `data.analyses[]` (SC-QAM)**

Same as OFDM: each list element represents a per-channel analysis view with
`device_details`, `capture_parameters`, and `signal_analysis`.

**Payload: `data.primative` (SC-QAM)**

| Field           | Type  | Description                                                             |
| --------------- | ----- | ----------------------------------------------------------------------- |
| `"0"`, `"1"`, … | array | Raw per-channel capture payloads for each SC-QAM channel position.     |

**Payload: `data.measurement_stats[]` (SC-QAM)**

Reuses the single-capture `measurement_stats` field definitions, per SC-QAM channel.

## Archive Output

For all three endpoints, when `analysis.output.type = "archive"`:

* The response body is a ZIP file (no JSON `data` envelope).
* Contents typically include:
  * CSV exports of amplitude vs frequency.
  * Matplotlib PNG plots per channel and aggregate views.

Examples of generated plots:

| Standard Plot  | Moving Average Plot  | Description |
| -------------- | -------------------- | ----------- |
| [DS Full Bandwidth](../images/spectrum/spec-analysis-standard.png) | [DS Full Bandwidth](../images/spectrum/spec-analysis-moving-average.png)    | Single-capture standard vs moving-average spectrum views.       |
| [SCQAM](../images/spectrum/scqam-2-spec-analysis-standard.png)     | [SCQAM](../images/spectrum/scqam-2-spec-analysis-moving-average.png)        | Example SC-QAM channel standard and moving-average plots.       |
| [OFDM](../images/spectrum/ofdm-34-spec-analysis-standard.png)      | [OFDM](../images/spectrum/ofdm-34-spec-analysis-moving-average.png)         | Example OFDM channel standard and moving-average plots.         |

## Notes

* Always validate requested frequency ranges against the modem diplexer configuration.  
* Spectrum captures can be long-running operations depending on span and averaging.  

# FILE: docs/docker/install.md
# PyPNM Docker Install & Usage

PyPNM ships with Docker assets so you can run the API quickly on a workstation, lab host, or VM. This guide covers the common flows:

- Install the published release image via the helper script.
- Use the deploy bundle (tarball) directly.
- Manual steps for hosts without GitHub access.

## Table of Contents

- [Fast path (helper script)](#fast-path-pypnm-docker-container-install)
- [Deploy bundle flow (tarball)](#deploy-bundle-flow-tarball)
- [Manual/no-network notes](#manualno-network-notes)

## Fast path: PyPNM Docker container install

```bash
TAG="v1.0.36.0"
PORT=8080

curl -fsSLo install-pypnm-docker-container.sh \
  https://raw.githubusercontent.com/PyPNMApps/PyPNM/main/scripts/install-pypnm-docker-container.sh

chmod +x install-pypnm-docker-container.sh

sudo ./install-pypnm-docker-container.sh --tag ${TAG} --port ${PORT}
```

What the script does:

- Downloads the deploy bundle (falls back to tag source if the asset is missing).
- Seeds `deploy/docker/config/system.json` and `deploy/docker/compose/.env`.
- Pulls `ghcr.io/PyPNMApps/pypnm:${TAG}` and starts the stack in `/opt/pypnm/compose`.
- Prints next steps (logs, reload docs, config-menu).

After install (from `/opt/pypnm/compose`):

```bash
sudo docker compose logs -f --tail=200 pypnm-api
curl -I http://127.0.0.1:${PORT}/docs
sudo docker compose run --rm config-menu

# Reload after config changes, this assumes IP/PORT is set as above:
curl -X GET http://127.0.0.1:${PORT}/pypnm/system/webService/reload -H 'accept: application/json'
```

## Deploy bundle flow (tarball)

```bash
TAG="v1.0.36.0"
WORKING_DIR="PyPNM-${TAG}"

mkdir -p "${WORKING_DIR}"
cd "${WORKING_DIR}"

wget "https://github.com/PyPNMApps/PyPNM/archive/refs/tags/${TAG}.tar.gz"
tar -xvf "${TAG}.tar.gz" --strip-components=1

cd deploy/docker
./install.sh

cd compose
sudo docker compose pull
sudo docker compose up -d
```

Edit `deploy/docker/config/system.json` as needed, then reload the service (curl or `sudo docker compose restart pypnm-api`).

## Manual/no-network notes

- If the host cannot reach GitHub, copy the `deploy/docker/` folder from a clone or a downloaded tarball and run `deploy/docker/install.sh`.
- The helper script falls back to the tag archive and then to `main` if the deploy asset is missing.
- The runtime config lives in `deploy/docker/config/system.json`; config-menu and the API share this file.

Need Docker itself first? See [Install Docker prerequisites](install-docker.md).

# FILE: docs/gallery/index.md
# PyPNM Gallery

Quick visual tour of every PNG asset that ships with PyPNM. Use this gallery when you need to spot a component at a glance or grab an image for presentations.

## [Multi-capture channel estimation](../api/fast-api/multi/multi-capture-chan-est.md)

| Image | Description |
| --- | --- |
| ![193 group delay](../api/fast-api/multi/images/multi-chan-est/193_chan_est_group_delay.png) | Group-delay curve for capture 193 showing upstream reflections. |
| ![194 group delay](../api/fast-api/multi/images/multi-chan-est/194_chan_est_group_delay.png) | Group-delay analysis for capture 194. |
| ![195 group delay](../api/fast-api/multi/images/multi-chan-est/195_chan_est_group_delay.png) | Group-delay profile for capture 195. |
| ![196 group delay](../api/fast-api/multi/images/multi-chan-est/196_chan_est_group_delay.png) | Group-delay profile for capture 196. |
| ![197 group delay](../api/fast-api/multi/images/multi-chan-est/197_chan_est_group_delay.png) | Group-delay profile for capture 197. |
| ![193 min avg max](../api/fast-api/multi/images/multi-chan-est/193_chan_est_min_avg_max.png) | Minimum/average/maximum tap summary for capture 193. |
| ![194 min avg max](../api/fast-api/multi/images/multi-chan-est/194_chan_est_min_avg_max.png) | Minimum/average/maximum tap summary for capture 194. |
| ![195 min avg max](../api/fast-api/multi/images/multi-chan-est/195_chan_est_min_avg_max.png) | Minimum/average/maximum tap summary for capture 195. |
| ![196 min avg max](../api/fast-api/multi/images/multi-chan-est/196_chan_est_min_avg_max.png) | Minimum/average/maximum tap summary for capture 196. |
| ![197 min avg max](../api/fast-api/multi/images/multi-chan-est/197_chan_est_min_avg_max.png) | Minimum/average/maximum tap summary for capture 197. |
| ![193 echo ifft](../api/fast-api/multi/images/multi-chan-est/193_chan_est_echo_ifft.png) | Echo impulse response (IFFT) for capture 193. |
| ![194 echo ifft](../api/fast-api/multi/images/multi-chan-est/194_chan_est_echo_ifft.png) | Echo impulse response (IFFT) for capture 194. |
| ![195 echo ifft](../api/fast-api/multi/images/multi-chan-est/195_chan_est_echo_ifft.png) | Echo impulse response (IFFT) for capture 195. |
| ![196 echo ifft](../api/fast-api/multi/images/multi-chan-est/196_chan_est_echo_ifft.png) | Echo impulse response (IFFT) for capture 196. |
| ![197 echo ifft](../api/fast-api/multi/images/multi-chan-est/197_chan_est_echo_ifft.png) | Echo impulse response (IFFT) for capture 197. |

## [Multi-capture RxMER dashboards](../api/fast-api/multi/multi-capture-rxmer.md)

| Image | Description |
| --- | --- |
| ![Profile 0 performance](../api/fast-api/multi/images/multi-rxmer/160_profile_0_ofdm_profile_perf_1.png) | OFDM profile performance summary for profile 0. |
| ![Profile 1 performance](../api/fast-api/multi/images/multi-rxmer/160_profile_1_ofdm_profile_perf_1.png) | OFDM profile performance summary for profile 1. |
| ![Profile 2 performance](../api/fast-api/multi/images/multi-rxmer/160_profile_2_ofdm_profile_perf_1.png) | OFDM profile performance summary for profile 2. |
| ![Profile 3 performance](../api/fast-api/multi/images/multi-rxmer/160_profile_3_ofdm_profile_perf_1.png) | OFDM profile performance summary for profile 3. |
| ![RxMER heatmap](../api/fast-api/multi/images/multi-rxmer/160_rxmer_heat_map.png) | Multi-modem RxMER heatmap across active subcarriers. |
| ![RxMER stats](../api/fast-api/multi/images/multi-rxmer/160_rxmer_min_avg_max.png) | Minimum/average/maximum RxMER overlay for the same capture set. |

## [Spectrum analysis](../api/fast-api/single/index.md)

| Image | Description |
| --- | --- |
| ![SC-QAM standard](../api/fast-api/single/images/spectrum/scqam-2-spec-analysis-standard.png) | Standard SC-QAM spectrum overlay. |
| ![SC-QAM moving average](../api/fast-api/single/images/spectrum/scqam-2-spec-analysis-moving-average.png) | Moving-average view of the same SC-QAM capture. |
| ![OFDM standard](../api/fast-api/single/images/spectrum/ofdm-34-spec-analysis-standard.png) | Standard OFDM-34 spectrum plot. |
| ![OFDM moving average](../api/fast-api/single/images/spectrum/ofdm-34-spec-analysis-moving-average.png) | Moving-average OFDM-34 spectrum plot. |
| ![General standard](../api/fast-api/single/images/spectrum/spec-analysis-standard.png) | Generic spectrum analysis template (standard weighting). |
| ![General moving average](../api/fast-api/single/images/spectrum/spec-analysis-moving-average.png) | Generic spectrum analysis template (moving average). |

## [Downstream DS histogram](../api/fast-api/single/ds/histogram.md)

| Image | Description |
| --- | --- |
| ![DS histogram](../api/fast-api/single/ds/images/histogram/ds-histogram.png) | Downstream histogram with modulation bins and counts. |

## [Upstream OFDMA pre-equalization](../api/fast-api/single/us/ofdma/pre-equalization.md)

| Image | Description |
| --- | --- |
| ![Magnitude view](../api/fast-api/single/us/ofdma/images/pre-eq/42_us_preeq_magnitude.png) | Upstream OFDMA pre-EQ magnitude trace for capture 42. |
| ![IQ scatter](../api/fast-api/single/us/ofdma/images/pre-eq/42_us_preeq_iqscatter.png) | Upstream OFDMA pre-EQ IQ scatter plot for capture 42. |
| ![IFFT taps](../api/fast-api/single/us/ofdma/images/pre-eq/42_us_preeq_ifft.png) | Upstream OFDMA pre-EQ impulse response (IFFT) for capture 42. |
| ![Group delay](../api/fast-api/single/us/ofdma/images/pre-eq/42_us_preeq_groupdelay.png) | Upstream OFDMA pre-EQ group delay for capture 42. |

## [OFDM modulation profiles](../api/fast-api/single/ds/ofdm/modulation-profile.md)

| Image | Description |
| --- | --- |
| ![Profile 0 BPS](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-0-bps-modulation-profile.png) | Profile 0 bits-per-symbol modulation assignment. |
| ![Profile 0 MQAM](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-0-mqam-modulation-profile.png) | Profile 0 MQAM breakdown. |
| ![Profile 0 Shannon](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-0-shannon-mer-modulation-profile.png) | Profile 0 Shannon MER estimate. |
| ![Profile 1 BPS](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-1-bps-modulation-profile.png) | Profile 1 bits-per-symbol modulation assignment. |
| ![Profile 1 MQAM](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-1-mqam-modulation-profile.png) | Profile 1 MQAM breakdown. |
| ![Profile 1 Shannon](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-1-shannon-mer-modulation-profile.png) | Profile 1 Shannon MER estimate. |
| ![Profile 2 BPS](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-2-bps-modulation-profile.png) | Profile 2 bits-per-symbol modulation assignment. |
| ![Profile 2 MQAM](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-2-mqam-modulation-profile.png) | Profile 2 MQAM breakdown. |
| ![Profile 2 Shannon](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-2-shannon-mer-modulation-profile.png) | Profile 2 Shannon MER estimate. |
| ![Profile 3 BPS](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-3-bps-modulation-profile.png) | Profile 3 bits-per-symbol modulation assignment. |
| ![Profile 3 MQAM](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-3-mqam-modulation-profile.png) | Profile 3 MQAM breakdown. |
| ![Profile 3 Shannon](../api/fast-api/single/ds/ofdm/images/modulation-profile/profile-3-shannon-mer-modulation-profile.png) | Profile 3 Shannon MER estimate. |

## [Constellation snapshots](../api/fast-api/single/ds/ofdm/constellation-display.md)

| Image | Description |
| --- | --- |
| ![16-QAM constellation](../api/fast-api/single/ds/ofdm/images/constellation/16qam-constellation.png) | Classic 16-QAM constellation display. |
| ![256-QAM constellation](../api/fast-api/single/ds/ofdm/images/constellation/256qam-constellation.png) | 256-QAM constellation view. |
| ![1k-QAM constellation](../api/fast-api/single/ds/ofdm/images/constellation/1kqam-constellation.png) | 1024-QAM constellation view. |
| ![2k-QAM constellation](../api/fast-api/single/ds/ofdm/images/constellation/2kqam-constellation.png) | 2048-QAM constellation view. |
| ![4k-QAM constellation](../api/fast-api/single/ds/ofdm/images/constellation/4kqam-constellation.png) | 4096-QAM constellation view. |

## [RxMER overlays & modulation counts](../api/fast-api/single/ds/ofdm/rxmer.md)

| Image | Description |
| --- | --- |
| ![Light 193 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/light_193_rxmer.png) | Light-themed RxMER plot for modem 193. |
| ![Light 194 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/light_194_rxmer.png) | Light-themed RxMER plot for modem 194. |
| ![Light 195 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/light_195_rxmer.png) | Light-themed RxMER plot for modem 195. |
| ![Light 196 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/light_196_rxmer.png) | Light-themed RxMER plot for modem 196. |
| ![Light 197 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/light_197_rxmer.png) | Light-themed RxMER plot for modem 197. |
| ![Light signal aggregate](../api/fast-api/single/ds/ofdm/images/rxmer/light_signal_aggregate.png) | Aggregate RxMER overlay (light theme). |
| ![Light 193 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/light_193_modulation_count.png) | Active subcarrier modulation counts for modem 193 (light). |
| ![Light 194 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/light_194_modulation_count.png) | Active subcarrier modulation counts for modem 194 (light). |
| ![Light 195 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/light_195_modulation_count.png) | Active subcarrier modulation counts for modem 195 (light). |
| ![Light 196 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/light_196_modulation_count.png) | Active subcarrier modulation counts for modem 196 (light). |
| ![Light 197 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/light_197_modulation_count.png) | Active subcarrier modulation counts for modem 197 (light). |
| ![Dark 193 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/dark_1761343516_193_rxmer.png) | Dark-themed RxMER overlay for modem 193 (capture hash 1761343516). |
| ![Dark 194 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/dark_1761343516_194_rxmer.png) | Dark-themed RxMER overlay for modem 194. |
| ![Dark 195 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/dark_195_rxmer.png) | Dark-themed RxMER overlay for modem 195. |
| ![Dark 196 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/dark_196_rxmer.png) | Dark-themed RxMER overlay for modem 196. |
| ![Dark 197 RxMER](../api/fast-api/single/ds/ofdm/images/rxmer/dark_197_rxmer.png) | Dark-themed RxMER overlay for modem 197. |
| ![Dark signal aggregate](../api/fast-api/single/ds/ofdm/images/rxmer/dark_1761343516_signal_aggregate.png) | Aggregate RxMER overlay (dark theme). |
| ![Dark 193 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/dark_1761343516_193_modulation_count.png) | Modulation counts for modem 193 (dark). |
| ![Dark 194 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/dark_194_modulation_count.png) | Modulation counts for modem 194 (dark). |
| ![Dark 195 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/dark_195_modulation_count.png) | Modulation counts for modem 195 (dark). |
| ![Dark 196 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/dark_196_modulation_count.png) | Modulation counts for modem 196 (dark). |
| ![Dark 197 modulation count](../api/fast-api/single/ds/ofdm/images/rxmer/dark_1761343516_197_modulation_count.png) | Modulation counts for modem 197 (dark). |

# FILE: docs/system/system-config.md
# System Configuration Reference

Canonical Structure And Field Semantics For `system.json`.

* **Config file**: [`src/pypnm/settings/system.json`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/settings/system.json)
* **ConfigManager class**: [`src/pypnm/config/config_manager.py`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/config/config_manager.py)
* **PnmConfigManager class**: [`src/pypnm/config/pnm_config_manager.py`](https://github.com/PyPNMApps/PyPNM/blob/main/src/pypnm/config/pnm_config_manager.py)

## Table Of Contents

* [1. FastApiRequestDefault](#1-fastapirequestdefault)
* [2. SNMP](#2-snmp)
* [3. PnmBulkDataTransfer](#3-pnmbulkdatatransfer)
* [4. PnmFileRetrieval](#pnmfileretrieval)
* [5. Logging](#5-logging)
* [6. TestMode](#6-testmode)
* [Loading Configuration](#loading-configuration)

## 1. FastApiRequestDefault

Default Parameters For REST Requests To The FastAPI Service.

```json
"FastApiRequestDefault": {
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "ip_address": "192.168.0.100"
}
```

| Field       | Type   | Description                       |
| ----------- | ------ | --------------------------------- |
| mac_address | string | Default device MAC address.       |
| ip_address  | string | Default device IP (IPv4 or IPv6). |

## 2. SNMP

Global SNMP Settings, Including Version-Specific Options.

```json
"SNMP": {
  "timeout": 2,
  "version": {
    "2c": {
      "enable": true,
      "retries": 3,
      "read_community": "public",
      "write_community": "private"
    },
    "3": {
      "enable": false,
      "retries": 3,
      "username": "user",
      "securityLevel": "authPriv",
      "authProtocol": "SHA",
      "authPassword": "pass",
      "privProtocol": "AES",
      "privPassword": "privpass"
    }
  }
}
```

**Top-Level**

| Field   | Type   | Description                                  |
| ------- | ------ | -------------------------------------------- |
| timeout | number | Per-request timeout (seconds).               |
| version | object | Container for v2c/v3 configuration versions. |

**SNMP v2c**

| Field           | Type    | Description                     |
| --------------- | ------- | ------------------------------- |
| enable          | boolean | Enable v2c operations.          |
| retries         | number  | Retry count on timeout/failure. |
| read_community  | string  | Community for GET/WALK.         |
| write_community | string  | Community for SET.              |

**SNMP v3**

| Field         | Type    | Description                                  |
| ------------- | ------- | -------------------------------------------- |
| enable        | boolean | Enable v3 operations.                        |
| retries       | number  | Retry count on timeout/failure.              |
| username      | string  | Security name.                               |
| securityLevel | string  | `noAuthNoPriv`, `authNoPriv`, or `authPriv`. |
| authProtocol  | string  | For example `MD5`, `SHA`.                    |
| authPassword  | string  | Required when `auth*` is used.               |
| privProtocol  | string  | For example `DES`, `AES`.                    |
| privPassword  | string  | Required when `*Priv` is used.               |

## 3. PnmBulkDataTransfer

Transport Parameters For CM-Generated Files (for example, RxMER, FEC Summary) Sent To A Server.

```json
"PnmBulkDataTransfer": {
  "method": "tftp",
  "tftp": {
    "ip_v4": "192.168.0.10",
    "ip_v6": "::1",
    "remote_dir": ""
  },
  "http": {
    "base_url": "http://files.example.com/",
    "port": 80
  },
  "https": {
    "base_url": "https://files.example.com/",
    "port": 443
  }
}
```

| Field   | Type   | Description                                                |
| ------- | ------ | ---------------------------------------------------------- |
| method  | string | Preferred bulk method: `tftp`, `http`, or `https`.         |
| tftp.*  | object | TFTP targets for IPv4/IPv6 plus optional remote directory. |
| http.*  | object | HTTP base URL and port for file delivery.                  |
| https.* | object | HTTPS base URL and port for file delivery.                 |

## 4. PnmFileRetrieval {#pnmfileretrieval}

Local Storage Layout And Remote Retrieval Methods.

Related Guide: [File Transfer Methods](pnm-file-retrieval/index.md)

```json
"PnmFileRetrieval": {
  "pnm_dir": ".data/pnm",
  "csv_dir": ".data/csv",
  "json_dir": ".data/json",
  "xlsx_dir": ".data/xlsx",
  "png_dir": ".data/png",
  "archive_dir": ".data/archive",
  "msg_rsp_dir": ".data/msg_rsp",
  "transaction_db": ".data/db/transactions.json",
  "capture_group_db": ".data/db/capture_group.json",
  "session_group_db": ".data/db/session_group.json",
  "operation_db": ".data/db/operation_capture.json",
  "json_transaction_db": ".data/db/json_transactions.json",
  "retries": 5,
  "retrieval_method": {
    "method": "local",
    "methods": {
      "local": {
        "src_dir": "/srv/tftp"
      },
      "tftp": {
        "host": "localhost",
        "port": 69,
        "timeout": 5,
        "remote_dir": ""
      },
      "ftp": {
        "host": "localhost",
        "port": 21,
        "tls": false,
        "timeout": 5,
        "user": "user",
        "password_enc": "",
        "remote_dir": "/srv/tftp"
      },
      "sftp": {
        "host": "localhost",
        "port": 22,
        "user": "user",
        "password_enc": "",
        "private_key_path": "",
        "remote_dir": "/srv/tftp"
      },
      "http": {
        "base_url": "http://STUB/",
        "port": 80
      },
      "https": {
        "base_url": "https://STUB/",
        "port": 443
      }
    }
  }
}
```

`password_enc` is the only supported password field for file retrieval methods. Plaintext `password` is not supported.

**Directories And Databases**

| Field               | Type   | Description                                  |
| ------------------- | ------ | -------------------------------------------- |
| pnm_dir             | string | Local storage for raw PNM binaries.          |
| csv_dir             | string | Local storage for derived CSVs.              |
| json_dir            | string | Local storage for derived JSON.              |
| xlsx_dir            | string | Local storage for Excel reports.             |
| png_dir             | string | Local storage for generated PNGs.            |
| archive_dir         | string | Local storage for analysis ZIP archives.     |
| msg_rsp_dir         | string | Local storage for message/response metadata. |
| transaction_db      | string | JSON ledger of file transactions.            |
| capture_group_db    | string | JSON map of grouped transactions.            |
| session_group_db    | string | JSON map of session groups.                  |
| operation_db        | string | JSON map of operation to capture group.      |
| json_transaction_db | string | JSON map of JSON transaction metadata.       |

**Retrieval Settings**

| Field                                  | Type   | Description                                                           |
| -------------------------------------- | ------ | --------------------------------------------------------------------- |
| retrieval_method.method                 | string | Active retrieval method: `local`, `tftp`, `ftp`, `sftp`, `http`, `https`. |
| retrieval_method.methods.local.src_dir  | string | Source directory to watch/copy from when using `local`.               |
| retrieval_method.methods.tftp.*         | object | TFTP host/port/timeout and remote directory.                          |
| retrieval_method.methods.ftp.*          | object | FTP connection, credentials, and remote directory.                    |
| retrieval_method.methods.sftp.*         | object | SFTP connection and remote directory.                                 |
| retrieval_method.methods.http.*         | object | HTTP base URL and port.                                               |
| retrieval_method.methods.https.*        | object | HTTPS base URL and port.                                              |
| retries                                | number | Max attempts per retrieval operation.                                 |

> The legacy key name `retrival_method` is accepted for backward compatibility.

## 5. Logging

Application Logging Options.

```json
"logging": {
  "log_level": "INFO",
  "log_dir": "logs",
  "log_filename": "pypnm.log"
}
```

| Field        | Type   | Description                                 |
| ------------ | ------ | ------------------------------------------- |
| log_level    | string | `DEBUG`, `INFO`, `WARN`, or `ERROR`.        |
| log_dir      | string | Directory for log files.                    |
| log_filename | string | Log filename (created under `log_dir`).     |

## 6. TestMode

Global And Class-Specific Test-Mode Controls.

```json
"TestMode": {
  "global": {
    "mode": {
      "enable": true
    }
  },
  "class_name": {
    "DsScQamChannelSpectrumAnalyzer": {
      "mode": {
        "enable": true
      }
    }
  }
}
```

| Field                          | Type    | Description                                            |
| ------------------------------ | ------- | ------------------------------------------------------ |
| global.mode.enable             | boolean | Enable or disable global test mode.                    |
| class_name.<Class>.mode.enable | boolean | Per-class override for test mode, keyed by class name. |

## Loading Configuration

Typical Access Pattern Using The Manager Abstractions.

```python
from pypnm.config.config_manager import ConfigManager
from pypnm.config.pnm_config_manager import PnmConfigManager

cfg = ConfigManager()

mac = cfg.get("FastApiRequestDefault", "mac_address")
ip  = cfg.get("FastApiRequestDefault", "ip_address")

pnm_cfg = PnmConfigManager()
tftp_v4 = pnm_cfg.get("PnmBulkDataTransfer", "tftp")["ip_v4"]
```

# FILE: mkdocs.yml
site_name: PyPNM Docs
site_url: https://pypnm.io/
repo_url: https://github.com/PyPNMApps/PyPNM
repo_name: PyPNMApps/PyPNM
edit_uri: edit/main/docs/

dev_addr: 127.0.0.1:8001

theme:
  name: material
  icon:
    repo: fontawesome/brands/github
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
      toggle:
        icon: material/weather-night
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: indigo
      toggle:
        icon: material/weather-sunny
        name: Switch to light mode
  features:
    - navigation.tabs
    - navigation.sections
    - content.code.copy

plugins:
  - search

markdown_extensions:
  - attr_list
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.arithmatex:
      generic: true
  - toc:
      permalink: true

extra_javascript:
  - js/mathjax-config.js
  - https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js

nav:
  - Home: index.md
  - API:
      - Overview: api/index.md
      - FastAPI:
          - Overview: api/fast-api/index.md
          - Common:
              - Requests: api/fast-api/common/request.md
              - Responses: api/fast-api/common/response.md
          - Single Capture: api/fast-api/single/index.md
          - Multi Capture: api/fast-api/multi/index.md
          - Status Codes: api/fast-api/status/fast-api-status-codes.md
      - Python: api/python/index.md
  - Examples:
      - Index: examples/index.md
  - Tools:
      - MIB compiler: tools/pypnm-mib-compiler.md
      - Clean: tools/pypnm-clean.md
  - Docker:
    - Install: docker/install.md
    - Commands: docker/commands.md
    - Install Docker prerequisites: docker/install-docker.md
  - Kubernetes:
    - kind install: kubernetes/kind-install.md
    - Quickstart: kubernetes/quickstart.md
    - PyPNM deploy: kubernetes/pypnm-deploy.md
    - kind + FreeLens (VM): kubernetes/kind-freelens.md
    - Single namespace (10 replicas): kubernetes/scale-replicas-kind.md
    - 10 namespaces (multi-port): kubernetes/ten-instances-kind.md
    - Multiple kind clusters: kubernetes/multi-cluster-kind.md
    - Commands: kubernetes/commands.md
    - Pros and cons: kubernetes/pros-cons.md
  - Gallery: gallery/index.md
  - Tests:
      - Index: tests/index.md

# FILE: src/pypnm/lib/constants.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025

from __future__ import annotations

from typing import Final, Literal, TypeAlias, TypeVar, cast

from pypnm.lib.types import (
    STATUS,
    CaptureTime,
    ChannelId,
    FloatEnum,
    FrequencyHz,
    Number,
    ProfileId,
    StringEnum,
)

DEFAULT_SSH_PORT: int   = 22

HZ:  Final[int] = 1
KHZ: Final[int] = 1_000
MHZ: Final[int] = 1_000_000
GHZ: Final[int] = 1_000_000_000

FEET_PER_METER: Final[float] = 3.280839895013123
SPEED_OF_LIGHT: Final[float] = 299_792_458.0  # m/s

NULL_ARRAY_NUMBER: Final[list[Number]] = [0]

ZERO_FREQUENCY: Final[FrequencyHz]                  = cast(FrequencyHz, 0)

INVALID_CHANNEL_ID: Final[ChannelId]                = cast(ChannelId, -1)
INVALID_PROFILE_ID: Final[ProfileId]                = cast(ProfileId, -1)
INVALID_SUB_CARRIER_ZERO_FREQ: Final[FrequencyHz]   = cast(FrequencyHz, 0)
INVALID_START_VALUE: Final[int]                     = -1
INVALID_SCHEMA_TYPE: Final[int]                     = -1
INVALID_CAPTURE_TIME: Final[CaptureTime]            = cast(CaptureTime, -1)

DEFAULT_CAPTURE_TIME: Final[CaptureTime]            = cast(CaptureTime, 19700101)  # epoch start

CableTypes: TypeAlias = Literal["RG6", "RG59", "RG11"]

# Velocity Factor (VF) by cable type (fraction of c0)
CABLE_VF: Final[dict[CableTypes, float]] = {
    "RG6":  0.87,
    "RG59": 0.82,
    "RG11": 0.87,
}

class CableType(FloatEnum):
    RG6  = 0.87
    RG59 = 0.82
    RG11 = 0.87

class MediaType(StringEnum):
    """
    Canonical Media Type Enumeration Used For File And HTTP Responses.

    Values
    ------
    APPLICATION_JSON
        JSON payloads (FastAPI JSONResponse, .json files).
    APPLICATION_ZIP
        ZIP archives (analysis bundles, multi-file exports).
    APPLICATION_OCTET_STREAM
        Raw binary streams (PNM files, generic downloads).
    TEXT_CSV
        Comma-separated values (tabular exports).
    """

    APPLICATION_JSON         = "application/json"
    APPLICATION_ZIP          = "application/zip"
    APPLICATION_OCTET_STREAM = "application/octet-stream"
    TEXT_CSV                 = "text/csv"

T = TypeVar("T")

DEFAULT_SPECTRUM_ANALYZER_INDICES: Final[list[int]] = [0]


FEC_SUMMARY_TYPE_STEP_SECONDS: dict[int, int] = {
    2: 1,      # interval10min(2): 600 samples, 1 sec apart
    3: 60,     # interval24hr(3): 1440 samples, 60 sec apart
    # other(1): unknown / device-specific, do not enforce
}

FEC_SUMMARY_TYPE_LABEL: dict[int, str] = {
    1: "other",
    2: "10-minute interval (1s cadence)",
    3: "24-hour interval (60s cadence)",
}

STATUS_OK:STATUS = True
STATUS_NOK:STATUS = False

__all__ = [
    "STATUS_OK", "STATUS_NOK",
    "DEFAULT_SSH_PORT",
    "HZ", "KHZ", "MHZ", "GHZ",
    "ZERO_FREQUENCY",
    "FEET_PER_METER", "SPEED_OF_LIGHT",
    "NULL_ARRAY_NUMBER",
    "INVALID_CHANNEL_ID", "INVALID_PROFILE_ID", "INVALID_SUB_CARRIER_ZERO_FREQ",
    "INVALID_START_VALUE", "INVALID_SCHEMA_TYPE", "INVALID_CAPTURE_TIME",
    "DEFAULT_CAPTURE_TIME",
    "CableTypes", "CABLE_VF",
    "DEFAULT_SPECTRUM_ANALYZER_INDICES",
    "FEC_SUMMARY_TYPE_STEP_SECONDS", "FEC_SUMMARY_TYPE_LABEL",
]

# FILE: src/pypnm/lib/types.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import NewType, TypeAlias

import numpy as np
from numpy.typing import NDArray

# TODO: New home for these
GroupId             = NewType("GroupId", str)
TransactionId       = NewType("TransactionId", str)
TransactionRecord  = NewType("TransactionRecord", dict)
OperationId         = NewType("OperationId", str)

HashStr = NewType("HashStr", str)
ExitCode = NewType("ExitCode", int)

# Enum String Type
class StringEnum(str, Enum):
    """Py3.10-compatible StrEnum shim."""
    pass

class FloatEnum(float, Enum):
    """Float-like Enum base: members behave like floats."""
    pass

# Basic strings
String: TypeAlias       = str
StringArray: TypeAlias  = list[String]
JsonScalar: TypeAlias   = str | int | float | bool | None
JsonValue: TypeAlias    = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias   = dict[str, JsonValue]

# ────────────────────────────────────────────────────────────────────────────────
# Core numerics
# ────────────────────────────────────────────────────────────────────────────────
Number       = int | float | np.number
Float64      = np.float64
ByteArray    = list[np.uint8]

# Generic array-likes (inputs)
# TODO: Review to remove -> _ArrayLike = Union[Sequence[Number], NDArray[object]]
_ArrayLike   = Sequence[Number] | NDArray[np.generic]

ArrayLike    = list[Number]
ArrayLikeF64 = Sequence[float] | NDArray[np.float64]

# Canonical ndarray outputs (internal processing should normalize to these)
NDArrayF64: TypeAlias   = NDArray[np.float64]
NDArrayI64: TypeAlias   = NDArray[np.int64]
NDArrayC128: TypeAlias  = NDArray[np.complex128]

# ────────────────────────────────────────────────────────────────────────────────
# Simple series / containers  — use TypeAlias (recommended)
# ────────────────────────────────────────────────────────────────────────────────
IntSeries: TypeAlias        = list[int]
FloatSeries: TypeAlias      = list[float]
TwoDFloatSeries: TypeAlias  = list[FloatSeries]
FloatSequence: TypeAlias    = Sequence[float]

# Complex number encodings (JSON-safe)
Complex                  = tuple[float, float]  # (re, im)
ComplexArray: TypeAlias  = list[Complex]        # K × (re, im)
ComplexSeries: TypeAlias = list[complex]        # Python complex list (internal use)
ComplexMatrix: TypeAlias = list[ComplexArray]

# ────────────────────────────────────────────────────────────────────────────────
# Modulation profile identifiers
# ────────────────────────────────────────────────────────────────────────────────
ProfileId = NewType("ProfileId", int)

# ────────────────────────────────────────────────────────────────────────────────
# Paths / filesystem
# ────────────────────────────────────────────────────────────────────────────────
PathLike    = str | Path
PathArray   = list[PathLike]
FileNameStr = NewType("FileNameStr", str)

# ────────────────────────────────────────────────────────────────────────────────
# JSON-like structures for REST I/O
# ────────────────────────────────────────────────────────────────────────────────
JSONScalar = str | int | float | bool | None
JSONDict   = dict[str, "JSONValue"]
JSONList   = list["JSONValue"]
JSONValue  = JSONScalar | JSONDict | JSONList

# ────────────────────────────────────────────────────────────────────────────────
# Unit-tagged NewTypes (scalars only; runtime = underlying type)
# ────────────────────────────────────────────────────────────────────────────────
# Time / index
CaptureTime   = NewType("CaptureTime", int)
TimeStamp     = NewType("TimeStamp", int)
TimestampSec  = NewType("TimestampSec", int)
TimestampMs   = NewType("TimestampMs", int)
TimeStampUs   = NewType("TimeStampUs", int)
TimeStampNs   = NewType("TimeStampNs", int)
SampleIndex   = NewType("SampleIndex", int)

# RF / PHY units (keep as scalars with units)
FrequencyHz   = NewType("FrequencyHz", int)
BandwidthHz   = NewType("BandwidthHz", int)
ResolutionBw  = NewType("ResolutionBw", int)
SegmentFreqSpan = NewType("SegmentFreqSpan", int)
NumBins       = NewType("NumBins", int)

PowerdBmV     = NewType("PowerdBmV", float)
PowerdB       = NewType("PowerdB", float)
MERdB         = NewType("MERdB", float)
SNRdB         = NewType("SNRdB", float)
SNRln         = NewType("SNRln", float)

# DOCSIS identifiers
ChannelId     = NewType("ChannelId", int)
SubcarrierId  = NewType("SubcarrierId", int)
SubcarrierIdx = NewType("SubcarrierIdx", int)

# SNMP identifiers
OidStr          = NewType("OidStr", str)              # symbolic or dotted-decimal
OidNumTuple     = NewType("OidNumTuple", tuple[int, ...])
SnmpIndex       = NewType("SnmpIndex", int)
InterfaceIndex  = NewType("InterfaceIndex", int)
EntryIndex      = NewType("EntryIndex", int)

# Network addressing (store as plain strings; validate elsewhere)
HostNameStr     = NewType("HostNameStr", str)
SnmpReadCommunity  = NewType("SnmpReadCommunity", str)
SnmpWriteCommunity = NewType("SnmpWriteCommunity", str)
SnmpCommunity      = SnmpReadCommunity
MacAddressStr   = NewType("MacAddressStr", str)         # aa:bb:cc:dd:ee:ff | aa-bb-cc-dd-ee-ff | aabb.ccdd.eeff | aabbccddeeff | aabbcc:ddeeff |
InetAddressStr  = NewType("InetAddressStr", str)        # 192.168.0.1 | 2001:db8::1
IPv4Str         = NewType("IPv4Str", InetAddressStr)    # 192.168.0.1
IPv6Str         = NewType("IPv6Str", InetAddressStr)    # 2001:db8::1

# File tokens
FileStem      = NewType("FileStem", str)            # name without extension
FileExt       = NewType("FileExt", str)             # ".csv", ".png", …
FileName      = NewType("FileName", str)

# ────────────────────────────────────────────────────────────────────────────────
# Analysis-specific tuples / series
# ────────────────────────────────────────────────────────────────────────────────
RegressionCoeffs = tuple[float, float]              # (slope, intercept)
RegressionStats  = tuple[float, float, float]       # (slope, intercept, r2)

# Spectrum analysis extension payloads
SpectrumAnalysisSnmpCaptureParameters: TypeAlias = dict[str, int | float]
ResolutionBwSettings: TypeAlias = tuple[ResolutionBw, NumBins, SegmentFreqSpan]

# RxMER / spectrum containers
FrequencySeriesHz: TypeAlias = list[FrequencyHz]
MerSeriesdB: TypeAlias       = FloatSeries
ShannonSeriesdB: TypeAlias   = FloatSeries
MagnitudeSeries: TypeAlias   = FloatSeries

BitsPerSymbol       = NewType("BitsPerSymbol", int)
BitsPerSymbolSeries: TypeAlias = list[BitsPerSymbol]

Microseconds = NewType("Microseconds", float)

# IFFT time response
IfftTimeResponse: TypeAlias = tuple[NDArrayF64, NDArrayC128]

# ────────────────────────────────────────────────────────────────────────────────
# HTTP return code type
# ────────────────────────────────────────────────────────────────────────────────
HttpRtnCode = NewType("HttpRtnCode", int)

ScalarValue: TypeAlias = float | int | str

# ────────────────────────────────────────────────────────────────────────────────
# SSH return code type
# ────────────────────────────────────────────────────────────────────────────────
UserNameStr         = NewType("UserNameStr", str)

SshOk: TypeAlias    = bool
SshStdout           = NewType("SshStdout", str)
SshStderr           = NewType("SshStderr", str)
SshExitCode         = NewType("SshExitCode", int)
SshCommandResult: TypeAlias = tuple[SshStdout, SshStderr, SshExitCode]

RemoteDirEntry             = NewType("RemoteDirEntry", str)
RemoteDirEntries: TypeAlias = list[RemoteDirEntry]

STATUS:TypeAlias = bool

# ────────────────────────────────────────────────────────────────────────────────
# Explicit public surface
# ────────────────────────────────────────────────────────────────────────────────
__all__ = [
    "STATUS",
    "SshOk", "SshStdout", "SshStderr", "SshExitCode", "SshCommandResult",
    "RemoteDirEntry", "RemoteDirEntries", "UserNameStr",
    "ScalarValue",
    "HashStr",
    "TransactionId", "GroupId", "OperationId",
    # enums
    "StringEnum", "FloatEnum",
    # strings
    "String", "StringArray",
    "ByteArray",
    # numerics
    "Number", "Float64", "ArrayLike", "ArrayLikeF64", "NDArrayF64", "NDArrayI64",
    "FloatSeries", "TwoDFloatSeries", "FloatSequence", "IntSeries",
    # complex
    "Complex", "ComplexArray", "ComplexSeries",
    # paths
    "PathLike", "PathArray", "FileNameStr",
    # JSON
    "JSONScalar", "JSONDict", "JSONList", "JSONValue",
    # unit-tagged scalars
    "CaptureTime", "TimeStamp", "TimestampSec", "TimestampMs", "TimeStampUs", "TimeStampNs",
    "SampleIndex",
    "FrequencyHz", "BandwidthHz", "ResolutionBw", "SegmentFreqSpan", "NumBins",
    "PowerdBmV", "PowerdB", "MERdB", "SNRdB", "SNRln",
    "ChannelId", "SubcarrierId",
    "OidStr", "OidNumTuple",
    "SnmpReadCommunity", "SnmpWriteCommunity", "SnmpCommunity",
    "MacAddressStr", "IPv4Str", "IPv6Str",
    "FileStem", "FileExt", "FileName",
    # analysis tuples / series
    "RegressionCoeffs", "RegressionStats", "SpectrumAnalysisSnmpCaptureParameters", "ResolutionBwSettings",
    "FrequencySeriesHz", "MerSeriesdB", "ShannonSeriesdB", "MagnitudeSeries",
    # modulation/profile & misc
    "ProfileId", "BitsPerSymbol", "BitsPerSymbolSeries", "Microseconds",
    "HttpRtnCode", "InterfaceIndex", "EntryIndex"
]

# FILE: src/pypnm/pnm/data_type/DocsIf3CmSpectrumAnalysisCtrlCmd.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from pypnm.lib.types import STATUS, ResolutionBw
from pypnm.lib.utils import Generate


class SpectrumRetrievalType(IntEnum):
    """
    Defines the method by which spectrum analysis results are retrieved from a cable modem.

    Attributes:
        FILE (int): Retrieve results from a file (e.g., via TFTP).
        SNMP (int): Retrieve results directly using SNMP queries.
    """
    UNKNOWN = -1
    ERROR   = 0
    FILE    = 1
    SNMP    = 2

class WindowFunction(IntEnum):
    """
    Enum representing windowing functions used during spectrum analysis via
    Discrete Fourier Transform (DFT).

    These functions help reduce spectral leakage by shaping the input signal
    prior to transformation. Not all devices support all functions; attempting
    to configure an unsupported window function may result in an SNMP
    `inconsistentValue` error.

    Reference:
        Harris, Fredric J. (1978). "On the use of Windows for Harmonic Analysis
        with the Discrete Fourier Transform", Proceedings of the IEEE,
        Vol. 66, Issue 1, doi:10.1109/PROC.1978.10837

    Values:
        OTHER (0): Unspecified or device-specific windowing function.
        HANN (1): Hann window — reduces side lobes, suitable for general use.
        BLACKMAN_HARRIS (2): High dynamic range window with low spectral leakage.
        RECTANGULAR (3): No windowing; equivalent to a raw DFT.
        HAMMING (4): Similar to Hann but with slightly different tapering.
        FLAT_TOP (5): Flatter frequency response — good for amplitude accuracy.
        GAUSSIAN (6): Gaussian shape; parameterized by standard deviation.
        CHEBYSHEV (7): Minimizes main lobe width for a given side lobe level.
    """
    OTHER = 0
    HANN = 1
    BLACKMAN_HARRIS = 2
    RECTANGULAR = 3
    HAMMING = 4
    FLAT_TOP = 5
    GAUSSIAN = 6
    CHEBYSHEV = 7

class SpectrumAnalysisDefaults(IntEnum):
    """
    Enum class representing the default configuration values for spectrum analysis.

    These defaults are used to control the parameters for spectrum analysis in DOCSIS-based systems.
    The values are used in the configuration of spectrum analysis commands, like center frequencies,
    frequency span, noise bandwidth, and window function.

    Attributes:
        ENABLE (int): The enable flag for the spectrum analysis.
        FILE_ENABLE (SpectrumRetrievalType): Whether to enable file-based retrieval for spectrum analysis results.
        INACTIVITY_TIMEOUT (int): Timeout in seconds before the spectrum analysis is considered inactive.
        FIRST_SEGMENT_CENTER_FREQ (int): Center frequency (in Hz) for the first spectrum segment.
        LAST_SEGMENT_CENTER_FREQ (int): Center frequency (in Hz) for the last spectrum segment.
        SEGMENT_FREQ_SPAN (int): Frequency span (in Hz) of each spectrum segment.
        NUM_BINS_PER_SEGMENT (int): Number of bins used in each spectrum segment.
        NOISE_BW (int): Equivalent noise bandwidth in MHz.
        WINDOW_FUNCTION (WindowFunction): The window function used in the analysis (e.g., Hann, Hamming).
        NUM_AVERAGES (int): The number of averages used for the analysis.
    """

    ENABLE = 1
    FILE_ENABLE = SpectrumRetrievalType.FILE
    INACTIVITY_TIMEOUT = 100
    FIRST_SEGMENT_CENTER_FREQ = 108_000_000
    LAST_SEGMENT_CENTER_FREQ = 993_000_000
    SEGMENT_FREQ_SPAN = 1_000_000
    NUM_BINS_PER_SEGMENT = 256
    NOISE_BW = 110
    WINDOW_FUNCTION = WindowFunction.HANN
    NUM_AVERAGES = 1

    @classmethod
    def to_dict(cls) -> dict:
        """
        Convert the enum class to a dictionary where each enum name is mapped to its value.

        Returns:
            dict: A dictionary containing the enum names as keys and the corresponding values.
        """
        return {key.name: key.value for key in cls}

    @classmethod
    def to_json(cls) -> str:
        """
        Export the default spectrum analysis configuration values as a JSON string.

        This method serializes the class's default attribute values into a dictionary and converts it
        to a JSON string. This is useful for getting the configuration data in JSON format without
        writing to a file.

        Returns:
            str: The JSON string representation of the class's default configuration.

        Example:
            json_string = SpectrumAnalysisDefaults.to_json()
        """
        return json.dumps(cls.to_dict(), indent=4)

@dataclass
class DocsIf3CmSpectrumAnalysisCtrlCmd:
    """
    Represents the control command configuration for DOCSIS 3.0/3.1+ Cable Modem Spectrum Analysis.

    This class encapsulates all parameters required to initiate a spectrum analysis test using
    SNMP control objects. It includes default values (via `SpectrumAnalysisDefaults`) and provides
    setter methods for each parameter to validate and update values safely before sending SNMP `set` operations.

    Source: https://mibs.cablelabs.com/MIBs/DOCSIS/
    MIB: DOCS-IF3-MIB

    Attributes:
        docsIf3CmSpectrumAnalysisCtrlCmdEnable (int): Enables spectrum analysis (1 = true, 2 = false).
        docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout (int): Timeout in seconds for inactivity before abort.
        docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency (int): Starting frequency of analysis (Hz).
        docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency (int): Ending frequency of analysis (Hz).
        docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan (int): Span per segment (Hz).
        docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment (int): Number of FFT bins per segment.
        docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth (int): ENBW used in DFT windowing.
        docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction (int): Window function ID to apply (see `WindowFunction` enum).
        docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages (int): Number of FFT averages to smooth noise floor.
        docsIf3CmSpectrumAnalysisCtrlCmdFileEnable (int): Enables storing result to file (1 = true, 2 = false).
        docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus (int): Read-only measurement status (1 = running, 2 = notRunning).
        docsIf3CmSpectrumAnalysisCtrlCmdFileName (str): Optional filename for output binary file.

    Methods:
        set_enable(value): Validates and sets enable flag.
        set_inactivity_timeout(value): Sets inactivity timeout (0-86400).
        set_first_segment_center_frequency(value): Sets first segment center frequency (>0).
        set_last_segment_center_frequency(value): Sets last segment center frequency (>0).
        set_segment_frequency_span(value): Sets span in Hz (1 MHz - 900 MHz).
        set_num_bins_per_segment(value): Sets bin count (2 - 2048).
        set_equivalent_noise_bandwidth(value): Sets ENBW in Hz (50 - 500).
        set_window_function(value): Sets window function from `WindowFunction` enum.
        set_number_of_averages(value): Sets number of FFT averages (1 - 1000).
        set_file_enable(value): Enables/disables file output.
        set_meas_status(value): Sets measurement status (1 = running, 2 = notRunning).
        set_file_name(value): Sets file name for output.
        get_member_list(): Returns full SNMP object list with `.0` instance suffixes.
    """
    docsIf3CmSpectrumAnalysisCtrlCmdEnable: int = SpectrumAnalysisDefaults.ENABLE
    docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout: int = SpectrumAnalysisDefaults.INACTIVITY_TIMEOUT
    docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency: int = SpectrumAnalysisDefaults.FIRST_SEGMENT_CENTER_FREQ
    docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency: int = SpectrumAnalysisDefaults.LAST_SEGMENT_CENTER_FREQ
    docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan: int = SpectrumAnalysisDefaults.SEGMENT_FREQ_SPAN
    docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment: int = SpectrumAnalysisDefaults.NUM_BINS_PER_SEGMENT
    docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth: int = SpectrumAnalysisDefaults.NOISE_BW
    docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction: int = SpectrumAnalysisDefaults.WINDOW_FUNCTION
    docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages: int = SpectrumAnalysisDefaults.NUM_AVERAGES
    docsIf3CmSpectrumAnalysisCtrlCmdFileEnable: int = SpectrumAnalysisDefaults.FILE_ENABLE
    docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus: int = -1
    docsIf3CmSpectrumAnalysisCtrlCmdFileName: str = f"spectrum_analysis_{Generate.time_stamp()}.bin"

    def __post_init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def autoScaleSpectrumAnalyzerRbw(self, rbw: ResolutionBw, adjust_segment_span: bool) -> tuple[STATUS, bool]:
        """
        This function take priority of the RBW, and calculate the following

        RBW = SegementSpan/FreqSpan

        Rules:
            FreqSpan % SegementSpan == 0
            if adjust_segment_span == true, update SegmentSpan to match RBW and adjust the frequency span inward at a minimum
            if adjust_segment_span == false, keep the frequency span and find SegmentSpan to meet RBW within 5% (prefer exact)

            at teh end, if if it is not achivable, then set STATUS to STATUS_NOK, else STATUS_OK

        """
        min_segment_span_hz = 1_000_000
        max_segment_span_hz = 900_000_000
        min_bins = 2
        max_bins = 2048
        tolerance_ratio = 0.05

        if rbw <= 0:
            self.logger.debug("RBW must be positive.")
            return False, False

        num_bins = int(self.docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment)
        if num_bins < min_bins or num_bins > max_bins:
            self.logger.debug("NumBinsPerSegment out of range: %s", num_bins)
            return False, False

        first_center = int(self.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency)
        last_center = int(self.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency)
        total_span = last_center - first_center
        if total_span <= 0:
            self.logger.debug("Invalid frequency span: first=%s last=%s", first_center, last_center)
            return False, False

        current_segment_span = int(self.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan)
        ideal_segment_span = int(rbw) * num_bins
        if ideal_segment_span <= 0:
            self.logger.debug("Computed segment span is invalid: %s", ideal_segment_span)
            return False, False

        if adjust_segment_span:
            if (ideal_segment_span < min_segment_span_hz or
                ideal_segment_span > max_segment_span_hz or
                ideal_segment_span > total_span):
                self.logger.debug(
                    "Ideal segment span out of range: %s (total span %s)",
                    ideal_segment_span,
                    total_span,
                )
                return False, False

            remainder = total_span % ideal_segment_span
            new_first = first_center
            new_last = last_center
            if remainder != 0:
                lower_adjust = remainder // 2
                upper_adjust = remainder - lower_adjust
                new_first = first_center + lower_adjust
                new_last = last_center - upper_adjust
                if new_last <= new_first:
                    self.logger.debug("Adjusted frequency span is invalid after alignment.")
                    return False, False

            self.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency = new_first
            self.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency = new_last
            self.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan = ideal_segment_span

            changed = (
                new_first != first_center or
                new_last != last_center or
                ideal_segment_span != current_segment_span
            )
            return True, changed

        max_segments = total_span // min_segment_span_hz
        if max_segments < 1:
            self.logger.debug("Total span too small for minimum segment span.")
            return False, False

        best_span = 0
        best_diff = 1.0
        best_distance = 0
        target_rbw = float(rbw)

        for segment_count in range(1, max_segments + 1):
            if total_span % segment_count != 0:
                continue
            segment_span = total_span // segment_count
            if segment_span < min_segment_span_hz or segment_span > max_segment_span_hz:
                continue

            actual_rbw = float(segment_span) / float(num_bins)
            diff_ratio = abs(actual_rbw - target_rbw) / target_rbw
            if diff_ratio > tolerance_ratio:
                continue

            distance = abs(segment_span - ideal_segment_span)
            if diff_ratio < best_diff or (diff_ratio == best_diff and distance < best_distance):
                best_span = segment_span
                best_diff = diff_ratio
                best_distance = distance

        if best_span == 0:
            self.logger.debug("No valid segment span found within RBW tolerance.")
            return False, False

        self.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan = best_span
        changed = best_span != current_segment_span
        return True, changed

    def precheck_spectrum_analyzer_settings(self) -> bool:
        """
        Validate that the spectrum analyzer's first/last segment center frequencies
        and the per-segment frequency span divide evenly into whole segments.

        If the total frequency range (last_center - first_center) isn't an exact multiple
        of the segment span, this method will **increase** the start segment center frequency
        to the nearest value that yields an integer number of segments.

        Returns:
            bool
                False if settings were already valid (no adjustment needed);
                True if the First segment center frequency was adjusted.

        Raises:
            ValueError
                If the configured last segment center frequency is lower than the first.
        """
        # Read and convert settings
        first_center = float(self.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency)
        last_center = float(self.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency)
        seg_freq_span = float(self.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan)

        # Compute total range and sanity‐check
        total_range = last_center - first_center
        if total_range < 0:
            raise ValueError(
                "docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency "
                "must be >= docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency")

        # Check for exact divisibility
        remainder = total_range % seg_freq_span
        if remainder == 0:
            self.logger.debug(f'No changes to SpectrumAnalysisCtrlCmd due to SegmentCenterFrequency({seg_freq_span}) divisible: ({total_range})')
            return False

        # Adjust the last center downward to the nearest whole‐segment boundary
        adjusted_first = int(first_center + remainder)
        self.logger.debug(f'New Start Center Frequency: {adjusted_first}')
        self.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency = adjusted_first
        return True

    def set_enable(self, value: int) -> None:
        if value not in (1, 2):
            raise ValueError("Enable must be 1 (true) or 2 (false)")
        self.docsIf3CmSpectrumAnalysisCtrlCmdEnable = value
        self.logger.debug(f"Set enable to {value}")

    def set_inactivity_timeout(self, value: int) -> None:
        if not 0 <= value <= 86400:
            raise ValueError("InactivityTimeout must be between 0 and 86400 seconds")
        self.docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout = value
        self.logger.debug(f"Set inactivity timeout to {value}")

    def set_first_segment_center_frequency(self, value: int) -> None:
        if value <= 0:
            raise ValueError("FirstSegmentCenterFrequency must be a positive integer")
        self.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency = value
        self.logger.debug(f"Set first segment center frequency to {value}")

    def set_last_segment_center_frequency(self, value: int) -> None:
        if value <= 0:
            raise ValueError("LastSegmentCenterFrequency must be a positive integer")
        self.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency = value
        self.logger.debug(f"Set last segment center frequency to {value}")

    def set_segment_frequency_span(self, value: int) -> None:
        if not 1000000 <= value <= 900000000:
            raise ValueError("SegmentFrequencySpan must be between 1 MHz and 900 MHz")
        self.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan = value
        self.logger.debug(f"Set segment frequency span to {value}")

    def set_num_bins_per_segment(self, value: int) -> None:
        if not 2 <= value <= 2048:
            raise ValueError("NumBinsPerSegment must be between 2 and 2048")
        self.docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment = value
        self.logger.debug(f"Set number of bins per segment to {value}")

    def set_equivalent_noise_bandwidth(self, value: int) -> None:
        if not 50 <= value <= 500:
            raise ValueError("EquivalentNoiseBandwidth must be between 50 and 500")
        self.docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth = value
        self.logger.debug(f"Set equivalent noise bandwidth to {value}")

    def set_window_function(self, value: int) -> None:
        try:
            window = WindowFunction(value)
        except ValueError:
            raise ValueError("Invalid WindowFunction value") from None
        self.docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction = window
        self.logger.debug(f"Set window function to {window.name} ({value})")

    def set_number_of_averages(self, value: int) -> None:
        if not 1 <= value <= 1000:
            raise ValueError("NumberOfAverages must be between 1 and 1000")
        self.docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages = value
        self.logger.debug(f"Set number of averages to {value}")

    def set_file_enable(self, value: int) -> None:
        if value not in (1, 2):
            raise ValueError("FileEnable must be 1 (true) or 2 (false)")
        self.docsIf3CmSpectrumAnalysisCtrlCmdFileEnable = value
        self.logger.debug(f"Set file enable to {value}")

    def set_meas_status(self, value: int) -> None:
        if value not in (1, 2):
            raise ValueError("MeasStatus must be 1 (running) or 2 (notRunning)")
        self.docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus = value
        self.logger.debug(f"Set measurement status to {value}")

    def set_file_name(self, value: str) -> None:
        if not isinstance(value, str):
            raise ValueError("FileName must be a string")
        self.docsIf3CmSpectrumAnalysisCtrlCmdFileName = value
        self.logger.debug(f"Set file name to {value}")

    def to_dict(self) -> dict[str, Any]:
        spectrum_cmd = {
            "docsIf3CmSpectrumAnalysisCtrlCmdEnable":                          self.docsIf3CmSpectrumAnalysisCtrlCmdEnable,
            "docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout":               self.docsIf3CmSpectrumAnalysisCtrlCmdInactivityTimeout,
            "docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency":     self.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency,
            "docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency":      self.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency,
            "docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan":            self.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan,
            "docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment":               self.docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment,
            "docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth":        self.docsIf3CmSpectrumAnalysisCtrlCmdEquivalentNoiseBandwidth,
            "docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction":                  self.docsIf3CmSpectrumAnalysisCtrlCmdWindowFunction,
            "docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages":                self.docsIf3CmSpectrumAnalysisCtrlCmdNumberOfAverages,
            "docsIf3CmSpectrumAnalysisCtrlCmdFileEnable":                      self.docsIf3CmSpectrumAnalysisCtrlCmdFileEnable,
            "docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus":                      self.docsIf3CmSpectrumAnalysisCtrlCmdMeasStatus,
            "docsIf3CmSpectrumAnalysisCtrlCmdFileName":                        self.docsIf3CmSpectrumAnalysisCtrlCmdFileName,
        }
        return spectrum_cmd

# FILE: tests/test_spectrum_analysis_ctrl_cmd_rbw.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026

from __future__ import annotations

from pypnm.lib.types import ResolutionBw
from pypnm.pnm.data_type.DocsIf3CmSpectrumAnalysisCtrlCmd import (
    DocsIf3CmSpectrumAnalysisCtrlCmd,
)


def test_auto_scale_rbw_adjusts_frequency_span() -> None:
    cmd = DocsIf3CmSpectrumAnalysisCtrlCmd(
        docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency=100_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency=105_050_000,
        docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan=1_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment=10,
    )

    status, changed = cmd.autoScaleSpectrumAnalyzerRbw(ResolutionBw(100_000), True)

    assert status is True
    assert changed is True
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan == 1_000_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency == 100_025_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency == 105_025_000


def test_auto_scale_rbw_selects_segment_span_without_frequency_shift() -> None:
    cmd = DocsIf3CmSpectrumAnalysisCtrlCmd(
        docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency=100_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency=105_200_000,
        docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan=1_000_000,
        docsIf3CmSpectrumAnalysisCtrlCmdNumBinsPerSegment=10,
    )

    status, changed = cmd.autoScaleSpectrumAnalyzerRbw(ResolutionBw(100_000), False)

    assert status is True
    assert changed is True
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdSegmentFrequencySpan == 1_040_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdFirstSegmentCenterFrequency == 100_000_000
    assert cmd.docsIf3CmSpectrumAnalysisCtrlCmdLastSegmentCenterFrequency == 105_200_000

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
        yield (None, None, 0, [in_subtree])
        yield (None, None, 0, [out_of_subtree])

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)

    results = await snmp.bulk_walk(oid)

    assert results is not None
    assert results == [in_subtree]


@pytest.mark.asyncio
async def test_bulk_walk_returns_none_on_empty_payload(
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
        yield (None, None, 0, [])

    monkeypatch.setattr(snmp, "_to_object_identity", lambda oid_value: FakeIdentity(str(oid_value)))
    monkeypatch.setattr(snmp_v2c_module.UdpTransportTarget, "create", fake_create)
    monkeypatch.setattr(snmp_v2c_module, "ObjectType", fake_object_type)
    monkeypatch.setattr(snmp_v2c_module, "bulk_cmd", fake_bulk_cmd)

    results = await snmp.bulk_walk("1.3.6.1.2.1")

    assert results is None
