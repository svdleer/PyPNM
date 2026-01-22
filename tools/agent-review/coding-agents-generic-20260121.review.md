## Agent Review Bundle Summary
- Goal: Refactor CODING_AGENTS.md to be a generic AI coding guide with reuse-first guidance and pytest expectations.
- Changes: Added reuse index references, clarified generic scope vs AGENTS.md, expanded pytest guidance to mirror PyPNM test patterns, added agent constraints, and tightened typing/type-definition rules.
- Files: CODING_AGENTS.md
- Tests: Not run in this doc-only update.
- Notes: None.

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
