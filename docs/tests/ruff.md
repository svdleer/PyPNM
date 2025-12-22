# Ruff Linting Guide For PyPNM

Ruff is the primary linter for PyPNM. It replaces flake8, isort, pyupgrade, and several other tools with a **single, fast** executable.

This guide focuses on **how Ruff is configured in PyPNM** and **useful options/features** you can lean on during development.

## 1. Project Configuration

Ruff is configured in `pyproject.toml`:

```toml
[tool.ruff]
src            = ["src"]
target-version = "py310"
exclude        = [
  "tools",
  "src/pypnm/lib/matplot/manager.py",
  "src/pypnm/lib/csv/manager.py",
  "src/pypnm/api/routes/common/extended/common_messaging_service.py",
  "src/pypnm/api/routes/common/extended/common_measure_service.py",
  "src/pypnm/examples/",
]

[tool.ruff.lint]
select = ["F", "E", "W", "I", "B", "UP", "ANN", "SIM", "PERF"]
ignore = [
  "E501",  # line length (Black controls this)
  "B006",  # mutable default arguments (handled manually)
]
```

### 1.1 Enabled Rule Families

Ruff rule codes enabled for PyPNM:

- **F** - Pyflakes: real errors (unused names, undefined variables, etc.).
- **E/W** - pycodestyle: basic style / correctness (whitespace, comparisons, etc.).
- **I** - isort: import sorting & grouping.
- **B** - flake8-bugbear: common bug patterns and suspicious constructs.
- **UP** - pyupgrade: auto-modernization for newer Python versions.
- **ANN** - type-annotation rules (light enforcement for consistency).
- **SIM** - simplify overly complex patterns where it’s safe.
- **PERF** - basic performance anti-patterns (e.g., repeated list concatenations).

Anything outside these families remains disabled unless explicitly enabled later.

## 2. Core CLI Usage

Ruff operates on the **source tree** (`src`) and (optionally) tests.

### 2.1 Quick Checks

```bash
# From the project root
ruff check src
ruff check src tests
```

Useful variants:

```bash
# Only show unused imports / unused locals
ruff check src tests --select F401,F841

# Only run the configured rule families (default behavior)
ruff check src
```

### 2.2 Auto-Fix Mode

```bash
# Apply safe fixes in-place
ruff check src --fix

# Show what would be fixed, without changing files
ruff check src --fix --diff
```

Common auto-fix behaviors:

- Reorder imports to match `I` rules (import sorting).
- Apply some `UP` transforms (modern syntax) where safe.
- Remove obviously unused imports / variables when unambiguous.

If a fix looks questionable, **commit before running `--fix`** so you can roll back.

## 3. Working With Rules

### 3.1 Narrowing or Expanding Families

To temporarily narrow the rule set from the CLI:

```bash
# Only import-related issues (unused, order, duplicates)
ruff check src --select F401,F403,F405,I

# Only simplification and performance hints
ruff check src --select SIM,PERF
```

To experiment with new rule families **without changing `pyproject.toml`**, just run ad‑hoc:

```bash
# Try docstring rules (D) without committing
ruff check src --select D
```

### 3.2 Rule-by-Rule Control

If a particular rule is too noisy or conflicts with a local pattern, you can:

1. Disable it project-wide by adding a specific code to `ignore`:

   ```toml
   [tool.ruff.lint]
   select = ["F", "E", "W", "I", "B", "UP", "ANN", "SIM", "PERF"]
   ignore = ["E501", "B006", "ANN101", "ANN102"]
   ```

2. Or, suppress it for a single line with `# noqa`:

   ```python
   value = some_weird_thing()  # noqa: SIM110
   ```

3. Or, suppress for an entire file at the top:

   ```python
   # ruff: noqa
   ```

Prefer **config-level ignores** for systematic patterns and `noqa` for rare exceptions.

## 4. Dealing With Type-Annotation (ANN) Rules

`ANN` rules help keep typing consistent but can be chatty. Typical strategies:

- Use them as **guidance, not absolute law**. If a rule is consistently noisy, ignore that specific code.
- For internal helpers, it’s fine to relax some rules with `noqa` if the signature is obvious.
- For public APIs (routers, models, service classes), keep annotations complete; they pay off in Pyright and user-facing docs.

If ANN gets in the way during a big refactor, you can temporarily narrow the check:

```bash
ruff check src --select F,E,W,I,B,UP
```

(Leaving ANN out of the `select` set for that run.)

## 5. Performance & Scope

Ruff is extremely fast. You can comfortably run it:

- In **pre-commit hooks**.
- In the **`pypnm-software-qa-checker`** suite.
- Ad-hoc on subsets of the tree:

  ```bash
  ruff check src/pypnm/lib/types.py
  ruff check src/pypnm/api/routes/docs/pnm/ds/ofdm
  ```

Because the configuration is centralized in `pyproject.toml`, these invocations all share the same behavior and rule set.

## 6. Suggested Workflows

- **During development**: run `ruff check src` or let the editor integration surface issues continuously.
- **Before commit**: run `pypnm-software-qa-checker` (which wraps Ruff + pytest + pycycle).
- **Before a bigger refactor**: run `ruff check src --select SIM,PERF` to look for easy cleanups and performance hints you might want to fold in while touching the code anyway.

Ruff should remain a **safety net and clean-up helper**, not a roadblock. If a rule doesn’t earn its keep, disable that specific code rather than fighting it everywhere.
