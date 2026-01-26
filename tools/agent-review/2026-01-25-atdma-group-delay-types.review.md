## Agent Review Bundle Summary
- Goal: Add a health check to post-build CI.
- Changes: Start uvicorn and curl /health after pytest.
- Files: .github/workflows/post-build.yml; .github/workflows/macos-ci.yml; README.md; install.sh; src/pypnm/pnm/analysis/atdma_group_delay.py; src/pypnm/pnm/analysis/us_drw.py; src/pypnm/pnm/data_type/DocsEqualizerData.py; src/pypnm/docsis/cm_snmp_operation.py; src/pypnm/api/routes/docs/if30/us/atdma/chan/stats/service.py; docs/api/fast-api/single/us/atdma/chan/pre-equalization.md; docs/api/fast-api/single/us/atdma/chan/stats.md; docs/api/fast-api/single/us/ofdma/stats.md; docs/api/fast-api/single/ds/ofdm/mer-margin.md; docs/api/fast-api/single/general/system-description.md; docs/install/development.md; docs/docker/install.md; docs/kubernetes/pypnm-deploy.md; docs/system/pnm-file-retrieval/tftp.md; tests/test_docs_equalizer_group_delay.py; tools/release/release.py
- Tests: Not run (not requested).
- Notes: None.

# FILE: .github/workflows/post-build.yml
name: Post Build

on:
  workflow_run:
    workflows: ["Build"]
    types: [completed]

jobs:
  downstream:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,docs]"

      - name: Build docs (gated after Build)
        run: mkdocs build --strict

      - name: Compile Python
        run: |
          python -m compileall src

      - name: Ruff Check
        run: |
          ruff check src

      - name: Ruff Format Check
        run: |
          ruff format --check .

      - name: Run Tests
        env:
          PYTHONWARNINGS: default
        run: |
          python -m pytest -q

      - name: Start PyPNM
        run: |
          python -m uvicorn pypnm.api.main:app --host 127.0.0.1 --port 8000 &
          sleep 5
          curl -fsS http://127.0.0.1:8000/health
          pkill -f "uvicorn pypnm.api.main:app"
# FILE: .github/workflows/macos-ci.yml
name: macOS CI

on:
  workflow_dispatch:
  push:
    branches:
      - "main"
      - "develop"
  pull_request:
    branches:
      - "main"
      - "develop"

permissions:
  contents: read

jobs:
  test-macos:
    name: macOS · Python ${{ matrix.python-version }}
    runs-on: macos-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set Up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Upgrade Pip Tooling
        run: |
          python -m pip install --upgrade pip setuptools wheel

      - name: Install Project
        run: |
          python -m pip install -e .
          python -m pip install -e ".[dev,docs]"

      - name: Run Tests
        env:
          PYTHONWARNINGS: default
        run: |
          python -m pytest -q

      - name: Start PyPNM
        run: |
          python -m uvicorn pypnm.api.main:app --host 127.0.0.1 --port 8000 &
          sleep 5
          curl -fsS http://127.0.0.1:8000/health
          pkill -f "uvicorn pypnm.api.main:app"

      - name: Compile Python
        run: |
          python -m compileall src

      - name: Build Docs (Strict)
        run: |
          mkdocs build --strict
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
[![macOS CI](https://github.com/PyPNMApps/PyPNM/actions/workflows/macos-ci.yml/badge.svg?branch=main)](https://github.com/PyPNMApps/PyPNM/actions/workflows/macos-ci.yml)
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
TAG="v1.0.53.0"
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
# FILE: install.sh
#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────────────────────────
# install.sh — Unified OS prerequisite installer and PyPNM bootstrapper
# Usage: ./install.sh [--demo-mode | --production] [--pnm-file-retrieval-setup] [venv_dir]
# ────────────────────────────────────────────────────────────────────────────────

VENV_DIR=".env"
DEMO_MODE="0"
PRODUCTION_MODE="0"
PNM_FILE_RETRIEVAL_SETUP="0"
DEVELOPMENT_MODE="0"
CLEAN_MODE="0"
PURGE_CACHE="0"
UNINSTALL_MODE="0"
GITLEAKS_VERSION="8.18.1"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
BANNER_PATH="${PROJECT_ROOT}/tools/banner.txt"

if [[ -f "${BANNER_PATH}" ]]; then
  cat "${BANNER_PATH}"
  echo
fi

usage() {
  cat <<EOF
PyPNM Installer And Bootstrap Script

Usage:
  ./install.sh [--demo-mode | --production] [--pnm-file-retrieval-setup] [venv_dir]
  ./install.sh --development
  ./install.sh --clean [--purge-cache]
  ./install.sh --uninstall [venv_dir]
  ./install.sh --help

Options:
  --development  Install Docker Engine + kind/kubectl + gitleaks for local dev and release workflows.
  --clean        Remove prior install artifacts (venv/build/dist/cache) before installing.
  --purge-cache  Clear pip cache after activating the venv (use with --clean when needed).
  --uninstall    Remove local install artifacts and the secrets key at ~/.ssh/pypnm_secrets.key.

  --demo-mode     Enable demo mode by backing up the default
                  src/pypnm/settings/system.json into backup/src/pypnm/settings/system.json
                  and replacing it with demo/settings/system.json. The demo system.json
                  should point all relevant directories to the demo/ tree.

  --production    Revert to production settings by restoring the backed-up
                  backup/src/pypnm/settings/system.json back to
                  src/pypnm/settings/system.json. This assumes a prior backup exists
                  (created by running with --demo-mode or a normal install).

  --pnm-file-retrieval-setup
                  After installation completes, attempt to run the interactive
                  PNM File Retrieval setup helper:

                      tools/pnm/pnm_file_retrieval_setup.py

                  This lets you choose how PyPNM retrieves PNM files:
                  local / tftp / ftp / scp / sftp / http / https.

                  For CI safety, this step is only executed when:
                    • stdin is a TTY (real terminal), and
                    • CI/GITHUB_ACTIONS are not set.
                  In CI environments, the option is acknowledged but skipped.

  venv_dir        Optional virtual environment directory name. Defaults to ".env".

  --help, -h      Show this help message and exit.

Examples:
  ./install.sh
      Create a venv in ".env" and install PyPNM with dev/docs extras.

  ./install.sh .pyenv
      Create a venv in ".pyenv" instead of ".env".

  ./install.sh --demo-mode
      Install and then switch system.json to the demo configuration
      (backing up the current system.json first).

  ./install.sh --development
      Install Docker Engine + kind/kubectl + gitleaks so release smoke tests can run.
      Tested on Ubuntu 22.04/24.04.

  ./install.sh --clean
      Remove previous install artifacts and rebuild the venv (preserves .data/ and
      src/pypnm/settings/system.json).

  ./install.sh --clean --purge-cache
      Remove previous install artifacts and clear pip cache before reinstalling.

  ./install.sh --uninstall
      Remove local install artifacts and the secrets key at ~/.ssh/pypnm_secrets.key.

  ./install.sh --demo-mode .env-demo
      Create a venv in ".env-demo" and enable demo-mode system.json.

  ./install.sh --production
      Install and then restore system.json from the backup tree, returning
      the configuration to production mode.

  ./install.sh --pnm-file-retrieval-setup
      Install and then invoke the PNM File Retrieval setup helper at the end,
      when running in an interactive, non-CI environment.

After installation, you can also configure how PyPNM retrieves PNM files
(local/TFTP/FTP/SCP/SFTP/HTTP/HTTPS) manually by running:

  ./tools/pnm/pnm_file_retrieval_setup.py
EOF
}

for arg in "$@"; do
  case "$arg" in
    --demo-mode)
      DEMO_MODE="1"
      ;;
    --production)
      PRODUCTION_MODE="1"
      ;;
    --pnm-file-retrieval-setup)
      PNM_FILE_RETRIEVAL_SETUP="1"
      ;;
    --development)
      DEVELOPMENT_MODE="1"
      ;;
    --clean)
      CLEAN_MODE="1"
      ;;
    --purge-cache)
      PURGE_CACHE="1"
      ;;
    --uninstall)
      UNINSTALL_MODE="1"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      VENV_DIR="$arg"
      ;;
  esac
done

if [[ "$UNINSTALL_MODE" == "1" ]]; then
  if [[ "$DEMO_MODE" == "1" || "$PRODUCTION_MODE" == "1" || "$PNM_FILE_RETRIEVAL_SETUP" == "1" || "$DEVELOPMENT_MODE" == "1" || "$CLEAN_MODE" == "1" || "$PURGE_CACHE" == "1" ]]; then
    echo "❌ --uninstall cannot be combined with other flags."
    usage
    exit 1
  fi
fi

if [[ "$DEMO_MODE" == "1" && "$PRODUCTION_MODE" == "1" ]]; then
  echo "❌ Cannot use --demo-mode and --production together."
  usage
  exit 1
fi

clean_previous_install() {
  echo "🧹 Cleaning previous install artifacts..."

  local remove_paths=(
    "${PROJECT_ROOT}/${VENV_DIR}"
    "${PROJECT_ROOT}/build"
    "${PROJECT_ROOT}/dist"
    "${PROJECT_ROOT}/.pytest_cache"
    "${PROJECT_ROOT}/.ruff_cache"
    "${PROJECT_ROOT}/.mypy_cache"
    "${PROJECT_ROOT}/.pyright"
    "${PROJECT_ROOT}/.coverage"
    "${PROJECT_ROOT}/htmlcov"
    "${PROJECT_ROOT}/test_reports"
  )

  for path in "${remove_paths[@]}"; do
    if [[ -e "${path}" ]]; then
      echo "🗑️  Removing ${path}"
      rm -rf "${path}"
    fi
  done

  find "${PROJECT_ROOT}" -maxdepth 2 -name "*.egg-info" -type d -print0 | while IFS= read -r -d '' item; do
    echo "🗑️  Removing ${item}"
    rm -rf "${item}"
  done

  echo "ℹ️  Preserving ${PROJECT_ROOT}/.data and ${PROJECT_ROOT}/src/pypnm/settings/system.json"
}

install_gitleaks() {
  if command -v gitleaks >/dev/null 2>&1; then
    echo "✅ gitleaks already installed."
    return
  fi

  if [[ "$PM" == "none" ]]; then
    echo "⚠️  gitleaks not found and no package manager available."
    echo "    Install manually: https://github.com/gitleaks/gitleaks"
    return
  fi

  echo "🔧 Installing gitleaks..."
  case "$PM" in
    apt-get) $PM_INSTALL gitleaks || true ;;
    dnf|yum) $PM_INSTALL gitleaks || true ;;
    zypper)  $PM_INSTALL gitleaks || true ;;
    apk)     $PM_INSTALL gitleaks || true ;;
    brew)    $PM_INSTALL gitleaks || true ;;
    *)
      echo "⚠️  Unknown package manager; install gitleaks manually."
      echo "    https://github.com/gitleaks/gitleaks"
      return
      ;;
  esac

  if ! command -v gitleaks >/dev/null 2>&1; then
    if ! command -v curl >/dev/null 2>&1; then
      echo "⚠️  gitleaks install did not complete (curl missing)."
      echo "    Install manually: https://github.com/gitleaks/gitleaks"
      return
    fi
    if ! command -v tar >/dev/null 2>&1; then
      echo "⚠️  gitleaks install did not complete (tar missing)."
      echo "    Install manually: https://github.com/gitleaks/gitleaks"
      return
    fi

    local os arch filename url tmp_dir target_dir bin_path
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    case "$os" in
      linux|darwin) ;;
      *)
        echo "⚠️  Unsupported OS for gitleaks auto-install: ${os}"
        echo "    Install manually: https://github.com/gitleaks/gitleaks"
        return
        ;;
    esac

    arch="$(uname -m)"
    case "$arch" in
      x86_64|amd64) arch="x64" ;;
      aarch64|arm64) arch="arm64" ;;
      *)
        echo "⚠️  Unsupported architecture for gitleaks auto-install: ${arch}"
        echo "    Install manually: https://github.com/gitleaks/gitleaks"
        return
        ;;
    esac

    filename="gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
    url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${filename}"
    tmp_dir="$(mktemp -d)"
    echo "⬇️  Downloading gitleaks ${GITLEAKS_VERSION}..."
    if ! curl -fsSL "${url}" -o "${tmp_dir}/${filename}"; then
      echo "⚠️  Failed to download gitleaks from ${url}"
      echo "    Install manually: https://github.com/gitleaks/gitleaks"
      rm -rf "${tmp_dir}"
      return
    fi

    if ! tar -xzf "${tmp_dir}/${filename}" -C "${tmp_dir}"; then
      echo "⚠️  Failed to extract gitleaks archive."
      echo "    Install manually: https://github.com/gitleaks/gitleaks"
      rm -rf "${tmp_dir}"
      return
    fi

    bin_path="${tmp_dir}/gitleaks"
    if [[ ! -f "${bin_path}" ]]; then
      echo "⚠️  gitleaks binary not found after extraction."
      echo "    Install manually: https://github.com/gitleaks/gitleaks"
      rm -rf "${tmp_dir}"
      return
    fi

    target_dir="/usr/local/bin"
    if [[ -w "${target_dir}" ]]; then
      install -m 0755 "${bin_path}" "${target_dir}/gitleaks"
    elif command -v sudo >/dev/null 2>&1; then
      sudo install -m 0755 "${bin_path}" "${target_dir}/gitleaks"
    else
      target_dir="${HOME}/.local/bin"
      mkdir -p "${target_dir}"
      install -m 0755 "${bin_path}" "${target_dir}/gitleaks"
      echo "ℹ️  Added gitleaks to ${target_dir}; ensure it's on PATH."
    fi

    rm -rf "${tmp_dir}"
    if ! command -v gitleaks >/dev/null 2>&1; then
      echo "⚠️  gitleaks install did not complete."
      echo "    Install manually: https://github.com/gitleaks/gitleaks"
      return
    fi
  fi
}

remove_secrets_key() {
  local secrets_key_path
  secrets_key_path="${HOME}/.ssh/pypnm_secrets.key"

  if [[ -f "${secrets_key_path}" ]]; then
    echo "🗑️  Removing ${secrets_key_path}"
    rm -f "${secrets_key_path}"
  else
    echo "ℹ️  Secret key not found at ${secrets_key_path}"
  fi
}

uninstall_pypnm() {
  echo "🧹 Uninstalling PyPNM artifacts..."
  clean_previous_install
  remove_secrets_key
  echo "✅ Uninstall complete."
}

if [[ "$UNINSTALL_MODE" == "1" ]]; then
  uninstall_pypnm
  exit 0
fi

backup_system_settings() {
  echo "🗂  Creating backup of system settings…"
  local backup_root
  backup_root="${PROJECT_ROOT}/backup"
  local src_path
  src_path="${PROJECT_ROOT}/src/pypnm/settings/system.json"
  local dst_path
  dst_path="${backup_root}/src/pypnm/settings/system.json"

  if [[ ! -f "$src_path" ]]; then
    echo "⚠️  System settings file not found at '$src_path'; skipping backup."
    return
  fi

  mkdir -p "$(dirname "$dst_path")"
  cp "$src_path" "$dst_path"
  echo "✅ Backup created at '$dst_path'."
}

restore_system_settings() {
  echo "🗂  Restoring system settings from backup…"
  local backup_root
  backup_root="${PROJECT_ROOT}/backup"
  local backup_path
  backup_path="${backup_root}/src/pypnm/settings/system.json"
  local target
  target="${PROJECT_ROOT}/src/pypnm/settings/system.json"

  if [[ ! -f "$backup_path" ]]; then
    echo "⚠️  Backup system settings not found at '$backup_path'; cannot restore."
    return
  fi

  mkdir -p "$(dirname "$target")"
  cp "$backup_path" "$target"
  echo "✅ System settings restored from backup to '$target'."
}

enable_demo_mode() {
  echo "🎛  Enabling demo mode configuration…"
  local demo_src
  demo_src="${PROJECT_ROOT}/demo/settings/system.json"
  local target
  target="${PROJECT_ROOT}/src/pypnm/settings/system.json"

  if [[ ! -f "$demo_src" ]]; then
    echo "⚠️  Demo settings file not found at '$demo_src'; skipping demo mode."
    return
  fi

  if [[ -f "$target" ]]; then
    echo "ℹ️  Overwriting existing system settings at '$target' with demo template."
  else
    echo "ℹ️  Creating system settings at '$target' from demo template."
  fi

  mkdir -p "$(dirname "$target")"
  cp "$demo_src" "$target"
  echo "✅ Demo mode system settings applied (directories now point to demo/)."
}

echo "🔍 Detecting package manager..."
PM="none"; PM_UPDATE=""; PM_INSTALL=""
if command -v apt-get >/dev/null 2>&1; then
  PM="apt-get"; PM_UPDATE="sudo apt-get update"; PM_INSTALL="sudo apt-get install -y"
  echo "ℹ️  Debian/Ubuntu (apt-get)"
elif command -v dnf >/dev/null 2>&1; then
  PM="dnf"; PM_UPDATE="sudo dnf makecache"; PM_INSTALL="sudo dnf install -y"
  echo "ℹ️  Fedora/RHEL (dnf)"
elif command -v yum >/dev/null 2>&1; then
  PM="yum"; PM_UPDATE="sudo yum makecache"; PM_INSTALL="sudo yum install -y"
  echo "ℹ️  RHEL/CentOS (yum)"
elif command -v zypper >/dev/null 2>&1; then
  PM="zypper"; PM_UPDATE="sudo zypper refresh"; PM_INSTALL="sudo zypper install -y"
  echo "ℹ️  SUSE/openSUSE (zypper)"
elif command -v apk >/dev/null 2>&1; then
  PM="apk"; PM_UPDATE=""; PM_INSTALL="sudo apk add --no-cache"
  echo "ℹ️  Alpine (apk)"
elif command -v brew >/dev/null 2>&1; then
  PM="brew"; PM_UPDATE="brew update"; PM_INSTALL="brew install"
  echo "ℹ️  macOS (brew)"
else
  echo "⚠️  Unsupported OS: please manually install 'ssh', 'sshpass', and Python venv support."
fi

if [[ "$PM" != "none" && -n "${PM_UPDATE:-}" ]]; then
  echo "🔄 Updating package cache..."
  $PM_UPDATE || true
fi

echo "✅ Installing OS prerequisites..."
if ! command -v ssh >/dev/null 2>&1; then
  if [[ "$PM" == "none" ]]; then
    echo "⚠️  No package manager; cannot auto-install 'ssh'."
  else
    echo "🔧 Installing ssh..."
    case "$PM" in
      apt-get) $PM_INSTALL openssh-client ;;
      dnf|yum) $PM_INSTALL openssh-clients ;;
      zypper)  $PM_INSTALL openssh ;;
      apk)     $PM_INSTALL openssh ;;
      brew)    $PM_INSTALL openssh ;;
    esac
  fi
fi

if ! command -v sshpass >/dev/null 2>&1; then
  if [[ "$PM" == "none" ]]; then
    echo "⚠️  No package manager; cannot auto-install 'sshpass'."
  else
    echo "🔧 Installing sshpass..."
    $PM_INSTALL sshpass || true
  fi
fi

echo "🧮 Ensuring SciPy/NumPy build prerequisites (where applicable)..."
case "$PM" in
  apt-get)
    $PM_INSTALL build-essential gfortran libopenblas-dev liblapack-dev || true
    ;;
  dnf|yum)
    $PM_INSTALL gcc gcc-c++ make blas-devel lapack-devel || true
    ;;
  zypper)
    $PM_INSTALL gcc gcc-c++ make libopenblas-devel lapack-devel || true
    ;;
  apk)
    $PM_INSTALL build-base gfortran openblas-dev lapack-dev || true
    ;;
  brew)
    # Homebrew wheels usually bundle BLAS/LAPACK; nothing extra required in most cases.
    :
    ;;
  *)
    echo "⚠️  Skipping SciPy/NumPy build prerequisites for unknown or manual PM."
    ;;
esac

if [[ "$DEVELOPMENT_MODE" == "1" ]]; then
  echo "🧰 Development setup: Docker + kind/kubectl + gitleaks..."
  if [[ "$PM" == "brew" ]]; then
    echo "⚠️  macOS does not support the Docker/kind bootstrap in this script."
    echo "    Skipping Docker/kind install; running gitleaks setup only."
    install_gitleaks
  else
  if ! command -v curl >/dev/null 2>&1; then
    if [[ "$PM" == "none" ]]; then
      echo "❌ curl not found and no package manager available."
      exit 1
    fi
    echo "🔧 Installing curl..."
    case "$PM" in
      apt-get) $PM_INSTALL curl ;;
      dnf|yum) $PM_INSTALL curl ;;
      zypper)  $PM_INSTALL curl ;;
      apk)     $PM_INSTALL curl ;;
      brew)    $PM_INSTALL curl ;;
    esac
  fi

  if [[ "$PM" == "apt-get" ]]; then
    bash "${PROJECT_ROOT}/tools/docker/install-docker-ubuntu.sh"
  else
    echo "⚠️  --development is tested on Ubuntu 22.04/24.04; continuing with kind/kubectl install."
    echo "    Install Docker manually for your OS, then re-run if needed."
  fi

  bash "${PROJECT_ROOT}/tools/k8s/pypnm_kind_vm_bootstrap.sh"
  install_gitleaks
  echo "ℹ️  Docker may require: sudo systemctl start docker"
  echo "ℹ️  For non-sudo Docker: sudo usermod -aG docker \"${USER}\" (then log out/in)"
  fi
fi

if ! command -v python3 >/dev/null 2>&1; then
  if [[ "$PM" == "none" ]]; then
    echo "❌ Python 3.x not found in PATH."
    exit 1
  fi
  echo "🔧 Installing Python 3..."
  case "$PM" in
    apt-get) $PM_INSTALL python3 ;;
    dnf|yum) $PM_INSTALL python3 ;;
    zypper)  $PM_INSTALL python3 ;;
    apk)     $PM_INSTALL python3 ;;
    brew)    $PM_INSTALL python ;;
  esac
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "3")"
PYTHON_CMD="python${PYTHON_VERSION}"
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
  else
    echo "❌ Python 3.x not found in PATH."
    exit 1
  fi
fi

echo "🔧 Ensuring venv support is available..."
case "$PM" in
  apt-get) $PM_INSTALL "python${PYTHON_VERSION}-venv" || true ;;
  dnf|yum) $PM_INSTALL python3-virtualenv || true ;;
  zypper)  $PM_INSTALL python3-virtualenv || true ;;
  apk)     $PM_INSTALL python3 || true ;;
  brew)    $PM_INSTALL python || true ;;
  *)       echo "⚠️  Skipping venv package install for unknown PM." ;;
esac

if [[ "$CLEAN_MODE" == "1" ]]; then
  clean_previous_install
fi

echo "🛠  Creating virtual environment in '$VENV_DIR'…"
"$PYTHON_CMD" -m venv "$VENV_DIR"

echo "🚀 Activating '$VENV_DIR'…"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "⬆️  Upgrading pip, setuptools, wheel…"
pip install --upgrade pip setuptools wheel

if [[ "$PURGE_CACHE" == "1" ]]; then
  echo "🧽 Purging pip cache..."
  pip cache purge || true
fi

echo "📥 Installing PyPNM extras: dev + docs…"
pip install -e "${PROJECT_ROOT}[dev,docs]"

echo "📦 Installing required tooling: pytest, mkdocs, mkdocs-material, cryptography…"
pip install "pytest>=7" "mkdocs>=1.6" "mkdocs-material>=9.5" "cryptography>=41"

echo "🔎 Verifying MkDocs install…"
mkdocs --version

echo "🔧 Configuring PYTHONPATH…"
"$PROJECT_ROOT/scripts/install_py_path.sh" "$PROJECT_ROOT" || true

echo "🔐 Ensuring PyPNM secret key exists (~/.ssh/pypnm_secrets.key)…"
if [[ -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
  echo "ℹ️  Skipping secret key creation (CI environment)."
  echo "    Create it locally with:"
  echo "      ./scripts/init_secrets_key.sh"
else
  if [[ -x "${PROJECT_ROOT}/scripts/init_secrets_key.sh" ]]; then
    "${PROJECT_ROOT}/scripts/init_secrets_key.sh" --quiet || true
  else
    echo "ℹ️  scripts/init_secrets_key.sh is missing or not executable; skipping."
  fi
fi

echo "🧪 Running unit tests…"
cd "$PROJECT_ROOT"
pytest -v

if [[ "$PRODUCTION_MODE" == "1" ]]; then
  restore_system_settings
elif [[ "$DEMO_MODE" == "1" ]]; then
  backup_system_settings
  enable_demo_mode
else
  backup_system_settings
fi

###############################################################################
# Optional: PNM File Retrieval Setup (CI-Safe)
#
# Behavior:
#   - If --pnm-file-retrieval-setup was passed:
#       • Attempt to run tools/pnm/pnm_file_retrieval_setup.py automatically
#         when in an interactive, non-CI environment.
#       • If in CI or non-TTY, print a message and skip.
#
#   - If the flag was NOT passed:
#       • Do NOT prompt interactively.
#       • Just print a short message about the manual helper.
###############################################################################
run_pnm_setup_if_possible() {
  if [[ ! -t 0 || -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
    echo "ℹ️  Skipping PNM file retrieval setup (non-interactive or CI environment)."
    echo "    You can run it later with:"
    echo "      ./tools/pnm/pnm_file_retrieval_setup.py"
    return
  fi

  if [[ -x "./tools/pnm/pnm_file_retrieval_setup.py" ]]; then
    echo
    echo "Launching PNM file retrieval setup..."
    ./tools/pnm/pnm_file_retrieval_setup.py
  else
    echo "tools/pnm/pnm_file_retrieval_setup.py is missing or not executable."
    echo "You can run it manually later once it is available:"
    echo "  ./tools/pnm/pnm_file_retrieval_setup.py"
  fi
}

run_pnm_alias_installer_if_available() {
  if [[ -x "${PROJECT_ROOT}/scripts/install_aliases.sh" ]]; then
    echo "🔗 Installing PyPNM shell aliases (e.g., config-menu)…"
    "${PROJECT_ROOT}/scripts/install_aliases.sh" || true
  fi
}

if [[ "$PNM_FILE_RETRIEVAL_SETUP" == "1" ]]; then
  echo
  echo "PNM File Retrieval Configuration (requested via --pnm-file-retrieval-setup)"
  run_pnm_setup_if_possible
else
  echo
  echo "ℹ️  PNM file retrieval setup was not requested."
  echo "    You can configure it later with:"
  echo "      ./tools/pnm/pnm_file_retrieval_setup.py"
fi

run_pnm_alias_installer_if_available

echo "✅ Bootstrap complete."
if [[ "$DEMO_MODE" == "1" ]]; then
  echo "👉 Demo mode is enabled: system settings now reference the demo/ directories."
fi
if [[ "$PRODUCTION_MODE" == "1" ]]; then
  echo "👉 Production mode is restored: system settings have been reverted from backup."
fi
echo "👉 Next steps:"
echo "   1) source '$VENV_DIR/bin/activate'"
echo "   2) (optional) ./tools/pnm/pnm_file_retrieval_setup.py"
echo "   3) mkdocs serve"
# FILE: src/pypnm/pnm/analysis/atdma_group_delay.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from pypnm.lib.constants import DOCSIS_ROLL_OFF_FACTOR
from pypnm.lib.types import (
    BandwidthHz,
    FloatSeries,
    Microseconds,
    PreEqAtdmaCoefficients,
)

MIN_CHANNEL_WIDTH_HZ: BandwidthHz = BandwidthHz(0)
MIN_TAPS_PER_SYMBOL: int = 0
MIN_ROLLOFF: float = 0.0
ONE: float = 1.0
TWO_PI: float = 2.0 * math.pi
MICROSECONDS_PER_SECOND: float = 1_000_000.0


class GroupDelayModel(BaseModel):
    """Immutable ATDMA group delay results derived from pre-equalization taps.

    Stores derived timing and delay series used for analysis and reporting.
    """

    channel_width_hz: BandwidthHz   = Field(..., description="ATDMA channel width in Hz.")
    rolloff: float                  = Field(..., description=f"RRC roll-off factor α (typical DOCSIS = {DOCSIS_ROLL_OFF_FACTOR}).")
    taps_per_symbol: int            = Field(..., description="Taps per symbol from the pre-EQ header.")
    symbol_rate: float              = Field(..., description="Derived symbol rate (sym/s): BW / (1 + rolloff).")
    symbol_time_us: Microseconds    = Field(..., description="Derived symbol time in microseconds (µs): 1/symbol_rate.")
    sample_period_us: Microseconds  = Field(..., description="Sample period in microseconds (µs): Tsym / taps_per_symbol.")
    fft_size: int                   = Field(..., description="FFT size used to evaluate the frequency response (N taps).")
    delay_samples: FloatSeries      = Field(..., description="Group delay in samples per FFT bin (tap-period units).")
    delay_us: FloatSeries           = Field(..., description="Group delay in microseconds per FFT bin.")
    model_config = {"frozen": True}


@dataclass(frozen=True, slots=True)
class GroupDelayCalculator:
    """Compute ATDMA group delay from upstream pre-equalization coefficients.

    This calculator derives **group delay** (the negative slope of the unwrapped
    phase response) from a 24-tap ATDMA upstream FIR equalizer. The input taps are
    complex coefficients (real, imag) taken from `docsIf3CmStatusUsEqData.*`
    after decoding to signed integers (your existing `DocsEqualizerData` class
    already handles endianness + 12/16-bit interpretation and yields taps).

    Conceptually, the equalizer taps represent a discrete-time FIR filter:

        h[n] = re[n] + j·im[n]    for n = 0..N-1

    The processing steps are:

    1) **Time → Frequency conversion**
       Compute the N-point FFT to obtain the complex frequency response:

           H[k] = FFT{ h[n] } ,  k = 0..N-1

    2) **Phase extraction and unwrap**
       Extract the phase angle of each bin and unwrap it to remove 2π discontinuities:

           φ[k] = unwrap(angle(H[k]))

    3) **Group delay in samples**
       Group delay is defined as:

           τ(ω) = - dφ(ω) / dω

       With FFT bins, ω[k] = 2π·k/N. We approximate the derivative numerically,
       resulting in group delay measured in **tap-sample periods** (i.e., "samples").

    4) **Convert delay from samples → microseconds**
       To express delay in time units, we need the tap sample period.

       For DOCSIS ATDMA upstream channels, symbol rate is typically derived from
       channel width and roll-off (root-raised cosine shaping):

           Rs = BW / (1 + α)

       Then:

           Tsym = 1 / Rs
           Tsamp = Tsym / taps_per_symbol

       Finally:

           delay_us[k] = delay_samples[k] · Tsamp(µs)

    Notes and expectations:

    - This class does **not** assume the main tap location is centered; it reports
      the group delay implied by the taps as provided.
    - The FFT size is set to **N = number of taps** by default. If you later want
      a smoother curve, you can zero-pad (e.g., 128/256 points) without changing
      the underlying physics—only the sampling density in frequency.
    - `taps_per_symbol` comes from the pre-EQ header byte (often 1).
    - `channel_width_hz` must be provided to compute absolute time units (µs).
      Without it, you can still compute delay in samples, but not in seconds.

    Attributes:
        channel_width_hz: ATDMA upstream channel width in Hz (e.g., 1_600_000).
        taps_per_symbol: Tap sampling density per symbol from the pre-EQ header.
                         Used to convert symbol time to tap-sample time.
        rolloff: DOCSIS shaping roll-off factor α. Typical default is 0.25.

    Returns:
        A `GroupDelayModel` containing:
        - derived symbol rate/time and sample period
        - group delay arrays per FFT bin in samples and microseconds
    """

    channel_width_hz: BandwidthHz
    taps_per_symbol: int
    rolloff: float = DOCSIS_ROLL_OFF_FACTOR

    def __post_init__(self) -> None:
        if int(self.channel_width_hz) <= MIN_CHANNEL_WIDTH_HZ:
            raise ValueError("channel_width_hz must be > 0.")
        if self.taps_per_symbol <= MIN_TAPS_PER_SYMBOL:
            raise ValueError("taps_per_symbol must be > 0.")
        if not math.isfinite(self.rolloff):
            raise ValueError("rolloff must be finite.")
        if self.rolloff < MIN_ROLLOFF:
            raise ValueError("rolloff must be >= 0.")

    @staticmethod
    def _to_complex_array(coefficients: list[PreEqAtdmaCoefficients]) -> NDArray[np.complex128]:
        taps: NDArray[np.complex128] = np.empty(len(coefficients), dtype=np.complex128)
        for i, (re, im) in enumerate(coefficients):
            taps[i] = complex(float(re), float(im))
        return taps

    def symbol_rate(self) -> float:
        bw = float(int(self.channel_width_hz))
        return bw / (ONE + self.rolloff)

    def symbol_time_us(self) -> Microseconds:
        sr = self.symbol_rate()
        ts = ONE / sr
        return Microseconds(ts * MICROSECONDS_PER_SECOND)

    def sample_period_us(self) -> Microseconds:
        tsym_us = float(self.symbol_time_us())
        return Microseconds(tsym_us / float(self.taps_per_symbol))

    def compute(self, coefficients: list[PreEqAtdmaCoefficients]) -> GroupDelayModel:
        if len(coefficients) == 0:
            raise ValueError("coefficients cannot be empty.")

        h_time = self._to_complex_array(coefficients)

        n = int(h_time.shape[0])
        h_freq = np.fft.fft(h_time, n=n)

        phase = np.unwrap(np.angle(h_freq))
        omega = TWO_PI * (np.arange(n, dtype=np.float64) / float(n))

        dphi_domega = np.gradient(phase, omega)
        delay_samples = -dphi_domega

        tsamp_us = float(self.sample_period_us())
        delay_us = delay_samples * tsamp_us

        delay_samples_list: FloatSeries = [float(x) for x in delay_samples.tolist()]
        delay_us_list: FloatSeries      = [float(x) for x in delay_us.tolist()]

        sr = self.symbol_rate()
        tsym_us = float(self.symbol_time_us())
        tsamp = float(self.sample_period_us())

        return GroupDelayModel(
            channel_width_hz    =   BandwidthHz(int(self.channel_width_hz)),
            rolloff             =   float(self.rolloff),
            taps_per_symbol     =   int(self.taps_per_symbol),
            symbol_rate         =   float(sr),
            symbol_time_us      =   Microseconds(tsym_us),
            sample_period_us    =   Microseconds(tsamp),
            fft_size            =   int(n),
            delay_samples       =   delay_samples_list,
            delay_us            =   delay_us_list,
        )
# FILE: src/pypnm/pnm/analysis/us_drw.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from pydantic import BaseModel, Field

from pypnm.lib.types import ChannelId, PowerdB, PowerdBmV


class DwrChannelPowerModel(BaseModel):
    channel_id: ChannelId = Field(..., description="DOCSIS upstream channel ID.")
    tx_power_dbmv: PowerdBmV = Field(..., description="Upstream transmit power in dBmV.")

    model_config = {"frozen": True}


class DwrWindowCheckModel(BaseModel):
    dwr_warning_db: PowerdB = Field(..., description="Warning threshold for DWR spread (dB).")
    dwr_violation_db: PowerdB = Field(..., description="Violation threshold for DWR spread (dB).")
    channel_count: int = Field(..., description="Number of channels evaluated.")

    min_power_dbmv: PowerdBmV = Field(..., description="Minimum TX power across channels (dBmV).")
    max_power_dbmv: PowerdBmV = Field(..., description="Maximum TX power across channels (dBmV).")
    spread_db: PowerdB = Field(..., description="Power spread across channels (max-min) in dB.")

    is_warning: bool = Field(..., description="True when warning_db < spread_db <= violation_db.")
    is_violation: bool = Field(..., description="True when spread_db > violation_db.")
    extreme_channel_ids: list[ChannelId] = Field(
        ...,
        description="Channels at the extremes (min/max) that define the spread.",
    )

    model_config = {"frozen": True}


@dataclass(frozen=True, slots=True, init=False)
class DwrDynamicWindowRangeChecker:
    """
    Check DOCSIS ATDMA Upstream Transmit-Power Dynamic Window Range (DWR) compliance.

    What This Checker Does
    - Evaluates whether a set of upstream ATDMA channels (N >= 2) are “clustered” in transmit power
      tightly enough to satisfy a configured DWR window.
    - The check is performed using the simplest deterministic rule: the *min/max spread*.

    Inputs
    - Each channel contributes a single transmit power sample p_i (in dBmV).

    Core Math (Min/Max Spread Rule)
    - For powers p_i across N channels:
        p_min     = min(p_i)
        p_max     = max(p_i)
        spread_db = p_max - p_min
      The DWR constraint is satisfied when:
        spread_db <= W
      and is a violation when:
        spread_db > W

    Thresholding With Warning + Violation Triggers
    - Two thresholds are evaluated independently:
      - W_warning:
          If spread_db > W_warning but spread_db <= W_violation then the condition is a WARNING.
      - W_violation:
          If spread_db > W_violation then the condition is a HARD violation.
      - Otherwise:
          spread_db <= W_warning is considered OK.

      Example (defaults):
      - W_warning = 6.0 dB, W_violation = 12.0 dB
        * spread_db <= 6.0 dB                -> OK
        * 6.0 dB < spread_db <= 12.0 dB      -> WARNING
        * spread_db > 12.0 dB                -> VIOLATION

    Output Field Meanings (DwrWindowCheckModel)
    - channel_count:
        Number of channels included in the evaluation.

    - min_power_dbmv / max_power_dbmv:
        The smallest and largest transmit powers observed across the channels (in dBmV).

    - spread_db:
        The computed power spread across channels:
            spread_db = max_power_dbmv - min_power_dbmv

    - extreme_channel_ids (or violating_channel_ids, depending on your model naming):
        Channel IDs at the power extremes that *define* the spread.
        Specifically:
        - All channel IDs whose tx_power_dbmv == min_power_dbmv
        - All channel IDs whose tx_power_dbmv == max_power_dbmv
        Notes:
        - If multiple channels tie for the minimum or maximum, all tied IDs are included.
        - These IDs are useful for pinpointing which channels anchor the DWR spread.

    - is_warning / is_violation:
        Booleans indicating the threshold state based on the trigger tuple.
        (You may choose a single enum-like status instead; the meaning is the same.)

    Notes / Scope
    - This checker implements the min/max spread rule only.
    - A “± window around a reference” (mean/median/anchor channel) is a different policy
      and should be implemented as a separate evaluation mode to avoid ambiguity.
    """

    dwr_warning_db: PowerdB
    dwr_violation_db: PowerdB

    MIN_CHANNELS: ClassVar[Final[int]] = 2
    DEFAULT_WARNING_DB: ClassVar[Final[PowerdB]] = PowerdB(6.0)
    DEFAULT_VIOLATION_DB: ClassVar[Final[PowerdB]] = PowerdB(12.0)

    def __init__(
        self,
        *,
        dwr_violation_db: PowerdB = DEFAULT_VIOLATION_DB,
        dwr_warning_db: PowerdB = DEFAULT_WARNING_DB,
    ) -> None:
        """
        Initialize a DWR checker with explicit thresholds.

        Args:
            dwr_violation_db: Violation threshold in dB. Default 12.0 dB.
            dwr_warning_db: Warning threshold in dB. Default 6.0 dB.

        Raises:
            ValueError: When dwr_warning_db > dwr_violation_db.
        """
        warn = float(dwr_warning_db)
        violation = float(dwr_violation_db)

        if warn > violation:
            raise ValueError("dwr_warning_db must be <= dwr_violation_db.")

        object.__setattr__(self, "dwr_warning_db", PowerdB(warn))
        object.__setattr__(self, "dwr_violation_db", PowerdB(violation))

    def evaluate(self, channels: list[DwrChannelPowerModel]) -> DwrWindowCheckModel:
        """
        Evaluate DWR compliance over a set of upstream channel powers.

        Args:
            channels: Channel power samples used to compute the min/max spread.

        Returns:
            DwrWindowCheckModel with spread, bounds, warning/violation status, and extreme channel IDs.
        """
        if len(channels) < self.MIN_CHANNELS:
            raise ValueError(f"Need at least {self.MIN_CHANNELS} channels to evaluate DWR.")

        samples: list[tuple[ChannelId, float]] = [(c.channel_id, float(c.tx_power_dbmv)) for c in channels]
        powers = [p for _, p in samples]

        p_min = min(powers)
        p_max = max(powers)
        spread = p_max - p_min

        min_ids = [cid for cid, p in samples if p == p_min]
        max_ids = [cid for cid, p in samples if p == p_max]

        extreme_ids: list[ChannelId] = []
        extreme_ids.extend(min_ids)
        for cid in max_ids:
            if cid not in extreme_ids:
                extreme_ids.append(cid)

        is_violation = spread > float(self.dwr_violation_db)
        is_warning = (spread > float(self.dwr_warning_db)) and (not is_violation)

        return DwrWindowCheckModel(
            dwr_warning_db=self.dwr_warning_db,
            dwr_violation_db=self.dwr_violation_db,
            channel_count=len(channels),
            min_power_dbmv=PowerdBmV(p_min),
            max_power_dbmv=PowerdBmV(p_max),
            spread_db=PowerdB(spread),
            is_warning=is_warning,
            is_violation=is_violation,
            extreme_channel_ids=extreme_ids,
        )
# FILE: src/pypnm/pnm/data_type/DocsEqualizerData.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

import json
import math
from typing import Final, Literal

from pydantic import BaseModel, Field

from pypnm.lib.constants import DOCSIS_ROLL_OFF_FACTOR
from pypnm.lib.types import BandwidthHz, ImginaryInt, PreEqAtdmaCoefficients, RealInt
from pypnm.pnm.analysis.atdma_group_delay import GroupDelayCalculator, GroupDelayModel
from pypnm.pnm.analysis.atdma_preeq_key_metrics import (
    EqualizerMetrics,
    EqualizerMetricsModel,
)


class UsEqTapModel(BaseModel):
    real: int = Field(..., description="Tap real coefficient decoded as 2's complement.")
    imag: int = Field(..., description="Tap imag coefficient decoded as 2's complement.")
    magnitude: float = Field(..., description="Magnitude computed from real/imag.")
    magnitude_power_dB: float | None = Field(..., description="Magnitude power in dB (10*log10(mag^2)); None when magnitude is 0.")
    real_hex: str = Field(..., description="Raw 2-byte real coefficient as received, shown as 4 hex chars.")
    imag_hex: str = Field(..., description="Raw 2-byte imag coefficient as received, shown as 4 hex chars.")

    model_config = {"frozen": True}


class UsEqDataModel(BaseModel):
    main_tap_location: int = Field(..., description="Main tap location (header byte 0; HEX value).")
    taps_per_symbol: int = Field(..., description="Taps per symbol (header byte 1; HEX value).")
    num_taps: int = Field(..., description="Number of taps (header byte 2; HEX value).")
    reserved: int = Field(..., description="Reserved (header byte 3; HEX value).")
    header_hex: str = Field(..., description="Header bytes as hex (4 bytes).")
    payload_hex: str = Field(..., description="Full payload as hex (space-separated bytes).")
    payload_preview_hex: str = Field(..., description="Header + first N taps as hex preview (space-separated bytes).")
    taps: list[UsEqTapModel] = Field(..., description="Decoded taps in order (real/imag pairs).")
    metrics: EqualizerMetricsModel | None = Field(None, description="ATDMA pre-equalization key metrics when available.")
    group_delay: GroupDelayModel | None = Field(None, description="ATDMA group delay derived from taps when channel_width_hz is provided.")

    model_config = {"frozen": True}


class DocsEqualizerData:
    """
    Parse DOCS-IF3 upstream pre-equalization tap data.

    Notes:
    - CM deployments have two common coefficient interpretations:
      * four-nibble 2's complement (16-bit signed)
      * three-nibble 2's complement (12-bit signed; upper nibble unused)
    - Some deployments can be handled with a "universal" decoder: drop the first nibble and decode as 12-bit.

    IMPORTANT:
    - Pass raw SNMP OctetString bytes via add_from_bytes() whenever possible.
    - If you pass a hex string, it must be real hex (e.g., 'FF FC 00 04 ...'), not a Unicode pretty string.
    """

    HEADER_SIZE: Final[int] = 4
    COEFF_BYTES: Final[int] = 2
    COMPLEX_TAP_SIZE: Final[int] = 4
    MAX_TAPS: Final[int] = 64

    U16_MASK: Final[int] = 0xFFFF
    U12_MASK: Final[int] = 0x0FFF
    U16_MSN_MASK: Final[int] = 0xF000

    I16_SIGN: Final[int] = 0x8000
    I12_SIGN: Final[int] = 0x0800
    I16_RANGE: Final[int] = 0x10000
    I12_RANGE: Final[int] = 0x1000

    AUTO_ENDIAN_SAMPLE_MAX_TAPS: Final[int] = 16
    AUTO_ENDIAN_BYTE_GOOD_0: Final[int] = 0x00
    AUTO_ENDIAN_BYTE_GOOD_FF: Final[int] = 0xFF

    def __init__(self) -> None:
        self._coefficients_found: bool = False
        self.equalizer_data: dict[int, UsEqDataModel] = {}

    def add(
        self,
        us_idx: int,
        payload_hex: str,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"] = "auto",
        coeff_endianness: Literal["little", "big", "auto"] = "auto",
        preview_taps: int = 8,
        channel_width_hz: BandwidthHz | None = None,
        rolloff: float = DOCSIS_ROLL_OFF_FACTOR,
    ) -> bool:
        """
        Parse/store from a hex string payload.

        payload_hex MUST be actual hex bytes (e.g., 'FF FC 00 04 ...').
        If payload_hex contains non-hex characters (like 'ÿ'), this will return False.

        coeff_encoding:
        - four-nibble: decode as signed 16-bit (2's complement)
        - three-nibble: decode as signed 12-bit (2's complement) after masking to 0x0FFF
        - auto: prefer 16-bit when the upper nibble is used; otherwise decode as 12-bit ("universal" behavior)

        coeff_endianness:
        - little: interpret each 2-byte coefficient as little-endian
        - big: interpret each 2-byte coefficient as big-endian
        - auto: heuristic selection based on common small-coefficient patterns
        """
        try:
            payload = self._hex_to_bytes_strict(payload_hex)
            return self._add_parsed(
                us_idx,
                payload,
                coeff_encoding=coeff_encoding,
                coeff_endianness=coeff_endianness,
                preview_taps=preview_taps,
                channel_width_hz=channel_width_hz,
                rolloff=rolloff,
            )
        except Exception:
            return False

    def add_from_bytes(
        self,
        us_idx: int,
        payload: bytes,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"] = "auto",
        coeff_endianness: Literal["little", "big", "auto"] = "auto",
        preview_taps: int = 8,
        channel_width_hz: BandwidthHz | None = None,
        rolloff: float = DOCSIS_ROLL_OFF_FACTOR,
    ) -> bool:
        """
        Parse/store from raw bytes (preferred for SNMP OctetString values).
        """
        try:
            return self._add_parsed(
                us_idx,
                payload,
                coeff_encoding=coeff_encoding,
                coeff_endianness=coeff_endianness,
                preview_taps=preview_taps,
                channel_width_hz=channel_width_hz,
                rolloff=rolloff,
            )
        except Exception:
            return False

    def coefficients_found(self) -> bool:
        return self._coefficients_found

    def get_record(self, us_idx: int) -> UsEqDataModel | None:
        return self.equalizer_data.get(us_idx)

    def to_dict(self) -> dict[int, dict]:
        return {k: v.model_dump() for k, v in self.equalizer_data.items()}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def _add_parsed(
        self,
        us_idx: int,
        payload: bytes,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"],
        coeff_endianness: Literal["little", "big", "auto"],
        preview_taps: int,
        channel_width_hz: BandwidthHz | None,
        rolloff: float,
    ) -> bool:
        if len(payload) < self.HEADER_SIZE:
            return False

        main_tap_location = payload[0]
        taps_per_symbol = payload[1]
        num_taps = payload[2]
        reserved = payload[3]

        if num_taps == 0:
            return False

        if num_taps > self.MAX_TAPS:
            return False

        expected_len = self.HEADER_SIZE + (num_taps * self.COMPLEX_TAP_SIZE)
        if len(payload) < expected_len:
            return False

        header_hex = payload[: self.HEADER_SIZE].hex(" ", 1).upper()
        payload_hex = payload[:expected_len].hex(" ", 1).upper()

        preview_taps_clamped = preview_taps
        if preview_taps_clamped < 0:
            preview_taps_clamped = 0
        if preview_taps_clamped > num_taps:
            preview_taps_clamped = num_taps

        preview_len = self.HEADER_SIZE + (preview_taps_clamped * self.COMPLEX_TAP_SIZE)
        payload_preview_hex = payload[:preview_len].hex(" ", 1).upper()

        taps_blob = payload[self.HEADER_SIZE : expected_len]
        taps = self._parse_taps(
            taps_blob,
            coeff_encoding=coeff_encoding,
            coeff_endianness=coeff_endianness,
        )

        metrics = self._build_metrics(taps)
        group_delay = self._build_group_delay(
            taps,
            channel_width_hz=channel_width_hz,
            taps_per_symbol=taps_per_symbol,
            rolloff=rolloff,
        )
        self.equalizer_data[us_idx] = UsEqDataModel(
            main_tap_location=main_tap_location,
            taps_per_symbol=taps_per_symbol,
            num_taps=num_taps,
            reserved=reserved,
            header_hex=header_hex,
            payload_hex=payload_hex,
            payload_preview_hex=payload_preview_hex,
            taps=taps,
            metrics=metrics,
            group_delay=group_delay,
        )

        self._coefficients_found = True
        return True

    def _parse_taps(
        self,
        data: bytes,
        *,
        coeff_encoding: Literal["four-nibble", "three-nibble", "auto"],
        coeff_endianness: Literal["little", "big", "auto"],
    ) -> list[UsEqTapModel]:
        taps: list[UsEqTapModel] = []
        step = self.COMPLEX_TAP_SIZE

        endian = coeff_endianness
        if endian == "auto":
            endian = self._detect_coeff_endianness(data)

        encoding = coeff_encoding
        if encoding == "auto":
            encoding = self._detect_coeff_encoding(data, coeff_endianness=endian)

        tap_count = len(data) // step
        for tap_idx in range(tap_count):
            base = tap_idx * step
            real_b = data[base : base + self.COEFF_BYTES]
            imag_b = data[base + self.COEFF_BYTES : base + step]

            real_u16 = int.from_bytes(real_b, byteorder=endian, signed=False)
            imag_u16 = int.from_bytes(imag_b, byteorder=endian, signed=False)

            real = self._decode_coeff(real_u16, coeff_encoding=encoding)
            imag = self._decode_coeff(imag_u16, coeff_encoding=encoding)

            magnitude = math.hypot(float(real), float(imag))
            if magnitude > 0.0:
                power_db = 10.0 * math.log10(magnitude * magnitude)
            else:
                power_db = None

            taps.append(
                UsEqTapModel(
                    real=real,
                    imag=imag,
                    magnitude=round(magnitude, 2),
                    magnitude_power_dB=(round(power_db, 2) if power_db is not None else None),
                    real_hex=real_b.hex().upper(),
                    imag_hex=imag_b.hex().upper(),
                )
            )

        return taps

    def _build_metrics(self, taps: list[UsEqTapModel]) -> EqualizerMetricsModel | None:
        if len(taps) != EqualizerMetrics.EXPECTED_TAP_COUNT:
            return None

        coefficients: list[PreEqAtdmaCoefficients] = [
            (RealInt(tap.real), ImginaryInt(tap.imag)) for tap in taps
        ]
        return EqualizerMetrics(coefficients=coefficients).to_model()

    def _build_group_delay(
        self,
        taps: list[UsEqTapModel],
        *,
        channel_width_hz: BandwidthHz | None,
        taps_per_symbol: int,
        rolloff: float,
    ) -> GroupDelayModel | None:
        if channel_width_hz is None:
            return None
        if len(taps) == 0:
            return None
        if taps_per_symbol <= 0:
            return None

        coefficients: list[PreEqAtdmaCoefficients] = [
            (RealInt(tap.real), ImginaryInt(tap.imag)) for tap in taps
        ]
        try:
            calculator = GroupDelayCalculator(
                channel_width_hz=channel_width_hz,
                taps_per_symbol=taps_per_symbol,
                rolloff=rolloff,
            )
            return calculator.compute(coefficients)
        except Exception:
            return None

    def _detect_coeff_endianness(self, data: bytes) -> Literal["little", "big"]:
        """
        Heuristic endianness detection.

        Many deployed pre-EQ taps are small-magnitude, so the MSB of each 16-bit word is often 0x00 (positive)
        or 0xFF (negative). We score both interpretations by counting how often the MSB matches {0x00, 0xFF}.
        """
        if len(data) < self.COMPLEX_TAP_SIZE:
            return "little"

        max_taps = self.AUTO_ENDIAN_SAMPLE_MAX_TAPS
        tap_count = len(data) // self.COMPLEX_TAP_SIZE
        if tap_count < max_taps:
            max_taps = tap_count

        good = (self.AUTO_ENDIAN_BYTE_GOOD_0, self.AUTO_ENDIAN_BYTE_GOOD_FF)

        score_little = 0
        score_big = 0

        for tap_idx in range(max_taps):
            base = tap_idx * self.COMPLEX_TAP_SIZE

            r0 = data[base]
            r1 = data[base + 1]
            i0 = data[base + 2]
            i1 = data[base + 3]

            if r1 in good:
                score_little += 1
            if i1 in good:
                score_little += 1

            if r0 in good:
                score_big += 1
            if i0 in good:
                score_big += 1

        if score_big > score_little:
            return "big"
        return "little"

    def _detect_coeff_encoding(
        self,
        data: bytes,
        *,
        coeff_endianness: Literal["little", "big"],
    ) -> Literal["four-nibble", "three-nibble"]:
        """
        Auto-select coefficient decoding:

        - If any coefficient uses the upper nibble (0xF000 mask != 0), assume 16-bit signed (four-nibble).
        - Otherwise, default to 12-bit signed (three-nibble), which matches the "universal" decoding guidance.
        """
        step = self.COMPLEX_TAP_SIZE
        tap_count = len(data) // step

        for tap_idx in range(tap_count):
            base = tap_idx * step
            real_b = data[base : base + self.COEFF_BYTES]
            imag_b = data[base + self.COEFF_BYTES : base + step]

            real_u16 = int.from_bytes(real_b, byteorder=coeff_endianness, signed=False)
            imag_u16 = int.from_bytes(imag_b, byteorder=coeff_endianness, signed=False)

            if (real_u16 & self.U16_MSN_MASK) != 0:
                return "four-nibble"
            if (imag_u16 & self.U16_MSN_MASK) != 0:
                return "four-nibble"

        return "three-nibble"

    def _decode_coeff(self, raw_u16: int, *, coeff_encoding: Literal["four-nibble", "three-nibble"]) -> int:
        match coeff_encoding:
            case "four-nibble":
                return self._decode_int16(raw_u16)
            case "three-nibble":
                return self._decode_int12(raw_u16)
            case _:
                raise ValueError(f"Unsupported coeff_encoding: {coeff_encoding}")

    def _decode_int16(self, raw_u16: int) -> int:
        value = raw_u16 & self.U16_MASK
        if value & self.I16_SIGN:
            return value - self.I16_RANGE
        return value

    def _decode_int12(self, raw_u16: int) -> int:
        value = raw_u16 & self.U12_MASK
        if value & self.I12_SIGN:
            return value - self.I12_RANGE
        return value

    def _hex_to_bytes_strict(self, payload_hex: str) -> bytes:
        text = payload_hex.strip()
        text = text.replace("Hex-STRING:", "")
        text = text.replace("0x", "")
        text = " ".join(text.split())

        if text == "":
            return b""

        for ch in text:
            if ch == " ":
                continue
            if "0" <= ch <= "9":
                continue
            if "a" <= ch <= "f":
                continue
            if "A" <= ch <= "F":
                continue
            return b""

        return bytes.fromhex(text)
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
from pypnm.lib.inet import Inet
from pypnm.lib.inet_utils import InetGenerate
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import (
    BandwidthHz,
    ChannelId,
    EntryIndex,
    FrequencyHz,
    InterfaceIndex,
)
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

    async def getDocsIf3CmStatusUsEqData(
        self,
        channel_widths: dict[int, BandwidthHz] | None = None,
    ) -> DocsEqualizerData:
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
                eq_bytes = Snmp_v2c.snmp_get_result_bytes([varbind])[0]
                if not eq_bytes:
                    continue
                self.logger.debug(f'idx: {us_idx} -> eq-data bytes: ({len(eq_bytes)})')
                channel_width_hz = channel_widths.get(us_idx) if channel_widths else None
                ded.add_from_bytes(us_idx, eq_bytes, channel_width_hz=channel_width_hz)

        except ValueError as e:
            self.logger.error(f"Failed to parse equalizer data. Error: {e}")
            return None

        if not ded.coefficients_found():
            self.logger.warning(
                "No upstream pre-equalization coefficients found. "
                "Ensure Pre-Equalization is enabled on the upstream interface(s).")

        return ded
# FILE: src/pypnm/api/routes/docs/if30/us/atdma/chan/stats/service.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

from pypnm.api.routes.common.classes.common_endpoint_classes.schema.base_connect_request import (
    SNMPConfig,
)
from pypnm.docsis.cable_modem import CableModem
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.types import (
    BandwidthHz,
    ChannelId,
    InetAddressStr,
    MacAddressStr,
    PowerdB,
    PowerdBmV,
)
from pypnm.pnm.analysis.us_drw import (
    DwrChannelPowerModel,
    DwrDynamicWindowRangeChecker,
    DwrWindowCheckModel,
)
from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData


class UsScQamChannelService:
    """
    Service for retrieving DOCSIS Upstream SC-QAM channel information and
    pre-equalization data from a cable modem using SNMP.

    Attributes:
        cm (CableModem): An instance of the CableModem class used to perform SNMP operations.
    """

    DEFAULT_DWR_WARNING_DB: PowerdB = PowerdB(6.0)
    DEFAULT_DWR_VIOLATION_DB: PowerdB = PowerdB(12.0)

    def __init__(self, mac_address: MacAddressStr,
                 ip_address: InetAddressStr,
                 snmp_config: SNMPConfig) -> None:
        """
        Initializes the service with a MAC and IP address.

        Args:
            mac_address (str): MAC address of the target cable modem.
            ip_address (str): IP address of the target cable modem.
        """
        self.cm = CableModem(mac_address=MacAddress(mac_address),
                             inet=Inet(ip_address),
                             write_community=snmp_config.snmp_v2c.community)

    async def get_upstream_entries(
        self,
        dwr_warning_db: PowerdB = DEFAULT_DWR_WARNING_DB,
        dwr_violation_db: PowerdB = DEFAULT_DWR_VIOLATION_DB,
    ) -> dict[str, object]:
        """
        Fetches DOCSIS Upstream SC-QAM channel entries.

        Returns:
            Dict[str, object]: Upstream channel entries with optional DWR evaluation summary.
        """
        entries = await self.cm.getDocsIfUpstreamChannelEntry()
        entry_dicts = [entry.model_dump() for entry in entries]

        channel_powers: list[DwrChannelPowerModel] = []
        for entry in entries:
            tx_power = entry.entry.docsIf3CmStatusUsTxPower
            if tx_power is None:
                continue
            channel_powers.append(
                DwrChannelPowerModel(
                    channel_id=ChannelId(entry.channel_id),
                    tx_power_dbmv=PowerdBmV(tx_power),
                )
            )

        dwr_check: DwrWindowCheckModel | None = None
        if len(channel_powers) >= DwrDynamicWindowRangeChecker.MIN_CHANNELS:
            try:
                checker = DwrDynamicWindowRangeChecker(
                    dwr_violation_db=dwr_violation_db,
                    dwr_warning_db=dwr_warning_db,
                )
                dwr_check = checker.evaluate(channel_powers)
            except Exception:
                dwr_check = None

        return {
            "entries": entry_dicts,
            "dwr_window_check": (dwr_check.model_dump() if dwr_check is not None else None),
        }

    async def get_upstream_pre_equalizations(self) ->  dict[int, dict]:
        """
        Fetches upstream pre-equalization coefficient data.

        Returns:
            List[dict]: A dictionary containing per-channel equalizer data with real, imag,
                        magnitude, and power (dB) for each tap.
        """
        entries_payload = await self.get_upstream_entries()
        channel_widths: dict[int, BandwidthHz] = {}
        for entry in entries_payload.get("entries", []):
            index = entry.get("index")
            entry_data = entry.get("entry") or {}
            channel_width = entry_data.get("docsIfUpChannelWidth")
            if isinstance(index, int) and isinstance(channel_width, int) and channel_width > 0:
                channel_widths[index] = BandwidthHz(channel_width)

        pre_eq_data: DocsEqualizerData = await self.cm.getDocsIf3CmStatusUsEqData(
            channel_widths=channel_widths
        )
        return pre_eq_data.to_dict()
# FILE: docs/api/fast-api/single/us/atdma/chan/pre-equalization.md
# DOCSIS 3.0 Upstream ATDMA Pre-Equalization

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Pre-Equalization Tap Data For Plant Analysis (Reflections, Group Delay, Pre-Echo).

## Endpoint

**POST** `/docs/if30/us/atdma/chan/preEqualization`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **object** keyed by the **SNMP table index** of each upstream channel.  
Each value contains decoded tap configuration, coefficients, metrics, and optional group delay.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": "Successfully retrieved upstream pre-equalization coefficients",
  "results": {
    "80": {
      "main_tap_location": 8,
      "taps_per_symbol": 1,
      "num_taps": 24,
      "reserved": 0,
      "header_hex": "08 01 18 00",
      "payload_hex": "08 01 18 00 00 00 00 01 00 03 FF FF FF FF 00 02 00 01",
      "payload_preview_hex": "08 01 18 00 00 00 00 01 00 03 FF FF FF FF 00 02 00 01",
      "taps": [
        { "real": 0, "imag": 1, "magnitude": 1.0, "magnitude_power_dB": 0.0, "real_hex": "0000", "imag_hex": "0001" },
        { "real": 3, "imag": -1, "magnitude": 3.16, "magnitude_power_dB": 10.0, "real_hex": "0003", "imag_hex": "FFFF" }
      ],
      "metrics": {
        "main_tap_energy": 4190209.0,
        "main_tap_nominal_energy": 8380418.0,
        "total_tap_energy": 4190713.0,
        "main_tap_ratio": 39.19,
        "frequency_response": {
          "fft_size": 24,
          "frequency_bins": [0.0, 0.041666666666666664, 0.08333333333333333],
          "magnitude": [2054.000243427444, 2025.9517291663806, 2030.7990565383996],
          "magnitude_power_db": [66.25200981462334, 66.13258187076737, 66.15333905939173],
          "magnitude_power_db_normalized": [0.0, -0.11942794385596756, -0.09867075523160906],
          "phase_radians": [-0.0004868548787686341, -1.8217247253384095, 2.620174402315228]
        }
      },
      "group_delay": {
        "channel_width_hz": 6400000,
        "rolloff": 0.25,
        "taps_per_symbol": 1,
        "symbol_rate": 5120000.0,
        "symbol_time_us": 0.1953125,
        "sample_period_us": 0.1953125,
        "fft_size": 24,
        "delay_samples": [6.956616231115412, 6.994905680977856, 7.001802249927044],
        "delay_us": [1.3587141076397289, 1.3661925158159873, 1.3675395019388759]
      }
    }
    /* ... other upstream channel indices elided ... */
  }
}
```

## Container Keys

| Key (top-level under `data`) | Type   | Description                                                       |
| ---------------------------- | ------ | ----------------------------------------------------------------- |
| `"80"`, `"81"`, …            | string | **SNMP table index** for the upstream channel row (OID instance). |

## Channel-Level Fields

| Field               | Type    | Description                                                 |
| ------------------- | ------- | ----------------------------------------------------------- |
| `main_tap_location` | integer | Location of the main tap (typically near the filter center) |
| `taps_per_symbol`   | integer | Taps per symbol from the pre-EQ header                      |
| `num_taps`          | integer | Total number of taps                                        |
| `reserved`          | integer | Reserved header byte                                        |
| `header_hex`        | string  | Header bytes in hex                                         |
| `payload_hex`       | string  | Full payload hex                                            |
| `payload_preview_hex` | string | Header plus a preview window of taps in hex                 |
| `taps`              | array   | Complex tap coefficients (real/imag pairs)                  |
| `metrics`           | object  | ATDMA pre-equalization key metrics when available           |
| `group_delay`       | object  | Group delay results when channel bandwidth is available     |

## Coefficient Object Fields

| Field                | Type  | Units | Description                          |
| -------------------- | ----- | ----- | ------------------------------------ |
| `real`               | int   | —     | Real part of the complex coefficient |
| `imag`               | int   | —     | Imaginary part of the coefficient    |
| `magnitude`          | float | —     | Magnitude of the complex tap         |
| `magnitude_power_dB` | float | dB    | Power of the tap in dB               |
| `real_hex`           | string | —    | Raw 2-byte real coefficient (hex)    |
| `imag_hex`           | string | —    | Raw 2-byte imag coefficient (hex)    |

## Notes

* Each top-level key under `data` is the DOCSIS **SNMP index** for an upstream SC-QAM (ATDMA) channel.
* Group delay is included only when the upstream channel bandwidth is available.
* Use tap shapes and main-tap offset to infer echo path delay and alignment health.
* Tap coefficients are signed integers; convert to floating-point as needed for analysis.
# FILE: docs/api/fast-api/single/us/atdma/chan/stats.md
# DOCSIS 3.0 Upstream ATDMA Channel Statistics

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Channel Statistics.

## Endpoint

**POST** `/docs/if30/us/atdma/chan/stats`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **object** with the upstream channel entries plus an optional DWR window evaluation summary. Each entry contains the SNMP table `index`, the upstream `channel_id`, and an `entry` with configuration, status, and (where available) raw pre-EQ data (`docsIf3CmStatusUsEqData`).

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "entries": [
      {
        "index": 80,
        "channel_id": 1,
        "entry": {
          "docsIfUpChannelId": 1,
          "docsIfUpChannelFrequency": 14600000,
          "docsIfUpChannelWidth": 6400000,
          "docsIfUpChannelModulationProfile": 0,
          "docsIfUpChannelSlotSize": 2,
          "docsIfUpChannelTxTimingOffset": 6436,
          "docsIfUpChannelRangingBackoffStart": 3,
          "docsIfUpChannelRangingBackoffEnd": 8,
          "docsIfUpChannelTxBackoffStart": 2,
          "docsIfUpChannelTxBackoffEnd": 6,
          "docsIfUpChannelType": 2,
          "docsIfUpChannelCloneFrom": 0,
          "docsIfUpChannelUpdate": false,
          "docsIfUpChannelStatus": 1,
          "docsIfUpChannelPreEqEnable": true,
          "docsIf3CmStatusUsTxPower": 49.0,
          "docsIf3CmStatusUsT3Timeouts": 0,
          "docsIf3CmStatusUsT4Timeouts": 0,
          "docsIf3CmStatusUsRangingAborteds": 0,
          "docsIf3CmStatusUsModulationType": 2,
          "docsIf3CmStatusUsEqData": "0x08011800ffff0003...00020001",
          "docsIf3CmStatusUsT3Exceededs": 0,
          "docsIf3CmStatusUsIsMuted": false,
          "docsIf3CmStatusUsRangingStatus": 4
        }
      },
      {
        "index": 81,
        "channel_id": 2,
        "entry": {
          "docsIfUpChannelId": 2,
          "docsIfUpChannelFrequency": 21000000,
          "docsIfUpChannelWidth": 6400000,
          "docsIfUpChannelModulationProfile": 0,
          "docsIfUpChannelSlotSize": 2,
          "docsIfUpChannelTxTimingOffset": 6436,
          "docsIfUpChannelRangingBackoffStart": 3,
          "docsIfUpChannelRangingBackoffEnd": 8,
          "docsIfUpChannelTxBackoffStart": 2,
          "docsIfUpChannelTxBackoffEnd": 6,
          "docsIfUpChannelType": 2,
          "docsIfUpChannelCloneFrom": 0,
          "docsIfUpChannelUpdate": false,
          "docsIfUpChannelStatus": 1,
          "docsIfUpChannelPreEqEnable": true,
          "docsIf3CmStatusUsTxPower": 48.5,
          "docsIf3CmStatusUsT3Timeouts": 0,
          "docsIf3CmStatusUsT4Timeouts": 0,
          "docsIf3CmStatusUsRangingAborteds": 0,
          "docsIf3CmStatusUsModulationType": 2,
          "docsIf3CmStatusUsEqData": "0x08011800ffff0001...0002",
          "docsIf3CmStatusUsT3Exceededs": 0,
          "docsIf3CmStatusUsIsMuted": false,
          "docsIf3CmStatusUsRangingStatus": 4
        }
      }
    ],
    "dwr_window_check": {
      "dwr_warning_db": 6.0,
      "dwr_violation_db": 12.0,
      "channel_count": 2,
      "min_power_dbmv": 48.5,
      "max_power_dbmv": 49.0,
      "spread_db": 0.5,
      "is_warning": false,
      "is_violation": false,
      "extreme_channel_ids": [1, 2]
    }
  }
}
```

## Data Fields

| Field              | Type   | Description                                      |
| ------------------ | ------ | ------------------------------------------------ |
| `entries`          | array  | Upstream channel entries (same as prior format). |
| `dwr_window_check` | object | DWR evaluation summary, or null when unavailable. |

## DWR Window Check Fields

| Field              | Type  | Units | Description |
| ------------------ | ----- | ----- | ----------- |
| `dwr_warning_db`   | float | dB    | Warning threshold for the DWR spread. |
| `dwr_violation_db` | float | dB    | Violation threshold for the DWR spread. |
| `channel_count`    | int   | —     | Number of channels included in the evaluation. |
| `min_power_dbmv`   | float | dBmV  | Minimum transmit power across channels. |
| `max_power_dbmv`   | float | dBmV  | Maximum transmit power across channels. |
| `spread_db`        | float | dB    | Power spread across channels (max-min). |
| `is_warning`       | bool  | —     | True when warning_db < spread_db <= violation_db. |
| `is_violation`     | bool  | —     | True when spread_db > violation_db. |
| `extreme_channel_ids` | array | —  | Channel IDs that define the min/max spread. |

## Channel Fields

| Field        | Type | Description                                                                 |
| ------------ | ---- | --------------------------------------------------------------------------- |
| `index`      | int  | **SNMP table index** (OID instance) for this channel’s row in the CM table. |
| `channel_id` | int  | DOCSIS upstream SC-QAM (ATDMA) logical channel ID.                          |

## Entry Fields

| Field                                | Type   | Units | Description                                             |
| ------------------------------------ | ------ | ----- | ------------------------------------------------------- |
| `docsIfUpChannelId`                  | int    | —     | Upstream channel ID (mirrors logical ID).               |
| `docsIfUpChannelFrequency`           | int    | Hz    | Center frequency.                                       |
| `docsIfUpChannelWidth`               | int    | Hz    | Channel width.                                          |
| `docsIfUpChannelModulationProfile`   | int    | —     | Modulation profile index.                               |
| `docsIfUpChannelSlotSize`            | int    | —     | Slot size (minislot units).                             |
| `docsIfUpChannelTxTimingOffset`      | int    | —     | Transmit timing offset (implementation-specific units). |
| `docsIfUpChannelRangingBackoffStart` | int    | —     | Initial ranging backoff window start.                   |
| `docsIfUpChannelRangingBackoffEnd`   | int    | —     | Initial ranging backoff window end.                     |
| `docsIfUpChannelTxBackoffStart`      | int    | —     | Data/backoff start window.                              |
| `docsIfUpChannelTxBackoffEnd`        | int    | —     | Data/backoff end window.                                |
| `docsIfUpChannelType`                | int    | —     | Channel type enum (e.g., `2` = ATDMA).                  |
| `docsIfUpChannelCloneFrom`           | int    | —     | Clone source channel (if used).                         |
| `docsIfUpChannelUpdate`              | bool   | —     | Indicates a pending/active update.                      |
| `docsIfUpChannelStatus`              | int    | —     | Operational status enum.                                |
| `docsIfUpChannelPreEqEnable`         | bool   | —     | Whether pre-equalization is enabled.                    |
| `docsIf3CmStatusUsTxPower`           | float  | dBmV  | Upstream transmit power.                                |
| `docsIf3CmStatusUsT3Timeouts`        | int    | —     | T3 timeouts counter.                                    |
| `docsIf3CmStatusUsT4Timeouts`        | int    | —     | T4 timeouts counter.                                    |
| `docsIf3CmStatusUsRangingAborteds`   | int    | —     | Aborted ranging attempts.                               |
| `docsIf3CmStatusUsModulationType`    | int    | —     | Modulation type enum.                                   |
| `docsIf3CmStatusUsEqData`            | string | hex   | Raw pre-EQ coefficient payload (hex string; raw octets). |
| `docsIf3CmStatusUsT3Exceededs`       | int    | —     | Exceeded T3 attempts.                                   |
| `docsIf3CmStatusUsIsMuted`           | bool   | —     | Whether the upstream transmitter is muted.              |
| `docsIf3CmStatusUsRangingStatus`     | int    | —     | Ranging state enum.                                     |

## Notes

* `docsIf3CmStatusUsEqData` contains the raw equalizer payload; decode to taps (location, magnitude, phase) in analysis workflows.
* The hex string preserves original SNMP octets (for example `FF` stays `FF`, not UTF-8 encoded).
* Use the combination of `TxPower`, timeout counters, and ranging status to corroborate upstream health with pre-EQ shape.
* Channels are discovered automatically; no channel list is required in the request.
* DWR warning and violation thresholds are evaluated against the min/max power spread for all channels returned.
# DOCSIS 3.0 Upstream ATDMA Pre-Equalization

Provides Access To DOCSIS 3.0 Upstream SC-QAM (ATDMA) Pre-Equalization Tap Data For Plant Analysis (Reflections, Group Delay, Pre-Echo).

## Endpoint

**POST** `/docs/if30/us/scqam/chan/preEqualization`

## Request

Use the SNMP-only format: [Common → Request](../../../../common/request.md)  
TFTP parameters are not required.

## Response

This endpoint returns the standard envelope described in [Common → Response](../../../../common/response.md) (`mac_address`, `status`, `message`, `data`).

`data` is an **object** keyed by the **SNMP table index** of each upstream channel.  
Each value contains decoded tap configuration and coefficient arrays.

### Abbreviated Example

```json
{
  "mac_address": "aa:bb:cc:dd:ee:ff",
  "status": 0,
  "message": null,
  "data": {
    "80": {
      "main_tap_location": 8,
      "forward_taps_per_symbol": 1,
      "num_forward_taps": 24,
      "num_reverse_taps": 0,
      "forward_coefficients": [
        { "real": 0, "imag": 4, "magnitude": 4.0, "magnitude_power_dB": 12.04 },
        { "real": 2, "imag": -15425, "magnitude": 15425.0, "magnitude_power_dB": 83.76 },
        { "real": -15426, "imag": 1, "magnitude": 15426.0, "magnitude_power_dB": 83.77 }
        /* ... taps elided ... */
      ],
      "reverse_coefficients": []
    },
    "81": {
      "main_tap_location": 8,
      "forward_taps_per_symbol": 1,
      "num_forward_taps": 24,
      "num_reverse_taps": 0,
      "forward_coefficients": [
        { "real": -15425, "imag": -15425, "magnitude": 21814.24, "magnitude_power_dB": 86.77 },
        { "real": 1, "imag": 3, "magnitude": 3.16, "magnitude_power_dB": 10.0 },
        { "real": 1, "imag": -15425, "magnitude": 15425.0, "magnitude_power_dB": 83.76 }
        /* ... taps elided ... */
      ],
      "reverse_coefficients": []
    }
    /* ... other upstream channel indices elided ... */
  }
}
```

## Container Keys

| Key (top-level under `data`) | Type   | Description                                                       |
| ---------------------------- | ------ | ----------------------------------------------------------------- |
| `"80"`, `"81"`, …            | string | **SNMP table index** for the upstream channel row (OID instance). |

## Channel-Level Fields

| Field                     | Type    | Description                                                 |
| ------------------------- | ------- | ----------------------------------------------------------- |
| `main_tap_location`       | integer | Location of the main tap (typically near the filter center) |
| `forward_taps_per_symbol` | integer | Number of forward taps per symbol                           |
| `num_forward_taps`        | integer | Total forward equalizer taps                                |
| `num_reverse_taps`        | integer | Total reverse equalizer taps (often `0` for ATDMA)          |
| `forward_coefficients`    | array   | Complex tap coefficients applied in forward direction       |
| `reverse_coefficients`    | array   | Complex tap coefficients applied in reverse direction       |
| `metrics`                 | object  | Derived equalizer metrics and frequency response            |

## Coefficient Object Fields

| Field                | Type  | Units | Description                          |
| -------------------- | ----- | ----- | ------------------------------------ |
| `real`               | int   | —     | Real part of the complex coefficient |
| `imag`               | int   | —     | Imaginary part of the coefficient    |
| `magnitude`          | float | —     | Magnitude of the complex tap         |
| `magnitude_power_dB` | float | dB    | Power of the tap in dB               |

## Equalizer Metrics Fields

| Field                           | Type  | Units | Description                                   |
| ------------------------------- | ----- | ----- | --------------------------------------------- |
| `main_tap_energy`               | float | —     | Main tap energy (MTE)                         |
| `main_tap_nominal_energy`       | float | —     | Main tap nominal energy (MTNE)                |
| `pre_main_tap_energy`           | float | —     | Pre-main tap energy (PreMTE)                  |
| `post_main_tap_energy`          | float | —     | Post-main tap energy (PostMTE)                |
| `total_tap_energy`              | float | —     | Total tap energy (TTE)                        |
| `main_tap_compression`          | float | dB    | Main tap compression (MTC)                    |
| `main_tap_ratio`                | float | dB    | Main tap ratio (MTR)                          |
| `non_main_tap_energy_ratio`     | float | dB    | Non-main tap to total energy ratio (NMTER)    |
| `pre_main_tap_total_energy_ratio` | float | dB  | Pre-main tap to total energy ratio (PreMTTER) |
| `post_main_tap_total_energy_ratio` | float | dB | Post-main tap to total energy ratio (PostMTTER) |
| `pre_post_energy_symmetry_ratio`  | float | dB | Pre-post energy symmetry ratio (PPESR)        |
| `pre_post_tap_symmetry_ratio`     | float | dB | Pre-post tap symmetry ratio (PPTSR)           |
| `frequency_response`              | object | —  | Frequency response derived from tap coefficients |

## Frequency Response Fields

| Field                         | Type          | Units | Description                                         |
| ----------------------------- | ------------- | ----- | --------------------------------------------------- |
| `fft_size`                    | integer       | —     | FFT size used to compute the response               |
| `frequency_bins`              | array[float]  | —     | Normalized bins from 0 to 1                         |
| `magnitude`                   | array[float]  | —     | Magnitude response per bin                          |
| `magnitude_power_db`          | array[float]  | dB    | Magnitude power per bin                             |
| `magnitude_power_db_normalized` | array[float] | dB    | Magnitude power normalized to the DC bin (bin 0)    |
| `phase_radians`               | array[float]  | rad   | Phase response per bin                              |

## Notes

* Each top-level key under `data` is the DOCSIS **SNMP index** for an upstream SC-QAM (ATDMA) channel.
* Forward taps pre-compensate the channel (handling pre-echo/echo paths); reverse taps are uncommon in ATDMA.
* Use tap shapes and main-tap offset to infer echo path delay and alignment health.
* Tap coefficients are signed integers; convert to floating-point as needed for analysis.
* `magnitude_power_db_normalized` references the DC bin (bin 0) as 0 dB when non-zero.
# FILE: docs/api/fast-api/single/us/ofdma/stats.md
# DOCSIS 3.1 Upstream OFDMA Channel Statistics

This API provides visibility into the configuration and runtime status of upstream OFDMA channels from DOCSIS 3.1 cable modems. It includes key metrics such as active subcarrier layout, transmit power, cyclic prefix configuration, and pre-equalization status. Additionally, it tracks upstream timeout counters (T3, T4) and ranging outcomes to help diagnose impairments and channel access issues.

Use this endpoint to support PNM workflows, particularly when analyzing power levels, ranging stability, and OFDMA symbol behavior under varying network conditions.

## Endpoint

**POST** `/docs/if31/us/ofdma/channel/stats`

Retrieves statistics and configuration parameters for upstream OFDMA channels from a DOCSIS 3.1 cable modem. This includes subcarrier layout, transmit power, and upstream timing-related error counters.


## Request Body (JSON)

### Request Fields

| Field          | Type   | Description                       |
| -------------- | ------ | --------------------------------- |
| `mac_address`  | string | MAC address of the cable modem    |
| `ip_address`   | string | IP address of the cable modem     |
| `snmp`         | object | SNMPv2c or SNMPv3 configuration   |
| `snmp.snmpV2C` | object | SNMPv2c options (`community`)     |
| `snmp.snmpV3`  | object | SNMPv3 options (auth & priv keys) |

```json
{
  "cable_modem": {
	"mac_address": "aa:bb:cc:dd:ee:ff",
	"ip_address": "192.168.0.100",
  "snmp": {
    "snmpV2C": {
      "community": "private"
    },
    "snmpV3": {
      "username": "string",
      "securityLevel": "noAuthNoPriv",
      "authProtocol": "MD5",
      "authPassword": "string",
      "privProtocol": "DES",
      "privPassword": "string"
    }
  }
}
```


## Response Body (JSON)

```json
[
  {
    "index": <SNMP_INDEX>,
    "channel_id": <CHANNEL_ID>,
    "entry": {
      "docsIf31CmUsOfdmaChanChannelId": 42,
      "docsIf31CmUsOfdmaChanConfigChangeCt": 1,
      "docsIf31CmUsOfdmaChanSubcarrierZeroFreq": 104800000,
      "docsIf31CmUsOfdmaChanFirstActiveSubcarrierNum": 74,
      "docsIf31CmUsOfdmaChanLastActiveSubcarrierNum": 1969,
      "docsIf31CmUsOfdmaChanNumActiveSubcarriers": 1896,
      "docsIf31CmUsOfdmaChanSubcarrierSpacing": 50,
      "docsIf31CmUsOfdmaChanCyclicPrefix": 192,
      "docsIf31CmUsOfdmaChanRollOffPeriod": 128,
      "docsIf31CmUsOfdmaChanNumSymbolsPerFrame": 10,
      "docsIf31CmUsOfdmaChanTxPower": 17.1,
      "docsIf31CmUsOfdmaChanPreEqEnabled": true,
      "docsIf31CmStatusOfdmaUsT3Timeouts": 0,
      "docsIf31CmStatusOfdmaUsT4Timeouts": 0,
      "docsIf31CmStatusOfdmaUsRangingAborteds": 0,
      "docsIf31CmStatusOfdmaUsT3Exceededs": 0,
      "docsIf31CmStatusOfdmaUsIsMuted": false,
      "docsIf31CmStatusOfdmaUsRangingStatus": "4"
    }
  }
]
```


## Response Field Highlights

| Field                                           | Type  | Description                                     |
| ----------------------------------------------- | ----- | ----------------------------------------------- |
| `docsIf31CmUsOfdmaChanChannelId`                | int   | Upstream channel ID                             |
| `docsIf31CmUsOfdmaChanConfigChangeCt`           | int   | Count of configuration changes since modem boot |
| `docsIf31CmUsOfdmaChanSubcarrierZeroFreq`       | int   | Frequency of subcarrier index 0 (Hz)            |
| `docsIf31CmUsOfdmaChanFirstActiveSubcarrierNum` | int   | First active subcarrier index                   |
| `docsIf31CmUsOfdmaChanLastActiveSubcarrierNum`  | int   | Last active subcarrier index                    |
| `docsIf31CmUsOfdmaChanNumActiveSubcarriers`     | int   | Total active subcarriers                        |
| `docsIf31CmUsOfdmaChanSubcarrierSpacing`        | int   | Subcarrier spacing in Hz                        |
| `docsIf31CmUsOfdmaChanCyclicPrefix`             | int   | Cyclic prefix duration                          |
| `docsIf31CmUsOfdmaChanRollOffPeriod`            | int   | Roll-off period                                 |
| `docsIf31CmUsOfdmaChanNumSymbolsPerFrame`       | int   | Number of OFDMA symbols per frame               |
| `docsIf31CmUsOfdmaChanTxPower`                  | float | Transmit power in dBm                           |
| `docsIf31CmUsOfdmaChanPreEqEnabled`             | bool  | Whether pre-equalization is enabled             |
| `docsIf31CmStatusOfdmaUsT3Timeouts`             | int   | T3 timeout count                                |
| `docsIf31CmStatusOfdmaUsT4Timeouts`             | int   | T4 timeout count                                |
| `docsIf31CmStatusOfdmaUsRangingAborteds`        | int   | Number of aborted ranging attempts              |
| `docsIf31CmStatusOfdmaUsT3Exceededs`            | int   | Number of times T3 retries exceeded             |
| `docsIf31CmStatusOfdmaUsIsMuted`                | bool  | Indicates if the upstream is muted              |
| `docsIf31CmStatusOfdmaUsRangingStatus`          | str   | Current ranging status (e.g., `4` = success)    |


## Notes

* Use this endpoint to monitor upstream channel state, power, and timeouts.
* Useful for diagnosing access failures, ranging issues, or transmit mismatches.
* Each response object corresponds to a separate upstream OFDMA channel.
# FILE: docs/api/fast-api/single/ds/ofdm/mer-margin.md
# OFDM MER Margin

The purpose of this item is to provide an estimate of the MER margin available on the downstream data channel with respect to a modulation profile. The profile may be a profile that the modem has already been assigned or a candidate profile. This is similar to the MER Margin reported in the OPT-RSP Message \[MULPIv3.1].

The CM calculates the Required Average MER for the profile based on the bit loading for the profile and the Required MER per Modulation Order provided in the CmDsOfdmRequiredQamMer table. For profiles with mixed modulation orders, this value is computed as an arithmetic mean of the required MER values for each non-excluded subcarrier in the Modulated Spectrum. The CM then measures the RxMER per subcarrier and calculates the Average MER for the Active Subcarriers used in the Profile and stores the value as MeasuredAvgMer. The Operator may also compute the value for Required Average MER for the profile and set that value for the test.

The CM also counts the number of MER per Subcarrier values that are below the threshold determined by the CmDsOfdmRequiredQamMer and the ThrshldOffset. The CM reports that value as NumSubcarriersBelowThrshld.

This table will have a row for each ifIndex for the modem.

## Table of Contents

* [Get Measurement](#get-measurement)

---

## Get Measurement

### Endpoint

**POST** `/docs/pnm/ds/ofdm/merMargin/getMeasurement`

Initiates a MER margin measurement on a DOCSIS 3.1 downstream OFDM profile.

### Request Body (JSON)

```json
{
  "cable_modem": {
  "mac_address": "aa:bb:cc:dd:ee:ff", 
  "ip_address": "192.168.0.100",
  "snmp": {
    "snmpV2C": {
      "community": "private"
    },
    "snmpV3": {
      "username": "string",
      "securityLevel": "noAuthNoPriv",
      "authProtocol": "MD5",
      "authPassword": "string",
      "privProtocol": "DES",
      "privPassword": "string"
    }
  }
}
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
# FILE: docs/install/development.md
# Development Install (Docker + kind)

Note: Docker and Kubernetes workflows are supported on Linux. macOS users should not use
the Docker/kind paths in this guide.

Use this when you want a local environment that can run the release smoke tests.

This option installs:
- Docker Engine + Compose (via `tools/docker/install-docker-ubuntu.sh`)
- kind + kubectl (via `tools/k8s/pypnm_kind_vm_bootstrap.sh`)

Tested on Ubuntu 22.04/24.04.

## Ubuntu (22.04/24.04)

From the repo root:

```bash
./install.sh --development
```

If you are re-running on a machine with a previous install, consider:

```bash
./install.sh --clean --development
```

### Notes

- Requires sudo and network access (for package installs and downloads).
- Docker may need to be started after install:

```bash
sudo systemctl start docker
```

- For non-sudo Docker access:

```bash
sudo usermod -aG docker "$USER"
```

Log out and back in for group changes to apply.

## Other OS

`--development` currently installs Docker automatically only on Ubuntu (apt-get).
On other platforms, install Docker manually first, then re-run:

```bash
./install.sh --development
```

This will still install kind + kubectl.
# FILE: docs/docker/install.md
# PyPNM Docker Install & Usage

Note: Docker workflows are supported on Linux hosts. macOS users should not use
these Docker-specific instructions.

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
TAG="v1.0.53.0"
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
TAG="v1.0.53.0"
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
# FILE: docs/kubernetes/pypnm-deploy.md
# PyPNM on Kubernetes (kind)

Note: Kubernetes (kind) workflows are supported on Linux hosts. macOS users should not
use this guide.

This walkthrough uses the manifests in `deploy/kubernetes/`. Start by installing kind and creating a cluster using [Local Kubernetes (kind) install](kind-install.md).

## Repo toolkit usage (recommended)

Use the toolkit to create a cluster and deploy from GHCR or local builds:

```bash
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source ghcr --tag TAG_VALUE --replicas 1
```

Add `--namespace` when you want multiple isolated instances (for example, one PyPNM per CMTS):

```bash
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source ghcr --tag TAG_VALUE --replicas 1 --namespace pypnm-cmts-a
```

If Docker or kubectl permissions require it, the toolkit will re-run itself with `sudo`.

## Script-only deploy (no repo clone)

This workflow pulls the manifests from GitHub and deploys the GHCR image directly.

```bash
curl -fsSL https://raw.githubusercontent.com/PyPNMApps/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \\
  -o /tmp/pypnm_k8s_remote_deploy.sh
TAG="v1.0.53.0"
NAMESPACE="pypnm-cmts-a"

bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1
```

Local image:

```bash
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source local --replicas 1
```

Teardown:

```bash
tools/k8s/pypnm_k8s_toolkit.sh --teardown --delete-cluster
```

## Diagram

![kind layout](../images/kubernetes/pypnm-kind.svg)

## Build and load a local image

```bash
docker build -t pypnm:local --build-arg PYTHON_VERSION=3.12 .
kind load docker-image pypnm:local --name pypnm-dev
```

## Apply the manifests

```bash
kubectl apply -k deploy/kubernetes
kubectl get pods
```

## Health check

```bash
kubectl port-forward deploy/pypnm-api 8000:8000
curl -i http://127.0.0.1:8000/health
```

## Config overrides (non-interactive)

Create a patch configmap:

```bash
kubectl create configmap pypnm-config-patch \
  --from-file=patch.json=/path/to/patch.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then add an initContainer to apply the patch into `/app/config/system.json`:

```yaml
initContainers:
  - name: config-apply
    image: pypnm:local
    command: ["python", "/app/tools/system_config/apply_config.py"]
    args:
      - "--input"
      - "/config-patch/patch.json"
      - "--config"
      - "/config/system.json"
    volumeMounts:
      - name: config-patch
        mountPath: /config-patch
      - name: pypnm-config
        mountPath: /config
volumes:
  - name: config-patch
    configMap:
      name: pypnm-config-patch
  - name: pypnm-config
    emptyDir: {}
```
# FILE: docs/system/pnm-file-retrieval/tftp.md
# TFTP PNM File Retrieval Setup (Config Menu)

This example shows how to configure **TFTP-based PNM file retrieval** using the
interactive `config-menu` helper. In this scenario, `localhost` is selected as
the TFTP host, which means the TFTP server and PyPNM are running on the same box.
PyPNM will still use the TFTP protocol to download PNM files for analysis.

The `remote_dir` is the directory on the TFTP server where PNM files are stored
and served. Leaving it empty (`""`) uses the TFTP server's default root
(often something like `/srv/tftp`, depending on your server configuration).

```shell
(.env) PyPNM$ config-menu

PyPNM System Configuration Menu
================================
Select an option:
  1) Edit FastApiRequestDefault
  2) Edit SNMP
  3) Edit PnmBulkDataTransfer
  4) Edit PnmFileRetrieval (retrieval_method only)
  5) Edit Logging
  6) Edit TestMode
  7) Run PnmFileRetrieval Setup (directory initialization)
  q) Quit
Enter selection: 7

Running: PyPNM/tools/pnm/pnm_file_retrieval_setup.py

INFO PnmFileRetrievalConfigurator: Using configuration file: PyPNM/src/pypnm/settings/system.json
INFO PnmFileRetrievalConfigurator: Created backup: PyPNM/src/pypnm/settings/system.bak.1765155200.json

Select PNM File Retrieval Method:
  1) local  - Copy from local src_dir
  2) tftp   - Download from TFTP server
  3) sftp   - Download from SFTP server
  q) Quit   - Exit without changes

Enter choice [1-4 or q to quit]: 2
INFO PnmFileRetrievalConfigurator: Selected retrieval method: tftp
Enter TFTP host [localhost]:
Enter TFTP port for localhost [69]:
Enter TFTP timeout seconds [5]:
Enter TFTP remote_dir []:
INFO PnmFileRetrievalConfigurator: Configured TFTP host=localhost port=69 remote_dir=
INFO PnmFileRetrievalConfigurator: PNM file retrieval configuration complete.

Script completed successfully.


PyPNM System Configuration Menu
================================
Select an option:
  1) Edit FastApiRequestDefault
  2) Edit SNMP
  3) Edit PnmBulkDataTransfer
  4) Edit PnmFileRetrieval (retrieval_method only)
  5) Edit Logging
  6) Edit TestMode
  7) Run PnmFileRetrieval Setup (directory initialization)
  q) Quit
Enter selection: q
Exiting System Configuration Menu.
(.env) PyPNM$
```

If PNM file retrieval fails with TFTP errors (for example,
`TFTP_PNM_FILE_FETCH_ERROR` in the logs), verify:

1. The TFTP service is running on `localhost` and listening on UDP port 69.

Note: macOS includes a TFTP client but does not ship a native TFTP server. Use a
third-party daemon if you need a local TFTP server on macOS.
2. The TFTP server is allowed to **serve** files (download) as well as accept
   uploads from the cable modem. Some configurations are upload-only.
3. The TFTP root or `remote_dir` actually contains the PNM files that the CM
   is writing.
4. Local firewall rules (or SELinux/AppArmor) are not blocking TFTP traffic
   between the CM and the PyPNM host, or between PyPNM and `localhost` itself.

## Quick TFTP Health Check On Ubuntu (localhost)

The following steps assume a typical Ubuntu environment where `tftpd-hpa` is
used and the TFTP root is `/srv/tftp`. Adjust paths if your configuration
differs.

1. Install the TFTP server (if not already installed):

   ```bash
   sudo apt update
   sudo apt install -y tftpd-hpa
   ```

2. Check that the TFTP service is running:

   ```bash
   systemctl status tftpd-hpa
   ```

   Look for `active (running)`. If it is not running, start it:

   ```bash
   sudo systemctl start tftpd-hpa
   sudo systemctl enable tftpd-hpa
   ```

3. Confirm the TFTP root directory:

   ```bash
   sudo cat /etc/default/tftpd-hpa
   ```

   ```shell

    (.env) PyPNM$ sudo cat /etc/default/tftpd-hpa
    [sudo] password for dev01: 
    # /etc/default/tftpd-hpa

    TFTP_USERNAME="tftp"
    TFTP_DIRECTORY="/srv/tftp"
    TFTP_ADDRESS=":69"
    TFTP_OPTIONS="--secure --create"

   ```

   Check the `TFTP_DIRECTORY` line. This directory must match what you expect
   for `remote_dir` (or be consistent with leaving `remote_dir` empty when it
   points to the server root). This is where the CM will write PNM files and
   where PyPNM will try to download them from.

4. Create a small test file in the TFTP directory (example assumes `/srv/tftp`):

   ```bash
   echo "pypnm-tftp-test" | sudo tee /srv/tftp/pypnm-test.txt
   sudo chmod 644 /srv/tftp/pypnm-test.txt
   ```

5. Install a TFTP client and test a download from `localhost`:

   ```bash
   sudo apt install -y tftp
   cd /tmp
   
   tftp localhost
   get pypnm-test.txt
   quit
   ```

   After the command, verify the file:

   ```bash
   cat /tmp/pypnm-test.txt
   ```

   You should see the contents `pypnm-tftp-test`. If this works, the TFTP
   server is able to **serve** files on `localhost`, which is the same path
   PyPNM will use when `host=localhost` and `method=tftp` are configured.

6. If the test fails, re-check:

   - TFTP service status (`systemctl status tftpd-hpa`)
   - The configured `TFTP_DIRECTORY` vs the directory where you put the file
   - Local firewall rules (for example, with UFW):

     ```bash
     sudo ufw status
     sudo ufw allow 69/udp
     ```

   Once the manual TFTP test succeeds, PyPNM should be able to retrieve PNM
   files from the same TFTP root/`remote_dir`.
# FILE: tests/test_docs_equalizer_group_delay.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Maurice Garcia

from __future__ import annotations

from pypnm.lib.types import BandwidthHz
from pypnm.pnm.data_type.DocsEqualizerData import DocsEqualizerData


def _encode_i16(value: int) -> bytes:
    if value < 0:
        value = (1 << 16) + value
    return value.to_bytes(2, byteorder="little", signed=False)


def _build_payload(num_taps: int, taps_per_symbol: int) -> bytes:
    header = bytes([8, taps_per_symbol, num_taps, 0])
    taps = bytearray()
    for _ in range(num_taps):
        taps.extend(_encode_i16(1))
        taps.extend(_encode_i16(0))
    return header + taps


def test_group_delay_included_with_channel_width() -> None:
    payload = _build_payload(num_taps=24, taps_per_symbol=1)
    ded = DocsEqualizerData()

    added = ded.add_from_bytes(80, payload, channel_width_hz=BandwidthHz(1_600_000))
    assert added is True

    record = ded.get_record(80)
    assert record is not None
    assert record.group_delay is not None
    assert int(record.group_delay.channel_width_hz) == 1_600_000
    assert record.group_delay.taps_per_symbol == 1
    assert record.group_delay.fft_size == 24
    assert len(record.group_delay.delay_samples) == 24
    assert len(record.group_delay.delay_us) == 24


def test_group_delay_missing_without_channel_width() -> None:
    payload = _build_payload(num_taps=24, taps_per_symbol=1)
    ded = DocsEqualizerData()

    added = ded.add_from_bytes(81, payload)
    assert added is True

    record = ded.get_record(81)
    assert record is not None
    assert record.group_delay is None
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


def _run_ruff_check(skip_failures: bool) -> None:
    """Run ruff check against src before finalizing the release."""
    if shutil.which("ruff") is None:
        print("ERROR: ruff is not available in PATH. Aborting release.", file=sys.stderr)
        _print_status("Ruff check", "fail")
        if skip_failures:
            return
        sys.exit(1)

    print("Running ruff check (src)...")
    result = _run(["ruff", "check", "src"], check=False, label="ruff-check")
    if result.returncode != 0:
        print("ERROR: ruff check failed. Aborting release.", file=sys.stderr)
        _print_status("Ruff check", "fail")
        if skip_failures:
            return
        sys.exit(result.returncode)
    _print_status("Ruff check", "pass")


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
        "--ruff-check-skip-failures",
        action="store_true",
        help="Allow release to continue if ruff check fails.",
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
    ruff_check_skip_failures: bool = args.ruff_check_skip_failures
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

    _run_ruff_check(ruff_check_skip_failures)

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
