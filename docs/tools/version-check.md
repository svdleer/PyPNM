# Version Check Tool

Validate that `src/pypnm/version.py` and `pyproject.toml` carry the same version.

## Usage

From the repo root:

```bash
PYPNM_ROOT="$(pwd)"
python "${PYPNM_ROOT}/tools/release/check_version.py"
```

Using the alias (after running `./scripts/install_aliases.sh`):

```bash
PYPNM_ALIAS="pypnm-version-check"
${PYPNM_ALIAS}
```

## JSON output

Use `--json` when you need machine-readable output:

```bash
PYPNM_ROOT="$(pwd)"
python "${PYPNM_ROOT}/tools/release/check_version.py" --json
```

Example JSON payload:

```json
{"version_py":"1.0.3.0","pyproject":"1.0.3.0","match":true,"status":"ok"}
```
