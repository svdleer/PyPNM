# PyPNM - pytest Usage Guide

Consistent, fast, and repeatable testing for the PyPNM codebase using `pytest`.

## 1. Test Layout In PyPNM

PyPNM follows a standard `src/` + `tests/` layout:

- Application code: `src/pypnm/...`
- Tests: `tests/`

Typical patterns:

- Unit and parsing tests: `tests/test_*.py`
- PNM file parsing tests: `tests/test_pnm_*.py`
- Integration tests (cable modem SNMP): `tests/test_cable_modem_*.py` (gated by markers and env vars)

pytest automatically discovers tests that follow these naming conventions.

## 2. Default pytest Configuration

pytest is configured via `pyproject.toml` under `[tool.pytest.ini_options]`. Key settings:

```toml
[tool.pytest.ini_options]
minversion   = "8.0"
pythonpath   = ["src"]
testpaths    = ["tests"]
addopts      = "-ra -q --strict-markers --tb=short -m 'not cm_it'"
asyncio_mode = "auto"
log_cli = true
log_cli_level = "INFO"
log_cli_format = "%(levelname)s %(name)s:%(lineno)d | %(message)s"
log_cli_date_format = "%H:%M:%S"
markers = [
  "asyncio: mark test as asyncio-based (requires pytest-asyncio)",
  "cm_it: cable modem integration tests (enable with -m cm_it)",
  "slow: slow tests",
  "net: network-required tests",
  "pnm: PNM file parsing tests",
]
```

Implications:

- `pythonpath=["src"]` lets tests import `pypnm` without extra sys.path hacks.
- `testpaths=["tests"]` keeps discovery limited and fast.
- `addopts` by default:
  - `-ra` short summary of skipped/xfailed tests
  - `-q` quiet output (per-test lines suppressed)
  - `--strict-markers` enforces marker registration
  - `--tb=short` compact tracebacks
  - `-m 'not cm_it'` skips cable-modem integration tests by default
- `asyncio_mode="auto"` enables seamless async tests using `pytest-asyncio`.
- CLI logging is enabled at `INFO` with a consistent format.

## 3. Everyday Commands

All commands assume you are in the project root (for example `~/Projects/PyPNM`) and have the dev dependencies installed:

```bash
pip install -e '.[dev]'
```

### 3.1 Fast default suite

Run the standard test suite (unit + parsing + markers, no `cm_it` integration tests):

```bash
pytest
```

This uses the `addopts` defined in `pyproject.toml`.

### 3.2 Focus on a single file or test

Single file:

```bash
pytest tests/test_pnm_histogram_parse.py
```

Single test within a file:

```bash
pytest tests/test_pnm_histogram_parse.py::test_hist_parses_and_model_shape
```

### 3.3 More verbose output

To temporarily override `-q` and get per-test lines, append `-v`:

```bash
pytest -v
```

You can combine this with explicit paths or markers as needed.

## 4. Markers And Test Selection

PyPNM uses markers to group tests by behavior and dependencies. All markers are registered in `pyproject.toml` and enforced via `--strict-markers`.

| Marker     | Purpose                                       | Example usage                                |
|------------|-----------------------------------------------|----------------------------------------------|
| `pnm`      | PNM file parsing and model-shape tests        | `pytest -m pnm`                              |
| `asyncio`  | Async tests using `pytest-asyncio`            | `pytest -m asyncio -v`                       |
| `net`      | Tests requiring live network connectivity     | `pytest -m net`                              |
| `slow`     | Long-running or heavy tests                   | `pytest -m slow -v`                          |
| `cm_it`    | Cable-modem integration tests (SNMP, hardware)| `pytest -m cm_it`                            |

Combine markers with boolean expressions:

```bash
# All PNM parsing tests that are not slow
pytest -m "pnm and not slow"

# All network tests including their detailed output
pytest -m net -v
```

The default `addopts` excludes `cm_it`, so you must explicitly opt in to those tests.

## 5. Cable-Modem Integration Tests (`cm_it`)

Hardware integration tests are guarded by:

- Marker: `cm_it`
- An environment variable: `PNM_CM_IT=1`

To run them:

```bash
export PNM_CM_IT=1
pytest -m cm_it -v
```

Typical behavior:

- If `PNM_CM_IT` is not set, tests will be skipped with a message such as:
  `Hardware integration disabled. Set PNM_CM_IT=1 to run.`
- The default suite (`pytest` with `addopts`) uses `-m 'not cm_it'`, so these tests never run accidentally.

Use these tests sparingly (for example, before a release or when validating hardware-related changes).

## 6. Async Tests And `pytest-asyncio`

PyPNM includes `pytest-asyncio` in its development dependencies and sets `asyncio_mode="auto"`. This supports:

- `async def` test functions
- Async fixtures

A typical async test looks like:

```python
import pytest

@pytest.mark.asyncio
async def test_snmp_async_round_trip(snmp_client) -> None:
    result = await snmp_client.get("sysDescr.0")
    assert "LANCity" in result
```

Key points:

- The `@pytest.mark.asyncio` marker is optional when `asyncio_mode="auto"`, but it is declared as a marker for clarity and selection.
- Async tests are discovered and run like any other test.

## 7. Coverage With pytest

Coverage is configured via `[tool.coverage.*]` in `pyproject.toml`. To run tests with coverage information:

```bash
pytest --cov=pypnm --cov-report=term-missing
```

This:

- Measures coverage over the `pypnm` package
- Shows a terminal report with missing lines per file

You can add `--cov-report=html` to generate an HTML report:

```bash
pytest --cov=pypnm --cov-report=term-missing --cov-report=html
```

The HTML report is usually written to `htmlcov/index.html` and can be opened in a browser.

## 8. Integration With The PyPNM QA Checker

The `pypnm-software-qa-checker` helper runs pytest as part of the QA suite. A typical invocation:

```bash
pypnm-software-qa-checker
```

By default, this will:

- Run `ruff check` for static analysis
- Run `pytest` with the configuration described above
- Run `pycycle --here` for import cycle detection

You can use that script as a single entry point before committing or pushing changes.

## 9. Troubleshooting

### 9.1 pytest: command not found

- Ensure the virtual environment is active.
- Confirm that `pytest` is installed:

  ```bash
  pip show pytest
  ```

- If needed, reinstall dev dependencies:

  ```bash
  pip install -e '.[dev]'
  ```

### 9.2 Marker-related errors

If you see `PytestUnknownMarkWarning` or marker errors:

- Ensure markers are registered in `pyproject.toml` under `markers`.
- Because `--strict-markers` is enabled, any new marker must be added there.
- Re-run pytest after updating `pyproject.toml`.

### 9.3 Async test failures

If async tests fail due to event-loop issues:

- Verify that `pytest-asyncio` is installed in your environment.
- Ensure you are not manually configuring another asyncio plugin that conflicts with `asyncio_mode="auto"`.


## See Also

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- `pysnmp` and `pysmi` documentation for SNMP integration specifics.
