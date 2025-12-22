# PyPNM CLI - FastAPI Service Launcher

The `pypnm` command is the primary entrypoint for launching the PyPNM FastAPI service. It is installed as a console script when you install the `pypnm-docsis` package.

Use this CLI to start the API server for local development, lab use, or deployment behind a reverse proxy.

## Table Of Contents

- [Overview](#overview)
- [Usage Summary](#usage-summary)
- [Command Line Options](#command-line-options)
  - [Network And Transport Options](#network-and-transport-options)
  - [TLS / HTTPS Options](#tls--https-options)
  - [Logging And Worker Options](#logging-and-worker-options)
  - [Auto-Reload Options](#auto-reload-options)
  - [Version Information](#version-information)
- [Common Usage Scenarios](#common-usage-scenarios)
  - [Local HTTP Development](#local-http-development)
  - [Development With Auto-Reload](#development-with-auto-reload)
  - [HTTPS Front-End Deployment](#https-front-end-deployment)
- [Logging And Environment Notes](#logging-and-environment-notes)
- [Troubleshooting](#troubleshooting)
- [See Also](#see-also)

## Overview

The PyPNM CLI wraps `uvicorn` to expose the FastAPI app defined at `pypnm.api.main:app`. It provides a small set of options to control:

- The bind address and port
- Whether HTTPS/TLS is enabled
- Uvicorn logging and number of workers
- Auto-reload behavior during development
- Version reporting for the installed `pypnm` package

The CLI is intentionally minimal and focuses on the most common operational settings. More advanced ASGI deployment scenarios (for example using `gunicorn` + `uvicorn.workers.UvicornWorker`) can be layered on top if needed.

Basic usage:

```bash
pypnm [OPTIONS]
```

## Usage Summary

When you run `pypnm --help`, you should see output similar to:

```text
usage: pypnm [-h] [-v] [--host HOST] [--port PORT] [--ssl] [--cert CERT] [--key KEY]
             [--log-level {critical,error,warning,info,debug,trace}] [--workers WORKERS]
             [--no-access-log] [--reload] [--reload-dir RELOAD_DIRS]
             [--reload-include RELOAD_INCLUDES] [--reload-exclude RELOAD_EXCLUDES]

Launch the PyPNM FastAPI service with optional HTTPS support.

options:
  -h, --help            show this help message and exit
  -v, --version         Show PyPNM version and exit.
  --host HOST           Host to bind (default: 127.0.0.1)
  --port PORT           Port to bind (default: 8000)
  --ssl                 Enable HTTPS (requires cert and key)
  --cert CERT           Path to SSL certificate
  --key KEY             Path to SSL private key
  --log-level {critical,error,warning,info,debug,trace}
                        Uvicorn log level (default: info).
  --workers WORKERS     Number of worker processes (default: 1).
  --no-access-log       Disable Uvicorn access log.
  --reload              Enable auto-reload on file changes (dev only).
  --reload-dir RELOAD_DIRS
                        Directory to watch for changes. Can be passed multiple times. Default: src (when --reload)
  --reload-include RELOAD_INCLUDES
                        Glob pattern(s) to include for reload. Can be passed multiple times. Default: *.py
  --reload-exclude RELOAD_EXCLUDES
                        Glob pattern(s) to exclude from reload. Can be passed multiple times.
```

## Command Line Options

### Network And Transport Options

#### `--host HOST`

Bind address for the FastAPI service.

- Default: `127.0.0.1` (loopback)
- Common values:
  - `127.0.0.1` for local-only access
  - `0.0.0.0` to listen on all interfaces (for example in a container or lab server)

Examples:

```bash
pypnm --host 127.0.0.1
pypnm --host 0.0.0.0
```

#### `--port PORT`

TCP port for the FastAPI service.

- Default: `8000`

Examples:

```bash
pypnm --port 8080
pypnm --host 0.0.0.0 --port 8000
```

### TLS / HTTPS Options {#tls--https-options}

#### `--ssl`

Enable HTTPS/TLS termination directly in the PyPNM process.

- When enabled, `pypnm` configures `uvicorn` with `ssl_certfile` and `ssl_keyfile`.
- You must also provide `--cert` and `--key` options that point to valid certificate and key files.

Example:

```bash
pypnm --ssl --cert ./certs/cert.pem --key ./certs/key.pem
```

#### `--cert CERT`

Path to the PEM-encoded certificate file.

- Default: `./certs/cert.pem`
- Used only when `--ssl` is provided.

#### `--key KEY`

Path to the PEM-encoded private key file.

- Default: `./certs/key.pem`
- Used only when `--ssl` is provided.

### Logging And Worker Options

#### `--log-level {critical,error,warning,info,debug,trace}`

Set the Uvicorn log level.

- Default: `info`
- Use `debug` or `trace` for deeper troubleshooting, at the cost of more verbose logs.

Examples:

```bash
pypnm --log-level warning
pypnm --log-level debug
```

#### `--workers WORKERS`

Number of Uvicorn worker processes.

- Default: `1`
- For simple development and small lab setups, `1` is usually sufficient.
- For larger deployments, you may increase this to better utilize CPU cores.

Examples:

```bash
pypnm --workers 4
pypnm --host 0.0.0.0 --port 8000 --workers 2
```

Note: When `--reload` is enabled, multiple workers are not supported. If you pass `--workers` with `--reload`, PyPNM will force `workers=1` and print a warning.

#### `--no-access-log`

Disable the Uvicorn access log.

- Useful when the access log is too noisy (for example, in tight test loops or CI).

Example:

```bash
pypnm --no-access-log
```

### Auto-Reload Options

These options are useful during development. Auto-reload should not be used in production environments.

#### `--reload`

Enable auto-reload on source code changes.

- Watches the specified directories and file patterns.
- On changes, the server process is restarted automatically.

Example:

```bash
pypnm --reload
```

#### `--reload-dir RELOAD_DIRS`

One or more directories to watch for changes.

- Default when `--reload` is used and no `--reload-dir` is specified: `src`
- Can be passed multiple times:

```bash
pypnm --reload --reload-dir src --reload-dir tests
```

#### `--reload-include RELOAD_INCLUDES`

Glob patterns for files that should trigger reload.

- Default: `*.py`
- Can be used multiple times:

```bash
pypnm --reload --reload-include "*.py" --reload-include "*.yaml"
```

#### `--reload-exclude RELOAD_EXCLUDES`

Glob patterns for files that should be ignored for reload purposes.

- Default: `["*.pyc", "*__pycache__*", "*.tmp", "*.log"]`

Example:

```bash
pypnm --reload --reload-exclude "*.tmp" --reload-exclude "*.bak"
```

### Version Information

#### `-v, --version`

Print the installed PyPNM package version and exit.

Example:

```bash
pypnm --version
```

Sample output:

```text
0.9.8.0
```

This flag is useful for:

- Verifying which version is installed in a given virtual environment
- Capturing environment information when reporting issues

## Common Usage Scenarios

### Local HTTP Development

For simple local development on the default address and port:

```bash
pypnm
```

The service will listen on:

- HTTP: [localhost API](http://127.0.0.1:8000)

You can then open:

- Swagger UI: [localhost Swagger](http://127.0.0.1:8000/docs)
- ReDoc: [localhost ReDoc](http://127.0.0.1:8000/redoc)

### Development With Auto-Reload

When iterating on API code, enable reload so local changes are picked up automatically:

```bash
pypnm --reload
```

This:

- Watches the `src` directory (by default) for Python file changes
- Restarts the server whenever a watched file changes

To watch multiple directories:

```bash
pypnm --reload --reload-dir src --reload-dir tests
```

### HTTPS Front-End Deployment

To terminate TLS directly in PyPNM:

```bash
pypnm --host 0.0.0.0 --port 443 --ssl --cert ./certs/cert.pem --key ./certs/key.pem
```

Notes:

- This is convenient for lab setups and small deployments.
- For larger or production systems, you may prefer to terminate TLS in a reverse proxy (for example NGINX or an API gateway) and run PyPNM with plain HTTP on an internal port.

## Logging And Environment Notes

- The CLI ensures that `PYTHONPATH` includes the local `src/` directory when run from a source checkout:

  ```bash
  os.environ["PYTHONPATH"] = os.getcwd() + "/src:" + os.environ.get("PYTHONPATH", "")
  ```

  This allows the `pypnm` command to work consistently during development and in editable installs.

- Logging behavior beyond `--log-level` and `--no-access-log` is controlled by the PyPNM configuration and any logging configuration you apply in your environment. The CLI itself does not introduce additional logging flags beyond what `uvicorn` configures by default.

## Troubleshooting

- **Cannot import pypnm**  
  Confirm that you are running the `pypnm` command inside the correct virtual environment and that `pypnm-docsis` is installed:

  ```bash
  python -m pip show pypnm-docsis
  ```

- **Port already in use**  
  Another process is already bound to the selected port. Choose a different port:

  ```bash
  pypnm --port 8080
  ```

- **HTTPS fails to start**  
  Check that `--cert` and `--key` point to valid PEM files and that the private key is not password-protected, or that `uvicorn` can prompt for any necessary passphrase in your environment.

- **Reload does not trigger**  
  Confirm that:
  - `--reload` is set
  - The directories and file patterns you expect are covered by `--reload-dir` and `--reload-include`
  - Files you are editing are not excluded by `--reload-exclude`

- **High CPU usage with many workers**  
  If you specify a large `--workers` value on a small machine, Uvicorn may oversubscribe CPU cores. Start with `--workers` equal to the number of physical cores and adjust based on real measurements.

## See Also

- [PyPNM README](https://github.com/svdleer/PyPNM/blob/main/README.md)
- FastAPI application entrypoint: `pypnm.api.main:app`
